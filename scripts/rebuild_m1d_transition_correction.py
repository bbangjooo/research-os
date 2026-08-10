#!/usr/bin/env python3
"""Deterministically apply both RESULT-INVALID M1-D oracle corrections.

This script deliberately uses only the Python standard library.  It does not
import the Research OS reducer, public state serializers, or fixture observers.
The transformations are structural and the hashes/IDs are derived from the
documented canonical JSON formulas.  In the second correction, append identity
and time come only from literal input and its verified pre-head.  The public
contract leaves 29 rejected-gate error paths unspecified; those paths remain
explicit JSON null rather than being promoted to invented normative pointers.
Documentary row-match flags, display-label race assertions, and the inert
top-level expected summary are deliberately absent from the normative fixture.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/scientific_state/v3/m1d-transition-matrix.json"
PROJECT_ID = "fixture-m1d"
EVENT_KEYS = {
    "version",
    "sequence",
    "project_id",
    "event_id",
    "event_type",
    "occurred_at",
    "payload",
    "prev_hash",
    "hash",
}
ALLOWED_FAILURE_TYPES = {
    "mechanism",
    "implementation",
    "evidence",
    "constraint",
    "operational",
    "supported",
}
LIMIT_FOUR_CASES = (
    "class-b-limit-four-n-minus-one-open",
    "class-b-limit-four-exact-threshold-close",
    "class-b-limit-four-post-close-n-plus-one-preserves-origin",
)
EVENT_TYPE_BY_OPERATION = {
    "register_first_attempt": "EXPERIMENT_REGISTERED",
    "register_retry": "EXPERIMENT_REGISTERED",
    "record_diagnosis": "research.experiment_diagnosed.v1",
    "open_successor_generation": "research.study_generation_opened.v1",
}
TERMINAL_STATUSES = {
    "ACCEPTED",
    "SUCCEEDED",
    "COMPLETED",
    "INVALID_EXPERIMENT",
    "INVALID",
    "REJECTED",
    "VALIDATED",
    "UNTRUSTED",
    "INFRA_FAILED",
    "INSUFFICIENT_EVIDENCE",
    "TIMED_OUT",
    "CANCELLED",
}
STOP_REASON_ORDER = ("UNTRUSTED", "BUDGET_EXHAUSTED", "ALL_CLASSES_CLOSED")
BUDGET_DIMENSION_ORDER = ("attempts", "elapsed_milliseconds", "cost_microunits")
UNSPECIFIED_ERROR_PATH_CODES = {
    "STUDY_STOPPED",
    "DIAGNOSIS_REQUIRED",
    "STUDY_ACTIVE_EXPERIMENTS",
    "HYPOTHESIS_CLASS_CLOSED",
    "PROPOSAL_PARENT_MISMATCH",
    "PROPOSAL_PARENT_NOT_TERMINAL",
    "PROPOSAL_PARENT_NOT_SUPPORTED",
}
EXPECTED_CENSUS = {
    "terminal_pending_cases": 23,
    "full_state_cases": 54,
    "counting_taxonomy": 26,
    "gate_cases": 37,
    "gate_accepted": 7,
    "gate_rejected": 30,
    "race_schedules": 7,
    "race_operations": 14,
    "race_appended_events": 9,
    "histories": 121,
    "history_events": 896,
    "all_event_objects": 912,
    "class_states": 210,
    "diagnosis_wrappers": 266,
    "state_digests": 105,
}
TRANSITION_TOP_LEVEL_KEYS = {
    "schema_version",
    "kind",
    "project_id",
    "generation_id",
    "study_contract_digest",
    "observer_contract",
    "terminal_pending_cases",
    "full_state_cases",
    "counting_taxonomy",
    "gate_cases",
    "race_schedules",
    "canonical_history_unreachable_axes",
}
OBSERVER_CONTRACT_PROOF_KEYS = {
    "case_id_is_display_only",
    "event_sequences_contiguous",
    "hash_chain_required",
    "counting_taxonomy_prederived_predicate_inputs",
    "counting_taxonomy_observer_expected_accesses",
    "gate_expected_state_subset_forbidden",
    "gate_prederived_predicate_inputs",
    "gate_observer_expected_accesses",
    "display_id_label_rename_invariance_required",
    "display_id_label_rename_invariance_assertions",
}
OBSERVER_CONTRACT_KEYS = {
    "strip_before_observer",
    "full_state_observer_input_exact_fields",
    "race_observer_input_exact_fields",
    "race_precondition_input_exact_fields",
    "forbidden_dispatch",
    "forbidden_observer_access",
    "input_kind",
    "event_envelope_exact_fields",
    "event_hash_algorithm",
    "forbidden_input_expansion",
    "expected_state_kind",
    "production_observer",
    "race_setup_source",
    "counting_taxonomy_observer_receives",
    "counting_taxonomy_derivation_sources",
    "counting_taxonomy_forbidden_input_fields",
    "counting_taxonomy_decision_exact_fields",
    "counting_taxonomy_observation_exact_fields",
    "counting_taxonomy_gate_evaluation_exact_fields",
    "terminal_pending_observer_receives",
    "terminal_pending_case_input_exact_fields",
    "gate_observer_receives",
    "gate_case_input_exact_fields",
    "gate_expected_state_kind",
    "display_identity_fields_stripped_before_observer",
    "race_schedule_operation_exact_fields",
    "race_observer_receives",
}
COUNTING_PROPOSAL_KEYS = {
    "proposal_schema_version",
    "generation_id",
    "hypothesis_class_id",
    "parent_experiment_id",
    "action",
    "mechanism",
    "intervention_json_pointers",
    "predicted_effect",
    "falsifier",
    "candidate_digest",
    "evaluation_scope_id",
    "authorized_action",
}
COUNTING_DECISION_KEYS = {
    "status",
    "reason_code",
    "primary_metric",
    "candidate_value",
    "baseline_value",
    "improvement",
    "promotion_margin",
    "gate_evaluations",
    "authorized_action",
}
COUNTING_OBSERVATION_KEYS = {
    "terminal_status",
    "reason_code",
    "verified",
    "retryable",
    "primary_metric",
    "candidate_value",
    "baseline_value",
    "improvement",
    "promotion_margin",
    "gate_evaluations",
}
COUNTING_GATE_KEYS = {
    "id",
    "metric",
    "role",
    "operator",
    "threshold",
    "unit",
    "scale",
    "observed",
    "signed_slack",
    "normalized_slack",
    "passed",
}
PENDING_TERMINAL_STATUSES = TERMINAL_STATUSES | {"FAILED", "CRASHED"}
STATUS_ALIASES = {
    "SUCCESS": "SUCCEEDED",
    "PASSED": "SUCCEEDED",
    "COMPLETE": "COMPLETED",
    "TIMEOUT": "TIMED_OUT",
    "TIMEDOUT": "TIMED_OUT",
    "CANCELED": "CANCELLED",
    "ERROR": "FAILED",
}


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def kernel_digest(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def stable_id(namespace: str, *components: object) -> str:
    prefix = {"event": "evt", "experiment": "exp"}.get(namespace, namespace)
    return f"{prefix}_{kernel_digest([namespace, *components])[:32]}"


def canonical_float(value: float) -> str:
    """Render binary64 with the ECMAScript/RFC-8785 number spelling."""

    if not math.isfinite(value):
        raise ValueError("canonical public JSON forbids non-finite numbers")
    if value == 0.0:
        return "0"
    negative = value < 0
    rendered = repr(-value if negative else value).lower()
    mantissa, separator, exponent_text = rendered.partition("e")
    exponent = int(exponent_text) if separator else 0
    integer, point, fraction = mantissa.partition(".")
    digits = integer + (fraction if point else "")
    decimal_position = len(integer) + exponent
    leading = len(digits) - len(digits.lstrip("0"))
    digits = digits[leading:]
    decimal_position -= leading
    digits = digits.rstrip("0") or "0"
    if -6 < decimal_position <= 21:
        if decimal_position <= 0:
            body = "0." + ("0" * -decimal_position) + digits
        elif decimal_position >= len(digits):
            body = digits + ("0" * (decimal_position - len(digits)))
        else:
            body = digits[:decimal_position] + "." + digits[decimal_position:]
    else:
        scientific_exponent = decimal_position - 1
        coefficient = digits[0] + ("." + digits[1:] if len(digits) > 1 else "")
        sign = "+" if scientific_exponent >= 0 else ""
        body = f"{coefficient}e{sign}{scientific_exponent}"
    return "-" + body if negative else body


def utf16_key(value: str) -> bytes:
    return value.encode("utf-16-be")


def public_canonical_json(value: Any) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        if abs(value) > (1 << 53) - 1:
            raise ValueError("canonical public JSON integer exceeds safe range")
        return str(value)
    if isinstance(value, float):
        return canonical_float(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(public_canonical_json(item) for item in value) + "]"
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise TypeError("canonical public JSON object keys must be strings")
        return (
            "{"
            + ",".join(
                json.dumps(key, ensure_ascii=False, separators=(",", ":"))
                + ":"
                + public_canonical_json(value[key])
                for key in sorted(value, key=utf16_key)
            )
            + "}"
        )
    raise TypeError(f"unsupported canonical public JSON value: {type(value).__name__}")


def public_digest(value: Any) -> str:
    return hashlib.sha256(public_canonical_json(value).encode("utf-8")).hexdigest()


def public_json_equal(actual: Any, expected: Any) -> bool:
    """Compare values in the normative public canonical-JSON equality domain."""

    return public_canonical_json(actual) == public_canonical_json(expected)


def assert_public_json_equal(actual: Any, expected: Any, *, path: str) -> None:
    """Require public JSON equality, preserving bool/number but not int/float spelling."""

    actual_json = public_canonical_json(actual)
    expected_json = public_canonical_json(expected)
    if actual_json != expected_json:
        raise AssertionError(
            f"{path}: public canonical JSON mismatch "
            f"({actual_json[:160]!r} != {expected_json[:160]!r})"
        )


def experiment_id(payload: Mapping[str, Any]) -> str:
    proposal = require_dict(payload["proposal"], "registration Proposal")
    return stable_id(
        "experiment",
        PROJECT_ID,
        proposal["generation_id"],
        payload["compatibility_digest"],
        proposal["parent_experiment_id"],
        payload["candidate_digest"],
        proposal["evaluation_scope_id"],
        payload.get("attempt", 1),
    )


def require_dict(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    return value


def require_list(value: object, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{label} must be an array")
    return value


def by_id(rows: Iterable[dict[str, Any]], identifier: str) -> dict[str, Any]:
    matches = [row for row in rows if row.get("id") == identifier]
    if len(matches) != 1:
        raise AssertionError(f"expected exactly one row {identifier!r}")
    return matches[0]


def replace_scalars(value: Any, replacements: Mapping[object, object]) -> Any:
    if isinstance(value, dict):
        return {key: replace_scalars(item, replacements) for key, item in value.items()}
    if isinstance(value, list):
        return [replace_scalars(item, replacements) for item in value]
    try:
        return replacements.get(value, value)
    except TypeError:
        return value


def replace_failure_type(value: Any) -> None:
    if isinstance(value, dict):
        if value.get("failure_type") == "execution":
            value["failure_type"] = "operational"
        for item in value.values():
            replace_failure_type(item)
    elif isinstance(value, list):
        for item in value:
            replace_failure_type(item)


def event_digest(event: Mapping[str, Any]) -> str:
    unsigned = dict(event)
    unsigned.pop("hash", None)
    return kernel_digest(unsigned)


def event_time_after(history: list[dict[str, Any]]) -> str:
    if not history:
        instant = datetime(2000, 1, 1, tzinfo=timezone.utc)
    else:
        value = history[-1]["occurred_at"]
        if not isinstance(value, str) or not value.endswith("Z"):
            raise AssertionError("pre-head occurred_at is not canonical UTC")
        instant = datetime.fromisoformat(value.removesuffix("Z") + "+00:00")
    return (instant + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def deterministic_event(
    history: list[dict[str, Any]],
    *,
    event_type: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Build an append envelope from literal input and its verified pre-head only."""

    sequence = len(history) + 1
    previous_hash = None if not history else history[-1]["hash"]
    payload_value = copy.deepcopy(dict(payload))
    payload_digest = kernel_digest(payload_value)
    event: dict[str, Any] = {
        "event_id": stable_id(
            "event",
            PROJECT_ID,
            sequence,
            previous_hash,
            event_type,
            payload_digest,
        ),
        "event_type": event_type,
        "occurred_at": event_time_after(history),
        "payload": payload_value,
        "prev_hash": previous_hash,
        "project_id": PROJECT_ID,
        "sequence": sequence,
        "version": 1,
    }
    event["hash"] = event_digest(event)
    return event


def final_log_head(history: list[dict[str, Any]]) -> dict[str, Any]:
    if not history:
        return {"sequence": 0, "event_id": None, "event_hash": None}
    event = history[-1]
    return {
        "sequence": event["sequence"],
        "event_id": event["event_id"],
        "event_hash": event["hash"],
    }


def normalized_event_type(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip().upper().replace(".", "_").replace("-", "_")


def canonical_status(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().upper().replace("-", "_")
    return STATUS_ALIASES.get(normalized, normalized)


def valid_counting_proposal(
    proposal: Mapping[str, Any],
    *,
    proposal_digest: object,
    proposal_id: object,
) -> bool:
    """Validate the frozen Proposal using only its literal public contract."""

    if set(proposal) != COUNTING_PROPOSAL_KEYS:
        return False
    text_fields = (
        "generation_id",
        "hypothesis_class_id",
        "action",
        "mechanism",
        "predicted_effect",
        "falsifier",
        "candidate_digest",
        "evaluation_scope_id",
    )
    pointers = proposal.get("intervention_json_pointers")
    schema_version = proposal.get("proposal_schema_version")
    return (
        isinstance(schema_version, int)
        and not isinstance(schema_version, bool)
        and schema_version == 1
        and proposal.get("authorized_action") is None
        and (
            proposal.get("parent_experiment_id") is None
            or isinstance(proposal.get("parent_experiment_id"), str)
        )
        and all(isinstance(proposal.get(field), str) and proposal[field] for field in text_fields)
        and isinstance(pointers, list)
        and bool(pointers)
        and all(isinstance(pointer, str) and pointer.startswith("/") for pointer in pointers)
        and isinstance(proposal_digest, str)
        and public_digest(dict(proposal)) == proposal_digest
        and isinstance(proposal_id, str)
        and stable_id("proposal", PROJECT_ID, proposal_digest) == proposal_id
    )


def counting_observation_matches(
    terminal: Mapping[str, Any],
    observation: Mapping[str, Any],
) -> bool:
    decision = terminal.get("decision")
    if not isinstance(decision, Mapping):
        return False
    if set(decision) != COUNTING_DECISION_KEYS:
        return False
    if set(observation) != COUNTING_OBSERVATION_KEYS:
        return False
    if decision.get("authorized_action") is not None:
        return False
    pairs = (
        ("terminal_status", "status"),
        ("reason_code", "reason_code"),
        ("primary_metric", "primary_metric"),
        ("candidate_value", "candidate_value"),
        ("baseline_value", "baseline_value"),
        ("improvement", "improvement"),
        ("promotion_margin", "promotion_margin"),
        ("gate_evaluations", "gate_evaluations"),
    )
    return all(
        public_json_equal(observation.get(left), decision.get(right)) for left, right in pairs
    )


def all_counting_gates_pass(observation: Mapping[str, Any]) -> bool:
    gates = observation.get("gate_evaluations")
    if not isinstance(gates, list):
        return False
    for gate in gates:
        if not isinstance(gate, Mapping) or set(gate) != COUNTING_GATE_KEYS:
            return False
        if gate.get("role") in {"hard", "support"} and gate.get("passed") is not True:
            return False
    return True


def counting_attempt_proposal_id(
    root: Mapping[str, Any],
    attempt: Mapping[str, Any],
) -> str | None:
    """Classify one conclusive-rejection attempt without reading its expected row."""

    registration = attempt.get("registration")
    terminal = attempt.get("terminal")
    diagnosis = attempt.get("diagnosis")
    persisted = root.get("persisted_proposal")
    scope = root.get("persisted_evaluation_scope")
    if not all(
        isinstance(value, Mapping)
        for value in (registration, terminal, diagnosis, persisted, scope)
    ):
        return None
    assert isinstance(registration, Mapping)
    assert isinstance(terminal, Mapping)
    assert isinstance(diagnosis, Mapping)
    assert isinstance(persisted, Mapping)
    assert isinstance(scope, Mapping)
    proposal = persisted.get("proposal")
    observation = diagnosis.get("observation")
    if not isinstance(proposal, Mapping) or not isinstance(observation, Mapping):
        return None
    proposal_id = persisted.get("proposal_id")
    proposal_digest = persisted.get("proposal_digest")
    if not valid_counting_proposal(
        proposal,
        proposal_digest=proposal_digest,
        proposal_id=proposal_id,
    ):
        return None
    if root.get("active_study_contract_schema_version") != 2:
        return None
    if registration.get("generation_id") != root.get("active_generation_id"):
        return None
    if registration.get("compatibility_digest") != root.get("active_compatibility_digest"):
        return None
    if scope.get("role") not in {"development", "diagnostic"}:
        return None
    if registration.get("evaluation_scope_id") != scope.get("id"):
        return None
    if proposal.get("evaluation_scope_id") != scope.get("id"):
        return None
    if registration.get("proposal_id") != proposal_id:
        return None
    if registration.get("proposal_digest") != proposal_digest:
        return None
    if not public_json_equal(registration.get("proposal"), proposal):
        return None
    if terminal.get("status") != "REJECTED":
        return None
    if terminal.get("reason_code") != "NO_MEANINGFUL_IMPROVEMENT":
        return None
    if terminal.get("verified") is not True or terminal.get("retryable") is not False:
        return None
    if "error" in terminal:
        return None
    if diagnosis.get("authorized_action") is not None:
        return None
    if not counting_observation_matches(terminal, observation):
        return None
    if observation.get("verified") is not True or observation.get("retryable") is not False:
        return None
    margin = observation.get("promotion_margin")
    if isinstance(margin, bool) or not isinstance(margin, (int, float)) or margin > 0:
        return None
    if not all_counting_gates_pass(observation):
        return None
    assert isinstance(proposal_id, str)
    return proposal_id


def observe_counting_input(data: Mapping[str, Any]) -> dict[str, Any]:
    """Derive the complete counting comparison surface from literal input only."""

    if "attempts" in data:
        attempts = require_list(data["attempts"], "counting attempts")
        proposal_ids = {
            proposal_id
            for raw_attempt in attempts
            if (
                proposal_id := counting_attempt_proposal_id(
                    data,
                    require_dict(raw_attempt, "counting attempt"),
                )
            )
            is not None
        }
        ordered = sorted(proposal_ids)
        return {
            "count_delta": len(ordered),
            "counted_proposal_ids": ordered,
            "maximum_count_per_proposal_chain": int(bool(ordered)),
        }
    if "registration" in data:
        proposal_id = counting_attempt_proposal_id(data, data)
        if proposal_id is None:
            return {"count_delta": 0}
        return {"count_delta": 1, "counted_proposal_id": proposal_id}
    if canonical_status(data.get("status")) == "UNTRUSTED":
        return {"count_delta": 0, "study_stop_reason": "UNTRUSTED"}
    return {"count_delta": 0}


def terminal_pending_ids(history: list[dict[str, Any]]) -> list[str]:
    """Reduce pending Diagnosis IDs from the latest literal generation only."""

    generation_index = -1
    for index, event in enumerate(history):
        if event.get("event_type") == "research.study_generation_opened.v1":
            generation_index = index
    registrations: set[str] = set()
    terminals: list[str] = []
    diagnosed: set[str] = set()
    for event in history[generation_index + 1 :]:
        payload = require_dict(event.get("payload"), "terminal-pending event payload")
        event_type = event.get("event_type")
        experiment_id = payload.get("experiment_id")
        if (
            event_type == "EXPERIMENT_REGISTERED"
            and isinstance(payload.get("proposal"), Mapping)
            and isinstance(experiment_id, str)
        ):
            registrations.add(experiment_id)
        elif (
            isinstance(experiment_id, str)
            and experiment_id in registrations
            and (
                event_type == "EXPERIMENT_TERMINATED"
                or (
                    event_type == "EXPERIMENT_STATUS_CHANGED"
                    and canonical_status(payload.get("status")) in PENDING_TERMINAL_STATUSES
                )
            )
        ):
            if experiment_id not in terminals:
                terminals.append(experiment_id)
        elif event_type == "research.experiment_diagnosed.v1":
            diagnosis = payload.get("diagnosis")
            if isinstance(diagnosis, Mapping) and isinstance(diagnosis.get("experiment_id"), str):
                diagnosed.add(diagnosis["experiment_id"])
    return [experiment_id for experiment_id in terminals if experiment_id not in diagnosed]


def observe_terminal_pending_input(
    operation: str,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive a terminal-pending row comparison without consulting expected data."""

    if operation not in {"reduce_terminal_pending", "observe_terminal_pending"}:
        raise AssertionError(f"unknown terminal-pending operation {operation!r}")
    if set(data) != {"event_history"}:
        raise AssertionError("terminal-pending input is not literal-only")
    history = [
        require_dict(event, "terminal-pending event")
        for event in require_list(data["event_history"], "terminal-pending history")
    ]
    status_event = next(
        (
            event
            for event in reversed(history)
            if event.get("event_type") in {"EXPERIMENT_TERMINATED", "EXPERIMENT_STATUS_CHANGED"}
        ),
        None,
    )
    if status_event is None:
        raise AssertionError("terminal-pending history has no status event")
    payload = require_dict(status_event.get("payload"), "terminal-pending status payload")
    raw_status = payload.get("status")
    if not isinstance(raw_status, str) or not raw_status:
        raise AssertionError("terminal-pending status is not non-empty text")
    terminal_status = canonical_status(raw_status)
    decision = payload.get("decision")
    decision_body = decision if isinstance(decision, Mapping) else {}
    pending = terminal_pending_ids(history)
    if operation == "reduce_terminal_pending":
        return {
            "terminal_status": terminal_status,
            "pending_diagnosis_experiment_ids": pending,
            "pending_count": len(pending),
        }
    reason_code = decision_body.get("reason_code", payload.get("reason_code"))
    if reason_code is None and status_event.get("event_type") == "EXPERIMENT_STATUS_CHANGED":
        reason_code = "STATUS_CHANGED"
    numeric_fields = (
        decision_body.get("candidate_value"),
        decision_body.get("baseline_value"),
        decision_body.get("improvement"),
        decision_body.get("promotion_margin"),
    )
    gate_evaluations = decision_body.get("gate_evaluations", [])
    if not isinstance(gate_evaluations, list):
        raise AssertionError("terminal-pending gate evaluations are not an array")
    experiment_id = payload.get("experiment_id")
    return {
        "raw_terminal_status": raw_status,
        "terminal_status": terminal_status,
        "reason_code": reason_code,
        "verified": payload.get("verified") is True,
        "primary_metric": decision_body.get("primary_metric", payload.get("primary_metric")),
        "numeric_fields_null": all(value is None for value in numeric_fields),
        "gate_evaluations": copy.deepcopy(gate_evaluations),
        "diagnosis_required": experiment_id in pending,
        "pending_diagnosis_experiment_ids": pending,
        "pending_count": len(pending),
        "normalization_applied": raw_status != terminal_status,
    }


def verify_counting_and_terminal_projections(matrix: Mapping[str, Any]) -> None:
    """Outer-compare all 49 projections against independent literal observations."""

    for index, raw_case in enumerate(matrix["counting_taxonomy"]):
        case = require_dict(raw_case, "counting row")
        data = require_dict(case.get("input"), "counting input")
        observed = observe_counting_input(data)
        expected = require_dict(case.get("expected"), "counting expected")
        assert_public_json_equal(
            expected,
            observed,
            path=f"/counting_taxonomy/{index}/expected ({case.get('id')})",
        )

    for index, raw_case in enumerate(matrix["terminal_pending_cases"]):
        case = require_dict(raw_case, "terminal-pending row")
        operation = case.get("operation")
        if not isinstance(operation, str):
            raise AssertionError(f"/terminal_pending_cases/{index}: missing operation")
        data = require_dict(case.get("input"), "terminal-pending input")
        observed = observe_terminal_pending_input(operation, data)
        expected = require_dict(case.get("expected"), "terminal-pending expected")
        assert_public_json_equal(
            expected,
            observed,
            path=f"/terminal_pending_cases/{index}/expected ({case.get('id')})",
        )


def is_terminal_event(event: Mapping[str, Any]) -> bool:
    event_type = normalized_event_type(event.get("event_type"))
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        return False
    status = payload.get("status")
    return event_type == "EXPERIMENT_TERMINATED" or (
        event_type == "EXPERIMENT_STATUS_CHANGED"
        and isinstance(status, str)
        and canonical_status(status) in PENDING_TERMINAL_STATUSES
    )


def decision_matches_diagnosis(
    terminal: Mapping[str, Any],
    diagnosis: Mapping[str, Any],
) -> bool:
    observation = diagnosis.get("observation")
    decision = terminal.get("decision")
    if not isinstance(observation, Mapping) or not isinstance(decision, Mapping):
        return False
    direct_pairs = (
        ("status", "terminal_status"),
        ("reason_code", "reason_code"),
        ("primary_metric", "primary_metric"),
    )
    if any(
        not public_json_equal(terminal.get(left), observation.get(right))
        for left, right in direct_pairs
    ):
        return False
    if not public_json_equal(terminal.get("verified"), observation.get("verified")):
        return False
    decision_pairs = (
        ("status", "terminal_status"),
        ("reason_code", "reason_code"),
        ("primary_metric", "primary_metric"),
        ("candidate_value", "candidate_value"),
        ("baseline_value", "baseline_value"),
        ("improvement", "improvement"),
        ("promotion_margin", "promotion_margin"),
        ("gate_evaluations", "gate_evaluations"),
    )
    return all(
        public_json_equal(decision.get(left), observation.get(right))
        for left, right in decision_pairs
    )


def supported_registration(snapshot: Mapping[str, Any], experiment_id: str) -> bool:
    registrations = snapshot["registrations"]
    terminals = snapshot["terminals"]
    diagnoses = snapshot["diagnoses"]
    registration = registrations.get(experiment_id)
    terminal_event = terminals.get(experiment_id)
    diagnosis_payload = diagnoses.get(experiment_id)
    if not all(
        isinstance(value, Mapping) for value in (registration, terminal_event, diagnosis_payload)
    ):
        return False
    assert isinstance(registration, Mapping)
    assert isinstance(terminal_event, Mapping)
    assert isinstance(diagnosis_payload, Mapping)
    proposal_id = registration.get("proposal_id")
    later_same_proposal = [
        item
        for item in registrations.values()
        if item.get("proposal_id") == proposal_id
        and item.get("experiment_id") != experiment_id
        and int(item.get("attempt", 0)) > int(registration.get("attempt", 0))
    ]
    if later_same_proposal:
        return False
    terminal = terminal_event.get("payload")
    diagnosis = diagnosis_payload.get("diagnosis")
    if not isinstance(terminal, Mapping) or not isinstance(diagnosis, Mapping):
        return False
    observation = diagnosis.get("observation")
    if not isinstance(observation, Mapping):
        return False
    gates = observation.get("gate_evaluations")
    return (
        terminal.get("status") == "VALIDATED"
        and terminal.get("reason_code") == "PRIMARY_METRIC_IMPROVED"
        and terminal.get("verified") is True
        and "error" not in terminal
        and diagnosis.get("experiment_id") == experiment_id
        and diagnosis.get("proposal_id") == proposal_id
        and decision_matches_diagnosis(terminal, diagnosis)
        and isinstance(observation.get("promotion_margin"), (int, float))
        and not isinstance(observation.get("promotion_margin"), bool)
        and observation["promotion_margin"] > 0
        and isinstance(gates, list)
        and all(isinstance(gate, Mapping) and gate.get("passed") is True for gate in gates)
    )


def conclusive_proposals(snapshot: Mapping[str, Any]) -> dict[str, set[str]]:
    result: dict[str, set[str]] = {}
    registrations = snapshot["registrations"]
    terminals = snapshot["terminals"]
    diagnoses = snapshot["diagnoses"]
    for experiment_id, diagnosis_payload in diagnoses.items():
        registration = registrations.get(experiment_id)
        terminal_event = terminals.get(experiment_id)
        if not isinstance(registration, Mapping) or not isinstance(terminal_event, Mapping):
            continue
        terminal = terminal_event.get("payload")
        diagnosis = diagnosis_payload.get("diagnosis")
        if not isinstance(terminal, Mapping) or not isinstance(diagnosis, Mapping):
            continue
        observation = diagnosis.get("observation")
        if not isinstance(observation, Mapping):
            continue
        gates = observation.get("gate_evaluations")
        margin = observation.get("promotion_margin")
        if not (
            terminal.get("status") == "REJECTED"
            and terminal.get("reason_code") == "NO_MEANINGFUL_IMPROVEMENT"
            and terminal.get("verified") is True
            and "error" not in terminal
            and diagnosis.get("experiment_id") == experiment_id
            and diagnosis.get("proposal_id") == registration.get("proposal_id")
            and decision_matches_diagnosis(terminal, diagnosis)
            and isinstance(margin, (int, float))
            and not isinstance(margin, bool)
            and margin <= 0
            and isinstance(gates, list)
            and all(isinstance(gate, Mapping) and gate.get("passed") is True for gate in gates)
        ):
            continue
        class_id = registration.get("proposal", {}).get("hypothesis_class_id")
        proposal_id = registration.get("proposal_id")
        if isinstance(class_id, str) and isinstance(proposal_id, str):
            result.setdefault(class_id, set()).add(proposal_id)
    return result


def semantic_snapshot(history: list[dict[str, Any]]) -> dict[str, Any]:
    generation_index = -1
    generation_payload: dict[str, Any] | None = None
    for index, event in enumerate(history):
        if event["event_type"] == "research.study_generation_opened.v1":
            generation_index = index
            generation_payload = require_dict(event["payload"], "generation payload")
    active = history[generation_index + 1 :] if generation_index >= 0 else history
    registrations: dict[str, dict[str, Any]] = {}
    registration_order: list[str] = []
    terminals: dict[str, dict[str, Any]] = {}
    terminal_order: list[str] = []
    diagnoses: dict[str, dict[str, Any]] = {}
    diagnosis_event_ids: dict[str, str] = {}
    ledger = [0, 0, 0, 0]
    for event in active:
        payload = require_dict(event["payload"], "active event payload")
        if event["event_type"] == "EXPERIMENT_REGISTERED" and isinstance(
            payload.get("proposal"), Mapping
        ):
            experiment_id = payload.get("experiment_id")
            if isinstance(experiment_id, str):
                registrations[experiment_id] = payload
                registration_order.append(experiment_id)
                debit = require_dict(payload["budget_debit"], "registration debit")
                ledger[0] += int(debit["attempts"])
                ledger[1] += int(debit["retries"])
                ledger[2] += int(debit["reserved_elapsed_milliseconds"])
                ledger[3] += int(debit.get("reserved_cost_microunits") or 0)
        elif is_terminal_event(event):
            experiment_id = payload.get("experiment_id")
            if isinstance(experiment_id, str) and experiment_id in registrations:
                terminals[experiment_id] = event
                terminal_order.append(experiment_id)
        elif event["event_type"] == "research.experiment_diagnosed.v1":
            body = payload.get("diagnosis")
            if isinstance(body, Mapping) and isinstance(body.get("experiment_id"), str):
                experiment_id = body["experiment_id"]
                diagnoses[experiment_id] = payload
                diagnosis_event_ids[experiment_id] = event["event_id"]
    snapshot: dict[str, Any] = {
        "generation": generation_payload,
        "registrations": registrations,
        "registration_order": registration_order,
        "terminals": terminals,
        "terminal_order": terminal_order,
        "diagnoses": diagnoses,
        "diagnosis_event_ids": diagnosis_event_ids,
        "ledger": tuple(ledger),
    }
    snapshot["pending"] = [
        experiment_id for experiment_id in terminal_order if experiment_id not in diagnoses
    ]
    snapshot["active_nonterminal"] = [
        experiment_id for experiment_id in registration_order if experiment_id not in terminals
    ]

    conclusive = conclusive_proposals(snapshot)
    closed_classes: set[str] = set()
    contract = None if generation_payload is None else generation_payload.get("contract")
    if isinstance(contract, Mapping):
        classes = contract.get("hypothesis_classes")
        if isinstance(classes, list):
            for raw_class in classes:
                if not isinstance(raw_class, Mapping):
                    continue
                class_id = raw_class.get("id")
                limit = raw_class.get("conclusive_rejection_limit")
                if (
                    isinstance(class_id, str)
                    and isinstance(limit, int)
                    and not isinstance(limit, bool)
                    and len(conclusive.get(class_id, set())) >= limit
                ):
                    closed_classes.add(class_id)
    snapshot["closed_classes"] = closed_classes

    untrusted = [
        experiment_id
        for experiment_id in terminal_order
        if require_dict(terminals[experiment_id]["payload"], "terminal payload").get("status")
        == "UNTRUSTED"
    ]
    exhausted: list[str] = []
    if isinstance(contract, Mapping):
        budget = contract.get("budget")
        if isinstance(budget, Mapping):
            attempts, _, elapsed, cost = ledger
            if attempts + 1 > int(budget["max_attempts"]):
                exhausted.append("attempts")
            elapsed_reservation = int(budget["elapsed_reservation_per_attempt_milliseconds"])
            if elapsed + elapsed_reservation > int(budget["max_elapsed_milliseconds"]):
                exhausted.append("elapsed_milliseconds")
            cost_limit = budget.get("max_cost_microunits")
            cost_reservation = budget.get("cost_reservation_per_attempt_microunits")
            if cost_limit is not None and cost_reservation is not None:
                if cost + int(cost_reservation) > int(cost_limit):
                    exhausted.append("cost_microunits")
    all_closed = False
    if isinstance(contract, Mapping) and isinstance(contract.get("hypothesis_classes"), list):
        class_ids = [
            item.get("id")
            for item in contract["hypothesis_classes"]
            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
        ]
        all_closed = bool(class_ids) and all(item in closed_classes for item in class_ids)
    stop_reasons = []
    if untrusted:
        stop_reasons.append("UNTRUSTED")
    if exhausted:
        stop_reasons.append("BUDGET_EXHAUSTED")
    if all_closed:
        stop_reasons.append("ALL_CLASSES_CLOSED")
    snapshot["untrusted"] = untrusted
    snapshot["budget_exhausted_dimensions"] = [
        item for item in BUDGET_DIMENSION_ORDER if item in exhausted
    ]
    snapshot["stop_reasons"] = [item for item in STOP_REASON_ORDER if item in stop_reasons]
    return snapshot


def request_class_id(snapshot: Mapping[str, Any], request: Mapping[str, Any]) -> str | None:
    retry_of = request.get("retry_of")
    if isinstance(retry_of, str):
        prior = snapshot["registrations"].get(retry_of)
        if isinstance(prior, Mapping):
            proposal = prior.get("proposal")
            if isinstance(proposal, Mapping) and isinstance(
                proposal.get("hypothesis_class_id"), str
            ):
                return proposal["hypothesis_class_id"]
    proposal = request.get("proposal")
    if isinstance(proposal, Mapping) and isinstance(proposal.get("hypothesis_class_id"), str):
        return proposal["hypothesis_class_id"]
    return None


def operation_error(
    history: list[dict[str, Any]],
    operation: str,
    request: Mapping[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    snapshot = semantic_snapshot(history)
    if operation == "record_diagnosis":
        body = request.get("diagnosis")
        if not isinstance(body, Mapping) or not isinstance(body.get("experiment_id"), str):
            raise AssertionError("literal Diagnosis request is not structurally valid")
        experiment_id = body["experiment_id"]
        existing = snapshot["diagnoses"].get(experiment_id)
        if isinstance(existing, Mapping) and not public_json_equal(existing.get("diagnosis"), body):
            return (
                "DIAGNOSIS_ALREADY_RECORDED",
                {
                    "experiment_id": experiment_id,
                    "diagnosis_id": existing["diagnosis_id"],
                    "path": "$.experiment_id",
                },
            )
        return None
    if operation == "open_successor_generation":
        if snapshot["pending"]:
            return (
                "DIAGNOSIS_REQUIRED",
                {"pending_diagnosis_experiment_ids": list(snapshot["pending"])},
            )
        if snapshot["active_nonterminal"]:
            return (
                "STUDY_ACTIVE_EXPERIMENTS",
                {"active_experiment_ids": list(snapshot["active_nonterminal"])},
            )
        return None
    if operation not in {"register_first_attempt", "register_retry"}:
        raise AssertionError(f"unsupported operation {operation!r}")
    if snapshot["stop_reasons"]:
        return "STUDY_STOPPED", {"reasons": list(snapshot["stop_reasons"])}
    if snapshot["pending"]:
        return (
            "DIAGNOSIS_REQUIRED",
            {"pending_diagnosis_experiment_ids": list(snapshot["pending"])},
        )
    class_id = request_class_id(snapshot, request)
    if class_id in snapshot["closed_classes"]:
        return "HYPOTHESIS_CLASS_CLOSED", {"hypothesis_class_id": class_id}
    proposal = request.get("proposal")
    if isinstance(proposal, Mapping) and proposal.get("action") == "replicate":
        parent_id = request.get("parent_id")
        if isinstance(parent_id, str):
            parent = snapshot["registrations"].get(parent_id)
            if not isinstance(parent, Mapping):
                return "PROPOSAL_PARENT_MISMATCH", {"parent_experiment_id": parent_id}
            if parent_id not in snapshot["terminals"]:
                return "PROPOSAL_PARENT_NOT_TERMINAL", {"parent_experiment_id": parent_id}
            if not supported_registration(snapshot, parent_id):
                return "PROPOSAL_PARENT_NOT_SUPPORTED", {"parent_experiment_id": parent_id}
    return None


def verify_canonical_request(operation: str, request: Mapping[str, Any]) -> None:
    if operation in {"register_first_attempt", "register_retry"}:
        if public_digest(request["candidate"]) != request["candidate_digest"]:
            raise AssertionError("registration candidate digest mismatch")
        proposal = require_dict(request["proposal"], "registration Proposal")
        if public_digest(proposal) != request["proposal_digest"]:
            raise AssertionError("registration Proposal digest mismatch")
        if stable_id("proposal", PROJECT_ID, request["proposal_digest"]) != request["proposal_id"]:
            raise AssertionError("registration Proposal ID mismatch")
        if experiment_id(request) != request["experiment_id"]:
            raise AssertionError("registration experiment ID mismatch")
    elif operation == "record_diagnosis":
        diagnosis = require_dict(request["diagnosis"], "Diagnosis body")
        if public_digest(diagnosis) != request["diagnosis_digest"]:
            raise AssertionError("Diagnosis digest mismatch")
        if (
            stable_id("diagnosis", PROJECT_ID, request["diagnosis_digest"])
            != request["diagnosis_id"]
        ):
            raise AssertionError("Diagnosis ID mismatch")
    elif operation == "open_successor_generation":
        if public_digest(request["contract"]) != request["study_contract_digest"]:
            raise AssertionError("successor contract digest mismatch")
        if public_digest(request["evaluation_seal"]) != request["evaluation_seal_digest"]:
            raise AssertionError("successor evaluation seal digest mismatch")
        expected_generation = stable_id(
            "generation",
            PROJECT_ID,
            request["predecessor_generation_id"],
            request["study_contract_digest"],
            request["evaluation_seal_digest"],
        )
        if request["generation_id"] != expected_generation:
            raise AssertionError("successor generation ID mismatch")


def operation_deltas(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    *,
    event_type: str | None,
    appended: bool,
    include_diagnosis: bool,
) -> dict[str, int]:
    before_ledger = before["ledger"]
    after_ledger = after["ledger"]
    result = {
        "canonical_events": int(appended),
        "registration_events": int(appended and event_type == "EXPERIMENT_REGISTERED"),
        "generation_events": int(appended and event_type == "research.study_generation_opened.v1"),
    }
    if include_diagnosis:
        result["diagnosis_events"] = int(
            appended and event_type == "research.experiment_diagnosed.v1"
        )
    result.update(
        {
            "budget_attempts": after_ledger[0] - before_ledger[0],
            "budget_retries": after_ledger[1] - before_ledger[1],
            "budget_elapsed_milliseconds": after_ledger[2] - before_ledger[2],
            "budget_cost_microunits": after_ledger[3] - before_ledger[3],
            "projection_rows": 0,
        }
    )
    return result


def simulate_operation(
    history: list[dict[str, Any]],
    operation: str,
    request: Mapping[str, Any],
    *,
    include_diagnosis_delta: bool,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    before = semantic_snapshot(history)
    error = operation_error(history, operation, request)
    zero = operation_deltas(
        before,
        before,
        event_type=None,
        appended=False,
        include_diagnosis=include_diagnosis_delta,
    )
    if error is not None:
        code, details = error
        return list(history), {
            "operation": operation,
            "success": False,
            "appended": False,
            "idempotent_reuse": False,
            "error_code": code,
            "error_path": details.get("path"),
            "error_details": details,
            "event": None,
            "deltas": zero,
        }

    if operation == "record_diagnosis":
        body = require_dict(request["diagnosis"], "Diagnosis request body")
        existing = before["diagnoses"].get(body["experiment_id"])
        if isinstance(existing, Mapping) and public_json_equal(existing.get("diagnosis"), body):
            return list(history), {
                "operation": operation,
                "success": True,
                "appended": False,
                "idempotent_reuse": True,
                "error_code": None,
                "error_path": None,
                "error_details": {},
                "event": None,
                "deltas": zero,
            }

    verify_canonical_request(operation, request)
    event_type = EVENT_TYPE_BY_OPERATION[operation]
    event = deterministic_event(history, event_type=event_type, payload=request)
    final_history = [*history, event]
    after = semantic_snapshot(final_history)
    return final_history, {
        "operation": operation,
        "success": True,
        "appended": True,
        "idempotent_reuse": False,
        "error_code": None,
        "error_path": None,
        "error_details": {},
        "event": event,
        "deltas": operation_deltas(
            before,
            after,
            event_type=event_type,
            appended=True,
            include_diagnosis=include_diagnosis_delta,
        ),
    }


def canonicalize_diagnosis_payload(
    payload: dict[str, Any],
    replacements: dict[object, object],
) -> None:
    transformed = replace_scalars(payload, replacements)
    payload.clear()
    payload.update(require_dict(transformed, "Diagnosis payload"))
    body = require_dict(payload["diagnosis"], "Diagnosis body")
    old_digest = payload["diagnosis_digest"]
    old_id = payload["diagnosis_id"]
    new_digest = public_digest(body)
    new_id = stable_id("diagnosis", PROJECT_ID, new_digest)
    payload["diagnosis_digest"] = new_digest
    payload["diagnosis_id"] = new_id
    replacements[old_digest] = new_digest
    replacements[old_id] = new_id


def canonicalize_registration_payload(
    payload: dict[str, Any],
    replacements: dict[object, object],
) -> None:
    transformed = replace_scalars(payload, replacements)
    payload.clear()
    payload.update(require_dict(transformed, "registration payload"))
    proposal = require_dict(payload["proposal"], "Proposal")
    if public_digest(payload["candidate"]) != payload["candidate_digest"]:
        raise AssertionError("candidate digest is not canonical")
    old_proposal_digest = payload["proposal_digest"]
    old_proposal_id = payload["proposal_id"]
    new_proposal_digest = public_digest(proposal)
    new_proposal_id = stable_id("proposal", PROJECT_ID, new_proposal_digest)
    payload["proposal_digest"] = new_proposal_digest
    payload["proposal_id"] = new_proposal_id
    replacements[old_proposal_digest] = new_proposal_digest
    replacements[old_proposal_id] = new_proposal_id

    old_experiment_id = payload["experiment_id"]
    new_experiment_id = experiment_id(payload)
    payload["experiment_id"] = new_experiment_id
    replacements[old_experiment_id] = new_experiment_id


def rebuild_history(
    history: list[dict[str, Any]],
    initial_replacements: Mapping[object, object] | None = None,
) -> tuple[dict[object, object], dict[str, dict[str, Any]]]:
    replacements: dict[object, object] = dict(initial_replacements or {})
    previous_hash: str | None = None
    events_by_id: dict[str, dict[str, Any]] = {}
    for expected_sequence, event in enumerate(history, 1):
        old_hash = event["hash"]
        event["sequence"] = expected_sequence
        event["prev_hash"] = previous_hash
        event_type = event["event_type"]
        payload = require_dict(event["payload"], "event payload")

        transformed = replace_scalars(payload, replacements)
        payload.clear()
        payload.update(require_dict(transformed, "event payload"))
        if event_type == "EXPERIMENT_REGISTERED" and "proposal" in payload:
            canonicalize_registration_payload(payload, replacements)
        elif event_type == "research.experiment_diagnosed.v1":
            canonicalize_diagnosis_payload(payload, replacements)

        event["hash"] = event_digest(event)
        replacements[old_hash] = event["hash"]
        previous_hash = event["hash"]
        events_by_id[event["event_id"]] = event
    return replacements, events_by_id


def canonicalize_state(
    state: dict[str, Any],
    replacements: Mapping[object, object],
    events_by_id: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    state = require_dict(replace_scalars(state, replacements), "expected state")
    for record in require_list(state.get("diagnoses", []), "state diagnoses"):
        record = require_dict(record, "Diagnosis record")
        event = events_by_id.get(record["diagnosis_event_id"])
        if event is None or event["event_type"] != "research.experiment_diagnosed.v1":
            raise AssertionError("expected Diagnosis record lacks its canonical event")
        payload = require_dict(event["payload"], "Diagnosis event payload")
        record["diagnosis_digest"] = payload["diagnosis_digest"]
        record["diagnosis_id"] = payload["diagnosis_id"]
        record["diagnosis_event_hash"] = event["hash"]
        record["event_sequence"] = event["sequence"]
        record["diagnosis"] = copy.deepcopy(payload["diagnosis"])

    for wrapper in require_list(state.get("class_states", []), "class states"):
        wrapper = require_dict(wrapper, "ClassState wrapper")
        body = require_dict(wrapper["class_state"], "ClassState body")
        wrapper["class_state_digest"] = public_digest(body)
        wrapper["class_state_id"] = stable_id(
            "classstate",
            PROJECT_ID,
            body["generation_id"],
            body["hypothesis_class_id"],
        )
    return state


def repair_full_case(case: dict[str, Any], *, limit_four: bool = False) -> None:
    replacements: dict[object, object] = {}
    if limit_four:
        generation_event = case["input"]["event_history"][1]
        generation_payload = require_dict(generation_event["payload"], "generation payload")
        old_generation = generation_payload["generation_id"]
        canonical_generation = stable_id(
            "generation",
            PROJECT_ID,
            generation_payload["predecessor_generation_id"],
            generation_payload["study_contract_digest"],
            generation_payload["evaluation_seal_digest"],
        )
        replacements[old_generation] = canonical_generation
        transformed = replace_scalars(case, replacements)
        case.clear()
        case.update(require_dict(transformed, "full-state case"))

    replace_failure_type(case)
    if case["id"] in {
        "class-b-limit-four-exact-threshold-close",
        "class-b-limit-four-post-close-n-plus-one-preserves-origin",
    }:
        registration = case["input"]["event_history"][17]["payload"]
        if registration["baseline_id"] not in {
            "base_m1d_diagnostic",
            "base_limit3_diagnostic-1",
        }:
            raise AssertionError("unexpected limit-four baseline ID")
        registration["baseline_id"] = "base_limit3_diagnostic-1"

    history = require_list(case["input"]["event_history"], "event history")
    history = [require_dict(event, "event") for event in history]
    replacements, events_by_id = rebuild_history(history, replacements)
    case["expected_state"] = canonicalize_state(case["expected_state"], replacements, events_by_id)
    case["expected"] = require_dict(
        replace_scalars(case["expected"], replacements), "full-state expected"
    )
    case["expected"]["post_state_digest"] = public_digest(case["expected_state"])


def repair_gate_nine(case: dict[str, Any]) -> None:
    replace_failure_type(case)
    history = [require_dict(event, "event") for event in case["input"]["event_history"]]
    replacements, events_by_id = rebuild_history(history)
    expected = require_dict(replace_scalars(case["expected"], replacements), "gate expected")
    expected["final_state"] = canonicalize_state(
        expected["final_state"], replacements, events_by_id
    )
    expected["final_state_digest"] = public_digest(expected["final_state"])
    last = history[-1]
    expected["final_log_head"] = {
        "sequence": last["sequence"],
        "event_id": last["event_id"],
        "event_hash": last["hash"],
    }
    case["expected"] = expected


def repair_gate_thirty_five(case: dict[str, Any]) -> None:
    history = [require_dict(event, "event") for event in case["input"]["event_history"]]
    registration = require_dict(history[6]["payload"], "pending registration")
    if registration["baseline_id"] not in {
        "base_m1d_development",
        "base_allclosed_development",
    }:
        raise AssertionError("unexpected all-closed baseline ID")
    registration["baseline_id"] = "base_allclosed_development"
    replacements, events_by_id = rebuild_history(history)

    request = require_dict(
        replace_scalars(case["input"]["request"], replacements), "Diagnosis request"
    )
    canonicalize_diagnosis_payload(request, replacements)
    case["input"]["request"] = request

    expected = require_dict(replace_scalars(case["expected"], replacements), "gate expected")
    appended = require_dict(expected["appended_event"], "appended event")
    old_appended_hash = appended["hash"]
    appended["payload"] = copy.deepcopy(request)
    appended["sequence"] = history[-1]["sequence"] + 1
    appended["prev_hash"] = history[-1]["hash"]
    appended["hash"] = event_digest(appended)
    replacements[old_appended_hash] = appended["hash"]
    events_by_id[appended["event_id"]] = appended

    expected = require_dict(replace_scalars(expected, replacements), "gate expected")
    expected["appended_event"] = appended
    expected["final_state"] = canonicalize_state(
        expected["final_state"], replacements, events_by_id
    )
    expected["final_state_digest"] = public_digest(expected["final_state"])
    expected["final_log_head"] = {
        "sequence": appended["sequence"],
        "event_id": appended["event_id"],
        "event_hash": appended["hash"],
    }
    case["expected"] = expected


def repair_expected_frontier(case: dict[str, Any], blockers: list[str]) -> None:
    state = require_dict(case["expected"]["final_state"], "gate final state")
    state["retry_frontier"]["blocked_by"] = blockers
    case["expected"]["final_state_digest"] = public_digest(state)


def normalize_full_expected(case: dict[str, Any]) -> None:
    expected = require_dict(case["expected"], "full-state expected")
    exact_keys = (
        "pre_state_digest",
        "post_state_digest",
        "history_event_count",
        "operation_deltas",
    )
    missing = [key for key in exact_keys if key not in expected]
    if missing:
        raise AssertionError(f"{case['id']}: missing full-state core {missing}")
    case["expected"] = {key: copy.deepcopy(expected[key]) for key in exact_keys}


def events_by_id(history: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {event["event_id"]: event for event in history}


def assert_state_projection(
    state: Mapping[str, Any],
    history: list[dict[str, Any]],
    *,
    label: str,
) -> None:
    snapshot = semantic_snapshot(history)
    generation = snapshot["generation"]
    if isinstance(generation, Mapping):
        assert_public_json_equal(
            state.get("active_generation_id"),
            generation.get("generation_id"),
            path=f"{label}/active_generation_id",
        )
        assert_public_json_equal(
            state.get("study_contract_digest"),
            generation.get("study_contract_digest"),
            path=f"{label}/study_contract_digest",
        )
        assert_public_json_equal(
            state.get("evaluation_seal_digest"),
            generation.get("evaluation_seal_digest"),
            path=f"{label}/evaluation_seal_digest",
        )
        assert_public_json_equal(
            state.get("contract"),
            generation.get("contract"),
            path=f"{label}/contract",
        )
    assert_public_json_equal(
        state.get("generation_count"),
        sum(event["event_type"] == "research.study_generation_opened.v1" for event in history),
        path=f"{label}/generation_count",
    )
    proposal_ids = {payload.get("proposal_id") for payload in snapshot["registrations"].values()}
    assert_public_json_equal(
        state.get("proposal_count"), len(proposal_ids), path=f"{label}/proposal_count"
    )
    assert_public_json_equal(
        state.get("diagnosis_count"),
        len(snapshot["diagnoses"]),
        path=f"{label}/diagnosis_count",
    )
    assert_public_json_equal(
        state.get("pending_diagnosis_experiment_ids"),
        snapshot["pending"],
        path=f"{label}/pending_diagnosis_experiment_ids",
    )
    stop = require_dict(state.get("study_stop"), "study stop")
    assert_public_json_equal(
        stop.get("reasons"), snapshot["stop_reasons"], path=f"{label}/study_stop/reasons"
    )
    assert_public_json_equal(
        stop.get("untrusted_experiment_ids"),
        snapshot["untrusted"],
        path=f"{label}/study_stop/untrusted_experiment_ids",
    )
    assert_public_json_equal(
        stop.get("budget_exhausted_dimensions"),
        snapshot["budget_exhausted_dimensions"],
        path=f"{label}/study_stop/budget_exhausted_dimensions",
    )
    assert_public_json_equal(
        stop.get("all_classes_closed"),
        bool(snapshot["stop_reasons"] and "ALL_CLASSES_CLOSED" in snapshot["stop_reasons"]),
        path=f"{label}/study_stop/all_classes_closed",
    )
    budget = require_dict(state.get("budget"), "state budget")
    ledger = list(snapshot["ledger"])
    observed_ledger = [
        require_dict(budget["attempts"], "attempt budget")["used"],
        require_dict(budget["retries"], "retry budget")["used"],
        require_dict(budget["elapsed_milliseconds"], "elapsed budget")["reserved"],
        0
        if budget.get("cost_microunits") is None
        else require_dict(budget["cost_microunits"], "cost budget")["reserved"],
    ]
    assert_public_json_equal(observed_ledger, ledger, path=f"{label}/budget/ledger")
    wrappers = require_list(state.get("class_states"), "ClassState wrappers")
    closed = {
        require_dict(require_dict(item, "ClassState wrapper")["class_state"], "ClassState body")[
            "hypothesis_class_id"
        ]
        for item in wrappers
        if require_dict(require_dict(item, "ClassState wrapper")["class_state"], "ClassState body")[
            "lifecycle"
        ]
        == "closed"
    }
    assert_public_json_equal(
        sorted(closed),
        sorted(snapshot["closed_classes"]),
        path=f"{label}/closed_hypothesis_class_ids",
    )


def repair_gate_case(case: dict[str, Any]) -> None:
    data = require_dict(case["input"], "gate input")
    history = [require_dict(event, "gate history event") for event in data["event_history"]]
    operation = data["operation"]
    request = require_dict(data["request"], "gate request")
    old_expected = require_dict(case["expected"], "gate expected")
    old_appended = old_expected.get("appended_event")
    final_history, outcome = simulate_operation(
        history,
        operation,
        request,
        include_diagnosis_delta=True,
    )
    replacements: dict[object, object] = {}
    event = outcome["event"]
    if isinstance(old_appended, Mapping) and isinstance(event, Mapping):
        replacements[old_appended["event_id"]] = event["event_id"]
        replacements[old_appended["hash"]] = event["hash"]
    elif (old_appended is None) != (event is None):
        raise AssertionError(f"{case['id']}: accepted/rejected append topology changed")
    state = canonicalize_state(
        require_dict(old_expected["final_state"], "gate final state"),
        replacements,
        events_by_id(final_history),
    )
    assert_state_projection(state, final_history, label=case["id"])
    case["expected"] = {
        "accepted": outcome["success"],
        "appended": outcome["appended"],
        "idempotent_reuse": outcome["idempotent_reuse"],
        "error_code": outcome["error_code"],
        "error_path": outcome["error_path"],
        "error_details": copy.deepcopy(outcome["error_details"]),
        "deltas": copy.deepcopy(outcome["deltas"]),
        "appended_event": copy.deepcopy(event),
        "final_log_head": final_log_head(final_history),
        "final_state": state,
        "final_state_digest": public_digest(state),
    }


def repair_race_case(case: dict[str, Any]) -> None:
    precondition = require_dict(case["precondition"], "race precondition")
    initial_history = [
        require_dict(event, "race precondition event") for event in precondition["event_history"]
    ]
    schedule = [require_dict(item, "race operation") for item in case["schedule"]]
    old_expected = require_dict(case["expected"], "race expected")
    old_operations = [require_dict(item, "old race outcome") for item in old_expected["operations"]]
    if len(old_operations) != len(schedule):
        raise AssertionError(f"{case['id']}: race schedule/outcome length mismatch")

    history = list(initial_history)
    outcomes: list[dict[str, Any]] = []
    replacements: dict[object, object] = {}
    for step, old_outcome in zip(schedule, old_operations, strict=True):
        operation = step["operation"]
        request = require_dict(step["request"], "race request")
        history, outcome = simulate_operation(
            history,
            operation,
            request,
            include_diagnosis_delta=False,
        )
        old_event = old_outcome.get("event")
        event = outcome.get("event")
        if isinstance(old_event, Mapping) and isinstance(event, Mapping):
            replacements[old_event["event_id"]] = event["event_id"]
            replacements[old_event["hash"]] = event["hash"]
        elif (old_event is None) != (event is None):
            raise AssertionError(f"{case['id']}: race append topology changed")
        outcomes.append(outcome)

    pre_state = canonicalize_state(
        require_dict(old_expected["pre_state"], "race pre-state"),
        {},
        events_by_id(initial_history),
    )
    final_state = canonicalize_state(
        require_dict(old_expected["final_state"], "race final state"),
        replacements,
        events_by_id(history),
    )
    assert_state_projection(pre_state, initial_history, label=f"{case['id']}:pre")
    assert_state_projection(final_state, history, label=f"{case['id']}:final")
    initial_snapshot = semantic_snapshot(initial_history)
    final_snapshot = semantic_snapshot(history)
    public_outcomes = [copy.deepcopy(outcome) for outcome in outcomes]
    appended_events = [
        outcome["event"] for outcome in public_outcomes if isinstance(outcome.get("event"), Mapping)
    ]
    registration_errors = [
        outcome["error_code"]
        for outcome in public_outcomes
        if outcome["operation"] in {"register_first_attempt", "register_retry"}
        and outcome["error_code"] is not None
    ]
    input_digest = kernel_digest(
        {"precondition": copy.deepcopy(precondition), "schedule": copy.deepcopy(schedule)}
    )
    error_codes = [
        outcome["error_code"] for outcome in public_outcomes if outcome["error_code"] is not None
    ]
    case["expected"] = {
        "pre_state": pre_state,
        "pre_state_digest": public_digest(pre_state),
        "pending_diagnosis_experiment_ids": list(initial_snapshot["pending"]),
        "study_stop_reasons": list(initial_snapshot["stop_reasons"]),
        "operations": public_outcomes,
        "diagnosis_successes": sum(
            outcome["operation"] == "record_diagnosis" and outcome["success"]
            for outcome in public_outcomes
        ),
        "diagnosis_events": sum(
            event["event_type"] == "research.experiment_diagnosed.v1" for event in appended_events
        ),
        "registration_events": sum(
            event["event_type"] == "EXPERIMENT_REGISTERED" for event in appended_events
        ),
        "successor_generation_events": sum(
            event["event_type"] == "research.study_generation_opened.v1"
            for event in appended_events
        ),
        "duplicate_errors": sum(
            outcome["operation"] == "record_diagnosis" and outcome["error_code"] is not None
            for outcome in public_outcomes
        ),
        "registration_error": registration_errors[0] if registration_errors else None,
        "errors": len(error_codes),
        "count_delta": len(final_snapshot["diagnoses"]) - len(initial_snapshot["diagnoses"]),
        "final_log_head": final_log_head(history),
        "final_state": final_state,
        "final_state_digest": public_digest(final_state),
        "outcome_counts": {
            "operation_rows": len(public_outcomes),
            "successes": sum(outcome["success"] for outcome in public_outcomes),
            "failures": sum(not outcome["success"] for outcome in public_outcomes),
            "appended_events": sum(outcome["appended"] for outcome in public_outcomes),
            "idempotent_reuses": sum(outcome["idempotent_reuse"] for outcome in public_outcomes),
            "error_codes": error_codes,
        },
        "observer_input_sha256": input_digest,
        "schedule_operation_count": len(schedule),
    }


def repair(matrix: dict[str, Any]) -> None:
    matrix.pop("expected", None)
    observer_contract = require_dict(matrix["observer_contract"], "observer contract")
    for key, value in list(observer_contract.items()):
        if key in OBSERVER_CONTRACT_PROOF_KEYS or not isinstance(value, (str, list)):
            observer_contract.pop(key)
    for raw_case in matrix["terminal_pending_cases"]:
        terminal_case = require_dict(raw_case, "terminal-pending row")
        terminal_expected = require_dict(terminal_case["expected"], "terminal-pending expected")
        terminal_expected.pop("exact_match", None)

    full_rows = [require_dict(row, "full-state row") for row in matrix["full_state_cases"]]
    repair_full_case(by_id(full_rows, "retry-frontier-latest-chain-full-state"))
    for identifier in LIMIT_FOUR_CASES:
        repair_full_case(by_id(full_rows, identifier), limit_four=True)
    for case in full_rows:
        normalize_full_expected(case)

    gate_rows = [require_dict(row, "gate row") for row in matrix["gate_cases"]]
    repair_gate_nine(by_id(gate_rows, "superseded-parent-attempt-not-supported"))
    repair_gate_thirty_five(
        by_id(gate_rows, "stopped-all-classes-closed-allows-required-diagnosis")
    )
    repair_expected_frontier(
        by_id(gate_rows, "budget-only-stop-allows-changed-successor"),
        ["RETRY_BUDGET_EXHAUSTED"],
    )
    repair_expected_frontier(
        by_id(gate_rows, "budget-plus-pending-stop-precedes-diagnosis-required"),
        ["BUDGET_EXHAUSTED"],
    )
    for case in gate_rows:
        repair_gate_case(case)

    for raw_case in matrix["race_schedules"]:
        repair_race_case(require_dict(raw_case, "race row"))


def iter_event_histories(matrix: Mapping[str, Any]) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    for section, root in (
        ("terminal_pending_cases", "input"),
        ("full_state_cases", "input"),
        ("gate_cases", "input"),
        ("race_schedules", "precondition"),
    ):
        for index, raw_case in enumerate(matrix[section]):
            case = require_dict(raw_case, f"{section} row")
            history = [require_dict(event, "event") for event in case[root]["event_history"]]
            yield f"/{section}/{index}/{root}/event_history", history


def verify_history(path: str, history: list[dict[str, Any]]) -> None:
    previous: str | None = None
    seen: set[str] = set()
    for sequence, event in enumerate(history, 1):
        if set(event) != EVENT_KEYS:
            raise AssertionError(f"{path}/{sequence - 1}: non-exact Event envelope")
        if event["sequence"] != sequence or event["prev_hash"] != previous:
            raise AssertionError(f"{path}/{sequence - 1}: broken Event chain")
        if event["project_id"] != PROJECT_ID or event["event_id"] in seen:
            raise AssertionError(f"{path}/{sequence - 1}: Event identity mismatch")
        if event["hash"] != event_digest(event):
            raise AssertionError(f"{path}/{sequence - 1}: Event hash mismatch")
        seen.add(event["event_id"])
        previous = event["hash"]


def verify_scientific_history(path: str, history: list[dict[str, Any]]) -> None:
    active_generation: str | None = None
    contract_digest: str | None = None
    seal_digest: str | None = None
    compatibility: str | None = None
    baselines: dict[str, tuple[str, str, str]] = {}
    registrations: dict[str, dict[str, Any]] = {}
    event_hashes = {event["event_id"]: event["hash"] for event in history}
    for index, event in enumerate(history):
        payload = require_dict(event["payload"], "event payload")
        event_type = event["event_type"]
        pointer = f"{path}/{index}/payload"
        if event_type == "research.study_generation_opened.v1":
            expected = stable_id(
                "generation",
                PROJECT_ID,
                active_generation,
                payload["study_contract_digest"],
                payload["evaluation_seal_digest"],
            )
            if payload["generation_id"] != expected:
                raise AssertionError(f"{pointer}/generation_id: non-canonical generation")
            if public_digest(payload["contract"]) != payload["study_contract_digest"]:
                raise AssertionError(f"{pointer}: contract digest mismatch")
            if public_digest(payload["evaluation_seal"]) != payload["evaluation_seal_digest"]:
                raise AssertionError(f"{pointer}: seal digest mismatch")
            active_generation = expected
            contract_digest = payload["study_contract_digest"]
            seal_digest = payload["evaluation_seal_digest"]
            compatibility = payload["evaluation_seal"]["compatibility_digest"]
            baselines = {}
            registrations = {}
        elif event_type == "BASELINE_RECORDED" and "evaluation_scope_id" in payload:
            if (
                payload["generation_id"] != active_generation
                or payload["study_contract_digest"] != contract_digest
                or payload["evaluation_seal_digest"] != seal_digest
                or payload["compatibility_digest"] != compatibility
            ):
                raise AssertionError(f"{pointer}: baseline generation/seal mismatch")
            baselines[payload["baseline_id"]] = (
                payload["generation_id"],
                payload["compatibility_digest"],
                payload["evaluation_scope_id"],
            )
        elif event_type == "EXPERIMENT_REGISTERED" and "proposal" in payload:
            proposal = require_dict(payload["proposal"], "Proposal")
            proposal_digest = public_digest(proposal)
            proposal_identifier = stable_id("proposal", PROJECT_ID, proposal_digest)
            candidate_digest = public_digest(payload["candidate"])
            if (
                payload["candidate_digest"] != candidate_digest
                or payload["proposal_digest"] != proposal_digest
                or payload["proposal_id"] != proposal_identifier
                or proposal["generation_id"] != active_generation
                or payload["generation_id"] != active_generation
                or payload["experiment_id"] != experiment_id(payload)
            ):
                raise AssertionError(f"{pointer}: registration identity mismatch")
            wanted_baseline = (
                proposal["generation_id"],
                payload["compatibility_digest"],
                proposal["evaluation_scope_id"],
            )
            if baselines.get(payload["baseline_id"]) != wanted_baseline:
                raise AssertionError(f"{pointer}/baseline_id: baseline join mismatch")
            registrations[payload["experiment_id"]] = payload
        elif event_type == "research.experiment_diagnosed.v1":
            body = require_dict(payload["diagnosis"], "Diagnosis")
            if body["failure_type"] not in ALLOWED_FAILURE_TYPES:
                raise AssertionError(f"{pointer}/diagnosis/failure_type: unsupported")
            body_digest = public_digest(body)
            diagnosis_identifier = stable_id("diagnosis", PROJECT_ID, body_digest)
            if (
                payload["diagnosis_digest"] != body_digest
                or payload["diagnosis_id"] != diagnosis_identifier
                or body["experiment_id"] not in registrations
            ):
                raise AssertionError(f"{pointer}: Diagnosis identity/binding mismatch")
            terminal = body["terminal_evidence"]
            if event_hashes.get(terminal["event_id"]) != terminal["event_hash"]:
                raise AssertionError(f"{pointer}: terminal evidence hash mismatch")


def walk(value: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, item in value.items():
            yield from walk(item, f"{path}/{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from walk(item, f"{path}/{index}")


def verify_fixture(matrix: dict[str, Any]) -> dict[str, int]:
    if set(matrix) != TRANSITION_TOP_LEVEL_KEYS:
        unexpected = sorted(set(matrix) - TRANSITION_TOP_LEVEL_KEYS)
        missing = sorted(TRANSITION_TOP_LEVEL_KEYS - set(matrix))
        raise AssertionError(
            f"transition top-level schema mismatch: unexpected={unexpected}, missing={missing}"
        )
    observer_contract = require_dict(matrix["observer_contract"], "observer contract")
    if set(observer_contract) != OBSERVER_CONTRACT_KEYS:
        unexpected = sorted(set(observer_contract) - OBSERVER_CONTRACT_KEYS)
        missing = sorted(OBSERVER_CONTRACT_KEYS - set(observer_contract))
        raise AssertionError(
            f"observer-contract schema mismatch: unexpected={unexpected}, missing={missing}"
        )
    for key, value in observer_contract.items():
        if isinstance(value, str):
            valid = bool(value)
        else:
            valid = (
                isinstance(value, list)
                and bool(value)
                and all(isinstance(item, str) and item for item in value)
            )
        if not valid:
            raise AssertionError(
                f"observer-contract {key!r} is not declarative string/list metadata"
            )

    basic_census = {
        "terminal_pending_cases": len(matrix["terminal_pending_cases"]),
        "full_state_cases": len(matrix["full_state_cases"]),
        "counting_taxonomy": len(matrix["counting_taxonomy"]),
        "gate_cases": len(matrix["gate_cases"]),
        "gate_accepted": sum(case["expected"]["accepted"] for case in matrix["gate_cases"]),
        "gate_rejected": sum(not case["expected"]["accepted"] for case in matrix["gate_cases"]),
        "race_schedules": len(matrix["race_schedules"]),
        "race_operations": sum(len(case["schedule"]) for case in matrix["race_schedules"]),
        "race_appended_events": sum(
            operation["appended"]
            for case in matrix["race_schedules"]
            for operation in case["expected"]["operations"]
        ),
    }
    for key, value in basic_census.items():
        assert_public_json_equal(value, EXPECTED_CENSUS[key], path=f"/census/{key}")

    verify_counting_and_terminal_projections(matrix)

    history_count = 0
    history_events = 0
    for path, history in iter_event_histories(matrix):
        verify_history(path, history)
        verify_scientific_history(path, history)
        history_count += 1
        history_events += len(history)

    all_events = [
        (path, value)
        for path, value in walk(matrix)
        if isinstance(value, dict) and set(value) == EVENT_KEYS
    ]
    for path, event in all_events:
        if event["hash"] != event_digest(event):
            raise AssertionError(f"{path}: standalone Event hash mismatch")

    class_states = 0
    diagnoses = 0
    for path, value in walk(matrix):
        if not isinstance(value, dict):
            continue
        if {"class_state_id", "class_state_digest", "class_state"} <= set(value):
            body = require_dict(value["class_state"], "ClassState body")
            if value["class_state_digest"] != public_digest(body):
                raise AssertionError(f"{path}: ClassState digest mismatch")
            expected_id = stable_id(
                "classstate", PROJECT_ID, body["generation_id"], body["hypothesis_class_id"]
            )
            if value["class_state_id"] != expected_id:
                raise AssertionError(f"{path}: ClassState ID mismatch")
            class_states += 1
        if {"diagnosis_id", "diagnosis_digest", "diagnosis"} <= set(value):
            body = require_dict(value["diagnosis"], "Diagnosis body")
            if body.get("failure_type") not in ALLOWED_FAILURE_TYPES:
                raise AssertionError(f"{path}: unsupported Diagnosis failure type")
            body_digest = public_digest(body)
            if value["diagnosis_digest"] != body_digest:
                raise AssertionError(f"{path}: Diagnosis digest mismatch")
            if value["diagnosis_id"] != stable_id("diagnosis", PROJECT_ID, body_digest):
                raise AssertionError(f"{path}: Diagnosis ID mismatch")
            diagnoses += 1

    state_digests = 0
    for case in matrix["full_state_cases"]:
        full_history = [
            require_dict(event, "full-state event")
            for event in require_list(case["input"]["event_history"], "full-state event history")
        ]
        full_state = require_dict(case["expected_state"], "full expected state")
        assert_state_projection(
            full_state,
            full_history,
            label=f"/full_state_cases/{case['id']}/expected_state",
        )
        assert_public_json_equal(
            case["expected"]["post_state_digest"],
            public_digest(full_state),
            path=f"/{case['id']}/expected/post_state_digest",
        )
        state_digests += 1
    for section in ("gate_cases", "race_schedules"):
        for case in matrix[section]:
            expected = case["expected"]
            for prefix in ("pre", "final"):
                state_key = f"{prefix}_state"
                digest_key = f"{prefix}_state_digest"
                if state_key in expected and digest_key in expected:
                    assert_public_json_equal(
                        expected[digest_key],
                        public_digest(expected[state_key]),
                        path=f"/{section}/{case['id']}/expected/{digest_key}",
                    )
                    state_digests += 1

    gate_rows = [require_dict(row, "gate row") for row in matrix["gate_cases"]]
    expected_blockers = {
        "budget-only-stop-allows-changed-successor": ["RETRY_BUDGET_EXHAUSTED"],
        "budget-plus-pending-stop-precedes-diagnosis-required": ["BUDGET_EXHAUSTED"],
    }
    for identifier, blockers in expected_blockers.items():
        case = by_id(gate_rows, identifier)
        observed = case["expected"]["final_state"]["retry_frontier"]["blocked_by"]
        assert_public_json_equal(
            observed,
            blockers,
            path=f"/gate_cases/{identifier}/expected/final_state/retry_frontier/blocked_by",
        )

    full_expected_keys = {
        "history_event_count",
        "operation_deltas",
        "pre_state_digest",
        "post_state_digest",
    }
    full_delta_keys = {
        "canonical_events",
        "budget_attempts",
        "budget_retries",
        "budget_elapsed_milliseconds",
        "budget_cost_microunits",
        "projection_rows",
    }
    for case in matrix["full_state_cases"]:
        expected = require_dict(case["expected"], "full-state expected")
        if set(expected) != full_expected_keys:
            raise AssertionError(f"{case['id']}: full-state expected is not exact four-key core")
        history = require_list(case["input"]["event_history"], "full-state history")
        assert_public_json_equal(
            expected["history_event_count"],
            len(history),
            path=f"/full_state_cases/{case['id']}/expected/history_event_count",
        )
        deltas = require_dict(expected["operation_deltas"], "full-state deltas")
        assert_public_json_equal(
            deltas,
            {key: 0 for key in full_delta_keys},
            path=f"/full_state_cases/{case['id']}/expected/operation_deltas",
        )
        for key in ("pre_state_digest", "post_state_digest"):
            digest = expected[key]
            if not isinstance(digest, str) or len(digest) != 64:
                raise AssertionError(f"{case['id']}: malformed {key}")

    gate_expected_keys = {
        "accepted",
        "appended",
        "idempotent_reuse",
        "error_code",
        "error_path",
        "error_details",
        "deltas",
        "appended_event",
        "final_log_head",
        "final_state",
        "final_state_digest",
    }
    unspecified_paths = 0
    explicit_paths = 0
    for case in gate_rows:
        expected = require_dict(case["expected"], "gate expected")
        if set(expected) != gate_expected_keys:
            raise AssertionError(f"{case['id']}: gate expected does not have the exact schema")
        recomputed = copy.deepcopy(case)
        repair_gate_case(recomputed)
        assert_public_json_equal(
            expected,
            recomputed["expected"],
            path=f"/gate_cases/{case['id']}/expected",
        )
        if expected["accepted"]:
            assert_public_json_equal(
                expected["error_details"],
                {},
                path=f"/gate_cases/{case['id']}/expected/error_details",
            )
            if (
                expected["appended"] is not True
                or expected["idempotent_reuse"] is not False
                or expected["error_code"] is not None
                or expected["error_path"] is not None
                or not isinstance(expected["appended_event"], Mapping)
            ):
                raise AssertionError(f"{case['id']}: malformed accepted gate outcome")
        else:
            assert_public_json_equal(
                expected["deltas"],
                {
                    "canonical_events": 0,
                    "registration_events": 0,
                    "generation_events": 0,
                    "diagnosis_events": 0,
                    "budget_attempts": 0,
                    "budget_retries": 0,
                    "budget_elapsed_milliseconds": 0,
                    "budget_cost_microunits": 0,
                    "projection_rows": 0,
                },
                path=f"/gate_cases/{case['id']}/expected/deltas",
            )
            if (
                expected["appended"] is not False
                or expected["idempotent_reuse"] is not False
                or expected["appended_event"] is not None
                or not expected["error_details"]
            ):
                raise AssertionError(f"{case['id']}: malformed rejected gate outcome")
            if expected["error_code"] == "DIAGNOSIS_ALREADY_RECORDED":
                if expected["error_path"] != "$.experiment_id":
                    raise AssertionError(f"{case['id']}: duplicate Diagnosis path mismatch")
                explicit_paths += 1
            else:
                if expected["error_code"] not in UNSPECIFIED_ERROR_PATH_CODES:
                    raise AssertionError(f"{case['id']}: unclassified error-path contract")
                if expected["error_path"] is not None or "path" in expected["error_details"]:
                    raise AssertionError(f"{case['id']}: invented unspecified error path")
                unspecified_paths += 1
    if (unspecified_paths, explicit_paths) != (29, 1):
        raise AssertionError("rejected gate error-path ambiguity census mismatch")

    race_expected_keys = {
        "pre_state",
        "pre_state_digest",
        "pending_diagnosis_experiment_ids",
        "study_stop_reasons",
        "operations",
        "diagnosis_successes",
        "diagnosis_events",
        "registration_events",
        "successor_generation_events",
        "duplicate_errors",
        "registration_error",
        "errors",
        "count_delta",
        "final_log_head",
        "final_state",
        "final_state_digest",
        "outcome_counts",
        "observer_input_sha256",
        "schedule_operation_count",
    }
    race_operation_keys = {
        "operation",
        "success",
        "appended",
        "idempotent_reuse",
        "error_code",
        "error_path",
        "error_details",
        "event",
        "deltas",
    }
    for case in matrix["race_schedules"]:
        expected = require_dict(case["expected"], "race expected")
        if set(expected) != race_expected_keys:
            raise AssertionError(f"{case['id']}: race expected does not have exact schema")
        for operation in expected["operations"]:
            if set(operation) != race_operation_keys:
                raise AssertionError(f"{case['id']}: race operation does not have exact schema")
        recomputed = copy.deepcopy(case)
        repair_race_case(recomputed)
        assert_public_json_equal(
            expected,
            recomputed["expected"],
            path=f"/race_schedules/{case['id']}/expected",
        )

    final_census = {
        **basic_census,
        "histories": history_count,
        "history_events": history_events,
        "all_event_objects": len(all_events),
        "class_states": class_states,
        "diagnosis_wrappers": diagnoses,
        "state_digests": state_digests,
    }
    for key, wanted in EXPECTED_CENSUS.items():
        assert_public_json_equal(final_census[key], wanted, path=f"/final_census/{key}")

    return final_census


def strict_load(path: Path) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                raise ValueError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    value = json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=pairs,
        parse_constant=lambda token: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON token {token}")
        ),
    )
    return require_dict(value, "transition fixture")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify without rewriting")
    args = parser.parse_args()
    matrix = strict_load(FIXTURE)
    if not args.check:
        repair(matrix)
        FIXTURE.write_text(
            json.dumps(matrix, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
            encoding="utf-8",
        )
        matrix = strict_load(FIXTURE)
    counts = verify_fixture(matrix)
    fixed_point = copy.deepcopy(matrix)
    repair(fixed_point)
    rendered = json.dumps(fixed_point, ensure_ascii=False, allow_nan=False, indent=2) + "\n"
    current_bytes = FIXTURE.read_bytes()
    if rendered.encode("utf-8") != current_bytes:
        raise AssertionError("fixture is not a byte-stable repair fixed point")
    print(
        json.dumps(
            {
                **counts,
                "deterministic_gate_appends": 7,
                "deterministic_race_appends": 9,
                "successor_reset_gate_rows": 3,
                "rejected_gate_error_metadata_rows": 30,
                "contract_unspecified_null_error_paths": 29,
                "explicit_error_paths": 1,
                "full_state_four_key_expected_rows": 54,
                "payload_digest_domain": "kernel_compact_sha256_not_public_sha256_json",
                "unresolved_ambiguity": (
                    "29 gate error paths are contract-unspecified and deliberately null"
                ),
                "repair_fixed_point": True,
                "raw_sha256": hashlib.sha256(current_bytes).hexdigest(),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
