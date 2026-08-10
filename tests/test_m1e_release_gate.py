from __future__ import annotations

import hashlib
import json
import tomllib
from pathlib import Path
from unittest import mock

import pytest

from research_os import __version__, agent_install
from research_os.agent import build_agent_context
from research_os.contracts import canonical_json_bytes
from research_os.errors import ScientificStateError
from research_os.science import StudyContract, reduce_scientific_state, reserve_registration
from tests.m1d_support.transition_observer import observe_transition_gate_rows
from tests.test_m1b_manifest_oracle import (
    _load_object,
    _observe_manifest_case,
    _opened_state,
    _registration,
    _science_event,
)
from tests.test_m1d_service_cli import _fixture_diagnosis, _service_with_history

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


def _canonical_equal(left: object, right: object) -> bool:
    return canonical_json_bytes(left) == canonical_json_bytes(right)


def _release_cases(release: dict[str, object]) -> list[dict[str, object]]:
    tokenless = release["tokenless_v2"]
    assert isinstance(tokenless, dict)
    cases = tokenless["cases"]
    assert isinstance(cases, list)
    assert all(isinstance(case, dict) for case in cases)
    return cases


def _proposal_required_observation(tmp_path: Path) -> dict[str, object]:
    project, service, _ = _service_with_history(tmp_path)
    service.record_diagnosis(_fixture_diagnosis("retryable-timeout"))
    candidate_path = project / "candidate-missing-proposal.json"
    candidate_path.write_text('{"x":9}\n', encoding="utf-8")
    before_events = service.event_log.read()
    before_status = service.study_status()

    with mock.patch.object(
        service,
        "_doctor",
        side_effect=AssertionError("doctor must not run for a missing Proposal"),
    ) as doctor:
        with pytest.raises(ScientificStateError) as caught:
            service.run_once(candidate_path)

    after_events = service.event_log.read()
    after_status = service.study_status()
    doctor.assert_not_called()
    assert _canonical_equal(after_status, before_status)
    return {
        "error_code": caught.value.code,
        "appended": len(after_events) != len(before_events),
        "event_delta": len(after_events) - len(before_events),
        "budget_delta": 0 if after_status["budget"] == before_status["budget"] else 1,
    }


def _transition_observations() -> dict[str, dict[str, object]]:
    fixture_root = ROOT / "tests" / "fixtures" / "scientific_state" / "v3"
    matrix = _json(fixture_root / "m1d-transition-matrix.json")
    rows = matrix["gate_cases"]
    assert isinstance(rows, list)
    observed = observe_transition_gate_rows({"fixture": "m1d-transition-matrix.json"}, fixture_root)
    assert len(observed) == len(rows)
    result: dict[str, dict[str, object]] = {}
    for row, outcome in zip(rows, observed, strict=True):
        assert isinstance(row, dict)
        expected = row["expected"]
        assert isinstance(expected, dict)
        exact_observed = {
            "accepted": outcome["accepted"],
            "appended": outcome["appended"],
            "error_code": outcome["error_code"],
            "deltas": outcome["deltas"],
        }
        exact_expected = {
            "accepted": expected["accepted"],
            "appended": expected["appended"],
            "error_code": expected["error_code"],
            "deltas": expected["deltas"],
        }
        assert _canonical_equal(exact_observed, exact_expected)
        inputs = row["input"]
        assert isinstance(inputs, dict)
        result[str(row["id"])] = {
            **outcome,
            "executed_path": str(inputs["operation"]).replace("_", "-"),
        }
    return result


def _release_transition_observation(outcome: dict[str, object]) -> dict[str, object]:
    deltas = outcome["deltas"]
    assert isinstance(deltas, dict)
    budget_keys = {
        "budget_attempts",
        "budget_retries",
        "budget_elapsed_milliseconds",
        "budget_cost_microunits",
    }
    return {
        "error_code": outcome["error_code"],
        "appended": outcome["appended"],
        "event_delta": deltas["canonical_events"],
        "budget_delta": sum(abs(int(deltas[key])) for key in budget_keys),
    }


def _budget_reservation_observation(case: dict[str, object]) -> dict[str, object]:
    inputs = case["input"]
    assert isinstance(inputs, dict)
    raw_contract = _load_object("m1b-contract.json")
    override = inputs.get("contract_override", {})
    assert isinstance(override, dict)
    budget = raw_contract["budget"]
    assert isinstance(budget, dict)
    budget.update(override)
    contract = StudyContract.from_mapping(raw_contract)
    events, state = _opened_state(contract=contract)
    prior_attempts = int(inputs.get("prior_attempts", 0))
    prior_retries = int(inputs.get("prior_retries", 0))
    for index in range(prior_attempts):
        retry = index >= prior_attempts - prior_retries
        payload = _registration(
            state,
            experiment_id=f"exp_release_prior_{index}",
            retry_of="exp_release_prior_0" if retry else None,
            attempt=2 if retry else 1,
        )
        state = reserve_registration(state, payload)
    proposed_retry = inputs.get("retry") is True
    proposed = _registration(
        state,
        experiment_id="exp_release_budget_overrun",
        retry_of="exp_release_prior_last" if proposed_retry else None,
        attempt=2 if proposed_retry else 1,
    )
    before_events = len(events)
    before_state = state.to_dict()
    with pytest.raises(ScientificStateError) as caught:
        reserve_registration(state, proposed)
    after_state = state.to_dict()
    assert _canonical_equal(after_state, before_state)
    return {
        "error_code": caught.value.code,
        "appended": len(events) != before_events,
        "event_delta": len(events) - before_events,
        "budget_delta": 0 if after_state["budget"] == before_state["budget"] else 1,
    }


def _legacy_replay_observation() -> dict[str, object]:
    legacy = _science_event(
        "EXPERIMENT_REGISTERED",
        {"experiment_id": "exp_release_legacy", "authorized_action": None},
    )
    state = reduce_scientific_state([legacy], project_id="fixture-m1b")
    return {
        "active_generation_id": state.active_generation_id,
        "legacy_unstructured_registrations": state.legacy_unstructured_registrations,
        "typed_registration_count": len(state.registrations),
        "proposal_count": state.proposal_count,
        "diagnosis_count": state.diagnosis_count,
        "class_state_count": len(state.class_states),
    }


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
        Path(path): (record["size_bytes"], record["sha256"]) for path, record in raw_files.items()
    }
    assert agent_install._KNOWN_MANAGED_RELEASE_FILES == {"0.2.0": expected}
    assert agent_install._KNOWN_MANAGED_RELEASE_DIRECTORIES == frozenset(
        Path(path) for path in upgrade["directories"]
    )


def test_v03_release_manifest_binds_v1_bytes_and_tokenless_gate_oracles(
    tmp_path: Path,
) -> None:
    release = _json(RELEASE_MANIFEST)
    compatibility = release["compatibility"]
    assert isinstance(compatibility, dict)
    for key in ("legacy_v1_events", "scientific_state_v1_manifest"):
        record = compatibility[key]
        assert isinstance(record, dict)
        content = (ROOT / record["path"]).read_bytes()
        assert len(content) == record["size_bytes"]
        assert hashlib.sha256(content).hexdigest() == record["sha256"]

    tokenless = release["tokenless_v2"]
    assert isinstance(tokenless, dict)
    cases = _release_cases(release)
    assert len(cases) == 7
    assert len({case["id"] for case in cases}) == 7
    transition_observed = _transition_observations()
    v1_manifest = _json(ROOT / "tests" / "fixtures" / "scientific_state" / "v1" / "manifest.json")
    observed_by_release_id: dict[str, dict[str, object]] = {}
    executed_path_by_release_id: dict[str, str] = {}
    for case in cases:
        observer = case["observer"]
        release_id = str(case["id"])
        if observer == "live-service":
            observed_by_release_id[release_id] = _proposal_required_observation(
                tmp_path / release_id
            )
            executed_path_by_release_id[release_id] = "register-first-attempt"
        elif observer == "m1d-transition":
            source_case_id = str(case["source_case_id"])
            transition_outcome = transition_observed[source_case_id]
            observed_by_release_id[release_id] = _release_transition_observation(
                transition_outcome
            )
            executed_path_by_release_id[release_id] = str(
                transition_outcome["executed_path"]
            )
        else:
            source_case_id = str(case["source_case_id"])
            source_case = _case_by_id(v1_manifest, source_case_id)
            source_observed = _observe_manifest_case(source_case, tmp_path / release_id)
            assert _canonical_equal(source_observed, source_case["expected"])
            executed_path_by_release_id[release_id] = str(
                source_case["operation"]
            ).replace("_", "-")
            if observer == "m1b-budget-reservation":
                observed_by_release_id[release_id] = _budget_reservation_observation(source_case)
            elif observer == "m1b-legacy-replay":
                observed_by_release_id[release_id] = _legacy_replay_observation()
            else:
                raise AssertionError(f"unknown release observer: {observer}")

    expected_by_release_id = {str(case["id"]): case["expected"] for case in cases}
    assert set(observed_by_release_id) == set(expected_by_release_id)
    assert _canonical_equal(observed_by_release_id, expected_by_release_id)
    assert executed_path_by_release_id == {
        str(case["id"]): case["path"] for case in cases
    }

    assert set(tokenless["required_no_write_codes"]) == {
        "BUDGET_ATTEMPTS_EXCEEDED",
        "DIAGNOSIS_REQUIRED",
        "HYPOTHESIS_CLASS_CLOSED",
        "PROPOSAL_REQUIRED",
    }
    observed_codes = {
        outcome["error_code"]
        for outcome in observed_by_release_id.values()
        if "error_code" in outcome
    }
    assert observed_codes == set(tokenless["required_no_write_codes"])
