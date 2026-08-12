from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from research_os.contracts.common import sha256_json
from research_os.errors import ScientificStateError
from research_os.kernel._canonical import canonical_bytes, sha256_hex
from research_os.kernel.events import Event, verify_events
from research_os.kernel.ids import stable_id
from research_os.science.diagnoses import Diagnosis
from research_os.science.state import (
    plan_diagnosis_append,
    reduce_scientific_state,
    validate_registration,
)

FIXTURES = Path(__file__).parent / "fixtures" / "scientific_state" / "v3"


def _load(name: str) -> dict[str, Any]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _events(raw: list[dict[str, Any]], project_id: str) -> list[Event]:
    events = [Event.from_mapping(item) for item in raw]
    verify_events(events, project_id=project_id)
    return events


def _full_state_case(case_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    matrix = _load("m1d-transition-matrix.json")
    case = next(item for item in matrix["full_state_cases"] if item["id"] == case_id)
    return matrix, case


@pytest.mark.parametrize(
    "case_id",
    [
        "initial-open-generation",
        "terminal-creates-pending",
        "exact-threshold-closes-class",
        "provisional-open",
        "replicated-open",
        "mixed-positive-negative-inconclusive",
        "diagnosis-extension-simultaneous-stop-order",
        "post-close-successful-replication-diagnosis-preserves-replicated-support",
        "minimal-status-changed-alias-timeout-diagnosed",
        "retry-frontier-latest-chain-full-state",
        "class-b-limit-four-n-minus-one-open",
        "class-b-limit-four-exact-threshold-close",
        "class-b-limit-four-post-close-n-plus-one-preserves-origin",
    ],
)
def test_representative_literal_full_states_replay_exactly(case_id: str) -> None:
    matrix, case = _full_state_case(case_id)
    state = reduce_scientific_state(
        _events(case["input"]["event_history"], matrix["project_id"]),
        project_id=matrix["project_id"],
    )

    assert state.to_dict() == case["expected_state"]
    assert sha256_json(state.to_dict()) == case["expected"]["post_state_digest"]


def test_all_canonical_diagnoses_clear_the_exact_pending_obligation() -> None:
    terminal = _load("m1d-terminal-corpus.json")
    valid = _load("m1d-diagnosis-valid.json")
    records = {item["id"]: item for item in terminal["records"]}

    for case in valid["cases"]:
        history = [
            *records[case["terminal_record_id"]]["canonical_history"],
            case["diagnosis_event"],
        ]
        state = reduce_scientific_state(
            _events(history, valid["project_id"]),
            project_id=valid["project_id"],
        )
        assert state.pending_diagnosis_experiment_ids == ()
        assert state.diagnosis_count == 1
        assert state.diagnoses[0].diagnosis_id == case["expected"]["diagnosis_id"]


def test_diagnosis_plan_is_append_then_same_body_idempotent() -> None:
    terminal = _load("m1d-terminal-corpus.json")
    valid = _load("m1d-diagnosis-valid.json")
    case = next(item for item in valid["cases"] if item["id"] == "supported")
    record = next(
        item for item in terminal["records"] if item["id"] == case["terminal_record_id"]
    )
    body = Diagnosis.from_mapping(case["diagnosis_event"]["payload"]["diagnosis"])

    first = plan_diagnosis_append(
        _events(record["canonical_history"], valid["project_id"]),
        project_id=valid["project_id"],
        diagnosis=body,
    )
    second = plan_diagnosis_append(
        _events(
            [*record["canonical_history"], case["diagnosis_event"]],
            valid["project_id"],
        ),
        project_id=valid["project_id"],
        diagnosis=body,
    )

    assert first.append_required is True
    assert second.append_required is False
    assert first.diagnosis_id == second.diagnosis_id == case["expected"]["diagnosis_id"]
    assert second.existing_event_id == case["diagnosis_event"]["event_id"]


def test_persisted_duplicate_diagnosis_after_successor_is_rejected_on_cold_replay() -> None:
    matrix = _load("m1d-transition-matrix.json")
    case = next(
        item
        for item in matrix["gate_cases"]
        if item["id"] == "diagnosed-stop-allows-genuine-changed-successor"
    )
    history = copy.deepcopy(
        [*case["input"]["event_history"], case["expected"]["appended_event"]]
    )
    diagnosis_event = next(
        event
        for event in history
        if event["event_type"] == "research.experiment_diagnosed.v1"
    )
    duplicate = copy.deepcopy(diagnosis_event)
    duplicate["event_id"] = "evt_successor_duplicate_diagnosis_08"
    duplicate["occurred_at"] = "2026-08-10T01:00:08.000000Z"
    history.append(duplicate)
    _rehash(history)

    with pytest.raises(ScientificStateError) as caught:
        reduce_scientific_state(
            _events(history, matrix["project_id"]),
            project_id=matrix["project_id"],
        )

    assert caught.value.code == "DIAGNOSIS_ALREADY_RECORDED"
    assert caught.value.details["path"] == "$.experiment_id"


def _rehash(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous: str | None = None
    for sequence, event in enumerate(history, 1):
        event["sequence"] = sequence
        event["prev_hash"] = previous
        unsigned = dict(event)
        unsigned.pop("hash", None)
        event["hash"] = sha256_hex(canonical_bytes(unsigned))
        previous = event["hash"]
    return history


def test_observation_forgery_has_frozen_code_and_path() -> None:
    terminal = _load("m1d-terminal-corpus.json")
    valid = _load("m1d-diagnosis-valid.json")
    case = next(
        item
        for item in valid["cases"]
        if item["id"] == "conclusive-no-meaningful-improvement"
    )
    record = next(
        item for item in terminal["records"] if item["id"] == case["terminal_record_id"]
    )
    history = copy.deepcopy(
        [*record["canonical_history"], case["diagnosis_event"]]
    )
    payload = history[-1]["payload"]
    payload["diagnosis"]["observation"]["reason_code"] = "FORGED_REASON"
    payload["diagnosis_digest"] = sha256_json(payload["diagnosis"])
    payload["diagnosis_id"] = stable_id(
        "diagnosis", valid["project_id"], payload["diagnosis_digest"]
    )
    _rehash(history)

    with pytest.raises(ScientificStateError) as caught:
        reduce_scientific_state(
            _events(history, valid["project_id"]),
            project_id=valid["project_id"],
        )
    assert caught.value.code == "DIAGNOSIS_OBSERVATION_MISMATCH"
    assert caught.value.details["path"] == "$.observation.reason_code"


@pytest.mark.parametrize("field", ["decision", "result"])
def test_present_null_terminal_evidence_is_not_treated_as_absent(field: str) -> None:
    terminal = _load("m1d-terminal-corpus.json")
    valid = _load("m1d-diagnosis-valid.json")
    case = next(item for item in valid["cases"] if item["id"] == "supported")
    record = next(
        item for item in terminal["records"] if item["id"] == case["terminal_record_id"]
    )
    history = copy.deepcopy([*record["canonical_history"], case["diagnosis_event"]])
    terminal_index = next(
        index
        for index, event in enumerate(history)
        if event["event_type"] == "EXPERIMENT_TERMINATED"
    )
    history[terminal_index]["payload"][field] = None
    _rehash(history)
    diagnosis_payload = history[-1]["payload"]
    diagnosis_payload["diagnosis"]["terminal_evidence"]["event_hash"] = history[
        terminal_index
    ]["hash"]
    diagnosis_payload["diagnosis_digest"] = sha256_json(
        diagnosis_payload["diagnosis"]
    )
    diagnosis_payload["diagnosis_id"] = stable_id(
        "diagnosis",
        valid["project_id"],
        diagnosis_payload["diagnosis_digest"],
    )
    _rehash(history)

    with pytest.raises(ScientificStateError) as caught:
        reduce_scientific_state(
            _events(history, valid["project_id"]),
            project_id=valid["project_id"],
        )
    assert caught.value.code == "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH"
    assert caught.value.details["path"] == f"$.terminal_evidence.{field}"


def test_terminal_result_cannot_declare_kernel_status() -> None:
    terminal = _load("m1d-terminal-corpus.json")
    valid = _load("m1d-diagnosis-valid.json")
    case = next(item for item in valid["cases"] if item["id"] == "supported")
    record = next(
        item for item in terminal["records"] if item["id"] == case["terminal_record_id"]
    )
    history = copy.deepcopy([*record["canonical_history"], case["diagnosis_event"]])
    terminal_index = next(
        index
        for index, event in enumerate(history)
        if event["event_type"] == "EXPERIMENT_TERMINATED"
    )
    history[terminal_index]["payload"]["result"]["status"] = "VALIDATED"
    _rehash(history)
    diagnosis_payload = history[-1]["payload"]
    diagnosis_payload["diagnosis"]["terminal_evidence"]["event_hash"] = history[
        terminal_index
    ]["hash"]
    diagnosis_payload["diagnosis_digest"] = sha256_json(
        diagnosis_payload["diagnosis"]
    )
    diagnosis_payload["diagnosis_id"] = stable_id(
        "diagnosis",
        valid["project_id"],
        diagnosis_payload["diagnosis_digest"],
    )
    _rehash(history)

    with pytest.raises(ScientificStateError) as caught:
        reduce_scientific_state(
            _events(history, valid["project_id"]),
            project_id=valid["project_id"],
        )
    assert caught.value.code == "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH"
    assert caught.value.details["path"] == "$.terminal_evidence.result.status"


@pytest.mark.parametrize(
    ("case_id", "error_code"),
    [
        ("stop-plus-pending-blocks-registration", "STUDY_STOPPED"),
        ("pending-blocks-first-attempt", "DIAGNOSIS_REQUIRED"),
        ("rejected-parent-not-supported", "PROPOSAL_PARENT_NOT_SUPPORTED"),
        ("closed-class-precedes-parent-support-gate", "HYPOTHESIS_CLASS_CLOSED"),
    ],
)
def test_registration_gate_precedence_is_literal(
    case_id: str,
    error_code: str,
) -> None:
    matrix = _load("m1d-transition-matrix.json")
    case = next(item for item in matrix["gate_cases"] if item["id"] == case_id)
    state = reduce_scientific_state(
        _events(case["input"]["event_history"], matrix["project_id"]),
        project_id=matrix["project_id"],
    )

    with pytest.raises(ScientificStateError) as caught:
        validate_registration(state, case["input"]["request"])
    assert caught.value.code == error_code
