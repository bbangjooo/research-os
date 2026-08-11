#!/usr/bin/env python3
"""Verify the sealed Research OS v0.5 acceptance and release conjunction."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import tomllib
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from research_os.contracts.common import canonical_json_bytes
from research_os.meta_evaluation import (
    arm_symmetry,
    compare_arms,
    generate_race_suite,
    generate_suite,
    load_generator_manifest,
    prearm_seal,
    run_arm,
    suite_digest,
)

ROOT: Final = Path(__file__).resolve().parents[1]
MANIFEST_PATH: Final = ROOT / "tests/fixtures/releases/v0.5.0/manifest.json"
RECEIPT_PATH: Final = ROOT / "docs/research-os-status/v0.5.0-release-receipt.json"
GENERATOR_PATH: Final = ROOT / "tests/fixtures/meta_evaluation/v1/generator-manifest.json"
SUITE_PATH: Final = ROOT / "tests/fixtures/meta_evaluation/v1/acceptance-suite.json"
RACE_PATH: Final = ROOT / "tests/fixtures/meta_evaluation/v1/acceptance-race-suite.json"
PREARM_PATH: Final = ROOT / "docs/research-os-status/14-m3-d-prearm-seal.json"
CUSTODY_PATH: Final = ROOT / "docs/research-os-status/14-m3-d-custody-transcript.json"

V05_UPGRADE_CASES: Final = (
    {"id": "exact-0.2-to-0.5", "operation": "upgrade-exact-sealed-0.2", "expected": {"from_release": "0.2.0", "to_release": "0.5.0", "status": "upgraded", "destination_current": True, "recovery_is_prior": True}},
    {"id": "exact-0.3-to-0.5", "operation": "upgrade-exact-sealed-0.3", "expected": {"from_release": "0.3.0", "to_release": "0.5.0", "status": "upgraded", "destination_current": True, "recovery_is_prior": True}},
    {"id": "exact-0.4-to-0.5", "operation": "upgrade-exact-sealed-0.4", "expected": {"from_release": "0.4.0", "to_release": "0.5.0", "status": "upgraded", "destination_current": True, "recovery_is_prior": True}},
    {"id": "drifted-0.4-rejected-no-write", "operation": "reject-drifted-0.4", "expected": {"error_type": "ConfigurationError", "destination_unchanged": True, "transactions_empty": True}},
    {"id": "unknown-release-rejected-no-write", "operation": "reject-unknown-managed-release", "expected": {"error_type": "ConfigurationError", "destination_unchanged": True, "transactions_empty": True}},
    {"id": "commit-failure-restores-0.4", "operation": "fail-second-target-commit", "expected": {"error_type": "OSError", "codex_unchanged": True, "claude_unchanged": True}},
    {"id": "publish-failure-restores-0.4", "operation": "fail-after-current-tree-publish", "expected": {"error_type": "OSError", "destination_is_prior": True, "recovery_count": 1, "recovery_is_current": True}},
)

DOC_REQUIREMENTS: Final = {
    "README.md": ("0.5.0", "finite, restartable single-researcher loop", "read-only compatibility"),
    "docs/architecture.md": ("v0.5.0", "DecisionPacket", "single-worker orchestration"),
    "docs/agent-usage.md": ("v0.5.0", "DecisionPacket", "live pilot and migration"),
    "docs/new-project.md": ("v0.5.0", "separate append-only Project, Program, and autonomy logs"),
    "src/research_os/resources/research-os/SKILL.md": ("v0.5.0", "finite-loop discipline", "authorized_action"),
    "src/research_os/resources/research-os/references/scientific-protocol.md": ("v0.5.0", "Finite autonomous research protocol", "single-worker"),
}


class V05ReleaseGateError(RuntimeError):
    """The v0.5 release conjunction is incomplete or invalid."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise V05ReleaseGateError(message)


def strict_json(path: Path) -> dict[str, Any]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise V05ReleaseGateError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    try:
        value = json.loads(
            path.read_bytes(),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda item: (_ for _ in ()).throw(
                V05ReleaseGateError(f"non-finite JSON number: {item}")
            ),
        )
    except (OSError, ValueError) as exc:
        raise V05ReleaseGateError(f"cannot load {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise V05ReleaseGateError(f"expected JSON object: {path}")
    return value


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _run(command: Sequence[str]) -> str:
    completed = subprocess.run(command, cwd=ROOT, check=False, capture_output=True, text=True)
    output = completed.stdout + completed.stderr
    if completed.returncode != 0:
        raise V05ReleaseGateError(
            f"command failed ({completed.returncode}): {' '.join(command)}\n{output[-6000:]}"
        )
    return output


def _passed_count(output: str) -> int:
    matches = re.findall(r"(?<!\d)(\d+) passed", output)
    _require(bool(matches), "pytest output has no passed count")
    return int(matches[-1])


def _full_counts(output: str) -> tuple[int, int]:
    passed = _passed_count(output)
    subtests = re.findall(r"(?<!\d)(\d+) subtests passed", output)
    _require(bool(subtests), "full pytest output has no subtest count")
    return passed, int(subtests[-1])


def _git_bytes(commit: str, relative: str) -> bytes:
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", commit)), "code commit must be full SHA")
    result = subprocess.run(
        ["git", "show", f"{commit}:{relative}"], cwd=ROOT, check=False, capture_output=True
    )
    _require(result.returncode == 0, f"frozen path missing at code commit: {relative}")
    return result.stdout


def _artifact_bindings(manifest: Mapping[str, Any], code_commit: str) -> None:
    artifacts = manifest.get("pre_nonce_artifacts")
    _require(isinstance(artifacts, list) and artifacts, "pre-nonce artifact bindings missing")
    for item in artifacts:
        _require(isinstance(item, Mapping), "pre-nonce artifact row must be an object")
        relative = item.get("path")
        digest = item.get("sha256")
        _require(isinstance(relative, str) and isinstance(digest, str), "artifact binding invalid")
        current = (ROOT / relative).read_bytes()
        _require(_sha256(current) == digest, f"pre-nonce artifact hash drifted: {relative}")
        _require(_git_bytes(code_commit, relative) == current, f"artifact is not frozen at code commit: {relative}")


def _version_and_docs(manifest: Mapping[str, Any], code_commit: str) -> dict[str, Any]:
    pyproject = tomllib.loads(_git_bytes(code_commit, "pyproject.toml").decode())
    lock = tomllib.loads(_git_bytes(code_commit, "uv.lock").decode())
    init = _git_bytes(code_commit, "src/research_os/__init__.py").decode()
    match = re.search(r'^__version__\s*=\s*"([^"]+)"$', init, re.MULTILINE)
    package = next((item for item in lock["package"] if item.get("name") == "research-os"), None)
    _require(match is not None and isinstance(package, Mapping), "version surfaces missing")
    versions = {
        "pyproject.toml": pyproject["project"]["version"],
        "src/research_os/__init__.py": match.group(1),
        "uv.lock": package["version"],
    }
    _require(set(versions.values()) == {"0.5.0"}, f"version drift: {versions}")
    for relative, phrases in DOC_REQUIREMENTS.items():
        source = _git_bytes(code_commit, relative).decode()
        missing = [phrase for phrase in phrases if phrase not in source]
        _require(not missing, f"v0.5 docs incomplete in {relative}: {missing}")
    gate = manifest.get("release_gate")
    _require(isinstance(gate, Mapping), "release gate contract missing")
    _require(gate.get("product_multi_agent") is False, "product multi-agent must remain disabled")
    _require(gate.get("live_migration") is False, "live migration must remain disabled")
    return {"versions": versions, "documentation_surfaces": len(DOC_REQUIREMENTS)}


def _wheel_gate() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="research-os-v05-wheel-") as raw:
        root = Path(raw)
        wheel_dir = root / "wheel"
        _run(["uv", "build", "--wheel", "--out-dir", str(wheel_dir)])
        wheels = list(wheel_dir.glob("*.whl"))
        _require(len(wheels) == 1, "wheel build did not create exactly one artifact")
        wheel = wheels[0]
        with zipfile.ZipFile(wheel) as archive:
            metadata_name = [name for name in archive.namelist() if name.endswith("/METADATA")]
            _require(len(metadata_name) == 1, "wheel METADATA missing")
            metadata = Parser().parsestr(archive.read(metadata_name[0]).decode())
            _require(metadata["Version"] == "0.5.0", "wheel version is not 0.5.0")
            _require(
                any(name.endswith("research_os/resources/research-os/SKILL.md") for name in archive.namelist()),
                "packaged skill missing from wheel",
            )
        venv = root / "venv"
        _run([sys.executable, "-m", "venv", str(venv)])
        python = venv / "bin/python"
        _run([str(python), "-m", "pip", "install", "--no-index", "--no-deps", str(wheel)])
        probe = _run([str(python), "-c", "import importlib.metadata as m; print(m.version('research-os'))"])
        _require(probe.strip() == "0.5.0", "temporary installation version drifted")
        return {"wheel": wheel.name, "installed": "0.5.0", "packaged_skill": True}


def reproduce_benchmark(
    *, nonce: str, suite: Mapping[str, Any], race: Mapping[str, Any], prearm: Mapping[str, Any]
) -> dict[str, Any]:
    manifest = load_generator_manifest(GENERATOR_PATH)
    _require(generate_suite(manifest, nonce) == suite, "acceptance suite is not reproducible")
    _require(generate_race_suite(manifest, nonce) == race, "race suite is not reproducible")
    _require(suite_digest(suite) == prearm.get("suite_sha256"), "suite digest differs from prearm seal")
    _require(suite_digest(race) == prearm.get("race_suite_sha256"), "race digest differs from prearm seal")
    results: dict[str, Any] = {}
    for arm in prearm.get("arm_order", []):
        _require(arm in {"v0.2", "v0.5"} and arm not in results, "prearm arm order invalid")
        results[arm] = run_arm(suite, arm)
    _require(set(results) == {"v0.2", "v0.5"}, "both benchmark arms are required")
    v02 = results["v0.2"]
    v05 = results["v0.5"]
    comparison = compare_arms(v02, v05)
    symmetry = arm_symmetry(v02, v05)
    _require(comparison["passed"] is True and symmetry["all_equal"] is True, "quality gate failed")
    for name in ("v0.2", "v0.5"):
        traces = comparison[name].pop("traces")
        comparison[name]["trace_sha256"] = _sha256(canonical_json_bytes(traces))
    symmetry_rows = symmetry.pop("episodes")
    symmetry["episodes_sha256"] = _sha256(canonical_json_bytes(symmetry_rows))
    symmetry["episode_count"] = len(symmetry_rows)
    return {"comparison": comparison, "symmetry": symmetry}


def collect_runtime_evidence(
    manifest: Mapping[str, Any], race: Mapping[str, Any]
) -> dict[str, Any]:
    attacks = _passed_count(_run([sys.executable, "-m", "pytest", "-q", "tests/test_m3d_protocol_attacks.py"]))
    _require(attacks == 25, "protocol attack manifest did not execute 24/24 rows")
    boundary_manifest = strict_json(ROOT / manifest["public_boundary_manifest"])
    nodes = [item["nodeid"] for item in boundary_manifest["cases"]]
    boundaries = _passed_count(_run([sys.executable, "-m", "pytest", "-q", *nodes]))
    _require(boundaries == 8, "six-family public boundary gate did not pass exact 8 nodes")
    external = _passed_count(_run([sys.executable, "-m", "pytest", "-q", "tests/test_m3d_external_compatibility.py"]))
    _require(external == 4, "external read-only gate did not pass 3/3 projects")
    upgrades = _passed_count(_run([sys.executable, "-m", "pytest", "-q", "tests/test_m3d_release_gate.py"]))
    _require(upgrades == 7, "managed upgrade/rollback gate did not pass 7/7")
    race_rows = race.get("schedules")
    _require(isinstance(race_rows, list) and len(race_rows) == 12, "race suite must have 12 rows")
    for row in race_rows:
        _require(_passed_count(_run([sys.executable, "-m", "pytest", "-q", row["pytest_node"]])) == 1, "race schedule failed")
    full_output = _run([sys.executable, "-m", "pytest", "-q"])
    passed, subtests = _full_counts(full_output)
    gate = manifest["release_gate"]
    _require(passed >= gate["minimum_passed_tests"], "full test floor not met")
    _require(subtests >= gate["minimum_subtests"], "full subtest floor not met")
    _run([sys.executable, "-m", "ruff", "check", "src", "tests", "scripts"])
    _run(["uvx", "--offline", "ty", "check", "src"])
    _run(["git", "diff", "--check"])
    return {
        "protocol_attacks": {"rows": 24, "pytest_passed": attacks},
        "public_boundaries": {"families": 6, "pytest_passed": boundaries},
        "external_read_only": {"projects": 3, "opaque": 3, "pytest_passed": external, "writer_delta": 0},
        "managed_upgrades": {"cases": 7, "pytest_passed": upgrades},
        "race_confirmation": {"schedules": 12, "passed": 12},
        "full_suite": {"passed": passed, "subtests_passed": subtests},
        "wheel": _wheel_gate(),
    }


def validate_prearm(
    manifest: Mapping[str, Any],
    suite: Mapping[str, Any],
    race: Mapping[str, Any],
    prearm: Mapping[str, Any],
    nonce: str,
) -> None:
    code_commit = prearm.get("code_commit")
    _require(isinstance(code_commit, str), "prearm code commit missing")
    manifest_relative = MANIFEST_PATH.relative_to(ROOT).as_posix()
    _require(
        _git_bytes(code_commit, manifest_relative) == MANIFEST_PATH.read_bytes(),
        "v0.5 release manifest changed after code freeze",
    )
    _artifact_bindings(manifest, code_commit)
    source_sha = _sha256(_git_bytes(code_commit, "src/research_os/meta_evaluation.py"))
    generator_sha = _sha256(_git_bytes(code_commit, GENERATOR_PATH.relative_to(ROOT).as_posix()))
    _require(generator_sha == prearm.get("generator_manifest_sha256"), "generator manifest seal drifted")
    _require(source_sha == prearm.get("generator_source_sha256"), "generator source seal drifted")
    commitment = _sha256(bytes.fromhex(nonce))
    _require(commitment == prearm.get("nonce_commitment_sha256"), "nonce commitment mismatch")
    expected = prearm_seal(
        code_commit=code_commit,
        generator_manifest_sha256=generator_sha,
        generator_source_sha256=source_sha,
        v02_agent_sha256=prearm["v0.2_agent_source_sha256"],
        v02_skill_sha256=prearm["v0.2_skill_sha256"],
        nonce_commitment_sha256=commitment,
        suite_sha256=suite_digest(suite),
        race_suite_sha256=suite_digest(race),
        arm_order=prearm["arm_order"],
        environment=prearm["environment"],
    )
    _require(expected == prearm, "prearm seal is not canonical")
    _version_and_docs(manifest, code_commit)


def verify() -> dict[str, Any]:
    manifest = strict_json(MANIFEST_PATH)
    receipt = strict_json(RECEIPT_PATH)
    suite = strict_json(SUITE_PATH)
    race = strict_json(RACE_PATH)
    prearm = strict_json(PREARM_PATH)
    _require(manifest.get("release") == receipt.get("release") == "0.5.0", "release version drifted")
    _require(receipt.get("result") == "PASS", "acceptance receipt is not passing")
    nonce = receipt.get("acceptance_nonce")
    _require(isinstance(nonce, str), "published acceptance nonce missing")
    validate_prearm(manifest, suite, race, prearm, nonce)
    benchmark = reproduce_benchmark(nonce=nonce, suite=suite, race=race, prearm=prearm)
    _require(receipt.get("benchmark") == benchmark, "saved benchmark result is not reproducible")
    runtime = collect_runtime_evidence(manifest, race)
    _require(receipt.get("runtime") == runtime, "saved runtime evidence is not reproducible")
    _require(receipt.get("authorized_action") is None, "release receipt authority must be null")
    _require(receipt.get("product_multi_agent") is False, "product multi-agent boundary drifted")
    _require(receipt.get("live_migration") is False, "live migration boundary drifted")
    _require(not _run(["git", "status", "--porcelain"]), "release checkpoint is not clean")
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else list(argv)
    if values:
        print("v0.5 release gate FAIL: bypass arguments are forbidden", file=sys.stderr)
        return 2
    try:
        receipt = verify()
    except (KeyError, TypeError, ValueError, V05ReleaseGateError) as exc:
        print(f"v0.5 release gate FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
