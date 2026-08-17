"""Pure contracts and replay for opt-in controlled frame transitions.

The active scientific generation remains owned by :mod:`research_os.science`.
This module reduces a separate family of namespaced extension events and grants
no external action authority.  A policy-adopted chain can authorize only an
invocation of the existing generation-open writer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from research_os.contracts import sha256_json
from research_os.errors import ScientificStateError
from research_os.kernel._canonical import json_value, validate_timestamp
from research_os.kernel.events import Event
from research_os.kernel.ids import stable_id
from research_os.science.state import GENERATION_EVENT_TYPE, reduce_scientific_state

FRAME_GATE_EVENT_TYPE = "research.frame_transition_gate_decided.v1"
FRAME_INQUIRY_EVENT_TYPE = "research.frame_transition_inquiry_opened.v1"
FRAME_DECISION_EVENT_TYPE = "research.frame_transition_inquiry_decided.v1"
FRAME_PILOT_AUTH_EVENT_TYPE = "research.frame_transition_pilot_authorized.v1"
FRAME_PILOT_RESULT_EVENT_TYPE = "research.frame_transition_pilot_recorded.v1"
FRAME_ADOPTION_REVIEW_EVENT_TYPE = "research.frame_transition_adoption_reviewed.v1"
FRAME_POLICY_ADOPTION_EVENT_TYPE = "research.frame_transition_policy_adopted.v1"
FRAME_REVOCATION_EVENT_TYPE = "research.frame_transition_authority_revoked.v1"

POLICY_ADOPTION_POLICY_ID = "research-os.controlled-frame-transition.policy.v1"
POLICY_ADOPTION_POLICY = {
    "schema_version": 1,
    "policy_id": POLICY_ADOPTION_POLICY_ID,
    "required_pilot_outcome": "PASS_FOR_ADOPTION",
    "required_review_verdict": "APPROVE",
    "independent_review_required": True,
    "exact_activation_bindings_required": True,
    "external_authority_required": False,
}
POLICY_ADOPTION_POLICY_DIGEST = sha256_json(POLICY_ADOPTION_POLICY)

FRAME_EVENT_TYPES = frozenset(
    {
        FRAME_GATE_EVENT_TYPE,
        FRAME_INQUIRY_EVENT_TYPE,
        FRAME_DECISION_EVENT_TYPE,
        FRAME_PILOT_AUTH_EVENT_TYPE,
        FRAME_PILOT_RESULT_EVENT_TYPE,
        FRAME_ADOPTION_REVIEW_EVENT_TYPE,
        FRAME_POLICY_ADOPTION_EVENT_TYPE,
        FRAME_REVOCATION_EVENT_TYPE,
    }
)

FRAME_SCHEMA_VERSION = 1
JUMP_CLASSES = frozenset({"J0", "J1", "J2", "J3", "AMBIGUOUS_MATERIAL"})
INQUIRY_OUTCOMES = frozenset({"ABSTAIN", "REJECT", "RECOMMEND_FOR_PILOT"})
PILOT_OUTCOMES = frozenset({"PASS_FOR_ADOPTION", "KILL_B1", "KILL_B2", "KILL_B3", "KILL_B4"})
GATE_OUTCOMES = frozenset({"GO", "NO_BUILD", "UNSTABLE_RUBRIC"})
PILOT_ARMS = ("llm_only", "llm_tools_memory", "llm_research_os")

_DIGEST_LENGTH = 64
_RECEIPT_GENERATED_KEYS = frozenset({"recorded_at", "receipt_digest"})

_GATE_INPUT_KEYS = frozenset(
    {
        "schema_version",
        "predecessor_generation_id",
        "compatibility_digest",
        "corpus_manifest_digest",
        "provider_revision",
        "privacy_policy_digest",
        "retention_policy_digest",
        "rubric_digest",
        "label_owner_id",
        "review_owner_id",
        "independent_reviewer_id",
        "sample_count",
        "actual_output_count",
        "recurrent_j2_j3_count",
        "recurrence_threshold",
        "rubric_stable",
        "evidence_digest",
        "authorized_action",
    }
)
_INQUIRY_INPUT_KEYS = frozenset(
    {
        "schema_version",
        "gate_receipt_digest",
        "maker_id",
        "claimed_jump_class",
        "changed_pointers",
        "material_change",
        "exhaustion_signals",
        "rivals",
        "discriminator",
        "authorized_action",
    }
)
_DECISION_INPUT_KEYS = frozenset(
    {
        "schema_version",
        "inquiry_id",
        "maker_id",
        "outcome",
        "rationale",
        "evidence_digest",
        "candidate",
        "pilot_plan",
        "authorized_action",
    }
)
_PILOT_AUTH_INPUT_KEYS = frozenset(
    {
        "schema_version",
        "inquiry_id",
        "authorizer_id",
        "authority",
        "candidate_digest",
        "pilot_plan_digest",
        "expires_at",
        "evidence_digest",
        "authorized_action",
    }
)
_PILOT_RESULT_INPUT_KEYS = frozenset(
    {
        "schema_version",
        "inquiry_id",
        "evaluator_id",
        "authorization_receipt_digest",
        "arm_results",
        "privacy_breach",
        "invariant_regression",
        "evidence_digest",
        "authorized_action",
    }
)
_ADOPTION_REVIEW_INPUT_KEYS = frozenset(
    {
        "schema_version",
        "inquiry_id",
        "reviewer_id",
        "verdict",
        "candidate_digest",
        "change_digest",
        "coverage_digest",
        "pilot_receipt_digest",
        "tree_digest",
        "predecessor_generation_id",
        "successor_contract_digest",
        "successor_compatibility_digest",
        "expires_at",
        "evidence_digest",
        "authorized_action",
    }
)
_POLICY_ADOPTION_INPUT_KEYS = frozenset(
    {
        "schema_version",
        "inquiry_id",
        "authorized_action",
    }
)
_REVOCATION_INPUT_KEYS = frozenset(
    {
        "schema_version",
        "inquiry_id",
        "revoker_id",
        "target_receipt_digest",
        "reason",
        "authorized_action",
    }
)

_SIGNAL_KEYS = frozenset(
    {
        "signal_id",
        "kind",
        "evidence_digest",
        "lane",
        "source_generation_id",
        "source_compatibility_digest",
    }
)
_SIGNAL_KINDS = frozenset(
    {"repeated_failure", "unresolved_anomaly", "assumption_conflict", "class_closure"}
)
_RIVAL_KEYS = frozenset(
    {
        "rival_id",
        "label",
        "assumptions",
        "mechanism",
        "predictions",
        "falsifiers",
        "uncertainty",
    }
)
_DISCRIMINATOR_KEYS = frozenset({"discriminator_id", "procedure", "outcome_rule", "plan_digest"})
_CANDIDATE_KEYS = frozenset(
    {"candidate_id", "candidate_digest", "change_digest", "coverage_digest", "isolation_digest"}
)
_PILOT_PLAN_KEYS = frozenset(
    {
        "pilot_plan_id",
        "task_digest",
        "provider_revision",
        "arms",
        "per_arm_call_limit",
        "per_arm_token_limit",
        "per_arm_elapsed_milliseconds_limit",
        "per_arm_cost_microunits_limit",
        "primary_metric",
        "higher_is_better",
        "minimum_effect_microunits",
        "max_critical_false_promotions",
        "privacy_policy_digest",
        "retention_policy_digest",
        "teardown_policy",
    }
)
_ARM_RESULT_KEYS = frozenset(
    {
        "arm",
        "score_microunits",
        "calls",
        "tokens",
        "elapsed_milliseconds",
        "cost_microunits",
        "critical_false_promotions",
    }
)

_EVENT_ID_KEYS = {
    FRAME_GATE_EVENT_TYPE: "gate_receipt_id",
    FRAME_INQUIRY_EVENT_TYPE: "inquiry_id",
    FRAME_DECISION_EVENT_TYPE: "decision_receipt_id",
    FRAME_PILOT_AUTH_EVENT_TYPE: "pilot_authorization_id",
    FRAME_PILOT_RESULT_EVENT_TYPE: "pilot_receipt_id",
    FRAME_ADOPTION_REVIEW_EVENT_TYPE: "adoption_review_id",
    FRAME_POLICY_ADOPTION_EVENT_TYPE: "policy_adoption_id",
    FRAME_REVOCATION_EVENT_TYPE: "revocation_id",
}


def _error(code: str, message: str, **details: object) -> ScientificStateError:
    return ScientificStateError(code, message, details=details)


def _object(
    value: Any,
    keys: frozenset[str],
    *,
    path: str,
    code: str = "FRAME_TRANSITION_INVALID",
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(code, f"{path} must be an object", path=path)
    observed = set(value)
    if observed != keys:
        raise _error(
            code,
            f"{path} must have exact fields",
            path=path,
            missing_fields=sorted(keys - observed),
            unknown_fields=sorted(observed - keys),
        )
    try:
        converted = json_value(value, path=path)
    except (TypeError, ValueError) as exc:
        raise _error(code, str(exc), path=path) from exc
    if not isinstance(converted, dict):  # pragma: no cover - guarded above
        raise _error(code, f"{path} must be an object", path=path)
    return converted


def _json_object_copy(value: Mapping[str, Any], *, path: str) -> dict[str, Any]:
    converted = json_value(value, path=path)
    if not isinstance(converted, dict):  # pragma: no cover - mapping guarantees object
        raise TypeError(f"{path} must be an object")
    return converted


def _same_typed_json(left: Any, right: Any) -> bool:
    """Compare JSON values without Python's bool/int or int/float aliases."""

    if isinstance(left, Mapping) and isinstance(right, Mapping):
        return set(left) == set(right) and all(
            _same_typed_json(left[key], right[key]) for key in left
        )
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(
            _same_typed_json(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return type(left) is type(right) and left == right


def _text(value: Any, *, path: str, code: str = "FRAME_TRANSITION_INVALID") -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise _error(code, f"{path} must be trimmed non-empty text", path=path)
    return value


def _digest(value: Any, *, path: str, code: str = "FRAME_TRANSITION_INVALID") -> str:
    text = _text(value, path=path, code=code)
    if len(text) != _DIGEST_LENGTH or any(ch not in "0123456789abcdef" for ch in text):
        raise _error(code, f"{path} must be a lowercase SHA-256 digest", path=path)
    return text


def _integer(
    value: Any,
    *,
    path: str,
    minimum: int | None = 0,
    code: str = "FRAME_TRANSITION_INVALID",
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _error(code, f"{path} must be an integer", path=path)
    if minimum is not None and value < minimum:
        raise _error(code, f"{path} must be at least {minimum}", path=path)
    return value


def _boolean(value: Any, *, path: str, code: str = "FRAME_TRANSITION_INVALID") -> bool:
    if not isinstance(value, bool):
        raise _error(code, f"{path} must be a boolean", path=path)
    return value


def _array(value: Any, *, path: str, minimum: int = 1) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _error("FRAME_TRANSITION_INVALID", f"{path} must be an array", path=path)
    result = list(value)
    if len(result) < minimum:
        raise _error(
            "FRAME_TRANSITION_INVALID",
            f"{path} must contain at least {minimum} items",
            path=path,
        )
    return result


def _text_array(value: Any, *, path: str, minimum: int = 1) -> list[str]:
    return [
        _text(item, path=f"{path}[{index}]")
        for index, item in enumerate(_array(value, path=path, minimum=minimum))
    ]


def _literal_null_authority(raw: Mapping[str, Any], *, path: str = "$.authorized_action") -> None:
    if raw.get("authorized_action") is not None:
        raise _error(
            "FRAME_TRANSITION_AUTHORITY_INVALID",
            "authorized_action must be literal null",
            path=path,
        )


def _schema(raw: Mapping[str, Any]) -> None:
    if raw.get("schema_version") != FRAME_SCHEMA_VERSION or isinstance(
        raw.get("schema_version"), bool
    ):
        raise _error(
            "FRAME_TRANSITION_SCHEMA_INVALID",
            "schema_version must be literal 1",
            path="$.schema_version",
        )
    _literal_null_authority(raw)


def _timestamp(value: Any, *, path: str) -> str:
    try:
        return validate_timestamp(value, field=path)
    except ValueError as exc:
        raise _error("FRAME_TRANSITION_TIME_INVALID", str(exc), path=path) from exc


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("z", "+00:00").replace("Z", "+00:00"))


def _require_later(expires_at: str, recorded_at: str, *, path: str = "$.expires_at") -> None:
    if _instant(expires_at) <= _instant(recorded_at):
        raise _error(
            "FRAME_TRANSITION_AUTHORITY_EXPIRED",
            "authority must expire after it is recorded",
            path=path,
        )


def _require_not_before(
    recorded_at: str,
    prior_recorded_at: str,
    *,
    path: str = "$.recorded_at",
) -> None:
    if _instant(recorded_at) < _instant(prior_recorded_at):
        raise _error(
            "FRAME_TRANSITION_TIME_INVALID",
            "a later lifecycle event cannot be backdated before its prerequisite",
            path=path,
            prerequisite_recorded_at=prior_recorded_at,
        )


def _expired(expires_at: str, as_of: str) -> bool:
    return _instant(expires_at) <= _instant(as_of)


def classify_frame_change(changed_pointers: Sequence[str]) -> str:
    """Classify exact JSON-pointer-like change surfaces, failing broad input closed."""

    pointers = _text_array(changed_pointers, path="$.changed_pointers")
    if len(pointers) != len(set(pointers)):
        raise _error(
            "FRAME_TRANSITION_CLASSIFICATION_INVALID",
            "changed pointers must be unique",
            path="$.changed_pointers",
        )
    semantic_segments = {
        "J3": {"objective", "evaluator", "evaluation", "metric", "metrics", "ontology"},
        "J2": {
            "candidate_schema",
            "schema",
            "representation",
            "class",
            "hypothesis_classes",
            "universe",
        },
        "J1": {"mechanism", "model", "feature", "features", "algorithm"},
        "J0": {"parameter", "parameters", "setting", "settings", "hyperparameters"},
    }
    semantic_substrings = {
        "J3": {"objective", "evaluator", "evaluation", "ontology"},
        "J2": {"representation", "schema", "universe"},
        "J1": {"mechanism", "model", "algorithm"},
        "J0": {"parameter", "setting", "hyperparameter"},
    }
    broad_inner_containers = {"parameters", "settings", "hyperparameters", "model", "features"}
    inner_leaf_exact = {
        "architecture",
        "alpha",
        "beta",
        "dropout",
        "estimator",
        "gamma",
        "kernel",
        "lambda",
        "regularization",
        "temperature",
    }
    inner_leaf_suffixes = (
        "_algorithm",
        "_architecture",
        "_count",
        "_decoder",
        "_depth",
        "_encoder",
        "_estimator",
        "_feature",
        "_features",
        "_fraction",
        "_kernel",
        "_limit",
        "_logging",
        "_mechanism",
        "_model",
        "_rate",
        "_seed",
        "_size",
        "_threshold",
        "_timeout",
        "_weight",
    )
    ranked = {"J0": 0, "J1": 1, "J2": 2, "J3": 3}
    observed: list[str] = []
    for index, pointer in enumerate(pointers):
        if not pointer.startswith("/") or pointer in {"/", "/*"} or "*" in pointer:
            if not pointer.startswith("/"):
                raise _error(
                    "FRAME_TRANSITION_CLASSIFICATION_INVALID",
                    "changed surfaces must use absolute JSON pointers",
                    path=f"$.changed_pointers[{index}]",
                )
            return "AMBIGUOUS_MATERIAL"
        raw_segments = pointer[1:].split("/")
        if any(
            "~" in segment
            and any(
                index + 1 >= len(segment) or segment[index + 1] not in "01"
                for index, character in enumerate(segment)
                if character == "~"
            )
            for segment in raw_segments
        ):
            raise _error(
                "FRAME_TRANSITION_CLASSIFICATION_INVALID",
                "changed surfaces must use valid RFC-6901 escapes",
                path=f"$.changed_pointers[{index}]",
            )
        segments = [segment.replace("~1", "/").replace("~0", "~") for segment in raw_segments]
        lowered_segments = [segment.lower() for segment in segments]
        if any(not segment or not segment.isascii() for segment in lowered_segments):
            return "AMBIGUOUS_MATERIAL"
        matches = {
            level
            for level, values in semantic_segments.items()
            if any(
                segment in values
                or any(
                    semantic_term in segment
                    for semantic_term in semantic_substrings[level]
                )
                for segment in lowered_segments
            )
        }
        if any(
            "metric" in segment
            and not segment.endswith(("_cache", "_display", "_format", "_log", "_logging"))
            for segment in lowered_segments
        ):
            matches.add("J3")
        if not matches:
            return "AMBIGUOUS_MATERIAL"
        highest = max(matches, key=ranked.__getitem__)
        if highest in {"J0", "J1"}:
            leaf = lowered_segments[-1]
            leaf_has_inner_semantics = any(
                leaf in semantic_segments[level]
                or any(term in leaf for term in semantic_substrings[level])
                for level in ("J0", "J1")
            )
            leaf_is_known_inner = (
                leaf_has_inner_semantics
                or leaf in inner_leaf_exact
                or leaf.endswith(inner_leaf_suffixes)
            )
            if (
                not leaf_is_known_inner
                or (len(lowered_segments) == 1 and leaf in broad_inner_containers)
            ):
                return "AMBIGUOUS_MATERIAL"
        observed.append(highest)
    return max(observed, key=ranked.__getitem__)


def controlled_change_reason(inquiry_id: str, policy_adoption_digest: str) -> str:
    inquiry = _text(inquiry_id, path="$.inquiry_id")
    digest = _digest(policy_adoption_digest, path="$.policy_adoption_digest")
    return f"controlled-frame-transition:{inquiry}:{digest}"


@dataclass(frozen=True, slots=True)
class FrameTransitionPlan:
    event_type: str
    payload: Mapping[str, Any]
    receipt_id: str
    receipt_digest: str
    append_required: bool
    existing_event_id: str | None = None


@dataclass(frozen=True, slots=True)
class FrameTransitionState:
    project_id: str
    active_generation_id: str | None
    active_compatibility_digest: str | None
    active_contract_digest: str | None
    gates: tuple[Mapping[str, Any], ...]
    inquiries: tuple[Mapping[str, Any], ...]
    revoked_receipt_digests: frozenset[str]

    @property
    def has_records(self) -> bool:
        return bool(self.gates or self.inquiries)

    def gate_by_digest(self, receipt_digest: str) -> dict[str, Any] | None:
        for gate in self.gates:
            if gate.get("receipt_digest") == receipt_digest:
                return dict(gate)
        return None

    def inquiry(self, inquiry_id: str) -> dict[str, Any] | None:
        for inquiry in self.inquiries:
            if inquiry.get("inquiry_id") == inquiry_id:
                return _json_object_copy(inquiry, path="$.inquiry")
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": FRAME_SCHEMA_VERSION,
            "project_id": self.project_id,
            "active_generation_id": self.active_generation_id,
            "active_compatibility_digest": self.active_compatibility_digest,
            "active_contract_digest": self.active_contract_digest,
            "gates": [json_value(item) for item in self.gates],
            "inquiries": [json_value(item) for item in self.inquiries],
            "revoked_receipt_digests": sorted(self.revoked_receipt_digests),
            "authorized_action": None,
        }


def _event_parts(
    event: Event | Mapping[str, Any], *, project_id: str
) -> tuple[str, Mapping[str, Any], str | None, str | None]:
    if isinstance(event, Event):
        if event.project_id != project_id:
            raise _error(
                "FRAME_TRANSITION_PROJECT_MISMATCH",
                "event belongs to another project",
                expected_project_id=project_id,
                observed_project_id=event.project_id,
            )
        return event.event_type, event.payload, event.occurred_at, event.event_id
    if not isinstance(event, Mapping):
        raise _error("FRAME_TRANSITION_EVENT_INVALID", "event must be an object")
    observed_project = event.get("project_id", project_id)
    if observed_project != project_id:
        raise _error(
            "FRAME_TRANSITION_PROJECT_MISMATCH",
            "event belongs to another project",
            expected_project_id=project_id,
            observed_project_id=observed_project,
        )
    event_type = event.get("event_type")
    payload = event.get("payload")
    if not isinstance(event_type, str) or not event_type.strip():
        raise _error("FRAME_TRANSITION_EVENT_INVALID", "event_type must be non-empty text")
    if not isinstance(payload, Mapping):
        raise _error("FRAME_TRANSITION_EVENT_INVALID", "event payload must be an object")
    occurred_at = event.get("occurred_at")
    if occurred_at is not None and not isinstance(occurred_at, str):
        raise _error("FRAME_TRANSITION_EVENT_INVALID", "occurred_at must be text")
    event_id = event.get("event_id")
    if event_id is not None and not isinstance(event_id, str):
        raise _error("FRAME_TRANSITION_EVENT_INVALID", "event_id must be text")
    return event_type, payload, occurred_at, event_id


def _receipt_payload(
    core: Mapping[str, Any],
    *,
    id_key: str,
    namespace: str,
    recorded_at: str,
) -> dict[str, Any]:
    clean_core = json_value(core)
    if not isinstance(clean_core, dict):  # pragma: no cover - caller contract
        raise TypeError("receipt core must be an object")
    core_digest = sha256_json(clean_core)
    receipt_id = stable_id(namespace, core_digest)
    body = {**clean_core, id_key: receipt_id, "recorded_at": recorded_at}
    return {**body, "receipt_digest": sha256_json(body)}


def _validate_receipt(
    payload: Mapping[str, Any],
    *,
    expected_keys: frozenset[str],
    id_key: str,
    namespace: str,
    occurred_at: str | None,
) -> dict[str, Any]:
    raw = _object(payload, expected_keys, path="$.payload")
    _schema(raw)
    recorded_at = _timestamp(raw["recorded_at"], path="$.payload.recorded_at")
    if occurred_at is None or recorded_at != occurred_at:
        raise _error(
            "FRAME_TRANSITION_TIME_INVALID",
            "payload recorded_at must equal the event occurred_at",
            path="$.payload.recorded_at",
        )
    observed_id = _text(raw[id_key], path=f"$.payload.{id_key}")
    observed_digest = _digest(raw["receipt_digest"], path="$.payload.receipt_digest")
    body = dict(raw)
    del body["receipt_digest"]
    if sha256_json(body) != observed_digest:
        raise _error(
            "FRAME_TRANSITION_RECEIPT_MISMATCH",
            "receipt digest does not bind the canonical payload",
            path="$.payload.receipt_digest",
        )
    core = dict(body)
    del core[id_key]
    del core["recorded_at"]
    expected_id = stable_id(namespace, sha256_json(core))
    if observed_id != expected_id:
        raise _error(
            "FRAME_TRANSITION_RECEIPT_MISMATCH",
            "receipt ID does not bind the canonical payload",
            path=f"$.payload.{id_key}",
        )
    return raw


_GATE_PAYLOAD_KEYS = frozenset(
    (
        *_GATE_INPUT_KEYS,
        "outcome",
        "policy_id",
        "policy_digest",
        "gate_receipt_id",
        "recorded_at",
        "receipt_digest",
    )
)
_INQUIRY_PAYLOAD_KEYS = frozenset(
    (
        *_INQUIRY_INPUT_KEYS,
        "jump_class",
        "predecessor_generation_id",
        "compatibility_digest",
        "policy_id",
        "policy_digest",
        "inquiry_id",
        "recorded_at",
        "receipt_digest",
    )
)
_DECISION_PAYLOAD_KEYS = frozenset(
    (
        *_DECISION_INPUT_KEYS,
        "pilot_plan_digest",
        "decision_receipt_id",
        "recorded_at",
        "receipt_digest",
    )
)
_PILOT_AUTH_PAYLOAD_KEYS = frozenset(
    (*_PILOT_AUTH_INPUT_KEYS, "pilot_authorization_id", "recorded_at", "receipt_digest")
)
_PILOT_RESULT_PAYLOAD_KEYS = frozenset(
    (
        *_PILOT_RESULT_INPUT_KEYS,
        "candidate_digest",
        "pilot_plan_digest",
        "outcome",
        "pilot_receipt_id",
        "recorded_at",
        "receipt_digest",
    )
)
_ADOPTION_REVIEW_PAYLOAD_KEYS = frozenset(
    (*_ADOPTION_REVIEW_INPUT_KEYS, "adoption_review_id", "recorded_at", "receipt_digest")
)
_POLICY_ADOPTION_PAYLOAD_KEYS = frozenset(
    (
        *_POLICY_ADOPTION_INPUT_KEYS,
        "decision",
        "policy_id",
        "policy_digest",
        "review_receipt_digest",
        "candidate_digest",
        "successor_contract_digest",
        "successor_compatibility_digest",
        "expires_at",
        "evidence_digest",
        "policy_adoption_id",
        "recorded_at",
        "receipt_digest",
    )
)
_REVOCATION_PAYLOAD_KEYS = frozenset(
    (*_REVOCATION_INPUT_KEYS, "revocation_id", "recorded_at", "receipt_digest")
)


def _validate_gate(raw: Mapping[str, Any]) -> dict[str, Any]:
    _schema(raw)
    _text(raw["predecessor_generation_id"], path="$.predecessor_generation_id")
    _digest(raw["compatibility_digest"], path="$.compatibility_digest")
    for key in (
        "corpus_manifest_digest",
        "privacy_policy_digest",
        "retention_policy_digest",
        "rubric_digest",
        "evidence_digest",
    ):
        _digest(raw[key], path=f"$.{key}")
    _text(raw["provider_revision"], path="$.provider_revision")
    owners = [
        _text(raw[key], path=f"$.{key}")
        for key in ("label_owner_id", "review_owner_id", "independent_reviewer_id")
    ]
    if owners[2] in owners[:2]:
        raise _error(
            "FRAME_TRANSITION_INDEPENDENCE_REQUIRED",
            "the independent Gate A reviewer must differ from label and review owners",
            path="$.independent_reviewer_id",
        )
    sample_count = _integer(raw["sample_count"], path="$.sample_count", minimum=20)
    if sample_count > 50:
        raise _error(
            "FRAME_TRANSITION_GATE_INVALID",
            "Gate A sample_count must not exceed 50",
            path="$.sample_count",
        )
    actual_count = _integer(raw["actual_output_count"], path="$.actual_output_count", minimum=0)
    if actual_count != sample_count:
        raise _error(
            "FRAME_TRANSITION_GATE_INCOMPLETE",
            "Gate A requires one actual output for every preregistered sample",
            path="$.actual_output_count",
        )
    recurrence = _integer(raw["recurrent_j2_j3_count"], path="$.recurrent_j2_j3_count", minimum=0)
    threshold = _integer(raw["recurrence_threshold"], path="$.recurrence_threshold", minimum=1)
    if recurrence > sample_count or threshold > sample_count:
        raise _error(
            "FRAME_TRANSITION_GATE_INVALID",
            "recurrence values cannot exceed the Gate A sample",
            path="$.recurrence_threshold",
        )
    stable = _boolean(raw["rubric_stable"], path="$.rubric_stable")
    outcome = "UNSTABLE_RUBRIC" if not stable else ("GO" if recurrence >= threshold else "NO_BUILD")
    result = dict(raw)
    result["outcome"] = outcome
    result["policy_id"] = POLICY_ADOPTION_POLICY_ID
    result["policy_digest"] = POLICY_ADOPTION_POLICY_DIGEST
    return result


def _validate_signals(
    value: Any,
    *,
    generation_id: str,
    compatibility_digest: str,
) -> list[dict[str, Any]]:
    rows = _array(value, path="$.exhaustion_signals", minimum=2)
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    kinds: set[str] = set()
    evidence_digests: set[str] = set()
    canonical_count = 0
    for index, value_row in enumerate(rows):
        path = f"$.exhaustion_signals[{index}]"
        row = _object(value_row, _SIGNAL_KEYS, path=path)
        signal_id = _text(row["signal_id"], path=f"{path}.signal_id")
        if signal_id in ids:
            raise _error(
                "FRAME_TRANSITION_EVIDENCE_INVALID",
                "exhaustion signal IDs must be unique",
                path=f"{path}.signal_id",
            )
        ids.add(signal_id)
        kind = _text(row["kind"], path=f"{path}.kind")
        if kind not in _SIGNAL_KINDS:
            raise _error(
                "FRAME_TRANSITION_EVIDENCE_INVALID",
                "unknown exhaustion signal kind",
                path=f"{path}.kind",
            )
        kinds.add(kind)
        evidence_digest = _digest(row["evidence_digest"], path=f"{path}.evidence_digest")
        if evidence_digest in evidence_digests:
            raise _error(
                "FRAME_TRANSITION_EVIDENCE_INSUFFICIENT",
                "independent exhaustion signals require distinct evidence digests",
                path=f"{path}.evidence_digest",
            )
        evidence_digests.add(evidence_digest)
        lane = _text(row["lane"], path=f"{path}.lane")
        if lane not in {"canonical", "advisory"}:
            raise _error(
                "FRAME_TRANSITION_MEMORY_LANE_INVALID",
                "evidence lane must be canonical or advisory",
                path=f"{path}.lane",
            )
        source_generation = _text(row["source_generation_id"], path=f"{path}.source_generation_id")
        source_compatibility = _digest(
            row["source_compatibility_digest"],
            path=f"{path}.source_compatibility_digest",
        )
        if lane == "canonical" and (
            source_generation != generation_id or source_compatibility != compatibility_digest
        ):
            raise _error(
                "FRAME_TRANSITION_ADVISORY_ONLY",
                "cross-generation or cross-compatibility evidence must be advisory",
                path=f"{path}.lane",
            )
        if lane == "canonical":
            canonical_count += 1
        result.append(row)
    if len(kinds) < 2:
        raise _error(
            "FRAME_TRANSITION_EVIDENCE_INSUFFICIENT",
            "one signal kind cannot authorize a frame inquiry",
            path="$.exhaustion_signals",
        )
    if canonical_count < 1:
        # Advisory material is self-authored and carries no compatibility seal.
        # It may corroborate exhaustion but must never establish it alone, or a
        # maker could open an inquiry purely from notes they wrote themselves.
        raise _error(
            "FRAME_TRANSITION_EVIDENCE_INSUFFICIENT",
            "advisory signals alone cannot authorize a frame inquiry",
            path="$.exhaustion_signals",
        )
    return result


def rival_fingerprint(assumptions: Sequence[str], mechanism: str) -> str:
    """Digest the substantive content of one rival frame.

    Assumption order, casing, and repeated whitespace are presentation, not a
    substantive rival-frame difference, so they are normalized away.  Two rivals
    sharing a fingerprint are the same frame under different labels.

    This is exported so that draft generation can enforce the same divergence
    rule before an inquiry exists, rather than discovering collisions only at
    inquiry-open time.
    """

    return sha256_json(
        {
            "assumptions": sorted(
                {" ".join(assumption.casefold().split()) for assumption in assumptions}
            ),
            "mechanism": " ".join(mechanism.casefold().split()),
        }
    )


def _validate_rivals(value: Any) -> list[dict[str, Any]]:
    rows = _array(value, path="$.rivals", minimum=2)
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    substantive_fingerprints: set[str] = set()
    for index, value_row in enumerate(rows):
        path = f"$.rivals[{index}]"
        row = _object(value_row, _RIVAL_KEYS, path=path)
        rival_id = _text(row["rival_id"], path=f"{path}.rival_id")
        if rival_id in ids:
            raise _error(
                "FRAME_TRANSITION_RIVALS_INVALID",
                "rival IDs must be unique",
                path=f"{path}.rival_id",
            )
        ids.add(rival_id)
        _text(row["label"], path=f"{path}.label")
        assumptions = _text_array(row["assumptions"], path=f"{path}.assumptions")
        mechanism = _text(row["mechanism"], path=f"{path}.mechanism")
        fingerprint = rival_fingerprint(assumptions, mechanism)
        if fingerprint in substantive_fingerprints:
            raise _error(
                "FRAME_TRANSITION_RIVALS_INVALID",
                "each rival must differ substantively in assumptions or mechanism",
                path=path,
            )
        substantive_fingerprints.add(fingerprint)
        _text_array(row["predictions"], path=f"{path}.predictions")
        _text_array(row["falsifiers"], path=f"{path}.falsifiers")
        _text(row["uncertainty"], path=f"{path}.uncertainty")
        result.append(row)
    if len(substantive_fingerprints) < 2:
        raise _error(
            "FRAME_TRANSITION_RIVALS_INVALID",
            "rivals must state different assumptions or mechanisms",
            path="$.rivals",
        )
    return result


def _validate_discriminator(value: Any) -> dict[str, Any]:
    row = _object(value, _DISCRIMINATOR_KEYS, path="$.discriminator")
    _text(row["discriminator_id"], path="$.discriminator.discriminator_id")
    _text(row["procedure"], path="$.discriminator.procedure")
    _text(row["outcome_rule"], path="$.discriminator.outcome_rule")
    _digest(row["plan_digest"], path="$.discriminator.plan_digest")
    return row


def _validate_inquiry(
    raw: Mapping[str, Any],
    *,
    gate: Mapping[str, Any],
) -> dict[str, Any]:
    _schema(raw)
    gate_digest = _digest(raw["gate_receipt_digest"], path="$.gate_receipt_digest")
    if gate_digest != gate["receipt_digest"] or gate["outcome"] != "GO":
        raise _error(
            "FRAME_TRANSITION_GATE_REQUIRED",
            "a current Gate A GO receipt is required",
            path="$.gate_receipt_digest",
        )
    _text(raw["maker_id"], path="$.maker_id")
    pointers = _text_array(raw["changed_pointers"], path="$.changed_pointers")
    derived = classify_frame_change(pointers)
    claimed = _text(raw["claimed_jump_class"], path="$.claimed_jump_class")
    if claimed not in JUMP_CLASSES or claimed != derived:
        raise _error(
            "FRAME_TRANSITION_CLASSIFICATION_MISMATCH",
            "claimed jump class must match the changed surfaces",
            path="$.claimed_jump_class",
            derived_jump_class=derived,
        )
    if derived in {"J0", "J1"}:
        raise _error(
            "FRAME_TRANSITION_INNER_LOOP_REQUIRED",
            "J0 and J1 changes remain in the existing inner loop",
            path="$.changed_pointers",
            jump_class=derived,
        )
    if not _boolean(raw["material_change"], path="$.material_change"):
        raise _error(
            "FRAME_TRANSITION_MATERIAL_CHANGE_REQUIRED",
            "outer inquiry requires a material change",
            path="$.material_change",
        )
    generation_id = str(gate["predecessor_generation_id"])
    compatibility = str(gate["compatibility_digest"])
    result = dict(raw)
    result["exhaustion_signals"] = _validate_signals(
        raw["exhaustion_signals"],
        generation_id=generation_id,
        compatibility_digest=compatibility,
    )
    result["rivals"] = _validate_rivals(raw["rivals"])
    result["discriminator"] = _validate_discriminator(raw["discriminator"])
    result["jump_class"] = derived
    result["predecessor_generation_id"] = generation_id
    result["compatibility_digest"] = compatibility
    result["policy_id"] = gate["policy_id"]
    result["policy_digest"] = gate["policy_digest"]
    return result


def _validate_candidate(value: Any) -> dict[str, Any]:
    row = _object(value, _CANDIDATE_KEYS, path="$.candidate")
    _text(row["candidate_id"], path="$.candidate.candidate_id")
    for key in (
        "candidate_digest",
        "change_digest",
        "coverage_digest",
        "isolation_digest",
    ):
        _digest(row[key], path=f"$.candidate.{key}")
    return row


def _validate_pilot_plan(value: Any) -> dict[str, Any]:
    row = _object(value, _PILOT_PLAN_KEYS, path="$.pilot_plan")
    _text(row["pilot_plan_id"], path="$.pilot_plan.pilot_plan_id")
    _digest(row["task_digest"], path="$.pilot_plan.task_digest")
    _text(row["provider_revision"], path="$.pilot_plan.provider_revision")
    arms = _text_array(row["arms"], path="$.pilot_plan.arms", minimum=3)
    if tuple(arms) != PILOT_ARMS:
        raise _error(
            "FRAME_TRANSITION_PILOT_PLAN_INVALID",
            "pilot arms must use the exact frozen three-arm order",
            path="$.pilot_plan.arms",
        )
    for key in (
        "per_arm_call_limit",
        "per_arm_token_limit",
        "per_arm_elapsed_milliseconds_limit",
    ):
        _integer(row[key], path=f"$.pilot_plan.{key}", minimum=1)
    cost_cap = row["per_arm_cost_microunits_limit"]
    if cost_cap is not None:
        _integer(cost_cap, path="$.pilot_plan.per_arm_cost_microunits_limit", minimum=0)
    _text(row["primary_metric"], path="$.pilot_plan.primary_metric")
    _boolean(row["higher_is_better"], path="$.pilot_plan.higher_is_better")
    _integer(
        row["minimum_effect_microunits"],
        path="$.pilot_plan.minimum_effect_microunits",
        minimum=0,
    )
    _integer(
        row["max_critical_false_promotions"],
        path="$.pilot_plan.max_critical_false_promotions",
        minimum=0,
    )
    for key in ("privacy_policy_digest", "retention_policy_digest"):
        _digest(row[key], path=f"$.pilot_plan.{key}")
    _text(row["teardown_policy"], path="$.pilot_plan.teardown_policy")
    return row


def _validate_decision(
    raw: Mapping[str, Any],
    *,
    inquiry: Mapping[str, Any],
) -> dict[str, Any]:
    _schema(raw)
    if raw["inquiry_id"] != inquiry["inquiry_id"]:
        raise _error(
            "FRAME_TRANSITION_INQUIRY_MISMATCH",
            "decision must bind the exact inquiry",
            path="$.inquiry_id",
        )
    if raw["maker_id"] != inquiry["intake"]["maker_id"]:
        raise _error(
            "FRAME_TRANSITION_MAKER_MISMATCH",
            "only the inquiry maker may record its comparative decision",
            path="$.maker_id",
        )
    outcome = _text(raw["outcome"], path="$.outcome")
    if outcome not in INQUIRY_OUTCOMES:
        raise _error(
            "FRAME_TRANSITION_OUTCOME_INVALID",
            "inquiry outcome must be ABSTAIN, REJECT, or RECOMMEND_FOR_PILOT",
            path="$.outcome",
        )
    _text(raw["rationale"], path="$.rationale")
    _digest(raw["evidence_digest"], path="$.evidence_digest")
    result = dict(raw)
    if outcome in {"ABSTAIN", "REJECT"}:
        if raw["candidate"] is not None or raw["pilot_plan"] is not None:
            raise _error(
                "FRAME_TRANSITION_REQUEST_MAPPING_INVALID",
                "ABSTAIN and REJECT cannot create candidate or pilot state",
                path="$.candidate",
            )
        result["pilot_plan_digest"] = None
        return result
    if raw["candidate"] is None or raw["pilot_plan"] is None:
        raise _error(
            "FRAME_TRANSITION_PILOT_PLAN_REQUIRED",
            "recommendation requires an exact candidate and frozen pilot plan",
            path="$.pilot_plan",
        )
    candidate = _validate_candidate(raw["candidate"])
    plan = _validate_pilot_plan(raw["pilot_plan"])
    result["candidate"] = candidate
    result["pilot_plan"] = plan
    result["pilot_plan_digest"] = sha256_json(plan)
    return result


def _validate_arm_results(
    value: Any, *, plan: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], bool, int]:
    rows = _array(value, path="$.arm_results", minimum=3)
    if len(rows) != 3:
        raise _error(
            "FRAME_TRANSITION_PILOT_RESULT_INVALID",
            "pilot result must contain exactly three arms",
            path="$.arm_results",
        )
    result: list[dict[str, Any]] = []
    cap_exceeded = False
    false_promotions = 0
    for index, (raw_row, expected_arm) in enumerate(zip(rows, PILOT_ARMS, strict=True)):
        path = f"$.arm_results[{index}]"
        row = _object(raw_row, _ARM_RESULT_KEYS, path=path)
        arm = _text(row["arm"], path=f"{path}.arm")
        if arm != expected_arm:
            raise _error(
                "FRAME_TRANSITION_PILOT_RESULT_INVALID",
                "pilot arm order or identity changed",
                path=f"{path}.arm",
            )
        _integer(row["score_microunits"], path=f"{path}.score_microunits", minimum=None)
        calls = _integer(row["calls"], path=f"{path}.calls", minimum=1)
        tokens = _integer(row["tokens"], path=f"{path}.tokens", minimum=1)
        elapsed = _integer(
            row["elapsed_milliseconds"], path=f"{path}.elapsed_milliseconds", minimum=0
        )
        cost = row["cost_microunits"]
        cost_cap = plan["per_arm_cost_microunits_limit"]
        if cost_cap is None:
            if cost is not None:
                _integer(cost, path=f"{path}.cost_microunits", minimum=0)
        else:
            cost = _integer(cost, path=f"{path}.cost_microunits", minimum=0)
        false_promotions += _integer(
            row["critical_false_promotions"],
            path=f"{path}.critical_false_promotions",
            minimum=0,
        )
        cap_exceeded = cap_exceeded or any(
            (
                calls > plan["per_arm_call_limit"],
                tokens > plan["per_arm_token_limit"],
                elapsed > plan["per_arm_elapsed_milliseconds_limit"],
                cost_cap is not None and cost is not None and cost > cost_cap,
            )
        )
        result.append(row)
    return result, cap_exceeded, false_promotions


def _pilot_outcome(
    *,
    plan: Mapping[str, Any],
    arm_results: Sequence[Mapping[str, Any]],
    invariant_regression: bool,
    privacy_breach: bool,
    cap_exceeded: bool,
    false_promotions: int,
) -> str:
    if invariant_regression:
        return "KILL_B4"
    if privacy_breach or cap_exceeded:
        return "KILL_B3"
    if false_promotions > plan["max_critical_false_promotions"]:
        return "KILL_B1"
    scores = [int(row["score_microunits"]) for row in arm_results]
    if plan["higher_is_better"]:
        unique_effect = scores[2] - max(scores[:2])
    else:
        unique_effect = min(scores[:2]) - scores[2]
    if unique_effect < plan["minimum_effect_microunits"]:
        return "KILL_B2"
    return "PASS_FOR_ADOPTION"


def _validate_pilot_authorization(
    raw: Mapping[str, Any],
    *,
    inquiry: Mapping[str, Any],
    recorded_at: str,
) -> dict[str, Any]:
    _schema(raw)
    if raw["inquiry_id"] != inquiry["inquiry_id"]:
        raise _error(
            "FRAME_TRANSITION_INQUIRY_MISMATCH",
            "pilot authorization must bind the exact inquiry",
            path="$.inquiry_id",
        )
    decision = inquiry.get("decision")
    if not isinstance(decision, Mapping) or decision.get("outcome") != "RECOMMEND_FOR_PILOT":
        raise _error(
            "FRAME_TRANSITION_RECOMMENDATION_REQUIRED",
            "pilot authority requires an exact RECOMMEND_FOR_PILOT receipt",
            path="$.inquiry_id",
        )
    authorizer = _text(raw["authorizer_id"], path="$.authorizer_id")
    if authorizer == inquiry["intake"]["maker_id"]:
        raise _error(
            "FRAME_TRANSITION_INDEPENDENCE_REQUIRED",
            "the inquiry maker cannot issue pilot authority",
            path="$.authorizer_id",
        )
    if raw["authority"] != "PILOT_ONLY":
        raise _error(
            "FRAME_TRANSITION_AUTHORITY_INVALID",
            "pilot authority must be literal PILOT_ONLY",
            path="$.authority",
        )
    candidate = decision.get("candidate")
    if not isinstance(candidate, Mapping):  # pragma: no cover - validated decision
        raise _error("FRAME_TRANSITION_STATE_INVALID", "candidate state is missing")
    candidate_digest = _digest(raw["candidate_digest"], path="$.candidate_digest")
    plan_digest = _digest(raw["pilot_plan_digest"], path="$.pilot_plan_digest")
    if candidate_digest != candidate["candidate_digest"] or plan_digest != decision.get(
        "pilot_plan_digest"
    ):
        raise _error(
            "FRAME_TRANSITION_RECEIPT_MISMATCH",
            "pilot authority must bind the exact candidate and frozen plan",
            path="$.candidate_digest",
        )
    expires_at = _timestamp(raw["expires_at"], path="$.expires_at")
    _require_later(expires_at, recorded_at)
    _digest(raw["evidence_digest"], path="$.evidence_digest")
    return dict(raw)


def _validate_pilot_result(
    raw: Mapping[str, Any],
    *,
    inquiry: Mapping[str, Any],
    recorded_at: str,
    revoked: frozenset[str] | set[str],
) -> dict[str, Any]:
    _schema(raw)
    if raw["inquiry_id"] != inquiry["inquiry_id"]:
        raise _error(
            "FRAME_TRANSITION_INQUIRY_MISMATCH",
            "pilot result must bind the exact inquiry",
            path="$.inquiry_id",
        )
    authorization = inquiry.get("pilot_authorization")
    decision = inquiry.get("decision")
    if not isinstance(authorization, Mapping) or not isinstance(decision, Mapping):
        raise _error(
            "FRAME_TRANSITION_PILOT_AUTHORITY_REQUIRED",
            "pilot result requires current PILOT_ONLY authority",
            path="$.authorization_receipt_digest",
        )
    authorization_digest = _digest(
        raw["authorization_receipt_digest"],
        path="$.authorization_receipt_digest",
    )
    if authorization_digest != authorization["receipt_digest"]:
        raise _error(
            "FRAME_TRANSITION_RECEIPT_MISMATCH",
            "pilot result must bind the exact authorization receipt",
            path="$.authorization_receipt_digest",
        )
    if authorization_digest in revoked:
        raise _error(
            "FRAME_TRANSITION_AUTHORITY_REVOKED",
            "pilot authority was revoked before use",
            path="$.authorization_receipt_digest",
        )
    if _expired(str(authorization["expires_at"]), recorded_at):
        raise _error(
            "FRAME_TRANSITION_AUTHORITY_EXPIRED",
            "pilot authority expired before the result was recorded",
            path="$.authorization_receipt_digest",
        )
    evaluator = _text(raw["evaluator_id"], path="$.evaluator_id")
    if evaluator in {
        inquiry["intake"]["maker_id"],
        authorization["authorizer_id"],
    }:
        raise _error(
            "FRAME_TRANSITION_INDEPENDENCE_REQUIRED",
            "pilot evaluator must differ from maker and pilot authorizer",
            path="$.evaluator_id",
        )
    plan = decision.get("pilot_plan")
    candidate = decision.get("candidate")
    if not isinstance(plan, Mapping) or not isinstance(candidate, Mapping):
        raise _error("FRAME_TRANSITION_STATE_INVALID", "frozen pilot state is missing")
    results, cap_exceeded, false_promotions = _validate_arm_results(raw["arm_results"], plan=plan)
    privacy_breach = _boolean(raw["privacy_breach"], path="$.privacy_breach")
    invariant_regression = _boolean(raw["invariant_regression"], path="$.invariant_regression")
    _digest(raw["evidence_digest"], path="$.evidence_digest")
    result = dict(raw)
    result["arm_results"] = results
    result["candidate_digest"] = candidate["candidate_digest"]
    result["pilot_plan_digest"] = decision["pilot_plan_digest"]
    result["outcome"] = _pilot_outcome(
        plan=plan,
        arm_results=results,
        invariant_regression=invariant_regression,
        privacy_breach=privacy_breach,
        cap_exceeded=cap_exceeded,
        false_promotions=false_promotions,
    )
    return result


def _validate_adoption_review(
    raw: Mapping[str, Any],
    *,
    inquiry: Mapping[str, Any],
    recorded_at: str,
    revoked: frozenset[str] | set[str],
) -> dict[str, Any]:
    _schema(raw)
    if raw["inquiry_id"] != inquiry["inquiry_id"]:
        raise _error(
            "FRAME_TRANSITION_INQUIRY_MISMATCH",
            "adoption review must bind the exact inquiry",
            path="$.inquiry_id",
        )
    pilot = inquiry.get("pilot_result")
    decision = inquiry.get("decision")
    authorization = inquiry.get("pilot_authorization")
    if (
        not isinstance(pilot, Mapping)
        or pilot.get("outcome") != "PASS_FOR_ADOPTION"
        or not isinstance(decision, Mapping)
        or not isinstance(authorization, Mapping)
    ):
        raise _error(
            "FRAME_TRANSITION_PILOT_PASS_REQUIRED",
            "adoption review requires an exact PASS_FOR_ADOPTION receipt",
            path="$.pilot_receipt_digest",
        )
    if authorization["receipt_digest"] in revoked:
        raise _error(
            "FRAME_TRANSITION_AUTHORITY_REVOKED",
            "revoked pilot authority cannot support adoption review",
            path="$.pilot_receipt_digest",
        )
    candidate = decision.get("candidate")
    if not isinstance(candidate, Mapping):  # pragma: no cover - validated decision
        raise _error("FRAME_TRANSITION_STATE_INVALID", "candidate state is missing")
    reviewer = _text(raw["reviewer_id"], path="$.reviewer_id")
    excluded = {
        inquiry["intake"]["maker_id"],
        authorization["authorizer_id"],
        pilot["evaluator_id"],
    }
    if reviewer in excluded:
        raise _error(
            "FRAME_TRANSITION_INDEPENDENCE_REQUIRED",
            "adoption reviewer must be fresh and independent",
            path="$.reviewer_id",
        )
    verdict = _text(raw["verdict"], path="$.verdict")
    if verdict not in {"APPROVE", "REJECT"}:
        raise _error(
            "FRAME_TRANSITION_OUTCOME_INVALID",
            "adoption review verdict must be APPROVE or REJECT",
            path="$.verdict",
        )
    exact = {
        "candidate_digest": candidate["candidate_digest"],
        "change_digest": candidate["change_digest"],
        "coverage_digest": candidate["coverage_digest"],
        "pilot_receipt_digest": pilot["receipt_digest"],
        "predecessor_generation_id": inquiry["intake"]["predecessor_generation_id"],
    }
    for key, expected in exact.items():
        observed = raw[key]
        if key.endswith("_digest"):
            _digest(observed, path=f"$.{key}")
        else:
            _text(observed, path=f"$.{key}")
        if observed != expected:
            raise _error(
                "FRAME_TRANSITION_RECEIPT_MISMATCH",
                "adoption review does not bind the exact pilot chain",
                path=f"$.{key}",
                expected=expected,
                observed=observed,
            )
    for key in (
        "tree_digest",
        "successor_contract_digest",
        "successor_compatibility_digest",
        "evidence_digest",
    ):
        _digest(raw[key], path=f"$.{key}")
    if raw["successor_compatibility_digest"] == inquiry["intake"]["compatibility_digest"]:
        raise _error(
            "FRAME_TRANSITION_COMPATIBILITY_UNCHANGED",
            "outer adoption requires a compatibility-separated successor",
            path="$.successor_compatibility_digest",
        )
    expires_at = _timestamp(raw["expires_at"], path="$.expires_at")
    _require_later(expires_at, recorded_at)
    return dict(raw)


def _validate_policy_adoption(
    raw: Mapping[str, Any],
    *,
    inquiry: Mapping[str, Any],
    recorded_at: str,
    revoked: frozenset[str] | set[str],
) -> dict[str, Any]:
    _schema(raw)
    if raw["inquiry_id"] != inquiry["inquiry_id"]:
        raise _error(
            "FRAME_TRANSITION_INQUIRY_MISMATCH",
            "policy adoption must bind the exact inquiry",
            path="$.inquiry_id",
        )
    review = inquiry.get("adoption_review")
    pilot = inquiry.get("pilot_result")
    authorization = inquiry.get("pilot_authorization")
    if (
        not isinstance(pilot, Mapping)
        or pilot.get("outcome") != "PASS_FOR_ADOPTION"
    ):
        raise _error(
            "FRAME_TRANSITION_PILOT_PASS_REQUIRED",
            "policy adoption requires an exact PASS_FOR_ADOPTION receipt",
            path="$.inquiry_id",
        )
    if (
        not isinstance(review, Mapping)
        or review.get("verdict") != "APPROVE"
    ):
        raise _error(
            "FRAME_TRANSITION_REVIEW_APPROVAL_REQUIRED",
            "policy adoption requires an exact APPROVE review",
            path="$.inquiry_id",
        )
    if not isinstance(authorization, Mapping):
        raise _error(
            "FRAME_TRANSITION_PILOT_AUTHORITY_REQUIRED",
            "policy adoption requires the exact pilot authority chain",
            path="$.inquiry_id",
        )
    if inquiry["intake"].get("policy_id") != POLICY_ADOPTION_POLICY_ID or inquiry[
        "intake"
    ].get("policy_digest") != POLICY_ADOPTION_POLICY_DIGEST:
        raise _error(
            "FRAME_TRANSITION_POLICY_MISMATCH",
            "inquiry does not bind the built-in policy",
            path="$.inquiry_id",
        )
    if review["receipt_digest"] in revoked:
        raise _error(
            "FRAME_TRANSITION_AUTHORITY_REVOKED",
            "adoption review was revoked before policy adoption",
            path="$.inquiry_id",
        )
    if authorization["receipt_digest"] in revoked:
        raise _error(
            "FRAME_TRANSITION_AUTHORITY_REVOKED",
            "revoked pilot authority invalidates policy adoption",
            path="$.inquiry_id",
        )
    if _expired(str(review["expires_at"]), recorded_at):
        raise _error(
            "FRAME_TRANSITION_AUTHORITY_EXPIRED",
            "adoption review expired before policy adoption",
            path="$.inquiry_id",
        )
    result = dict(raw)
    result.update(
        {
            "decision": "POLICY_ADOPTION",
            "policy_id": POLICY_ADOPTION_POLICY_ID,
            "policy_digest": POLICY_ADOPTION_POLICY_DIGEST,
            "review_receipt_digest": review["receipt_digest"],
            "candidate_digest": review["candidate_digest"],
            "successor_contract_digest": review["successor_contract_digest"],
            "successor_compatibility_digest": review[
                "successor_compatibility_digest"
            ],
            "expires_at": review["expires_at"],
        }
    )
    result["evidence_digest"] = sha256_json(
        {
            "policy_digest": POLICY_ADOPTION_POLICY_DIGEST,
            "pilot_receipt_digest": review["pilot_receipt_digest"],
            "review_receipt_digest": review["receipt_digest"],
            "candidate_digest": review["candidate_digest"],
            "successor_contract_digest": review["successor_contract_digest"],
            "successor_compatibility_digest": review[
                "successor_compatibility_digest"
            ],
        }
    )
    return result


def _validate_revocation(
    raw: Mapping[str, Any],
    *,
    inquiry: Mapping[str, Any],
    revoked: frozenset[str] | set[str],
) -> dict[str, Any]:
    _schema(raw)
    if raw["inquiry_id"] != inquiry["inquiry_id"]:
        raise _error(
            "FRAME_TRANSITION_INQUIRY_MISMATCH",
            "revocation must bind the exact inquiry",
            path="$.inquiry_id",
        )
    if inquiry.get("successor_generation_id") is not None:
        raise _error(
            "FRAME_TRANSITION_AUTHORITY_CONSUMED",
            "consumed authority cannot retroactively revoke an opened successor",
            path="$.target_receipt_digest",
        )
    revoker = _text(raw["revoker_id"], path="$.revoker_id")
    target = _digest(raw["target_receipt_digest"], path="$.target_receipt_digest")
    valid_targets = {
        item["receipt_digest"]
        for item in (inquiry.get("pilot_authorization"),)
        if isinstance(item, Mapping)
    }
    review = inquiry.get("adoption_review")
    if isinstance(review, Mapping) and review.get("verdict") == "APPROVE":
        valid_targets.add(review["receipt_digest"])
    if target not in valid_targets:
        raise _error(
            "FRAME_TRANSITION_REVOCATION_INVALID",
            "only an authority receipt in this inquiry can be revoked",
            path="$.target_receipt_digest",
        )
    if target in revoked:
        raise _error(
            "FRAME_TRANSITION_AUTHORITY_REVOKED",
            "authority receipt is already revoked",
            path="$.target_receipt_digest",
        )
    issuers = {
        item["receipt_digest"]: item[issuer_key]
        for item, issuer_key in (
            (inquiry.get("pilot_authorization"), "authorizer_id"),
            (inquiry.get("adoption_review"), "reviewer_id"),
        )
        if isinstance(item, Mapping)
    }
    if revoker != issuers[target]:
        raise _error(
            "FRAME_TRANSITION_REVOCATION_INVALID",
            "only the authority issuer may revoke its unused receipt",
            path="$.revoker_id",
        )
    _text(raw["reason"], path="$.reason")
    return dict(raw)


_RECEIPT_SPECS: dict[str, tuple[frozenset[str], str, str]] = {
    FRAME_GATE_EVENT_TYPE: (_GATE_PAYLOAD_KEYS, "gate_receipt_id", "framegate"),
    FRAME_INQUIRY_EVENT_TYPE: (_INQUIRY_PAYLOAD_KEYS, "inquiry_id", "frameinquiry"),
    FRAME_DECISION_EVENT_TYPE: (
        _DECISION_PAYLOAD_KEYS,
        "decision_receipt_id",
        "framedecision",
    ),
    FRAME_PILOT_AUTH_EVENT_TYPE: (
        _PILOT_AUTH_PAYLOAD_KEYS,
        "pilot_authorization_id",
        "pilotauth",
    ),
    FRAME_PILOT_RESULT_EVENT_TYPE: (
        _PILOT_RESULT_PAYLOAD_KEYS,
        "pilot_receipt_id",
        "pilotreceipt",
    ),
    FRAME_ADOPTION_REVIEW_EVENT_TYPE: (
        _ADOPTION_REVIEW_PAYLOAD_KEYS,
        "adoption_review_id",
        "adoptionreview",
    ),
    FRAME_POLICY_ADOPTION_EVENT_TYPE: (
        _POLICY_ADOPTION_PAYLOAD_KEYS,
        "policy_adoption_id",
        "policyadoption",
    ),
    FRAME_REVOCATION_EVENT_TYPE: (
        _REVOCATION_PAYLOAD_KEYS,
        "revocation_id",
        "revocation",
    ),
}


def _generation_values(payload: Mapping[str, Any]) -> tuple[str, str, str, str | None, str | None]:
    generation_id = str(payload["generation_id"])
    contract_digest = str(payload["study_contract_digest"])
    seal = payload["evaluation_seal"]
    if not isinstance(seal, Mapping):  # pragma: no cover - scientific reducer owns this
        raise _error(
            "FRAME_TRANSITION_STATE_INVALID",
            "generation evaluation seal is missing",
        )
    compatibility_digest = str(seal["compatibility_digest"])
    predecessor = payload.get("predecessor_generation_id")
    reason = payload.get("change_reason")
    return (
        generation_id,
        contract_digest,
        compatibility_digest,
        None if predecessor is None else str(predecessor),
        None if reason is None else str(reason),
    )


def _authority_revoked(inquiry: Mapping[str, Any], revoked: set[str]) -> bool:
    return any(
        item.get("receipt_digest") in revoked
        for item in (
            inquiry.get("pilot_authorization"),
            inquiry.get("adoption_review"),
        )
        if isinstance(item, Mapping)
    )


def _activation_matches(
    inquiry: Mapping[str, Any],
    *,
    predecessor_generation_id: str | None,
    contract_digest: str,
    compatibility_digest: str,
    change_reason: str | None,
    occurred_at: str | None,
    revoked: set[str],
) -> bool:
    policy_adoption = inquiry.get("policy_adoption")
    review = inquiry.get("adoption_review")
    pilot = inquiry.get("pilot_result")
    if (
        not isinstance(policy_adoption, Mapping)
        or not isinstance(review, Mapping)
        or not isinstance(pilot, Mapping)
        or pilot.get("outcome") != "PASS_FOR_ADOPTION"
        or review.get("verdict") != "APPROVE"
        or inquiry.get("superseded_by_generation_id") is not None
        or inquiry.get("gate_superseded_by_receipt_digest") is not None
        or _authority_revoked(inquiry, revoked)
    ):
        return False
    if occurred_at is None:
        raise _error(
            "FRAME_TRANSITION_TIME_INVALID",
            "controlled generation events require occurred_at",
        )
    expected_reason = controlled_change_reason(
        str(inquiry["inquiry_id"]), str(policy_adoption["receipt_digest"])
    )
    return all(
        (
            predecessor_generation_id == inquiry["intake"]["predecessor_generation_id"],
            contract_digest == policy_adoption["successor_contract_digest"],
            compatibility_digest
            == policy_adoption["successor_compatibility_digest"],
            compatibility_digest != inquiry["intake"]["compatibility_digest"],
            change_reason == expected_reason,
            _instant(occurred_at)
            >= _instant(str(policy_adoption["recorded_at"])),
            not _expired(str(review["expires_at"]), occurred_at),
            not _expired(str(policy_adoption["expires_at"]), occurred_at),
        )
    )


def _refresh_inquiry_status(
    inquiry: dict[str, Any],
    *,
    revoked: set[str],
    as_of: str | None,
) -> None:
    decision = inquiry.get("decision")
    authorization = inquiry.get("pilot_authorization")
    pilot = inquiry.get("pilot_result")
    review = inquiry.get("adoption_review")
    policy_adoption = inquiry.get("policy_adoption")
    successor = inquiry.get("successor_generation_id")

    if successor is not None:
        inquiry["stage"] = "ACTIVATED"
        inquiry["terminal_result"] = "GO_ADOPTION"
    elif inquiry.get("gate_superseded_by_receipt_digest") is not None:
        inquiry["stage"] = "STALE_GATE"
        inquiry["terminal_result"] = "GO_NO_ADOPTION"
    elif inquiry.get("superseded_by_generation_id") is not None:
        inquiry["stage"] = "STALE_PREDECESSOR"
        inquiry["terminal_result"] = "GO_NO_ADOPTION"
    elif decision is None:
        inquiry["stage"] = "AWAITING_DECISION"
        inquiry["terminal_result"] = None
    elif decision["outcome"] in {"ABSTAIN", "REJECT"}:
        inquiry["stage"] = decision["outcome"]
        inquiry["terminal_result"] = "GO_NO_ADOPTION"
    elif authorization is None:
        inquiry["stage"] = "AWAITING_PILOT_AUTHORIZATION"
        inquiry["terminal_result"] = None
    elif authorization["receipt_digest"] in revoked:
        inquiry["stage"] = "PILOT_AUTHORITY_REVOKED"
        inquiry["terminal_result"] = "GO_NO_ADOPTION"
    elif pilot is None and as_of is not None and _expired(authorization["expires_at"], as_of):
        inquiry["stage"] = "PILOT_AUTHORITY_EXPIRED"
        inquiry["terminal_result"] = "GO_NO_ADOPTION"
    elif pilot is None:
        inquiry["stage"] = "AWAITING_PILOT_RESULT"
        inquiry["terminal_result"] = None
    elif pilot["outcome"] != "PASS_FOR_ADOPTION":
        inquiry["stage"] = pilot["outcome"]
        inquiry["terminal_result"] = "GO_NO_ADOPTION"
    elif review is None:
        inquiry["stage"] = "AWAITING_ADOPTION_REVIEW"
        inquiry["terminal_result"] = None
    elif review["receipt_digest"] in revoked:
        inquiry["stage"] = "ADOPTION_REVIEW_REVOKED"
        inquiry["terminal_result"] = "GO_NO_ADOPTION"
    elif review["verdict"] == "REJECT":
        inquiry["stage"] = "ADOPTION_REJECTED"
        inquiry["terminal_result"] = "GO_NO_ADOPTION"
    elif policy_adoption is None and as_of is not None and _expired(
        review["expires_at"], as_of
    ):
        inquiry["stage"] = "ADOPTION_REVIEW_EXPIRED"
        inquiry["terminal_result"] = "GO_NO_ADOPTION"
    elif policy_adoption is None:
        inquiry["stage"] = "AWAITING_POLICY_ADOPTION"
        inquiry["terminal_result"] = None
    elif as_of is not None and _expired(policy_adoption["expires_at"], as_of):
        inquiry["stage"] = "POLICY_ADOPTION_EXPIRED"
        inquiry["terminal_result"] = "GO_NO_ADOPTION"
    else:
        inquiry["stage"] = "READY_TO_ACTIVATE"
        inquiry["terminal_result"] = None
    inquiry["durable_successor_writer_count"] = 1 if successor is not None else 0
    inquiry["authorized_action"] = None


def reduce_frame_transition_state(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    as_of: str | None = None,
) -> FrameTransitionState:
    """Replay the opt-in outer lifecycle without I/O or implicit clocks."""

    project_id = _text(project_id, path="$.project_id")
    if as_of is not None:
        as_of = _timestamp(as_of, path="$.as_of")
    # The scientific reducer remains the owner of every generation payload and
    # successor invariant. It intentionally ignores the extension events.
    scientific = reduce_scientific_state(events, project_id=project_id)

    active_generation_id: str | None = None
    active_compatibility_digest: str | None = None
    active_contract_digest: str | None = None
    active_generation_occurred_at: str | None = None
    gates: list[dict[str, Any]] = []
    gate_by_digest: dict[str, dict[str, Any]] = {}
    inquiries: dict[str, dict[str, Any]] = {}
    revoked: set[str] = set()
    receipt_ids: set[str] = set()
    receipt_digests: set[str] = set()

    for event in events:
        event_type, payload, occurred_at, event_id = _event_parts(event, project_id=project_id)
        if event_type == GENERATION_EVENT_TYPE:
            (
                generation_id,
                contract_digest,
                compatibility_digest,
                predecessor,
                reason,
            ) = _generation_values(payload)
            if predecessor is not None:
                candidates = [
                    inquiry
                    for inquiry in inquiries.values()
                    if inquiry["intake"]["predecessor_generation_id"] == predecessor
                    and inquiry.get("successor_generation_id") is None
                    and inquiry.get("superseded_by_generation_id") is None
                ]
                controlled = reason is not None and reason.startswith(
                    "controlled-frame-transition:"
                )
                matches = [
                    inquiry
                    for inquiry in candidates
                    if _activation_matches(
                        inquiry,
                        predecessor_generation_id=predecessor,
                        contract_digest=contract_digest,
                        compatibility_digest=compatibility_digest,
                        change_reason=reason,
                        occurred_at=occurred_at,
                        revoked=revoked,
                    )
                ]
                if controlled and len(matches) != 1:
                    raise _error(
                        "FRAME_TRANSITION_ACTIVATION_INVALID",
                        "controlled generation does not bind exactly one current adoption",
                        generation_id=generation_id,
                    )
                winner = matches[0] if matches else None
                for inquiry in candidates:
                    if inquiry is winner:
                        inquiry["successor_generation_id"] = generation_id
                        inquiry["activation_event_id"] = event_id
                    else:
                        inquiry["superseded_by_generation_id"] = generation_id
            active_generation_id = generation_id
            active_compatibility_digest = compatibility_digest
            active_contract_digest = contract_digest
            active_generation_occurred_at = occurred_at
            continue
        if event_type not in FRAME_EVENT_TYPES:
            continue

        expected_keys, id_key, namespace = _RECEIPT_SPECS[event_type]
        raw = _validate_receipt(
            payload,
            expected_keys=expected_keys,
            id_key=id_key,
            namespace=namespace,
            occurred_at=occurred_at,
        )
        receipt_id = str(raw[id_key])
        receipt_digest = str(raw["receipt_digest"])
        if receipt_id in receipt_ids or receipt_digest in receipt_digests:
            raise _error(
                "FRAME_TRANSITION_DUPLICATE_RECEIPT",
                "canonical history contains a duplicate frame-transition receipt",
                receipt_id=receipt_id,
            )
        receipt_ids.add(receipt_id)
        receipt_digests.add(receipt_digest)
        recorded_at = str(raw["recorded_at"])

        if event_type == FRAME_GATE_EVENT_TYPE:
            derived = _validate_gate(raw)
            if raw["outcome"] != derived["outcome"]:
                raise _error(
                    "FRAME_TRANSITION_OUTCOME_INVALID",
                    "Gate A outcome does not match the deterministic reducer",
                    path="$.payload.outcome",
                )
            for key in ("policy_id", "policy_digest"):
                if raw[key] != derived[key]:
                    raise _error(
                        "FRAME_TRANSITION_RECEIPT_MISMATCH",
                        "Gate A derived fields do not match the deterministic reducer",
                        path=f"$.payload.{key}",
                    )
            if active_generation_id is None or any(
                (
                    raw["predecessor_generation_id"] != active_generation_id,
                    raw["compatibility_digest"] != active_compatibility_digest,
                )
            ):
                raise _error(
                    "FRAME_TRANSITION_GATE_STALE",
                    "Gate A must bind the then-active generation and compatibility",
                    active_generation_id=active_generation_id,
                )
            if active_generation_occurred_at is None:
                raise _error(
                    "FRAME_TRANSITION_TIME_INVALID",
                    "Gate A requires a timestamped active generation",
                    path="$.payload.recorded_at",
                )
            _require_not_before(recorded_at, active_generation_occurred_at)
            gate = dict(raw)
            gates.append(gate)
            gate_by_digest[receipt_digest] = gate
            for inquiry in inquiries.values():
                intake = inquiry["intake"]
                if (
                    intake["predecessor_generation_id"] == active_generation_id
                    and intake["compatibility_digest"]
                    == active_compatibility_digest
                    and intake["gate_receipt_digest"] != receipt_digest
                    and inquiry.get("successor_generation_id") is None
                ):
                    inquiry["gate_superseded_by_receipt_digest"] = receipt_digest
            continue

        inquiry_id = str(raw.get("inquiry_id", ""))
        if event_type == FRAME_INQUIRY_EVENT_TYPE:
            gate = gate_by_digest.get(str(raw["gate_receipt_digest"]))
            if gate is None:
                raise _error(
                    "FRAME_TRANSITION_GATE_REQUIRED",
                    "inquiry references a missing Gate A receipt",
                    path="$.payload.gate_receipt_digest",
                )
            current_gates = [
                item
                for item in gates
                if item["predecessor_generation_id"] == active_generation_id
                and item["compatibility_digest"] == active_compatibility_digest
            ]
            if not current_gates or current_gates[-1]["receipt_digest"] != gate["receipt_digest"]:
                raise _error(
                    "FRAME_TRANSITION_GATE_STALE",
                    "inquiry must use the latest Gate A receipt for the active frame",
                    path="$.payload.gate_receipt_digest",
                )
            derived = _validate_inquiry(raw, gate=gate)
            for key in (
                "jump_class",
                "predecessor_generation_id",
                "compatibility_digest",
                "policy_id",
                "policy_digest",
            ):
                if raw[key] != derived[key]:
                    raise _error(
                        "FRAME_TRANSITION_RECEIPT_MISMATCH",
                        "inquiry derived fields do not match their evidence",
                        path=f"$.payload.{key}",
                    )
            if raw["predecessor_generation_id"] != active_generation_id:
                raise _error(
                    "FRAME_TRANSITION_INQUIRY_STALE",
                    "inquiry predecessor is no longer active",
                    path="$.payload.predecessor_generation_id",
                )
            _require_not_before(recorded_at, str(gate["recorded_at"]))
            if inquiry_id in inquiries:
                raise _error(
                    "FRAME_TRANSITION_DUPLICATE_INQUIRY",
                    "inquiry already exists",
                    inquiry_id=inquiry_id,
                )
            inquiries[inquiry_id] = {
                "inquiry_id": inquiry_id,
                "intake": dict(raw),
                "decision": None,
                "pilot_authorization": None,
                "pilot_result": None,
                "adoption_review": None,
                "policy_adoption": None,
                "revocations": [],
                "successor_generation_id": None,
                "activation_event_id": None,
                "superseded_by_generation_id": None,
                "gate_superseded_by_receipt_digest": None,
                "stage": "AWAITING_DECISION",
                "terminal_result": None,
                "durable_successor_writer_count": 0,
                "authorized_action": None,
            }
            continue

        inquiry = inquiries.get(inquiry_id)
        if inquiry is None:
            raise _error(
                "FRAME_TRANSITION_INQUIRY_REQUIRED",
                "lifecycle receipt references a missing inquiry",
                path="$.payload.inquiry_id",
            )
        if inquiry.get("superseded_by_generation_id") is not None:
            raise _error(
                "FRAME_TRANSITION_INQUIRY_STALE",
                "a superseded inquiry cannot receive new lifecycle receipts",
                inquiry_id=inquiry_id,
            )
        if inquiry.get("gate_superseded_by_receipt_digest") is not None:
            raise _error(
                "FRAME_TRANSITION_GATE_STALE",
                "a superseded Gate A receipt cannot support new lifecycle receipts",
                inquiry_id=inquiry_id,
            )

        if event_type == FRAME_DECISION_EVENT_TYPE:
            if inquiry["decision"] is not None:
                raise _error(
                    "FRAME_TRANSITION_STAGE_ALREADY_RECORDED",
                    "inquiry decision is single-writer",
                    inquiry_id=inquiry_id,
                )
            derived = _validate_decision(raw, inquiry=inquiry)
            if raw["pilot_plan_digest"] != derived["pilot_plan_digest"]:
                raise _error(
                    "FRAME_TRANSITION_RECEIPT_MISMATCH",
                    "decision pilot plan digest is not canonical",
                    path="$.payload.pilot_plan_digest",
                )
            _require_not_before(recorded_at, inquiry["intake"]["recorded_at"])
            inquiry["decision"] = dict(raw)
            continue

        if event_type == FRAME_PILOT_AUTH_EVENT_TYPE:
            if inquiry["pilot_authorization"] is not None:
                raise _error(
                    "FRAME_TRANSITION_STAGE_ALREADY_RECORDED",
                    "pilot authorization is single-writer",
                    inquiry_id=inquiry_id,
                )
            decision = inquiry.get("decision")
            if not isinstance(decision, Mapping):
                raise _error(
                    "FRAME_TRANSITION_RECOMMENDATION_REQUIRED",
                    "pilot authorization requires a decision",
                )
            _require_not_before(recorded_at, str(decision["recorded_at"]))
            _validate_pilot_authorization(raw, inquiry=inquiry, recorded_at=recorded_at)
            inquiry["pilot_authorization"] = dict(raw)
            continue

        if event_type == FRAME_PILOT_RESULT_EVENT_TYPE:
            if inquiry["pilot_result"] is not None:
                raise _error(
                    "FRAME_TRANSITION_STAGE_ALREADY_RECORDED",
                    "pilot result is single-writer",
                    inquiry_id=inquiry_id,
                )
            authorization = inquiry.get("pilot_authorization")
            if not isinstance(authorization, Mapping):
                raise _error(
                    "FRAME_TRANSITION_PILOT_AUTHORITY_REQUIRED",
                    "pilot result requires authorization",
                )
            _require_not_before(recorded_at, str(authorization["recorded_at"]))
            derived = _validate_pilot_result(
                raw,
                inquiry=inquiry,
                recorded_at=recorded_at,
                revoked=revoked,
            )
            for key in ("candidate_digest", "pilot_plan_digest", "outcome"):
                if raw[key] != derived[key]:
                    raise _error(
                        "FRAME_TRANSITION_RECEIPT_MISMATCH",
                        "pilot derived fields do not match the frozen plan",
                        path=f"$.payload.{key}",
                    )
            inquiry["pilot_result"] = dict(raw)
            continue

        if event_type == FRAME_ADOPTION_REVIEW_EVENT_TYPE:
            if inquiry["adoption_review"] is not None:
                raise _error(
                    "FRAME_TRANSITION_STAGE_ALREADY_RECORDED",
                    "adoption review is single-writer",
                    inquiry_id=inquiry_id,
                )
            pilot = inquiry.get("pilot_result")
            if not isinstance(pilot, Mapping):
                raise _error(
                    "FRAME_TRANSITION_PILOT_PASS_REQUIRED",
                    "adoption review requires a pilot result",
                )
            _require_not_before(recorded_at, str(pilot["recorded_at"]))
            _validate_adoption_review(
                raw,
                inquiry=inquiry,
                recorded_at=recorded_at,
                revoked=revoked,
            )
            inquiry["adoption_review"] = dict(raw)
            continue

        if event_type == FRAME_POLICY_ADOPTION_EVENT_TYPE:
            if inquiry["policy_adoption"] is not None:
                raise _error(
                    "FRAME_TRANSITION_STAGE_ALREADY_RECORDED",
                    "policy adoption is single-writer",
                    inquiry_id=inquiry_id,
                )
            review = inquiry.get("adoption_review")
            if not isinstance(review, Mapping):
                raise _error(
                    "FRAME_TRANSITION_REVIEW_APPROVAL_REQUIRED",
                    "policy adoption requires review",
                )
            _require_not_before(recorded_at, str(review["recorded_at"]))
            derived = _validate_policy_adoption(
                raw,
                inquiry=inquiry,
                recorded_at=recorded_at,
                revoked=revoked,
            )
            for key in (
                "decision",
                "policy_id",
                "policy_digest",
                "review_receipt_digest",
                "candidate_digest",
                "successor_contract_digest",
                "successor_compatibility_digest",
                "expires_at",
                "evidence_digest",
            ):
                if raw[key] != derived[key]:
                    raise _error(
                        "FRAME_TRANSITION_RECEIPT_MISMATCH",
                        "policy adoption derived fields do not match its current review",
                        path=f"$.payload.{key}",
                    )
            inquiry["policy_adoption"] = dict(raw)
            continue

        if event_type == FRAME_REVOCATION_EVENT_TYPE:
            target = str(raw["target_receipt_digest"])
            targets = [
                item
                for item in (
                    inquiry.get("pilot_authorization"),
                    inquiry.get("adoption_review"),
                )
                if isinstance(item, Mapping) and item["receipt_digest"] == target
            ]
            if targets:
                _require_not_before(recorded_at, str(targets[0]["recorded_at"]))
            if (
                isinstance(inquiry.get("pilot_authorization"), Mapping)
                and target == inquiry["pilot_authorization"]["receipt_digest"]
                and inquiry.get("pilot_result") is not None
            ):
                raise _error(
                    "FRAME_TRANSITION_AUTHORITY_CONSUMED",
                    "consumed authority cannot be revoked",
                    path="$.payload.target_receipt_digest",
                )
            _validate_revocation(raw, inquiry=inquiry, revoked=revoked)
            revoked.add(target)
            inquiry["revocations"].append(dict(raw))

    if active_generation_id != scientific.active_generation_id:
        raise _error(
            "FRAME_TRANSITION_STATE_INVALID",
            "outer replay disagrees with canonical scientific generation state",
        )
    for inquiry in inquiries.values():
        _refresh_inquiry_status(inquiry, revoked=revoked, as_of=as_of)
    return FrameTransitionState(
        project_id=project_id,
        active_generation_id=active_generation_id,
        active_compatibility_digest=active_compatibility_digest,
        active_contract_digest=active_contract_digest,
        gates=tuple(_json_object_copy(item, path="$.gates[]") for item in gates),
        inquiries=tuple(
            _json_object_copy(item, path="$.inquiries[]")
            for item in inquiries.values()
        ),
        revoked_receipt_digests=frozenset(revoked),
    )


def _existing_input_plan(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    event_type: str,
    raw: Mapping[str, Any],
) -> FrameTransitionPlan | None:
    id_key = _EVENT_ID_KEYS[event_type]
    for event in events:
        observed_type, payload, _occurred_at, event_id = _event_parts(
            event, project_id=project_id
        )
        if observed_type != event_type:
            continue
        if not set(raw).issubset(payload):
            continue
        canonical_input = {key: payload[key] for key in raw}
        if not _same_typed_json(canonical_input, raw):
            continue
        return FrameTransitionPlan(
            event_type=event_type,
            payload=_json_object_copy(payload, path="$.payload"),
            receipt_id=str(payload[id_key]),
            receipt_digest=str(payload["receipt_digest"]),
            append_required=False,
            existing_event_id=event_id,
        )
    return None


def _finalize_plan(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    event_type: str,
    core: Mapping[str, Any],
    recorded_at: str,
) -> FrameTransitionPlan:
    expected_keys, id_key, namespace = _RECEIPT_SPECS[event_type]
    payload = _receipt_payload(
        core,
        id_key=id_key,
        namespace=namespace,
        recorded_at=recorded_at,
    )
    if set(payload) != set(expected_keys):  # pragma: no cover - programmer invariant
        raise RuntimeError(
            f"invalid {event_type} planner fields: {sorted(set(payload) ^ set(expected_keys))}"
        )
    synthetic = {
        "project_id": project_id,
        "event_type": event_type,
        "occurred_at": recorded_at,
        "payload": payload,
    }
    reduce_frame_transition_state(
        (*events, synthetic),
        project_id=project_id,
        as_of=recorded_at,
    )
    return FrameTransitionPlan(
        event_type=event_type,
        payload=payload,
        receipt_id=str(payload[id_key]),
        receipt_digest=str(payload["receipt_digest"]),
        append_required=True,
    )


def _raw_plan_input(
    raw: Mapping[str, Any],
    *,
    keys: frozenset[str],
) -> dict[str, Any]:
    result = _object(raw, keys, path="$")
    _schema(result)
    return result


def plan_gate_a(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    raw: Mapping[str, Any],
    recorded_at: str,
) -> FrameTransitionPlan:
    reduce_frame_transition_state(events, project_id=project_id)
    data = _raw_plan_input(raw, keys=_GATE_INPUT_KEYS)
    retry = _existing_input_plan(
        events,
        project_id=project_id,
        event_type=FRAME_GATE_EVENT_TYPE,
        raw=data,
    )
    if retry is not None:
        return retry
    core = _validate_gate(data)
    return _finalize_plan(
        events,
        project_id=project_id,
        event_type=FRAME_GATE_EVENT_TYPE,
        core=core,
        recorded_at=_timestamp(recorded_at, path="$.recorded_at"),
    )


def plan_inquiry_open(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    raw: Mapping[str, Any],
    recorded_at: str,
) -> FrameTransitionPlan:
    state = reduce_frame_transition_state(events, project_id=project_id)
    data = _raw_plan_input(raw, keys=_INQUIRY_INPUT_KEYS)
    retry = _existing_input_plan(
        events,
        project_id=project_id,
        event_type=FRAME_INQUIRY_EVENT_TYPE,
        raw=data,
    )
    if retry is not None:
        return retry
    gate = state.gate_by_digest(str(data["gate_receipt_digest"]))
    if gate is None:
        raise _error(
            "FRAME_TRANSITION_GATE_REQUIRED",
            "inquiry references a missing Gate A receipt",
            path="$.gate_receipt_digest",
        )
    core = _validate_inquiry(data, gate=gate)
    return _finalize_plan(
        events,
        project_id=project_id,
        event_type=FRAME_INQUIRY_EVENT_TYPE,
        core=core,
        recorded_at=_timestamp(recorded_at, path="$.recorded_at"),
    )


def _require_inquiry(state: FrameTransitionState, inquiry_id: Any) -> dict[str, Any]:
    identifier = _text(inquiry_id, path="$.inquiry_id")
    inquiry = state.inquiry(identifier)
    if inquiry is None:
        raise _error(
            "FRAME_TRANSITION_INQUIRY_REQUIRED",
            "frame-transition inquiry does not exist",
            inquiry_id=identifier,
        )
    return inquiry


def plan_inquiry_decision(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    raw: Mapping[str, Any],
    recorded_at: str,
) -> FrameTransitionPlan:
    state = reduce_frame_transition_state(events, project_id=project_id)
    data = _raw_plan_input(raw, keys=_DECISION_INPUT_KEYS)
    retry = _existing_input_plan(
        events,
        project_id=project_id,
        event_type=FRAME_DECISION_EVENT_TYPE,
        raw=data,
    )
    if retry is not None:
        return retry
    inquiry = _require_inquiry(state, data["inquiry_id"])
    core = _validate_decision(data, inquiry=inquiry)
    return _finalize_plan(
        events,
        project_id=project_id,
        event_type=FRAME_DECISION_EVENT_TYPE,
        core=core,
        recorded_at=_timestamp(recorded_at, path="$.recorded_at"),
    )


def plan_pilot_authorization(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    raw: Mapping[str, Any],
    recorded_at: str,
) -> FrameTransitionPlan:
    state = reduce_frame_transition_state(events, project_id=project_id)
    data = _raw_plan_input(raw, keys=_PILOT_AUTH_INPUT_KEYS)
    retry = _existing_input_plan(
        events,
        project_id=project_id,
        event_type=FRAME_PILOT_AUTH_EVENT_TYPE,
        raw=data,
    )
    if retry is not None:
        return retry
    inquiry = _require_inquiry(state, data["inquiry_id"])
    timestamp = _timestamp(recorded_at, path="$.recorded_at")
    core = _validate_pilot_authorization(
        data,
        inquiry=inquiry,
        recorded_at=timestamp,
    )
    return _finalize_plan(
        events,
        project_id=project_id,
        event_type=FRAME_PILOT_AUTH_EVENT_TYPE,
        core=core,
        recorded_at=timestamp,
    )


def plan_pilot_result(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    raw: Mapping[str, Any],
    recorded_at: str,
) -> FrameTransitionPlan:
    state = reduce_frame_transition_state(events, project_id=project_id)
    data = _raw_plan_input(raw, keys=_PILOT_RESULT_INPUT_KEYS)
    retry = _existing_input_plan(
        events,
        project_id=project_id,
        event_type=FRAME_PILOT_RESULT_EVENT_TYPE,
        raw=data,
    )
    if retry is not None:
        return retry
    inquiry = _require_inquiry(state, data["inquiry_id"])
    timestamp = _timestamp(recorded_at, path="$.recorded_at")
    core = _validate_pilot_result(
        data,
        inquiry=inquiry,
        recorded_at=timestamp,
        revoked=state.revoked_receipt_digests,
    )
    return _finalize_plan(
        events,
        project_id=project_id,
        event_type=FRAME_PILOT_RESULT_EVENT_TYPE,
        core=core,
        recorded_at=timestamp,
    )


def plan_adoption_review(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    raw: Mapping[str, Any],
    recorded_at: str,
) -> FrameTransitionPlan:
    state = reduce_frame_transition_state(events, project_id=project_id)
    data = _raw_plan_input(raw, keys=_ADOPTION_REVIEW_INPUT_KEYS)
    retry = _existing_input_plan(
        events,
        project_id=project_id,
        event_type=FRAME_ADOPTION_REVIEW_EVENT_TYPE,
        raw=data,
    )
    if retry is not None:
        return retry
    inquiry = _require_inquiry(state, data["inquiry_id"])
    timestamp = _timestamp(recorded_at, path="$.recorded_at")
    core = _validate_adoption_review(
        data,
        inquiry=inquiry,
        recorded_at=timestamp,
        revoked=state.revoked_receipt_digests,
    )
    return _finalize_plan(
        events,
        project_id=project_id,
        event_type=FRAME_ADOPTION_REVIEW_EVENT_TYPE,
        core=core,
        recorded_at=timestamp,
    )


def plan_policy_adoption(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    raw: Mapping[str, Any],
    recorded_at: str,
) -> FrameTransitionPlan:
    state = reduce_frame_transition_state(events, project_id=project_id)
    data = _raw_plan_input(raw, keys=_POLICY_ADOPTION_INPUT_KEYS)
    retry = _existing_input_plan(
        events,
        project_id=project_id,
        event_type=FRAME_POLICY_ADOPTION_EVENT_TYPE,
        raw=data,
    )
    if retry is not None:
        return retry
    inquiry = _require_inquiry(state, data["inquiry_id"])
    timestamp = _timestamp(recorded_at, path="$.recorded_at")
    core = _validate_policy_adoption(
        data,
        inquiry=inquiry,
        recorded_at=timestamp,
        revoked=state.revoked_receipt_digests,
    )
    return _finalize_plan(
        events,
        project_id=project_id,
        event_type=FRAME_POLICY_ADOPTION_EVENT_TYPE,
        core=core,
        recorded_at=timestamp,
    )


def plan_authority_revocation(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    raw: Mapping[str, Any],
    recorded_at: str,
) -> FrameTransitionPlan:
    state = reduce_frame_transition_state(events, project_id=project_id)
    data = _raw_plan_input(raw, keys=_REVOCATION_INPUT_KEYS)
    retry = _existing_input_plan(
        events,
        project_id=project_id,
        event_type=FRAME_REVOCATION_EVENT_TYPE,
        raw=data,
    )
    if retry is not None:
        return retry
    inquiry = _require_inquiry(state, data["inquiry_id"])
    core = _validate_revocation(
        data,
        inquiry=inquiry,
        revoked=state.revoked_receipt_digests,
    )
    return _finalize_plan(
        events,
        project_id=project_id,
        event_type=FRAME_REVOCATION_EVENT_TYPE,
        core=core,
        recorded_at=_timestamp(recorded_at, path="$.recorded_at"),
    )


def validate_frame_transition_commit_time(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    plan: FrameTransitionPlan,
    as_of: str,
) -> None:
    """Recheck expiring authority at the canonical append linearization point."""

    if not plan.append_required:
        return
    timestamp = _timestamp(as_of, path="$.as_of")
    payload = plan.payload

    def require_unexpired(value: Any, *, path: str) -> None:
        expires_at = _timestamp(value, path=path)
        if _expired(expires_at, timestamp):
            raise _error(
                "FRAME_TRANSITION_AUTHORITY_EXPIRED",
                "frame-transition authority expired before canonical commit",
                path=path,
                as_of=timestamp,
            )

    if plan.event_type in {
        FRAME_PILOT_AUTH_EVENT_TYPE,
        FRAME_ADOPTION_REVIEW_EVENT_TYPE,
        FRAME_POLICY_ADOPTION_EVENT_TYPE,
    }:
        require_unexpired(payload["expires_at"], path="$.payload.expires_at")

    if plan.event_type not in {
        FRAME_PILOT_RESULT_EVENT_TYPE,
        FRAME_POLICY_ADOPTION_EVENT_TYPE,
    }:
        return
    state = reduce_frame_transition_state(events, project_id=project_id, as_of=timestamp)
    inquiry = _require_inquiry(state, payload["inquiry_id"])
    if plan.event_type == FRAME_PILOT_RESULT_EVENT_TYPE:
        authorization = inquiry.get("pilot_authorization")
        if not isinstance(authorization, Mapping):  # pragma: no cover - planner owns order
            raise _error(
                "FRAME_TRANSITION_PILOT_AUTHORITY_REQUIRED",
                "pilot authority disappeared before canonical commit",
            )
        require_unexpired(
            authorization["expires_at"],
            path="$.pilot_authorization.expires_at",
        )
        return
    review = inquiry.get("adoption_review")
    if not isinstance(review, Mapping):  # pragma: no cover - planner owns order
        raise _error(
            "FRAME_TRANSITION_REVIEW_APPROVAL_REQUIRED",
            "adoption review disappeared before canonical commit",
        )
    require_unexpired(review["expires_at"], path="$.adoption_review.expires_at")
    derived = _validate_policy_adoption(
        payload,
        inquiry=inquiry,
        recorded_at=timestamp,
        revoked=state.revoked_receipt_digests,
    )
    for key in (
        "decision",
        "policy_id",
        "policy_digest",
        "review_receipt_digest",
        "candidate_digest",
        "successor_contract_digest",
        "successor_compatibility_digest",
        "expires_at",
        "evidence_digest",
    ):
        if payload[key] != derived[key]:  # pragma: no cover - planner owns payload
            raise _error(
                "FRAME_TRANSITION_RECEIPT_MISMATCH",
                "policy adoption changed before canonical commit",
                path=f"$.payload.{key}",
            )


def validate_controlled_activation(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    inquiry_id: str,
    policy_adoption_digest: str,
    target_contract_digest: str,
    target_successor_compatibility_digest: str,
    change_reason: str,
    as_of: str,
) -> dict[str, Any]:
    """Validate exact, current activation authority for the existing writer."""

    identifier = _text(inquiry_id, path="$.inquiry_id")
    policy_adoption_receipt = _digest(
        policy_adoption_digest,
        path="$.policy_adoption_digest",
    )
    contract_digest = _digest(target_contract_digest, path="$.target_contract_digest")
    compatibility_digest = _digest(
        target_successor_compatibility_digest,
        path="$.target_successor_compatibility_digest",
    )
    timestamp = _timestamp(as_of, path="$.as_of")
    expected_reason = controlled_change_reason(identifier, policy_adoption_receipt)
    if change_reason != expected_reason:
        raise _error(
            "FRAME_TRANSITION_ACTIVATION_INVALID",
            "controlled change reason does not bind inquiry and policy adoption",
            path="$.change_reason",
        )
    state = reduce_frame_transition_state(events, project_id=project_id, as_of=timestamp)
    inquiry = _require_inquiry(state, identifier)
    policy_adoption = inquiry.get("policy_adoption")
    review = inquiry.get("adoption_review")
    if not isinstance(policy_adoption, Mapping) or not isinstance(review, Mapping):
        raise _error(
            "FRAME_TRANSITION_ADOPTION_REQUIRED",
            "controlled activation requires POLICY_ADOPTION",
            inquiry_id=identifier,
        )
    if policy_adoption["receipt_digest"] != policy_adoption_receipt:
        raise _error(
            "FRAME_TRANSITION_RECEIPT_MISMATCH",
            "activation policy adoption digest is not current",
            path="$.policy_adoption_digest",
        )
    if _instant(timestamp) < _instant(str(policy_adoption["recorded_at"])):
        raise _error(
            "FRAME_TRANSITION_TIME_INVALID",
            "activation cannot precede POLICY_ADOPTION",
            path="$.as_of",
            policy_adoption_recorded_at=policy_adoption["recorded_at"],
        )
    exact = {
        "successor_contract_digest": contract_digest,
        "successor_compatibility_digest": compatibility_digest,
    }
    for key, observed in exact.items():
        if policy_adoption[key] != observed:
            raise _error(
                "FRAME_TRANSITION_RECEIPT_MISMATCH",
                "activation target does not match POLICY_ADOPTION",
                path=f"$.{key}",
            )
    predecessor = str(inquiry["intake"]["predecessor_generation_id"])
    successor = inquiry.get("successor_generation_id")
    if successor is None:
        if inquiry.get("stage") != "READY_TO_ACTIVATE":
            raise _error(
                "FRAME_TRANSITION_ACTIVATION_INVALID",
                "inquiry is not currently eligible for activation",
                inquiry_id=identifier,
                stage=inquiry.get("stage"),
            )
        if state.active_generation_id != predecessor:
            raise _error(
                "FRAME_TRANSITION_INQUIRY_STALE",
                "inquiry predecessor is no longer active",
                active_generation_id=state.active_generation_id,
                predecessor_generation_id=predecessor,
            )
    elif inquiry.get("terminal_result") != "GO_ADOPTION":
        raise _error(
            "FRAME_TRANSITION_ACTIVATION_INVALID",
            "recorded successor is not an exact controlled activation",
            inquiry_id=identifier,
        )
    return {
        "schema_version": FRAME_SCHEMA_VERSION,
        "inquiry_id": identifier,
        "policy_adoption_digest": policy_adoption_receipt,
        "predecessor_generation_id": predecessor,
        "successor_generation_id": successor,
        "successor_contract_digest": contract_digest,
        "successor_compatibility_digest": compatibility_digest,
        "source_tree_digest": review["tree_digest"],
        "change_reason": expected_reason,
        "already_activated": successor is not None,
        "authorized_action": None,
    }


__all__ = [
    "FRAME_EVENT_TYPES",
    "FRAME_GATE_EVENT_TYPE",
    "FRAME_INQUIRY_EVENT_TYPE",
    "FRAME_DECISION_EVENT_TYPE",
    "FRAME_PILOT_AUTH_EVENT_TYPE",
    "FRAME_PILOT_RESULT_EVENT_TYPE",
    "FRAME_ADOPTION_REVIEW_EVENT_TYPE",
    "FRAME_POLICY_ADOPTION_EVENT_TYPE",
    "FRAME_REVOCATION_EVENT_TYPE",
    "POLICY_ADOPTION_POLICY_ID",
    "POLICY_ADOPTION_POLICY",
    "POLICY_ADOPTION_POLICY_DIGEST",
    "FrameTransitionPlan",
    "FrameTransitionState",
    "classify_frame_change",
    "controlled_change_reason",
    "plan_gate_a",
    "plan_inquiry_open",
    "plan_inquiry_decision",
    "plan_pilot_authorization",
    "plan_pilot_result",
    "plan_adoption_review",
    "plan_policy_adoption",
    "plan_authority_revocation",
    "reduce_frame_transition_state",
    "rival_fingerprint",
    "validate_frame_transition_commit_time",
    "validate_controlled_activation",
]
