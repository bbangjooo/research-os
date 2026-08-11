from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

import scripts.verify_release as verifier
from scripts.verify_release import (
    CURRENT_MANIFEST,
    DEFAULT_MANIFEST,
    DEFAULT_RECEIPT,
    M2D_CASE_IDS,
    V04_UPGRADE_CASE_IDS,
    ReleaseGateError,
    _external_snapshot_matches_contract,
    _external_snapshots,
    _external_snapshots_strict,
    _installer_gate,
    _m2d_contract,
    _pytest_counts,
    _run,
    _sealed_release_tree,
    _static_gate,
    _strict_json,
    main,
    verify,
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


def test_v04_static_gate_binds_frozen_m2d_and_product_checkpoint() -> None:
    manifest = _strict_json(CURRENT_MANIFEST)
    contract = _m2d_contract(manifest)
    observed = _static_gate(manifest)

    assert manifest["m2d_contract"]["case_ids"] == list(M2D_CASE_IDS)
    assert [case["id"] for case in contract["cases"]] == list(M2D_CASE_IDS)
    assert observed == {
        "python": "3.12",
        "versions": {
            "pyproject.toml": "0.4.0",
            "src/research_os/__init__.py": "0.4.0",
            "uv.lock": "0.4.0",
        },
        "documentation_surfaces": 6,
        "product_code_commit": "3ea072675c5f7b0e30aafe1fa11055df2db06c21",
        "product_python_tree": {
            "file_count": 41,
            "sha256": "0c0c088f3a86856cfc08b1a9336edc97daa9b8796f96a7e84fad1d83113fa1bc",
        },
        "external_projects_mode": "read-only-no-live-migration",
        "product_multi_agent": False,
    }


def test_v04_contract_rejects_any_frozen_case_binding_drift() -> None:
    manifest = copy.deepcopy(_strict_json(CURRENT_MANIFEST))
    manifest["m2d_contract"]["case_ids"][-1] = "release-constant-pass"

    with pytest.raises(ReleaseGateError, match="case binding drifted"):
        _m2d_contract(manifest)


def test_v03_full_verifier_refuses_reissue_from_a_later_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sealed_commit = "a" * 40
    later_commit = "b" * 40
    monkeypatch.setattr(verifier, "_static_gate", lambda _: {})
    monkeypatch.setattr(verifier, "_sealed_release_tree", lambda _: (sealed_commit, {}))
    monkeypatch.setattr(verifier, "_run", lambda _: later_commit)

    with pytest.raises(ReleaseGateError, match="cannot be reissued"):
        verify(DEFAULT_MANIFEST)


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


def test_v04_external_snapshots_bind_bytes_modes_and_symlink_count() -> None:
    manifest = _strict_json(CURRENT_MANIFEST)
    contract = _m2d_contract(manifest)
    before = _external_snapshots_strict(manifest)
    _external_snapshot_matches_contract(contract, before)
    after = _external_snapshots_strict(manifest)

    assert before == after
    assert all(
        set(snapshot)
        == {"exists", "entry_count", "sha256", "metadata_sha256", "symlink_count"}
        for snapshot in before.values()
    )
    assert before["BinancePredictionStrategy"]["exists"] is False


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


def test_v04_release_verifier_executes_all_six_upgrade_subcases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = _strict_json(CURRENT_MANIFEST)
    observed_commands: list[list[str]] = []

    def pass_six(command: list[str]) -> str:
        observed_commands.append(command)
        return "6 passed in 0.10s"

    monkeypatch.setattr(verifier, "_run", pass_six)
    result = _installer_gate(manifest)

    assert result == {"case_ids": list(V04_UPGRADE_CASE_IDS), "passed": 6}
    assert len(observed_commands) == 1
    rendered = " ".join(observed_commands[0])
    assert "test_v04_managed_upgrade_subcase" in rendered
    assert all(case_id in rendered for case_id in V04_UPGRADE_CASE_IDS)


def test_release_verifier_rejects_an_alternate_manifest_path(tmp_path: Path) -> None:
    alternate = tmp_path / "manifest.json"
    alternate.write_text(CURRENT_MANIFEST.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ReleaseGateError, match="alternate manifest forbidden"):
        verify(alternate)
