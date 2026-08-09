from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from research_os.errors import ScientificStateError
from research_os.science import (
    EvaluationSeal,
    StudyContract,
    plan_generation_open,
    reduce_scientific_state,
    registration_payload_fields,
    reserve_registration,
)

FIXTURES = Path(__file__).parent / "fixtures" / "scientific_state" / "v1"
PROJECT_ID = "fixture-m1b"


def _load(name: str) -> dict[str, Any]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_type": event_type,
        "project_id": PROJECT_ID,
        "payload": payload,
    }


def _contract(**budget_overrides: Any) -> StudyContract:
    raw = _load("m1b-contract.json")
    raw["budget"].update(budget_overrides)
    return StudyContract.from_mapping(raw)


def _seal() -> EvaluationSeal:
    return EvaluationSeal.from_mapping(_load("manifest.json")["fixtures"]["evaluation_seal"])


def _opened(
    contract: StudyContract | None = None,
) -> tuple[list[dict[str, Any]], Any]:
    selected = _contract() if contract is None else contract
    plan = plan_generation_open(
        [],
        project_id=PROJECT_ID,
        contract=selected,
        evaluation_seal=_seal(),
    )
    events = [_event(plan.event_type, plan.payload)]
    return events, reduce_scientific_state(events, project_id=PROJECT_ID)


def _registration(
    state: Any,
    *,
    experiment_id: str,
    retry_of: str | None = None,
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "retry_of": retry_of,
        "authorized_action": None,
        **registration_payload_fields(state, retry_of=retry_of),
    }


def _assert_code(code: str, operation: Any) -> ScientificStateError:
    with pytest.raises(ScientificStateError) as caught:
        operation()
    assert caught.value.code == code
    return caught.value


def test_first_idempotent_and_successor_generation_oracles_are_exact() -> None:
    manifest = _load("manifest.json")["fixtures"]
    contract = _contract()
    seal = _seal()
    first = plan_generation_open(
        [], project_id=PROJECT_ID, contract=contract, evaluation_seal=seal
    )
    assert first.append_required is True
    assert first.generation_id == manifest["first_generation_id"]
    assert first.payload["authorized_action"] is None
    events = [_event(first.event_type, first.payload)]

    identical = plan_generation_open(
        events, project_id=PROJECT_ID, contract=contract, evaluation_seal=seal
    )
    assert identical.append_required is False
    assert identical.generation_id == first.generation_id

    _assert_code(
        "STUDY_GENERATION_UNCHANGED",
        lambda: plan_generation_open(
            events,
            project_id=PROJECT_ID,
            contract=contract,
            evaluation_seal=seal,
            predecessor_generation_id=first.generation_id,
            change_reason="Attempt to reset an unchanged generation budget.",
        ),
    )
    successor_contract = _contract(max_attempts=5)
    successor = plan_generation_open(
        events,
        project_id=PROJECT_ID,
        contract=successor_contract,
        evaluation_seal=seal,
        predecessor_generation_id=first.generation_id,
        change_reason="Increase the preregistered attempt budget after evaluator review.",
    )
    assert successor.contract.digest == manifest["successor_contract_digest"]
    assert successor.generation_id == manifest["successor_generation_id"]
    alternative = plan_generation_open(
        events,
        project_id=PROJECT_ID,
        contract=_contract(max_attempts=6),
        evaluation_seal=seal,
        predecessor_generation_id=first.generation_id,
        change_reason="Use the alternate preregistered successor budget.",
    )
    assert alternative.generation_id == (
        "generation_64218dec5982640fd914612fd6734c10"
    )
    successor_state = reduce_scientific_state(
        [*events, _event(successor.event_type, successor.payload)],
        project_id=PROJECT_ID,
    )
    assert successor_state.active_generation_id == successor.generation_id
    assert successor_state.generation_count == 2


def test_generation_planner_revalidates_instances_and_closes_under_replay() -> None:
    contract = _contract()
    plan = plan_generation_open(
        [],
        project_id=PROJECT_ID,
        contract=contract,
        evaluation_seal=_seal(),
    )
    replayed = reduce_scientific_state(
        [_event(plan.event_type, plan.payload)],
        project_id=PROJECT_ID,
    )
    assert replayed.contract == contract

    invalid = replace(contract, schema_version=2)
    _assert_code(
        "STUDY_CONTRACT_INVALID",
        lambda: plan_generation_open(
            [],
            project_id=PROJECT_ID,
            contract=invalid,
            evaluation_seal=_seal(),
        ),
    )


def test_generation_event_requires_the_exact_canonical_identifier() -> None:
    events, _ = _opened()
    malformed = copy.deepcopy(events[0])
    malformed["payload"]["generation_id"] = (
        f" {malformed['payload']['generation_id']} "
    )
    _assert_code(
        "STUDY_GENERATION_INVALID",
        lambda: reduce_scientific_state([malformed], project_id=PROJECT_ID),
    )


def test_successor_missing_reason_and_stale_predecessor_are_stable() -> None:
    events, state = _opened()
    changed = _contract(max_attempts=5)
    assert state.active_generation_id is not None
    _assert_code(
        "STUDY_CHANGE_REASON_REQUIRED",
        lambda: plan_generation_open(
            events,
            project_id=PROJECT_ID,
            contract=changed,
            evaluation_seal=_seal(),
            predecessor_generation_id=state.active_generation_id,
        ),
    )
    _assert_code(
        "STUDY_GENERATION_MISMATCH",
        lambda: plan_generation_open(
            events,
            project_id=PROJECT_ID,
            contract=changed,
            evaluation_seal=_seal(),
            predecessor_generation_id=(
                "generation_00000000000000000000000000000000"
            ),
            change_reason="Attempt a stale successor.",
        ),
    )


def test_legacy_before_generation_is_opaque_but_after_generation_fails_closed() -> None:
    legacy = _event(
        "EXPERIMENT_REGISTERED",
        {"experiment_id": "exp_legacy", "authorized_action": None},
    )
    legacy_state = reduce_scientific_state([legacy], project_id=PROJECT_ID)
    assert legacy_state.active_generation_id is None
    assert legacy_state.legacy_unstructured_registrations == 1

    events, _ = _opened()
    _assert_code(
        "STUDY_GENERATION_REQUIRED",
        lambda: reduce_scientific_state([*events, legacy], project_id=PROJECT_ID),
    )
    partial = copy.deepcopy(legacy)
    partial["payload"]["generation_id"] = (
        "generation_b87daa35b5f8e5593fe0c4f5d245f8a6"
    )
    _assert_code(
        "STUDY_REGISTRATION_INVALID",
        lambda: reduce_scientific_state([*events, partial], project_id=PROJECT_ID),
    )


def test_all_terminal_statuses_consume_and_never_refund_reserved_budget() -> None:
    events, state = _opened()
    registrations = [
        _registration(state, experiment_id="exp_invalid"),
        _registration(state, experiment_id="exp_infra"),
        _registration(state, experiment_id="exp_retry", retry_of="exp_infra"),
        _registration(state, experiment_id="exp_rejected"),
    ]
    statuses = [
        "INVALID_EXPERIMENT",
        "INFRA_FAILED",
        "INSUFFICIENT_EVIDENCE",
        "REJECTED",
    ]
    sequence = list(events)
    for registration, status in zip(registrations, statuses, strict=True):
        sequence.append(_event("EXPERIMENT_REGISTERED", registration))
        sequence.append(
            _event(
                "EXPERIMENT_TERMINATED",
                {
                    "experiment_id": registration["experiment_id"],
                    "status": status,
                },
            )
        )
    reduced = reduce_scientific_state(sequence, project_id=PROJECT_ID)
    budget = reduced.to_dict()["budget"]
    assert budget == {
        "attempts": {"limit": 4, "used": 4, "remaining": 0},
        "retries": {"limit": 1, "used": 1, "remaining": 0},
        "elapsed_milliseconds": {
            "limit": 4000,
            "reserved": 4000,
            "remaining": 0,
        },
        "cost_microunits": {
            "unit": "USD_MICRO",
            "limit": 10000,
            "reserved": 10000,
            "remaining": 0,
        },
    }


def test_null_cost_contract_keeps_the_entire_cost_ledger_null() -> None:
    contract = _contract(
        cost_unit=None,
        max_cost_microunits=None,
        cost_reservation_per_attempt_microunits=None,
    )
    events, state = _opened(contract)
    registration = _registration(state, experiment_id="exp_null_cost")
    assert registration["budget_debit"]["reserved_cost_microunits"] is None
    reduced = reduce_scientific_state(
        [*events, _event("EXPERIMENT_REGISTERED", registration)],
        project_id=PROJECT_ID,
    )
    assert reduced.to_dict()["budget"]["cost_microunits"] is None


@pytest.mark.parametrize(
    ("dimension", "contract_overrides", "prior_retries", "expected_code"),
    [
        ("attempts", {}, 0, "BUDGET_ATTEMPTS_EXCEEDED"),
        ("retries", {}, 1, "BUDGET_RETRIES_EXCEEDED"),
        (
            "elapsed",
            {"max_elapsed_milliseconds": 1500},
            0,
            "BUDGET_ELAPSED_EXCEEDED",
        ),
        (
            "cost",
            {"max_cost_microunits": 4000},
            0,
            "BUDGET_COST_EXCEEDED",
        ),
    ],
)
def test_dimension_specific_overrun_precedence_is_exact(
    dimension: str,
    contract_overrides: dict[str, Any],
    prior_retries: int,
    expected_code: str,
) -> None:
    events, state = _opened(_contract(**contract_overrides))
    if dimension == "attempts":
        for index in range(4):
            payload = _registration(state, experiment_id=f"exp_prior_{index}")
            state = reserve_registration(state, payload)
    elif dimension == "retries":
        state = reserve_registration(
            state, _registration(state, experiment_id="exp_prior_ordinary")
        )
        state = reserve_registration(
            state,
            _registration(
                state,
                experiment_id="exp_prior_retry",
                retry_of="exp_prior_ordinary",
            ),
        )
    else:
        state = reserve_registration(
            state, _registration(state, experiment_id="exp_prior")
        )
    proposed = _registration(
        state,
        experiment_id="exp_overrun",
        retry_of=("exp_prior_retry" if prior_retries else None),
    )
    error = _assert_code(expected_code, lambda: reserve_registration(state, proposed))
    assert error.details["dimension"] in {
        "attempts",
        "retries",
        "elapsed_milliseconds",
        "cost_microunits",
    }


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("unbound", "STUDY_GENERATION_REQUIRED"),
        ("partial", "STUDY_REGISTRATION_INVALID"),
        ("contract", "STUDY_CONTRACT_MISMATCH"),
        ("seal", "STUDY_EVALUATION_SEAL_MISMATCH"),
        ("generation", "STUDY_GENERATION_MISMATCH"),
        ("debit", "STUDY_REGISTRATION_INVALID"),
        ("attempts_overrun", "BUDGET_ATTEMPTS_EXCEEDED"),
    ],
)
def test_malformed_direct_append_matrix_fails_closed(
    mutation: str,
    expected_code: str,
) -> None:
    events, state = _opened()
    payload = _registration(state, experiment_id=f"exp_{mutation}")
    if mutation == "unbound":
        for key in tuple(registration_payload_fields(state, retry_of=None)):
            payload.pop(key)
    elif mutation == "partial":
        for key in tuple(registration_payload_fields(state, retry_of=None)):
            if key != "generation_id":
                payload.pop(key)
    elif mutation == "contract":
        payload["study_contract_digest"] = "9" * 64
    elif mutation == "seal":
        payload["evaluation_seal_digest"] = "9" * 64
    elif mutation == "generation":
        payload["generation_id"] = (
            "generation_00000000000000000000000000000000"
        )
    elif mutation == "debit":
        payload["budget_debit"]["attempts"] = 0
    sequence = list(events)
    if mutation == "attempts_overrun":
        for index in range(4):
            sequence.append(
                _event(
                    "EXPERIMENT_REGISTERED",
                    _registration(state, experiment_id=f"exp_prior_{index}"),
                )
            )
    _assert_code(
        expected_code,
        lambda: reduce_scientific_state(
            [*sequence, _event("EXPERIMENT_REGISTERED", payload)],
            project_id=PROJECT_ID,
        ),
    )


def test_live_candidate_and_cold_replay_use_the_same_state_and_failure_code() -> None:
    events, live = _opened()
    ordinary = _registration(live, experiment_id="exp_ordinary")
    live = reserve_registration(live, ordinary)
    retry = _registration(
        live,
        experiment_id="exp_retry",
        retry_of="exp_ordinary",
    )
    live = reserve_registration(live, retry)
    persisted = [
        *events,
        _event("EXPERIMENT_REGISTERED", ordinary),
        _event("EXPERIMENT_REGISTERED", retry),
    ]
    cold = reduce_scientific_state(persisted, project_id=PROJECT_ID)
    assert live.to_dict() == cold.to_dict()
    assert live.attempts_used == 2
    assert live.retries_used == 1
    assert live.elapsed_reserved_milliseconds == 2000
    assert live.cost_reserved_microunits == 5000

    forbidden = _registration(
        live,
        experiment_id="exp_second_retry",
        retry_of="exp_retry",
    )
    live_error = _assert_code(
        "BUDGET_RETRIES_EXCEEDED",
        lambda: reserve_registration(live, forbidden),
    )
    replay_error = _assert_code(
        "BUDGET_RETRIES_EXCEEDED",
        lambda: reduce_scientific_state(
            [*persisted, _event("EXPERIMENT_REGISTERED", forbidden)],
            project_id=PROJECT_ID,
        ),
    )
    assert live_error.details == replay_error.details
