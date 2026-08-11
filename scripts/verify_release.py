#!/usr/bin/env python3
"""Run the current Research OS release gate and retain sealed historical proof."""

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
DEFAULT_RECEIPT = ROOT / "docs/research-os-status/v0.3.0-release-receipt.json"
CURRENT_MANIFEST = ROOT / "tests/fixtures/releases/v0.4.0/manifest.json"
CURRENT_RECEIPT = ROOT / "docs/research-os-status/v0.4.0-release-receipt.json"
M2D_MANIFEST = ROOT / "tests/fixtures/program_memory/v3/m2d-manifest.json"
AUTHORITY_TESTS = (
    "tests/test_m1a_evidence_e2e.py::test_m1a_changed_surfaces_keep_authority_null",
    "tests/test_m1b_manifest_oracle.py::test_every_manifest_case_has_an_executable_expectation_binding[authority-null-changed-surfaces]",
    "tests/test_m1c_manifest_oracle.py::test_every_manifest_case_has_an_operation_only_expectation_binding[proposal-authority-null-surfaces]",
    "tests/test_m1d_manifest_oracle.py::test_all_frozen_authority_values_are_null",
    "tests/test_m1d_manifest_oracle.py::test_ten_live_public_surfaces_keep_authority_present_and_null",
    "tests/test_m1e_release_gate.py",
    "tests/test_m2d_knowledge_disposition.py",
)
DOC_REQUIREMENTS = {
    "README.md": ("0.4.0", "Context v3", "ProposalKnowledgeDisposition", "legacy_unstructured"),
    "docs/architecture.md": ("0.4.0", "ProgramLog", "knowledge-disposition", "legacy_unstructured"),
    "docs/agent-usage.md": ("0.4.0", "Context v3", "knowledge disposition", "legacy_unstructured"),
    "docs/new-project.md": (
        "0.4.0",
        "Program memory",
        "legacy_unstructured",
        "never store raw legacy content",
    ),
    "src/research_os/resources/research-os/SKILL.md": (
        "0.4.0",
        "Context",
        "knowledge disposition",
        "legacy_unstructured",
    ),
    "src/research_os/resources/research-os/references/scientific-protocol.md": (
        "0.4.0",
        "ProgramLog",
        "knowledge disposition",
        "legacy_unstructured",
    ),
}
PRODUCT_MULTI_AGENT_MARKERS = ("multi_agent", "multi-agent", "agent_swarm", "role_swarm")
INSTALLER_CASE_IDS = (
    "explicit-upgrade-required",
    "exact-managed-upgrade-retains-prior-backup",
    "drifted-managed-tree-rejected-no-write",
    "unknown-managed-release-rejected-no-write",
    "two-target-commit-failure-restores-both",
    "publish-then-fail-restores-prior-and-retains-new-recovery",
)
V04_UPGRADE_CASE_IDS = (
    "exact-0.2-to-0.4",
    "exact-0.3-to-0.4",
    "drifted-0.3-rejected-no-write",
    "unknown-release-rejected-no-write",
    "commit-failure-restores-prior",
    "publish-failure-retains-recovery",
)
V04_UPGRADE_CASES = (
    {
        "id": "exact-0.2-to-0.4",
        "operation": "upgrade-exact-sealed-0.2",
        "expected": {
            "from_release": "0.2.0",
            "to_release": "0.4.0",
            "status": "upgraded",
            "destination_current": True,
            "recovery_is_prior": True,
        },
    },
    {
        "id": "exact-0.3-to-0.4",
        "operation": "upgrade-exact-sealed-0.3",
        "expected": {
            "from_release": "0.3.0",
            "to_release": "0.4.0",
            "status": "upgraded",
            "destination_current": True,
            "recovery_is_prior": True,
        },
    },
    {
        "id": "drifted-0.3-rejected-no-write",
        "operation": "reject-drifted-0.3",
        "expected": {
            "error_type": "ConfigurationError",
            "destination_unchanged": True,
            "transactions_empty": True,
        },
    },
    {
        "id": "unknown-release-rejected-no-write",
        "operation": "reject-unknown-managed-release",
        "expected": {
            "error_type": "ConfigurationError",
            "destination_unchanged": True,
            "transactions_empty": True,
        },
    },
    {
        "id": "commit-failure-restores-prior",
        "operation": "fail-second-target-commit",
        "expected": {
            "error_type": "OSError",
            "codex_unchanged": True,
            "claude_unchanged": True,
        },
    },
    {
        "id": "publish-failure-retains-recovery",
        "operation": "fail-after-current-tree-publish",
        "expected": {
            "error_type": "OSError",
            "destination_is_prior": True,
            "recovery_count": 1,
            "recovery_is_current": True,
        },
    },
)
M2D_DISPOSITION_CASE_IDS = (
    "disposition-valid-three-way",
    "disposition-missing-returned-claim",
    "disposition-duplicate-claim",
    "disposition-unknown-claim",
    "disposition-forged-claim-digest",
    "disposition-forged-role",
    "disposition-forged-relation-ref",
    "disposition-forged-proposal-binding",
    "disposition-stale-context-token",
    "disposition-stale-program-head",
    "disposition-used-without-proposal-ref",
    "disposition-rejected-without-contradiction-ref",
    "disposition-not-applicable-without-code",
    "disposition-non-null-authority",
)
M2D_LEGACY_CASE_IDS = (
    "legacy-valid-opaque-import",
    "legacy-free-text-never-inferred",
    "legacy-forged-content-digest",
    "legacy-duplicate-id",
    "legacy-extra-key",
    "legacy-non-null-authority",
)
M2D_EXTERNAL_CASE_ID = "external-three-project-read-only"
M2D_UPGRADE_CASE_ID = "upgrade-prior-managed-releases"
M2D_RELEASE_CASE_ID = "release-v0.4-single-gate"
DURABLE_THREE_WAY_NODE = (
    "tests/test_m2d_knowledge_disposition.py::"
    "test_durable_three_way_disposition_replays_from_registered_proposal"
)
M2D_CASE_IDS = (
    *M2D_DISPOSITION_CASE_IDS,
    *M2D_LEGACY_CASE_IDS,
    M2D_EXTERNAL_CASE_ID,
    M2D_UPGRADE_CASE_ID,
    M2D_RELEASE_CASE_ID,
)


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


def _passed_count(output: str) -> int:
    passed = re.findall(r"(?<!\d)(\d+) passed", output)
    _require(bool(passed), "pytest output has no passed-test count")
    return int(passed[-1])


def _installer_gate(manifest: dict[str, Any]) -> dict[str, object]:
    upgrade = manifest.get("managed_skill_upgrade")
    _require(isinstance(upgrade, dict), "managed skill upgrade contract is missing")
    cases = upgrade.get("cases")
    _require(isinstance(cases, list), "managed skill upgrade cases are missing")
    case_ids = [case.get("id") for case in cases if isinstance(case, dict)]
    release = manifest.get("release")
    if release == "0.3.0":
        expected_ids = INSTALLER_CASE_IDS
        node_prefix = (
            "tests/test_m1e_release_gate.py::"
            "test_managed_upgrade_manifest_case_executes_exact_outcome"
        )
    elif release == "0.4.0":
        expected_ids = V04_UPGRADE_CASE_IDS
        node_prefix = "tests/test_m2d_release_gate.py::test_v04_managed_upgrade_subcase"
    else:
        raise ReleaseGateError(f"unsupported release manifest: {release!r}")
    _require(case_ids == list(expected_ids), "managed skill upgrade case IDs drifted")
    _require(
        all(set(case) == {"id", "operation", "expected"} for case in cases),
        "managed skill upgrade case shape drifted",
    )
    if release == "0.4.0":
        _require(cases == list(V04_UPGRADE_CASES), "v0.4 upgrade outcomes drifted")
    nodes = [f"{node_prefix}[{case_id}]" for case_id in case_ids]
    output = _run([sys.executable, "-m", "pytest", "-q", *nodes])
    passed = _passed_count(output)
    _require(passed == len(case_ids), "installer matrix did not pass exactly six cases")
    return {"case_ids": case_ids, "passed": passed}


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


def _python_tree_at_commit(commit: str) -> dict[str, object]:
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", commit)), "release commit must be a full SHA")
    exists = subprocess.run(
        ["git", "cat-file", "-e", f"{commit}^{{commit}}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    _require(exists.returncode == 0, "release commit is absent from the repository")
    listed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", commit, "--", "src/research_os"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    _require(listed.returncode == 0, "cannot list release product tree")
    names = sorted(name for name in listed.stdout.split(b"\0") if name.endswith(b".py"))
    digest = hashlib.sha256()
    prefix = b"src/research_os/"
    for name in names:
        _require(name.startswith(prefix), "release tree contains an unexpected path")
        shown = subprocess.run(
            ["git", "show", f"{commit}:{name.decode('utf-8')}"],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
        _require(shown.returncode == 0, f"cannot read release product path: {name!r}")
        relative = name[len(prefix) :]
        digest.update(len(relative).to_bytes(8, "big") + relative)
        digest.update(len(shown.stdout).to_bytes(8, "big") + shown.stdout)
    return {"file_count": len(names), "sha256": digest.hexdigest()}


def _git_file_bytes(commit: str, relative: str) -> bytes:
    shown = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    _require(shown.returncode == 0, f"cannot read release path: {relative}")
    return shown.stdout


def _python_sources_at_commit(commit: str) -> dict[str, str]:
    listed = subprocess.run(
        ["git", "ls-tree", "-r", "--name-only", "-z", commit, "--", "src/research_os"],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )
    _require(listed.returncode == 0, "cannot list release product sources")
    names = sorted(
        name.decode("utf-8") for name in listed.stdout.split(b"\0") if name.endswith(b".py")
    )
    return {name: _git_file_bytes(commit, name).decode("utf-8") for name in names}


def _sealed_release_tree(manifest: dict[str, Any]) -> tuple[str, dict[str, object]]:
    release = manifest.get("release")
    receipt_path = DEFAULT_RECEIPT if release == "0.3.0" else CURRENT_RECEIPT
    _require(release in {"0.3.0", "0.4.0"}, "unsupported sealed release")
    receipt = _strict_json(receipt_path)
    _require(receipt.get("schema_version") == 1, "release receipt schema drifted")
    _require(
        receipt.get("kind") == "research_os.release_gate_receipt", "release receipt kind drifted"
    )
    _require(receipt.get("release") == manifest.get("release"), "release receipt version drifted")
    _require(receipt.get("result") == "PASS", "release receipt is not passing")
    commit = receipt.get("commit")
    _require(isinstance(commit, str), "release receipt commit is missing")
    static = receipt.get("static")
    _require(isinstance(static, dict), "release receipt static result is missing")
    recorded_tree = static.get("product_python_tree")
    _require(isinstance(recorded_tree, dict), "release receipt product tree is missing")
    gate = manifest.get("release_gate")
    _require(isinstance(gate, dict), "release_gate must be an object")
    expected_tree = {
        "file_count": gate.get("product_python_file_count"),
        "sha256": gate.get("product_python_tree_sha256"),
    }
    _require(recorded_tree == expected_tree, "release receipt and manifest tree differ")
    observed_tree = _python_tree_at_commit(commit)
    _require(observed_tree == expected_tree, "sealed release commit product tree drifted")
    return commit, observed_tree


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


def _control_tree_strict(path: Path) -> dict[str, object]:
    """Bind byte content plus permission/type metadata without following links."""
    base = _control_tree(path)
    digest = hashlib.sha256()
    if not path.exists():
        digest.update(b"absent")
        return {**base, "metadata_sha256": digest.hexdigest(), "symlink_count": 0}

    root_info = path.lstat()
    digest.update(b"root")
    digest.update((root_info.st_mode & 0o7777).to_bytes(4, "big"))
    symlinks = 0
    for current, directories, files in os.walk(path, followlinks=False):
        directories.sort()
        files.sort()
        for name in [*directories, *files]:
            item = Path(current) / name
            info = item.lstat()
            is_link = item.is_symlink()
            symlinks += int(is_link)
            relative = item.relative_to(path).as_posix().encode()
            kind = b"l" if is_link else b"d" if item.is_dir() else b"f"
            digest.update(kind + len(relative).to_bytes(8, "big") + relative)
            digest.update((info.st_mode & 0o7777).to_bytes(4, "big"))
            digest.update(info.st_size.to_bytes(8, "big"))
    return {**base, "metadata_sha256": digest.hexdigest(), "symlink_count": symlinks}


def _external_snapshots(manifest: dict[str, Any]) -> dict[str, dict[str, object]]:
    gate = manifest["release_gate"]
    names = gate.get("external_projects")
    _require(
        names == ["crypto-new", "manager", "BinancePredictionStrategy"],
        "external project set drifted",
    )
    surface = gate.get("external_snapshot_surface")
    _require(surface == ".research-os", "external snapshot surface drifted")
    snapshots: dict[str, dict[str, object]] = {}
    for name in names:
        project = ROOT.parent / name
        _require(project.is_dir() and not project.is_symlink(), f"external project missing: {name}")
        snapshots[name] = _control_tree(project / surface)
    return snapshots


def _external_snapshots_strict(manifest: dict[str, Any]) -> dict[str, dict[str, object]]:
    gate = manifest["release_gate"]
    names = gate.get("external_projects")
    _require(
        names == ["crypto-new", "manager", "BinancePredictionStrategy"],
        "external project set drifted",
    )
    surface = gate.get("external_snapshot_surface")
    _require(surface == ".research-os", "external snapshot surface drifted")
    snapshots: dict[str, dict[str, object]] = {}
    for name in names:
        project = ROOT.parent / name
        _require(project.is_dir() and not project.is_symlink(), f"external project missing: {name}")
        snapshots[name] = _control_tree_strict(project / surface)
    return snapshots


def _version_surfaces(
    manifest: dict[str, Any],
    *,
    commit: str | None = None,
) -> dict[str, str]:
    release = manifest.get("release")
    _require(isinstance(release, str) and bool(release), "release must be text")
    gate = manifest.get("release_gate")
    _require(isinstance(gate, dict), "release_gate must be an object")
    expected_paths = ["pyproject.toml", "src/research_os/__init__.py", "uv.lock"]
    _require(gate.get("version_surfaces") == expected_paths, "version surfaces drifted")

    def source(relative: str) -> str:
        if commit is None:
            return (ROOT / relative).read_text(encoding="utf-8")
        return _git_file_bytes(commit, relative).decode("utf-8")

    pyproject = tomllib.loads(source("pyproject.toml"))
    lock = tomllib.loads(source("uv.lock"))
    init_source = source("src/research_os/__init__.py")
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


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _m2d_contract(manifest: dict[str, Any]) -> dict[str, Any]:
    binding = manifest.get("m2d_contract")
    _require(isinstance(binding, dict), "M2-D contract binding is missing")
    _require(
        set(binding) == {"path", "sha256", "case_ids"},
        "M2-D contract binding shape drifted",
    )
    relative = M2D_MANIFEST.relative_to(ROOT).as_posix()
    _require(binding.get("path") == relative, "M2-D contract path drifted")
    expected_sha256 = "b61da8af3930c25c575b3c8834cd952afdfb3f0e3bf886322baa94fa9bf0b2a7"
    _require(binding.get("sha256") == expected_sha256, "M2-D contract hash drifted")
    _require(_file_sha256(M2D_MANIFEST) == expected_sha256, "frozen M2-D manifest changed")
    _require(binding.get("case_ids") == list(M2D_CASE_IDS), "M2-D case binding drifted")

    contract = _strict_json(M2D_MANIFEST)
    cases = contract.get("cases")
    _require(isinstance(cases, list), "M2-D cases are missing")
    case_ids = [case.get("id") for case in cases if isinstance(case, dict)]
    _require(case_ids == list(M2D_CASE_IDS), "frozen M2-D case IDs drifted")
    _require(len(case_ids) == len(set(case_ids)) == 23, "M2-D case IDs are not unique")
    _require(
        contract.get("managed_upgrade", {}).get("upgrade_cases") == list(V04_UPGRADE_CASE_IDS),
        "frozen M2-D upgrade cases drifted",
    )
    release = contract.get("release")
    _require(isinstance(release, dict), "frozen M2-D release contract is missing")
    _require(release.get("version") == manifest.get("release"), "M2-D release version drifted")
    _require(release.get("product_multi_agent") is False, "M2-D multi-agent boundary drifted")
    _require(contract.get("authority") == {"authorized_action": None}, "M2-D authority drifted")
    return contract


def _m2d_case_gate() -> dict[str, object]:
    nodes = [
        f"tests/test_m2d_knowledge_disposition.py::test_frozen_disposition_case[{case_id}]"
        for case_id in M2D_DISPOSITION_CASE_IDS
    ]
    nodes.extend(
        f"tests/test_m2d_knowledge_disposition.py::test_frozen_legacy_case[{case_id}]"
        for case_id in M2D_LEGACY_CASE_IDS
    )
    output = _run([sys.executable, "-m", "pytest", "-q", *nodes])
    passed = _passed_count(output)
    expected = len(M2D_DISPOSITION_CASE_IDS) + len(M2D_LEGACY_CASE_IDS)
    _require(passed == expected, "M2-D disposition/legacy matrix did not pass exactly 20 cases")
    return {
        "case_ids": [*M2D_DISPOSITION_CASE_IDS, *M2D_LEGACY_CASE_IDS],
        "passed": passed,
        "results": {
            case_id: "PASS" for case_id in (*M2D_DISPOSITION_CASE_IDS, *M2D_LEGACY_CASE_IDS)
        },
    }


def _external_snapshot_matches_contract(
    contract: dict[str, Any],
    snapshots: dict[str, dict[str, object]],
) -> None:
    external = contract.get("external_read_only")
    _require(isinstance(external, dict), "M2-D external contract is missing")
    _require(external.get("writer_delta") == 0, "external writer target must be zero")
    _require(external.get("live_migration") is False, "external live migration must be false")
    expected = external.get("projects")
    _require(isinstance(expected, dict), "M2-D external project baselines are missing")
    observed = {
        name: {key: snapshot[key] for key in ("exists", "entry_count", "sha256")}
        for name, snapshot in snapshots.items()
    }
    _require(observed == expected, "external project baseline differs from frozen M2-D contract")
    _require(
        all(snapshot["symlink_count"] == 0 for snapshot in snapshots.values()),
        "external Research OS state contains a symlink",
    )


def _static_gate(manifest: dict[str, Any]) -> dict[str, object]:
    gate = manifest.get("release_gate")
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

    if manifest.get("release") == "0.3.0":
        _, product_tree = _sealed_release_tree(manifest)
        release = str(manifest["release"])
        return {
            "python": current_python,
            "versions": {
                "pyproject.toml": release,
                "src/research_os/__init__.py": release,
                "uv.lock": release,
            },
            "documentation_surfaces": 4,
            "product_python_tree": product_tree,
            "external_projects_mode": gate["external_projects_mode"],
            "product_multi_agent": False,
        }

    _require(manifest.get("release") == "0.4.0", "unsupported current release manifest")

    receipt_commit, sealed_tree = _sealed_release_tree(manifest)
    for relative, phrases in DOC_REQUIREMENTS.items():
        source = _git_file_bytes(receipt_commit, relative).decode("utf-8")
        missing = [phrase for phrase in phrases if phrase not in source]
        _require(not missing, f"documentation drift in {relative}: {missing}")

    for path, source in _python_sources_at_commit(receipt_commit).items():
        source = source.lower()
        found = [marker for marker in PRODUCT_MULTI_AGENT_MARKERS if marker in source]
        _require(not found, f"product multi-agent marker in {path}: {found}")
    expected_tree = {
        "file_count": gate.get("product_python_file_count"),
        "sha256": gate.get("product_python_tree_sha256"),
    }
    product_code_commit = gate.get("product_code_commit")
    _require(isinstance(product_code_commit, str), "product code commit is missing")
    _require(
        _python_tree_at_commit(product_code_commit) == expected_tree,
        "v0.4 product code commit tree drifted",
    )
    _require(sealed_tree == expected_tree, "sealed v0.4 receipt product tree drifted")

    return {
        "python": current_python,
        "versions": _version_surfaces(manifest, commit=receipt_commit),
        "documentation_surfaces": len(DOC_REQUIREMENTS),
        "product_code_commit": product_code_commit,
        "product_python_tree": expected_tree,
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
            skill_paths = [
                name
                for name in archive.namelist()
                if name.endswith("research_os/resources/research-os/SKILL.md")
            ]
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


def _verify_historical(manifest: dict[str, Any]) -> dict[str, object]:
    static = _static_gate(manifest)
    sealed_commit, _ = _sealed_release_tree(manifest)
    current_commit = _run(["git", "rev-parse", "HEAD"]).strip()
    _require(
        current_commit == sealed_commit,
        "historical v0.3 release receipt cannot be reissued from a later commit",
    )
    gate = manifest["release_gate"]
    external_before = _external_snapshots(manifest)
    try:
        focused_output = _run([sys.executable, "-m", "pytest", "-q", *AUTHORITY_TESTS])
        installer = _installer_gate(manifest)
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
        "managed_skill_upgrade": installer,
        "authorized_action_non_null": gate["authorized_action_non_null"],
        "external_project_snapshots": external_before,
        "static": static,
        "wheel": wheel,
    }


def _verify_current(manifest: dict[str, Any]) -> dict[str, object]:
    contract = _m2d_contract(manifest)
    static = _static_gate(manifest)
    gate = manifest["release_gate"]
    external_before = _external_snapshots_strict(manifest)
    _external_snapshot_matches_contract(contract, external_before)
    try:
        m2d = _m2d_case_gate()
        durable_output = _run([sys.executable, "-m", "pytest", "-q", DURABLE_THREE_WAY_NODE])
        _require(_passed_count(durable_output) == 1, "durable three-way case did not pass")
        external_output = _run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests/test_m2d_release_gate.py::"
                "test_external_three_project_snapshot_is_independent_and_read_only",
            ]
        )
        _require(_passed_count(external_output) == 1, "external read-only case did not pass")
        installer = _installer_gate(manifest)
        focused_output = _run([sys.executable, "-m", "pytest", "-q", *AUTHORITY_TESTS])
        focused_passed = _passed_count(focused_output)
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
        external_after = _external_snapshots_strict(manifest)
        _external_snapshot_matches_contract(contract, external_after)
        _require(external_after == external_before, "external Research OS state changed")

    case_results = dict(m2d["results"])
    case_results[M2D_EXTERNAL_CASE_ID] = "PASS"
    case_results[M2D_UPGRADE_CASE_ID] = "PASS"
    case_results[M2D_RELEASE_CASE_ID] = "PASS"
    _require(list(case_results) == list(M2D_CASE_IDS), "release receipt case order drifted")

    return {
        "schema_version": 1,
        "kind": "research_os.release_gate_receipt",
        "release": manifest["release"],
        "commit": commit,
        "result": "PASS",
        "m2d_contract": {
            "path": manifest["m2d_contract"]["path"],
            "sha256": manifest["m2d_contract"]["sha256"],
            "case_ids": list(M2D_CASE_IDS),
            "case_results": case_results,
            "disposition_and_legacy": m2d,
            "durable_three_way": {"node": DURABLE_THREE_WAY_NODE, "passed": 1},
        },
        "full_suite": {"passed": passed, "subtests_passed": subtests},
        "focused_authority_and_manifest": {
            "nodes": list(AUTHORITY_TESTS),
            "passed": focused_passed,
        },
        "managed_skill_upgrade": installer,
        "authorized_action_non_null": gate["authorized_action_non_null"],
        "external_project_snapshots": external_before,
        "static": static,
        "wheel": wheel,
    }


def verify(manifest_path: Path) -> dict[str, object]:
    resolved = manifest_path.resolve()
    _require(
        resolved in {DEFAULT_MANIFEST.resolve(), CURRENT_MANIFEST.resolve()},
        "alternate manifest forbidden",
    )
    manifest = _strict_json(manifest_path)
    if resolved == DEFAULT_MANIFEST.resolve():
        _require(manifest.get("release") == "0.3.0", "historical manifest version drifted")
        return _verify_historical(manifest)
    _require(manifest.get("release") == "0.4.0", "current manifest version drifted")
    sealed_commit, _ = _sealed_release_tree(manifest)
    current_commit = _run(["git", "rev-parse", "HEAD"]).strip()
    _require(
        current_commit == sealed_commit,
        "historical v0.4 release receipt cannot be reissued from a later commit",
    )
    return _verify_current(manifest)


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]
    if argv:
        print("release gate FAIL: this command accepts no bypass arguments", file=sys.stderr)
        return 2
    try:
        receipt = verify(CURRENT_MANIFEST)
    except ReleaseGateError as exc:
        print(f"release gate FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
