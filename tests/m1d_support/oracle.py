"""Executable, operation-only observers for the frozen M1-D fixtures.

The manifest dispatcher receives exactly an operation name and its input object.
Display identity and the manifest comparison value never cross that boundary.
Supporting corpora remain data: row identity may join literal source histories,
but it never selects observer behavior.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any, TypeAlias, cast
from unittest import mock

JSONValue: TypeAlias = None | bool | int | float | str | list["JSONValue"] | dict[str, "JSONValue"]
Observation = Callable[[Mapping[str, object]], dict[str, object]]
_DIAGNOSIS_OBSERVATION_KEYS = frozenset(
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


class DuplicateKeyError(ValueError):
    """A supposedly canonical fixture repeated an object key."""


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON object key: {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number is forbidden: {value}")


def strict_load_json(path: Path) -> object:
    """Read strict JSON, rejecting duplicate keys and non-finite numbers."""

    return json.loads(
        path.read_text(encoding="utf-8"),
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_nonfinite,
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sorted_compact_digest(value: object) -> str:
    """Kernel compact digest, deliberately distinct from public sha256_json."""

    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256_bytes(encoded)


def json_canonical_equal(left: object, right: object) -> bool:
    """Compare values in the public canonical-JSON equality domain."""

    from research_os.contracts import canonical_json_bytes

    return canonical_json_bytes(left) == canonical_json_bytes(right)


def canonical_event_digest(unsigned_event: Mapping[str, object]) -> str:
    """Independently recompute an Event hash with the kernel compact encoder."""

    return sorted_compact_digest(dict(unsigned_event))


def recursive_key_values(value: object, key: str) -> list[object]:
    values: list[object] = []
    if isinstance(value, Mapping):
        for name, item in value.items():
            if name == key:
                values.append(item)
            values.extend(recursive_key_values(item, key))
    elif isinstance(value, list):
        for item in value:
            values.extend(recursive_key_values(item, key))
    return values


def _recursive_key_occurrences(value: object, keys: frozenset[str]) -> int:
    if isinstance(value, Mapping):
        return sum(name in keys for name in value) + sum(
            _recursive_key_occurrences(item, keys) for item in value.values()
        )
    if isinstance(value, list):
        return sum(_recursive_key_occurrences(item, keys) for item in value)
    return 0


def _mapping_difference_count(frozen: Mapping[str, object], observed: Mapping[str, object]) -> int:
    return len(set(frozen) ^ set(observed)) + sum(
        not json_canonical_equal(observed[key], value)
        for key, value in frozen.items()
        if key in observed
    )


def _v2_budget_difference_count(
    raw_budget: Mapping[str, object],
    observed_budget: Mapping[str, object],
) -> int:
    attempts = _mapping(observed_budget.get("attempts"), "attempt budget")
    retries = _mapping(observed_budget.get("retries"), "retry budget")
    elapsed = _mapping(observed_budget.get("elapsed_milliseconds"), "elapsed budget")
    cost = _mapping(observed_budget.get("cost_microunits"), "cost budget")
    comparisons = (
        (attempts.get("limit"), raw_budget.get("max_attempts")),
        (retries.get("limit"), raw_budget.get("max_retries")),
        (elapsed.get("limit"), raw_budget.get("max_elapsed_milliseconds")),
        (
            elapsed.get("reserved"),
            raw_budget.get("elapsed_reservation_per_attempt_milliseconds"),
        ),
        (cost.get("unit"), raw_budget.get("cost_unit")),
        (cost.get("limit"), raw_budget.get("max_cost_microunits")),
        (
            cost.get("reserved"),
            raw_budget.get("cost_reservation_per_attempt_microunits"),
        ),
    )
    return sum(not json_canonical_equal(left, right) for left, right in comparisons)


def _pointer_tokens(pointer: str) -> list[str]:
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ValueError(f"invalid RFC-6901 pointer: {pointer!r}")
    tokens: list[str] = []
    for token in pointer[1:].split("/"):
        tokens.append(token.replace("~1", "/").replace("~0", "~"))
    return tokens


def _pointer_parent(document: object, pointer: str) -> tuple[object, str]:
    tokens = _pointer_tokens(pointer)
    if not tokens:
        raise ValueError("root pointer has no parent")
    current = document
    for token in tokens[:-1]:
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, Mapping):
            current = current[token]
        else:
            raise KeyError(f"pointer crosses a scalar at {token!r}")
    return current, tokens[-1]


def _pointer_get(document: object, pointer: str) -> object:
    current = document
    for token in _pointer_tokens(pointer):
        if isinstance(current, list):
            current = current[int(token)]
        elif isinstance(current, Mapping):
            current = current[token]
        else:
            raise KeyError(f"pointer crosses a scalar at {token!r}")
    return current


def apply_json_patch(document: object, patch: Mapping[str, object]) -> object:
    """Apply the mutation vocabulary shared by the negative corpus."""

    operation = patch.get("op")
    pointer = patch.get("path")
    if not isinstance(operation, str) or not isinstance(pointer, str):
        raise TypeError("patch operation and path must be text")
    if operation == "replace_utf8_recipe":
        code_point = patch.get("code_point")
        repeat = patch.get("repeat")
        suffix = patch.get("suffix", "")
        if (
            not isinstance(code_point, str)
            or len(code_point) != 1
            or isinstance(repeat, bool)
            or not isinstance(repeat, int)
            or repeat < 0
            or not isinstance(suffix, str)
        ):
            raise TypeError("invalid UTF-8 replacement recipe")
        patch = {"op": "replace", "path": pointer, "value": code_point * repeat + suffix}
        operation = "replace"
    if operation not in {"add", "remove", "replace"}:
        raise ValueError(f"unsupported patch operation: {operation!r}")
    if pointer == "":
        if operation == "remove":
            raise ValueError("cannot remove the document root")
        if "value" not in patch:
            raise KeyError("root replacement requires a value")
        return copy.deepcopy(patch["value"])

    parent, token = _pointer_parent(document, pointer)
    if isinstance(parent, list):
        if operation == "add":
            value = copy.deepcopy(patch["value"])
            if token == "-":
                parent.append(value)
            else:
                parent.insert(int(token), value)
        elif operation == "remove":
            parent.pop(int(token))
        else:
            parent[int(token)] = copy.deepcopy(patch["value"])
        return document
    if not isinstance(parent, dict):
        raise KeyError(f"patch parent is not a container: {pointer!r}")
    if operation == "add":
        parent[token] = copy.deepcopy(patch["value"])
    elif operation == "remove":
        del parent[token]
    else:
        if token not in parent:
            raise KeyError(f"replace target is absent: {pointer!r}")
        parent[token] = copy.deepcopy(patch["value"])
    return document


def _apply_corpus_patch(document: object, patch: Mapping[str, object]) -> object:
    operation = patch.get("op")
    pointer = patch.get("path")
    if operation in {"add", "remove", "replace", "replace_utf8_recipe"}:
        return apply_json_patch(document, patch)
    if not isinstance(pointer, str):
        raise TypeError("corpus patch path must be text")
    target = _pointer_get(document, pointer)
    if not isinstance(target, list):
        raise TypeError(f"{operation!r} requires an array target")
    if operation == "append":
        target.append(copy.deepcopy(patch.get("value")))
    elif operation == "append_copy":
        source_index = patch.get("source_index")
        if isinstance(source_index, bool) or not isinstance(source_index, int):
            raise TypeError("append_copy source_index must be an integer")
        target.append(copy.deepcopy(target[source_index]))
    elif operation == "reverse":
        target.reverse()
    else:
        raise ValueError(f"unsupported corpus patch operation: {operation!r}")
    return document


class OperationRegistry:
    """Dispatch solely on a declared operation and pass only its input."""

    def __init__(self) -> None:
        self._operations: dict[str, Observation] = {}

    def register(self, operation: str, observer: Observation) -> None:
        if not operation or operation in self._operations:
            raise ValueError(f"duplicate or empty observer operation: {operation!r}")
        self._operations[operation] = observer

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._operations)

    def observe(
        self,
        operation: str,
        inputs: Mapping[str, object],
    ) -> dict[str, object]:
        if not isinstance(operation, str) or not isinstance(inputs, Mapping):
            raise TypeError("observer dispatch requires operation text and an input object")
        try:
            observer = self._operations[operation]
        except KeyError as exc:
            raise AssertionError(f"unbound manifest operation: {operation}") from exc
        return observer(inputs)


def _mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return cast(Mapping[str, object], value)


def _list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    return value


def _text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{name} must be non-empty text")
    return value


def _integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _event_objects(history: object, project_id: str) -> list[Any]:
    """Parse every loose envelope and verify the complete ordered chain."""

    from research_os.kernel.events import Event, verify_events

    events = [Event.from_mapping(_mapping(item, "event")) for item in _list(history, "history")]
    verify_events(events, project_id=project_id)
    return events


def _event_hashes_independent(history: object) -> bool:
    for raw in _list(history, "history"):
        envelope = dict(_mapping(raw, "event"))
        supplied = envelope.pop("hash", None)
        if supplied != canonical_event_digest(envelope):
            return False
    return True


def _authorized_action_non_null(value: object) -> int:
    return sum(item is not None for item in recursive_key_values(value, "authorized_action"))


def _event_payloads(history: object, normalized_type: str) -> list[Mapping[str, object]]:
    result: list[Mapping[str, object]] = []
    for raw in _list(history, "history"):
        envelope = _mapping(raw, "event")
        event_type = envelope.get("event_type")
        if (
            isinstance(event_type, str)
            and event_type.strip().upper().replace(".", "_").replace("-", "_") == normalized_type
        ):
            result.append(_mapping(envelope.get("payload"), "event payload"))
    return result


def _terminal_event(history: object) -> Mapping[str, object] | None:
    for raw in reversed(_list(history, "history")):
        envelope = _mapping(raw, "event")
        event_type = envelope.get("event_type")
        payload = _mapping(envelope.get("payload"), "event payload")
        if event_type == "EXPERIMENT_TERMINATED":
            return envelope
        if event_type == "EXPERIMENT_STATUS_CHANGED" and _canonical_status(
            payload.get("status")
        ) in {
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
        }:
            return envelope
    return None


_STATUS_ALIASES = {
    "SUCCESS": "SUCCEEDED",
    "PASSED": "SUCCEEDED",
    "COMPLETE": "COMPLETED",
    "TIMEOUT": "TIMED_OUT",
    "TIMEDOUT": "TIMED_OUT",
    "CANCELED": "CANCELLED",
    "ERROR": "FAILED",
}

_NORMALIZATION_ROW_FIELDS = (
    "experiment_id",
    "terminal_event_id",
    "terminal_event_hash",
    "raw_terminal_status",
    "canonical_terminal_status",
    "reason_code",
    "verified",
    "retryable",
    "primary_metric",
    "candidate_value",
    "baseline_value",
    "improvement",
    "promotion_margin",
    "gate_evaluations",
)
_NORMALIZATION_ROW_ORDER = "diagnosis_fixture_case_order"

_M1D_ADDITIVE_PUBLIC_KEYS = frozenset(
    {
        "class_state",
        "class_state_digest",
        "class_state_id",
        "class_states",
        "diagnosis",
        "diagnosis_count",
        "diagnosis_digest",
        "diagnosis_event_hash",
        "diagnosis_event_id",
        "diagnosis_id",
        "diagnoses",
        "pending_diagnosis_experiment_ids",
        "retry_frontier",
        "semantic_frontier",
        "study_stop",
    }
)
_CONTEXT_V2_TOP_LEVEL_KEYS = frozenset(
    {
        "agent",
        "allowed_agent_actions",
        "authority",
        "evidence",
        "graph",
        "kind",
        "packet_size_bytes",
        "project",
        "proposal_contract",
        "schema_version",
        "snapshot",
        "state",
    }
)
_BRANCH_CONCLUSION_V1_KEYS = frozenset(
    {
        "branch_conclusion_version",
        "content",
        "event_sequence",
        "evidence",
        "experiment_id",
        "finding_id",
        "key",
        "metadata",
        "project_id",
        "scope",
        "session_id",
    }
)
_BRANCH_CONCLUSION_V1_CONTENT_KEYS = frozenset(
    {
        "branch_experiment_ids",
        "compatibility_digest",
        "conclusion",
        "confidence",
        "failure_signature",
        "hypothesis_class",
        "next_step",
    }
)
_BRANCH_CONCLUSION_V1_EVIDENCE_KEYS = frozenset({"event_hash", "event_id", "experiment_id"})
_BRANCH_CONCLUSION_V1_METADATA_KEYS = frozenset(
    {
        "agent_context_schema_version",
        "agent_context_token",
        "authorized_action",
        "claim_authority",
    }
)


def _canonical_status(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
    return _STATUS_ALIASES.get(normalized, normalized)


def _is_generic_status_event(envelope: Mapping[str, object]) -> bool:
    return envelope.get("event_type") == "EXPERIMENT_STATUS_CHANGED"


def _is_terminal_status(value: object) -> bool:
    return _canonical_status(value) in {
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


def _kernel_retryable(payload: Mapping[str, object]) -> bool:
    declared = payload.get("retryable")
    if isinstance(declared, bool):
        return declared
    return _canonical_status(payload.get("status")) in {
        "TIMED_OUT",
        "CANCELLED",
        "INFRA_FAILED",
        "INSUFFICIENT_EVIDENCE",
    }


def _observation_from_history(history: object) -> dict[str, object] | None:
    terminal = _terminal_event(history)
    if terminal is None:
        return None
    payload = _mapping(terminal.get("payload"), "terminal payload")
    decision = payload.get("decision")
    decision_map = _mapping(decision, "decision") if isinstance(decision, Mapping) else None
    event_type = terminal.get("event_type")
    reason = payload.get("reason_code")
    if not isinstance(reason, str) or not reason:
        reason = "STATUS_CHANGED" if event_type == "EXPERIMENT_STATUS_CHANGED" else "TERMINATED"
    primary_metric = payload.get("primary_metric")
    if not isinstance(primary_metric, str) or not primary_metric:
        primary_metric = decision_map.get("primary_metric") if decision_map is not None else None
    if not isinstance(primary_metric, str) or not primary_metric:
        registration_metric: object = None
        baseline_metric: object = None
        for raw in _list(history, "history"):
            envelope = _mapping(raw, "event")
            item_payload = _mapping(envelope.get("payload"), "event payload")
            if envelope.get("event_type") == "EXPERIMENT_REGISTERED":
                candidate = item_payload.get("primary_metric")
                if isinstance(candidate, str) and candidate:
                    registration_metric = candidate
            elif envelope.get("event_type") == "BASELINE_RECORDED":
                candidate = item_payload.get("primary_metric")
                if isinstance(candidate, str) and candidate:
                    baseline_metric = candidate
        primary_metric = registration_metric if registration_metric is not None else baseline_metric
    return {
        "terminal_status": _canonical_status(payload.get("status")),
        "reason_code": reason,
        "verified": payload.get("verified", False),
        "retryable": _kernel_retryable(payload),
        "primary_metric": primary_metric,
        "candidate_value": None if decision_map is None else decision_map.get("candidate_value"),
        "baseline_value": None if decision_map is None else decision_map.get("baseline_value"),
        "improvement": None if decision_map is None else decision_map.get("improvement"),
        "promotion_margin": None if decision_map is None else decision_map.get("promotion_margin"),
        "gate_evaluations": []
        if decision_map is None
        else decision_map.get("gate_evaluations", []),
    }


def _public_digest(value: object) -> str:
    from research_os.contracts.common import sha256_json

    return sha256_json(value)


def _stable_id(namespace: str, *components: object) -> str:
    from research_os.kernel.ids import stable_id

    return stable_id(namespace, *components)


_REGRESSION_OBSERVATION: dict[str, object] | None = None


def _completed(
    command: list[str], *, environment: Mapping[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[2],
        check=False,
        capture_output=True,
        text=True,
        env=None if environment is None else dict(environment),
    )


def _approved_floor(path: Path, pattern: str) -> tuple[int, int]:
    match = re.search(pattern, path.read_text(encoding="utf-8"), flags=re.DOTALL)
    if match is None:
        raise AssertionError(f"approved regression floor is absent from {path.name}")
    return int(match.group(1)), int(match.group(2))


def _m1c_exact_case_count(case_count: int) -> int:
    """Run the frozen M1-C outer comparisons without recursing through M1-D."""

    environment = dict(os.environ)
    existing_options = environment.get("PYTEST_ADDOPTS", "").strip()
    environment["PYTEST_ADDOPTS"] = " ".join(
        option
        for option in (
            existing_options,
            "--ignore=tests/test_m1d_manifest_oracle.py",
        )
        if option
    )
    run = _completed(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_m1c_manifest_oracle.py::"
            "test_every_manifest_case_has_an_operation_only_expectation_binding",
        ],
        environment=environment,
    )
    output = run.stdout + run.stderr
    match = re.search(r"(?:^|\s)(\d+) passed", output)
    if run.returncode != 0 or match is None:
        raise AssertionError(output)
    passed = int(match.group(1))
    if passed != case_count:
        raise AssertionError(
            f"M1-C exact comparison count changed: {passed}/{case_count}\n{output}"
        )
    return passed


class DiagnosisNegativeMaterializer:
    """Materialize mutation recipes without semantic dispatch on display identity."""

    def __init__(
        self,
        matrix: Mapping[str, object],
        terminal_fixture: Mapping[str, object],
        diagnosis_fixture: Mapping[str, object],
    ) -> None:
        self.matrix = matrix
        self.project_id = _text(diagnosis_fixture.get("project_id"), "project id")
        self._terminal_records = self._indexed(
            _list(terminal_fixture.get("records"), "terminal records")
        )
        self._diagnosis_rows = self._indexed(
            _list(diagnosis_fixture.get("cases"), "diagnosis rows")
        )

    @staticmethod
    def _indexed(rows: list[object]) -> dict[object, Mapping[str, object]]:
        result: dict[object, Mapping[str, object]] = {}
        for raw_row in rows:
            row = _mapping(raw_row, "referenced row")
            identity = row.get("id")
            if identity in result:
                raise AssertionError("duplicate supporting-row identity")
            result[identity] = row
        return result

    def _base_history(self, inputs: Mapping[str, object]) -> list[dict[str, object]]:
        reference = inputs.get("base_case")
        try:
            diagnosis_row = self._diagnosis_rows[reference]
        except KeyError as exc:
            raise AssertionError("negative recipe references an unknown Diagnosis") from exc
        terminal_reference = diagnosis_row.get("terminal_record_id")
        try:
            terminal_record = self._terminal_records[terminal_reference]
        except KeyError as exc:
            raise AssertionError("Diagnosis references an unknown terminal history") from exc
        history = copy.deepcopy(
            _list(terminal_record.get("canonical_history"), "canonical history")
        )
        history.append(copy.deepcopy(dict(_mapping(diagnosis_row.get("diagnosis_event"), "event"))))
        return cast(list[dict[str, object]], history)

    @staticmethod
    def _matching_event_indexes(
        history: Sequence[Mapping[str, object]], selector: Mapping[str, object]
    ) -> list[int]:
        return [
            index
            for index, event in enumerate(history)
            if all(json_canonical_equal(event.get(key), value) for key, value in selector.items())
        ]

    @staticmethod
    def _diagnosis_indexes(history: Sequence[Mapping[str, object]]) -> list[int]:
        return [
            index
            for index, event in enumerate(history)
            if event.get("event_type") == "research.experiment_diagnosed.v1"
        ]

    @staticmethod
    def _artifact_indexes(history: Sequence[Mapping[str, object]]) -> list[int]:
        return [
            index
            for index, event in enumerate(history)
            if event.get("event_type") == "ARTIFACT_RECORDED"
        ]

    def _inject_registered_decoy(
        self,
        history: list[dict[str, object]],
        mutation: Mapping[str, object],
    ) -> None:
        source_reference = mutation.get("source_terminal_record_id")
        try:
            source = self._terminal_records[source_reference]
        except KeyError as exc:
            raise AssertionError("decoy mutation references an unknown history") from exc
        source_history = _list(source.get("canonical_history"), "decoy history")
        requested_types = _list(mutation.get("inject_event_types"), "decoy event types")
        selected = [
            copy.deepcopy(dict(_mapping(raw, "decoy event")))
            for requested in requested_types
            for raw in source_history
            if _mapping(raw, "decoy event").get("event_type") == requested
        ]
        artifacts = self._artifact_indexes(history)
        artifact_position = mutation.get("artifact_event_index")
        if isinstance(artifact_position, bool) or not isinstance(artifact_position, int):
            raise TypeError("artifact_event_index must be an integer")
        target_index = artifacts[artifact_position]
        history[target_index:target_index] = selected
        target_index += len(selected)
        registrations = [
            event for event in selected if event.get("event_type") == "EXPERIMENT_REGISTERED"
        ]
        if len(registrations) != 1:
            raise AssertionError("decoy injection must contain one registration")
        registration_payload = _mapping(registrations[0].get("payload"), "registration")
        artifact_payload = _mapping(history[target_index].get("payload"), "artifact")
        cast(dict[str, object], artifact_payload)["experiment_id"] = registration_payload.get(
            "experiment_id"
        )

    def _mutate_history(
        self,
        history: list[dict[str, object]],
        mutation: Mapping[str, object],
    ) -> None:
        operation = mutation.get("op")
        if operation == "move_event_after_diagnosis":
            selector = _mapping(mutation.get("selector"), "event selector")
            matches = self._matching_event_indexes(history, selector)
            if len(matches) != 1:
                raise AssertionError("event move selector must resolve exactly once")
            moved = history.pop(matches[0])
            diagnosis_index = self._diagnosis_indexes(history)[0]
            history.insert(diagnosis_index + 1, moved)
            return
        if operation == "move_selected_artifact_after_terminal":
            artifact_position = mutation.get("artifact_index")
            if isinstance(artifact_position, bool) or not isinstance(artifact_position, int):
                raise TypeError("artifact_index must be an integer")
            selected_index = self._artifact_indexes(history)[artifact_position]
            moved = history.pop(selected_index)
            terminal_index = next(
                index
                for index, event in enumerate(history)
                if event.get("event_type") == "EXPERIMENT_TERMINATED"
            )
            history.insert(terminal_index + 1, moved)
            return
        if operation == "append_diagnosis_copy":
            source_index = self._diagnosis_indexes(history)[0]
            duplicated = copy.deepcopy(history[source_index])
            duplicated["event_id"] = mutation.get("new_event_id")
            history.append(duplicated)
            return
        if operation == "replace_on_appended_copy":
            target_index = self._diagnosis_indexes(history)[-1]
            payload = _mapping(history[target_index].get("payload"), "diagnosis payload")
            replacement = {
                "op": "replace",
                "path": mutation.get("path"),
                "value": mutation.get("value"),
            }
            _apply_corpus_patch(payload, replacement)
            return
        if operation == "reassign_artifact_to_registered_decoy":
            self._inject_registered_decoy(history, mutation)
            return
        selector_raw = mutation.get("event_selector")
        if isinstance(selector_raw, Mapping):
            matches = self._matching_event_indexes(history, selector_raw)
            if len(matches) != 1:
                raise AssertionError("event selector must resolve exactly once")
            _apply_corpus_patch(history[matches[0]], mutation)
            return
        artifact_position = mutation.get("artifact_event_index")
        if isinstance(artifact_position, int) and not isinstance(artifact_position, bool):
            target_index = self._artifact_indexes(history)[artifact_position]
            payload = _mapping(history[target_index].get("payload"), "artifact payload")
            _apply_corpus_patch(payload, mutation)
            return
        raise ValueError(f"history mutation lacks a data selector: {operation!r}")

    def _recompute_artifact_identities(self, history: list[dict[str, object]]) -> None:
        for index in self._artifact_indexes(history):
            payload = cast(
                dict[str, object],
                _mapping(history[index].get("payload"), "artifact payload"),
            )
            payload["artifact_id"] = _stable_id(
                "artifact",
                payload.get("project_id"),
                payload.get("experiment_id"),
                payload.get("relative_path"),
                payload.get("digest"),
                payload.get("role"),
                payload.get("media_type"),
                payload.get("metadata"),
            )

    @staticmethod
    def _rebind_diagnosis_evidence(
        body: dict[str, object],
        prefix: Sequence[Mapping[str, object]],
        recompute: frozenset[object],
    ) -> None:
        experiment_id = body.get("experiment_id")
        if "artifact_evidence" in recompute:
            references: list[dict[str, object]] = []
            for event in prefix:
                if event.get("event_type") != "ARTIFACT_RECORDED":
                    continue
                payload = _mapping(event.get("payload"), "artifact payload")
                if not json_canonical_equal(payload.get("experiment_id"), experiment_id):
                    continue
                references.append(
                    {
                        "artifact_id": payload.get("artifact_id"),
                        "artifact_digest": payload.get("digest"),
                        "event_id": event.get("event_id"),
                        "event_hash": event.get("hash"),
                    }
                )
            references.sort(key=lambda item: (str(item["artifact_id"]), str(item["event_id"])))
            body["artifact_evidence"] = references
        if "terminal_evidence" in recompute:
            terminal = next(
                (
                    event
                    for event in reversed(prefix)
                    if event.get("event_type")
                    in {"EXPERIMENT_TERMINATED", "EXPERIMENT_STATUS_CHANGED"}
                    and json_canonical_equal(
                        _mapping(event.get("payload"), "terminal payload").get("experiment_id"),
                        experiment_id,
                    )
                    and _is_terminal_status(
                        _mapping(event.get("payload"), "terminal payload").get("status")
                    )
                ),
                None,
            )
            if terminal is not None:
                body["terminal_evidence"] = {
                    "experiment_id": experiment_id,
                    "event_id": terminal.get("event_id"),
                    "event_hash": terminal.get("hash"),
                }

    def _rehash(
        self,
        history: list[dict[str, object]],
        recompute: frozenset[object],
    ) -> list[dict[str, object]]:
        if "artifact_record_identity" in recompute:
            self._recompute_artifact_identities(history)
        previous_hash: str | None = None
        prefix: list[dict[str, object]] = []
        for sequence, event in enumerate(history, start=1):
            event["sequence"] = sequence
            event["prev_hash"] = previous_hash
            if event.get("event_type") == "research.experiment_diagnosed.v1":
                payload = cast(
                    dict[str, object],
                    _mapping(event.get("payload"), "diagnosis event payload"),
                )
                body_raw = payload.get("diagnosis")
                if isinstance(body_raw, dict):
                    self._rebind_diagnosis_evidence(body_raw, prefix, recompute)
                    if "diagnosis_digest" in recompute:
                        payload["diagnosis_digest"] = _public_digest(body_raw)
                    if "diagnosis_id" in recompute:
                        payload["diagnosis_id"] = _stable_id(
                            "diagnosis",
                            self.project_id,
                            payload.get("diagnosis_digest"),
                        )
            unsigned = dict(event)
            unsigned.pop("hash", None)
            event["hash"] = canonical_event_digest(unsigned)
            previous_hash = cast(str, event["hash"])
            prefix.append(event)
        return history

    def materialize(
        self,
        operation: object,
        inputs: Mapping[str, object],
    ) -> list[dict[str, object]] | Mapping[str, object]:
        history = self._base_history(inputs)
        mutations = _list(inputs.get("mutations"), "negative mutations")
        if operation == "mutate_diagnosis_event":
            diagnosis_index = self._diagnosis_indexes(history)[0]
            payload = _mapping(history[diagnosis_index].get("payload"), "diagnosis payload")
            for raw_mutation in mutations:
                _apply_corpus_patch(payload, _mapping(raw_mutation, "mutation"))
        elif operation == "mutate_history":
            for raw_mutation in mutations:
                self._mutate_history(history, _mapping(raw_mutation, "mutation"))
        elif operation == "mutate_diagnosis_submission":
            diagnosis_index = self._diagnosis_indexes(history)[0]
            payload = cast(
                dict[str, object],
                _mapping(history[diagnosis_index].get("payload"), "diagnosis payload"),
            )
            for raw_mutation in mutations:
                mutation = _mapping(raw_mutation, "mutation")
                if mutation.get("op") != "replace_raw_json_string":
                    raise ValueError("submission mutation must be a raw JSON string replacement")
                token = _text(mutation.get("json_string_token"), "raw JSON string token")
                decoded = json.loads(token)
                replacement = {"op": "replace", "path": mutation.get("path"), "value": decoded}
                _apply_corpus_patch(payload, replacement)
            return _mapping(payload.get("diagnosis"), "diagnosis")
        else:
            raise ValueError(f"unsupported negative operation: {operation!r}")
        recompute = frozenset(_list(inputs.get("recompute", []), "recompute directives"))
        return self._rehash(history, recompute)


class M1DOracle:
    """A registry of independent observers over the exact frozen fixture bytes."""

    _SUPPORTING_FIXTURES = (
        "contract",
        "terminal_corpus",
        "diagnosis_valid",
        "diagnosis_negative_matrix",
        "transition_matrix",
        "frontier_oracle",
        "compatibility_oracle",
    )

    def __init__(
        self,
        fixture_root: Path,
        *,
        project_root: Path,
        work_root: Path | None = None,
    ) -> None:
        self.fixture_root = fixture_root.resolve()
        self.project_root = project_root.resolve()
        self.work_root = None if work_root is None else work_root.resolve()
        manifest = strict_load_json(self.fixture_root / "manifest.json")
        manifest_object = _mapping(manifest, "manifest")
        self._fixture_links = _mapping(manifest_object.get("fixtures"), "manifest fixtures")
        bindings = _list(manifest_object.get("cases"), "manifest bindings")
        display_ids = tuple(_mapping(binding, "manifest binding").get("id") for binding in bindings)
        self._manifest_binding_count = len(bindings)
        self._manifest_duplicate_id_count = len(display_ids) - len(set(display_ids))
        self._cache: dict[str, Mapping[str, object]] = {}

    def _fixture(self, name: object) -> Mapping[str, object]:
        fixture_name = _text(name, "fixture name")
        if fixture_name not in self._cache:
            path = (self.fixture_root / fixture_name).resolve()
            if path.parent != self.fixture_root:
                raise AssertionError(f"fixture escapes frozen root: {fixture_name}")
            self._cache[fixture_name] = _mapping(strict_load_json(path), fixture_name)
        return self._cache[fixture_name]

    def registry(self) -> OperationRegistry:
        registry = OperationRegistry()
        operations: tuple[tuple[str, Observation], ...] = (
            ("verify_fixture_integrity", self.verify_fixture_integrity),
            ("parse_m1d_contract", self.parse_m1d_contract),
            ("verify_terminal_corpus", self.verify_terminal_corpus),
            ("verify_canonical_diagnoses", self.verify_canonical_diagnoses),
            ("verify_terminal_exactness_attacks", self.verify_terminal_exactness_attacks),
            ("execute_diagnosis_negative_matrix", self.execute_diagnosis_negative_matrix),
            (
                "observe_all_valid_diagnosis_dispositions",
                self.observe_all_valid_diagnosis_dispositions,
            ),
            ("verify_generic_terminal_normalization", self.verify_generic_terminal_normalization),
            ("verify_nonterminal_status_boundary", self.verify_nonterminal_status_boundary),
            ("execute_counting_taxonomy", self.execute_counting_taxonomy),
            ("reduce_literal_full_states", self.reduce_literal_full_states),
            ("execute_all_transition_gates", self.execute_all_transition_gates),
            (
                "verify_stop_reason_and_precedence_matrix",
                self.verify_stop_reason_and_precedence_matrix,
            ),
            ("verify_successor_generation_matrix", self.verify_successor_generation_matrix),
            (
                "execute_replication_parent_gate_matrix",
                self.execute_replication_parent_gate_matrix,
            ),
            ("verify_class_state_partitions", self.verify_class_state_partitions),
            ("verify_class_closure_origin", self.verify_class_closure_origin),
            ("verify_retry_frontiers", self.verify_retry_frontiers),
            ("derive_semantic_frontier", self.derive_semantic_frontier),
            ("execute_frontier_exclusions", self.execute_frontier_exclusions),
            (
                "execute_frontier_consumption_counterfactuals",
                self.execute_frontier_consumption_counterfactuals,
            ),
            ("execute_frontier_stop_cases", self.execute_frontier_stop_cases),
            ("execute_all_literal_races", self.execute_all_literal_races),
            ("verify_race_serialization_groups", self.verify_race_serialization_groups),
            ("verify_race_label_invariance", self.verify_race_label_invariance),
            ("verify_race_operation_coverage", self.verify_race_operation_coverage),
            (
                "verify_m1d_compatibility_authority",
                self.verify_m1d_compatibility_authority,
            ),
            ("verify_regression_floor", self.verify_regression_floor),
        )
        for name, observer in operations:
            registry.register(name, observer)
        return registry

    def verify_fixture_integrity(self, inputs: Mapping[str, object]) -> dict[str, object]:
        relative = _text(inputs.get("fixture_directory"), "fixture directory")
        target = (self.fixture_root / relative).resolve()
        if target != self.fixture_root:
            raise AssertionError("fixture integrity may inspect only the frozen v3 root")
        matches = 0
        for link in self._SUPPORTING_FIXTURES:
            fixture_name = _text(self._fixture_links.get(link), link)
            digest = _text(self._fixture_links.get(f"{link}_raw_sha256"), f"{link} digest")
            path = self.fixture_root / fixture_name
            strict_load_json(path)
            matches += int(sha256_bytes(path.read_bytes()) == digest)
        return {
            "supporting_fixture_count": len(self._SUPPORTING_FIXTURES),
            "total_json_files_including_manifest": len(tuple(target.glob("*.json"))),
            "raw_digest_matches": matches,
            "manifest_cases": self._manifest_binding_count,
            "duplicate_case_ids": self._manifest_duplicate_id_count,
        }

    def parse_m1d_contract(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from research_os.science import EvaluationSeal, StudyContract, plan_generation_open

        contract = StudyContract.from_mapping(self._fixture(inputs.get("fixture")))
        terminal_name = _text(self._fixture_links.get("terminal_corpus"), "terminal fixture")
        terminal_fixture = self._fixture(terminal_name)
        first_record = _mapping(
            _list(terminal_fixture.get("records"), "terminal records")[0], "terminal record"
        )
        history = _list(first_record.get("canonical_history"), "canonical history")
        generation_payload = next(
            _mapping(_mapping(event, "event").get("payload"), "generation payload")
            for event in history
            if _mapping(event, "event").get("event_type") == "research.study_generation_opened.v1"
        )
        seal = EvaluationSeal.from_mapping(
            _mapping(generation_payload.get("evaluation_seal"), "evaluation seal")
        )
        plan = plan_generation_open(
            [],
            project_id=_text(self._fixture_links.get("project_id"), "project id"),
            contract=contract,
            evaluation_seal=seal,
        )
        return {
            "schema_version": contract.schema_version,
            "study_contract_digest": contract.digest,
            "generation_id": plan.generation_id,
            "evaluation_scope_ids": [scope.id for scope in contract.evaluation_scopes],
            "hypothesis_class_ids": [item.id for item in contract.hypothesis_classes],
            "max_active_branches": contract.frontier.max_active_branches,
        }

    def verify_terminal_corpus(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from research_os.artifacts.catalog import ArtifactRecord
        from research_os.contracts import GateEvaluation, ResultEnvelope, TerminalStatus
        from research_os.policy import Decision
        from research_os.science import reduce_scientific_state

        fixture = self._fixture(inputs.get("fixture"))
        project_id = _text(fixture.get("project_id"), "project id")
        records = _list(fixture.get("records"), "terminal records")
        parser_acceptances = 0
        verifier_acceptances = 0
        artifact_acceptances = 0
        result_round_trips = 0
        decision_round_trips = 0
        gate_round_trips = 0
        feasible = 0
        pending_matches = 0
        canonical_generic = 0
        alias_generic = 0
        retryable_generic = 0
        nonretryable_generic = 0
        nonterminal_controls = 0
        null_primary_fallback = 0
        for raw_record in records:
            record = _mapping(raw_record, "terminal record")
            history = _list(record.get("canonical_history"), "canonical history")
            events = _event_objects(history, project_id)
            assert _event_hashes_independent(history)
            parser_acceptances += len(events)
            verifier_acceptances += 1
            terminal = _terminal_event(history)
            expected_pending = (
                []
                if terminal is None
                else [
                    _text(
                        _mapping(terminal.get("payload"), "terminal payload").get("experiment_id"),
                        "terminal experiment id",
                    )
                ]
            )
            observed_pending = list(
                reduce_scientific_state(
                    events,
                    project_id=project_id,
                ).pending_diagnosis_experiment_ids
            )
            pending_matches += int(json_canonical_equal(observed_pending, expected_pending))
            if terminal is None:
                nonterminal_controls += 1
                last = _mapping(history[-1], "nonterminal event")
                if _is_generic_status_event(last):
                    primary_sources = [
                        _mapping(event, "event").get("payload")
                        for event in history
                        if _mapping(event, "event").get("event_type")
                        in {"EXPERIMENT_REGISTERED", "BASELINE_RECORDED"}
                    ]
                    null_primary_fallback += int(
                        all(
                            not isinstance(source, Mapping) or not source.get("primary_metric")
                            for source in primary_sources
                        )
                    )
            else:
                payload = _mapping(terminal.get("payload"), "terminal payload")
                feasible += 1
                generic = _is_generic_status_event(terminal)
                raw_status = payload.get("status")
                if generic:
                    normalized = _canonical_status(raw_status)
                    if normalized == raw_status:
                        canonical_generic += 1
                    else:
                        alias_generic += 1
                    if _kernel_retryable(payload):
                        retryable_generic += 1
                    else:
                        nonretryable_generic += 1
                observation = _observation_from_history(history)
                if observation is not None and observation["primary_metric"] is None:
                    null_primary_fallback += 1
                decision = payload.get("decision")
                if isinstance(decision, Mapping):
                    assert decision.get("authorized_action") is None
                    gates = _list(decision.get("gate_evaluations"), "gate evaluations")
                    parsed_gates = tuple(
                        GateEvaluation.from_mapping(_mapping(raw_gate, "gate"))
                        for raw_gate in gates
                    )
                    parsed_decision = Decision(
                        status=TerminalStatus(_text(decision.get("status"), "status")),
                        reason_code=_text(decision.get("reason_code"), "reason code"),
                        primary_metric=_text(decision.get("primary_metric"), "primary metric"),
                        candidate_value=cast(float | None, decision.get("candidate_value")),
                        baseline_value=cast(float | None, decision.get("baseline_value")),
                        improvement=cast(float | None, decision.get("improvement")),
                        promotion_margin=cast(float | None, decision.get("promotion_margin")),
                        gate_evaluations=parsed_gates,
                        authorized_action=None,
                    )
                    assert json_canonical_equal(parsed_decision.to_dict(), dict(decision))
                    decision_round_trips += 1
                    for raw_gate in gates:
                        gate = GateEvaluation.from_mapping(_mapping(raw_gate, "gate"))
                        assert json_canonical_equal(
                            gate.to_dict(),
                            dict(_mapping(raw_gate, "gate")),
                        )
                        gate_round_trips += 1
                result = payload.get("result")
                if isinstance(result, Mapping):
                    parsed_result = ResultEnvelope.from_mapping(result)
                    assert json_canonical_equal(parsed_result.to_dict(), dict(result))
                    result_round_trips += 1
            for payload in _event_payloads(history, "ARTIFACT_RECORDED"):
                raw_artifact = dict(payload)
                authority = raw_artifact.pop("authorized_action")
                assert authority is None
                artifact = ArtifactRecord.from_mapping(raw_artifact)
                assert json_canonical_equal(artifact.to_dict(), raw_artifact)
                artifact_acceptances += 1
        return {
            "records": len(records),
            "canonical_histories": len(records),
            "event_parser_acceptances": parser_acceptances,
            "history_verifier_acceptances": verifier_acceptances,
            "artifact_record_parser_acceptances": artifact_acceptances,
            "result_envelope_round_trips": result_round_trips,
            "decision_round_trips": decision_round_trips,
            "gate_evaluation_round_trips": gate_round_trips,
            "product_feasible_terminal_payloads": feasible,
            "pending_diagnosis_row_matches": pending_matches,
            "generic_canonical_terminal_records": canonical_generic,
            "generic_alias_terminal_records": alias_generic,
            "generic_retryable_terminal_records": retryable_generic,
            "generic_nonretryable_terminal_records": nonretryable_generic,
            "nonterminal_status_changed_controls": nonterminal_controls,
            "generic_null_primary_metric_fallback_histories": null_primary_fallback,
            "authorized_action_non_null": _authorized_action_non_null(fixture),
        }

    @staticmethod
    def _joined_diagnosis_rows(
        terminal_fixture: Mapping[str, object],
        diagnosis_fixture: Mapping[str, object],
    ) -> list[tuple[Mapping[str, object], Mapping[str, object]]]:
        terminal_records = _list(terminal_fixture.get("records"), "terminal records")
        by_identity: dict[object, Mapping[str, object]] = {}
        for raw_record in terminal_records:
            record = _mapping(raw_record, "terminal record")
            identity = record.get("id")
            if identity in by_identity:
                raise AssertionError("duplicate terminal-record identity")
            by_identity[identity] = record
        joined: list[tuple[Mapping[str, object], Mapping[str, object]]] = []
        for raw_case in _list(diagnosis_fixture.get("cases"), "diagnosis cases"):
            diagnosis_case = _mapping(raw_case, "diagnosis case")
            reference = diagnosis_case.get("terminal_record_id")
            try:
                terminal_record = by_identity[reference]
            except KeyError as exc:
                raise AssertionError("diagnosis references an unknown terminal record") from exc
            joined.append((terminal_record, diagnosis_case))
        return joined

    @staticmethod
    def _diagnosis_payload(diagnosis_case: Mapping[str, object]) -> Mapping[str, object]:
        event = _mapping(diagnosis_case.get("diagnosis_event"), "diagnosis event")
        return _mapping(event.get("payload"), "diagnosis event payload")

    @staticmethod
    def _diagnosis_body(diagnosis_case: Mapping[str, object]) -> Mapping[str, object]:
        payload = M1DOracle._diagnosis_payload(diagnosis_case)
        return _mapping(payload.get("diagnosis"), "diagnosis")

    @staticmethod
    def _decision_matches_observation(
        terminal_payload: Mapping[str, object],
        observation: Mapping[str, object],
    ) -> bool:
        decision = terminal_payload.get("decision")
        if not isinstance(decision, Mapping) or set(observation) != _DIAGNOSIS_OBSERVATION_KEYS:
            return False
        bound_fields = {
            "terminal_status": decision.get("status"),
            "reason_code": decision.get("reason_code"),
            "primary_metric": decision.get("primary_metric"),
            "candidate_value": decision.get("candidate_value"),
            "baseline_value": decision.get("baseline_value"),
            "improvement": decision.get("improvement"),
            "promotion_margin": decision.get("promotion_margin"),
            "gate_evaluations": decision.get("gate_evaluations"),
        }
        return json_canonical_equal(
            {key: observation.get(key) for key in bound_fields},
            bound_fields,
        )

    @staticmethod
    def _qualifying_gates(observation: Mapping[str, object]) -> bool:
        gates = observation.get("gate_evaluations")
        if not isinstance(gates, list):
            return False
        for raw_gate in gates:
            gate = _mapping(raw_gate, "gate evaluation")
            if gate.get("role") in {"hard", "support"} and gate.get("passed") is not True:
                return False
        return True

    @classmethod
    def _disposition(
        cls,
        terminal_record: Mapping[str, object],
        diagnosis_case: Mapping[str, object],
    ) -> dict[str, object]:
        history = _list(terminal_record.get("canonical_history"), "canonical history")
        terminal = _terminal_event(history)
        if terminal is None:
            raise AssertionError("a canonical Diagnosis must bind terminal evidence")
        terminal_payload = _mapping(terminal.get("payload"), "terminal payload")
        body = cls._diagnosis_body(diagnosis_case)
        observation = _mapping(body.get("observation"), "diagnosis observation")
        status = _canonical_status(terminal_payload.get("status"))
        reason = terminal_payload.get("reason_code")
        decision_matches = cls._decision_matches_observation(terminal_payload, observation)
        verified = terminal_payload.get("verified") is True
        gates_pass = cls._qualifying_gates(observation)
        no_primary_error = "error" not in terminal_payload
        margin = observation.get("promotion_margin")
        supported = (
            status == "VALIDATED"
            and reason == "PRIMARY_METRIC_IMPROVED"
            and verified
            and decision_matches
            and isinstance(margin, (int, float))
            and not isinstance(margin, bool)
            and margin > 0
            and gates_pass
            and no_primary_error
        )
        conclusive = (
            status == "REJECTED"
            and reason == "NO_MEANINGFUL_IMPROVEMENT"
            and verified
            and decision_matches
            and isinstance(margin, (int, float))
            and not isinstance(margin, bool)
            and margin <= 0
            and gates_pass
            and no_primary_error
        )
        retryable = observation.get("retryable") is True and _kernel_retryable(terminal_payload)
        if supported:
            kernel_disposition = "supported"
        elif conclusive:
            kernel_disposition = "conclusive_rejection"
        elif status == "REJECTED":
            kernel_disposition = "nonconclusive_rejection"
        elif retryable:
            kernel_disposition = "retryable_operational"
        else:
            kernel_disposition = "inconclusive"
        payload = cls._diagnosis_payload(diagnosis_case)
        return {
            "diagnosis_id": payload.get("diagnosis_id"),
            "kernel_disposition": kernel_disposition,
            "conclusive_rejection": conclusive,
            "semantic_supported": supported,
            "retry_eligible": retryable,
        }

    def verify_canonical_diagnoses(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from research_os.science import Diagnosis, DiagnosisEventPayload, diagnosis_id

        terminal_fixture = self._fixture(inputs.get("terminal_fixture"))
        diagnosis_fixture = self._fixture(inputs.get("fixture"))
        project_id = _text(diagnosis_fixture.get("project_id"), "project id")
        joined = self._joined_diagnosis_rows(terminal_fixture, diagnosis_fixture)
        parser_acceptances = 0
        history_acceptances = 0
        feasible_bindings = 0
        diagnosis_ids: list[str] = []
        generic_bindings = 0
        generic_normalized = 0
        generic_retryable = 0
        generic_inconclusive = 0
        pending_cleared = 0
        generic_null_metric = 0
        generic_null_numeric = 0
        generic_empty_gates = 0
        for terminal_record, diagnosis_case in joined:
            history = _list(terminal_record.get("canonical_history"), "canonical history")
            diagnosis_event = _mapping(diagnosis_case.get("diagnosis_event"), "diagnosis event")
            extended = [*history, diagnosis_event]
            events = _event_objects(extended, project_id)
            assert _event_hashes_independent(extended)
            history_acceptances += 1
            payload_raw = _mapping(diagnosis_event.get("payload"), "diagnosis event payload")
            payload = DiagnosisEventPayload.from_mapping(payload_raw, project_id=project_id)
            assert json_canonical_equal(payload.to_dict(), dict(payload_raw))
            diagnosis = Diagnosis.from_mapping(payload_raw.get("diagnosis"))
            assert json_canonical_equal(
                diagnosis.to_dict(),
                payload.diagnosis.to_dict(),
            )
            assert diagnosis.digest == payload.diagnosis_digest
            assert diagnosis_id(project_id, diagnosis.digest) == payload.diagnosis_id
            parser_acceptances += 1
            feasible_bindings += 1
            diagnosis_ids.append(payload.diagnosis_id)

            terminal = _terminal_event(history)
            assert terminal is not None
            if _is_generic_status_event(terminal):
                generic_bindings += 1
                terminal_payload = _mapping(terminal.get("payload"), "terminal payload")
                observation = payload.diagnosis.observation.to_dict()
                generic_normalized += int(
                    observation["terminal_status"]
                    == _canonical_status(terminal_payload.get("status"))
                )
                disposition = self._disposition(terminal_record, diagnosis_case)
                generic_retryable += int(
                    disposition["kernel_disposition"] == "retryable_operational"
                )
                generic_inconclusive += int(disposition["kernel_disposition"] == "inconclusive")
                generic_null_metric += int(observation["primary_metric"] is None)
                numeric_keys = (
                    "candidate_value",
                    "baseline_value",
                    "improvement",
                    "promotion_margin",
                )
                generic_null_numeric += int(all(observation[key] is None for key in numeric_keys))
                generic_empty_gates += int(observation["gate_evaluations"] == [])

            from research_os.science import reduce_scientific_state

            before = reduce_scientific_state(events[:-1], project_id=project_id)
            after = reduce_scientific_state(events, project_id=project_id)
            experiment_id = payload.diagnosis.experiment_id
            pending_cleared += int(
                _is_generic_status_event(terminal)
                and experiment_id in before.pending_diagnosis_experiment_ids
                and experiment_id not in after.pending_diagnosis_experiment_ids
            )
        return {
            "cases": len(joined),
            "diagnosis_event_parser_acceptances": parser_acceptances,
            "extended_history_verifier_acceptances": history_acceptances,
            "product_feasible_terminal_bindings": feasible_bindings,
            "diagnosis_ids": diagnosis_ids,
            "generic_terminal_bindings": generic_bindings,
            "generic_normalized_status_observations": generic_normalized,
            "generic_retryable_dispositions": generic_retryable,
            "generic_inconclusive_dispositions": generic_inconclusive,
            "generic_pending_obligations_cleared": pending_cleared,
            "generic_null_primary_metric_observations": generic_null_metric,
            "generic_null_numeric_observations": generic_null_numeric,
            "generic_empty_gate_evaluation_observations": generic_empty_gates,
            "authorized_action_non_null": _authorized_action_non_null(diagnosis_fixture),
        }

    @staticmethod
    def _negative_rows(fixture: Mapping[str, object]) -> list[Mapping[str, object]]:
        return [
            _mapping(raw, "negative row") for raw in _list(fixture.get("cases"), "negative rows")
        ]

    @staticmethod
    def _row_mutations(row: Mapping[str, object]) -> list[Mapping[str, object]]:
        inputs = _mapping(row.get("input"), "negative input")
        return [
            _mapping(raw, "negative mutation")
            for raw in _list(inputs.get("mutations"), "negative mutations")
        ]

    def verify_terminal_exactness_attacks(self, inputs: Mapping[str, object]) -> dict[str, object]:
        fixture = self._fixture(inputs.get("fixture"))
        rows = self._negative_rows(fixture)

        def selected_terminal(mutation: Mapping[str, object]) -> bool:
            selector = mutation.get("event_selector")
            return (
                isinstance(selector, Mapping)
                and selector.get("event_type") == "EXPERIMENT_TERMINATED"
            )

        def mutation_path(mutation: Mapping[str, object]) -> str:
            value = mutation.get("path", "")
            return value if isinstance(value, str) else ""

        decision_exactness = 0
        decision_binding = 0
        observation_binding = 0
        artifact_ref_binding = 0
        terminal_authority = 0
        result_exactness = 0
        result_artifacts = 0
        same_digest_attributes = 0
        result_nested = 0
        artifact_records = 0
        gate_order = 0
        narrative_text = 0
        bool_integer = 0
        prehash_surrogates = 0
        for row in rows:
            mutations = self._row_mutations(row)
            paths = [mutation_path(mutation) for mutation in mutations]
            terminal_mutations = [mutation for mutation in mutations if selected_terminal(mutation)]
            decision_exactness += int(
                any(
                    mutation_path(mutation).startswith("/payload/decision/")
                    and (
                        mutation.get("op") in {"add", "remove"}
                        or mutation_path(mutation).endswith("/authorized_action")
                    )
                    for mutation in terminal_mutations
                )
            )
            decision_binding += int(
                any(
                    mutation_path(mutation)
                    in {
                        "/payload/decision/status",
                        "/payload/decision/reason_code",
                        "/payload/decision/primary_metric",
                    }
                    for mutation in terminal_mutations
                )
            )
            observation_binding += int(
                len(mutations) == 1
                and paths[0]
                in {
                    "/diagnosis/observation/terminal_status",
                    "/diagnosis/observation/reason_code",
                    "/diagnosis/observation/promotion_margin",
                    "/diagnosis/observation/primary_metric",
                    "/diagnosis/observation/candidate_value",
                    "/diagnosis/observation/baseline_value",
                    "/diagnosis/observation/improvement",
                    "/diagnosis/observation/verified",
                    "/diagnosis/observation/retryable",
                    "/diagnosis/observation/gate_evaluations",
                }
                and mutations[0].get("op") == "replace"
                and "diagnosis_digest"
                in _list(
                    _mapping(row.get("input"), "negative input").get("recompute", []),
                    "recompute directives",
                )
            )
            artifact_ref_binding += int(
                len(mutations) == 1
                and paths[0]
                in {
                    "/diagnosis/artifact_evidence/0/artifact_id",
                    "/diagnosis/artifact_evidence/0/artifact_digest",
                    "/diagnosis/artifact_evidence/0/event_id",
                    "/diagnosis/artifact_evidence/0/event_hash",
                }
                and mutations[0].get("op") == "replace"
            )
            terminal_authority += int("/payload/authorized_action" in paths)
            result_exactness += int(
                any(
                    mutation_path(mutation)
                    in {"/payload/result/diagnostics", "/payload/result/unknown"}
                    for mutation in terminal_mutations
                )
            )
            result_artifacts += int(
                any(
                    mutation_path(mutation).startswith("/payload/result")
                    for mutation in terminal_mutations
                )
            )
            same_digest_attributes += int(
                any(
                    mutation.get("op") == "replace"
                    and mutation_path(mutation)
                    in {
                        "/payload/result/artifacts/0/path",
                        "/payload/result/artifacts/0/size_bytes",
                        "/payload/result/artifacts/0/media_type",
                        "/payload/result/artifacts/0/retention",
                        "/payload/result/artifacts/0/sensitivity",
                    }
                    for mutation in terminal_mutations
                )
            )
            result_nested += int(
                any(
                    mutation.get("op") in {"add", "remove"}
                    and mutation_path(mutation)
                    in {
                        "/payload/result/artifacts/0/sensitivity",
                        "/payload/result/artifacts/0/unknown",
                    }
                    for mutation in terminal_mutations
                )
            )
            artifact_records += int(
                row.get("operation") == "mutate_history"
                and any(
                    not isinstance(mutation.get("event_selector"), Mapping)
                    and (
                        mutation.get("op") == "reassign_artifact_to_registered_decoy"
                        or mutation_path(mutation)
                        in {
                            "/storage_path",
                            "/project_id",
                            "/authorized_action",
                            "/unknown",
                            "/role",
                            "/media_type",
                            "/metadata/source",
                            "/metadata/retention",
                            "/metadata/sensitivity",
                        }
                    )
                    for mutation in mutations
                )
            )
            gate_order += int(
                any(
                    (
                        mutation_path(mutation) == "/diagnosis/observation/gate_evaluations"
                        and mutation.get("op") == "reverse"
                    )
                    or mutation_path(mutation).endswith("/gate_evaluations/1/id")
                    for mutation in mutations
                )
            )
            raw_submission = (
                _mapping(row.get("input"), "negative input").get("prehash_structural_validation")
                is True
            )
            noncanonical_narrative = any(
                mutation_path(mutation) in {"/diagnosis/interpretation", "/diagnosis/falsifier"}
                and isinstance(mutation.get("value"), str)
                and cast(str, mutation.get("value")).strip() != mutation.get("value")
                for mutation in mutations
            )
            narrative_text += int(raw_submission or noncanonical_narrative)
            prehash_surrogates += int(raw_submission)
            bool_integer += int(
                any(
                    (
                        mutation_path(mutation)
                        in {
                            "/diagnosis/observation/verified",
                            "/diagnosis/observation/retryable",
                            "/diagnosis/observation/gate_evaluations/1/passed",
                        }
                        and isinstance(mutation.get("value"), int)
                        and not isinstance(mutation.get("value"), bool)
                    )
                    or (
                        mutation_path(mutation)
                        in {
                            "/diagnosis/diagnosis_schema_version",
                            "/science_state_version",
                        }
                        and isinstance(mutation.get("value"), bool)
                    )
                    for mutation in mutations
                )
            )
        return {
            "decision_exactness_cases": decision_exactness,
            "decision_terminal_binding_cases": decision_binding,
            "observation_exact_binding_cases": observation_binding,
            "artifact_evidence_single_field_binding_cases": artifact_ref_binding,
            "terminal_authority_cases": terminal_authority,
            "result_envelope_exactness_cases": result_exactness,
            "result_artifact_attack_cases": result_artifacts,
            "same_digest_result_artifact_attribute_cases": same_digest_attributes,
            "result_artifact_nested_exactness_cases": result_nested,
            "artifact_record_attack_cases": artifact_records,
            "gate_order_attack_cases": gate_order,
            "narrative_text_exactness_cases": narrative_text,
            "bool_integer_boundary_cases": bool_integer,
            "prehash_surrogate_cases": prehash_surrogates,
            "structural_parser_boundary_cases": narrative_text + bool_integer,
        }

    def _verify_acceptance_controls(
        self,
        matrix: Mapping[str, object],
        materializer: DiagnosisNegativeMaterializer,
    ) -> int:
        from research_os.science import reduce_scientific_state

        accepted = 0
        for raw_control in _list(matrix.get("acceptance_controls"), "acceptance controls"):
            control = _mapping(raw_control, "acceptance control")
            inputs = _mapping(control.get("input"), "acceptance input")
            history = materializer.materialize(control.get("operation"), inputs)
            if not isinstance(history, list):
                raise AssertionError("acceptance control must materialize a canonical history")
            events = _event_objects(history, materializer.project_id)
            reduce_scientific_state(events, project_id=materializer.project_id)
            diagnosis_index = materializer._diagnosis_indexes(history)[-1]
            payload = _mapping(history[diagnosis_index].get("payload"), "diagnosis payload")
            body = _mapping(payload.get("diagnosis"), "diagnosis")
            mutation = _mapping(
                _list(inputs.get("mutations"), "acceptance mutations")[0],
                "acceptance mutation",
            )
            field_pointer = _text(mutation.get("path"), "acceptance mutation path")
            observed_text = _pointer_get(payload, field_pointer)
            if not isinstance(observed_text, str):
                raise AssertionError("UTF-8 acceptance control did not produce text")
            code_point = _text(mutation.get("code_point"), "UTF-8 recipe code point")
            repeat = mutation.get("repeat")
            suffix = mutation.get("suffix", "")
            if (
                len(code_point) != 1
                or isinstance(repeat, bool)
                or not isinstance(repeat, int)
                or repeat < 0
                or not isinstance(suffix, str)
            ):
                raise TypeError("invalid UTF-8 acceptance recipe")
            recipe_text = code_point * repeat + suffix
            assert observed_text == recipe_text
            assert len(observed_text.encode("utf-8")) == 16384
            assert payload.get("diagnosis_digest") == _public_digest(body)
            assert payload.get("diagnosis_id") == _stable_id(
                "diagnosis", materializer.project_id, payload.get("diagnosis_digest")
            )
            accepted += 1
        return accepted

    def _verify_service_idempotency_controls(
        self,
        matrix: Mapping[str, object],
        materializer: DiagnosisNegativeMaterializer,
    ) -> int:
        from research_os.kernel.events import EventLog
        from research_os.service import ResearchService

        if self.work_root is None:
            raise AssertionError("service idempotency observation requires a work root")
        verified = 0
        controls = _list(matrix.get("service_idempotency_controls"), "idempotency controls")
        for ordinal, raw_control in enumerate(controls):
            control = _mapping(raw_control, "idempotency control")
            inputs = _mapping(control.get("input"), "idempotency input")
            full_history = materializer._base_history(inputs)
            diagnosis_event = full_history[-1]
            prefix = full_history[:-1]
            path = self.work_root / "diagnosis-idempotency" / str(ordinal) / "events.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(
                b"".join(
                    json.dumps(
                        event,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=False,
                        allow_nan=False,
                    ).encode("utf-8")
                    + b"\n"
                    for event in prefix
                )
            )
            path.chmod(0o600)
            service = object.__new__(ResearchService)
            service.config = SimpleNamespace(project_id=materializer.project_id)
            service.event_log = EventLog(path, materializer.project_id)
            service._assert_config_unchanged = MethodType(lambda _self: None, service)
            service._sync = MethodType(lambda _self: None, service)
            payload = _mapping(diagnosis_event.get("payload"), "diagnosis event payload")
            body = _mapping(payload.get("diagnosis"), "diagnosis body")
            with (
                mock.patch(
                    "research_os.kernel.events.new_id",
                    return_value=diagnosis_event.get("event_id"),
                ),
                mock.patch(
                    "research_os.kernel.events.utc_now",
                    return_value=diagnosis_event.get("occurred_at"),
                ),
            ):
                first = ResearchService.record_diagnosis(service, body)
                second = ResearchService.record_diagnosis(service, body)
            persisted = [
                event
                for event in service.event_log.read()
                if event.event_type == "research.experiment_diagnosed.v1"
            ]
            assert first["appended_events"] == 1
            assert second["appended_events"] == 0
            assert len(persisted) == 1
            assert first["diagnosis_id"] == second["diagnosis_id"]
            assert first["diagnosis_id"] == payload.get("diagnosis_id")
            assert first["event_id"] == second["event_id"]
            assert first["event_id"] == diagnosis_event.get("event_id")
            assert first["event_hash"] == second["event_hash"]
            assert first["event_hash"] == diagnosis_event.get("hash")
            assert first["authorized_action"] is second["authorized_action"] is None
            verified += 1
        return verified

    def execute_diagnosis_negative_matrix(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from research_os.errors import ScientificStateError
        from research_os.science import Diagnosis

        from .transition_observer import execute_history_paths

        matrix = self._fixture(inputs.get("fixture"))
        terminal_fixture = self._fixture(inputs.get("terminal_fixture"))
        valid_fixture = self._fixture(inputs.get("valid_fixture"))
        materializer = DiagnosisNegativeMaterializer(
            matrix,
            terminal_fixture,
            valid_fixture,
        )
        rows = self._negative_rows(matrix)
        execution_path_count = len(_list(matrix.get("execution_paths"), "execution paths"))
        if self.work_root is None:
            raise AssertionError("negative path observation requires a work root")
        rejections = 0
        path_matches = 0
        materialized = 0
        materialized_events = 0
        surrogate_rejections = 0
        all_deltas_zero = True
        for ordinal, row in enumerate(rows):
            row_inputs = _mapping(row.get("input"), "negative input")
            history_or_body = materializer.materialize(row.get("operation"), row_inputs)
            row_matches = 0
            if isinstance(history_or_body, list):
                materialized += 1
                materialized_events += len(history_or_body)
                _event_objects(history_or_body, materializer.project_id)
                assert _event_hashes_independent(history_or_body)
                observed_paths = execute_history_paths(
                    history_or_body,
                    materializer.project_id,
                    self.work_root / "negative-paths" / str(ordinal),
                )
                path_rows = (
                    list(observed_paths.values())
                    if isinstance(observed_paths, Mapping)
                    else list(observed_paths)
                )
                if len(path_rows) != execution_path_count:
                    raise AssertionError("negative helper did not execute every declared path")
                reference = _mapping(path_rows[0], "negative reference path")
                if reference.get("accepted") is not False:
                    raise AssertionError("negative reference path accepted a forbidden row")
                if not isinstance(reference.get("error_code"), str):
                    raise AssertionError("negative reference path omitted an error code")
                for raw_path in path_rows:
                    path_result = _mapping(raw_path, "negative path result")
                    deltas = _mapping(path_result.get("deltas"), "negative path deltas")
                    same = (
                        path_result.get("accepted") is False
                        and path_result.get("error_code") == reference.get("error_code")
                        and json_canonical_equal(
                            path_result.get("error_path"), reference.get("error_path")
                        )
                        and json_canonical_equal(deltas, reference.get("deltas"))
                    )
                    row_matches += int(same)
                    all_deltas_zero = all_deltas_zero and all(
                        json_canonical_equal(value, 0) for value in deltas.values()
                    )
            else:
                reference_error: tuple[str, object] | None = None
                for _ in range(execution_path_count):
                    try:
                        Diagnosis.from_mapping(history_or_body)
                    except ScientificStateError as exc:
                        observed_error = (exc.code, exc.details.get("path"))
                        if reference_error is None:
                            reference_error = observed_error
                        same = json_canonical_equal(observed_error, reference_error)
                    else:
                        same = False
                    row_matches += int(same)
                surrogate_rejections += int(row_matches == execution_path_count)
            path_matches += row_matches
            rejections += int(row_matches == execution_path_count)
        acceptance_controls = self._verify_acceptance_controls(matrix, materializer)
        idempotency_controls = self._verify_service_idempotency_controls(matrix, materializer)
        precedence = sum(
            "precedence_transition" in _mapping(row.get("input"), "negative input") for row in rows
        )
        return {
            "cases": len(rows),
            "rejections": rejections,
            "execution_paths": execution_path_count,
            "path_matches": path_matches,
            "acceptance_controls": acceptance_controls,
            "service_idempotency_controls": idempotency_controls,
            "precedence_cases": precedence,
            "event_valid_materialized_mutations": materialized,
            "prehash_surrogate_rejections": surrogate_rejections,
            "materialized_event_envelopes": materialized_events,
            "all_declared_deltas_zero": all_deltas_zero,
        }

    def observe_all_valid_diagnosis_dispositions(
        self, inputs: Mapping[str, object]
    ) -> dict[str, object]:
        diagnosis_fixture = self._fixture(inputs.get("fixture"))
        terminal_fixture = self._fixture(diagnosis_fixture.get("terminal_fixture"))
        rows = [
            self._disposition(terminal_record, diagnosis_case)
            for terminal_record, diagnosis_case in self._joined_diagnosis_rows(
                terminal_fixture, diagnosis_fixture
            )
        ]
        histogram = Counter(row["kernel_disposition"] for row in rows)
        return {
            "cases": len(rows),
            "supported": histogram["supported"],
            "conclusive_rejection": histogram["conclusive_rejection"],
            "nonconclusive_rejection": histogram["nonconclusive_rejection"],
            "retryable_operational": histogram["retryable_operational"],
            "inconclusive": histogram["inconclusive"],
            "semantic_supported": sum(row["semantic_supported"] is True for row in rows),
            "retry_eligible": sum(row["retry_eligible"] is True for row in rows),
            "exact_rows_digest": _public_digest(rows),
        }

    def verify_generic_terminal_normalization(
        self, inputs: Mapping[str, object]
    ) -> dict[str, object]:
        from research_os.science import normalize_terminal_status, reduce_scientific_state

        declared_fields = tuple(
            _text(value, "normalization row field")
            for value in _list(
                inputs.get("normalization_row_fields"),
                "normalization row fields",
            )
        )
        if declared_fields != _NORMALIZATION_ROW_FIELDS:
            raise AssertionError("normalization row field declaration changed")
        if inputs.get("normalization_row_order") != _NORMALIZATION_ROW_ORDER:
            raise AssertionError("normalization row order declaration changed")
        terminal_fixture = self._fixture(inputs.get("terminal_fixture"))
        diagnosis_fixture = self._fixture(inputs.get("diagnosis_fixture"))
        project_id = _text(diagnosis_fixture.get("project_id"), "project id")
        joined = self._joined_diagnosis_rows(terminal_fixture, diagnosis_fixture)
        normalization_rows: list[dict[str, object]] = []
        canonical_statuses: set[str] = set()
        alias_count = 0
        retryable = 0
        nonretryable = 0
        for terminal_record, diagnosis_case in joined:
            history = _list(terminal_record.get("canonical_history"), "canonical history")
            terminal = _terminal_event(history)
            assert terminal is not None
            if not _is_generic_status_event(terminal):
                continue
            terminal_payload = _mapping(terminal.get("payload"), "terminal payload")
            body = self._diagnosis_body(diagnosis_case)
            observation = _mapping(body.get("observation"), "diagnosis observation")
            raw_status = terminal_payload.get("status")
            canonical = _canonical_status(raw_status)
            assert normalize_terminal_status(_text(raw_status, "raw terminal status")) == canonical
            state = reduce_scientific_state(
                _event_objects(history, project_id),
                project_id=project_id,
            )
            registration = state.registration(_text(body.get("experiment_id"), "experiment id"))
            if registration is None:
                raise AssertionError("generic terminal registration is absent")
            assert registration.terminal_status == canonical
            assert registration.retryable is (observation.get("retryable") is True)
            if raw_status == canonical:
                canonical_statuses.add(canonical)
            else:
                alias_count += 1
            is_retryable = observation.get("retryable") is True
            retryable += int(is_retryable)
            nonretryable += int(not is_retryable)
            row = {
                "experiment_id": body.get("experiment_id"),
                "terminal_event_id": terminal.get("event_id"),
                "terminal_event_hash": terminal.get("hash"),
                "raw_terminal_status": raw_status,
                "canonical_terminal_status": canonical,
                "reason_code": observation.get("reason_code"),
                "verified": observation.get("verified"),
                "retryable": observation.get("retryable"),
                "primary_metric": observation.get("primary_metric"),
                "candidate_value": observation.get("candidate_value"),
                "baseline_value": observation.get("baseline_value"),
                "improvement": observation.get("improvement"),
                "promotion_margin": observation.get("promotion_margin"),
                "gate_evaluations": observation.get("gate_evaluations"),
            }
            if tuple(row) != _NORMALIZATION_ROW_FIELDS:
                raise AssertionError("normalization evidence row domain changed")
            normalization_rows.append(row)
        terminal_records = _list(terminal_fixture.get("records"), "terminal records")
        generic_and_control = sum(
            _mapping(
                _list(_mapping(record, "record").get("canonical_history"), "history")[-1], "event"
            ).get("event_type")
            == "EXPERIMENT_STATUS_CHANGED"
            for record in terminal_records
        )
        return {
            "generic_and_nonterminal_histories": generic_and_control,
            "generic_terminal_histories": len(normalization_rows),
            "canonical_terminal_statuses": len(canonical_statuses),
            "alias_terminal_statuses": alias_count,
            "retryable_terminal_statuses": retryable,
            "nonretryable_terminal_statuses": nonretryable,
            "diagnosed_terminal_histories": len(normalization_rows),
            "normalization_rows_digest": _public_digest(normalization_rows),
        }

    def verify_nonterminal_status_boundary(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from research_os.science import reduce_scientific_state

        fixture = self._fixture(inputs.get("fixture"))
        project_id = _text(fixture.get("project_id"), "project id")
        controls: list[tuple[Mapping[str, object], object]] = []
        for raw_record in _list(fixture.get("records"), "terminal records"):
            record = _mapping(raw_record, "terminal record")
            history = _list(record.get("canonical_history"), "canonical history")
            terminal = _terminal_event(history)
            if terminal is None:
                controls.append(
                    (
                        record,
                        reduce_scientific_state(
                            _event_objects(history, project_id), project_id=project_id
                        ),
                    )
                )
        if len(controls) != 1:
            raise AssertionError("the terminal corpus must contain one nonterminal control")
        record, state = controls[0]
        history = _list(record.get("canonical_history"), "canonical history")
        last = _mapping(history[-1], "status event")
        payload = _mapping(last.get("payload"), "status payload")
        observation = {
            "raw_status": payload.get("status"),
            "canonical_status": _canonical_status(payload.get("status")),
            "reason_code": "STATUS_CHANGED",
            "verified": False,
            "retry_eligible": False,
            "primary_metric": None,
            "diagnosis_required": False,
        }
        return {
            "nonterminal_status_changed_controls": len(controls),
            "diagnosis_required": len(state.pending_diagnosis_experiment_ids),
            "pending_diagnosis_ids": len(state.pending_diagnosis_experiment_ids),
            "normalized_status": observation["canonical_status"],
            "reason_code": observation["reason_code"],
            "exact_control_digest": _public_digest(observation),
        }

    def execute_counting_taxonomy(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .transition_observer import execute_counting_taxonomy

        return execute_counting_taxonomy(inputs, self._fixture)

    def reduce_literal_full_states(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .transition_observer import reduce_literal_full_states

        return reduce_literal_full_states(inputs, self._fixture)

    def execute_all_transition_gates(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .transition_observer import execute_all_transition_gates

        return execute_all_transition_gates(inputs, self._fixture)

    def verify_stop_reason_and_precedence_matrix(
        self, inputs: Mapping[str, object]
    ) -> dict[str, object]:
        from .transition_observer import verify_stop_reason_and_precedence_matrix

        return verify_stop_reason_and_precedence_matrix(inputs, self._fixture)

    def verify_successor_generation_matrix(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .transition_observer import verify_successor_generation_matrix

        return verify_successor_generation_matrix(inputs, self._fixture)

    def execute_replication_parent_gate_matrix(
        self, inputs: Mapping[str, object]
    ) -> dict[str, object]:
        from .transition_observer import execute_replication_parent_gate_matrix

        return execute_replication_parent_gate_matrix(inputs, self._fixture)

    def verify_class_state_partitions(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .transition_observer import verify_class_state_partitions

        return verify_class_state_partitions(inputs, self._fixture)

    def verify_class_closure_origin(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .transition_observer import verify_class_closure_origin

        return verify_class_closure_origin(inputs, self._fixture)

    def verify_retry_frontiers(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .frontier_observer import verify_retry_frontiers

        return verify_retry_frontiers(inputs, self._fixture)

    def derive_semantic_frontier(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .frontier_observer import derive_semantic_frontier

        return derive_semantic_frontier(inputs, self._fixture)

    def execute_frontier_exclusions(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .frontier_observer import execute_frontier_exclusions

        return execute_frontier_exclusions(inputs, self._fixture)

    def execute_frontier_consumption_counterfactuals(
        self, inputs: Mapping[str, object]
    ) -> dict[str, object]:
        from .frontier_observer import execute_frontier_consumption_counterfactuals

        return execute_frontier_consumption_counterfactuals(inputs, self._fixture)

    def execute_frontier_stop_cases(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .frontier_observer import execute_frontier_stop_cases

        return execute_frontier_stop_cases(inputs, self._fixture)

    def execute_all_literal_races(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .transition_observer import execute_all_literal_races

        return execute_all_literal_races(inputs, self._fixture)

    def verify_race_serialization_groups(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .transition_observer import verify_race_serialization_groups

        return verify_race_serialization_groups(inputs, self._fixture)

    def verify_race_label_invariance(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .transition_observer import verify_race_label_invariance

        return verify_race_label_invariance(inputs, self._fixture)

    def verify_race_operation_coverage(self, inputs: Mapping[str, object]) -> dict[str, object]:
        from .transition_observer import verify_race_operation_coverage

        return verify_race_operation_coverage(inputs, self._fixture)

    @staticmethod
    def _unique_operation_input(
        manifest: Mapping[str, object], operation: str
    ) -> Mapping[str, object]:
        matches = [
            _mapping(binding, "legacy manifest binding")
            for binding in _list(manifest.get("cases"), "legacy manifest bindings")
            if _mapping(binding, "legacy manifest binding").get("operation") == operation
        ]
        if len(matches) != 1:
            raise AssertionError(f"legacy operation must be unique: {operation}")
        return _mapping(matches[0].get("input"), "legacy operation input")

    def _authority_surfaces(
        self,
        compatibility: Mapping[str, object],
    ) -> dict[str, Mapping[str, object]]:
        from research_os.cli import main as cli_main
        from research_os.science import (
            Diagnosis,
            DiagnosisEventPayload,
            reduce_scientific_state,
        )
        from research_os.service import ResearchService

        from .transition_observer import _service_harness

        if self.work_root is None:
            raise AssertionError("authority observation requires a work root")
        terminal_name = _text(self._fixture_links.get("terminal_corpus"), "terminal fixture")
        diagnosis_name = _text(self._fixture_links.get("diagnosis_valid"), "Diagnosis fixture")
        terminal_fixture = self._fixture(terminal_name)
        diagnosis_fixture = self._fixture(diagnosis_name)
        joined = self._joined_diagnosis_rows(terminal_fixture, diagnosis_fixture)
        candidates = [
            (record, diagnosis_case)
            for record, diagnosis_case in joined
            if cast(
                Mapping[str, object],
                _terminal_event(record.get("canonical_history")),
            ).get("event_type")
            == "EXPERIMENT_TERMINATED"
            and not _event_payloads(
                record.get("canonical_history"),
                "ARTIFACT_RECORDED",
            )
        ]
        if not candidates:
            raise AssertionError("authority observer requires an artifact-free terminal Diagnosis")
        terminal_record, diagnosis_case = candidates[0]
        raw_history = _list(terminal_record.get("canonical_history"), "canonical history")
        event_payload = self._diagnosis_payload(diagnosis_case)
        body = self._diagnosis_body(diagnosis_case)
        diagnosis_input = Diagnosis.from_mapping(body).to_dict()
        diagnosis_event = DiagnosisEventPayload.from_mapping(
            event_payload,
            project_id=_text(diagnosis_fixture.get("project_id"), "project id"),
        ).to_dict()

        project = self.work_root / "m1d-authority-project"
        if project.exists():
            shutil.rmtree(project)
        shutil.copytree(self.project_root / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        config_path = project / ".research-os" / "project.toml"
        config_text = config_path.read_text(encoding="utf-8")
        config_path.write_text(
            config_text.replace(
                'id = "toy-optimization"',
                f'id = "{diagnosis_fixture.get("project_id")}"',
            ),
            encoding="utf-8",
        )
        service = ResearchService(project)
        for raw_event in raw_history:
            event = _mapping(raw_event, "authority seed event")
            appended = service.event_log.append(
                _text(event.get("event_type"), "event type"),
                _mapping(event.get("payload"), "event payload"),
                event_id=_text(event.get("event_id"), "event id"),
                occurred_at=_text(event.get("occurred_at"), "event time"),
            )
            assert json_canonical_equal(appended.to_dict(), dict(event))
        diagnosis_service_result = service.record_diagnosis(body)
        diagnosis_path = project / "diagnosis.json"
        diagnosis_path.write_text(
            json.dumps(body, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = cli_main(["--project", str(project), "diagnose", str(diagnosis_path)])
        if exit_code != 0 or stderr.getvalue():
            raise AssertionError(stderr.getvalue() or "diagnose CLI failed")
        diagnosis_cli_result = _mapping(json.loads(stdout.getvalue()), "CLI result")
        events = service.event_log.read()
        state = reduce_scientific_state(
            events,
            project_id=_text(diagnosis_fixture.get("project_id"), "project id"),
        )
        if not state.class_states:
            raise AssertionError("authority observer requires at least one ClassState")
        study_status = service.study_status()
        replay = _service_harness(
            service.event_log,
            service.projection,
            _text(diagnosis_fixture.get("project_id"), "project id"),
        ).replay()
        rebuilt_events = service.projection.rebuild(service.event_log)
        projection_rebuild = {
            "events_replayed": rebuilt_events,
            "authorized_action": None,
        }
        surfaces: dict[str, Mapping[str, object]] = {
            "diagnosis_input": diagnosis_input,
            "diagnosis_event": diagnosis_event,
            "diagnosis_service_result": diagnosis_service_result,
            "diagnosis_cli_result": diagnosis_cli_result,
            "study_status": study_status,
            "class_state": state.class_states[0].body_dict(),
            "semantic_frontier": state.semantic_frontier,
            "retry_frontier": state.retry_frontier,
            "replay": replay,
            "projection_rebuild": projection_rebuild,
        }
        declared = _list(compatibility.get("public_surfaces"), "public surfaces")
        if set(surfaces) != set(declared):
            raise AssertionError("authority surface contract does not match live surfaces")
        return surfaces

    def _legacy_compatibility_key_counts(
        self,
        legacy_input: Mapping[str, object],
        legacy_oracle: Any,
    ) -> dict[str, int]:
        from research_os.science import reduce_scientific_state

        if self.work_root is None:
            raise AssertionError("legacy compatibility observation requires a work root")
        generation_name = _text(
            legacy_input.get("m1b_generation_events"),
            "M1-B generation events",
        )
        generation_path = legacy_oracle.FIXTURE_ROOT / generation_name
        generation_bytes = generation_path.read_bytes()
        root = self.work_root / "compatibility" / "legacy-key-observation"
        if root.exists():
            shutil.rmtree(root)
        service = legacy_oracle._fixed_v1_service(root, generation_bytes)
        events = service.event_log.read()
        # The frozen generation fixture has its own legacy project identity.
        project_id = _text(events[0].project_id, "legacy project id")
        science_state = reduce_scientific_state(events, project_id=project_id).to_dict()
        service.projection.rebuild(service.event_log)
        projection = {
            "status": service.projection.project_status(project_id),
            "lineage": service.projection.lineage(project_id),
        }
        study_status = service.study_status()
        replay = service.replay()
        # This observer certifies the frozen Context v2 compatibility surface.
        # Keep the version explicit now that the released default is v3.
        context = service.agent_context(schema_version=2)
        return {
            "legacy_science_state_new_keys": _recursive_key_occurrences(
                science_state, _M1D_ADDITIVE_PUBLIC_KEYS
            ),
            "legacy_projection_new_keys": _recursive_key_occurrences(
                projection, _M1D_ADDITIVE_PUBLIC_KEYS
            ),
            "legacy_study_status_new_keys": _recursive_key_occurrences(
                study_status, _M1D_ADDITIVE_PUBLIC_KEYS
            ),
            "legacy_replay_new_keys": _recursive_key_occurrences(replay, _M1D_ADDITIVE_PUBLIC_KEYS),
            "context_v2_new_keys": len(
                (set(context) - _CONTEXT_V2_TOP_LEVEL_KEYS) - _M1D_ADDITIVE_PUBLIC_KEYS
            )
            + _recursive_key_occurrences(context, _M1D_ADDITIVE_PUBLIC_KEYS),
        }

    def _branch_conclusion_v1_new_keys(self) -> int:
        from research_os.service import ResearchService
        from tests.test_agent_scientific_control import (
            _configure_agent_files,
            _passing_review,
        )

        if self.work_root is None:
            raise AssertionError("branch compatibility observation requires a work root")
        root = self.work_root / "compatibility" / "branch-conclusion-v1"
        if root.exists():
            shutil.rmtree(root)
        project = root / "project"
        shutil.copytree(self.project_root / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        _configure_agent_files(project)
        service = ResearchService(project)
        subject = service.evaluator_review_subject()
        service.certify_evaluator(
            _passing_review(
                root / "review.json",
                subject_digest=_text(subject.get("digest"), "review subject digest"),
            )
        )
        service.baseline()
        context = service.agent_context(limit=10)
        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text('{"x":0.0}\n', encoding="utf-8")
        run = service.run_once(
            inbox,
            context_token=_text(
                _mapping(context.get("snapshot"), "agent context snapshot").get("context_token"),
                "agent context token",
            ),
            graph_action="explore",
            scientific_change="class-a: preserve branch conclusion v1",
        )
        context = service.agent_context(limit=10)
        conclusion_path = root / "conclusion.json"
        conclusion_path.write_text(
            json.dumps(
                {
                    "branch_experiment_ids": [run["experiment_id"]],
                    "hypothesis_class": "class-a",
                    "failure_signature": "primary metric below promotion threshold",
                    "conclusion": "This mechanism is not supported by this node.",
                    "confidence": "inconclusive",
                    "next_step": "explore",
                },
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        finding = service.conclude_branch(
            conclusion_path,
            context_token=_text(
                _mapping(context.get("snapshot"), "agent context snapshot").get("context_token"),
                "agent context token",
            ),
        )
        content = _mapping(finding.get("content"), "branch conclusion content")
        evidence = _list(finding.get("evidence"), "branch conclusion evidence")
        metadata = _mapping(finding.get("metadata"), "branch conclusion metadata")
        evidence_keys = set()
        for raw_item in evidence:
            evidence_keys.update(_mapping(raw_item, "branch evidence"))
        return (
            len((set(finding) - _BRANCH_CONCLUSION_V1_KEYS) - _M1D_ADDITIVE_PUBLIC_KEYS)
            + len(set(content) - _BRANCH_CONCLUSION_V1_CONTENT_KEYS)
            + len(evidence_keys - _BRANCH_CONCLUSION_V1_EVIDENCE_KEYS)
            + len(set(metadata) - _BRANCH_CONCLUSION_V1_METADATA_KEYS)
            + _recursive_key_occurrences(finding, _M1D_ADDITIVE_PUBLIC_KEYS)
        )

    def _v2_compatibility_deltas(self, legacy_oracle: Any) -> dict[str, int]:
        from research_os.kernel.ids import new_experiment_id
        from research_os.science import Proposal, StudyContract, proposal_id

        if self.work_root is None:
            raise AssertionError("v2 compatibility observation requires a work root")
        v2_root = legacy_oracle.FIXTURE_ROOT
        raw_contract = _mapping(
            strict_load_json(v2_root / "m1c-contract.json"),
            "M1-C contract",
        )
        raw_proposal = _mapping(
            strict_load_json(v2_root / "m1c-proposal-explore.json"),
            "M1-C Proposal",
        )
        contract = StudyContract.from_mapping(raw_contract)
        proposal = Proposal.from_mapping(raw_proposal)
        root = self.work_root / "compatibility" / "v2-old-fields"
        if root.exists():
            shutil.rmtree(root)
        with legacy_oracle._m1c_service_project(root) as project:
            project.service.baseline(evaluation_scope_id="development")
            run = project.service.run_once(
                project.candidate_path,
                proposal=project.proposal_explore_path,
            )
            registration = _mapping(
                project.registration(_text(run.get("experiment_id"), "experiment id")),
                "M1-C registration",
            )
            state = project.science_state().to_dict()
            baseline_event = next(
                event
                for event in project.service.event_log.read()
                if event.event_type == "BASELINE_RECORDED"
                and event.payload.get("evaluation_scope_id") == "development"
            )

        observed_proposal = _mapping(registration.get("proposal"), "registered Proposal")
        proposal_changes = _mapping_difference_count(raw_proposal, observed_proposal)

        raw_scopes = [
            _mapping(value, "raw evaluation scope")
            for value in _list(raw_contract.get("evaluation_scopes"), "evaluation scopes")
        ]
        parsed_contract = contract.to_dict()
        parsed_scopes = [
            _mapping(value, "parsed evaluation scope")
            for value in _list(
                parsed_contract.get("evaluation_scopes"),
                "parsed evaluation scopes",
            )
        ]
        scope_changes = abs(len(raw_scopes) - len(parsed_scopes)) + sum(
            _mapping_difference_count(raw, observed)
            for raw, observed in zip(raw_scopes, parsed_scopes, strict=False)
        )
        development_scope = next(scope for scope in raw_scopes if scope.get("id") == "development")
        scope_changes += _mapping_difference_count(
            development_scope,
            _mapping(
                baseline_event.payload.get("evaluation_scope"),
                "baseline evaluation scope",
            ),
        )
        scope_changes += int(
            not json_canonical_equal(
                registration.get("evaluation_scope_id"), development_scope.get("id")
            )
        )

        project_id = _text(legacy_oracle._fixtures().get("project_id"), "M1-C project id")
        expected_proposal_id = proposal_id(project_id, proposal.digest)
        expected_experiment_id = new_experiment_id(
            project_id,
            _text(registration.get("candidate_digest"), "candidate digest"),
            compatibility_digest=_text(
                registration.get("compatibility_digest"),
                "compatibility digest",
            ),
            generation_id=_text(registration.get("generation_id"), "generation id"),
            evaluation_scope_id=_text(
                registration.get("evaluation_scope_id"),
                "evaluation scope id",
            ),
            attempt=_integer(registration.get("attempt"), "attempt"),
        )
        identity_changes = sum(
            (
                not json_canonical_equal(
                    registration.get("generation_id"), raw_proposal.get("generation_id")
                ),
                not json_canonical_equal(
                    registration.get("candidate_digest"), raw_proposal.get("candidate_digest")
                ),
                not json_canonical_equal(registration.get("proposal_digest"), proposal.digest),
                not json_canonical_equal(registration.get("proposal_id"), expected_proposal_id),
                not json_canonical_equal(registration.get("experiment_id"), expected_experiment_id),
            )
        )

        raw_budget = _mapping(raw_contract.get("budget"), "raw budget")
        observed_budget = _mapping(state.get("budget"), "observed budget")
        budget_changes = _v2_budget_difference_count(raw_budget, observed_budget)
        return {
            "v2_old_proposal_fields_changed": proposal_changes,
            "v2_old_scope_fields_changed": scope_changes,
            "v2_old_identity_fields_changed": identity_changes,
            "v2_old_budget_fields_changed": budget_changes,
        }

    def verify_m1d_compatibility_authority(self, inputs: Mapping[str, object]) -> dict[str, object]:
        if self.work_root is None:
            raise AssertionError("compatibility observation requires a work root")
        compatibility = self._fixture(inputs.get("fixture"))
        frozen = _mapping(compatibility.get("frozen_inputs"), "frozen inputs")
        for path_key, digest_key in (
            ("m1b_manifest", "m1b_manifest_raw_sha256"),
            ("legacy_v1_events", "legacy_v1_events_raw_sha256"),
            ("legacy_v1_projection", "legacy_v1_projection_raw_sha256"),
            ("m1c_manifest", "m1c_manifest_raw_sha256"),
            ("m1c_transition_matrix", "m1c_transition_matrix_raw_sha256"),
        ):
            relative = _text(frozen.get(path_key), path_key)
            path = (self.fixture_root / relative).resolve()
            if not path.is_relative_to(self.fixture_root.parent):
                raise AssertionError("compatibility input escapes the frozen fixture tree")
            if sha256_bytes(path.read_bytes()) != frozen.get(digest_key):
                raise AssertionError(f"frozen compatibility input changed: {path_key}")

        m1b_manifest = _mapping(
            strict_load_json(
                (self.fixture_root / _text(frozen.get("m1b_manifest"), "M1-B manifest")).resolve()
            ),
            "M1-B manifest",
        )
        m1c_manifest = _mapping(
            strict_load_json(
                (self.fixture_root / _text(frozen.get("m1c_manifest"), "M1-C manifest")).resolve()
            ),
            "M1-C manifest",
        )
        if sorted_compact_digest(m1c_manifest) != frozen.get("m1c_manifest_sorted_compact_sha256"):
            raise AssertionError("frozen M1-C public digest changed")

        from tests import test_m1c_manifest_oracle as legacy_oracle

        transition_input = self._unique_operation_input(
            m1c_manifest,
            "execute_transition_negative_matrix",
        )
        transition_root = self.work_root / "compatibility" / "transition"
        transition_root.mkdir(parents=True, exist_ok=True)
        transition = legacy_oracle._observe_transition_negatives(
            transition_input,
            transition_root,
        )
        legacy_input = self._unique_operation_input(m1c_manifest, "verify_legacy_parity")
        legacy_root = self.work_root / "compatibility" / "legacy"
        legacy_root.mkdir(parents=True, exist_ok=True)
        legacy = legacy_oracle._observe_legacy_parity(
            legacy_input,
            legacy_root,
        )
        m1c_cases = _list(m1c_manifest.get("cases"), "M1-C manifest bindings")
        m1c_operations = {
            _text(_mapping(binding, "M1-C binding").get("operation"), "operation")
            for binding in m1c_cases
        }
        if (
            legacy_oracle._registry(self.work_root / "compatibility" / "registry").names
            != m1c_operations
        ):
            raise AssertionError("M1-C executable registry coverage changed")

        m1c_exact_matches = _m1c_exact_case_count(len(m1c_cases))
        legacy_key_counts = self._legacy_compatibility_key_counts(
            legacy_input,
            legacy_oracle,
        )
        branch_conclusion_new_keys = self._branch_conclusion_v1_new_keys()
        v2_deltas = self._v2_compatibility_deltas(legacy_oracle)

        surfaces = self._authority_surfaces(compatibility)
        recursive_authorities = [
            authority
            for surface in surfaces.values()
            for authority in recursive_key_values(surface, "authorized_action")
        ]
        legacy_exact = legacy.get("m1b_manifest_exact_matches")
        transition_cases = transition.get("cases")
        transition_exact = transition.get("case_rejections")
        direct_matches = transition.get("direct_replay_path_matches")
        if not all(
            isinstance(value, int)
            for value in (legacy_exact, transition_cases, transition_exact, direct_matches)
        ):
            raise AssertionError("legacy compatibility observer returned invalid counts")
        return {
            "m1b_manifest_cases": len(_list(m1b_manifest.get("cases"), "M1-B cases")),
            "m1b_manifest_exact_matches": legacy_exact,
            "m1c_manifest_cases": len(m1c_cases),
            "m1c_manifest_exact_matches": m1c_exact_matches,
            "m1c_transition_cases": transition_cases,
            "m1c_transition_case_rejections": transition_exact,
            "m1c_direct_replay_path_matches": direct_matches,
            "legacy_event_bytes_preserved_after_replay": legacy.get(
                "m1b_event_bytes_preserved_after_replay"
            ),
            "legacy_event_head_preserved_after_replay": legacy.get(
                "m1b_event_head_preserved_after_replay"
            ),
            "legacy_science_state_new_keys": legacy_key_counts["legacy_science_state_new_keys"],
            "legacy_projection_new_keys": legacy_key_counts["legacy_projection_new_keys"],
            "legacy_study_status_new_keys": legacy_key_counts["legacy_study_status_new_keys"],
            "legacy_replay_new_keys": legacy_key_counts["legacy_replay_new_keys"],
            "context_v2_new_keys": legacy_key_counts["context_v2_new_keys"],
            "branch_conclusion_v1_new_keys": branch_conclusion_new_keys,
            "legacy_typed_inference_count": legacy.get("typed_key_occurrences"),
            "v2_old_proposal_fields_changed": v2_deltas["v2_old_proposal_fields_changed"],
            "v2_old_scope_fields_changed": v2_deltas["v2_old_scope_fields_changed"],
            "v2_old_identity_fields_changed": v2_deltas["v2_old_identity_fields_changed"],
            "v2_old_budget_fields_changed": v2_deltas["v2_old_budget_fields_changed"],
            "authorized_action_surface_count": len(surfaces),
            "authorized_action_key_count": sum(
                "authorized_action" in surface for surface in surfaces.values()
            ),
            "authorized_action_recursive_non_null_count": sum(
                value is not None for value in recursive_authorities
            ),
        }

    def verify_regression_floor(self, inputs: Mapping[str, object]) -> dict[str, object]:
        global _REGRESSION_OBSERVATION

        requested_python = inputs.get("python")
        running_python = f"{sys.version_info.major}.{sys.version_info.minor}"
        if requested_python != running_python:
            raise AssertionError("regression observer is running under the wrong Python")
        if _REGRESSION_OBSERVATION is not None:
            return copy.deepcopy(_REGRESSION_OBSERVATION)
        status = (
            self.project_root
            / "docs"
            / "research-os-status"
            / "04-2026-08-10-m1-d-diagnosis-class-frontier.md"
        )
        tests_floor, subtests_floor = _approved_floor(
            status,
            r"구현 전 기준선:.*?(\d+) passed, (\d+) subtests passed",
        )
        observation = {
            "tests_minimum": tests_floor,
            "subtests_minimum": subtests_floor,
            "ruff": "PASS",
            "ty_src": "PASS",
            "diff_check": "PASS",
        }
        environment = dict(os.environ)
        existing_options = environment.get("PYTEST_ADDOPTS", "").strip()
        environment["PYTEST_ADDOPTS"] = " ".join(
            option
            for option in (
                existing_options,
                "--ignore=tests/test_m1d_manifest_oracle.py",
            )
            if option
        )
        pytest_run = _completed(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "tests",
                "--ignore=tests/test_m1d_manifest_oracle.py",
            ],
            environment=environment,
        )
        pytest_output = pytest_run.stdout + pytest_run.stderr
        tests_match = re.search(r"(?:^|\s)(\d+) passed", pytest_output)
        subtests_match = re.search(r"(\d+) subtests passed", pytest_output)
        if pytest_run.returncode != 0:
            raise AssertionError(pytest_output)
        if tests_match is None or subtests_match is None:
            raise AssertionError(pytest_output)
        if int(tests_match.group(1)) < tests_floor:
            raise AssertionError(pytest_output)
        if int(subtests_match.group(1)) < subtests_floor:
            raise AssertionError(pytest_output)

        ruff = _completed([sys.executable, "-m", "ruff", "check", "src", "tests"])
        ty = _completed(["uvx", "--offline", "ty", "check", "src"])
        diff = _completed(["git", "diff", "--check"])
        if ruff.returncode != 0:
            raise AssertionError(ruff.stdout + ruff.stderr)
        if ty.returncode != 0:
            raise AssertionError(ty.stdout + ty.stderr)
        if diff.returncode != 0:
            raise AssertionError(diff.stdout + diff.stderr)
        _REGRESSION_OBSERVATION = observation
        return copy.deepcopy(observation)
