#!/usr/bin/env python3
"""Run the Research OS v0.3 release gate as one fail-closed command."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "tests/fixtures/releases/v0.3.0/manifest.json"
AUTHORITY_TESTS = (
    "tests/test_m1a_evidence_e2e.py::test_m1a_changed_surfaces_keep_authority_null",
    "tests/test_m1b_manifest_oracle.py::test_every_manifest_case_has_an_executable_expectation_binding[authority-null-changed-surfaces]",
    "tests/test_m1c_manifest_oracle.py::test_every_manifest_case_has_an_operation_only_expectation_binding[proposal-authority-null-surfaces]",
    "tests/test_m1d_manifest_oracle.py::test_all_frozen_authority_values_are_null",
    "tests/test_m1d_manifest_oracle.py::test_ten_live_public_surfaces_keep_authority_present_and_null",
    "tests/test_m1e_release_gate.py",
)
DOC_REQUIREMENTS = {
    "README.md": ("0.3.0", "Context v3", "--schema-version 2", "managed Research OS 0.2.0", "--upgrade", "recovery_backup"),
    "docs/architecture.md": ("0.3.0", "Context v3", "tokenless", "managed 0.2.0", "--upgrade", "recovery_backup"),
    "docs/agent-usage.md": ("0.3.0", "Context v3", "--schema-version 2", "managed 0.2.0", "--upgrade", "recovery_backup"),
    "src/research_os/resources/research-os/SKILL.md": ("0.3.0", "Context v3", "--schema-version 2", "managed 0.2.0", "--upgrade", "recovery_backup"),
}
PRODUCT_MULTI_AGENT_MARKERS = ("multi_agent", "multi-agent", "agent_swarm", "role_swarm")


class ReleaseGateError(RuntimeError):
    """A release conjunct did not pass."""


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ReleaseGateError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _strict_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda value: (_ for _ in ()).throw(
                ReleaseGateError(f"non-finite JSON number: {value}")
            ),
        )
    except (OSError, ValueError) as exc:
        raise ReleaseGateError(f"cannot load release manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseGateError("release manifest must be an object")
    return value


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ReleaseGateError(message)


def _run(command: list[str]) -> str:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        rendered = " ".join(command)
        raise ReleaseGateError(
            f"command failed ({completed.returncode}): {rendered}\n{output[-6000:]}"
        )
    return output


def _pytest_counts(output: str) -> tuple[int, int]:
    passed = re.findall(r"(?<!\d)(\d+) passed", output)
    subtests = re.findall(r"(?<!\d)(\d+) subtests passed", output)
    _require(bool(passed), "pytest output has no passed-test count")
    _require(bool(subtests), "pytest output has no passed-subtest count")
    return int(passed[-1]), int(subtests[-1])


def _python_tree() -> dict[str, object]:
    root = ROOT / "src/research_os"
    files = sorted(root.rglob("*.py"))
    digest = hashlib.sha256()
    for path in files:
        relative = path.relative_to(root).as_posix().encode()
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big") + relative)
        digest.update(len(content).to_bytes(8, "big") + content)
    return {"file_count": len(files), "sha256": digest.hexdigest()}


def _control_tree(path: Path) -> dict[str, object]:
    if not path.exists():
        return {"exists": False, "entry_count": 0, "sha256": hashlib.sha256(b"absent").hexdigest()}
    _require(path.is_dir() and not path.is_symlink(), f"unsafe external control root: {path}")
    digest = hashlib.sha256()
    entries = 0
    for current, directories, files in os.walk(path, followlinks=False):
        directories.sort()
        files.sort()
        for name in [*directories, *files]:
            item = Path(current) / name
            _require(not item.is_symlink(), f"external control symlink is forbidden: {item}")
            relative = item.relative_to(path).as_posix().encode()
            kind = b"d" if item.is_dir() else b"f"
            _require(kind == b"d" or item.is_file(), f"unsupported external entry: {item}")
            content = b"" if kind == b"d" else item.read_bytes()
            digest.update(kind + len(relative).to_bytes(8, "big") + relative)
            digest.update(len(content).to_bytes(8, "big") + content)
            entries += 1
    return {"exists": True, "entry_count": entries, "sha256": digest.hexdigest()}


def _external_snapshots(manifest: dict[str, Any]) -> dict[str, dict[str, object]]:
    gate = manifest["release_gate"]
    names = gate.get("external_projects")
    _require(names == ["crypto-new", "manager", "BinancePredictionStrategy"], "external project set drifted")
    surface = gate.get("external_snapshot_surface")
    _require(surface == ".research-os", "external snapshot surface drifted")
    snapshots: dict[str, dict[str, object]] = {}
    for name in names:
        project = ROOT.parent / name
        _require(project.is_dir() and not project.is_symlink(), f"external project missing: {name}")
        snapshots[name] = _control_tree(project / surface)
    return snapshots


def _version_surfaces(manifest: dict[str, Any]) -> dict[str, str]:
    release = manifest.get("release")
    _require(isinstance(release, str) and bool(release), "release must be text")
    gate = manifest.get("release_gate")
    _require(isinstance(gate, dict), "release_gate must be an object")
    expected_paths = ["pyproject.toml", "src/research_os/__init__.py", "uv.lock"]
    _require(gate.get("version_surfaces") == expected_paths, "version surfaces drifted")
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    init_source = (ROOT / "src/research_os/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"$', init_source, re.MULTILINE)
    _require(match is not None, "__version__ surface is missing")
    package = next(
        (row for row in lock["package"] if row.get("name") == "research-os"),
        None,
    )
    _require(isinstance(package, dict), "uv.lock research-os package is missing")
    surfaces = {
        "pyproject.toml": str(pyproject["project"]["version"]),
        "src/research_os/__init__.py": str(match.group(1)),
        "uv.lock": str(package["version"]),
    }
    _require(set(surfaces.values()) == {release}, f"version surface drift: {surfaces}")
    return surfaces


def _static_gate(manifest: dict[str, Any]) -> dict[str, object]:
    gate = manifest["release_gate"]
    _require(isinstance(gate, dict), "release_gate must be an object")
    _require(gate.get("single_verifier") == "scripts/verify_release.py", "verifier drift")
    required_python = gate.get("python")
    current_python = f"{sys.version_info.major}.{sys.version_info.minor}"
    _require(current_python == required_python, "release must run on declared Python")
    _require(gate.get("authorized_action_non_null") == 0, "authority target must be zero")
    _require(
        gate.get("external_projects_mode") == "read-only-no-live-migration",
        "external project mode drifted",
    )
    _require(gate.get("product_multi_agent") is False, "product multi-agent must be false")

    for relative, phrases in DOC_REQUIREMENTS.items():
        path = ROOT / relative
        source = path.read_text(encoding="utf-8")
        missing = [phrase for phrase in phrases if phrase not in source]
        _require(not missing, f"documentation drift in {relative}: {missing}")

    product_sources = list((ROOT / "src/research_os").rglob("*.py"))
    for path in product_sources:
        source = path.read_text(encoding="utf-8").lower()
        found = [marker for marker in PRODUCT_MULTI_AGENT_MARKERS if marker in source]
        _require(not found, f"product multi-agent marker in {path.relative_to(ROOT)}: {found}")
    product_tree = _python_tree()
    _require(product_tree["file_count"] == gate.get("product_python_file_count"), "product Python file count drifted")
    _require(product_tree["sha256"] == gate.get("product_python_tree_sha256"), "product Python tree drifted")

    return {
        "python": current_python,
        "versions": _version_surfaces(manifest),
        "documentation_surfaces": len(DOC_REQUIREMENTS),
        "product_python_tree": product_tree,
        "external_projects_mode": gate["external_projects_mode"],
        "product_multi_agent": False,
    }


def _wheel_gate(release: str) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="research-os-release-") as raw:
        work = Path(raw)
        wheel_dir = work / "wheel"
        _run(["uv", "build", "--wheel", "--out-dir", str(wheel_dir)])
        wheels = list(wheel_dir.glob("*.whl"))
        _require(len(wheels) == 1, "release build must produce exactly one wheel")
        wheel = wheels[0]
        with zipfile.ZipFile(wheel) as archive:
            metadata_names = [name for name in archive.namelist() if name.endswith("/METADATA")]
            _require(len(metadata_names) == 1, "wheel must contain one METADATA file")
            metadata = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
            _require(metadata["Version"] == release, "wheel metadata version drifted")
            skill_paths = [name for name in archive.namelist() if name.endswith("research_os/resources/research-os/SKILL.md")]
            _require(len(skill_paths) == 1, "wheel packaged skill is missing")

        venv = work / "install"
        _run([sys.executable, "-m", "venv", str(venv)])
        python = venv / "bin/python"
        _run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)])
        probe = _run(
            [
                str(python),
                "-c",
                "import importlib.metadata as m, importlib.resources as r, json; "
                "p=r.files('research_os').joinpath('resources/research-os/SKILL.md'); "
                "print(json.dumps({'version':m.version('research-os'),'skill':p.is_file()}))",
            ]
        )
        installed = json.loads(probe.strip().splitlines()[-1])
        _require(installed == {"version": release, "skill": True}, "temp install probe failed")
        return {
            "wheel": wheel.name,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "installed_metadata_version": installed["version"],
            "packaged_skill": installed["skill"],
        }


def verify(manifest_path: Path) -> dict[str, object]:
    _require(manifest_path.resolve() == DEFAULT_MANIFEST.resolve(), "alternate manifest forbidden")
    manifest = _strict_json(manifest_path)
    static = _static_gate(manifest)
    gate = manifest["release_gate"]
    external_before = _external_snapshots(manifest)
    try:
        focused_output = _run([sys.executable, "-m", "pytest", "-q", *AUTHORITY_TESTS])
        full_output = _run([sys.executable, "-m", "pytest", "-q"])
        passed, subtests = _pytest_counts(full_output)
        _require(passed >= int(gate["minimum_collected_tests"]), "passed-test floor not met")
        _require(subtests >= int(gate["minimum_subtests"]), "subtest floor not met")
        _run([sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"])
        _run(["uvx", "--offline", "ty", "check", "src"])
        _run(["git", "diff", "--check"])
        _require(not _run(["git", "status", "--porcelain"]), "release checkpoint is not clean")
        commit = _run(["git", "rev-parse", "HEAD"]).strip()
        wheel = _wheel_gate(str(manifest["release"]))
        _run(["git", "diff", "--check"])
        _require(not _run(["git", "status", "--porcelain"]), "release build dirtied checkpoint")
    finally:
        external_after = _external_snapshots(manifest)
        _require(external_after == external_before, "external Research OS state changed")

    return {
        "schema_version": 1,
        "kind": "research_os.release_gate_receipt",
        "release": manifest["release"],
        "commit": commit,
        "result": "PASS",
        "full_suite": {"passed": passed, "subtests_passed": subtests},
        "focused_authority_and_manifest": "PASS" if focused_output else "PASS",
        "authorized_action_non_null": gate["authorized_action_non_null"],
        "external_project_snapshots": external_before,
        "static": static,
        "wheel": wheel,
    }


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print("release gate FAIL: this command accepts no bypass arguments", file=sys.stderr)
        return 2
    try:
        receipt = verify(DEFAULT_MANIFEST)
    except ReleaseGateError as exc:
        print(f"release gate FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
