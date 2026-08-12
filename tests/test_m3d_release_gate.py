from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from unittest import mock

import pytest

from research_os import agent_install
from research_os.errors import ConfigurationError
from scripts import m3d_custodian
from scripts.verify_v05_release import V05_UPGRADE_CASES
from tests.test_agent_install_upgrade import (
    _TARGETS,
    _capture_tree,
    _exception_recovery_paths,
    _fake_managed_release,
    _write_files,
)
from tests.test_m2d_release_gate import _sealed_prior

CASE_IDS = tuple(case["id"] for case in V05_UPGRADE_CASES)
ROOT = Path(__file__).resolve().parents[1]
RELEASE_MANIFEST_PATH = ROOT / "tests/fixtures/releases/v0.5.0/manifest.json"


def _transactions_empty(home: Path) -> bool:
    root = home / agent_install._BACKUP_ROOT_NAME
    return not root.exists() or not any(root.iterdir())


def _observe(case_id: str, home: Path) -> dict[str, object]:
    destination = home / _TARGETS["codex"]
    if case_id.startswith("exact-"):
        release = case_id.split("-to-")[0].removeprefix("exact-") + ".0"
        prior = _sealed_prior(release)
        _write_files(destination, prior)
        records = agent_install.install_agent_skill("codex", home=home, upgrade=True)
        recovery = Path(records[0]["recovery_backup"])
        return {
            "from_release": records[0]["from_release"],
            "to_release": records[0]["to_release"],
            "status": records[0]["status"],
            "destination_current": _capture_tree(destination)[0]
            == agent_install._expected_files(),
            "recovery_is_prior": _capture_tree(recovery)[0] == prior,
        }
    if case_id == "drifted-0.4-rejected-no-write":
        _write_files(destination, _sealed_prior("0.4.0"))
        (destination / "SKILL.md").write_bytes(b"drifted 0.4\n")
        before = _capture_tree(destination)
        with pytest.raises(ConfigurationError) as caught:
            agent_install.install_agent_skill("codex", home=home, upgrade=True)
        return {
            "error_type": type(caught.value).__name__,
            "destination_unchanged": _capture_tree(destination) == before,
            "transactions_empty": _transactions_empty(home),
        }
    if case_id == "unknown-release-rejected-no-write":
        _write_files(destination, _fake_managed_release("9.9.9"))
        before = _capture_tree(destination)
        with pytest.raises(ConfigurationError) as caught:
            agent_install.install_agent_skill("codex", home=home, upgrade=True)
        return {
            "error_type": type(caught.value).__name__,
            "destination_unchanged": _capture_tree(destination) == before,
            "transactions_empty": _transactions_empty(home),
        }
    if case_id == "commit-failure-restores-0.4":
        prior = _sealed_prior("0.4.0")
        destinations = {target: home / relative for target, relative in _TARGETS.items()}
        for target in destinations.values():
            _write_files(target, prior)
        before = {name: _capture_tree(path) for name, path in destinations.items()}
        original = agent_install._commit_one

        def fail_second(prepared, expected):
            if prepared.state.target == "claude":
                raise OSError("M3-D second-target commit failure")
            return original(prepared, expected)

        with (
            mock.patch.object(agent_install, "_commit_one", side_effect=fail_second),
            pytest.raises(OSError) as caught,
        ):
            agent_install.install_agent_skill("all", home=home, upgrade=True)
        return {
            "error_type": type(caught.value).__name__,
            "codex_unchanged": _capture_tree(destinations["codex"]) == before["codex"],
            "claude_unchanged": _capture_tree(destinations["claude"]) == before["claude"],
        }
    if case_id == "publish-failure-restores-0.4":
        prior = _sealed_prior("0.4.0")
        _write_files(destination, prior)
        original = agent_install._rename_noreplace
        calls = 0

        def publish_then_fail(source: Path, target: Path) -> None:
            nonlocal calls
            calls += 1
            original(source, target)
            if calls == 2:
                raise OSError("M3-D publish failure")

        with (
            mock.patch.object(agent_install, "_rename_noreplace", side_effect=publish_then_fail),
            pytest.raises(OSError) as caught,
        ):
            agent_install.install_agent_skill("codex", home=home, upgrade=True)
        recovery = _exception_recovery_paths(caught.value)
        return {
            "error_type": type(caught.value).__name__,
            "destination_is_prior": _capture_tree(destination)[0] == prior,
            "recovery_count": len(recovery),
            "recovery_is_current": len(recovery) == 1
            and _capture_tree(recovery[0])[0] == agent_install._expected_files(),
        }
    raise AssertionError(case_id)


@pytest.mark.parametrize("case_id", CASE_IDS, ids=CASE_IDS)
def test_v05_managed_upgrade_and_rollback(case_id: str, tmp_path: Path) -> None:
    observed = _observe(case_id, tmp_path)
    expected = next(case["expected"] for case in V05_UPGRADE_CASES if case["id"] == case_id)
    assert observed == expected


def test_v05_release_manifest_binds_every_pre_nonce_byte() -> None:
    manifest = json.loads(RELEASE_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert manifest["release"] == "0.5.0"
    assert manifest["status"] == "precommitted-before-acceptance-nonce"
    assert manifest["acceptance"]["nonce_draw_count"] == 1
    assert manifest["acceptance"]["arm_run_count"] == 1
    assert manifest["release_gate"]["single_verifier"] == "scripts/verify_v05_release.py"
    assert manifest["release_gate"]["product_multi_agent"] is False
    assert manifest["release_gate"]["live_migration"] is False
    paths = [row["path"] for row in manifest["pre_nonce_artifacts"]]
    assert len(paths) == len(set(paths))
    for row in manifest["pre_nonce_artifacts"]:
        assert hashlib.sha256((ROOT / row["path"]).read_bytes()).hexdigest() == row["sha256"]


def test_acceptance_custodian_calls_secrets_after_atomic_reservation_exactly_once() -> None:
    source = (ROOT / "scripts/m3d_custodian.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "secrets"
        and node.func.attr == "token_hex"
    ]
    assert len(calls) == 1
    assert len(calls[0].args) == 1
    assert isinstance(calls[0].args[0], ast.Constant) and calls[0].args[0].value == 32
    reservation = source.index('"state": "reserved-before-nonce"')
    nonce_call = source.index("secrets.token_hex(32)")
    assert reservation < nonce_call
    prepare_source = (ROOT / "scripts/prepare_m3d_acceptance.py").read_text(
        encoding="utf-8"
    )
    prepare_tree = ast.parse(prepare_source)
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "secrets"
        and node.func.attr == "token_hex"
        for node in ast.walk(prepare_tree)
    )
    assert '[sys.executable, "-m", "scripts.m3d_custodian"]' in prepare_source
    run_source = (ROOT / "scripts/run_m3d_acceptance.py").read_text(encoding="utf-8")
    assert '"state": "reserved-before-arms"' in run_source
    assert "arm-run-reservation.json" in run_source
    assert "acceptance-result.json" in run_source
    assert run_source.index("_exclusive_json(arm_reservation_path") < run_source.index(
        "reproduce_benchmark("
    )


def test_custodian_reservation_is_durable_and_blocks_a_second_draw(tmp_path: Path) -> None:
    parent = tmp_path / "external-custody"
    commit = "a" * 40
    calls = 0

    def one_draw(_: int) -> str:
        nonlocal calls
        calls += 1
        reservation = parent / commit / "draw-reservation.json"
        assert json.loads(reservation.read_text(encoding="utf-8"))["state"] == (
            "reserved-before-nonce"
        )
        return "ab" * 32

    with mock.patch.object(m3d_custodian.secrets, "token_hex", side_effect=one_draw):
        transcript = m3d_custodian.reserve_draw(commit, custody_parent=parent)
        with pytest.raises(RuntimeError, match="already has a durable"):
            m3d_custodian.reserve_draw(commit, custody_parent=parent)
    assert calls == 1
    assert transcript["acceptance_nonce"] == "ab" * 32
    assert (parent / commit / "nonce-transcript.json").is_file()
