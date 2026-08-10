from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path

from research_os import __version__, agent_install
from research_os.agent import build_agent_context

ROOT = Path(__file__).resolve().parents[1]
RELEASE_MANIFEST = ROOT / "tests" / "fixtures" / "releases" / "v0.3.0" / "manifest.json"


def _json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _case_by_id(
    manifest: dict[str, object], case_id: str, *, group: str = "cases"
) -> dict[str, object]:
    cases = manifest[group]
    assert isinstance(cases, list)
    selected = next(case for case in cases if case["id"] == case_id)
    assert isinstance(selected, dict)
    return selected


def test_v03_release_manifest_binds_versions_context_and_published_v02_skill() -> None:
    release = _json(RELEASE_MANIFEST)
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))

    assert release["release"] == __version__ == pyproject["project"]["version"] == "0.3.0"
    package = next(row for row in lock["package"] if row["name"] == "research-os")
    assert package["version"] == "0.3.0"

    context_contract = release["context"]
    assert isinstance(context_contract, dict)
    v2 = build_agent_context(
        project={},
        status={},
        lineage=[],
        findings=[],
        artifacts=[],
        agent_spec={},
        snapshot={},
        limit=1,
    )
    assert v2["schema_version"] == context_contract["explicit_legacy_schema_version"]
    assert set(v2) == set(context_contract["context_v2_exact_top_level_keys"])

    upgrade = release["managed_skill_upgrade"]
    assert isinstance(upgrade, dict)
    raw_files = upgrade["files"]
    assert isinstance(raw_files, dict)
    expected = {
        Path(path): (record["size_bytes"], record["sha256"])
        for path, record in raw_files.items()
    }
    assert agent_install._KNOWN_MANAGED_RELEASE_FILES == {"0.2.0": expected}
    assert agent_install._KNOWN_MANAGED_RELEASE_DIRECTORIES == frozenset(
        Path(path) for path in upgrade["directories"]
    )


def test_v03_release_manifest_binds_v1_bytes_and_tokenless_gate_oracles() -> None:
    release = _json(RELEASE_MANIFEST)
    compatibility = release["compatibility"]
    assert isinstance(compatibility, dict)
    for key in ("legacy_v1_events", "scientific_state_v1_manifest"):
        record = compatibility[key]
        assert isinstance(record, dict)
        content = (ROOT / record["path"]).read_bytes()
        assert len(content) == record["size_bytes"]
        assert hashlib.sha256(content).hexdigest() == record["sha256"]

    transition = _json(
        ROOT / "tests" / "fixtures" / "scientific_state" / "v3" / "m1d-transition-matrix.json"
    )
    transition_bindings = {
        "pending-blocks-registration": "pending-blocks-first-attempt",
        "pending-blocks-retry": "pending-blocks-retry",
        "pending-blocks-successor": "pending-blocks-successor",
        "closed-class-blocks-registration": "closed-class-blocks-first-attempt-before-payload",
    }
    tokenless = release["tokenless_v2"]
    assert isinstance(tokenless, dict)
    release_case_ids = set(tokenless["case_ids"])
    for release_id, transition_id in transition_bindings.items():
        assert release_id in release_case_ids
        expected = _case_by_id(
            transition, transition_id, group="gate_cases"
        )["expected"]
        assert isinstance(expected, dict)
        assert expected["accepted"] is False
        assert expected["appended"] is False
        deltas = expected["deltas"]
        assert isinstance(deltas, dict)
        assert set(deltas.values()) == {0}

    v1_manifest = _json(
        ROOT / "tests" / "fixtures" / "scientific_state" / "v1" / "manifest.json"
    )
    budget = _case_by_id(v1_manifest, "budget-attempts-overrun")
    legacy = _case_by_id(v1_manifest, "legacy-registration-before-generation")
    assert budget["expected"]["error_code"] == "BUDGET_ATTEMPTS_EXCEEDED"
    assert legacy["expected"]["legacy_unstructured_registrations"] == 1

    assert len(tokenless["case_ids"]) == 7
    assert set(tokenless["required_no_write_codes"]) == {
        "BUDGET_ATTEMPTS_EXCEEDED",
        "DIAGNOSIS_REQUIRED",
        "HYPOTHESIS_CLASS_CLOSED",
        "PROPOSAL_REQUIRED",
    }
