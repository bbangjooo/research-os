from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from research_os.contracts.common import sha256_json
from research_os.errors import ScientificStateError
from research_os.kernel.ids import new_experiment_id
from research_os.science import (
    EvaluationSeal,
    Proposal,
    StudyContract,
    plan_generation_open,
    proposal_id,
    reduce_scientific_state,
    registration_payload_fields,
    reserve_registration,
    validate_registration,
)

FIXTURES = Path(__file__).parent / "fixtures" / "scientific_state" / "v2"
PROJECT_ID = "fixture-m1c"
ROOT_CANDIDATE = {"x": 2.0, "y": 1.0}


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


def _open() -> tuple[list[dict[str, Any]], Any]:
    contract = StudyContract.from_mapping(_load("m1c-contract.json"))
    seal = EvaluationSeal.from_mapping(_load("manifest.json")["fixtures"]["evaluation_seal"])
    plan = plan_generation_open(
        [],
        project_id=PROJECT_ID,
        contract=contract,
        evaluation_seal=seal,
    )
    events = [_event(plan.event_type, plan.payload)]
    return events, reduce_scientific_state(events, project_id=PROJECT_ID)


def _scope(state: Any, scope_id: str) -> Any:
    assert state.contract is not None
    return next(scope for scope in state.contract.evaluation_scopes if scope.id == scope_id)


def _baseline_payload(
    state: Any,
    scope_id: str,
    *,
    baseline_id: str | None = None,
) -> dict[str, Any]:
    scope = _scope(state, scope_id)
    assert state.contract is not None
    assert state.evaluation_seal is not None
    return {
        "baseline_id": baseline_id or f"base_{scope_id}",
        "compatibility_digest": state.evaluation_seal.compatibility_digest,
        "science_state_version": 1,
        "generation_id": state.active_generation_id,
        "study_contract_digest": state.contract.digest,
        "evaluation_seal_digest": state.evaluation_seal.digest,
        "evaluation_scope_id": scope.id,
        "evaluation_scope": scope.to_dict(),
        "authorized_action": None,
    }


def _add_baseline(
    events: list[dict[str, Any]],
    state: Any,
    scope_id: str,
    *,
    baseline_id: str | None = None,
) -> Any:
    events.append(
        _event(
            "BASELINE_RECORDED",
            _baseline_payload(state, scope_id, baseline_id=baseline_id),
        )
    )
    return reduce_scientific_state(events, project_id=PROJECT_ID)


def _registration_payload(
    state: Any,
    candidate: dict[str, Any],
    proposal_raw: dict[str, Any],
    *,
    attempt: int = 1,
    retry_of: str | None = None,
    baseline_id: str | None = None,
) -> dict[str, Any]:
    proposal = Proposal.from_mapping(proposal_raw)
    candidate_digest = sha256_json(candidate)
    proposal_digest = proposal.digest
    assert state.evaluation_seal is not None
    selected_baseline = state.baseline_for_scope(proposal.evaluation_scope_id)
    selected_baseline_id = (
        baseline_id
        if baseline_id is not None
        else None
        if selected_baseline is None
        else selected_baseline.baseline_id
    )
    experiment_id = new_experiment_id(
        PROJECT_ID,
        candidate_digest,
        parent_id=proposal.parent_experiment_id,
        compatibility_digest=state.evaluation_seal.compatibility_digest,
        generation_id=proposal.generation_id,
        evaluation_scope_id=proposal.evaluation_scope_id,
        attempt=attempt,
    )
    return {
        "experiment_id": experiment_id,
        "candidate": copy.deepcopy(candidate),
        "candidate_digest": candidate_digest,
        "parent_id": proposal.parent_experiment_id,
        "compatibility_digest": state.evaluation_seal.compatibility_digest,
        "baseline_id": selected_baseline_id,
        "attempt": attempt,
        "retry_of": retry_of,
        "authorized_action": None,
        "proposal": proposal.to_dict(),
        "proposal_digest": proposal_digest,
        "proposal_id": proposal_id(PROJECT_ID, proposal_digest),
        "evaluation_scope_id": proposal.evaluation_scope_id,
        **registration_payload_fields(state, retry_of=retry_of),
    }


def _append_registration(
    events: list[dict[str, Any]],
    state: Any,
    payload: dict[str, Any],
) -> Any:
    events.append(_event("EXPERIMENT_REGISTERED", payload))
    return reduce_scientific_state(events, project_id=PROJECT_ID)


def _terminate(
    events: list[dict[str, Any]],
    state: Any,
    experiment_id: str,
    status: str,
    *,
    retryable: bool,
) -> Any:
    registration = state.registration(experiment_id)
    assert registration is not None
    events.append(
        _event(
            "EXPERIMENT_TERMINATED",
            {
                "experiment_id": experiment_id,
                "status": status,
                "attempt": registration.attempt,
                "retry_of": registration.retry_of,
                "retryable": retryable,
                "authorized_action": None,
            },
        )
    )
    return reduce_scientific_state(events, project_id=PROJECT_ID)


def _assert_code(code: str, operation: Any) -> ScientificStateError:
    with pytest.raises(ScientificStateError) as caught:
        operation()
    assert caught.value.code == code
    return caught.value


def test_v1_state_shape_and_digest_remain_exact() -> None:
    oracle = _load("m1b-v1-compat-oracle.json")["expected"]
    path = FIXTURES / "m1b-v1-generation-events.jsonl"
    events = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    state = reduce_scientific_state(
        events,
        project_id="fixture-m1c-v1-compat",
    )

    assert sha256_json(state.to_dict()) == oracle["science_state_sorted_compact_digest"]
    assert "proposal_count" not in state.to_dict()
    assert "replication_count" not in state.to_dict()
    assert "used_candidate_scope_pairs" not in state.to_dict()


def test_v2_baseline_registration_terminal_and_conditional_state_replay() -> None:
    manifest = _load("manifest.json")["fixtures"]
    events, state = _open()
    state = _add_baseline(
        events,
        state,
        "development",
        baseline_id=manifest["development_baseline_workspace_id"],
    )
    payload = _registration_payload(
        state,
        ROOT_CANDIDATE,
        _load("m1c-proposal-explore.json"),
    )
    validate_registration(state, payload)
    state = _append_registration(events, state, payload)

    assert payload["experiment_id"] == manifest["explore_experiment_id"]
    assert state.proposal_count == 1
    assert state.replication_count == 0
    assert state.used_candidate_scope_pairs == 1
    assert state.to_dict()["proposal_count"] == 1
    assert state.registration(payload["experiment_id"]) is not None

    state = _terminate(
        events,
        state,
        payload["experiment_id"],
        "VALIDATED",
        retryable=False,
    )
    root = state.registration(payload["experiment_id"])
    assert root is not None
    assert root.terminal_status == "VALIDATED"
    assert root.retryable is False
    assert reduce_scientific_state(events, project_id=PROJECT_ID) == state


def test_replication_and_retry_inherit_canonical_proposal_without_double_counting() -> None:
    manifest = _load("manifest.json")["fixtures"]
    events, state = _open()
    state = _add_baseline(events, state, "development")
    root_payload = _registration_payload(
        state,
        ROOT_CANDIDATE,
        _load("m1c-proposal-explore.json"),
    )
    state = _append_registration(events, state, root_payload)
    state = _terminate(
        events,
        state,
        root_payload["experiment_id"],
        "VALIDATED",
        retryable=False,
    )
    state = _add_baseline(
        events,
        state,
        "replication-1",
        baseline_id=manifest["replication_1_baseline_workspace_id"],
    )
    replication_proposal = _load("m1c-proposal-replicate.json")
    replication_payload = _registration_payload(
        state,
        ROOT_CANDIDATE,
        replication_proposal,
    )
    state = _append_registration(events, state, replication_payload)
    assert replication_payload["experiment_id"] == manifest["replication_1_experiment_id"]
    assert state.proposal_count == 2
    assert state.replication_count == 1
    assert state.used_candidate_scope_pairs == 2

    state = _terminate(
        events,
        state,
        replication_payload["experiment_id"],
        "TIMED_OUT",
        retryable=True,
    )
    retry_payload = _registration_payload(
        state,
        ROOT_CANDIDATE,
        replication_proposal,
        attempt=2,
        retry_of=replication_payload["experiment_id"],
    )
    state = _append_registration(events, state, retry_payload)

    assert retry_payload["experiment_id"] == manifest["replication_1_retry_experiment_id"]
    assert state.attempts_used == 3
    assert state.retries_used == 1
    assert state.proposal_count == 2
    assert state.replication_count == 1
    assert state.used_candidate_scope_pairs == 2


def test_same_candidate_scope_first_attempt_is_atomically_unique() -> None:
    events, state = _open()
    state = _add_baseline(events, state, "development")
    payload = _registration_payload(
        state,
        ROOT_CANDIDATE,
        _load("m1c-proposal-explore.json"),
    )
    winner = reserve_registration(state, payload)

    validate_registration(state, payload)
    error = _assert_code(
        "PROPOSAL_EVALUATION_SCOPE_REUSED",
        lambda: reserve_registration(winner, payload),
    )
    assert error.details["evaluation_scope_id"] == "development"
    assert winner.attempts_used == 1


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("candidate_body", "CANDIDATE_DIGEST_MISMATCH"),
        ("proposal_body", "PROPOSAL_DIGEST_MISMATCH"),
        ("proposal_digest", "PROPOSAL_DIGEST_MISMATCH"),
        ("proposal_id", "PROPOSAL_ID_MISMATCH"),
        ("experiment_id", "EXPERIMENT_ID_MISMATCH"),
        ("partial_bundle", "STUDY_REGISTRATION_INVALID"),
    ],
)
def test_forgery_and_partial_bundle_error_order_is_stable(
    mutation: str,
    expected_code: str,
) -> None:
    events, state = _open()
    state = _add_baseline(events, state, "development")
    payload = _registration_payload(
        state,
        ROOT_CANDIDATE,
        _load("m1c-proposal-explore.json"),
    )
    if mutation == "candidate_body":
        payload["candidate"]["x"] = 3.0
    elif mutation == "proposal_body":
        payload["proposal"]["mechanism"] = "Forged mechanism."
    elif mutation == "proposal_digest":
        payload["proposal_digest"] = "0" * 64
    elif mutation == "proposal_id":
        payload["proposal_id"] = f"proposal_{'0' * 32}"
    elif mutation == "experiment_id":
        payload["experiment_id"] = f"exp_{'0' * 32}"
    else:
        payload.pop("proposal_digest")

    live = _assert_code(expected_code, lambda: validate_registration(state, payload))
    replay = _assert_code(
        expected_code,
        lambda: reduce_scientific_state(
            [*events, _event("EXPERIMENT_REGISTERED", payload)],
            project_id=PROJECT_ID,
        ),
    )
    assert live.details == replay.details
    assert state.attempts_used == 0


def test_actual_candidate_diff_and_declared_intervention_must_match() -> None:
    events, state = _open()
    state = _add_baseline(events, state, "development")
    state = _add_baseline(events, state, "diagnostic-1")
    root_payload = _registration_payload(
        state,
        ROOT_CANDIDATE,
        _load("m1c-proposal-explore.json"),
    )
    state = _append_registration(events, state, root_payload)
    state = _terminate(
        events,
        state,
        root_payload["experiment_id"],
        "VALIDATED",
        retryable=False,
    )
    candidate = {"x": 2.0, "y": 2.0}
    proposal = _load("m1c-proposal-explore.json")
    proposal.update(
        {
            "action": "exploit",
            "candidate_digest": sha256_json(candidate),
            "parent_experiment_id": root_payload["experiment_id"],
            "evaluation_scope_id": "diagnostic-1",
            "intervention_json_pointers": ["/x"],
        }
    )
    payload = _registration_payload(state, candidate, proposal)

    error = _assert_code(
        "PROPOSAL_INTERVENTION_MISMATCH",
        lambda: validate_registration(state, payload),
    )
    assert error.details == {
        "declared_json_pointers": ["/x"],
        "observed_json_pointers": ["/y"],
    }


def test_unscoped_baseline_replays_but_cannot_authorize_typed_registration() -> None:
    events, state = _open()
    unscoped = _baseline_payload(state, "development")
    unscoped.pop("evaluation_scope_id")
    unscoped.pop("evaluation_scope")
    events.append(_event("BASELINE_RECORDED", unscoped))
    state = reduce_scientific_state(events, project_id=PROJECT_ID)
    assert state.scope_baselines == ()

    payload = _registration_payload(
        state,
        ROOT_CANDIDATE,
        _load("m1c-proposal-explore.json"),
        baseline_id=unscoped["baseline_id"],
    )
    _assert_code(
        "STUDY_SCOPE_BASELINE_REQUIRED",
        lambda: validate_registration(state, payload),
    )


def test_successor_generation_resets_all_typed_ledgers() -> None:
    events, state = _open()
    state = _add_baseline(events, state, "development")
    payload = _registration_payload(
        state,
        ROOT_CANDIDATE,
        _load("m1c-proposal-explore.json"),
    )
    state = _append_registration(events, state, payload)
    assert state.proposal_count == 1

    changed_raw = _load("m1c-contract.json")
    changed_raw["budget"]["max_attempts"] = 13
    successor = plan_generation_open(
        events,
        project_id=PROJECT_ID,
        contract=StudyContract.from_mapping(changed_raw),
        evaluation_seal=state.evaluation_seal,
        predecessor_generation_id=state.active_generation_id,
        change_reason="Increase the preregistered attempt ceiling.",
    )
    events.append(_event(successor.event_type, successor.payload))
    reset = reduce_scientific_state(events, project_id=PROJECT_ID)

    assert reset.generation_count == 2
    assert reset.attempts_used == 0
    assert reset.scope_baselines == ()
    assert reset.registrations == ()
    assert reset.proposal_count == 0
    assert reset.replication_count == 0
    assert reset.used_candidate_scope_pairs == 0
