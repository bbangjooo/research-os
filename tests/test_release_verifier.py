from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

import scripts.verify_release as verifier
from scripts.verify_release import (
    DEFAULT_MANIFEST,
    DEFAULT_RECEIPT,
    ReleaseGateError,
    _external_snapshots,
    _installer_gate,
    _pytest_counts,
    _run,
    _sealed_release_tree,
    _static_gate,
    _strict_json,
    main,
)


def test_v03_release_manifest_fields_are_consumed_by_static_gate() -> None:
    manifest = _strict_json(DEFAULT_MANIFEST)
    observed = _static_gate(manifest)

    assert observed["python"] == manifest["release_gate"]["python"]
    assert observed["versions"] == {
        "pyproject.toml": "0.3.0",
        "src/research_os/__init__.py": "0.3.0",
        "uv.lock": "0.3.0",
    }
    assert observed["documentation_surfaces"] == 4
    assert observed["product_python_tree"] == {
        "file_count": manifest["release_gate"]["product_python_file_count"],
        "sha256": manifest["release_gate"]["product_python_tree_sha256"],
    }
    assert observed["external_projects_mode"] == "read-only-no-live-migration"
    assert observed["product_multi_agent"] is False


def test_v03_static_gate_recomputes_the_historical_receipt_commit_tree() -> None:
    manifest = _strict_json(DEFAULT_MANIFEST)
    commit, tree = _sealed_release_tree(manifest)

    assert commit == "e120292620b17179231902deadb34cda9491c786"
    assert tree == {
        "file_count": manifest["release_gate"]["product_python_file_count"],
        "sha256": manifest["release_gate"]["product_python_tree_sha256"],
    }


def test_v03_static_gate_rejects_a_tampered_historical_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt = json.loads(DEFAULT_RECEIPT.read_text(encoding="utf-8"))
    tampered = copy.deepcopy(receipt)
    tampered["static"]["product_python_tree"]["sha256"] = "a" * 64
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(tampered), encoding="utf-8")
    monkeypatch.setattr(verifier, "DEFAULT_RECEIPT", path)

    with pytest.raises(ReleaseGateError, match="receipt and manifest"):
        _static_gate(_strict_json(DEFAULT_MANIFEST))


def test_release_verifier_snapshots_all_external_research_os_state_read_only() -> None:
    manifest = _strict_json(DEFAULT_MANIFEST)
    before = _external_snapshots(manifest)
    after = _external_snapshots(manifest)

    assert set(before) == {"crypto-new", "manager", "BinancePredictionStrategy"}
    assert before == after
    assert all(
        set(snapshot) == {"exists", "entry_count", "sha256"}
        for snapshot in before.values()
    )


def test_release_verifier_has_no_skip_or_alternate_manifest_mode(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["--skip-pytest"]) == 2
    assert "accepts no bypass arguments" in capsys.readouterr().err


def test_release_verifier_rejects_failed_commands_and_incomplete_pytest_output() -> None:
    with pytest.raises(ReleaseGateError, match="command failed"):
        _run([sys.executable, "-c", "raise SystemExit(7)"])
    with pytest.raises(ReleaseGateError, match="subtest"):
        _pytest_counts("600 passed in 1.00s")
    with pytest.raises(ReleaseGateError, match="passed-test"):
        _pytest_counts("115 subtests passed in 1.00s")


def test_release_verifier_parses_only_complete_full_suite_summary() -> None:
    assert _pytest_counts("601 passed, 115 subtests passed in 42:00") == (601, 115)


def test_release_verifier_executes_all_six_installer_manifest_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _strict_json(DEFAULT_MANIFEST)
    observed_commands: list[list[str]] = []

    def pass_six(command: list[str]) -> str:
        observed_commands.append(command)
        return "6 passed in 0.10s"

    monkeypatch.setattr(verifier, "_run", pass_six)
    result = _installer_gate(manifest)

    expected_ids = [case["id"] for case in manifest["managed_skill_upgrade"]["cases"]]
    assert result == {"case_ids": expected_ids, "passed": 6}
    assert len(observed_commands) == 1
    assert all(case_id in " ".join(observed_commands[0]) for case_id in expected_ids)
