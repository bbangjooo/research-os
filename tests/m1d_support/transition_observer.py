"""Literal transition observers for the frozen M1-D matrix.

The public functions in this module receive only a manifest input object and a
fixture loader (or fixture root).  Display identities and comparison values are
deliberately never consulted.  Every scientific-state observation starts from a
verified literal event history.
"""

from __future__ import annotations

import copy
import hashlib
import json
import tempfile
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, TypeAlias, cast

JSONValue: TypeAlias = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
FixtureSource: TypeAlias = Path | Callable[[object], object]

_DIAGNOSIS_EVENT = "research.experiment_diagnosed.v1"
_GENERATION_EVENT = "research.study_generation_opened.v1"
_REGISTRATION_EVENT = "EXPERIMENT_REGISTERED"
_TERMINAL_STATUSES = frozenset(
    {
        "ACCEPTED",
        "SUCCEEDED",
        "COMPLETED",
        "INVALID",
        "INVALID_EXPERIMENT",
        "FAILED",
        "CRASHED",
        "TIMED_OUT",
        "CANCELLED",
        "REJECTED",
        "VALIDATED",
        "INFRA_FAILED",
        "INSUFFICIENT_EVIDENCE",
        "UNTRUSTED",
    }
)
_STATUS_ALIASES = {
    "SUCCESS": "SUCCEEDED",
    "PASSED": "SUCCEEDED",
    "COMPLETE": "COMPLETED",
    "TIMEOUT": "TIMED_OUT",
    "TIMEDOUT": "TIMED_OUT",
    "CANCELED": "CANCELLED",
    "ERROR": "FAILED",
}
_DECISION_FIELDS = frozenset(
    {
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
)
_OBSERVATION_FIELDS = frozenset(
    {
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
)
_GATE_FIELDS = frozenset(
    {
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
)
_ZERO_DELTAS = {
    "canonical_events": 0,
    "registration_events": 0,
    "generation_events": 0,
    "diagnosis_events": 0,
    "budget_attempts": 0,
    "budget_retries": 0,
    "budget_elapsed_milliseconds": 0,
    "budget_cost_microunits": 0,
    "projection_rows": 0,
}
_FULL_REDUCTION_ZERO_DELTAS = {
    "canonical_events": 0,
    "budget_attempts": 0,
    "budget_retries": 0,
    "budget_elapsed_milliseconds": 0,
    "budget_cost_microunits": 0,
    "projection_rows": 0,
}
_NEGATIVE_PATH_ZERO_DELTAS = {
    "events": 0,
    "budget": 0,
    "diagnoses": 0,
    "class_state": 0,
    "frontier": 0,
    "projection_cursor": 0,
}


class DuplicateKeyError(ValueError):
    """Raised when a frozen JSON object repeats a member name."""


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def _strict_json(path: Path) -> object:
    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_nonfinite,
    )


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _array(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be non-empty text")
    return value


def _load_fixture(inputs: Mapping[str, object], source: FixtureSource) -> Mapping[str, object]:
    name = _text(inputs.get("fixture"), "fixture")
    if callable(source):
        value = source(name)
    else:
        root = Path(source).resolve()
        path = (root / name).resolve()
        if path.parent != root:
            raise AssertionError("fixture path escapes the frozen root")
        value = _strict_json(path)
    return _mapping(value, name)


def _rows(matrix: Mapping[str, object], name: str) -> list[Mapping[str, object]]:
    return [_mapping(item, f"{name} row") for item in _array(matrix.get(name), name)]


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _public_digest(value: object) -> str:
    from research_os.contracts.common import canonical_json_bytes

    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _public_json_equal(left: object, right: object) -> bool:
    """Compare values in the public canonical-JSON equality domain."""

    from research_os.contracts import canonical_json_bytes

    return canonical_json_bytes(left) == canonical_json_bytes(right)


def _canonical_status(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
    return _STATUS_ALIASES.get(normalized, normalized)


def _history_from(container: Mapping[str, object]) -> list[Mapping[str, object]]:
    return [
        _mapping(item, "event envelope")
        for item in _array(container.get("event_history"), "event_history")
    ]


def _parse_history(history: Sequence[Mapping[str, object]], project_id: str) -> tuple[Any, ...]:
    from research_os.kernel.events import Event, verify_events

    events = tuple(Event.from_mapping(item) for item in history)
    verify_events(list(events), project_id=project_id)
    for raw, event in zip(history, events, strict=True):
        unsigned = dict(raw)
        supplied = unsigned.pop("hash", None)
        if supplied != _digest(unsigned) or not _public_json_equal(event.to_dict(), raw):
            raise AssertionError("literal event envelope failed independent verification")
    return events


def _project_id(matrix: Mapping[str, object]) -> str:
    return _text(matrix.get("project_id"), "project_id")


def _reduce_history(
    history: Sequence[Mapping[str, object]], project_id: str
) -> tuple[Any, dict[str, object]]:
    from research_os.science import reduce_scientific_state

    events = _parse_history(history, project_id)
    parsed_state = reduce_scientific_state(events, project_id=project_id)
    loose_state = reduce_scientific_state(
        [event.to_dict() for event in events], project_id=project_id
    )
    parsed_dict = parsed_state.to_dict()
    if not _public_json_equal(loose_state.to_dict(), parsed_dict):
        raise AssertionError("parsed and detached literal reductions diverged")
    if _public_digest(parsed_dict) != _public_digest(copy.deepcopy(parsed_dict)):
        raise AssertionError("scientific-state digest is not deterministic")
    return parsed_state, parsed_dict


def _append_and_reduce_literal_history(
    history: Sequence[Mapping[str, object]], project_id: str
) -> tuple[Any, dict[str, object]]:
    """Commit each supplied input envelope, replay it, and reduce the replay.

    This is deliberately used for the terminal-pending corpus so a row cannot
    count as executed merely because its already-materialized state was read.
    Every input event passes through EventLog's canonical constructor and hash
    chain before scientific reduction.
    """

    from research_os.kernel.events import EventLog

    verified = _parse_history(history, project_id)
    with tempfile.TemporaryDirectory(prefix="m1d-literal-history-") as temporary:
        event_log = EventLog(Path(temporary) / "events.jsonl", project_id)
        previous_hash: str | None = None
        for ordinal, (raw, supplied) in enumerate(zip(history, verified, strict=True), 1):
            appended = event_log.append(
                supplied.event_type,
                supplied.payload,
                event_id=supplied.event_id,
                occurred_at=supplied.occurred_at,
                expected_head=(ordinal - 1, previous_hash),
            )
            if not _public_json_equal(appended.to_dict(), raw):
                raise AssertionError("literal EventLog append changed a supplied envelope")
            previous_hash = appended.hash
        replayed = [event.to_dict() for event in event_log.read()]
    if not _public_json_equal(replayed, history):
        raise AssertionError("literal EventLog replay differs from its dispatched input")
    return _reduce_history(replayed, project_id)


def _body(class_wrapper: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(class_wrapper.get("class_state"), "class_state body")


def _class_wrappers(state: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = state.get("class_states", [])
    return [_mapping(item, "class_state wrapper") for item in _array(raw, "class_states")]


def _diagnosis_wrappers(state: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = state.get("diagnoses", [])
    return [_mapping(item, "diagnosis wrapper") for item in _array(raw, "diagnoses")]


def _validate_state_identities(state: Mapping[str, object], project_id: str) -> None:
    from research_os.contracts.common import sha256_json
    from research_os.kernel.ids import stable_id

    for wrapper in _class_wrappers(state):
        body = _body(wrapper)
        if wrapper.get("class_state_digest") != _public_digest(body):
            raise AssertionError("class-state digest mismatch")
        if wrapper.get("class_state_digest") != sha256_json(body):
            raise AssertionError("independent and product class-state digests diverged")
        expected_id = stable_id(
            "classstate",
            project_id,
            body.get("generation_id"),
            body.get("hypothesis_class_id"),
        )
        if wrapper.get("class_state_id") != expected_id:
            raise AssertionError("class-state identity mismatch")


def _observation_matches(terminal: Mapping[str, object], observation: Mapping[str, object]) -> bool:
    decision = terminal.get("decision")
    if not isinstance(decision, Mapping):
        return False
    if set(decision) != _DECISION_FIELDS or set(observation) != _OBSERVATION_FIELDS:
        return False
    if decision.get("authorized_action") is not None:
        return False
    identity_pairs = {
        "terminal_status": "status",
        "reason_code": "reason_code",
        "primary_metric": "primary_metric",
    }
    result_pairs = {
        "candidate_value": "candidate_value",
        "baseline_value": "baseline_value",
        "improvement": "improvement",
        "promotion_margin": "promotion_margin",
        "gate_evaluations": "gate_evaluations",
    }
    return all(
        _public_json_equal(observation.get(left), decision.get(right))
        for left, right in identity_pairs.items()
    ) and all(
        _public_json_equal(observation.get(left), decision.get(right))
        for left, right in result_pairs.items()
    )


def _all_qualifying_gates_pass(observation: Mapping[str, object]) -> bool:
    gates = observation.get("gate_evaluations")
    if not isinstance(gates, list):
        return False
    for raw in gates:
        gate = _mapping(raw, "gate evaluation")
        if set(gate) != _GATE_FIELDS:
            return False
        if gate.get("role") in {"hard", "support"} and gate.get("passed") is not True:
            return False
    return True


def _counting_attempt_qualifies(
    root: Mapping[str, object],
    attempt: Mapping[str, object],
) -> str | None:
    registration = _mapping(attempt.get("registration"), "registration")
    terminal = _mapping(attempt.get("terminal"), "terminal")
    diagnosis = _mapping(attempt.get("diagnosis"), "diagnosis")
    observation = _mapping(diagnosis.get("observation"), "diagnosis observation")
    persisted = _mapping(root.get("persisted_proposal"), "persisted_proposal")
    proposal = _mapping(persisted.get("proposal"), "persisted Proposal")
    persisted_scope = _mapping(root.get("persisted_evaluation_scope"), "evaluation scope")

    proposal_id = persisted.get("proposal_id")
    proposal_digest = persisted.get("proposal_digest")
    if not isinstance(proposal_id, str) or not isinstance(proposal_digest, str):
        return None
    if root.get("active_study_contract_schema_version") != 2:
        return None
    if not _public_json_equal(registration.get("generation_id"), root.get("active_generation_id")):
        return None
    if not _public_json_equal(
        registration.get("compatibility_digest"), root.get("active_compatibility_digest")
    ):
        return None
    if persisted_scope.get("role") not in {"development", "diagnostic"}:
        return None
    if not _public_json_equal(registration.get("evaluation_scope_id"), persisted_scope.get("id")):
        return None
    if not _public_json_equal(proposal.get("evaluation_scope_id"), persisted_scope.get("id")):
        return None
    if not _public_json_equal(registration.get("proposal_id"), proposal_id):
        return None
    if not _public_json_equal(registration.get("proposal_digest"), proposal_digest):
        return None
    if not _public_json_equal(registration.get("proposal"), proposal):
        return None

    from research_os.science import Proposal

    parsed = Proposal.from_mapping(proposal)
    if parsed.digest != proposal_digest:
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
    if not _observation_matches(terminal, observation):
        return None
    if observation.get("verified") is not True or observation.get("retryable") is not False:
        return None
    margin = observation.get("promotion_margin")
    if isinstance(margin, bool) or not isinstance(margin, (int, float)) or margin > 0:
        return None
    if not _all_qualifying_gates_pass(observation):
        return None
    return proposal_id


def _counting_result(row: Mapping[str, object]) -> tuple[set[str], str | None]:
    if "attempts" in row:
        proposal_ids: set[str] = set()
        for raw in _array(row.get("attempts"), "attempts"):
            proposal_id = _counting_attempt_qualifies(root=row, attempt=_mapping(raw, "attempt"))
            if proposal_id is not None:
                proposal_ids.add(proposal_id)
        return proposal_ids, None
    if "registration" in row:
        proposal_id = _counting_attempt_qualifies(root=row, attempt=row)
        return ({proposal_id} if proposal_id is not None else set()), None
    stop_reason = "UNTRUSTED" if _canonical_status(row.get("status")) == "UNTRUSTED" else None
    return set(), stop_reason


def observe_counting_taxonomy_rows(
    inputs: Mapping[str, object], source: FixtureSource
) -> list[dict[str, object]]:
    """Return every independently classified counting row for outer comparison."""

    matrix = _load_fixture(inputs, source)
    observations: list[dict[str, object]] = []
    for ordinal, row in enumerate(_rows(matrix, "counting_taxonomy")):
        data = _mapping(row.get("input"), "counting input")
        proposal_ids, stop_reason = _counting_result(data)
        ordered_ids = sorted(proposal_ids)
        if "attempts" in data:
            observation: dict[str, object] = {
                "count_delta": len(ordered_ids),
                "counted_proposal_ids": ordered_ids,
                "maximum_count_per_proposal_chain": int(bool(ordered_ids)),
            }
        elif "registration" in data:
            observation = {"count_delta": len(ordered_ids)}
            if len(ordered_ids) == 1:
                observation["counted_proposal_id"] = ordered_ids[0]
        elif stop_reason is not None:
            observation = {
                "count_delta": 0,
                "study_stop_reason": stop_reason,
            }
        else:
            observation = {"count_delta": 0}
        observations.append(
            {
                "ordinal": ordinal,
                "input_sha256": _digest(data),
                "observation": observation,
            }
        )
    return observations


def execute_counting_taxonomy(
    inputs: Mapping[str, object], source: FixtureSource
) -> dict[str, object]:
    """Recompute the conclusive-rejection counting taxonomy from literal joins."""

    matrix = _load_fixture(inputs, source)
    rows = _rows(matrix, "counting_taxonomy")
    results = [_counting_result(_mapping(row.get("input"), "counting input")) for row in rows]
    positives = [index for index, (ids, _) in enumerate(results) if ids]
    counted_ids = Counter(identifier for ids, _ in results for identifier in ids)

    boundary_rows = 0
    margin_zero = 0
    nonempty_passed = 0
    diagnostic_counts = False
    agent_control_counts = False
    top_level_null_counts = False
    hard_constraint_counts = False
    for row, (identifiers, _) in zip(rows, results, strict=True):
        data = _mapping(row.get("input"), "counting input")
        if "active_generation_id" not in data:
            boundary_rows += 1
        terminal = data.get("terminal")
        if isinstance(terminal, Mapping):
            decision = terminal.get("decision")
            if isinstance(decision, Mapping):
                margin = decision.get("promotion_margin")
                gates = decision.get("gate_evaluations")
                if identifiers and margin == 0:
                    margin_zero += 1
                    boundary_rows += 1
                if identifiers and isinstance(gates, list) and gates:
                    nonempty_passed += 1
                    boundary_rows += 1
            if identifiers and "error" in terminal and terminal.get("error") is None:
                top_level_null_counts = True
        scope = data.get("persisted_evaluation_scope")
        if identifiers and isinstance(scope, Mapping) and scope.get("role") == "diagnostic":
            diagnostic_counts = True
        registration = data.get("registration")
        if (
            identifiers
            and isinstance(registration, Mapping)
            and "non_authoritative_control_claim" in registration
        ):
            agent_control_counts = True
        if identifiers and data.get("reason_code") == "HARD_CONSTRAINT_FAILED":
            hard_constraint_counts = True

    return {
        "cases": len(rows),
        "executed_rows": len(results),
        "positive_rows": len(positives),
        "zero_rows": len(rows) - len(positives),
        "added_boundary_rows": boundary_rows,
        "margin_zero_positive_rows": margin_zero,
        "nonempty_all_passed_gate_positive_rows": nonempty_passed,
        "diagnostic_scope_counts": diagnostic_counts,
        "agent_control_label_counts": agent_control_counts,
        "top_level_error_null_counts": top_level_null_counts,
        "hard_constraint_counts": hard_constraint_counts,
        "maximum_count_per_proposal_chain": max(counted_ids.values(), default=0),
    }


def _is_generic_terminal(event: Mapping[str, object]) -> bool:
    return (
        event.get("event_type") == "EXPERIMENT_STATUS_CHANGED"
        and _canonical_status(_mapping(event.get("payload"), "status payload").get("status"))
        in _TERMINAL_STATUSES
    )


def _is_diagnosis_event(event: Mapping[str, object]) -> bool:
    return event.get("event_type") == _DIAGNOSIS_EVENT


def _final_log_head(history: Sequence[Mapping[str, object]]) -> dict[str, object]:
    if not history:
        return {"sequence": 0, "event_id": None, "event_hash": None}
    head = history[-1]
    return {
        "sequence": head.get("sequence"),
        "event_id": head.get("event_id"),
        "event_hash": head.get("hash"),
    }


def observe_terminal_pending_rows(
    inputs: Mapping[str, object], source: FixtureSource
) -> list[dict[str, object]]:
    """Execute all terminal-pending rows without consulting row comparisons."""

    matrix = _load_fixture(inputs, source)
    project_id = _project_id(matrix)
    observations: list[dict[str, object]] = []
    for ordinal, row in enumerate(_rows(matrix, "terminal_pending_cases")):
        operation = _text(row.get("operation"), "terminal-pending operation")
        if operation not in {"reduce_terminal_pending", "observe_terminal_pending"}:
            raise AssertionError("terminal-pending row declares an unknown operation")
        data = _mapping(row.get("input"), "terminal-pending input")
        if set(data) != {"event_history"}:
            raise AssertionError("terminal-pending observer input is not literal-only")
        history = _history_from(data)
        _, state = _append_and_reduce_literal_history(history, project_id)
        terminal_event = next(
            (
                event
                for event in reversed(history)
                if event.get("event_type") in {"EXPERIMENT_TERMINATED", "EXPERIMENT_STATUS_CHANGED"}
            ),
            None,
        )
        if terminal_event is None:
            raise AssertionError("terminal-pending history omitted its observed status event")
        payload = _mapping(terminal_event.get("payload"), "terminal payload")
        raw_status = _text(payload.get("status"), "terminal status")
        terminal_status = _canonical_status(raw_status)
        decision = payload.get("decision")
        decision_body = decision if isinstance(decision, Mapping) else {}
        reason_code = decision_body.get("reason_code", payload.get("reason_code"))
        if reason_code is None and terminal_event.get("event_type") == "EXPERIMENT_STATUS_CHANGED":
            reason_code = "STATUS_CHANGED"
        primary_metric = decision_body.get("primary_metric", payload.get("primary_metric"))
        gate_evaluations = decision_body.get("gate_evaluations", [])
        if not isinstance(gate_evaluations, list):
            raise AssertionError("terminal gate evaluations are not an array")
        numeric_values = [
            decision_body.get(name)
            for name in (
                "candidate_value",
                "baseline_value",
                "improvement",
                "promotion_margin",
            )
        ]
        pending = list(
            _array(
                state.get("pending_diagnosis_experiment_ids"),
                "pending diagnosis experiment IDs",
            )
        )
        experiment_id = payload.get("experiment_id")
        observation: dict[str, object] = {
            "terminal_status": terminal_status,
            "pending_diagnosis_experiment_ids": pending,
            "pending_count": len(pending),
        }
        if operation == "observe_terminal_pending":
            observation = {
                "raw_terminal_status": raw_status,
                "terminal_status": terminal_status,
                "reason_code": reason_code,
                "verified": payload.get("verified") is True,
                "primary_metric": primary_metric,
                "numeric_fields_null": all(value is None for value in numeric_values),
                "gate_evaluations": copy.deepcopy(gate_evaluations),
                "diagnosis_required": experiment_id in pending,
                "pending_diagnosis_experiment_ids": pending,
                "pending_count": len(pending),
                "normalization_applied": raw_status != terminal_status,
            }
        observations.append(
            {
                "ordinal": ordinal,
                "input_sha256": _digest(data),
                "observation": observation,
            }
        )
    return observations


def _state_rows(
    matrix: Mapping[str, object],
) -> list[tuple[list[Mapping[str, object]], dict[str, object]]]:
    project_id = _project_id(matrix)
    observed: list[tuple[list[Mapping[str, object]], dict[str, object]]] = []
    for row in _rows(matrix, "full_state_cases"):
        if row.get("operation") not in {
            "reduce_full_history",
            "reduce_scientific_state",
        }:
            raise AssertionError("full-state row declares an unknown operation")
        payload = _mapping(row.get("input"), "full-state input")
        if set(payload) != {"event_history"}:
            raise AssertionError("full-state observer input is not literal-only")
        history = _history_from(payload)
        _, state = _reduce_history(history, project_id)
        observed.append((history, state))
    return observed


def observe_full_state_rows(
    inputs: Mapping[str, object], source: FixtureSource
) -> list[dict[str, object]]:
    """Return every independently reduced full state keyed by input digest."""

    matrix = _load_fixture(inputs, source)
    project_id = _project_id(matrix)
    observations: list[dict[str, object]] = []
    for ordinal, row in enumerate(_rows(matrix, "full_state_cases")):
        operation = _text(row.get("operation"), "full-state operation")
        if operation not in {"reduce_full_history", "reduce_scientific_state"}:
            raise AssertionError("full-state row declares an unknown operation")
        data = _mapping(row.get("input"), "full-state input")
        if set(data) != {"event_history"}:
            raise AssertionError("full-state observer input is not literal-only")
        history = _history_from(data)
        _, state = _reduce_history(history, project_id)
        _, pre_state = _reduce_history([], project_id)
        _validate_state_identities(state, project_id)
        observations.append(
            {
                "ordinal": ordinal,
                "input_sha256": _digest(data),
                "state": state,
                "history_event_count": len(history),
                "operation_deltas": dict(_FULL_REDUCTION_ZERO_DELTAS),
                "pre_state_digest": _public_digest(pre_state),
                "post_state_digest": _public_digest(state),
            }
        )
    return observations


def _class_bodies(state: Mapping[str, object]) -> list[Mapping[str, object]]:
    return [_body(wrapper) for wrapper in _class_wrappers(state)]


def _supporting_diagnosis_ids(state: Mapping[str, object]) -> set[object]:
    identifiers: set[object] = set()
    for body in _class_bodies(state):
        identifiers.update(_array(body.get("provisional_diagnosis_ids"), "provisional IDs"))
        identifiers.update(_array(body.get("replicated_diagnosis_ids"), "replicated IDs"))
    return identifiers


def _diagnosis_body(wrapper: Mapping[str, object]) -> Mapping[str, object]:
    return _mapping(wrapper.get("diagnosis"), "diagnosis body")


def _nonempty_passing_supported(state: Mapping[str, object]) -> bool:
    supporting = _supporting_diagnosis_ids(state)
    for wrapper in _diagnosis_wrappers(state):
        if wrapper.get("diagnosis_id") not in supporting:
            continue
        diagnosis = _diagnosis_body(wrapper)
        observation = _mapping(diagnosis.get("observation"), "diagnosis observation")
        gates = observation.get("gate_evaluations")
        if isinstance(gates, list) and gates and _all_qualifying_gates_pass(observation):
            return True
    return False


def _has_post_close_support(state: Mapping[str, object]) -> bool:
    wrappers = _diagnosis_wrappers(state)
    sequences = {wrapper.get("diagnosis_id"): wrapper.get("event_sequence") for wrapper in wrappers}
    for body in _class_bodies(state):
        if body.get("lifecycle") != "closed":
            continue
        closure = body.get("closure_evidence")
        closure_id = closure.get("diagnosis_id") if isinstance(closure, Mapping) else None
        closure_sequence = sequences.get(closure_id)
        if not isinstance(closure_sequence, int):
            continue
        supporting = [
            *_array(body.get("provisional_diagnosis_ids"), "provisional IDs"),
            *_array(body.get("replicated_diagnosis_ids"), "replicated IDs"),
        ]
        if any(
            isinstance(sequences.get(identifier), int)
            and cast(int, sequences[identifier]) > closure_sequence
            for identifier in supporting
        ):
            return True
    return False


def reduce_literal_full_states(
    inputs: Mapping[str, object], source: FixtureSource
) -> dict[str, object]:
    """Reduce every literal full history and summarize boundary coverage."""

    matrix = _load_fixture(inputs, source)
    rows = _state_rows(matrix)
    states = [state for _, state in rows]
    for state in states:
        _validate_state_identities(state, _project_id(matrix))
    key_counts = {len(state) for state in states}
    if len(key_counts) != 1:
        raise AssertionError("full scientific-state key sets are inconsistent")

    generic_cases = 0
    generic_terminal_observations = 0
    minimal_pending = 0
    minimal_diagnosed = 0
    nonterminal_controls = 0
    for history, state in rows:
        generic = [
            event for event in history if event.get("event_type") == "EXPERIMENT_STATUS_CHANGED"
        ]
        generic_cases += int(bool(generic))
        terminal_generic = [event for event in generic if _is_generic_terminal(event)]
        diagnoses = [event for event in history if _is_diagnosis_event(event)]
        generic_terminal_observations += int(bool(terminal_generic) and not diagnoses)
        if len(history) == 5 and terminal_generic and not diagnoses:
            minimal_pending += 1
        if len(history) == 6 and terminal_generic and diagnoses:
            minimal_diagnosed += 1
        if generic and not terminal_generic and not state.get("pending_diagnosis_experiment_ids"):
            nonterminal_controls += 1

    limit_four = 0
    replicated_persistence = 0
    for _, state in rows:
        class_bodies = _class_bodies(state)
        contract = state.get("contract")
        if isinstance(contract, Mapping):
            classes = _array(contract.get("hypothesis_classes"), "hypothesis classes")
            limit_four += int(
                any(
                    isinstance(item, Mapping) and item.get("conclusive_rejection_limit") == 4
                    for item in classes
                )
            )
        for body in class_bodies:
            if body.get("support") == "replicated":
                later = len(_array(body.get("conclusive_diagnosis_ids"), "conclusive IDs")) + len(
                    _array(body.get("inconclusive_diagnosis_ids"), "inconclusive IDs")
                )
                replicated_persistence += int(later > 0)

    expansions = {"$ref", "extends", "template", "scenario"}
    expansion_rows = sum(
        bool(expansions.intersection(_mapping(row.get("input"), "full-state input")))
        for row in _rows(matrix, "full_state_cases")
    )
    return {
        "cases": len(rows),
        "event_envelopes": sum(len(history) for history, _ in rows),
        "reduced_state_rows": len(states),
        "state_key_count": key_counts.pop(),
        "generic_status_changed_cases": generic_cases,
        "generic_terminal_observation_cases": generic_terminal_observations,
        "generic_minimal_pending_cases": minimal_pending,
        "generic_minimal_diagnosed_cases": minimal_diagnosed,
        "generic_nonterminal_controls": nonterminal_controls,
        "post_close_positive_diagnosis_cases": sum(
            _has_post_close_support(state) for state in states
        ),
        "nonempty_all_passed_supported_cases": sum(
            _nonempty_passing_supported(state) for state in states
        ),
        "class_limit_four_boundary_cases": limit_four,
        "replicated_support_persistence_cases": replicated_persistence,
        "scenario_inputs": expansion_rows,
    }


def _event_time_after(history: Sequence[Mapping[str, object]]) -> str:
    if not history:
        instant = datetime(2000, 1, 1, tzinfo=timezone.utc)
    else:
        value = _text(history[-1].get("occurred_at"), "occurred_at")
        instant = datetime.fromisoformat(
            value.replace("Z", "+00:00").replace("z", "+00:00")
        ).astimezone(timezone.utc)
    return (instant + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _new_event(
    history: Sequence[Mapping[str, object]],
    *,
    project_id: str,
    event_type: str,
    payload: Mapping[str, object],
) -> dict[str, object]:
    """Append through EventLog with input-derived deterministic entropy/clock.

    Frozen comparison values are intentionally unavailable here.  Identity and
    time depend only on the verified prefix, event type, canonical payload, and
    append ordinal.  EventLog itself derives sequence, previous hash, and event
    hash while holding its append lock; replay then proves the committed
    envelope is canonical.
    """

    from research_os.kernel._canonical import canonical_bytes, sha256_hex
    from research_os.kernel.ids import stable_id

    sequence = len(history) + 1
    previous_value = None if not history else history[-1].get("hash")
    previous_hash = cast(str | None, previous_value)
    payload_digest = sha256_hex(canonical_bytes(payload))
    event_id = stable_id(
        "event",
        project_id,
        sequence,
        previous_hash,
        event_type,
        payload_digest,
    )
    occurred_at = _event_time_after(history)
    with tempfile.TemporaryDirectory(prefix="m1d-observed-append-") as temporary:
        event_log = _literal_event_log(
            Path(temporary) / "events.jsonl",
            history,
            project_id,
        )
        appended = event_log.append(
            event_type,
            payload,
            event_id=event_id,
            occurred_at=occurred_at,
            expected_head=((sequence - 1, previous_hash) if history else (0, None)),
        )
        replayed = event_log.read()
        if len(replayed) != sequence or not _public_json_equal(
            replayed[-1].to_dict(), appended.to_dict()
        ):
            raise AssertionError("deterministic EventLog append did not replay exactly")
    return cast(dict[str, object], appended.to_dict())


def _state_ledger(state: Any) -> tuple[int, int, int, int]:
    cost = state.cost_reserved_microunits
    return (
        state.attempts_used,
        state.retries_used,
        state.elapsed_reserved_milliseconds,
        0 if cost is None else cost,
    )


def _operation_deltas(
    before: Any,
    after: Any,
    *,
    appended: int,
    event_type: str | None,
) -> dict[str, int]:
    before_ledger = _state_ledger(before)
    after_ledger = _state_ledger(after)
    return {
        "canonical_events": appended,
        "registration_events": int(appended == 1 and event_type == _REGISTRATION_EVENT),
        "generation_events": int(appended == 1 and event_type == _GENERATION_EVENT),
        "diagnosis_events": int(appended == 1 and event_type == _DIAGNOSIS_EVENT),
        "budget_attempts": after_ledger[0] - before_ledger[0],
        "budget_retries": after_ledger[1] - before_ledger[1],
        "budget_elapsed_milliseconds": after_ledger[2] - before_ledger[2],
        "budget_cost_microunits": after_ledger[3] - before_ledger[3],
        "projection_rows": 0,
    }


def _error_code(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if not isinstance(code, str) or not code:
        raise exc
    return code


def _execute_operation(
    history: Sequence[Mapping[str, object]],
    operation: str,
    request: Mapping[str, object],
    project_id: str,
) -> tuple[list[Mapping[str, object]], dict[str, object]]:
    """Execute one pure transition and synthesize its canonical envelope."""

    from research_os.errors import ScientificStateError
    from research_os.science import (
        Diagnosis,
        EvaluationSeal,
        StudyContract,
        plan_diagnosis_append,
        plan_generation_open,
        reduce_scientific_state,
        reserve_registration,
    )

    events = _parse_history(history, project_id)
    before = reduce_scientific_state(events, project_id=project_id)
    event_type: str | None = None
    payload: Mapping[str, object] | None = None
    appended = 0
    idempotent_reuse = False
    try:
        if operation in {"register_first_attempt", "register_retry"}:
            after_plan = reserve_registration(before, request)
            event_type = _REGISTRATION_EVENT
            payload = request
        elif operation == "record_diagnosis":
            diagnosis = Diagnosis.from_mapping(
                _mapping(request.get("diagnosis"), "diagnosis request body")
            )
            plan = plan_diagnosis_append(
                events,
                project_id=project_id,
                diagnosis=diagnosis,
            )
            if not _public_json_equal(plan.payload, request):
                raise ScientificStateError(
                    "DIAGNOSIS_BINDING_MISMATCH",
                    "literal Diagnosis request differs from its canonical plan",
                )
            if not plan.append_required:
                idempotent_reuse = True
                after_plan = before
            else:
                event_type = plan.event_type
                payload = plan.payload
        elif operation == "open_successor_generation":
            contract = StudyContract.from_mapping(
                _mapping(request.get("contract"), "successor contract")
            )
            seal = EvaluationSeal.from_mapping(
                _mapping(request.get("evaluation_seal"), "successor evaluation seal")
            )
            plan = plan_generation_open(
                events,
                project_id=project_id,
                contract=contract,
                evaluation_seal=seal,
                predecessor_generation_id=cast(
                    str | None, request.get("predecessor_generation_id")
                ),
                change_reason=cast(str | None, request.get("change_reason")),
            )
            if not _public_json_equal(plan.payload, request):
                raise ScientificStateError(
                    "STUDY_GENERATION_INVALID",
                    "literal successor request differs from its canonical plan",
                )
            if not plan.append_required:
                after_plan = before
                idempotent_reuse = True
            else:
                event_type = plan.event_type
                payload = plan.payload
        else:
            raise AssertionError(f"unknown literal transition operation: {operation}")
    except ScientificStateError as exc:
        details = copy.deepcopy(dict(exc.details)) if isinstance(exc.details, Mapping) else {}
        outcome = {
            "operation": operation,
            "success": False,
            "appended": False,
            "idempotent_reuse": False,
            "error_code": exc.code,
            "error_path": details.get("path"),
            "error_details": details,
            "event": None,
            "deltas": dict(_ZERO_DELTAS),
            "state": before.to_dict(),
            "state_digest": _public_digest(before.to_dict()),
        }
        return list(history), outcome

    final_history = list(history)
    event: dict[str, object] | None = None
    if payload is not None and event_type is not None:
        event = _new_event(
            final_history,
            project_id=project_id,
            event_type=event_type,
            payload=payload,
        )
        final_history.append(event)
        appended = 1
        after, final_state = _reduce_history(final_history, project_id)
        if operation in {"register_first_attempt", "register_retry"}:
            if not _public_json_equal(after.to_dict(), after_plan.to_dict()):
                raise AssertionError("reserved and replayed registration states diverged")
    else:
        after = after_plan
        final_state = after.to_dict()
    deltas = _operation_deltas(
        before,
        after,
        appended=appended,
        event_type=event_type,
    )
    outcome = {
        "operation": operation,
        "success": True,
        "appended": appended == 1,
        "idempotent_reuse": idempotent_reuse,
        "error_code": None,
        "error_path": None,
        "error_details": {},
        "event": event,
        "deltas": deltas,
        "state": final_state,
        "state_digest": _public_digest(final_state),
    }
    return final_history, outcome


def _gate_rows(
    matrix: Mapping[str, object],
) -> list[tuple[Mapping[str, object], list[Mapping[str, object]], dict[str, object]]]:
    project_id = _project_id(matrix)
    observed: list[tuple[Mapping[str, object], list[Mapping[str, object]], dict[str, object]]] = []
    for row in _rows(matrix, "gate_cases"):
        data = _mapping(row.get("input"), "gate input")
        if set(data) != {"event_history", "operation", "request"}:
            raise AssertionError("gate observer input is not literal-only")
        history = _history_from(data)
        operation = _text(data.get("operation"), "gate operation")
        request = _mapping(data.get("request"), "gate request")
        final_history, outcome = _execute_operation(
            history,
            operation,
            request,
            project_id,
        )
        if not outcome["success"] and not _public_json_equal(final_history, history):
            raise AssertionError("rejected transition changed canonical history")
        state = _mapping(outcome.get("state"), "final state")
        if _public_digest(state) != outcome.get("state_digest"):
            raise AssertionError("transition state digest mismatch")
        observed.append((data, final_history, outcome))
    return observed


def observe_transition_gate_rows(
    inputs: Mapping[str, object], source: FixtureSource
) -> list[dict[str, object]]:
    """Return exact gate outcomes keyed only by ordinal and literal-input hash."""

    matrix = _load_fixture(inputs, source)
    observations: list[dict[str, object]] = []
    for ordinal, (data, history, outcome) in enumerate(_gate_rows(matrix)):
        event = outcome.get("event")
        if event is not None:
            appended = _mapping(event, "appended event")
            unsigned = dict(appended)
            supplied_hash = unsigned.pop("hash", None)
            if supplied_hash != _digest(unsigned):
                raise AssertionError("observed appended event hash is not canonical")
            if not _public_json_equal(appended.get("payload"), data.get("request")):
                raise AssertionError("observed appended payload differs from dispatched request")
        observations.append(
            {
                "ordinal": ordinal,
                "input_sha256": _digest(data),
                "accepted": outcome.get("success"),
                "appended": outcome.get("appended"),
                "idempotent_reuse": outcome.get("idempotent_reuse"),
                "error_code": outcome.get("error_code"),
                "error_path": outcome.get("error_path"),
                "error_details": copy.deepcopy(outcome.get("error_details")),
                "deltas": copy.deepcopy(outcome.get("deltas")),
                "appended_event": copy.deepcopy(event),
                "final_log_head": _final_log_head(history),
                "final_state": copy.deepcopy(outcome.get("state")),
                "final_state_digest": outcome.get("state_digest"),
            }
        )
    return observations


def execute_all_transition_gates(
    inputs: Mapping[str, object], source: FixtureSource
) -> dict[str, object]:
    """Execute every literal pending, stop, class, parent, and race gate."""

    matrix = _load_fixture(inputs, source)
    rows = _gate_rows(matrix)
    histogram = Counter(
        "ACCEPT" if outcome["success"] else outcome["error_code"] for _, _, outcome in rows
    )
    rejections = [outcome for _, _, outcome in rows if not outcome["success"]]
    return {
        "cases": len(rows),
        "accepted": histogram["ACCEPT"],
        "rejected": len(rows) - histogram["ACCEPT"],
        "final_state_observations": len(rows),
        "verified_final_state_digests": sum(
            _public_digest(_mapping(outcome.get("state"), "final state"))
            == outcome.get("state_digest")
            for _, _, outcome in rows
        ),
        "final_log_head_observations": len(rows),
        "zero_write_rejections": sum(
            _public_json_equal(outcome["deltas"], _ZERO_DELTAS) for outcome in rejections
        ),
        "history_event_envelopes": sum(len(_history_from(data)) for data, _, _ in rows),
        "appended_event_envelopes": sum(
            cast(Mapping[str, int], outcome["deltas"])["canonical_events"] for _, _, outcome in rows
        ),
        "prederived_predicate_inputs": sum(
            bool(
                {
                    "pre_state",
                    "pre_state_digest",
                    "pending_diagnosis_experiment_ids",
                    "study_stop_reasons",
                    "hypothesis_class_closed",
                    "parent_supported",
                    "active_nonterminal_experiment_ids",
                    "budget_remaining",
                }.intersection(data)
            )
            for data, _, _ in rows
        ),
        "error_histogram": dict(sorted(histogram.items())),
    }


def _pre_state(data: Mapping[str, object], project_id: str) -> tuple[Any, Mapping[str, object]]:
    state, serialized = _reduce_history(_history_from(data), project_id)
    return state, serialized


def verify_stop_reason_and_precedence_matrix(
    inputs: Mapping[str, object], source: FixtureSource
) -> dict[str, object]:
    """Recompute stop reasons and their transition precedence."""

    matrix = _load_fixture(inputs, source)
    project_id = _project_id(matrix)
    rows = _gate_rows(matrix)
    observations: list[tuple[Mapping[str, object], Mapping[str, object], dict[str, object]]] = []
    for data, _, outcome in rows:
        _, state = _pre_state(data, project_id)
        observations.append((data, state, outcome))

    def reasons(state: Mapping[str, object]) -> set[object]:
        stop = _mapping(state.get("study_stop"), "study_stop")
        return set(_array(stop.get("reasons"), "stop reasons"))

    stopped_diagnoses = [
        (state, outcome)
        for data, state, outcome in observations
        if data.get("operation") == "record_diagnosis" and reasons(state) and outcome["success"]
    ]
    return {
        "study_stopped": sum(
            outcome["error_code"] == "STUDY_STOPPED" for _, _, outcome in observations
        ),
        "hypothesis_class_closed": sum(
            outcome["error_code"] == "HYPOTHESIS_CLASS_CLOSED" for _, _, outcome in observations
        ),
        "diagnosis_required": sum(
            outcome["error_code"] == "DIAGNOSIS_REQUIRED" for _, _, outcome in observations
        ),
        "budget_only_registration_stops": sum(
            data.get("operation") in {"register_first_attempt", "register_retry"}
            and reasons(state) == {"BUDGET_EXHAUSTED"}
            and not state.get("pending_diagnosis_experiment_ids")
            and outcome["error_code"] == "STUDY_STOPPED"
            for data, state, outcome in observations
        ),
        "budget_plus_pending_priority": sum(
            "BUDGET_EXHAUSTED" in reasons(state)
            and bool(state.get("pending_diagnosis_experiment_ids"))
            and data.get("operation") in {"register_first_attempt", "register_retry"}
            and outcome["error_code"] == "STUDY_STOPPED"
            for data, state, outcome in observations
        ),
        "all_classes_closed_retry_stops": sum(
            data.get("operation") == "register_retry"
            and reasons(state) == {"ALL_CLASSES_CLOSED"}
            and outcome["error_code"] == "STUDY_STOPPED"
            for data, state, outcome in observations
        ),
        "stopped_diagnoses_accepted": len(stopped_diagnoses),
        "stopped_untrusted_diagnoses_accepted": sum(
            "UNTRUSTED" in reasons(state) for state, _ in stopped_diagnoses
        ),
        "stopped_budget_diagnoses_accepted": sum(
            "BUDGET_EXHAUSTED" in reasons(state) for state, _ in stopped_diagnoses
        ),
        "stopped_all_classes_diagnoses_accepted": sum(
            "ALL_CLASSES_CLOSED" in reasons(state) for state, _ in stopped_diagnoses
        ),
        "stopped_pending_active_successor_diagnosis_priority": sum(
            data.get("operation") == "open_successor_generation"
            and bool(reasons(state))
            and bool(state.get("pending_diagnosis_experiment_ids"))
            and outcome["error_code"] == "DIAGNOSIS_REQUIRED"
            for data, state, outcome in observations
        ),
        "rejection_deltas_nonzero": sum(
            not outcome["success"] and not _public_json_equal(outcome["deltas"], _ZERO_DELTAS)
            for _, _, outcome in observations
        ),
    }


def verify_successor_generation_matrix(
    inputs: Mapping[str, object], source: FixtureSource
) -> dict[str, object]:
    """Execute and summarize only genuine successor-generation requests."""

    matrix = _load_fixture(inputs, source)
    rows = [
        (data, history, outcome)
        for data, history, outcome in _gate_rows(matrix)
        if data.get("operation") == "open_successor_generation"
    ]
    accepted = [outcome for _, _, outcome in rows if outcome["success"]]
    reset = True
    for outcome in accepted:
        state = _mapping(outcome.get("state"), "successor state")
        budget = _mapping(state.get("budget"), "successor budget")
        attempts = _mapping(budget.get("attempts"), "attempt budget")
        retries = _mapping(budget.get("retries"), "retry budget")
        reset = reset and _public_json_equal(attempts.get("used"), 0)
        reset = reset and _public_json_equal(retries.get("used"), 0)
        reset = reset and _public_json_equal(state.get("diagnosis_count"), 0)
        reset = reset and _public_json_equal(state.get("pending_diagnosis_experiment_ids"), [])
    return {
        "cases": len(rows),
        "accepted": len(accepted),
        "diagnosis_required": sum(
            outcome["error_code"] == "DIAGNOSIS_REQUIRED" for _, _, outcome in rows
        ),
        "study_active_experiments": sum(
            outcome["error_code"] == "STUDY_ACTIVE_EXPERIMENTS" for _, _, outcome in rows
        ),
        "final_state_observations": len(rows),
        "new_generation_resets_active_state": reset,
    }


def execute_replication_parent_gate_matrix(
    inputs: Mapping[str, object], source: FixtureSource
) -> dict[str, object]:
    """Execute every literal replication-parent gate without display dispatch."""

    matrix = _load_fixture(inputs, source)
    rows = []
    for data, history, outcome in _gate_rows(matrix):
        request = _mapping(data.get("request"), "gate request")
        proposal = request.get("proposal")
        if isinstance(proposal, Mapping) and proposal.get("action") == "replicate":
            rows.append((data, history, outcome))
    unreachable = [
        _mapping(item, "unreachable axis")
        for item in _array(
            matrix.get("canonical_history_unreachable_axes"),
            "canonical_history_unreachable_axes",
        )
    ]
    return {
        "cases": len(rows),
        "accepted": sum(outcome["success"] for _, _, outcome in rows),
        "rejected": sum(not outcome["success"] for _, _, outcome in rows),
        "semantic_not_supported": sum(
            outcome["error_code"] == "PROPOSAL_PARENT_NOT_SUPPORTED" for _, _, outcome in rows
        ),
        "structural_parent_errors": sum(
            outcome["error_code"] in {"PROPOSAL_PARENT_MISMATCH", "PROPOSAL_PARENT_NOT_TERMINAL"}
            for _, _, outcome in rows
        ),
        "pending_priority": sum(
            outcome["error_code"] == "DIAGNOSIS_REQUIRED" for _, _, outcome in rows
        ),
        "closed_class_priority": sum(
            outcome["error_code"] == "HYPOTHESIS_CLASS_CLOSED" for _, _, outcome in rows
        ),
        "canonical_history_unreachable_axes": len(unreachable),
        "preserved_m1c_injected_compatibility_axes": sum(
            isinstance(item.get("preserved_test_surface"), str) for item in unreachable
        ),
        "final_state_observations": len(rows),
        "all_rejection_deltas_zero": all(
            outcome["success"] or _public_json_equal(outcome["deltas"], _ZERO_DELTAS)
            for _, _, outcome in rows
        ),
    }


def _validate_diagnosis_identities(state: Mapping[str, object], project_id: str) -> None:
    from research_os.science import Diagnosis, diagnosis_id

    for wrapper in _diagnosis_wrappers(state):
        body = _diagnosis_body(wrapper)
        diagnosis = Diagnosis.from_mapping(body)
        if not _public_json_equal(diagnosis.to_dict(), body):
            raise AssertionError("Diagnosis parser round-trip mismatch")
        if wrapper.get("diagnosis_digest") != _public_digest(body):
            raise AssertionError("Diagnosis digest mismatch")
        if wrapper.get("diagnosis_digest") != diagnosis.digest:
            raise AssertionError("independent and product Diagnosis digests diverged")
        if wrapper.get("diagnosis_id") != diagnosis_id(project_id, diagnosis.digest):
            raise AssertionError("Diagnosis identity mismatch")


def _partition_observation(state: Mapping[str, object], project_id: str) -> tuple[int, int, bool]:
    _validate_diagnosis_identities(state, project_id)
    diagnoses = _diagnosis_wrappers(state)
    by_class: dict[object, set[object]] = {}
    for wrapper in diagnoses:
        diagnosis = _diagnosis_body(wrapper)
        by_class.setdefault(diagnosis.get("hypothesis_class_id"), set()).add(
            wrapper.get("diagnosis_id")
        )
    exhaustive = 0
    overlaps = 0
    for class_wrapper in _class_wrappers(state):
        body = _body(class_wrapper)
        partitions = [
            _array(body.get(name), name)
            for name in (
                "conclusive_diagnosis_ids",
                "provisional_diagnosis_ids",
                "replicated_diagnosis_ids",
                "inconclusive_diagnosis_ids",
            )
        ]
        flattened = [identifier for part in partitions for identifier in part]
        overlap = len(flattened) - len(set(flattened))
        overlaps += overlap
        expected_ids = by_class.get(body.get("hypothesis_class_id"), set())
        exhaustive += int(not overlap and set(flattened) == expected_ids)
    return exhaustive, overlaps, len(diagnoses) > 0


def _replicated_persists(state: Mapping[str, object]) -> bool:
    for body in _class_bodies(state):
        if body.get("support") != "replicated":
            continue
        replicated = _array(body.get("replicated_diagnosis_ids"), "replicated IDs")
        if not replicated:
            continue
        if body.get("lifecycle") == "closed":
            return True
        wrappers = _diagnosis_wrappers(state)
        positions = {
            wrapper.get("diagnosis_id"): wrapper.get("event_sequence") for wrapper in wrappers
        }
        replication_sequence = min(
            cast(int, positions[identifier])
            for identifier in replicated
            if isinstance(positions.get(identifier), int)
        )
        if any(
            isinstance(wrapper.get("event_sequence"), int)
            and cast(int, wrapper.get("event_sequence")) > replication_sequence
            for wrapper in wrappers
        ):
            return True
    return False


def verify_class_state_partitions(
    inputs: Mapping[str, object], source: FixtureSource
) -> dict[str, object]:
    """Verify class-local Diagnosis partitions and support persistence."""

    matrix = _load_fixture(inputs, source)
    project_id = _project_id(matrix)
    rows = _state_rows(matrix)
    exhaustive = 0
    overlaps = 0
    diagnosis_wrappers = 0
    class_wrappers = 0
    for _, state in rows:
        _validate_state_identities(state, project_id)
        complete, row_overlaps, _ = _partition_observation(state, project_id)
        exhaustive += complete
        overlaps += row_overlaps
        diagnosis_wrappers += len(_diagnosis_wrappers(state))
        class_wrappers += len(_class_wrappers(state))
    return {
        "full_state_cases": len(rows),
        "diagnosis_wrappers": diagnosis_wrappers,
        "class_state_wrappers": class_wrappers,
        "class_local_exhaustive_partitions": exhaustive,
        "partition_overlaps": overlaps,
        "provisional_state_cases": sum(
            any(body.get("support") == "provisional" for body in _class_bodies(state))
            for _, state in rows
        ),
        "replicated_state_cases": sum(
            any(body.get("support") == "replicated" for body in _class_bodies(state))
            for _, state in rows
        ),
        "nonempty_all_passed_supported_cases": sum(
            _nonempty_passing_supported(state) for _, state in rows
        ),
        "replicated_support_persistence_cases": sum(
            _replicated_persists(state) for _, state in rows
        ),
        "post_close_successful_replication_cases": sum(
            any(
                body.get("lifecycle") == "closed" and bool(body.get("replicated_diagnosis_ids"))
                for body in _class_bodies(state)
            )
            for _, state in rows
        ),
    }


def _first_closure(
    history: Sequence[Mapping[str, object]], project_id: str
) -> tuple[int, dict[object, Mapping[str, object]]]:
    first: dict[object, Mapping[str, object]] = {}
    first_sequence = len(history) + 1
    for size in range(1, len(history) + 1):
        _, state = _reduce_history(history[:size], project_id)
        for body in _class_bodies(state):
            class_id = body.get("hypothesis_class_id")
            if body.get("lifecycle") == "closed" and class_id not in first:
                evidence = body.get("closure_evidence")
                if isinstance(evidence, Mapping):
                    first[class_id] = copy.deepcopy(dict(evidence))
                    first_sequence = min(first_sequence, size)
    return first_sequence, first


def verify_class_closure_origin(
    inputs: Mapping[str, object], source: FixtureSource
) -> dict[str, object]:
    """Prove exact-threshold closure and immutable origin evidence."""

    matrix = _load_fixture(inputs, source)
    project_id = _project_id(matrix)
    rows = _state_rows(matrix)
    closed_cases = 0
    threshold_cases = 0
    followups = 0
    all_closed = 0
    limit_three = 0
    limit_four = 0
    limit_four_comparisons = 0
    changed = 0
    for history, state in rows:
        bodies = _class_bodies(state)
        for body in bodies:
            if body.get("hypothesis_class_id") != "class-b":
                continue
            distance = cast(int, body.get("conclusive_rejections", 0)) - cast(
                int, body.get("conclusive_rejection_limit", 0)
            )
            if distance not in {-1, 0, 1}:
                continue
            if body.get("conclusive_rejection_limit") == 3:
                limit_three += 1
            if body.get("conclusive_rejection_limit") == 4:
                limit_four += 1
        closed = [body for body in bodies if body.get("lifecycle") == "closed"]
        if not closed:
            continue
        closed_cases += 1
        all_closed += int(len(closed) == len(bodies) and bool(bodies))
        first_sequence, first_evidence = _first_closure(history, project_id)
        if first_sequence == len(history):
            threshold_cases += 1
        diagnosis_sequences: dict[object, tuple[object, object]] = {}
        for wrapper in _diagnosis_wrappers(state):
            diagnosis = _diagnosis_body(wrapper)
            diagnosis_sequences[wrapper.get("diagnosis_id")] = (
                wrapper.get("event_sequence"),
                diagnosis.get("hypothesis_class_id"),
            )
        has_same_class_followup = False
        for body in closed:
            class_id = body.get("hypothesis_class_id")
            initial = first_evidence.get(class_id)
            final = body.get("closure_evidence")
            if initial is not None and not _public_json_equal(final, initial):
                changed += 1
            closure_id = final.get("diagnosis_id") if isinstance(final, Mapping) else None
            closure_item = diagnosis_sequences.get(closure_id)
            closure_sequence = None if closure_item is None else closure_item[0]
            if isinstance(closure_sequence, int):
                material_followups = {
                    *_array(body.get("conclusive_diagnosis_ids"), "conclusive IDs"),
                    *_array(body.get("provisional_diagnosis_ids"), "provisional IDs"),
                    *_array(body.get("replicated_diagnosis_ids"), "replicated IDs"),
                }
                has_same_class_followup = has_same_class_followup or any(
                    diagnosis_id_value in material_followups
                    and item_class == class_id
                    and isinstance(item_sequence, int)
                    and item_sequence > closure_sequence
                    for diagnosis_id_value, (
                        item_sequence,
                        item_class,
                    ) in diagnosis_sequences.items()
                )
            if (
                initial is not None
                and has_same_class_followup
                and body.get("conclusive_rejection_limit") == 4
            ):
                limit_four_comparisons += 1
        followups += int(has_same_class_followup)
    return {
        "closed_state_cases": closed_cases,
        "exact_threshold_transition_cases": threshold_cases,
        "post_closure_followup_cases": followups,
        "all_classes_closed_cases": all_closed,
        "class_b_limit_three_boundary_cases": limit_three,
        "class_b_limit_four_boundary_cases": limit_four,
        "limit_four_immutable_origin_comparisons": limit_four_comparisons,
        "closure_origin_changes_after_followup": changed,
    }


def _race_rows(
    matrix: Mapping[str, object],
) -> list[
    tuple[
        Mapping[str, object],
        list[dict[str, object]],
        list[Mapping[str, object]],
        Mapping[str, object],
    ]
]:
    project_id = _project_id(matrix)
    observed = []
    for row in _rows(matrix, "race_schedules"):
        precondition = _mapping(row.get("precondition"), "race precondition")
        if set(precondition) != {"event_history"}:
            raise AssertionError("race precondition is not a literal history")
        schedule = [
            _mapping(item, "race schedule operation")
            for item in _array(row.get("schedule"), "race schedule")
        ]
        history = _history_from(precondition)
        outcomes: list[dict[str, object]] = []
        for scheduled in schedule:
            if set(scheduled) != {"operation", "request"}:
                raise AssertionError("race schedule row has non-operation fields")
            operation = _text(scheduled.get("operation"), "race operation")
            request = _mapping(scheduled.get("request"), "race request")
            history, outcome = _execute_operation(
                history,
                operation,
                request,
                project_id,
            )
            race_deltas = dict(_mapping(outcome.get("deltas"), "race deltas"))
            race_deltas.pop("diagnosis_events")
            outcome["deltas"] = race_deltas
            outcomes.append(outcome)
        final_state = _mapping(outcomes[-1].get("state"), "race final state")
        observer_input = {
            "precondition": copy.deepcopy(dict(precondition)),
            "schedule": copy.deepcopy([dict(item) for item in schedule]),
        }
        observed.append((row, outcomes, history, observer_input | {"state": final_state}))
    return observed


def _public_operation_outcome(outcome: Mapping[str, object]) -> dict[str, object]:
    return {
        "operation": outcome.get("operation"),
        "success": outcome.get("success"),
        "appended": outcome.get("appended"),
        "idempotent_reuse": outcome.get("idempotent_reuse"),
        "error_code": outcome.get("error_code"),
        "error_path": outcome.get("error_path"),
        "error_details": copy.deepcopy(outcome.get("error_details")),
        "event": copy.deepcopy(outcome.get("event")),
        "deltas": copy.deepcopy(outcome.get("deltas")),
    }


def observe_literal_race_rows(
    inputs: Mapping[str, object], source: FixtureSource
) -> list[dict[str, object]]:
    """Return every serialized race result without fixture-output access."""

    matrix = _load_fixture(inputs, source)
    project_id = _project_id(matrix)
    observations: list[dict[str, object]] = []
    for ordinal, (row, outcomes, history, observer_input) in enumerate(_race_rows(matrix)):
        precondition = _mapping(row.get("precondition"), "race precondition")
        schedule = [
            _mapping(item, "race schedule operation")
            for item in _array(row.get("schedule"), "race schedule")
        ]
        _, pre_state = _reduce_history(_history_from(precondition), project_id)
        final_state = copy.deepcopy(_mapping(outcomes[-1].get("state"), "race final state"))
        public_outcomes = [_public_operation_outcome(outcome) for outcome in outcomes]
        appended_events = [
            _mapping(event, "race appended event")
            for outcome in public_outcomes
            if isinstance((event := outcome.get("event")), Mapping)
        ]
        registration_outcomes = [
            outcome
            for outcome in public_outcomes
            if outcome.get("operation") in {"register_first_attempt", "register_retry"}
        ]
        input_digest = _race_input_digest(observer_input)
        stop = _mapping(pre_state.get("study_stop"), "pre-race study stop")
        observations.append(
            {
                "ordinal": ordinal,
                "input_sha256": input_digest,
                "pre_state": pre_state,
                "pre_state_digest": _public_digest(pre_state),
                "pending_diagnosis_experiment_ids": copy.deepcopy(
                    pre_state.get("pending_diagnosis_experiment_ids")
                ),
                "study_stop_reasons": copy.deepcopy(stop.get("reasons")),
                "operations": public_outcomes,
                "diagnosis_successes": sum(
                    outcome.get("operation") == "record_diagnosis"
                    and outcome.get("success") is True
                    for outcome in public_outcomes
                ),
                "diagnosis_events": sum(
                    event.get("event_type") == _DIAGNOSIS_EVENT for event in appended_events
                ),
                "registration_events": sum(
                    event.get("event_type") == _REGISTRATION_EVENT for event in appended_events
                ),
                "successor_generation_events": sum(
                    event.get("event_type") == _GENERATION_EVENT for event in appended_events
                ),
                "duplicate_errors": sum(
                    outcome.get("operation") == "record_diagnosis"
                    and outcome.get("error_code") is not None
                    for outcome in public_outcomes
                ),
                "registration_error": next(
                    (
                        outcome.get("error_code")
                        for outcome in registration_outcomes
                        if outcome.get("error_code") is not None
                    ),
                    None,
                ),
                "errors": sum(outcome.get("error_code") is not None for outcome in public_outcomes),
                "count_delta": cast(int, final_state.get("diagnosis_count", 0))
                - cast(int, pre_state.get("diagnosis_count", 0)),
                "final_log_head": _final_log_head(history),
                "final_state": final_state,
                "final_state_digest": _public_digest(final_state),
                "outcome_counts": _race_counts(public_outcomes),
                "observer_input_sha256": input_digest,
                "schedule_operation_count": len(schedule),
            }
        )
    return observations


def _race_label_invariance_flags(matrix: Mapping[str, object]) -> list[bool]:
    baseline = _race_rows(matrix)
    renamed_matrix = copy.deepcopy(dict(matrix))
    renamed_rows = _rows(renamed_matrix, "race_schedules")
    for ordinal, row in enumerate(renamed_rows):
        if not isinstance(row, dict):  # pragma: no cover - deepcopy invariant
            raise TypeError("renamed race row is not mutable")
        row["id"] = f"observer-display-rename-{ordinal}"
        row["label"] = f"observer label rename {ordinal}"
    renamed = _race_rows(renamed_matrix)
    if len(baseline) != len(renamed):
        raise AssertionError("display rename changed the race row count")
    return [
        _public_json_equal(baseline_outcomes, renamed_outcomes)
        and _public_json_equal(baseline_history, renamed_history)
        and _public_json_equal(baseline_input, renamed_input)
        for (_, baseline_outcomes, baseline_history, baseline_input), (
            _,
            renamed_outcomes,
            renamed_history,
            renamed_input,
        ) in zip(baseline, renamed, strict=True)
    ]


def _race_input_digest(observation: Mapping[str, object]) -> str:
    return _digest(
        {
            "precondition": observation.get("precondition"),
            "schedule": observation.get("schedule"),
        }
    )


def _race_counts(outcomes: Sequence[Mapping[str, object]]) -> dict[str, object]:
    return {
        "operation_rows": len(outcomes),
        "successes": sum(outcome.get("success") is True for outcome in outcomes),
        "failures": sum(outcome.get("success") is False for outcome in outcomes),
        "appended_events": sum(outcome.get("appended") is True for outcome in outcomes),
        "idempotent_reuses": sum(outcome.get("idempotent_reuse") is True for outcome in outcomes),
        "error_codes": [
            outcome.get("error_code")
            for outcome in outcomes
            if outcome.get("error_code") is not None
        ],
    }


def execute_all_literal_races(
    inputs: Mapping[str, object], source: FixtureSource
) -> dict[str, object]:
    """Execute each literal serialization schedule in declared operation order."""

    matrix = _load_fixture(inputs, source)
    rows = _race_rows(matrix)
    all_outcomes = [outcome for _, outcomes, _, _ in rows for outcome in outcomes]
    duplicate = [
        outcomes
        for row, outcomes, _, _ in rows
        if all(
            item.get("operation") == "record_diagnosis"
            for item in _array(row.get("schedule"), "race schedule")
        )
    ]
    if len(duplicate) != 1:
        raise AssertionError("literal race corpus must contain one duplicate append schedule")
    duplicate_outcomes = duplicate[0]
    verbs = sorted({cast(str, outcome["operation"]) for outcome in all_outcomes})
    rename_flags = _race_label_invariance_flags(matrix)
    return {
        "schedules": len(rows),
        "literal_schedule_rows": len(all_outcomes),
        "operation_successes": sum(outcome["success"] is True for outcome in all_outcomes),
        "operation_failures": sum(outcome["success"] is False for outcome in all_outcomes),
        "appended_events": sum(outcome["appended"] is True for outcome in all_outcomes),
        "outcome_count_observations": len(rows),
        "display_id_label_rename_invariance_assertions": sum(rename_flags),
        "semantic_lock_operation_labels": sum(
            verb
            not in {
                "open_successor_generation",
                "record_diagnosis",
                "register_first_attempt",
            }
            for verb in verbs
        ),
        "generic_operation_verbs": verbs,
        "diagnosis_successes": sum(outcome["success"] is True for outcome in duplicate_outcomes),
        "diagnosis_events": sum(outcome["appended"] is True for outcome in duplicate_outcomes),
        "duplicate_errors": sum(
            outcome["error_code"] is not None for outcome in duplicate_outcomes
        ),
        "idempotent_reuses": sum(
            outcome["idempotent_reuse"] is True for outcome in duplicate_outcomes
        ),
        "final_state_observations": len(rows),
    }


def verify_race_serialization_groups(
    inputs: Mapping[str, object], source: FixtureSource
) -> dict[str, object]:
    """Verify diagnosis/registration/closure/successor serialization groups."""

    matrix = _load_fixture(inputs, source)
    rows = _race_rows(matrix)
    diagnosis_first_registration_successes = 0
    registration_first_diagnosis_required = 0
    closure_first_class_closed = 0
    registration_first_closure_diagnosis_required = 0
    diagnosis_first_successor_events = 0
    successor_first_diagnosis_required = 0
    for row, outcomes, _, observation in rows:
        schedule = _array(row.get("schedule"), "race schedule")
        verbs = [_mapping(item, "race operation").get("operation") for item in schedule]
        state = _mapping(observation.get("state"), "race final state")
        class_closed = any(body.get("lifecycle") == "closed" for body in _class_bodies(state))
        if verbs == ["record_diagnosis", "register_first_attempt"]:
            if outcomes[1]["success"]:
                diagnosis_first_registration_successes += 1
            elif outcomes[1]["error_code"] == "HYPOTHESIS_CLASS_CLOSED":
                closure_first_class_closed += 1
        elif verbs == ["register_first_attempt", "record_diagnosis"]:
            if outcomes[0]["error_code"] == "DIAGNOSIS_REQUIRED" and class_closed:
                registration_first_closure_diagnosis_required += 1
            elif outcomes[0]["error_code"] == "DIAGNOSIS_REQUIRED":
                registration_first_diagnosis_required += 1
        elif verbs == ["record_diagnosis", "open_successor_generation"]:
            diagnosis_first_successor_events += int(
                outcomes[1]["success"] and outcomes[1]["appended"]
            )
        elif verbs == ["open_successor_generation", "record_diagnosis"]:
            successor_first_diagnosis_required += int(
                outcomes[0]["error_code"] == "DIAGNOSIS_REQUIRED"
            )
    return {
        "schedules": len(rows),
        "literal_schedule_rows": sum(len(outcomes) for _, outcomes, _, _ in rows),
        "final_state_observations": len(rows),
        "diagnosis_first_registration_successes": diagnosis_first_registration_successes,
        "registration_first_diagnosis_required": registration_first_diagnosis_required,
        "closure_first_class_closed": closure_first_class_closed,
        "registration_first_closure_diagnosis_required": registration_first_closure_diagnosis_required,
        "diagnosis_first_successor_events": diagnosis_first_successor_events,
        "successor_first_diagnosis_required": successor_first_diagnosis_required,
    }


def verify_race_label_invariance(
    inputs: Mapping[str, object], source: FixtureSource
) -> dict[str, object]:
    """Prove that out-of-band display renames do not alter observer input."""

    matrix = _load_fixture(inputs, source)
    rows = _race_rows(matrix)
    hashes = [_race_input_digest(observation) for _, _, _, observation in rows]
    renamed_matrix = copy.deepcopy(dict(matrix))
    for ordinal, row in enumerate(_rows(renamed_matrix, "race_schedules")):
        if not isinstance(row, dict):  # pragma: no cover - deepcopy invariant
            raise TypeError("renamed race row is not mutable")
        row["id"] = f"observer-display-rename-{ordinal}"
        row["label"] = f"observer label rename {ordinal}"
    renamed_rows = _race_rows(renamed_matrix)
    renamed_hashes = [_race_input_digest(observation) for _, _, _, observation in renamed_rows]
    invariance = _race_label_invariance_flags(matrix)
    return {
        "schedules": len(rows),
        "observer_input_hash_observations": len(hashes),
        "display_renamed_observer_input_hash_observations": len(renamed_hashes),
        "display_id_label_rename_invariance_assertions": sum(
            flag and left == right
            for flag, left, right in zip(invariance, hashes, renamed_hashes, strict=True)
        ),
        "semantic_lock_operation_labels": sum(
            _mapping(item, "race operation").get("operation")
            not in {
                "open_successor_generation",
                "record_diagnosis",
                "register_first_attempt",
            }
            for row, _, _, _ in rows
            for item in _array(row.get("schedule"), "race schedule")
        ),
    }


def verify_race_operation_coverage(
    inputs: Mapping[str, object], source: FixtureSource
) -> dict[str, object]:
    """Summarize the generic operation vocabulary and outcome coverage."""

    matrix = _load_fixture(inputs, source)
    rows = _race_rows(matrix)
    schedule_rows = [
        item for row, _, _, _ in rows for item in _array(row.get("schedule"), "race schedule")
    ]
    operations = [_mapping(item, "race operation").get("operation") for item in schedule_rows]
    outcomes = [outcome for _, items, _, _ in rows for outcome in items]
    generic = sorted({cast(str, operation) for operation in operations})
    allowed = {
        "open_successor_generation",
        "record_diagnosis",
        "register_first_attempt",
    }
    return {
        "schedules": len(rows),
        "generic_operation_verbs": generic,
        "semantic_lock_operation_labels": sum(operation not in allowed for operation in operations),
        "literal_schedule_rows": len(schedule_rows),
        "string_schedule_rows": sum(isinstance(item, str) for item in schedule_rows),
        "operation_successes": sum(outcome["success"] is True for outcome in outcomes),
        "operation_failures": sum(outcome["success"] is False for outcome in outcomes),
        "appended_events": sum(outcome["appended"] is True for outcome in outcomes),
    }


def _literal_event_log(path: Path, history: Sequence[Mapping[str, object]], project_id: str) -> Any:
    from research_os.kernel._canonical import canonical_bytes
    from research_os.kernel.events import Event, EventLog

    events = [Event.from_mapping(item) for item in history]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(canonical_bytes(event.to_dict()) + b"\n" for event in events))
    path.chmod(0o600)
    return EventLog(path, project_id)


def _service_harness(event_log: Any, projection: Any, project_id: str) -> Any:
    from research_os.service import ResearchService

    class LiteralReplayService(ResearchService):
        def __init__(self) -> None:
            self.config = SimpleNamespace(project_id=project_id)  # type: ignore[assignment]
            self.event_log = event_log
            self.projection = projection
            self.catalog = SimpleNamespace(get=lambda _: None)  # type: ignore[assignment]

        @contextmanager
        def _workflow_lock(self):  # type: ignore[no-untyped-def,override]
            yield

        def _assert_config_unchanged(self) -> None:
            return None

        def _recover_incomplete_experiments(self) -> None:
            return None

        def _verify_terminal_artifact_bindings(  # type: ignore[no-untyped-def,override]
            self,
            projected_records,
            *,
            events=None,
        ):
            return None

        def _validate_baseline_payload(  # type: ignore[no-untyped-def,override]
            self,
            payload,
            compatibility_digest,
            **kwargs,
        ):
            return {**payload, "artifacts": []}

    return LiteralReplayService()


def _path_error(exc: BaseException) -> tuple[str, object]:
    code = _error_code(exc)
    details = getattr(exc, "details", None)
    path = details.get("path") if isinstance(details, Mapping) else None
    return code, path


def _path_result(
    *,
    accepted: bool,
    error_code: str | None = None,
    error_path: object = None,
    deltas: Mapping[str, int] | None = None,
) -> dict[str, object]:
    return {
        "accepted": accepted,
        "error_code": error_code,
        "error_path": error_path,
        "deltas": dict(_NEGATIVE_PATH_ZERO_DELTAS if deltas is None else deltas),
    }


def execute_history_paths(
    history: Sequence[Mapping[str, object]],
    project_id: str,
    work_root: Path,
) -> dict[str, dict[str, object]]:
    """Exercise one literal final event through four independent replay paths.

    The final envelope is deliberately replayed as supplied.  In particular, a
    malformed Diagnosis wrapper is never replaced by a body-derived plan.
    """

    from research_os.kernel.events import Event
    from research_os.kernel.projection import ProjectionStore
    from research_os.science import reduce_scientific_state

    if not history:
        raise ValueError("history-path execution requires at least one event")
    literal = [dict(item) for item in history]
    events = [Event.from_mapping(item) for item in literal]
    prefix = events[:-1]
    candidate = events[-1]
    work_root = Path(work_root).resolve()
    work_root.mkdir(parents=True, exist_ok=True)
    results: dict[str, dict[str, object]] = {}

    with tempfile.TemporaryDirectory(prefix="m1d-paths-", dir=work_root) as temporary:
        root = Path(temporary)

        locked_log = _literal_event_log(
            root / "locked" / "events.jsonl",
            [event.to_dict() for event in prefix],
            project_id,
        )
        try:
            before = reduce_scientific_state(prefix, project_id=project_id)
            appended = locked_log.append(
                candidate.event_type,
                candidate.payload,
                event_id=candidate.event_id,
                occurred_at=candidate.occurred_at,
                expected_head=((prefix[-1].sequence, prefix[-1].hash) if prefix else (0, None)),
                precondition=lambda locked: reduce_scientific_state(
                    [*locked, candidate], project_id=project_id
                ),
                postcondition=lambda locked: reduce_scientific_state(
                    [*locked, candidate], project_id=project_id
                ),
            )
            if appended.hash != candidate.hash:
                raise AssertionError("locked literal append changed the event hash")
            after = reduce_scientific_state(locked_log.read(), project_id=project_id)
            results["locked_append"] = _path_result(
                accepted=True,
                deltas=_operation_deltas(
                    before,
                    after,
                    appended=1,
                    event_type=candidate.event_type,
                ),
            )
        except Exception as exc:
            code, path = _path_error(exc)
            results["locked_append"] = _path_result(
                accepted=False, error_code=code, error_path=path
            )

        try:
            reduce_scientific_state(events, project_id=project_id)
            results["cold_reducer"] = _path_result(accepted=True)
        except Exception as exc:
            code, path = _path_error(exc)
            results["cold_reducer"] = _path_result(accepted=False, error_code=code, error_path=path)

        projection_log = _literal_event_log(
            root / "projection" / "events.jsonl", literal, project_id
        )
        try:
            ProjectionStore(root / "projection" / "state.db").rebuild(projection_log)
            results["projection_rebuild"] = _path_result(accepted=True)
        except Exception as exc:
            code, path = _path_error(exc)
            results["projection_rebuild"] = _path_result(
                accepted=False, error_code=code, error_path=path
            )

        service_log = _literal_event_log(root / "service" / "events.jsonl", literal, project_id)
        try:
            service = _service_harness(
                service_log,
                ProjectionStore(root / "service" / "state.db"),
                project_id,
            )
            service.replay()
            results["service_replay"] = _path_result(accepted=True)
        except Exception as exc:
            code, path = _path_error(exc)
            results["service_replay"] = _path_result(
                accepted=False, error_code=code, error_path=path
            )
    return results
