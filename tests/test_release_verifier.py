from __future__ import annotations

import sys

import pytest

from scripts.verify_release import (
    DEFAULT_MANIFEST,
    ReleaseGateError,
    _pytest_counts,
    _run,
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
    assert observed["external_project_path_references"] == 0
    assert observed["external_projects_mode"] == "read-only-no-live-migration"
    assert observed["product_multi_agent"] is False


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
