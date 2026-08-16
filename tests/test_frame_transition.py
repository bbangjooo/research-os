from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from research_os.contracts import sha256_json
from research_os.errors import ScientificStateError
from research_os.frame_transition import (
    FRAME_POLICY_ADOPTION_EVENT_TYPE,
    POLICY_ADOPTION_POLICY,
    POLICY_ADOPTION_POLICY_DIGEST,
    POLICY_ADOPTION_POLICY_ID,
    classify_frame_change,
    controlled_change_reason,
    plan_adoption_review,
    plan_authority_revocation,
    plan_gate_a,
    plan_inquiry_decision,
    plan_inquiry_open,
    plan_pilot_authorization,
    plan_pilot_result,
    plan_policy_adoption,
    reduce_frame_transition_state,
    validate_controlled_activation,
    validate_frame_transition_commit_time,
)
from research_os.kernel.ids import stable_id
from research_os.science import (
    EvaluationSeal,
    StudyContract,
    plan_generation_open,
    reduce_scientific_state,
)

FIXTURES = Path(__file__).parent / "fixtures" / "scientific_state" / "v1"
PROJECT_ID = "fixture-frame-transition"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _time(minute: int) -> str:
    return f"2026-08-16T00:{minute:02d}:00.000000Z"


def _load(name: str) -> dict[str, Any]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _contract(*, max_attempts: int = 4) -> StudyContract:
    raw = _load("m1b-contract.json")
    raw["budget"]["max_attempts"] = max_attempts
    return StudyContract.from_mapping(raw)


def _seal(*, compatibility_digest: str | None = None) -> EvaluationSeal:
    raw = _load("manifest.json")["fixtures"]["evaluation_seal"]
    if compatibility_digest is not None:
        raw["compatibility_digest"] = compatibility_digest
    return EvaluationSeal.from_mapping(raw)


def _event(
    event_type: str,
    payload: dict[str, Any] | Any,
    *,
    occurred_at: str,
    sequence: int,
) -> dict[str, Any]:
    return {
        "event_id": f"event-{sequence}",
        "event_type": event_type,
        "project_id": PROJECT_ID,
        "occurred_at": occurred_at,
        "payload": copy.deepcopy(dict(payload)),
    }


def _append_plan(events: list[dict[str, Any]], plan: Any) -> None:
    events.append(
        _event(
            plan.event_type,
            plan.payload,
            occurred_at=plan.payload["recorded_at"],
            sequence=len(events) + 1,
        )
    )


def _reseal_receipt(
    payload: dict[str, Any],
    *,
    id_key: str,
    namespace: str,
) -> dict[str, Any]:
    core = {
        key: value
        for key, value in payload.items()
        if key not in {id_key, "recorded_at", "receipt_digest"}
    }
    body = {
        **core,
        id_key: stable_id(namespace, sha256_json(core)),
        "recorded_at": payload["recorded_at"],
    }
    return {**body, "receipt_digest": sha256_json(body)}


def _opened() -> tuple[list[dict[str, Any]], StudyContract, EvaluationSeal]:
    contract = _contract()
    seal = _seal()
    plan = plan_generation_open(
        [],
        project_id=PROJECT_ID,
        contract=contract,
        evaluation_seal=seal,
    )
    return (
        [
            _event(
                plan.event_type,
                plan.payload,
                occurred_at=_time(0),
                sequence=1,
            )
        ],
        contract,
        seal,
    )


def _gate_raw(
    events: list[dict[str, Any]],
    *,
    marker: str,
    recurrent_count: int = 3,
    threshold: int = 2,
    stable: bool = True,
) -> dict[str, Any]:
    state = reduce_frame_transition_state(events, project_id=PROJECT_ID)
    assert state.active_generation_id is not None
    assert state.active_compatibility_digest is not None
    return {
        "schema_version": 1,
        "predecessor_generation_id": state.active_generation_id,
        "compatibility_digest": state.active_compatibility_digest,
        "corpus_manifest_digest": _digest(f"corpus-{marker}"),
        "provider_revision": f"provider-{marker}",
        "privacy_policy_digest": _digest("privacy"),
        "retention_policy_digest": _digest("retention"),
        "rubric_digest": _digest(f"rubric-{marker}"),
        "label_owner_id": "label-owner",
        "review_owner_id": "review-owner",
        "independent_reviewer_id": "gate-reviewer",
        "sample_count": 20,
        "actual_output_count": 20,
        "recurrent_j2_j3_count": recurrent_count,
        "recurrence_threshold": threshold,
        "rubric_stable": stable,
        "evidence_digest": _digest(f"gate-evidence-{marker}"),
        "authorized_action": None,
    }


def _append_gate(
    events: list[dict[str, Any]],
    *,
    minute: int = 1,
    marker: str = "primary",
    recurrent_count: int = 3,
    threshold: int = 2,
    stable: bool = True,
) -> Any:
    plan = plan_gate_a(
        events,
        project_id=PROJECT_ID,
        raw=_gate_raw(
            events,
            marker=marker,
            recurrent_count=recurrent_count,
            threshold=threshold,
            stable=stable,
        ),
        recorded_at=_time(minute),
    )
    _append_plan(events, plan)
    return plan


def _inquiry_raw(
    events: list[dict[str, Any]],
    gate_receipt_digest: str,
) -> dict[str, Any]:
    state = reduce_frame_transition_state(events, project_id=PROJECT_ID)
    assert state.active_generation_id is not None
    assert state.active_compatibility_digest is not None
    return {
        "schema_version": 1,
        "gate_receipt_digest": gate_receipt_digest,
        "maker_id": "inquiry-maker",
        "claimed_jump_class": "J2",
        "changed_pointers": ["/representation/embedding"],
        "material_change": True,
        "exhaustion_signals": [
            {
                "signal_id": "signal-failure",
                "kind": "repeated_failure",
                "evidence_digest": _digest("signal-failure"),
                "lane": "canonical",
                "source_generation_id": state.active_generation_id,
                "source_compatibility_digest": state.active_compatibility_digest,
            },
            {
                "signal_id": "signal-anomaly",
                "kind": "unresolved_anomaly",
                "evidence_digest": _digest("signal-anomaly"),
                "lane": "canonical",
                "source_generation_id": state.active_generation_id,
                "source_compatibility_digest": state.active_compatibility_digest,
            },
        ],
        "rivals": [
            {
                "rival_id": "rival-a",
                "label": "Sparse representation",
                "assumptions": ["Observed failures arise from representation aliasing."],
                "mechanism": "Separate aliased states with a sparse basis.",
                "predictions": ["Replication error decreases."],
                "falsifiers": ["Aliasing remains unchanged."],
                "uncertainty": "Sensitivity to basis size remains unknown.",
            },
            {
                "rival_id": "rival-b",
                "label": "Structured representation",
                "assumptions": ["Observed failures arise from missing relations."],
                "mechanism": "Encode relations directly in the candidate schema.",
                "predictions": ["Relational failures decrease."],
                "falsifiers": ["Relational failures persist."],
                "uncertainty": "Relation extraction may be noisy.",
            },
        ],
        "discriminator": {
            "discriminator_id": "disc-1",
            "procedure": "Run the frozen paired task suite once per rival.",
            "outcome_rule": "Prefer the rival with lower replication error.",
            "plan_digest": _digest("discriminator-plan"),
        },
        "authorized_action": None,
    }


def _append_inquiry(
    events: list[dict[str, Any]],
    gate: Any,
    *,
    minute: int = 2,
) -> Any:
    plan = plan_inquiry_open(
        events,
        project_id=PROJECT_ID,
        raw=_inquiry_raw(events, gate.receipt_digest),
        recorded_at=_time(minute),
    )
    _append_plan(events, plan)
    return plan


def _candidate() -> dict[str, Any]:
    return {
        "candidate_id": "candidate-frame-v2",
        "candidate_digest": _digest("candidate"),
        "change_digest": _digest("change"),
        "coverage_digest": _digest("coverage"),
        "isolation_digest": _digest("isolation"),
    }


def _pilot_plan() -> dict[str, Any]:
    return {
        "pilot_plan_id": "pilot-plan-1",
        "task_digest": _digest("pilot-task"),
        "provider_revision": "provider-primary",
        "arms": ["llm_only", "llm_tools_memory", "llm_research_os"],
        "per_arm_call_limit": 5,
        "per_arm_token_limit": 1_000,
        "per_arm_elapsed_milliseconds_limit": 5_000,
        "per_arm_cost_microunits_limit": 1_000,
        "primary_metric": "replication_score",
        "higher_is_better": True,
        "minimum_effect_microunits": 20,
        "max_critical_false_promotions": 0,
        "privacy_policy_digest": _digest("privacy"),
        "retention_policy_digest": _digest("retention"),
        "teardown_policy": "Delete isolated pilot artifacts after receipt capture.",
    }


def _decision_raw(inquiry_id: str, outcome: str) -> dict[str, Any]:
    recommended = outcome == "RECOMMEND_FOR_PILOT"
    return {
        "schema_version": 1,
        "inquiry_id": inquiry_id,
        "maker_id": "inquiry-maker",
        "outcome": outcome,
        "rationale": "Frozen rivals were compared under the discriminator.",
        "evidence_digest": _digest(f"decision-{outcome}"),
        "candidate": _candidate() if recommended else None,
        "pilot_plan": _pilot_plan() if recommended else None,
        "authorized_action": None,
    }


def _append_decision(
    events: list[dict[str, Any]],
    inquiry_id: str,
    *,
    outcome: str = "RECOMMEND_FOR_PILOT",
    minute: int = 3,
) -> Any:
    plan = plan_inquiry_decision(
        events,
        project_id=PROJECT_ID,
        raw=_decision_raw(inquiry_id, outcome),
        recorded_at=_time(minute),
    )
    _append_plan(events, plan)
    return plan


def _authorization_raw(
    inquiry_id: str,
    decision: Any,
    *,
    authorizer_id: str = "pilot-authorizer",
    expires_minute: int = 10,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "inquiry_id": inquiry_id,
        "authorizer_id": authorizer_id,
        "authority": "PILOT_ONLY",
        "candidate_digest": decision.payload["candidate"]["candidate_digest"],
        "pilot_plan_digest": decision.payload["pilot_plan_digest"],
        "expires_at": _time(expires_minute),
        "evidence_digest": _digest("pilot-authorization"),
        "authorized_action": None,
    }


def _append_authorization(
    events: list[dict[str, Any]],
    inquiry_id: str,
    decision: Any,
    *,
    minute: int = 4,
    expires_minute: int = 10,
) -> Any:
    plan = plan_pilot_authorization(
        events,
        project_id=PROJECT_ID,
        raw=_authorization_raw(
            inquiry_id,
            decision,
            expires_minute=expires_minute,
        ),
        recorded_at=_time(minute),
    )
    _append_plan(events, plan)
    return plan


def _arm_results(
    *,
    research_score: int = 150,
    critical_false_promotions: int = 0,
    exceed_cap: bool = False,
) -> list[dict[str, Any]]:
    scores = (100, 110, research_score)
    return [
        {
            "arm": arm,
            "score_microunits": score,
            "calls": 6 if exceed_cap and index == 0 else 1,
            "tokens": 100,
            "elapsed_milliseconds": 100,
            "cost_microunits": 100,
            "critical_false_promotions": (
                critical_false_promotions if index == 2 else 0
            ),
        }
        for index, (arm, score) in enumerate(
            zip(
                ("llm_only", "llm_tools_memory", "llm_research_os"),
                scores,
                strict=True,
            )
        )
    ]


def _pilot_result_raw(
    inquiry_id: str,
    authorization: Any,
    *,
    evaluator_id: str = "pilot-evaluator",
    research_score: int = 150,
    critical_false_promotions: int = 0,
    exceed_cap: bool = False,
    privacy_breach: bool = False,
    invariant_regression: bool = False,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "inquiry_id": inquiry_id,
        "evaluator_id": evaluator_id,
        "authorization_receipt_digest": authorization.receipt_digest,
        "arm_results": _arm_results(
            research_score=research_score,
            critical_false_promotions=critical_false_promotions,
            exceed_cap=exceed_cap,
        ),
        "privacy_breach": privacy_breach,
        "invariant_regression": invariant_regression,
        "evidence_digest": _digest("pilot-result"),
        "authorized_action": None,
    }


def _append_pilot_result(
    events: list[dict[str, Any]],
    inquiry_id: str,
    authorization: Any,
    *,
    minute: int = 5,
    **overrides: Any,
) -> Any:
    plan = plan_pilot_result(
        events,
        project_id=PROJECT_ID,
        raw=_pilot_result_raw(inquiry_id, authorization, **overrides),
        recorded_at=_time(minute),
    )
    _append_plan(events, plan)
    return plan


def _review_raw(
    inquiry_id: str,
    pilot: Any,
    successor_contract: StudyContract,
    successor_seal: EvaluationSeal,
    *,
    reviewer_id: str = "adoption-reviewer",
    verdict: str = "APPROVE",
    expires_minute: int = 12,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "inquiry_id": inquiry_id,
        "reviewer_id": reviewer_id,
        "verdict": verdict,
        "candidate_digest": _candidate()["candidate_digest"],
        "change_digest": _candidate()["change_digest"],
        "coverage_digest": _candidate()["coverage_digest"],
        "pilot_receipt_digest": pilot.receipt_digest,
        "tree_digest": _digest("tree"),
        "predecessor_generation_id": None,
        "successor_contract_digest": successor_contract.digest,
        "successor_compatibility_digest": successor_seal.compatibility_digest,
        "expires_at": _time(expires_minute),
        "evidence_digest": _digest("adoption-review"),
        "authorized_action": None,
    }


def _append_review(
    events: list[dict[str, Any]],
    inquiry_id: str,
    pilot: Any,
    successor_contract: StudyContract,
    successor_seal: EvaluationSeal,
    *,
    minute: int = 6,
    verdict: str = "APPROVE",
    expires_minute: int = 12,
) -> Any:
    raw = _review_raw(
        inquiry_id,
        pilot,
        successor_contract,
        successor_seal,
        verdict=verdict,
        expires_minute=expires_minute,
    )
    inquiry = reduce_frame_transition_state(events, project_id=PROJECT_ID).inquiry(
        inquiry_id
    )
    assert inquiry is not None
    raw["predecessor_generation_id"] = inquiry["intake"][
        "predecessor_generation_id"
    ]
    plan = plan_adoption_review(
        events,
        project_id=PROJECT_ID,
        raw=raw,
        recorded_at=_time(minute),
    )
    _append_plan(events, plan)
    return plan


def _policy_adoption_raw(inquiry_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "inquiry_id": inquiry_id,
        "authorized_action": None,
    }


def _append_policy_adoption(
    events: list[dict[str, Any]],
    inquiry_id: str,
    *,
    minute: int = 7,
) -> Any:
    plan = plan_policy_adoption(
        events,
        project_id=PROJECT_ID,
        raw=_policy_adoption_raw(inquiry_id),
        recorded_at=_time(minute),
    )
    _append_plan(events, plan)
    return plan


def _through_recommendation() -> tuple[list[dict[str, Any]], Any, Any]:
    events, _, _ = _opened()
    gate = _append_gate(events)
    inquiry = _append_inquiry(events, gate)
    decision = _append_decision(events, inquiry.receipt_id)
    return events, inquiry, decision


def _through_authorization(
    *,
    expires_minute: int = 10,
) -> tuple[list[dict[str, Any]], Any, Any, Any]:
    events, inquiry, decision = _through_recommendation()
    authorization = _append_authorization(
        events,
        inquiry.receipt_id,
        decision,
        expires_minute=expires_minute,
    )
    return events, inquiry, decision, authorization


def _through_approved_review(
    *,
    expires_minute: int = 12,
) -> tuple[
    list[dict[str, Any]],
    Any,
    Any,
    StudyContract,
    EvaluationSeal,
]:
    events, inquiry, _, authorization = _through_authorization()
    pilot = _append_pilot_result(events, inquiry.receipt_id, authorization)
    successor_contract = _contract(max_attempts=5)
    successor_seal = _seal(compatibility_digest=_digest("successor-compatibility"))
    review = _append_review(
        events,
        inquiry.receipt_id,
        pilot,
        successor_contract,
        successor_seal,
        expires_minute=expires_minute,
    )
    return events, inquiry, review, successor_contract, successor_seal


def _ready_to_activate() -> tuple[
    list[dict[str, Any]],
    Any,
    Any,
    StudyContract,
    EvaluationSeal,
]:
    events, inquiry, _, successor_contract, successor_seal = (
        _through_approved_review()
    )
    policy_adoption = _append_policy_adoption(events, inquiry.receipt_id)
    return events, inquiry, policy_adoption, successor_contract, successor_seal


def _append_revocation(
    events: list[dict[str, Any]],
    inquiry_id: str,
    *,
    revoker_id: str,
    target_receipt_digest: str,
    minute: int,
) -> Any:
    plan = plan_authority_revocation(
        events,
        project_id=PROJECT_ID,
        raw={
            "schema_version": 1,
            "inquiry_id": inquiry_id,
            "revoker_id": revoker_id,
            "target_receipt_digest": target_receipt_digest,
            "reason": "The unused authority is no longer current.",
            "authorized_action": None,
        },
        recorded_at=_time(minute),
    )
    _append_plan(events, plan)
    return plan


def _assert_code(code: str, operation: Any) -> ScientificStateError:
    with pytest.raises(ScientificStateError) as caught:
        operation()
    assert caught.value.code == code
    return caught.value


@pytest.mark.parametrize(
    ("pointers", "expected"),
    [
        (("/parameters/learning_rate",), "J0"),
        (("/model/architecture",), "J1"),
        (("/representation/embedding",), "J2"),
        (("/metrics/primary",), "J3"),
        (("/ontology/name",), "J3"),
        (("/parameters/ontology",), "J3"),
        (("/settings/objective",), "J3"),
        (("/model/evaluator",), "J3"),
        (("/features/representation",), "J2"),
        (("/parameters/objective_function",), "J3"),
        (("/parameters/world_ontology",), "J3"),
        (("/parameters/primary_metric",), "J3"),
        (("/model/evaluation_metric",), "J3"),
        (("/settings/candidate_representation",), "J2"),
        (("/parameters/class_weight",), "J0"),
        (("/hyperparameters/feature_fraction",), "J0"),
        (("/settings/metric_logging",), "J0"),
        (("/parameters/learning_rate", "/representation/embedding"), "J2"),
    ],
)
def test_classifies_known_surfaces_without_relabeling_downgrade(
    pointers: tuple[str, ...], expected: str
) -> None:
    assert classify_frame_change(pointers) == expected


@pytest.mark.parametrize(
    "pointers",
    [
        ("/",),
        ("/*",),
        ("/unknown/surface",),
        ("/parameters/x",),
        ("/settings/foo",),
        ("/model/foo",),
        ("/parameters/renamed_object",),
        ("/settings/object\u0456ve",),
        ("/parameters/x", "/unknown/y"),
    ],
)
def test_broad_or_unknown_material_surface_fails_closed(
    pointers: tuple[str, ...],
) -> None:
    assert classify_frame_change(pointers) == "AMBIGUOUS_MATERIAL"


@pytest.mark.parametrize("pointers", [(), ("parameters/x",)])
def test_empty_or_non_pointer_input_is_rejected(pointers: tuple[str, ...]) -> None:
    with pytest.raises(ScientificStateError):
        classify_frame_change(pointers)


def test_gate_a_derives_all_outcomes_and_requires_latest_receipt() -> None:
    events, _, _ = _opened()
    no_build = _append_gate(
        events,
        marker="no-build",
        recurrent_count=1,
        minute=1,
    )
    unstable = _append_gate(
        events,
        marker="unstable",
        stable=False,
        minute=2,
    )
    old_go = _append_gate(events, marker="old-go", minute=3)
    go = _append_gate(events, marker="go", minute=4)

    assert no_build.payload["outcome"] == "NO_BUILD"
    assert unstable.payload["outcome"] == "UNSTABLE_RUBRIC"
    assert old_go.payload["outcome"] == "GO"
    assert go.payload["outcome"] == "GO"
    assert go.payload["policy_id"] == POLICY_ADOPTION_POLICY_ID
    assert go.payload["policy_digest"] == POLICY_ADOPTION_POLICY_DIGEST
    assert POLICY_ADOPTION_POLICY_DIGEST == sha256_json(POLICY_ADOPTION_POLICY)
    state = reduce_frame_transition_state(events, project_id=PROJECT_ID)
    assert [gate["outcome"] for gate in state.gates] == [
        "NO_BUILD",
        "UNSTABLE_RUBRIC",
        "GO",
        "GO",
    ]

    _assert_code(
        "FRAME_TRANSITION_GATE_STALE",
        lambda: plan_inquiry_open(
            events,
            project_id=PROJECT_ID,
            raw=_inquiry_raw(events, old_go.receipt_digest),
            recorded_at=_time(5),
        ),
    )
    current = plan_inquiry_open(
        events,
        project_id=PROJECT_ID,
        raw=_inquiry_raw(events, go.receipt_digest),
        recorded_at=_time(5),
    )
    assert current.payload["jump_class"] == "J2"
    assert current.payload["policy_id"] == POLICY_ADOPTION_POLICY_ID
    assert current.payload["policy_digest"] == POLICY_ADOPTION_POLICY_DIGEST


def test_new_gate_supersedes_an_open_inquiry_before_later_authority() -> None:
    events, _, _ = _opened()
    gate = _append_gate(events, marker="initial-go")
    inquiry = _append_inquiry(events, gate)
    _append_gate(
        events,
        marker="later-no-build",
        recurrent_count=0,
        minute=3,
    )

    row = reduce_frame_transition_state(events, project_id=PROJECT_ID).inquiry(
        inquiry.receipt_id
    )
    assert row is not None
    assert row["stage"] == "STALE_GATE"
    assert row["terminal_result"] == "GO_NO_ADOPTION"
    _assert_code(
        "FRAME_TRANSITION_GATE_STALE",
        lambda: plan_inquiry_decision(
            events,
            project_id=PROJECT_ID,
            raw=_decision_raw(inquiry.receipt_id, "RECOMMEND_FOR_PILOT"),
            recorded_at=_time(4),
        ),
    )


@pytest.mark.parametrize(
    ("event_index", "field", "id_key", "namespace"),
    [
        (1, "policy_id", "gate_receipt_id", "framegate"),
        (1, "policy_digest", "gate_receipt_id", "framegate"),
        (2, "policy_id", "inquiry_id", "frameinquiry"),
        (2, "policy_digest", "inquiry_id", "frameinquiry"),
    ],
)
def test_gate_and_inquiry_replay_reject_resealed_policy_binding_tampering(
    event_index: int,
    field: str,
    id_key: str,
    namespace: str,
) -> None:
    events, _, _ = _opened()
    gate = _append_gate(events)
    _append_inquiry(events, gate)
    payload = events[event_index]["payload"]
    payload[field] = (
        "research-os.controlled-frame-transition.policy.tampered"
        if field == "policy_id"
        else _digest("tampered-policy")
    )
    events[event_index]["payload"] = _reseal_receipt(
        payload,
        id_key=id_key,
        namespace=namespace,
    )

    _assert_code(
        "FRAME_TRANSITION_RECEIPT_MISMATCH",
        lambda: reduce_frame_transition_state(events, project_id=PROJECT_ID),
    )


def test_inquiry_rejects_insufficient_or_misclassified_evidence() -> None:
    events, _, _ = _opened()
    gate = _append_gate(events)
    valid = _inquiry_raw(events, gate.receipt_digest)

    single_signal = copy.deepcopy(valid)
    single_signal["exhaustion_signals"] = single_signal["exhaustion_signals"][:1]
    with pytest.raises(ScientificStateError):
        plan_inquiry_open(
            events,
            project_id=PROJECT_ID,
            raw=single_signal,
            recorded_at=_time(2),
        )

    incompatible_canonical = copy.deepcopy(valid)
    incompatible_canonical["exhaustion_signals"][0][
        "source_compatibility_digest"
    ] = _digest("another-frame")
    _assert_code(
        "FRAME_TRANSITION_ADVISORY_ONLY",
        lambda: plan_inquiry_open(
            events,
            project_id=PROJECT_ID,
            raw=incompatible_canonical,
            recorded_at=_time(2),
        ),
    )

    duplicate_rival = copy.deepcopy(valid)
    duplicate_rival["rivals"][1]["assumptions"] = duplicate_rival["rivals"][0][
        "assumptions"
    ]
    duplicate_rival["rivals"][1]["mechanism"] = duplicate_rival["rivals"][0][
        "mechanism"
    ]
    _assert_code(
        "FRAME_TRANSITION_RIVALS_INVALID",
        lambda: plan_inquiry_open(
            events,
            project_id=PROJECT_ID,
            raw=duplicate_rival,
            recorded_at=_time(2),
        ),
    )

    permuted_rival = copy.deepcopy(valid)
    shared_assumptions = ["First shared assumption.", "Second shared assumption."]
    permuted_rival["rivals"][0]["assumptions"] = shared_assumptions
    permuted_rival["rivals"][1]["assumptions"] = list(reversed(shared_assumptions))
    permuted_rival["rivals"][1]["mechanism"] = permuted_rival["rivals"][0][
        "mechanism"
    ].upper()
    _assert_code(
        "FRAME_TRANSITION_RIVALS_INVALID",
        lambda: plan_inquiry_open(
            events,
            project_id=PROJECT_ID,
            raw=permuted_rival,
            recorded_at=_time(2),
        ),
    )


def test_extension_events_leave_scientific_state_unchanged() -> None:
    events, _, _ = _opened()
    before = reduce_scientific_state(events, project_id=PROJECT_ID).to_dict()
    gate = _append_gate(events)
    _append_inquiry(events, gate)

    after = reduce_scientific_state(events, project_id=PROJECT_ID).to_dict()
    assert after == before


def test_nested_authority_fields_are_rejected_not_silently_ignored() -> None:
    events, inquiry, _ = _through_recommendation()
    raw = _decision_raw(inquiry.receipt_id, "RECOMMEND_FOR_PILOT")
    raw["candidate"]["authorized_action"] = None

    with pytest.raises(ScientificStateError):
        plan_inquiry_decision(
            events,
            project_id=PROJECT_ID,
            raw=raw,
            recorded_at=_time(4),
        )


def test_exact_retry_returns_existing_receipt_without_append() -> None:
    events, _, _ = _opened()
    raw = _gate_raw(events, marker="retry")
    first = plan_gate_a(
        events,
        project_id=PROJECT_ID,
        raw=raw,
        recorded_at=_time(1),
    )
    _append_plan(events, first)

    retry = plan_gate_a(
        events,
        project_id=PROJECT_ID,
        raw=raw,
        recorded_at=_time(9),
    )

    assert retry.append_required is False
    assert retry.receipt_id == first.receipt_id
    assert retry.receipt_digest == first.receipt_digest
    assert retry.payload["recorded_at"] == _time(1)
    assert retry.existing_event_id == events[-1]["event_id"]


@pytest.mark.parametrize(
    ("field", "near_match"),
    [("rubric_stable", 1), ("sample_count", 20.0)],
)
def test_typed_near_match_is_not_treated_as_idempotent_retry(
    field: str,
    near_match: Any,
) -> None:
    events, _, _ = _opened()
    raw = _gate_raw(events, marker="typed-retry")
    first = plan_gate_a(
        events,
        project_id=PROJECT_ID,
        raw=raw,
        recorded_at=_time(1),
    )
    _append_plan(events, first)
    malformed = copy.deepcopy(raw)
    malformed[field] = near_match

    with pytest.raises(ScientificStateError):
        plan_gate_a(
            events,
            project_id=PROJECT_ID,
            raw=malformed,
            recorded_at=_time(2),
        )


def test_gate_cannot_be_backdated_before_its_active_generation() -> None:
    events, _, _ = _opened()
    events[0]["occurred_at"] = _time(5)

    _assert_code(
        "FRAME_TRANSITION_TIME_INVALID",
        lambda: plan_gate_a(
            events,
            project_id=PROJECT_ID,
            raw=_gate_raw(events, marker="backdated"),
            recorded_at=_time(1),
        ),
    )


@pytest.mark.parametrize("outcome", ["ABSTAIN", "REJECT"])
def test_non_recommendation_decisions_are_terminal_without_pilot_state(
    outcome: str,
) -> None:
    events, _, _ = _opened()
    gate = _append_gate(events)
    inquiry = _append_inquiry(events, gate)
    _append_decision(events, inquiry.receipt_id, outcome=outcome)

    row = reduce_frame_transition_state(
        events,
        project_id=PROJECT_ID,
        as_of=_time(9),
    ).inquiry(inquiry.receipt_id)
    assert row is not None
    assert row["stage"] == outcome
    assert row["terminal_result"] == "GO_NO_ADOPTION"
    assert row["decision"]["candidate"] is None
    assert row["decision"]["pilot_plan"] is None
    assert row["authorized_action"] is None


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        (
            {
                "invariant_regression": True,
                "privacy_breach": True,
                "exceed_cap": True,
                "critical_false_promotions": 1,
                "research_score": 110,
            },
            "KILL_B4",
        ),
        (
            {
                "privacy_breach": True,
                "critical_false_promotions": 1,
                "research_score": 110,
            },
            "KILL_B3",
        ),
        ({"critical_false_promotions": 1, "research_score": 110}, "KILL_B1"),
        ({"research_score": 119}, "KILL_B2"),
        ({"research_score": 150}, "PASS_FOR_ADOPTION"),
    ],
)
def test_pilot_outcome_uses_fixed_kill_precedence(
    overrides: dict[str, Any], expected: str
) -> None:
    events, inquiry, _, authorization = _through_authorization()
    pilot = _append_pilot_result(
        events,
        inquiry.receipt_id,
        authorization,
        **overrides,
    )

    assert pilot.payload["outcome"] == expected
    row = reduce_frame_transition_state(events, project_id=PROJECT_ID).inquiry(
        inquiry.receipt_id
    )
    assert row is not None
    if expected == "PASS_FOR_ADOPTION":
        assert row["stage"] == "AWAITING_ADOPTION_REVIEW"
        assert row["terminal_result"] is None
    else:
        assert row["stage"] == expected
        assert row["terminal_result"] == "GO_NO_ADOPTION"


def test_maker_authorizer_evaluator_and_reviewer_are_distinct() -> None:
    events, inquiry, decision = _through_recommendation()
    _assert_code(
        "FRAME_TRANSITION_INDEPENDENCE_REQUIRED",
        lambda: plan_pilot_authorization(
            events,
            project_id=PROJECT_ID,
            raw=_authorization_raw(
                inquiry.receipt_id,
                decision,
                authorizer_id="inquiry-maker",
            ),
            recorded_at=_time(4),
        ),
    )
    authorization = _append_authorization(events, inquiry.receipt_id, decision)

    _assert_code(
        "FRAME_TRANSITION_INDEPENDENCE_REQUIRED",
        lambda: plan_pilot_result(
            events,
            project_id=PROJECT_ID,
            raw=_pilot_result_raw(
                inquiry.receipt_id,
                authorization,
                evaluator_id="pilot-authorizer",
            ),
            recorded_at=_time(5),
        ),
    )
    pilot = _append_pilot_result(events, inquiry.receipt_id, authorization)
    successor_contract = _contract(max_attempts=5)
    successor_seal = _seal(compatibility_digest=_digest("successor-compatibility"))
    review_raw = _review_raw(
        inquiry.receipt_id,
        pilot,
        successor_contract,
        successor_seal,
        reviewer_id="pilot-evaluator",
    )
    review_raw["predecessor_generation_id"] = reduce_frame_transition_state(
        events, project_id=PROJECT_ID
    ).active_generation_id
    _assert_code(
        "FRAME_TRANSITION_INDEPENDENCE_REQUIRED",
        lambda: plan_adoption_review(
            events,
            project_id=PROJECT_ID,
            raw=review_raw,
            recorded_at=_time(6),
        ),
    )


def test_policy_adoption_is_fully_derived_and_idempotent() -> None:
    events, inquiry, review, _, _ = _through_approved_review()
    before = reduce_frame_transition_state(events, project_id=PROJECT_ID).inquiry(
        inquiry.receipt_id
    )
    assert before is not None
    assert before["stage"] == "AWAITING_POLICY_ADOPTION"

    raw = _policy_adoption_raw(inquiry.receipt_id)
    policy_adoption = plan_policy_adoption(
        events,
        project_id=PROJECT_ID,
        raw=raw,
        recorded_at=_time(7),
    )
    assert policy_adoption.event_type == FRAME_POLICY_ADOPTION_EVENT_TYPE
    assert set(raw) == {"schema_version", "inquiry_id", "authorized_action"}
    assert policy_adoption.payload["decision"] == "POLICY_ADOPTION"
    assert policy_adoption.payload["policy_id"] == POLICY_ADOPTION_POLICY_ID
    assert policy_adoption.payload["policy_digest"] == POLICY_ADOPTION_POLICY_DIGEST
    for key in (
        "candidate_digest",
        "successor_contract_digest",
        "successor_compatibility_digest",
        "expires_at",
    ):
        assert policy_adoption.payload[key] == review.payload[key]
    assert policy_adoption.payload["review_receipt_digest"] == review.receipt_digest
    assert policy_adoption.payload["evidence_digest"] == sha256_json(
        {
            "policy_digest": POLICY_ADOPTION_POLICY_DIGEST,
            "pilot_receipt_digest": review.payload["pilot_receipt_digest"],
            "review_receipt_digest": review.receipt_digest,
            "candidate_digest": review.payload["candidate_digest"],
            "successor_contract_digest": review.payload[
                "successor_contract_digest"
            ],
            "successor_compatibility_digest": review.payload[
                "successor_compatibility_digest"
            ],
        }
    )
    assert "ratifier_id" not in policy_adoption.payload
    assert policy_adoption.payload["authorized_action"] is None

    _append_plan(events, policy_adoption)
    after = reduce_frame_transition_state(events, project_id=PROJECT_ID).inquiry(
        inquiry.receipt_id
    )
    assert after is not None
    assert after["stage"] == "READY_TO_ACTIVATE"
    assert after["policy_adoption"]["receipt_digest"] == (
        policy_adoption.receipt_digest
    )
    assert "adoption" not in after

    retry = plan_policy_adoption(
        events,
        project_id=PROJECT_ID,
        raw=raw,
        recorded_at=_time(9),
    )
    assert retry.append_required is False
    assert retry.receipt_digest == policy_adoption.receipt_digest
    assert retry.payload == policy_adoption.payload


def test_pilot_pass_and_review_approval_remain_separate_policy_gates() -> None:
    events, inquiry, _, authorization = _through_authorization()
    pilot = _append_pilot_result(events, inquiry.receipt_id, authorization)
    successor_contract = _contract(max_attempts=5)
    successor_seal = _seal(compatibility_digest=_digest("successor-compatibility"))
    _append_review(
        events,
        inquiry.receipt_id,
        pilot,
        successor_contract,
        successor_seal,
        verdict="REJECT",
    )
    row = reduce_frame_transition_state(events, project_id=PROJECT_ID).inquiry(
        inquiry.receipt_id
    )
    assert row is not None
    assert row["pilot_result"]["outcome"] == "PASS_FOR_ADOPTION"
    assert row["adoption_review"]["verdict"] == "REJECT"
    assert row["stage"] == "ADOPTION_REJECTED"
    _assert_code(
        "FRAME_TRANSITION_REVIEW_APPROVAL_REQUIRED",
        lambda: plan_policy_adoption(
            events,
            project_id=PROJECT_ID,
            raw=_policy_adoption_raw(inquiry.receipt_id),
            recorded_at=_time(7),
        ),
    )


@pytest.mark.parametrize(
    "field",
    [
        "ratifier_id",
        "decision",
        "policy_id",
        "policy_digest",
        "review_receipt_digest",
        "candidate_digest",
        "successor_contract_digest",
        "successor_compatibility_digest",
        "expires_at",
        "evidence_digest",
    ],
)
def test_policy_adoption_rejects_every_caller_supplied_derived_field(
    field: str,
) -> None:
    events, inquiry, _, _, _ = _through_approved_review()
    raw = _policy_adoption_raw(inquiry.receipt_id)
    raw[field] = "caller-controlled"

    _assert_code(
        "FRAME_TRANSITION_INVALID",
        lambda: plan_policy_adoption(
            events,
            project_id=PROJECT_ID,
            raw=raw,
            recorded_at=_time(7),
        ),
    )


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("decision", "ADOPTION"),
        ("policy_id", "research-os.controlled-frame-transition.policy.tampered"),
        ("policy_digest", _digest("wrong-policy")),
        ("review_receipt_digest", _digest("wrong-review")),
        ("candidate_digest", _digest("wrong-candidate")),
        ("successor_contract_digest", _digest("wrong-contract")),
        ("successor_compatibility_digest", _digest("wrong-compatibility")),
        ("expires_at", _time(11)),
        ("evidence_digest", _digest("wrong-evidence")),
    ],
)
def test_policy_adoption_replay_rejects_resealed_derived_field_tampering(
    field: str,
    replacement: str,
) -> None:
    events, _, _, _, _ = _ready_to_activate()
    payload = events[-1]["payload"]
    payload[field] = replacement
    events[-1]["payload"] = _reseal_receipt(
        payload,
        id_key="policy_adoption_id",
        namespace="policyadoption",
    )

    _assert_code(
        "FRAME_TRANSITION_RECEIPT_MISMATCH",
        lambda: reduce_frame_transition_state(events, project_id=PROJECT_ID),
    )


def test_expired_or_revoked_review_cannot_issue_policy_adoption() -> None:
    expired_events, expired_inquiry, _, _, _ = _through_approved_review(
        expires_minute=7
    )
    _assert_code(
        "FRAME_TRANSITION_AUTHORITY_EXPIRED",
        lambda: plan_policy_adoption(
            expired_events,
            project_id=PROJECT_ID,
            raw=_policy_adoption_raw(expired_inquiry.receipt_id),
            recorded_at=_time(7),
        ),
    )

    events, inquiry, review, _, _ = _through_approved_review()
    pending = plan_policy_adoption(
        events,
        project_id=PROJECT_ID,
        raw=_policy_adoption_raw(inquiry.receipt_id),
        recorded_at=_time(7),
    )
    _append_revocation(
        events,
        inquiry.receipt_id,
        revoker_id="adoption-reviewer",
        target_receipt_digest=review.receipt_digest,
        minute=8,
    )
    _assert_code(
        "FRAME_TRANSITION_AUTHORITY_REVOKED",
        lambda: validate_frame_transition_commit_time(
            events,
            project_id=PROJECT_ID,
            plan=pending,
            as_of=_time(8),
        ),
    )
    _assert_code(
        "FRAME_TRANSITION_AUTHORITY_REVOKED",
        lambda: plan_policy_adoption(
            events,
            project_id=PROJECT_ID,
            raw=_policy_adoption_raw(inquiry.receipt_id),
            recorded_at=_time(9),
        ),
    )


def test_policy_adoption_commit_guard_rechecks_review_expiry() -> None:
    events, inquiry, _, _, _ = _through_approved_review(expires_minute=7)
    plan = plan_policy_adoption(
        events,
        project_id=PROJECT_ID,
        raw=_policy_adoption_raw(inquiry.receipt_id),
        recorded_at=_time(6),
    )

    _assert_code(
        "FRAME_TRANSITION_AUTHORITY_EXPIRED",
        lambda: validate_frame_transition_commit_time(
            events,
            project_id=PROJECT_ID,
            plan=plan,
            as_of=_time(7),
        ),
    )
def test_unused_pilot_authority_expires_and_cannot_be_consumed() -> None:
    events, inquiry, _, authorization = _through_authorization(expires_minute=5)

    row = reduce_frame_transition_state(
        events,
        project_id=PROJECT_ID,
        as_of=_time(5),
    ).inquiry(inquiry.receipt_id)
    assert row is not None
    assert row["stage"] == "PILOT_AUTHORITY_EXPIRED"
    assert row["terminal_result"] == "GO_NO_ADOPTION"
    _assert_code(
        "FRAME_TRANSITION_AUTHORITY_EXPIRED",
        lambda: plan_pilot_result(
            events,
            project_id=PROJECT_ID,
            raw=_pilot_result_raw(inquiry.receipt_id, authorization),
            recorded_at=_time(5),
        ),
    )


def test_commit_guard_rechecks_expiry_after_lock_wait() -> None:
    events, inquiry, _, authorization = _through_authorization(expires_minute=5)
    plan = plan_pilot_result(
        events,
        project_id=PROJECT_ID,
        raw=_pilot_result_raw(inquiry.receipt_id, authorization),
        recorded_at=_time(4),
    )

    _assert_code(
        "FRAME_TRANSITION_AUTHORITY_EXPIRED",
        lambda: validate_frame_transition_commit_time(
            events,
            project_id=PROJECT_ID,
            plan=plan,
            as_of=_time(5),
        ),
    )


def test_unused_authority_can_be_revoked_only_by_issuer() -> None:
    events, inquiry, _, authorization = _through_authorization()
    raw = {
        "schema_version": 1,
        "inquiry_id": inquiry.receipt_id,
        "revoker_id": "pilot-authorizer",
        "target_receipt_digest": authorization.receipt_digest,
        "reason": "Pilot isolation guarantee is no longer valid.",
        "authorized_action": None,
    }
    plan = plan_authority_revocation(
        events,
        project_id=PROJECT_ID,
        raw=raw,
        recorded_at=_time(5),
    )
    _append_plan(events, plan)

    state = reduce_frame_transition_state(
        events,
        project_id=PROJECT_ID,
        as_of=_time(5),
    )
    row = state.inquiry(inquiry.receipt_id)
    assert row is not None
    assert row["stage"] == "PILOT_AUTHORITY_REVOKED"
    assert row["terminal_result"] == "GO_NO_ADOPTION"
    assert authorization.receipt_digest in state.revoked_receipt_digests
    _assert_code(
        "FRAME_TRANSITION_AUTHORITY_REVOKED",
        lambda: plan_pilot_result(
            events,
            project_id=PROJECT_ID,
            raw=_pilot_result_raw(inquiry.receipt_id, authorization),
            recorded_at=_time(6),
        ),
    )


def test_review_revocation_after_policy_blocks_activation_and_forged_successor() -> None:
    events, inquiry, policy_adoption, successor_contract, successor_seal = (
        _ready_to_activate()
    )
    row = reduce_frame_transition_state(events, project_id=PROJECT_ID).inquiry(
        inquiry.receipt_id
    )
    assert row is not None
    review = row["adoption_review"]
    _append_revocation(
        events,
        inquiry.receipt_id,
        revoker_id=review["reviewer_id"],
        target_receipt_digest=review["receipt_digest"],
        minute=8,
    )

    revoked = reduce_frame_transition_state(
        events,
        project_id=PROJECT_ID,
        as_of=_time(8),
    ).inquiry(inquiry.receipt_id)
    assert revoked is not None
    assert revoked["stage"] == "ADOPTION_REVIEW_REVOKED"
    assert revoked["terminal_result"] == "GO_NO_ADOPTION"
    assert revoked["durable_successor_writer_count"] == 0
    reason = controlled_change_reason(
        inquiry.receipt_id,
        policy_adoption.receipt_digest,
    )
    _assert_code(
        "FRAME_TRANSITION_ACTIVATION_INVALID",
        lambda: validate_controlled_activation(
            events,
            project_id=PROJECT_ID,
            inquiry_id=inquiry.receipt_id,
            policy_adoption_digest=policy_adoption.receipt_digest,
            target_contract_digest=successor_contract.digest,
            target_successor_compatibility_digest=(
                successor_seal.compatibility_digest
            ),
            change_reason=reason,
            as_of=_time(9),
        ),
    )
    _assert_code(
        "FRAME_TRANSITION_REVOCATION_INVALID",
        lambda: plan_authority_revocation(
            events,
            project_id=PROJECT_ID,
            raw={
                "schema_version": 1,
                "inquiry_id": inquiry.receipt_id,
                "revoker_id": review["reviewer_id"],
                "target_receipt_digest": policy_adoption.receipt_digest,
                "reason": "A policy receipt is not revocable authority.",
                "authorized_action": None,
            },
            recorded_at=_time(9),
        ),
    )

    successor = plan_generation_open(
        events,
        project_id=PROJECT_ID,
        contract=successor_contract,
        evaluation_seal=successor_seal,
        predecessor_generation_id=revoked["intake"]["predecessor_generation_id"],
        change_reason=reason,
    )
    forged = [
        *events,
        _event(
            successor.event_type,
            successor.payload,
            occurred_at=_time(9),
            sequence=len(events) + 1,
        ),
    ]
    _assert_code(
        "FRAME_TRANSITION_ACTIVATION_INVALID",
        lambda: reduce_frame_transition_state(forged, project_id=PROJECT_ID),
    )


def test_full_pass_chain_requires_exact_activation_binding() -> None:
    events, inquiry, policy_adoption, successor_contract, successor_seal = (
        _ready_to_activate()
    )
    reason = controlled_change_reason(
        inquiry.receipt_id,
        policy_adoption.receipt_digest,
    )

    binding = validate_controlled_activation(
        events,
        project_id=PROJECT_ID,
        inquiry_id=inquiry.receipt_id,
        policy_adoption_digest=policy_adoption.receipt_digest,
        target_contract_digest=successor_contract.digest,
        target_successor_compatibility_digest=successor_seal.compatibility_digest,
        change_reason=reason,
        as_of=_time(8),
    )
    assert binding["already_activated"] is False
    assert binding["policy_adoption_digest"] == policy_adoption.receipt_digest
    assert binding["authorized_action"] is None

    _assert_code(
        "FRAME_TRANSITION_TIME_INVALID",
        lambda: validate_controlled_activation(
            events,
            project_id=PROJECT_ID,
            inquiry_id=inquiry.receipt_id,
            policy_adoption_digest=policy_adoption.receipt_digest,
            target_contract_digest=successor_contract.digest,
            target_successor_compatibility_digest=successor_seal.compatibility_digest,
            change_reason=reason,
            as_of=_time(0),
        ),
    )

    for wrong in (
        {"change_reason": "ordinary-change"},
        {"target_contract_digest": _digest("wrong-contract")},
        {"target_successor_compatibility_digest": _digest("wrong-compatibility")},
    ):
        arguments = {
            "project_id": PROJECT_ID,
            "inquiry_id": inquiry.receipt_id,
            "policy_adoption_digest": policy_adoption.receipt_digest,
            "target_contract_digest": successor_contract.digest,
            "target_successor_compatibility_digest": successor_seal.compatibility_digest,
            "change_reason": reason,
            "as_of": _time(8),
            **wrong,
        }
        with pytest.raises(ScientificStateError):
            validate_controlled_activation(events, **arguments)

    successor = plan_generation_open(
        events,
        project_id=PROJECT_ID,
        contract=successor_contract,
        evaluation_seal=successor_seal,
        predecessor_generation_id=binding["predecessor_generation_id"],
        change_reason=reason,
    )
    backdated = [
        *events,
        _event(
            successor.event_type,
            successor.payload,
            occurred_at=_time(0),
            sequence=len(events) + 1,
        ),
    ]
    _assert_code(
        "FRAME_TRANSITION_ACTIVATION_INVALID",
        lambda: reduce_frame_transition_state(backdated, project_id=PROJECT_ID),
    )
    events.append(
        _event(
            successor.event_type,
            successor.payload,
            occurred_at=_time(8),
            sequence=len(events) + 1,
        )
    )
    state = reduce_frame_transition_state(events, project_id=PROJECT_ID, as_of=_time(9))
    row = state.inquiry(inquiry.receipt_id)
    assert row is not None
    assert row["stage"] == "ACTIVATED"
    assert row["terminal_result"] == "GO_ADOPTION"
    assert row["durable_successor_writer_count"] == 1
    assert row["successor_generation_id"] == successor.generation_id

    replayed = validate_controlled_activation(
        events,
        project_id=PROJECT_ID,
        inquiry_id=inquiry.receipt_id,
        policy_adoption_digest=policy_adoption.receipt_digest,
        target_contract_digest=successor_contract.digest,
        target_successor_compatibility_digest=successor_seal.compatibility_digest,
        change_reason=reason,
        as_of=_time(12),
    )
    assert replayed["already_activated"] is True
    assert replayed["successor_generation_id"] == successor.generation_id
    _assert_code(
        "FRAME_TRANSITION_AUTHORITY_CONSUMED",
        lambda: plan_authority_revocation(
            events,
            project_id=PROJECT_ID,
            raw={
                "schema_version": 1,
                "inquiry_id": inquiry.receipt_id,
                "revoker_id": row["adoption_review"]["reviewer_id"],
                "target_receipt_digest": row["adoption_review"][
                    "receipt_digest"
                ],
                "reason": "Too late after the durable successor.",
                "authorized_action": None,
            },
            recorded_at=_time(13),
        ),
    )


def test_ordinary_successor_wins_once_and_makes_pending_inquiry_stale() -> None:
    events, inquiry, policy_adoption, _, _ = _ready_to_activate()
    state = reduce_frame_transition_state(events, project_id=PROJECT_ID)
    assert state.active_generation_id is not None
    ordinary_contract = _contract(max_attempts=6)
    ordinary_seal = _seal(compatibility_digest=_digest("ordinary-compatibility"))
    successor = plan_generation_open(
        events,
        project_id=PROJECT_ID,
        contract=ordinary_contract,
        evaluation_seal=ordinary_seal,
        predecessor_generation_id=state.active_generation_id,
        change_reason="Administrative successor opened outside the controlled inquiry.",
    )
    events.append(
        _event(
            successor.event_type,
            successor.payload,
            occurred_at=_time(8),
            sequence=len(events) + 1,
        )
    )

    reduced = reduce_frame_transition_state(events, project_id=PROJECT_ID, as_of=_time(9))
    row = reduced.inquiry(inquiry.receipt_id)
    assert row is not None
    assert row["stage"] == "STALE_PREDECESSOR"
    assert row["terminal_result"] == "GO_NO_ADOPTION"
    assert row["durable_successor_writer_count"] == 0
    assert row["superseded_by_generation_id"] == successor.generation_id
    _assert_code(
        "FRAME_TRANSITION_ACTIVATION_INVALID",
        lambda: validate_controlled_activation(
            events,
            project_id=PROJECT_ID,
            inquiry_id=inquiry.receipt_id,
            policy_adoption_digest=policy_adoption.receipt_digest,
            target_contract_digest=policy_adoption.payload[
                "successor_contract_digest"
            ],
            target_successor_compatibility_digest=policy_adoption.payload[
                "successor_compatibility_digest"
            ],
            change_reason=controlled_change_reason(
                inquiry.receipt_id, policy_adoption.receipt_digest
            ),
            as_of=_time(9),
        ),
    )
