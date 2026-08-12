"""Pure observers for the frozen M1-D semantic-frontier fact corpus.

The public functions receive only a manifest input object and a fixture loader.
Fixture row labels and comparison values are intentionally outside this module's
dispatch boundary.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from typing import cast

FixtureLoader = Callable[[str], Mapping[str, object]]

_RETRYABLE_STATUSES = {
    "TIMED_OUT",
    "CANCELLED",
    "INFRA_FAILED",
    "INSUFFICIENT_EVIDENCE",
}
_STATUS_ALIASES = {
    "TIMEOUT": "TIMED_OUT",
    "TIMEDOUT": "TIMED_OUT",
    "CANCELED": "CANCELLED",
    "SUCCESS": "SUCCEEDED",
    "PASSED": "SUCCEEDED",
    "COMPLETE": "COMPLETED",
    "ERROR": "FAILED",
}
_SUPPORT_FAILURE_AXES = {
    "SUPPORT_VERIFIED_FALSE",
    "SUPPORT_NONPOSITIVE_MARGIN",
    "SUPPORT_FAILED_HARD_GATE",
    "SUPPORT_FAILED_SUPPORT_GATE",
    "SUPPORT_TOP_LEVEL_ERROR_KEY",
    "SUPPORT_OBSERVATION_MISMATCH",
}
_DISPLAY_SELECTOR_KEYS = frozenset(
    {
        "$ref",
        "case_id",
        "display_id",
        "extends",
        "gate_ids",
        "label",
        "race_ids",
        "required_operations",
        "scenario",
        "template",
    }
)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _sequence(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be non-empty text")
    return value


def _public_json_equal(left: object, right: object) -> bool:
    """Compare values in the public canonical-JSON equality domain."""

    from research_os.contracts import canonical_json_bytes

    return canonical_json_bytes(left) == canonical_json_bytes(right)


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _fixture(
    inputs: Mapping[str, object],
    key: str,
    fixture_source: FixtureLoader,
) -> Mapping[str, object]:
    return _mapping(fixture_source(_text(inputs.get(key), key)), key)


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_status(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
    return _STATUS_ALIASES.get(normalized, normalized)


def _kernel_retryable(payload: Mapping[str, object]) -> bool:
    declared = payload.get("retryable")
    if isinstance(declared, bool):
        return declared
    return _canonical_status(payload.get("status")) in _RETRYABLE_STATUSES


def _registration(node: Mapping[str, object]) -> Mapping[str, object] | None:
    fact = node.get("registration_fact")
    if not isinstance(fact, Mapping) or fact.get("event_type") != "EXPERIMENT_REGISTERED":
        return None
    payload = fact.get("payload")
    return _mapping(payload, "registration payload") if isinstance(payload, Mapping) else None


def _terminal(node: Mapping[str, object]) -> Mapping[str, object] | None:
    fact = node.get("terminal_fact")
    return _mapping(fact, "terminal fact") if isinstance(fact, Mapping) else None


def _terminal_payload(node: Mapping[str, object]) -> Mapping[str, object] | None:
    fact = _terminal(node)
    if fact is None or not isinstance(fact.get("payload"), Mapping):
        return None
    return _mapping(fact["payload"], "terminal payload")


def _diagnosis_fact(node: Mapping[str, object]) -> Mapping[str, object] | None:
    fact = node.get("diagnosis_fact")
    return _mapping(fact, "diagnosis fact") if isinstance(fact, Mapping) else None


def _diagnosis(node: Mapping[str, object]) -> Mapping[str, object] | None:
    fact = _diagnosis_fact(node)
    if fact is None or fact.get("event_type") != "research.experiment_diagnosed.v1":
        return None
    body = fact.get("diagnosis")
    return _mapping(body, "diagnosis") if isinstance(body, Mapping) else None


def _decision(payload: Mapping[str, object]) -> Mapping[str, object] | None:
    value = payload.get("decision")
    return _mapping(value, "decision") if isinstance(value, Mapping) else None


def _terminal_observation(node: Mapping[str, object]) -> dict[str, object] | None:
    fact = _terminal(node)
    payload = _terminal_payload(node)
    if fact is None or payload is None:
        return None
    decision = _decision(payload)
    reason = payload.get("reason_code")
    if not isinstance(reason, str) or not reason:
        reason = (
            "STATUS_CHANGED"
            if fact.get("event_type") == "EXPERIMENT_STATUS_CHANGED"
            else "TERMINATED"
        )
    primary_metric = payload.get("primary_metric")
    if not isinstance(primary_metric, str) or not primary_metric:
        primary_metric = None if decision is None else decision.get("primary_metric")
    return {
        "terminal_status": _canonical_status(payload.get("status")),
        "reason_code": reason,
        "verified": payload.get("verified", False),
        "retryable": _kernel_retryable(payload),
        "primary_metric": primary_metric,
        "candidate_value": None if decision is None else decision.get("candidate_value"),
        "baseline_value": None if decision is None else decision.get("baseline_value"),
        "improvement": None if decision is None else decision.get("improvement"),
        "promotion_margin": None if decision is None else decision.get("promotion_margin"),
        "gate_evaluations": [] if decision is None else decision.get("gate_evaluations", []),
    }


def _accepted_diagnosis(node: Mapping[str, object]) -> bool:
    registration = _registration(node)
    terminal = _terminal(node)
    diagnosis_fact = _diagnosis_fact(node)
    diagnosis = _diagnosis(node)
    observation = _terminal_observation(node)
    if None in (registration, terminal, diagnosis_fact, diagnosis, observation):
        return False
    assert registration is not None
    assert terminal is not None
    assert diagnosis_fact is not None
    assert diagnosis is not None
    assert observation is not None
    experiment_id = node.get("experiment_id")
    evidence = diagnosis.get("terminal_evidence")
    if not isinstance(evidence, Mapping):
        return False
    identity_pairs = (
        (diagnosis.get("experiment_id"), experiment_id),
        (diagnosis.get("generation_id"), registration.get("generation_id")),
        (diagnosis.get("compatibility_digest"), registration.get("compatibility_digest")),
        (diagnosis.get("proposal_id"), registration.get("proposal_id")),
        (diagnosis.get("proposal_digest"), registration.get("proposal_digest")),
        (diagnosis.get("hypothesis_class_id"), registration.get("hypothesis_class_id")),
        (diagnosis.get("evaluation_scope_id"), registration.get("evaluation_scope_id")),
        (evidence.get("experiment_id"), experiment_id),
        (evidence.get("event_id"), terminal.get("event_id")),
        (evidence.get("event_hash"), terminal.get("event_hash")),
    )
    return (
        all(_public_json_equal(left, right) for left, right in identity_pairs)
        and _public_json_equal(diagnosis.get("observation"), observation)
        and diagnosis.get("authorized_action") is None
        and diagnosis_fact.get("diagnosis_id") is not None
    )


def _gates_pass(payload: Mapping[str, object]) -> bool:
    decision = _decision(payload)
    if decision is None:
        return False
    gates = decision.get("gate_evaluations", [])
    if not isinstance(gates, list):
        return False
    for raw_gate in gates:
        if not isinstance(raw_gate, Mapping):
            return False
        if raw_gate.get("role") in {"hard", "support"} and raw_gate.get("passed") is not True:
            return False
    return True


def _active_registration(
    node: Mapping[str, object],
    generation_id: object,
    compatibility_digest: object,
) -> bool:
    registration = _registration(node)
    return (
        registration is not None
        and _public_json_equal(registration.get("generation_id"), generation_id)
        and _public_json_equal(registration.get("compatibility_digest"), compatibility_digest)
    )


def _latest_ids(nodes: Sequence[Mapping[str, object]]) -> set[object]:
    superseded = {
        registration.get("retry_of")
        for node in nodes
        if (registration := _registration(node)) is not None
        and registration.get("retry_of") is not None
    }
    return {node.get("experiment_id") for node in nodes} - superseded


def _conclusive_rejection(node: Mapping[str, object]) -> bool:
    payload = _terminal_payload(node)
    observation = _terminal_observation(node)
    if payload is None or observation is None or not _accepted_diagnosis(node):
        return False
    margin = observation.get("promotion_margin")
    return (
        _canonical_status(payload.get("status")) == "REJECTED"
        and payload.get("reason_code") == "NO_MEANINGFUL_IMPROVEMENT"
        and payload.get("verified") is True
        and isinstance(margin, (int, float))
        and not isinstance(margin, bool)
        and margin <= 0
        and _gates_pass(payload)
        and "error" not in payload
    )


def _class_lifecycle(
    nodes: Sequence[Mapping[str, object]],
    contract: Mapping[str, object],
    generation_id: object,
    compatibility_digest: object,
) -> dict[str, str]:
    counts: Counter[str] = Counter()
    for node in nodes:
        registration = _registration(node)
        if (
            registration is not None
            and _active_registration(node, generation_id, compatibility_digest)
            and _conclusive_rejection(node)
            and isinstance(registration.get("hypothesis_class_id"), str)
        ):
            counts[str(registration["hypothesis_class_id"])] += 1
    result: dict[str, str] = {}
    for raw_class in _sequence(contract.get("hypothesis_classes"), "hypothesis classes"):
        class_contract = _mapping(raw_class, "hypothesis class")
        class_id = _text(class_contract.get("id"), "hypothesis class id")
        limit = _integer(
            class_contract.get("conclusive_rejection_limit"),
            "conclusive rejection limit",
        )
        result[class_id] = "closed" if counts[class_id] >= limit else "open"
    return result


def _support_failure_axis(node: Mapping[str, object]) -> str | None:
    payload = _terminal_payload(node)
    observation = _terminal_observation(node)
    diagnosis = _diagnosis(node)
    if payload is None or observation is None:
        return None
    if payload.get("verified") is not True:
        return "SUPPORT_VERIFIED_FALSE"
    decision = _decision(payload)
    margin = None if decision is None else decision.get("promotion_margin")
    if not isinstance(margin, (int, float)) or isinstance(margin, bool) or margin <= 0:
        return "SUPPORT_NONPOSITIVE_MARGIN"
    if decision is not None and isinstance(decision.get("gate_evaluations", []), list):
        for raw_gate in decision.get("gate_evaluations", []):
            if isinstance(raw_gate, Mapping) and raw_gate.get("passed") is not True:
                if raw_gate.get("role") == "hard":
                    return "SUPPORT_FAILED_HARD_GATE"
                if raw_gate.get("role") == "support":
                    return "SUPPORT_FAILED_SUPPORT_GATE"
    if "error" in payload:
        return "SUPPORT_TOP_LEVEL_ERROR_KEY"
    if diagnosis is None or not _public_json_equal(diagnosis.get("observation"), observation):
        return "SUPPORT_OBSERVATION_MISMATCH"
    return None


def _supported_without_lifecycle(node: Mapping[str, object]) -> bool:
    payload = _terminal_payload(node)
    observation = _terminal_observation(node)
    if payload is None or observation is None or not _accepted_diagnosis(node):
        return False
    decision = _decision(payload)
    margin = None if decision is None else decision.get("promotion_margin")
    return (
        _terminal(node).get("event_type") == "EXPERIMENT_TERMINATED"  # type: ignore[union-attr]
        and _canonical_status(payload.get("status")) == "VALIDATED"
        and payload.get("reason_code") == "PRIMARY_METRIC_IMPROVED"
        and payload.get("verified") is True
        and decision is not None
        and _canonical_status(decision.get("status")) == "VALIDATED"
        and decision.get("reason_code") == "PRIMARY_METRIC_IMPROVED"
        and isinstance(margin, (int, float))
        and not isinstance(margin, bool)
        and margin > 0
        and _gates_pass(payload)
        and "error" not in payload
    )


def _contract_cap(contract: Mapping[str, object]) -> int:
    if "max_active_branches" in contract:
        return _integer(contract.get("max_active_branches"), "max active branches")
    frontier = _mapping(contract.get("frontier"), "frontier contract")
    return _integer(frontier.get("max_active_branches"), "max active branches")


def _replication_scopes(contract: Mapping[str, object]) -> list[str]:
    result: list[str] = []
    for raw_scope in _sequence(contract.get("evaluation_scopes"), "evaluation scopes"):
        scope = _mapping(raw_scope, "evaluation scope")
        if scope.get("role") == "replication":
            result.append(_text(scope.get("id"), "evaluation scope id"))
    return result


def _used_replication_scopes(
    nodes: Sequence[Mapping[str, object]],
    candidate_digest: object,
    replication_scopes: Sequence[str],
    generation_id: object,
    compatibility_digest: object,
) -> list[str]:
    registered = {
        registration.get("evaluation_scope_id")
        for node in nodes
        if (registration := _registration(node)) is not None
        and _active_registration(node, generation_id, compatibility_digest)
        and _public_json_equal(registration.get("candidate_digest"), candidate_digest)
        and registration.get("evaluation_scope_id") in replication_scopes
    }
    return [scope for scope in replication_scopes if scope in registered]


def _derive_frontiers(raw_input: Mapping[str, object]) -> dict[str, object]:
    generation_id = raw_input.get("active_generation_id")
    compatibility_digest = raw_input.get("active_compatibility_digest")
    contract = _mapping(raw_input.get("contract"), "frontier contract")
    nodes = [
        _mapping(raw, "raw node") for raw in _sequence(raw_input.get("raw_nodes"), "raw nodes")
    ]
    latest = _latest_ids(nodes)
    lifecycle = _class_lifecycle(nodes, contract, generation_id, compatibility_digest)
    supported: list[Mapping[str, object]] = []
    for node in nodes:
        registration = _registration(node)
        if (
            registration is not None
            and node.get("experiment_id") in latest
            and _active_registration(node, generation_id, compatibility_digest)
            and lifecycle.get(str(registration.get("hypothesis_class_id"))) == "open"
            and _supported_without_lifecycle(node)
        ):
            supported.append(node)

    supported_ids = {node.get("experiment_id") for node in supported}
    consumed = {
        registration.get("parent_experiment_id")
        for node in supported
        if (registration := _registration(node)) is not None
        and registration.get("parent_experiment_id") in supported_ids
    }
    leaves = [node for node in supported if node.get("experiment_id") not in consumed]
    supported_by_id = {node.get("experiment_id"): node for node in supported}
    replication_scopes = _replication_scopes(contract)

    def maturity(node: Mapping[str, object]) -> str:
        registration = _registration(node)
        assert registration is not None
        parent = supported_by_id.get(registration.get("parent_experiment_id"))
        parent_registration = None if parent is None else _registration(parent)
        if (
            registration.get("action") == "replicate"
            and registration.get("evaluation_scope_id") in replication_scopes
            and parent_registration is not None
            and _public_json_equal(
                parent_registration.get("candidate_digest"),
                registration.get("candidate_digest"),
            )
            and not _public_json_equal(
                parent_registration.get("evaluation_scope_id"),
                registration.get("evaluation_scope_id"),
            )
        ):
            return "replicated"
        return "provisional"

    def rank_key(node: Mapping[str, object]) -> tuple[int, int, str]:
        terminal = _terminal(node)
        assert terminal is not None
        sequence = _integer(terminal.get("event_sequence"), "terminal event sequence")
        return (
            0 if maturity(node) == "replicated" else 1,
            -sequence,
            _text(node.get("experiment_id"), "experiment id"),
        )

    leaves.sort(key=rank_key)
    cap = _contract_cap(contract)
    diversity: list[Mapping[str, object]] = []
    seen_classes: set[object] = set()
    for node in leaves:
        registration = _registration(node)
        assert registration is not None
        class_id = registration.get("hypothesis_class_id")
        if class_id not in seen_classes and len(diversity) < cap:
            diversity.append(node)
            seen_classes.add(class_id)
    fill = [node for node in leaves if node not in diversity][: max(0, cap - len(diversity))]
    selected = [*diversity, *fill]

    def public_entry(node: Mapping[str, object]) -> dict[str, object]:
        registration = _registration(node)
        terminal = _terminal(node)
        diagnosis_fact = _diagnosis_fact(node)
        assert registration is not None and terminal is not None and diagnosis_fact is not None
        used = _used_replication_scopes(
            nodes,
            registration.get("candidate_digest"),
            replication_scopes,
            generation_id,
            compatibility_digest,
        )
        actions = ["ablate", "exploit"]
        if any(scope not in used for scope in replication_scopes):
            actions.append("replicate")
        return {
            "experiment_id": node.get("experiment_id"),
            "proposal_id": registration.get("proposal_id"),
            "diagnosis_id": diagnosis_fact.get("diagnosis_id"),
            "hypothesis_class_id": registration.get("hypothesis_class_id"),
            "evaluation_scope_id": registration.get("evaluation_scope_id"),
            "action": registration.get("action"),
            "parent_experiment_id": registration.get("parent_experiment_id"),
            "candidate_digest": registration.get("candidate_digest"),
            "terminal_event_sequence": terminal.get("event_sequence"),
            "maturity": maturity(node),
            "eligible_actions": actions,
            "authorized_action": None,
        }

    retry_candidates: list[Mapping[str, object]] = []
    for node in nodes:
        registration = _registration(node)
        payload = _terminal_payload(node)
        diagnosis = _diagnosis(node)
        if (
            registration is not None
            and payload is not None
            and diagnosis is not None
            and node.get("experiment_id") in latest
            and _active_registration(node, generation_id, compatibility_digest)
            and lifecycle.get(str(registration.get("hypothesis_class_id"))) == "open"
            and _accepted_diagnosis(node)
            and _kernel_retryable(payload)
            and _mapping(diagnosis.get("observation"), "diagnosis observation").get("retryable")
            is True
        ):
            retry_candidates.append(node)
    retry_candidates.sort(
        key=lambda node: (
            -_integer(_terminal(node).get("event_sequence"), "terminal event sequence"),  # type: ignore[union-attr]
            _text(node.get("experiment_id"), "experiment id"),
        )
    )

    return {
        "nodes": nodes,
        "class_lifecycle": lifecycle,
        "supported": supported,
        "consumed": consumed,
        "leaves": leaves,
        "diversity": diversity,
        "fill": fill,
        "selected": selected,
        "semantic_frontier": {
            "max_active_branches": cap,
            "eligible_total": len(leaves),
            "returned": len(selected),
            "truncated": len(selected) < len(leaves),
            "blocked_by": [],
            "entries": [public_entry(node) for node in selected],
            "authorized_action": None,
        },
        "retry_candidates": retry_candidates,
        "replication_scopes": replication_scopes,
    }


def _case_inputs(fixture: Mapping[str, object]) -> list[Mapping[str, object]]:
    rows: list[Mapping[str, object]] = []
    flat_groups = ("consumption_counterfactuals", "exclusions", "stop_cases")
    nested_groups = (
        "frontier_cap_counterfactuals",
        "action_derivation_cases",
        "retry_class_gate_cases",
        "retry_frontier_exclusion_cases",
    )
    for key in flat_groups:
        for raw_row in _sequence(fixture.get(key), key):
            row = _mapping(raw_row, f"{key} row")
            rows.append(_mapping(row.get("input"), f"{key} input"))
    for key in nested_groups:
        group = _mapping(fixture.get(key), key)
        for raw_row in _sequence(group.get("cases"), f"{key} cases"):
            row = _mapping(raw_row, f"{key} row")
            rows.append(_mapping(row.get("input"), f"{key} input"))
    return rows


def _contains_display_selector(value: object) -> bool:
    if isinstance(value, Mapping):
        return bool(_DISPLAY_SELECTOR_KEYS.intersection(value)) or any(
            _contains_display_selector(item) for item in value.values()
        )
    if isinstance(value, list):
        return any(_contains_display_selector(item) for item in value)
    return False


def _budget_contract(contract: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(contract.get("budget"), "budget contract")


def _budget_facts(raw_input: Mapping[str, object]) -> dict[str, object]:
    contract = _mapping(raw_input.get("contract"), "study contract")
    budget = _budget_contract(contract)
    ledger = _mapping(raw_input.get("budget_ledger"), "budget ledger")
    remaining = {
        "attempts": _integer(budget.get("max_attempts"), "max attempts")
        - _integer(ledger.get("attempts_used"), "attempts used"),
        "elapsed_milliseconds": _integer(
            budget.get("max_elapsed_milliseconds"), "max elapsed milliseconds"
        )
        - _integer(
            ledger.get("elapsed_milliseconds_reserved"),
            "elapsed milliseconds reserved",
        ),
    }
    reservation = {
        "attempts": 1,
        "elapsed_milliseconds": _integer(
            budget.get("elapsed_reservation_per_attempt_milliseconds"),
            "elapsed reservation",
        ),
    }
    max_cost = budget.get("max_cost_microunits")
    cost_reservation = budget.get("cost_reservation_per_attempt_microunits")
    if max_cost is not None or cost_reservation is not None:
        remaining["cost_microunits"] = _integer(max_cost, "max cost") - _integer(
            ledger.get("cost_microunits_reserved"), "cost reserved"
        )
        reservation["cost_microunits"] = _integer(cost_reservation, "cost reservation")
    feasible = {
        dimension: remaining[dimension] >= amount for dimension, amount in reservation.items()
    }
    first_attempt_capacity = all(feasible.values())
    retry_capacity = first_attempt_capacity and _integer(
        ledger.get("retries_used"), "retries used"
    ) < _integer(budget.get("max_retries"), "max retries")
    exhausted = [
        dimension
        for dimension in ("attempts", "elapsed_milliseconds", "cost_microunits")
        if dimension in feasible and not feasible[dimension]
    ]
    return {
        "remaining": remaining,
        "reservation": reservation,
        "feasible": feasible,
        "first_attempt_capacity": first_attempt_capacity,
        "retry_capacity": retry_capacity,
        "exhausted_dimensions": exhausted,
    }


def _stop_facts(raw_input: Mapping[str, object]) -> dict[str, object]:
    generation_id = raw_input.get("active_generation_id")
    compatibility_digest = raw_input.get("active_compatibility_digest")
    contract = _mapping(raw_input.get("contract"), "study contract")
    budget = _budget_facts(raw_input)
    pool = [
        _mapping(raw, "raw node")
        for key in ("raw_node_history", "raw_node_pool")
        for raw in _sequence(raw_input.get(key), key)
    ]
    lifecycle = _class_lifecycle(pool, contract, generation_id, compatibility_digest)
    all_classes_closed = bool(lifecycle) and all(state == "closed" for state in lifecycle.values())
    untrusted: list[tuple[int, str]] = []
    for raw_terminal in _sequence(raw_input.get("terminal_history"), "terminal history"):
        terminal = _mapping(raw_terminal, "terminal history item")
        if (
            _public_json_equal(terminal.get("generation_id"), generation_id)
            and _public_json_equal(terminal.get("compatibility_digest"), compatibility_digest)
            and _canonical_status(terminal.get("status")) == "UNTRUSTED"
        ):
            untrusted.append(
                (
                    _integer(terminal.get("event_sequence"), "terminal event sequence"),
                    _text(terminal.get("experiment_id"), "experiment id"),
                )
            )
    for node in pool:
        registration = _registration(node)
        terminal = _terminal(node)
        payload = _terminal_payload(node)
        if (
            registration is not None
            and terminal is not None
            and payload is not None
            and _active_registration(node, generation_id, compatibility_digest)
            and _canonical_status(payload.get("status")) == "UNTRUSTED"
        ):
            untrusted.append(
                (
                    _integer(terminal.get("event_sequence"), "terminal event sequence"),
                    _text(node.get("experiment_id"), "experiment id"),
                )
            )
    untrusted_ids = [item[1] for item in sorted(set(untrusted))]
    reasons: list[str] = []
    if untrusted_ids:
        reasons.append("UNTRUSTED")
    exhausted = cast(list[str], budget["exhausted_dimensions"])
    if exhausted:
        reasons.append("BUDGET_EXHAUSTED")
    if all_classes_closed:
        reasons.append("ALL_CLASSES_CLOSED")
    return {
        "reasons": reasons,
        "untrusted_experiment_ids": untrusted_ids,
        "all_classes_closed": all_classes_closed,
        "class_lifecycle": lifecycle,
        **budget,
    }


def _events_from_history(raw_case: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw_input = _mapping(raw_case.get("input"), "full-state input")
    return [
        _mapping(raw, "event") for raw in _sequence(raw_input.get("event_history"), "event history")
    ]


def _canonical_history_facts(raw_case: Mapping[str, object]) -> dict[str, object] | None:
    events = _events_from_history(raw_case)
    generation_events = [
        event
        for event in events
        if event.get("event_type") == "research.study_generation_opened.v1"
    ]
    if not generation_events:
        return None
    generation_payload = _mapping(generation_events[-1].get("payload"), "generation payload")
    generation_id = generation_payload.get("generation_id")
    seal = _mapping(generation_payload.get("evaluation_seal"), "evaluation seal")
    compatibility_digest = seal.get("compatibility_digest")
    contract = _mapping(generation_payload.get("contract"), "study contract")
    registrations: dict[object, Mapping[str, object]] = {}
    terminals: dict[object, tuple[Mapping[str, object], Mapping[str, object]]] = {}
    diagnoses: dict[object, Mapping[str, object]] = {}
    attempts_used = 0
    retries_used = 0
    elapsed_reserved = 0
    cost_reserved = 0
    for event in events:
        payload = event.get("payload")
        if not isinstance(payload, Mapping):
            continue
        if event.get("event_type") == "EXPERIMENT_REGISTERED":
            experiment_id = payload.get("experiment_id")
            if not _public_json_equal(payload.get("generation_id"), generation_id):
                continue
            registrations[experiment_id] = payload
            debit = payload.get("budget_debit")
            if isinstance(debit, Mapping):
                attempts_used += _integer(debit.get("attempts"), "attempt debit")
                retries_used += _integer(debit.get("retries"), "retry debit")
                elapsed_reserved += _integer(
                    debit.get("reserved_elapsed_milliseconds"), "elapsed debit"
                )
                cost = debit.get("reserved_cost_microunits")
                if cost is not None:
                    cost_reserved += _integer(cost, "cost debit")
        elif event.get("event_type") in {
            "EXPERIMENT_TERMINATED",
            "EXPERIMENT_STATUS_CHANGED",
        }:
            terminals[payload.get("experiment_id")] = (event, payload)
        elif event.get("event_type") == "research.experiment_diagnosed.v1":
            body = payload.get("diagnosis")
            if isinstance(body, Mapping):
                diagnoses[body.get("experiment_id")] = body

    normalized_nodes: list[dict[str, object]] = []
    for experiment_id, registration in registrations.items():
        proposal = registration.get("proposal")
        proposal_map = _mapping(proposal, "proposal") if isinstance(proposal, Mapping) else {}
        terminal_pair = terminals.get(experiment_id)
        terminal_fact: dict[str, object] | None = None
        if terminal_pair is not None:
            terminal_event, terminal_payload = terminal_pair
            terminal_fact = {
                "event_type": terminal_event.get("event_type"),
                "event_id": terminal_event.get("event_id"),
                "event_hash": terminal_event.get("hash"),
                "event_sequence": terminal_event.get("sequence"),
                "payload": dict(terminal_payload),
            }
        diagnosis = diagnoses.get(experiment_id)
        diagnosis_fact: dict[str, object] | None = None
        if diagnosis is not None:
            diagnosis_event = next(
                (
                    event
                    for event in events
                    if event.get("event_type") == "research.experiment_diagnosed.v1"
                    and isinstance(event.get("payload"), Mapping)
                    and _public_json_equal(
                        _mapping(event["payload"], "diagnosis payload").get("diagnosis"),
                        diagnosis,
                    )
                ),
                None,
            )
            diagnosis_payload = (
                None
                if diagnosis_event is None
                else _mapping(diagnosis_event.get("payload"), "diagnosis payload")
            )
            diagnosis_fact = {
                "event_type": "research.experiment_diagnosed.v1",
                "event_id": None if diagnosis_event is None else diagnosis_event.get("event_id"),
                "event_hash": None if diagnosis_event is None else diagnosis_event.get("hash"),
                "event_sequence": None
                if diagnosis_event is None
                else diagnosis_event.get("sequence"),
                "diagnosis_id": None
                if diagnosis_payload is None
                else diagnosis_payload.get("diagnosis_id"),
                "diagnosis": dict(diagnosis),
            }
        normalized_nodes.append(
            {
                "experiment_id": experiment_id,
                "registration_fact": {
                    "event_type": "EXPERIMENT_REGISTERED",
                    "event_sequence": next(
                        event.get("sequence")
                        for event in events
                        if event.get("event_type") == "EXPERIMENT_REGISTERED"
                        and isinstance(event.get("payload"), Mapping)
                        and _public_json_equal(
                            _mapping(event["payload"], "registration payload").get("experiment_id"),
                            experiment_id,
                        )
                    ),
                    "payload": {
                        "generation_id": registration.get("generation_id"),
                        "compatibility_digest": registration.get("compatibility_digest"),
                        "proposal_id": registration.get("proposal_id"),
                        "proposal_digest": registration.get("proposal_digest"),
                        "hypothesis_class_id": proposal_map.get("hypothesis_class_id"),
                        "evaluation_scope_id": registration.get("evaluation_scope_id"),
                        "action": proposal_map.get("action"),
                        "parent_experiment_id": proposal_map.get("parent_experiment_id"),
                        "candidate_digest": registration.get("candidate_digest"),
                        "attempt": registration.get("attempt"),
                        "retry_of": registration.get("retry_of"),
                    },
                },
                "terminal_fact": terminal_fact,
                "diagnosis_fact": diagnosis_fact,
            }
        )
    ledger = {
        "attempts_used": attempts_used,
        "retries_used": retries_used,
        "elapsed_milliseconds_reserved": elapsed_reserved,
        "cost_microunits_reserved": cost_reserved,
    }
    raw_input = {
        "active_generation_id": generation_id,
        "active_compatibility_digest": compatibility_digest,
        "contract": contract,
        "budget_ledger": ledger,
        "raw_nodes": normalized_nodes,
    }
    lifecycle = _class_lifecycle(normalized_nodes, contract, generation_id, compatibility_digest)
    budget = _budget_facts(raw_input)
    untrusted = sorted(
        _text(node.get("experiment_id"), "experiment id")
        for node in normalized_nodes
        if (payload := _terminal_payload(node)) is not None
        and _canonical_status(payload.get("status")) == "UNTRUSTED"
    )
    all_closed = bool(lifecycle) and all(value == "closed" for value in lifecycle.values())
    reasons: list[str] = []
    if untrusted:
        reasons.append("UNTRUSTED")
    if budget["exhausted_dimensions"]:
        reasons.append("BUDGET_EXHAUSTED")
    if all_closed:
        reasons.append("ALL_CLASSES_CLOSED")
    latest = _latest_ids(normalized_nodes)
    retry_candidates = [
        node
        for node in normalized_nodes
        if node.get("experiment_id") in latest
        and _active_registration(node, generation_id, compatibility_digest)
        and (registration := _registration(node)) is not None
        and lifecycle.get(str(registration.get("hypothesis_class_id"))) == "open"
        and (payload := _terminal_payload(node)) is not None
        and _kernel_retryable(payload)
        and _accepted_diagnosis(node)
    ]
    return {
        "stop_reasons": reasons,
        "retry_candidates": retry_candidates,
    }


def _changed_node_exclusion_axis(
    node: Mapping[str, object],
    generation_id: object,
    compatibility_digest: object,
) -> str:
    registration = _registration(node)
    if registration is None:
        return "NON_SCIENTIFIC"
    if not _public_json_equal(registration.get("generation_id"), generation_id):
        return "GENERATION_MISMATCH"
    if not _public_json_equal(registration.get("compatibility_digest"), compatibility_digest):
        return "COMPATIBILITY_MISMATCH"
    terminal = _terminal(node)
    if terminal is None:
        return "NONTERMINAL"
    if terminal.get("event_type") != "EXPERIMENT_TERMINATED":
        return "UNSUPPORTED_TERMINAL"
    if _diagnosis(node) is None:
        return "DIAGNOSIS_REQUIRED"
    payload = _terminal_payload(node)
    assert payload is not None
    status = _canonical_status(payload.get("status"))
    if status == "UNTRUSTED":
        return "UNTRUSTED_STOP"
    if status == "TIMED_OUT":
        return "RETRY_FRONTIER_ONLY"
    if status == "INSUFFICIENT_EVIDENCE":
        return "NOT_SUPPORTED_INSUFFICIENT"
    if status in {"INVALID", "INVALID_EXPERIMENT"}:
        return "NOT_SUPPORTED_INVALID"
    if status == "REJECTED":
        return "NOT_SUPPORTED_REJECTED"
    if status == "VALIDATED":
        return _support_failure_axis(node) or "UNEXPLAINED"
    return "NOT_SUPPORTED_OTHER"


def verify_retry_frontiers(
    inputs: Mapping[str, object],
    fixture_source: FixtureLoader,
) -> dict[str, object]:
    """Observe latest-attempt and class-gated retry frontiers."""

    transition = _fixture(inputs, "transition_fixture", fixture_source)
    frontier = _fixture(inputs, "frontier_fixture", fixture_source)
    full_state_cases = [
        _mapping(raw, "full-state case")
        for raw in _sequence(transition.get("full_state_cases"), "full-state cases")
    ]
    canonical_retry_cases: list[dict[str, object]] = []
    for raw_case in full_state_cases:
        facts = _canonical_history_facts(raw_case)
        if facts is not None and facts["retry_candidates"]:
            canonical_retry_cases.append(facts)
    latest_attempt = max(
        (
            _integer(_registration(node).get("attempt"), "attempt")  # type: ignore[union-attr]
            for facts in canonical_retry_cases
            for node in cast(list[Mapping[str, object]], facts["retry_candidates"])
        ),
        default=0,
    )
    canonical_eligible = max(
        (
            len(cast(list[Mapping[str, object]], facts["retry_candidates"]))
            for facts in canonical_retry_cases
        ),
        default=0,
    )

    base_input = _mapping(frontier.get("input"), "frontier input")
    base = _derive_frontiers(base_input)
    base_retry = cast(list[Mapping[str, object]], base["retry_candidates"])
    retry_statuses = list(
        dict.fromkeys(
            _canonical_status(_terminal_payload(node).get("status"))  # type: ignore[union-attr]
            for node in base_retry
        )
    )

    class_group = _mapping(frontier.get("retry_class_gate_cases"), "retry class cases")
    class_rows = [
        _mapping(raw, "retry class row")
        for raw in _sequence(class_group.get("cases"), "retry class rows")
    ]
    closed_exclusions = 0
    class_returned = 0
    for row in class_rows:
        row_input = _mapping(row.get("input"), "retry class input")
        row_engine = _derive_frontiers(row_input)
        generation_id = row_input.get("active_generation_id")
        compatibility_digest = row_input.get("active_compatibility_digest")
        lifecycle = cast(dict[str, str], row_engine["class_lifecycle"])
        nodes = cast(list[Mapping[str, object]], row_engine["nodes"])
        latest = _latest_ids(nodes)
        all_retryable = [
            node
            for node in nodes
            if node.get("experiment_id") in latest
            and _active_registration(node, generation_id, compatibility_digest)
            and (payload := _terminal_payload(node)) is not None
            and _kernel_retryable(payload)
            and _accepted_diagnosis(node)
        ]
        closed_exclusions += sum(
            lifecycle.get(str(_registration(node).get("hypothesis_class_id"))) == "closed"  # type: ignore[union-attr]
            for node in all_retryable
        )
        class_returned += len(cast(list[Mapping[str, object]], row_engine["retry_candidates"]))

    exclusion_group = _mapping(
        frontier.get("retry_frontier_exclusion_cases"),
        "retry frontier exclusion cases",
    )
    exclusion_rows = [
        _mapping(raw, "retry exclusion row")
        for raw in _sequence(exclusion_group.get("cases"), "retry exclusion rows")
    ]
    retained = sum(
        len(
            cast(
                list[Mapping[str, object]],
                _derive_frontiers(_mapping(row.get("input"), "retry exclusion input"))[
                    "retry_candidates"
                ],
            )
        )
        for row in exclusion_rows
    )
    stop_rows = [
        _mapping(raw, "stop row") for raw in _sequence(frontier.get("stop_cases"), "stop cases")
    ]
    retry_budget_nodes = 0
    for row in stop_rows:
        row_input = _mapping(row.get("input"), "stop input")
        facts = _stop_facts(row_input)
        if facts["first_attempt_capacity"] is True and facts["retry_capacity"] is False:
            retry_budget_nodes += len(_sequence(row_input.get("raw_node_pool"), "raw node pool"))

    return {
        "canonical_retry_full_state_cases": len(canonical_retry_cases),
        "canonical_retry_latest_attempt": latest_attempt,
        "canonical_retry_eligible": canonical_eligible,
        "frontier_fixture_retry_eligible": len(base_retry),
        "non_allowlist_retry_positive_cases": len(retry_statuses),
        "non_allowlist_retry_positive_statuses": retry_statuses,
        "retry_budget_raw_nodes": retry_budget_nodes,
        "retry_class_gate_cases": len(class_rows),
        "retry_class_closed_exclusions": closed_exclusions,
        "retry_frontier_exclusion_cases": len(exclusion_rows),
        "retry_frontier_exclusion_axes_with_closed_class": len(exclusion_rows)
        + int(closed_exclusions > 0),
        "retry_frontier_exclusion_retained_entries": retained,
    }


def derive_semantic_frontier(
    inputs: Mapping[str, object],
    fixture_source: FixtureLoader,
) -> dict[str, object]:
    """Derive the positive semantic frontier and cap/action properties."""

    fixture = _fixture(inputs, "fixture", fixture_source)
    base_input = _mapping(fixture.get("input"), "frontier input")
    base = _derive_frontiers(base_input)
    raw_nodes = cast(list[Mapping[str, object]], base["nodes"])
    supported = cast(list[Mapping[str, object]], base["supported"])
    consumed = cast(set[object], base["consumed"])
    leaves = cast(list[Mapping[str, object]], base["leaves"])
    selected = cast(list[Mapping[str, object]], base["selected"])

    cap_group = _mapping(
        fixture.get("frontier_cap_counterfactuals"), "frontier cap counterfactuals"
    )
    cap_rows = [
        _mapping(raw, "frontier cap row")
        for raw in _sequence(cap_group.get("cases"), "frontier cap rows")
    ]
    cap_results: dict[int, dict[str, object]] = {}
    for row in cap_rows:
        row_input = _mapping(row.get("input"), "frontier cap input")
        _digest(row_input)
        result = _derive_frontiers(row_input)
        cap = cast(dict[str, object], result["semantic_frontier"])["max_active_branches"]
        cap_results[_integer(cap, "derived cap")] = result
    cap_two = cap_results[2]
    cap_two_selected = cast(list[Mapping[str, object]], cap_two["selected"])

    action_group = _mapping(fixture.get("action_derivation_cases"), "action cases")
    action_rows = [
        _mapping(raw, "action row") for raw in _sequence(action_group.get("cases"), "action rows")
    ]
    registered_replications = 0
    successful_replications = 0
    retry_registrations = 0
    registration_only_fresh = 0
    distinct_pairs = 0
    used_scope_total = 0
    unused_scope_total = 0
    public_replicate_actions = 0
    provisional_classes: set[object] = set()
    replication_required_classes: set[object] = set()
    for row in action_rows:
        row_input = _mapping(row.get("input"), "action input")
        result = _derive_frontiers(row_input)
        nodes = cast(list[Mapping[str, object]], result["nodes"])
        replication_scopes = cast(list[str], result["replication_scopes"])
        generation_id = row_input.get("active_generation_id")
        compatibility_digest = row_input.get("active_compatibility_digest")
        replication_nodes = [
            node
            for node in nodes
            if (registration := _registration(node)) is not None
            and _active_registration(node, generation_id, compatibility_digest)
            and registration.get("evaluation_scope_id") in replication_scopes
        ]
        registered_replications += len(replication_nodes)
        successful_replications += sum(
            _supported_without_lifecycle(node) and _registration(node).get("action") == "replicate"  # type: ignore[union-attr]
            for node in replication_nodes
        )
        retry_registrations += sum(
            _registration(node).get("retry_of") is not None  # type: ignore[union-attr]
            for node in replication_nodes
        )
        registration_only_fresh += sum(
            _terminal(node) is None and _registration(node).get("retry_of") is None  # type: ignore[union-attr]
            for node in replication_nodes
        )
        pairs = {
            (
                _registration(node).get("candidate_digest"),  # type: ignore[union-attr]
                _registration(node).get("evaluation_scope_id"),  # type: ignore[union-attr]
            )
            for node in replication_nodes
        }
        distinct_pairs += len(pairs)
        supported_nodes = cast(list[Mapping[str, object]], result["supported"])
        for node in supported_nodes:
            registration = _registration(node)
            assert registration is not None
            used = _used_replication_scopes(
                nodes,
                registration.get("candidate_digest"),
                replication_scopes,
                generation_id,
                compatibility_digest,
            )
            if not any(
                _registration(candidate).get("action") == "replicate"  # type: ignore[union-attr]
                and _supported_without_lifecycle(candidate)
                and _public_json_equal(
                    _registration(candidate).get("parent_experiment_id"),  # type: ignore[union-attr]
                    node.get("experiment_id"),
                )
                for candidate in nodes
            ):
                provisional_classes.add(registration.get("hypothesis_class_id"))
                if any(scope not in used for scope in replication_scopes):
                    replication_required_classes.add(registration.get("hypothesis_class_id"))
        candidate_digests = {
            _registration(node).get("candidate_digest")  # type: ignore[union-attr]
            for node in cast(list[Mapping[str, object]], result["leaves"])
        }
        for candidate_digest in candidate_digests:
            used = _used_replication_scopes(
                nodes,
                candidate_digest,
                replication_scopes,
                generation_id,
                compatibility_digest,
            )
            used_scope_total += len(used)
            unused_scope_total += sum(scope not in used for scope in replication_scopes)
        semantic = cast(dict[str, object], result["semantic_frontier"])
        for entry in cast(list[Mapping[str, object]], semantic["entries"]):
            public_replicate_actions += int("replicate" in entry["eligible_actions"])  # type: ignore[operator]

    decisive_gate_nodes = sum(
        bool(
            (payload := _terminal_payload(node)) is not None
            and (decision := _decision(payload)) is not None
            and isinstance(decision.get("gate_evaluations"), list)
            and decision.get("gate_evaluations")
            and _gates_pass(payload)
        )
        for node in supported
    )
    all_rows = _case_inputs(fixture)
    selector_free_rows = sum(not _contains_display_selector(row) for row in all_rows)
    semantic = cast(dict[str, object], base["semantic_frontier"])
    return {
        "raw_nodes": len(raw_nodes),
        "derived_supported_nodes": len(supported),
        "consumed_supported_parents": len(consumed),
        "derived_semantic_leaves": len(leaves),
        "eligible_total": semantic["eligible_total"],
        "returned": semantic["returned"],
        "ordered_experiment_ids": [node.get("experiment_id") for node in selected],
        "truncated": semantic["truncated"],
        "frontier_cap_counterfactuals": len(cap_rows),
        "frontier_cap_property_caps": sorted(cap_results),
        "frontier_cap_returned_by_cap": {
            str(cap): cast(dict[str, object], cap_results[cap]["semantic_frontier"])["returned"]
            for cap in sorted(cap_results)
        },
        "cap_two_eligible_total": cast(dict[str, object], cap_two["semantic_frontier"])[
            "eligible_total"
        ],
        "cap_two_returned": len(cap_two_selected),
        "cap_two_ordered_experiment_ids": [node.get("experiment_id") for node in cap_two_selected],
        "action_derivation_cases": len(action_rows),
        "action_derivation_registered_replication_attempts": registered_replications,
        "action_derivation_qualifying_successful_replications": successful_replications,
        "action_derivation_provisional_support_classes": len(provisional_classes),
        "action_derivation_replication_required_classes": len(replication_required_classes),
        "action_derivation_public_replicate_actions": public_replicate_actions,
        "action_derivation_retry_registrations": retry_registrations,
        "action_derivation_registration_only_fresh_scopes": registration_only_fresh,
        "action_derivation_distinct_candidate_scope_pairs": distinct_pairs,
        "action_derivation_used_replication_scopes": used_scope_total,
        "action_derivation_unused_replication_scopes": unused_scope_total,
        "decisive_supported_nodes_with_passed_hard_and_support_gates": decisive_gate_nodes,
        "selector_free_observer_rows": selector_free_rows,
    }


def execute_frontier_exclusions(
    inputs: Mapping[str, object],
    fixture_source: FixtureLoader,
) -> dict[str, object]:
    """Execute selector-free semantic-frontier exclusion rows."""

    fixture = _fixture(inputs, "fixture", fixture_source)
    base_input = _mapping(fixture.get("input"), "frontier input")
    base_result = _derive_frontiers(base_input)
    base_nodes = {
        node.get("experiment_id"): node
        for node in cast(list[Mapping[str, object]], base_result["nodes"])
    }
    base_lifecycle = cast(dict[str, str], base_result["class_lifecycle"])
    base_consumed = cast(set[object], base_result["consumed"])
    rows = [
        _mapping(raw, "exclusion row") for raw in _sequence(fixture.get("exclusions"), "exclusions")
    ]
    axes: list[str] = []
    excluded = 0
    for row in rows:
        row_input = _mapping(row.get("input"), "exclusion input")
        _digest(row_input)
        result = _derive_frontiers(row_input)
        nodes = cast(list[Mapping[str, object]], result["nodes"])
        by_id = {node.get("experiment_id"): node for node in nodes}
        changed = [
            node
            for experiment_id, node in by_id.items()
            if experiment_id not in base_nodes
            or not _public_json_equal(node, base_nodes[experiment_id])
        ]
        lifecycle = cast(dict[str, str], result["class_lifecycle"])
        newly_closed = {
            class_id
            for class_id, state in lifecycle.items()
            if state == "closed" and base_lifecycle.get(class_id) != "closed"
        }
        consumed = cast(set[object], result["consumed"])
        newly_consumed = consumed - base_consumed
        if newly_closed:
            axis = "HYPOTHESIS_CLASS_CLOSED"
            target_ids = {
                experiment_id
                for experiment_id, node in base_nodes.items()
                if (
                    (registration := _registration(node)) is not None
                    and registration.get("hypothesis_class_id") in newly_closed
                )
            }
        elif newly_consumed:
            axis = "SUCCESSFUL_CHILD_CONSUMED"
            target_ids = set(newly_consumed)
        elif not changed:
            superseded = {
                registration.get("retry_of")
                for node in nodes
                if (registration := _registration(node)) is not None
                and registration.get("retry_of") is not None
            }
            axis = "RETRY_SUPERSEDED" if superseded else "UNEXPLAINED"
            target_ids = set(superseded)
        else:
            axis = _changed_node_exclusion_axis(
                changed[0],
                row_input.get("active_generation_id"),
                row_input.get("active_compatibility_digest"),
            )
            target_ids = {
                node.get("experiment_id")
                for node in changed
                if node.get("experiment_id") in base_nodes
            }
        if not target_ids:
            raise AssertionError("exclusion row has no independently derived target")
        semantic_leaf_ids = {
            node.get("experiment_id") for node in cast(list[Mapping[str, object]], result["leaves"])
        }
        public_entry_ids = {
            entry.get("experiment_id")
            for entry in cast(
                list[Mapping[str, object]],
                cast(Mapping[str, object], result["semantic_frontier"])["entries"],
            )
        }
        is_excluded = target_ids.isdisjoint(semantic_leaf_ids | public_entry_ids)
        axes.append(axis)
        excluded += int(is_excluded)
    return {
        "exclusion_axes": len(set(axes)),
        "exclusion_subcases": len(rows),
        "shared_support_predicate_exclusion_axes": len(set(axes) & _SUPPORT_FAILURE_AXES),
        "excluded": excluded,
        "unexpectedly_eligible": len(rows) - excluded,
    }


def execute_frontier_consumption_counterfactuals(
    inputs: Mapping[str, object],
    fixture_source: FixtureLoader,
) -> dict[str, object]:
    """Execute direct-child, grandchild, and unrelated consumption facts."""

    fixture = _fixture(inputs, "fixture", fixture_source)
    rows = [
        _mapping(raw, "consumption row")
        for raw in _sequence(
            fixture.get("consumption_counterfactuals"), "consumption counterfactuals"
        )
    ]
    qualifying_direct = 0
    failed_direct_consumes = 0
    grandchild_consumes = 0
    unrelated_consumes = 0
    for row in rows:
        row_input = _mapping(row.get("input"), "consumption input")
        _digest(row_input)
        result = _derive_frontiers(
            {
                **dict(row_input),
                "contract": {
                    "hypothesis_classes": [
                        {"id": class_id, "conclusive_rejection_limit": 1_000_000}
                        for class_id in sorted(
                            {
                                str(_registration(node).get("hypothesis_class_id"))
                                for node in [
                                    _mapping(raw, "consumption node")
                                    for raw in _sequence(row_input.get("raw_nodes"), "raw nodes")
                                ]
                                if _registration(node) is not None
                            }
                        )
                    ],
                    "evaluation_scopes": [
                        {"id": "replication-1", "role": "replication"},
                        {"id": "replication-2", "role": "replication"},
                    ],
                    "max_active_branches": 100,
                },
            }
        )
        nodes = cast(list[Mapping[str, object]], result["nodes"])
        supported_ids = {
            node.get("experiment_id")
            for node in cast(list[Mapping[str, object]], result["supported"])
        }
        consumed = cast(set[object], result["consumed"])
        if len(nodes) == 2:
            first, second = nodes
            second_registration = _registration(second)
            assert second_registration is not None
            direct = _public_json_equal(
                second_registration.get("parent_experiment_id"),
                first.get("experiment_id"),
            )
            if direct and first.get("experiment_id") in supported_ids:
                if second.get("experiment_id") in supported_ids:
                    qualifying_direct += int(first.get("experiment_id") in consumed)
                else:
                    failed_direct_consumes += int(first.get("experiment_id") in consumed)
            elif (
                first.get("experiment_id") in supported_ids
                and second.get("experiment_id") in supported_ids
            ):
                unrelated_consumes += int(first.get("experiment_id") in consumed)
        elif len(nodes) == 3:
            ancestor, bridge, grandchild = nodes
            bridge_registration = _registration(bridge)
            grandchild_registration = _registration(grandchild)
            assert bridge_registration is not None and grandchild_registration is not None
            is_grandchild = _public_json_equal(
                bridge_registration.get("parent_experiment_id"),
                ancestor.get("experiment_id"),
            ) and _public_json_equal(
                grandchild_registration.get("parent_experiment_id"),
                bridge.get("experiment_id"),
            )
            if is_grandchild and grandchild.get("experiment_id") in supported_ids:
                grandchild_consumes += int(ancestor.get("experiment_id") in consumed)
    return {
        "counterfactuals": len(rows),
        "qualifying_direct_child_consumes": qualifying_direct,
        "failed_direct_child_consumes": failed_direct_consumes,
        "grandchild_consumes": grandchild_consumes,
        "unrelated_child_consumes": unrelated_consumes,
    }


def execute_frontier_stop_cases(
    inputs: Mapping[str, object],
    fixture_source: FixtureLoader,
) -> dict[str, object]:
    """Execute reservation-aware stop and retry-budget frontiers."""

    frontier = _fixture(inputs, "frontier_fixture", fixture_source)
    transition = _fixture(inputs, "transition_fixture", fixture_source)
    rows = [
        _mapping(raw, "stop row") for raw in _sequence(frontier.get("stop_cases"), "stop cases")
    ]
    stop_results = [_stop_facts(_mapping(row.get("input"), "stop input")) for row in rows]
    transition_cases = [
        _mapping(raw, "full-state case")
        for raw in _sequence(transition.get("full_state_cases"), "full-state cases")
    ]
    canonical_stop_cases = sum(
        bool(history["stop_reasons"])
        for row in transition_cases
        if (history := _canonical_history_facts(row)) is not None
    )
    base_contract = _mapping(
        _mapping(frontier.get("input"), "frontier input").get("contract"),
        "base contract",
    )
    base_budget = _budget_contract(base_contract)
    positive_shortfall = 0
    equality_feasible = 0
    alternate_attempts = 0
    alternate_retries = 0
    retry_budget_only = 0
    for row, row_facts in zip(rows, stop_results, strict=True):
        row_input = _mapping(row.get("input"), "stop input")
        remaining = cast(dict[str, int], row_facts["remaining"])
        reservation = cast(dict[str, int], row_facts["reservation"])
        feasible = cast(dict[str, bool], row_facts["feasible"])
        positive_shortfall += int(
            any(0 < remaining[dimension] < amount for dimension, amount in reservation.items())
        )
        equality_feasible += int(
            all(feasible.values())
            and any(remaining[dimension] == amount for dimension, amount in reservation.items())
        )
        budget = _budget_contract(_mapping(row_input.get("contract"), "contract"))
        alternate_attempts += int(
            not _public_json_equal(budget.get("max_attempts"), base_budget.get("max_attempts"))
        )
        alternate_retries += int(
            not _public_json_equal(budget.get("max_retries"), base_budget.get("max_retries"))
        )
        retry_budget_only += int(
            not row_facts["reasons"]
            and row_facts["first_attempt_capacity"] is True
            and row_facts["retry_capacity"] is False
        )
    return {
        "frontier_stop_cases": len(rows),
        "canonical_stop_full_state_cases": canonical_stop_cases,
        "untrusted_stop_cases": sum("UNTRUSTED" in item["reasons"] for item in stop_results),
        "budget_exhausted_stop_cases": sum(
            "BUDGET_EXHAUSTED" in item["reasons"] for item in stop_results
        ),
        "positive_remaining_insufficient_reservation_cases": positive_shortfall,
        "reservation_equality_feasible_cases": equality_feasible,
        "all_classes_closed_stop_cases": sum(
            "ALL_CLASSES_CLOSED" in item["reasons"] for item in stop_results
        ),
        "retry_budget_only_cases": retry_budget_only,
        "alternate_attempt_limit_cases": alternate_attempts,
        "alternate_retry_limit_cases": alternate_retries,
    }
