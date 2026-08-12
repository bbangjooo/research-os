"""Pure replay and prospective validation for versioned scientific state."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from research_os.artifacts.catalog import ArtifactRecord
from research_os.contracts import GateEvaluation, ResultEnvelope, TerminalStatus
from research_os.contracts.common import canonical_json, sha256_json
from research_os.errors import IntegrityError, LifecycleError, ScientificStateError
from research_os.kernel._canonical import strict_json_loads
from research_os.kernel.events import Event
from research_os.kernel.ids import new_experiment_id, stable_id, validate_namespaced_id
from research_os.kernel.lifecycle import (
    TERMINAL_STATES,
    LifecycleState,
    coerce_state,
)

from .contracts import (
    SCIENCE_STATE_VERSION,
    EvaluationScope,
    EvaluationSeal,
    StudyContract,
    is_safe_integer,
)
from .contracts import generation_id as derive_generation_id
from .diagnoses import Diagnosis, DiagnosisEventPayload
from .diagnoses import diagnosis_id as derive_diagnosis_id
from .proposals import Proposal, canonical_json_diff_pointers, proposal_id

GENERATION_EVENT_TYPE = "research.study_generation_opened.v1"
DIAGNOSIS_EVENT_TYPE = "research.experiment_diagnosed.v1"
_REGISTRATION_EVENT_TYPE = "EXPERIMENT_REGISTERED"
_ARTIFACT_EVENT_TYPE = "ARTIFACT_RECORDED"
_GENERATION_PAYLOAD_KEYS = frozenset(
    {
        "science_state_version",
        "generation_id",
        "study_contract_digest",
        "evaluation_seal",
        "evaluation_seal_digest",
        "predecessor_generation_id",
        "change_reason",
        "contract",
        "authorized_action",
    }
)
_REGISTRATION_SCIENCE_KEYS = frozenset(
    {
        "science_state_version",
        "generation_id",
        "study_contract_digest",
        "evaluation_seal_digest",
        "budget_debit",
    }
)
_TYPED_REGISTRATION_KEYS = frozenset(
    {
        "proposal",
        "proposal_digest",
        "proposal_id",
        "evaluation_scope_id",
    }
)
_TYPED_BASELINE_KEYS = frozenset(
    {
        "science_state_version",
        "generation_id",
        "study_contract_digest",
        "evaluation_seal_digest",
        "evaluation_scope_id",
        "evaluation_scope",
    }
)
_LEGACY_GRAPH_KEYS = frozenset({"graph_metadata_version", "graph_action", "scientific_change"})
_BUDGET_DEBIT_KEYS = frozenset(
    {
        "attempts",
        "retries",
        "reserved_elapsed_milliseconds",
        "reserved_cost_microunits",
    }
)

_NON_RETRYABLE_TERMINAL_STATES = frozenset(
    {
        LifecycleState.ACCEPTED,
        LifecycleState.SUCCEEDED,
        LifecycleState.COMPLETED,
        LifecycleState.INVALID_EXPERIMENT,
        LifecycleState.INVALID,
        LifecycleState.REJECTED,
        LifecycleState.VALIDATED,
        LifecycleState.UNTRUSTED,
    }
)

_DECISION_KEYS = frozenset(
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
_RESULT_BASE_KEYS = frozenset(
    {
        "metrics",
        "constraints",
        "resource_usage",
        "artifacts",
        "provenance",
        "diagnostics",
    }
)
_ARTIFACT_EVENT_KEYS = frozenset((*ArtifactRecord._FIELDS, "authorized_action"))
_DIAGNOSIS_PAYLOAD_KEYS = frozenset(
    {
        "science_state_version",
        "generation_id",
        "study_contract_digest",
        "evaluation_seal_digest",
        "compatibility_digest",
        "diagnosis",
        "diagnosis_digest",
        "diagnosis_id",
        "authorized_action",
    }
)
_STOP_REASON_ORDER = ("UNTRUSTED", "BUDGET_EXHAUSTED", "ALL_CLASSES_CLOSED")
_BUDGET_DIMENSION_ORDER = (
    "attempts",
    "elapsed_milliseconds",
    "cost_microunits",
)


def _error(
    code: str,
    message: str,
    **details: object,
) -> ScientificStateError:
    return ScientificStateError(code, message, details=details)


def _normalized_event_type(value: str) -> str:
    return value.strip().upper().replace(".", "_").replace("-", "_")


def _event_parts(
    event: Event | Mapping[str, Any],
    *,
    expected_project_id: str,
) -> tuple[str, Mapping[str, Any]]:
    if isinstance(event, Event):
        event_type = event.event_type
        payload: Any = event.payload
        event_project_id: Any = event.project_id
    elif isinstance(event, Mapping):
        event_type = event.get("event_type")
        payload = event.get("payload")
        event_project_id = event.get("project_id", expected_project_id)
    else:
        raise _error(
            "STUDY_EVENT_INVALID",
            "scientific state input must contain event objects",
        )
    if not isinstance(event_type, str) or not event_type.strip():
        raise _error("STUDY_EVENT_INVALID", "event_type must be non-empty text")
    if not isinstance(payload, Mapping):
        raise _error("STUDY_EVENT_INVALID", "event payload must be an object")
    if event_project_id != expected_project_id:
        raise _error(
            "STUDY_EVENT_INVALID",
            "event project does not match the scientific-state project",
            expected_project_id=expected_project_id,
            event_project_id=event_project_id,
        )
    return event_type, payload


def _event_identity(
    event: Event | Mapping[str, Any],
) -> tuple[str | None, str | None, int | None]:
    """Return envelope identity without making loose legacy events authoritative."""

    if isinstance(event, Event):
        return event.event_id, event.hash, event.sequence
    event_id = event.get("event_id")
    event_hash = event.get("hash")
    sequence = event.get("sequence")
    return (
        event_id if isinstance(event_id, str) else None,
        event_hash if isinstance(event_hash, str) else None,
        sequence
        if isinstance(sequence, int) and not isinstance(sequence, bool) and sequence > 0
        else None,
    )


def _literal_version(value: Any, *, code: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        raise _error(code, "science_state_version must be integer literal 1")


def _generation_identifier(value: Any, *, code: str, field: str) -> str:
    if not isinstance(value, str):
        raise _error(code, f"{field} must be a generation ID")
    try:
        identifier = validate_namespaced_id(value, "generation")
    except (TypeError, ValueError) as exc:
        raise _error(code, f"{field} must be a generation ID") from exc
    if identifier != value:
        raise _error(code, f"{field} must be a canonical generation ID")
    return identifier


@dataclass(frozen=True, slots=True)
class ScopeBaseline:
    """One active-generation baseline bound to a declared evaluation scope."""

    baseline_id: str
    generation_id: str
    compatibility_digest: str
    evaluation_scope_id: str
    evaluation_scope: EvaluationScope
    primary_metric: str | None = None


@dataclass(frozen=True, slots=True)
class ArtifactEventEvidence:
    """One canonical artifact event retained for Diagnosis evidence binding."""

    experiment_id: str | None
    event_id: str
    event_hash: str
    event_sequence: int
    payload_json: str

    @property
    def payload(self) -> dict[str, Any]:
        value = strict_json_loads(self.payload_json)
        if not isinstance(value, dict):  # pragma: no cover - constructor invariant
            raise _error("STUDY_STATE_INVALID", "stored artifact payload is not an object")
        return cast(dict[str, Any], value)


@dataclass(frozen=True, slots=True)
class DiagnosisRecord:
    """One accepted canonical Diagnosis plus its immutable event identity."""

    diagnosis_id: str
    diagnosis_digest: str
    diagnosis_event_id: str
    diagnosis_event_hash: str
    event_sequence: int
    diagnosis: Diagnosis

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnosis_id": self.diagnosis_id,
            "diagnosis_digest": self.diagnosis_digest,
            "diagnosis_event_id": self.diagnosis_event_id,
            "diagnosis_event_hash": self.diagnosis_event_hash,
            "event_sequence": self.event_sequence,
            "diagnosis": self.diagnosis.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ClassState:
    """Derived lifecycle and evidentiary support for one hypothesis class."""

    project_id: str
    generation_id: str
    hypothesis_class_id: str
    lifecycle: str
    support: str
    replication_required: bool
    conclusive_rejection_limit: int
    conclusive_rejections: int
    conclusive_diagnosis_ids: tuple[str, ...]
    provisional_diagnosis_ids: tuple[str, ...]
    replicated_diagnosis_ids: tuple[str, ...]
    inconclusive_diagnosis_ids: tuple[str, ...]
    closure_reason: str | None
    closure_evidence: Mapping[str, Any] | None

    @property
    def class_state_id(self) -> str:
        return stable_id(
            "classstate",
            self.project_id,
            self.generation_id,
            self.hypothesis_class_id,
        )

    def body_dict(self) -> dict[str, Any]:
        return {
            "class_state_schema_version": 1,
            "generation_id": self.generation_id,
            "hypothesis_class_id": self.hypothesis_class_id,
            "lifecycle": self.lifecycle,
            "support": self.support,
            "replication_required": self.replication_required,
            "conclusive_rejection_limit": self.conclusive_rejection_limit,
            "conclusive_rejections": self.conclusive_rejections,
            "conclusive_diagnosis_ids": list(self.conclusive_diagnosis_ids),
            "provisional_diagnosis_ids": list(self.provisional_diagnosis_ids),
            "replicated_diagnosis_ids": list(self.replicated_diagnosis_ids),
            "inconclusive_diagnosis_ids": list(self.inconclusive_diagnosis_ids),
            "closure_reason": self.closure_reason,
            "closure_evidence": (
                None if self.closure_evidence is None else dict(self.closure_evidence)
            ),
            "authorized_action": None,
        }

    @property
    def class_state_digest(self) -> str:
        return sha256_json(self.body_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "class_state_id": self.class_state_id,
            "class_state_digest": self.class_state_digest,
            "class_state": self.body_dict(),
        }


@dataclass(frozen=True, slots=True)
class DiagnosisPlan:
    """Prospective idempotent append plan for one validated Diagnosis body."""

    project_id: str
    diagnosis: Diagnosis
    diagnosis_digest: str
    diagnosis_id: str
    append_required: bool
    existing_event_id: str | None
    _payload: DiagnosisEventPayload

    @property
    def event_type(self) -> str:
        return DIAGNOSIS_EVENT_TYPE

    @property
    def payload(self) -> dict[str, Any]:
        return self._payload.to_dict()


@dataclass(frozen=True, slots=True)
class ScientificRegistration:
    """Canonical typed registration evidence retained for pure transitions."""

    experiment_id: str
    generation_id: str
    candidate_digest: str
    candidate_json: str
    proposal: Proposal
    proposal_digest: str
    proposal_id: str
    parent_id: str | None
    evaluation_scope_id: str
    compatibility_digest: str
    baseline_id: str
    attempt: int
    retry_of: str | None
    primary_metric: str | None = None
    terminal_status: str | None = None
    retryable: bool = False
    terminal_event_type: str | None = None
    terminal_event_id: str | None = None
    terminal_event_hash: str | None = None
    terminal_event_sequence: int | None = None
    terminal_payload_json: str | None = None

    @property
    def candidate(self) -> dict[str, Any]:
        value = strict_json_loads(self.candidate_json)
        if not isinstance(value, dict):  # pragma: no cover - constructor invariant
            raise _error(
                "STUDY_STATE_INVALID",
                "stored candidate JSON is not an object",
                experiment_id=self.experiment_id,
            )
        return cast(dict[str, Any], value)

    @property
    def is_terminal(self) -> bool:
        return self.terminal_status is not None

    @property
    def terminal_payload(self) -> dict[str, Any] | None:
        if self.terminal_payload_json is None:
            return None
        value = strict_json_loads(self.terminal_payload_json)
        if not isinstance(value, dict):  # pragma: no cover - constructor invariant
            raise _error(
                "STUDY_STATE_INVALID",
                "stored terminal payload JSON is not an object",
                experiment_id=self.experiment_id,
            )
        return cast(dict[str, Any], value)


@dataclass(frozen=True, slots=True)
class ScientificState:
    """The replay-derived active generation and its reservation ledger."""

    project_id: str
    generation_count: int = 0
    active_generation_id: str | None = None
    contract: StudyContract | None = None
    evaluation_seal: EvaluationSeal | None = None
    attempts_used: int = 0
    retries_used: int = 0
    elapsed_reserved_milliseconds: int = 0
    cost_reserved_microunits: int | None = None
    legacy_unstructured_registrations: int = 0
    scope_baselines: tuple[ScopeBaseline, ...] = ()
    registrations: tuple[ScientificRegistration, ...] = ()
    proposal_ids: frozenset[str] = frozenset()
    used_candidate_scope_keys: frozenset[tuple[str, str, str]] = frozenset()
    replication_count: int = 0
    artifact_events: tuple[ArtifactEventEvidence, ...] = ()
    diagnoses: tuple[DiagnosisRecord, ...] = ()
    historical_diagnosis_payloads: tuple[tuple[str, str], ...] = ()

    @property
    def study_contract_digest(self) -> str | None:
        return None if self.contract is None else self.contract.digest

    @property
    def evaluation_seal_digest(self) -> str | None:
        return None if self.evaluation_seal is None else self.evaluation_seal.digest

    @property
    def proposal_count(self) -> int:
        return len(self.proposal_ids)

    @property
    def used_candidate_scope_pairs(self) -> int:
        return len(self.used_candidate_scope_keys)

    @property
    def diagnosis_count(self) -> int:
        return len(self.diagnoses)

    @property
    def pending_diagnosis_experiment_ids(self) -> tuple[str, ...]:
        diagnosed = {item.diagnosis.experiment_id for item in self.diagnoses}
        pending = [
            item
            for item in self.registrations
            if item.is_terminal and item.experiment_id not in diagnosed
        ]
        pending.sort(
            key=lambda item: (
                item.terminal_event_sequence
                if item.terminal_event_sequence is not None
                else 2**63,
                item.experiment_id,
            )
        )
        return tuple(item.experiment_id for item in pending)

    @property
    def class_states(self) -> tuple[ClassState, ...]:
        return _derive_class_states(self)

    @property
    def study_stop(self) -> dict[str, Any]:
        return _derive_study_stop(self)

    @property
    def semantic_frontier(self) -> dict[str, Any]:
        return _derive_semantic_frontier(self)

    @property
    def retry_frontier(self) -> dict[str, Any]:
        return _derive_retry_frontier(self)

    def registration(self, experiment_id: str) -> ScientificRegistration | None:
        for registration in reversed(self.registrations):
            if registration.experiment_id == experiment_id:
                return registration
        return None

    def baseline_for_scope(
        self,
        evaluation_scope_id: str,
    ) -> ScopeBaseline | None:
        for baseline in reversed(self.scope_baselines):
            if baseline.evaluation_scope_id == evaluation_scope_id:
                return baseline
        return None

    def to_dict(self) -> dict[str, Any]:
        budget: dict[str, Any] | None
        if self.contract is None:
            budget = None
        else:
            declared = self.contract.budget
            cost: dict[str, Any] | None
            if declared.max_cost_microunits is None:
                cost = None
            else:
                reserved_cost = self.cost_reserved_microunits
                if reserved_cost is None:  # pragma: no cover - defensive invariant
                    raise _error(
                        "STUDY_STATE_INVALID",
                        "configured cost ledger cannot be null",
                    )
                cost = {
                    "unit": declared.cost_unit,
                    "limit": declared.max_cost_microunits,
                    "reserved": reserved_cost,
                    "remaining": declared.max_cost_microunits - reserved_cost,
                }
            budget = {
                "attempts": {
                    "limit": declared.max_attempts,
                    "used": self.attempts_used,
                    "remaining": declared.max_attempts - self.attempts_used,
                },
                "retries": {
                    "limit": declared.max_retries,
                    "used": self.retries_used,
                    "remaining": declared.max_retries - self.retries_used,
                },
                "elapsed_milliseconds": {
                    "limit": declared.max_elapsed_milliseconds,
                    "reserved": self.elapsed_reserved_milliseconds,
                    "remaining": (
                        declared.max_elapsed_milliseconds - self.elapsed_reserved_milliseconds
                    ),
                },
                "cost_microunits": cost,
            }
        result = {
            "science_state_version": SCIENCE_STATE_VERSION,
            "generation_count": self.generation_count,
            "active_generation_id": self.active_generation_id,
            "study_contract_digest": self.study_contract_digest,
            "evaluation_seal": (
                None if self.evaluation_seal is None else self.evaluation_seal.to_dict()
            ),
            "evaluation_seal_digest": self.evaluation_seal_digest,
            "contract": None if self.contract is None else self.contract.to_dict(),
            "budget": budget,
            "legacy_unstructured_registrations": (self.legacy_unstructured_registrations),
        }
        if self.contract is not None and self.contract.schema_version == 2:
            result.update(
                {
                    "proposal_count": self.proposal_count,
                    "replication_count": self.replication_count,
                    "used_candidate_scope_pairs": (self.used_candidate_scope_pairs),
                    "diagnosis_count": self.diagnosis_count,
                    "diagnoses": [item.to_dict() for item in self.diagnoses],
                    "pending_diagnosis_experiment_ids": list(
                        self.pending_diagnosis_experiment_ids
                    ),
                    "class_states": [item.to_dict() for item in self.class_states],
                    "study_stop": self.study_stop,
                    "semantic_frontier": self.semantic_frontier,
                    "retry_frontier": self.retry_frontier,
                }
            )
        return result


def _diagnosis_for(
    state: ScientificState,
    experiment_id: str,
) -> DiagnosisRecord | None:
    for item in reversed(state.diagnoses):
        if item.diagnosis.experiment_id == experiment_id:
            return item
    return None


def _latest_registration_ids(state: ScientificState) -> frozenset[str]:
    latest: dict[str, str] = {}
    for item in state.registrations:
        latest[item.proposal_id] = item.experiment_id
    return frozenset(latest.values())


def _terminal_decision(registration: ScientificRegistration) -> Mapping[str, Any] | None:
    payload = registration.terminal_payload
    if payload is None:
        return None
    decision = payload.get("decision")
    return decision if isinstance(decision, Mapping) else None


def _all_hard_support_gates_pass(decision: Mapping[str, Any]) -> bool:
    gates = decision.get("gate_evaluations")
    if not isinstance(gates, list):
        return False
    return all(
        isinstance(item, Mapping)
        and item.get("role") in {"hard", "support"}
        and item.get("passed") is True
        for item in gates
    )


def _is_evidence_supported(
    state: ScientificState,
    registration: ScientificRegistration,
) -> bool:
    if registration.experiment_id not in _latest_registration_ids(state):
        return False
    if _diagnosis_for(state, registration.experiment_id) is None:
        return False
    payload = registration.terminal_payload
    decision = _terminal_decision(registration)
    if payload is None or decision is None or "error" in payload:
        return False
    margin = decision.get("promotion_margin")
    return (
        registration.terminal_status == "VALIDATED"
        and payload.get("reason_code") == "PRIMARY_METRIC_IMPROVED"
        and payload.get("verified") is True
        and decision.get("status") == "VALIDATED"
        and decision.get("reason_code") == "PRIMARY_METRIC_IMPROVED"
        and isinstance(margin, (int, float))
        and not isinstance(margin, bool)
        and margin > 0
        and _all_hard_support_gates_pass(decision)
    )


def _is_qualifying_replication(
    state: ScientificState,
    registration: ScientificRegistration,
) -> bool:
    if registration.proposal.action != "replicate" or not _is_evidence_supported(
        state, registration
    ):
        return False
    if registration.parent_id is None:
        return False
    parent = state.registration(registration.parent_id)
    if parent is None or not _is_evidence_supported(state, parent):
        return False
    return (
        parent.candidate_digest == registration.candidate_digest
        and parent.evaluation_scope_id != registration.evaluation_scope_id
    )


def _is_conclusive_rejection(registration: ScientificRegistration) -> bool:
    payload = registration.terminal_payload
    decision = _terminal_decision(registration)
    if payload is None or decision is None or "error" in payload:
        return False
    margin = decision.get("promotion_margin")
    return (
        registration.terminal_status == "REJECTED"
        and payload.get("reason_code") == "NO_MEANINGFUL_IMPROVEMENT"
        and payload.get("verified") is True
        and decision.get("status") == "REJECTED"
        and decision.get("reason_code") == "NO_MEANINGFUL_IMPROVEMENT"
        and isinstance(margin, (int, float))
        and not isinstance(margin, bool)
        and margin <= 0
        and _all_hard_support_gates_pass(decision)
    )


def _class_state_by_id(
    state: ScientificState,
    hypothesis_class_id: str,
) -> ClassState | None:
    return next(
        (
            item
            for item in state.class_states
            if item.hypothesis_class_id == hypothesis_class_id
        ),
        None,
    )


def _replication_scope_ids(state: ScientificState) -> tuple[str, ...]:
    if state.contract is None:
        return ()
    return tuple(
        item.id for item in state.contract.evaluation_scopes if item.role == "replication"
    )


def _unused_replication_scope_ids(
    state: ScientificState,
    candidate_digest: str,
) -> tuple[str, ...]:
    used = {
        item.evaluation_scope_id
        for item in state.registrations
        if item.candidate_digest == candidate_digest
        and item.evaluation_scope_id in _replication_scope_ids(state)
    }
    return tuple(item for item in _replication_scope_ids(state) if item not in used)


def _has_qualifying_supported_child(
    state: ScientificState,
    registration: ScientificRegistration,
) -> bool:
    return any(
        item.parent_id == registration.experiment_id
        and _is_evidence_supported(state, item)
        for item in state.registrations
    )


def _derive_class_states(state: ScientificState) -> tuple[ClassState, ...]:
    if (
        state.contract is None
        or state.contract.schema_version != 2
        or state.active_generation_id is None
    ):
        return ()
    result: list[ClassState] = []
    for declared in state.contract.hypothesis_classes:
        conclusive: list[str] = []
        provisional: list[str] = []
        replicated: list[str] = []
        inconclusive: list[str] = []
        counted_proposals: set[str] = set()
        closure_record: DiagnosisRecord | None = None
        for diagnosis_record in state.diagnoses:
            diagnosis = diagnosis_record.diagnosis
            if diagnosis.hypothesis_class_id != declared.id:
                continue
            registration = state.registration(diagnosis.experiment_id)
            if registration is None:  # pragma: no cover - Diagnosis binding invariant
                inconclusive.append(diagnosis_record.diagnosis_id)
                continue
            if (
                _is_conclusive_rejection(registration)
                and registration.proposal_id not in counted_proposals
            ):
                counted_proposals.add(registration.proposal_id)
                conclusive.append(diagnosis_record.diagnosis_id)
                if len(conclusive) == declared.conclusive_rejection_limit:
                    closure_record = diagnosis_record
            elif _is_qualifying_replication(state, registration):
                replicated.append(diagnosis_record.diagnosis_id)
            elif (
                registration.proposal.action != "replicate"
                and _is_evidence_supported(state, registration)
            ):
                provisional.append(diagnosis_record.diagnosis_id)
            else:
                inconclusive.append(diagnosis_record.diagnosis_id)

        closed = len(conclusive) >= declared.conclusive_rejection_limit
        support = "replicated" if replicated else "provisional" if provisional else "none"
        replication_required = False
        if not closed and support == "provisional":
            for diagnosis_id_value in provisional:
                record = next(
                    item for item in state.diagnoses if item.diagnosis_id == diagnosis_id_value
                )
                registration = state.registration(record.diagnosis.experiment_id)
                if (
                    registration is not None
                    and not _has_qualifying_supported_child(state, registration)
                    and bool(
                        _unused_replication_scope_ids(state, registration.candidate_digest)
                    )
                ):
                    replication_required = True
                    break

        closure_evidence: dict[str, Any] | None = None
        if closure_record is not None:
            registration = state.registration(closure_record.diagnosis.experiment_id)
            assert registration is not None
            closure_evidence = {
                "diagnosis_id": closure_record.diagnosis_id,
                "diagnosis_digest": closure_record.diagnosis_digest,
                "diagnosis_event_id": closure_record.diagnosis_event_id,
                "diagnosis_event_hash": closure_record.diagnosis_event_hash,
                "terminal_event_id": registration.terminal_event_id,
                "terminal_event_hash": registration.terminal_event_hash,
            }
        result.append(
            ClassState(
                project_id=state.project_id,
                generation_id=state.active_generation_id,
                hypothesis_class_id=declared.id,
                lifecycle="closed" if closed else "open",
                support=support,
                replication_required=replication_required,
                conclusive_rejection_limit=declared.conclusive_rejection_limit,
                conclusive_rejections=len(conclusive),
                conclusive_diagnosis_ids=tuple(conclusive),
                provisional_diagnosis_ids=tuple(provisional),
                replicated_diagnosis_ids=tuple(replicated),
                inconclusive_diagnosis_ids=tuple(inconclusive),
                closure_reason=(
                    "CONCLUSIVE_REJECTION_LIMIT_REACHED" if closed else None
                ),
                closure_evidence=closure_evidence,
            )
        )
    return tuple(result)


def _budget_exhausted_dimensions(state: ScientificState) -> tuple[str, ...]:
    if state.contract is None:
        return ()
    budget = state.contract.budget
    exhausted: set[str] = set()
    if state.attempts_used + 1 > budget.max_attempts:
        exhausted.add("attempts")
    if (
        state.elapsed_reserved_milliseconds
        + budget.elapsed_reservation_per_attempt_milliseconds
        > budget.max_elapsed_milliseconds
    ):
        exhausted.add("elapsed_milliseconds")
    if budget.max_cost_microunits is not None:
        reserved = state.cost_reserved_microunits
        per_attempt = budget.cost_reservation_per_attempt_microunits
        if (
            reserved is None
            or per_attempt is None
            or reserved + per_attempt > budget.max_cost_microunits
        ):
            exhausted.add("cost_microunits")
    return tuple(item for item in _BUDGET_DIMENSION_ORDER if item in exhausted)


def _derive_study_stop(state: ScientificState) -> dict[str, Any]:
    untrusted = sorted(
        (
            item
            for item in state.registrations
            if item.terminal_status == "UNTRUSTED"
        ),
        key=lambda item: (
            item.terminal_event_sequence
            if item.terminal_event_sequence is not None
            else 2**63,
            item.experiment_id,
        ),
    )
    dimensions = _budget_exhausted_dimensions(state)
    class_states = state.class_states
    all_closed = bool(class_states) and all(
        item.lifecycle == "closed" for item in class_states
    )
    present: set[str] = set()
    if untrusted:
        present.add("UNTRUSTED")
    if dimensions:
        present.add("BUDGET_EXHAUSTED")
    if all_closed:
        present.add("ALL_CLASSES_CLOSED")
    reasons = [item for item in _STOP_REASON_ORDER if item in present]
    return {
        "stopped": bool(reasons),
        "reasons": reasons,
        "untrusted_experiment_ids": [item.experiment_id for item in untrusted],
        "budget_exhausted_dimensions": list(dimensions),
        "all_classes_closed": all_closed,
        "authorized_action": None,
    }


def _open_class_ids(state: ScientificState) -> frozenset[str]:
    return frozenset(
        item.hypothesis_class_id
        for item in state.class_states
        if item.lifecycle == "open"
    )


def _ranked_semantic_leaves(
    state: ScientificState,
) -> list[tuple[ScientificRegistration, DiagnosisRecord, str]]:
    open_ids = _open_class_ids(state)
    leaves: list[tuple[ScientificRegistration, DiagnosisRecord, str]] = []
    for registration in state.registrations:
        if (
            registration.proposal.hypothesis_class_id not in open_ids
            or not _is_evidence_supported(state, registration)
            or _has_qualifying_supported_child(state, registration)
        ):
            continue
        diagnosis = _diagnosis_for(state, registration.experiment_id)
        assert diagnosis is not None
        maturity = (
            "replicated" if _is_qualifying_replication(state, registration) else "provisional"
        )
        leaves.append((registration, diagnosis, maturity))
    leaves.sort(
        key=lambda item: (
            0 if item[2] == "replicated" else 1,
            -cast(int, item[0].terminal_event_sequence),
            item[0].experiment_id,
        )
    )
    return leaves


def _derive_semantic_frontier(state: ScientificState) -> dict[str, Any]:
    cap = 0 if state.contract is None else state.contract.frontier.max_active_branches
    stop = state.study_stop
    if stop["stopped"]:
        return {
            "max_active_branches": cap,
            "eligible_total": 0,
            "returned": 0,
            "truncated": False,
            "blocked_by": list(stop["reasons"]),
            "entries": [],
            "authorized_action": None,
        }
    ranked = _ranked_semantic_leaves(state)
    diverse: list[tuple[ScientificRegistration, DiagnosisRecord, str]] = []
    remaining: list[tuple[ScientificRegistration, DiagnosisRecord, str]] = []
    seen_classes: set[str] = set()
    for item in ranked:
        class_id = item[0].proposal.hypothesis_class_id
        if class_id not in seen_classes:
            seen_classes.add(class_id)
            diverse.append(item)
        else:
            remaining.append(item)
    selected = (diverse + remaining)[:cap]
    entries: list[dict[str, Any]] = []
    for registration, diagnosis, maturity in selected:
        actions = ["ablate", "exploit"]
        if _unused_replication_scope_ids(state, registration.candidate_digest):
            actions.append("replicate")
        entries.append(
            {
                "experiment_id": registration.experiment_id,
                "proposal_id": registration.proposal_id,
                "diagnosis_id": diagnosis.diagnosis_id,
                "hypothesis_class_id": registration.proposal.hypothesis_class_id,
                "evaluation_scope_id": registration.evaluation_scope_id,
                "action": registration.proposal.action,
                "parent_experiment_id": registration.parent_id,
                "candidate_digest": registration.candidate_digest,
                "terminal_event_sequence": registration.terminal_event_sequence,
                "maturity": maturity,
                "eligible_actions": actions,
                "authorized_action": None,
            }
        )
    return {
        "max_active_branches": cap,
        "eligible_total": len(ranked),
        "returned": len(entries),
        "truncated": len(ranked) > len(entries),
        "blocked_by": [],
        "entries": entries,
        "authorized_action": None,
    }


def _derive_retry_frontier(state: ScientificState) -> dict[str, Any]:
    stop = state.study_stop
    if stop["stopped"]:
        return {
            "eligible_total": 0,
            "blocked_by": list(stop["reasons"]),
            "entries": [],
            "authorized_action": None,
        }
    if (
        state.contract is not None
        and state.retries_used + 1 > state.contract.budget.max_retries
    ):
        return {
            "eligible_total": 0,
            "blocked_by": ["RETRY_BUDGET_EXHAUSTED"],
            "entries": [],
            "authorized_action": None,
        }
    latest = _latest_registration_ids(state)
    open_ids = _open_class_ids(state)
    eligible: list[tuple[ScientificRegistration, DiagnosisRecord]] = []
    for registration in state.registrations:
        diagnosis = _diagnosis_for(state, registration.experiment_id)
        if (
            registration.experiment_id in latest
            and registration.proposal.hypothesis_class_id in open_ids
            and registration.is_terminal
            and registration.retryable
            and diagnosis is not None
        ):
            eligible.append((registration, diagnosis))
    eligible.sort(
        key=lambda item: (
            -cast(int, item[0].terminal_event_sequence),
            item[0].experiment_id,
        )
    )
    return {
        "eligible_total": len(eligible),
        "blocked_by": [],
        "entries": [
            {
                "experiment_id": registration.experiment_id,
                "proposal_id": registration.proposal_id,
                "diagnosis_id": diagnosis.diagnosis_id,
                "hypothesis_class_id": registration.proposal.hypothesis_class_id,
                "evaluation_scope_id": registration.evaluation_scope_id,
                "attempt": registration.attempt,
                "retry_of": registration.retry_of,
                "terminal_event_sequence": registration.terminal_event_sequence,
                "authorized_action": None,
            }
            for registration, diagnosis in eligible
        ],
        "authorized_action": None,
    }


@dataclass(frozen=True, slots=True)
class GenerationPlan:
    project_id: str
    generation_id: str
    append_required: bool
    contract: StudyContract
    evaluation_seal: EvaluationSeal
    predecessor_generation_id: str | None
    change_reason: str | None

    @property
    def event_type(self) -> str:
        return GENERATION_EVENT_TYPE

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "science_state_version": SCIENCE_STATE_VERSION,
            "generation_id": self.generation_id,
            "study_contract_digest": self.contract.digest,
            "evaluation_seal": self.evaluation_seal.to_dict(),
            "evaluation_seal_digest": self.evaluation_seal.digest,
            "predecessor_generation_id": self.predecessor_generation_id,
            "change_reason": self.change_reason,
            "contract": self.contract.to_dict(),
            "authorized_action": None,
        }


def plan_diagnosis_append(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    diagnosis: Diagnosis | Mapping[str, Any],
) -> DiagnosisPlan:
    """Validate and plan one idempotent canonical Diagnosis append."""

    parsed = (
        Diagnosis.from_mapping(diagnosis.to_dict())
        if isinstance(diagnosis, Diagnosis)
        else Diagnosis.from_mapping(diagnosis)
    )
    state = reduce_scientific_state(events, project_id=project_id)
    # Idempotency is log-wide rather than active-generation-local.  A genuine
    # successor resets the active scientific projection, but it must not turn
    # a delayed network retry of an already durable Diagnosis into a false
    # generation/experiment error.  The full replay above still rejects any
    # actually persisted duplicate or corrupt Diagnosis event.
    for event in events:
        event_type, raw_payload = _event_parts(
            event,
            expected_project_id=project_id,
        )
        if event_type != DIAGNOSIS_EVENT_TYPE:
            continue
        existing_payload = DiagnosisEventPayload.from_mapping(
            raw_payload,
            project_id=project_id,
        )
        if existing_payload.diagnosis.experiment_id != parsed.experiment_id:
            continue
        event_id, _, _ = _event_identity(event)
        if event_id is None:  # pragma: no cover - reducer rejects this first
            raise _error(
                "DIAGNOSIS_INVALID",
                "persisted Diagnosis requires a canonical event identity",
                path="$",
            )
        if existing_payload.diagnosis.to_dict() != parsed.to_dict():
            raise _error(
                "DIAGNOSIS_ALREADY_RECORDED",
                "the experiment already has a canonical Diagnosis",
                experiment_id=parsed.experiment_id,
                diagnosis_id=existing_payload.diagnosis_id,
                path="$.experiment_id",
            )
        return DiagnosisPlan(
            project_id=project_id,
            diagnosis=parsed,
            diagnosis_digest=existing_payload.diagnosis_digest,
            diagnosis_id=existing_payload.diagnosis_id,
            append_required=False,
            existing_event_id=event_id,
            _payload=existing_payload,
        )
    if (
        state.active_generation_id is None
        or state.contract is None
        or state.evaluation_seal is None
        or state.contract.schema_version != 2
    ):
        raise _error(
            "DIAGNOSIS_EXPERIMENT_UNKNOWN",
            "Diagnosis requires an active version-two typed registration",
            experiment_id=parsed.experiment_id,
        )
    payload = DiagnosisEventPayload.from_diagnosis(
        project_id=project_id,
        generation_id=state.active_generation_id,
        study_contract_digest=state.contract.digest,
        evaluation_seal_digest=state.evaluation_seal.digest,
        compatibility_digest=state.evaluation_seal.compatibility_digest,
        diagnosis=parsed,
    )
    _validate_diagnosis_binding(state, payload)
    return DiagnosisPlan(
        project_id=project_id,
        diagnosis=parsed,
        diagnosis_digest=payload.diagnosis_digest,
        diagnosis_id=payload.diagnosis_id,
        append_required=True,
        existing_event_id=None,
        _payload=payload,
    )


def build_diagnosis_template(
    state: ScientificState,
    *,
    experiment_id: str | None = None,
) -> dict[str, Any]:
    """Build one read-only Diagnosis body with only agent judgment left blank."""

    if (
        state.active_generation_id is None
        or state.contract is None
        or state.evaluation_seal is None
        or state.contract.schema_version != 2
    ):
        raise _error(
            "DIAGNOSIS_TEMPLATE_UNAVAILABLE",
            "Diagnosis authoring requires an active version-two generation",
        )
    pending = state.pending_diagnosis_experiment_ids
    if experiment_id is None:
        if not pending:
            raise _error(
                "DIAGNOSIS_TEMPLATE_NONE_PENDING",
                "no terminal experiment is awaiting Diagnosis",
            )
        if len(pending) != 1:
            raise _error(
                "DIAGNOSIS_TEMPLATE_EXPERIMENT_REQUIRED",
                "select one pending experiment explicitly",
                pending_experiment_ids=list(pending),
            )
        experiment_id = pending[0]
    registration = state.registration(experiment_id)
    if registration is None:
        raise _error(
            "DIAGNOSIS_TEMPLATE_EXPERIMENT_UNKNOWN",
            "Diagnosis template experiment is not registered in the active generation",
            experiment_id=experiment_id,
        )
    if experiment_id not in pending:
        raise _error(
            "DIAGNOSIS_TEMPLATE_EXPERIMENT_NOT_PENDING",
            "Diagnosis template requires a pending terminal experiment",
            experiment_id=experiment_id,
        )
    if (
        registration.terminal_event_id is None
        or registration.terminal_event_hash is None
        or registration.terminal_payload is None
    ):  # pragma: no cover - pending invariant
        raise _error(
            "DIAGNOSIS_TEMPLATE_EXPERIMENT_NOT_PENDING",
            "Diagnosis template experiment lacks canonical terminal evidence",
            experiment_id=experiment_id,
        )
    artifact_evidence = [
        {
            "artifact_id": record.artifact_id,
            "artifact_digest": record.digest,
            "event_id": event.event_id,
            "event_hash": event.event_hash,
        }
        for event, record in _validated_artifact_records(state, registration)
    ]
    return {
        "diagnosis_schema_version": 1,
        "generation_id": state.active_generation_id,
        "compatibility_digest": registration.compatibility_digest,
        "experiment_id": registration.experiment_id,
        "proposal_id": registration.proposal_id,
        "proposal_digest": registration.proposal_digest,
        "hypothesis_class_id": registration.proposal.hypothesis_class_id,
        "evaluation_scope_id": registration.evaluation_scope_id,
        "terminal_evidence": {
            "experiment_id": registration.experiment_id,
            "event_id": registration.terminal_event_id,
            "event_hash": registration.terminal_event_hash,
        },
        "artifact_evidence": artifact_evidence,
        "observation": _expected_observation(
            state,
            registration,
            registration.terminal_payload,
        ),
        "interpretation": "REPLACE_ME: evidence-bound interpretation",
        "failure_type": (
            "REPLACE_ME: mechanism|implementation|evidence|constraint|operational|supported"
        ),
        "falsifier": "REPLACE_ME: observation that would falsify this interpretation",
        "recommendation": (
            "REPLACE_ME: stop|change_control|explore|ablate|exploit|replicate|retry"
        ),
        "authorized_action": None,
    }


def plan_generation_open(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    contract: StudyContract,
    evaluation_seal: EvaluationSeal,
    predecessor_generation_id: str | None = None,
    change_reason: str | None = None,
) -> GenerationPlan:
    """Plan an idempotent first open or an explicit successor."""

    if not isinstance(contract, StudyContract):
        raise _error(
            "STUDY_CONTRACT_INVALID",
            "contract must be a validated StudyContract",
        )
    # Frozen dataclasses prevent mutation but do not make direct construction a
    # validation boundary.  Reparse here so every plan is canonical and every
    # emitted payload is accepted by the replay reducer that owns authority.
    contract = StudyContract.from_mapping(contract.to_dict())
    if not isinstance(evaluation_seal, EvaluationSeal):
        raise _error(
            "STUDY_EVALUATION_SEAL_INVALID",
            "evaluation_seal must be a validated EvaluationSeal",
        )
    evaluation_seal = EvaluationSeal.from_mapping(evaluation_seal.to_dict())
    state = reduce_scientific_state(events, project_id=project_id)
    if state.active_generation_id is None:
        if predecessor_generation_id is not None or change_reason is not None:
            raise _error(
                "STUDY_GENERATION_MISMATCH",
                "the first generation cannot declare a predecessor or change reason",
                active_generation_id=None,
                predecessor_generation_id=predecessor_generation_id,
            )
        identifier = derive_generation_id(
            project_id,
            None,
            contract.digest,
            evaluation_seal.digest,
        )
        return GenerationPlan(
            project_id,
            identifier,
            True,
            contract,
            evaluation_seal,
            None,
            None,
        )

    identical = (
        state.study_contract_digest == contract.digest
        and state.evaluation_seal_digest == evaluation_seal.digest
    )
    if identical and predecessor_generation_id is None and change_reason is None:
        return GenerationPlan(
            project_id,
            state.active_generation_id,
            False,
            contract,
            evaluation_seal,
            None,
            None,
        )
    _validate_successor_gate(state)
    if predecessor_generation_id != state.active_generation_id:
        raise _error(
            "STUDY_GENERATION_MISMATCH",
            "predecessor_generation_id must match the active generation",
            active_generation_id=state.active_generation_id,
            predecessor_generation_id=predecessor_generation_id,
        )
    if not isinstance(change_reason, str) or not change_reason.strip():
        raise _error(
            "STUDY_CHANGE_REASON_REQUIRED",
            "a non-empty change reason is required for a successor generation",
            active_generation_id=state.active_generation_id,
        )
    normalized_reason = change_reason.strip()
    if normalized_reason != change_reason:
        raise _error(
            "STUDY_CHANGE_REASON_REQUIRED",
            "change_reason must be trimmed",
            active_generation_id=state.active_generation_id,
        )
    if identical:
        raise _error(
            "STUDY_GENERATION_UNCHANGED",
            "an unchanged contract and evaluation seal cannot reset the budget",
            active_generation_id=state.active_generation_id,
        )
    identifier = derive_generation_id(
        project_id,
        state.active_generation_id,
        contract.digest,
        evaluation_seal.digest,
    )
    return GenerationPlan(
        project_id,
        identifier,
        True,
        contract,
        evaluation_seal,
        state.active_generation_id,
        change_reason,
    )


def _validate_successor_gate(state: ScientificState) -> None:
    if state.contract is None or state.contract.schema_version != 2:
        return
    pending = state.pending_diagnosis_experiment_ids
    if pending:
        raise _error(
            "DIAGNOSIS_REQUIRED",
            "all terminal typed experiments require Diagnosis before a successor",
            pending_diagnosis_experiment_ids=list(pending),
        )
    active = [item.experiment_id for item in state.registrations if not item.is_terminal]
    if active:
        raise _error(
            "STUDY_ACTIVE_EXPERIMENTS",
            "a successor generation requires all typed experiments to be terminal",
            active_experiment_ids=active,
        )


def validate_successor_preflight(state: ScientificState) -> None:
    """Reject active-generation successor blockers before contract work."""

    if not isinstance(state, ScientificState):
        raise _error(
            "STUDY_STATE_INVALID",
            "successor preflight requires a ScientificState",
        )
    _validate_successor_gate(state)


def registration_payload_fields(
    state: ScientificState,
    *,
    retry_of: str | None,
) -> dict[str, Any]:
    """Return the complete contract-fixed science bundle for registration."""

    if (
        state.active_generation_id is None
        or state.contract is None
        or state.evaluation_seal is None
    ):
        return {}
    budget = state.contract.budget
    return {
        "science_state_version": SCIENCE_STATE_VERSION,
        "generation_id": state.active_generation_id,
        "study_contract_digest": state.contract.digest,
        "evaluation_seal_digest": state.evaluation_seal.digest,
        "budget_debit": {
            "attempts": 1,
            "retries": int(retry_of is not None),
            "reserved_elapsed_milliseconds": (budget.elapsed_reservation_per_attempt_milliseconds),
            "reserved_cost_microunits": (budget.cost_reservation_per_attempt_microunits),
        },
    }


def _registration_debit(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> tuple[int, int, int, int | None]:
    if state.contract is None or state.active_generation_id is None:
        raise _error(
            "STUDY_GENERATION_REQUIRED",
            "a versioned registration requires an active study generation",
        )
    present = _REGISTRATION_SCIENCE_KEYS.intersection(payload)
    if not present:
        raise _error(
            "STUDY_GENERATION_REQUIRED",
            "registration must bind the active study generation",
            active_generation_id=state.active_generation_id,
        )
    if present != _REGISTRATION_SCIENCE_KEYS:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "registration has a partial scientific-state bundle",
            missing_fields=sorted(_REGISTRATION_SCIENCE_KEYS - present),
        )
    if "authorized_action" not in payload or payload["authorized_action"] is not None:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "versioned registration authorized_action must be present and null",
        )
    retry_of = payload.get("retry_of")
    if retry_of is not None and (not isinstance(retry_of, str) or not retry_of.strip()):
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "retry_of must be null or a non-empty experiment ID",
        )
    _literal_version(
        payload["science_state_version"],
        code="STUDY_REGISTRATION_INVALID",
    )
    proposed_generation_id = _generation_identifier(
        payload["generation_id"],
        code="STUDY_REGISTRATION_INVALID",
        field="generation_id",
    )
    for field in ("study_contract_digest", "evaluation_seal_digest"):
        value = payload[field]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise _error(
                "STUDY_REGISTRATION_INVALID",
                f"{field} must be a lowercase SHA-256 digest",
            )
    debit = payload["budget_debit"]
    if not isinstance(debit, Mapping) or set(debit) != _BUDGET_DEBIT_KEYS:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "budget_debit must have exact version-one fields",
        )
    attempts = debit["attempts"]
    retries = debit["retries"]
    elapsed = debit["reserved_elapsed_milliseconds"]
    cost = debit["reserved_cost_microunits"]
    if (
        not is_safe_integer(attempts, minimum=0)
        or not is_safe_integer(retries, minimum=0)
        or not is_safe_integer(elapsed, minimum=0)
        or (cost is not None and not is_safe_integer(cost, minimum=0))
    ):
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "budget_debit values must be null or nonnegative safe integers",
        )
    expected = registration_payload_fields(
        state,
        retry_of=retry_of,
    )["budget_debit"]
    if dict(debit) != expected:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "budget_debit does not match the active contract reservation",
            expected_budget_debit=expected,
            observed_budget_debit=dict(debit),
        )
    if proposed_generation_id != state.active_generation_id:
        raise _error(
            "STUDY_GENERATION_MISMATCH",
            "registration generation does not match the active generation",
            active_generation_id=state.active_generation_id,
            registration_generation_id=proposed_generation_id,
        )
    if payload["study_contract_digest"] != state.study_contract_digest:
        raise _error(
            "STUDY_CONTRACT_MISMATCH",
            "registration contract digest does not match the active generation",
            active_study_contract_digest=state.study_contract_digest,
            registration_study_contract_digest=payload["study_contract_digest"],
        )
    if payload["evaluation_seal_digest"] != state.evaluation_seal_digest:
        raise _error(
            "STUDY_EVALUATION_SEAL_MISMATCH",
            "registration evaluation seal does not match the active generation",
            active_evaluation_seal_digest=state.evaluation_seal_digest,
            registration_evaluation_seal_digest=payload["evaluation_seal_digest"],
        )
    return int(attempts), int(retries), int(elapsed), None if cost is None else int(cost)


def _evaluation_scope(
    state: ScientificState,
    evaluation_scope_id: str,
) -> EvaluationScope | None:
    if state.contract is None:
        return None
    for scope in state.contract.evaluation_scopes:
        if scope.id == evaluation_scope_id:
            return scope
    return None


def _typed_registration_evidence(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> ScientificRegistration | None:
    """Recompute one registration's canonical typed sibling evidence."""

    assert state.contract is not None
    present = _TYPED_REGISTRATION_KEYS.intersection(payload)
    if state.contract.schema_version == 1:
        if present:
            raise _error(
                "PROPOSAL_CONTRACT_VERSION_REQUIRED",
                "typed Proposal evidence requires StudyContract version 2",
            )
        return None
    if state.contract.schema_version != 2:  # pragma: no cover - contract parser guards
        raise _error(
            "STUDY_CONTRACT_INVALID",
            "active study contract has an unsupported schema version",
        )
    if not present:
        raise _error(
            "PROPOSAL_REQUIRED",
            "StudyContract version 2 registration requires a typed Proposal",
        )
    if present != _TYPED_REGISTRATION_KEYS:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "registration has a partial typed Proposal bundle",
            missing_fields=sorted(_TYPED_REGISTRATION_KEYS - present),
        )
    graph_fields = _LEGACY_GRAPH_KEYS.intersection(payload)
    if graph_fields:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "typed Proposal registration cannot contain legacy graph metadata",
            present_fields=sorted(graph_fields),
        )

    candidate_value = payload.get("candidate")
    if not isinstance(candidate_value, Mapping):
        raise _error(
            "CANDIDATE_DIGEST_MISMATCH",
            "typed registration candidate body must be an object",
        )
    try:
        candidate_digest = sha256_json(candidate_value)
        candidate_json = canonical_json(candidate_value)
    except (TypeError, ValueError) as exc:
        raise _error(
            "CANDIDATE_DIGEST_MISMATCH",
            "typed registration candidate body is not canonical JSON",
        ) from exc
    if payload.get("candidate_digest") != candidate_digest:
        raise _error(
            "CANDIDATE_DIGEST_MISMATCH",
            "registration candidate digest does not match its canonical body",
            expected_candidate_digest=candidate_digest,
            observed_candidate_digest=payload.get("candidate_digest"),
        )

    proposal_raw = payload.get("proposal")
    proposal = Proposal.from_mapping(cast(Mapping[str, Any], proposal_raw))
    expected_proposal_digest = proposal.digest
    if payload.get("proposal_digest") != expected_proposal_digest:
        raise _error(
            "PROPOSAL_DIGEST_MISMATCH",
            "registration Proposal digest does not match its canonical body",
            expected_proposal_digest=expected_proposal_digest,
            observed_proposal_digest=payload.get("proposal_digest"),
        )
    expected_proposal_id = proposal_id(
        state.project_id,
        expected_proposal_digest,
    )
    if payload.get("proposal_id") != expected_proposal_id:
        raise _error(
            "PROPOSAL_ID_MISMATCH",
            "registration Proposal ID does not match its canonical identity",
            expected_proposal_id=expected_proposal_id,
            observed_proposal_id=payload.get("proposal_id"),
        )

    if (
        proposal.generation_id != payload.get("generation_id")
        or proposal.generation_id != state.active_generation_id
    ):
        raise _error(
            "PROPOSAL_GENERATION_MISMATCH",
            "Proposal generation does not match the registration and active generation",
            active_generation_id=state.active_generation_id,
            registration_generation_id=payload.get("generation_id"),
            proposal_generation_id=proposal.generation_id,
        )
    if (
        proposal.candidate_digest != payload.get("candidate_digest")
        or proposal.candidate_digest != candidate_digest
    ):
        raise _error(
            "PROPOSAL_CANDIDATE_MISMATCH",
            "Proposal candidate digest does not match the registration candidate",
            registration_candidate_digest=payload.get("candidate_digest"),
            proposal_candidate_digest=proposal.candidate_digest,
        )
    parent_id = payload.get("parent_id")
    if parent_id != proposal.parent_experiment_id:
        raise _error(
            "PROPOSAL_PARENT_MISMATCH",
            "flat registration parent does not match the Proposal parent",
            registration_parent_id=parent_id,
            proposal_parent_experiment_id=proposal.parent_experiment_id,
        )
    evaluation_scope_id = payload.get("evaluation_scope_id")
    if evaluation_scope_id != proposal.evaluation_scope_id:
        raise _error(
            "PROPOSAL_EVALUATION_SCOPE_MISMATCH",
            "flat registration scope does not match the Proposal scope",
            registration_evaluation_scope_id=evaluation_scope_id,
            proposal_evaluation_scope_id=proposal.evaluation_scope_id,
        )

    compatibility_digest = payload.get("compatibility_digest")
    active_compatibility = (
        None if state.evaluation_seal is None else state.evaluation_seal.compatibility_digest
    )
    if compatibility_digest != active_compatibility:
        raise _error(
            "STUDY_EVALUATION_SEAL_MISMATCH",
            "registration compatibility does not match the active evaluation seal",
            active_compatibility_digest=active_compatibility,
            registration_compatibility_digest=compatibility_digest,
        )
    attempt = payload.get("attempt", 1)
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "typed registration attempt must be a positive integer",
        )
    retry_of = payload.get("retry_of")
    if retry_of is None and attempt != 1:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "a first typed registration must use attempt 1",
        )
    if retry_of is not None and attempt == 1:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "a typed retry cannot use attempt 1",
        )

    expected_experiment_id = new_experiment_id(
        state.project_id,
        candidate_digest,
        compatibility_digest=cast(str, compatibility_digest),
        parent_id=proposal.parent_experiment_id,
        generation_id=proposal.generation_id,
        evaluation_scope_id=proposal.evaluation_scope_id,
        attempt=attempt,
    )
    experiment_id = payload.get("experiment_id")
    if experiment_id != expected_experiment_id:
        raise _error(
            "EXPERIMENT_ID_MISMATCH",
            "typed experiment ID does not match its canonical scoped identity",
            expected_experiment_id=expected_experiment_id,
            observed_experiment_id=experiment_id,
        )
    baseline_id = payload.get("baseline_id")
    if not isinstance(baseline_id, str) or not baseline_id.strip():
        raise _error(
            "STUDY_SCOPE_BASELINE_REQUIRED",
            "typed registration requires a scope-bound baseline",
            evaluation_scope_id=proposal.evaluation_scope_id,
        )

    return ScientificRegistration(
        experiment_id=expected_experiment_id,
        generation_id=proposal.generation_id,
        candidate_digest=candidate_digest,
        candidate_json=candidate_json,
        proposal=proposal,
        proposal_digest=expected_proposal_digest,
        proposal_id=expected_proposal_id,
        parent_id=proposal.parent_experiment_id,
        evaluation_scope_id=proposal.evaluation_scope_id,
        compatibility_digest=cast(str, compatibility_digest),
        baseline_id=baseline_id,
        attempt=attempt,
        retry_of=cast(str | None, retry_of),
        primary_metric=(
            payload.get("primary_metric")
            if isinstance(payload.get("primary_metric"), str)
            and bool(cast(str, payload.get("primary_metric")).strip())
            else None
        ),
    )


def _require_scope_baseline(
    state: ScientificState,
    registration: ScientificRegistration,
) -> None:
    baseline = next(
        (
            item
            for item in reversed(state.scope_baselines)
            if item.baseline_id == registration.baseline_id
        ),
        None,
    )
    if (
        baseline is None
        or baseline.generation_id != registration.generation_id
        or baseline.compatibility_digest != registration.compatibility_digest
        or baseline.evaluation_scope_id != registration.evaluation_scope_id
    ):
        raise _error(
            "STUDY_SCOPE_BASELINE_REQUIRED",
            "typed registration requires a trusted baseline for the same generation and scope",
            baseline_id=registration.baseline_id,
            evaluation_scope_id=registration.evaluation_scope_id,
        )


def _validate_retry_registration(
    state: ScientificState,
    registration: ScientificRegistration,
) -> None:
    assert registration.retry_of is not None
    prior = state.registration(registration.retry_of)
    if prior is None:
        raise _error(
            "PROPOSAL_RETRY_MISMATCH",
            "typed retry does not reference a canonical prior registration",
        )
    related = tuple(
        item
        for item in state.registrations
        if item.proposal_id == prior.proposal_id
        and item.candidate_digest == prior.candidate_digest
        and item.evaluation_scope_id == prior.evaluation_scope_id
    )
    exact_inheritance = (
        prior.is_terminal
        and prior.retryable
        and bool(related)
        and related[-1].experiment_id == prior.experiment_id
        and registration.attempt == prior.attempt + 1
        and registration.generation_id == prior.generation_id
        and registration.candidate_digest == prior.candidate_digest
        and registration.candidate_json == prior.candidate_json
        and registration.proposal == prior.proposal
        and registration.proposal_digest == prior.proposal_digest
        and registration.proposal_id == prior.proposal_id
        and registration.parent_id == prior.parent_id
        and registration.evaluation_scope_id == prior.evaluation_scope_id
        and registration.compatibility_digest == prior.compatibility_digest
        and registration.primary_metric == prior.primary_metric
    )
    if not exact_inheritance:
        raise _error(
            "PROPOSAL_RETRY_MISMATCH",
            "typed retry must inherit the immediately prior Proposal and scope exactly",
            retry_of=registration.retry_of,
        )
    _require_scope_baseline(state, registration)


def _validate_first_typed_registration(
    state: ScientificState,
    registration: ScientificRegistration,
) -> bool:
    assert state.contract is not None
    proposal = registration.proposal
    hypothesis_ids = {item.id for item in state.contract.hypothesis_classes}
    if proposal.hypothesis_class_id not in hypothesis_ids:
        raise _error(
            "PROPOSAL_HYPOTHESIS_CLASS_UNKNOWN",
            "Proposal hypothesis class is not declared by the active contract",
            hypothesis_class_id=proposal.hypothesis_class_id,
        )
    scope = _evaluation_scope(state, proposal.evaluation_scope_id)
    if scope is None:
        raise _error(
            "PROPOSAL_EVALUATION_SCOPE_UNKNOWN",
            "Proposal evaluation scope is not declared by the active contract",
            evaluation_scope_id=proposal.evaluation_scope_id,
        )

    iterative = proposal.action in {"explore", "exploit", "ablate"}
    if iterative and scope.role not in {"development", "diagnostic"}:
        raise _error(
            "PROPOSAL_SCOPE_ROLE_MISMATCH",
            "iterative Proposal requires a development or diagnostic scope",
            action=proposal.action,
            evaluation_scope_id=scope.id,
            evaluation_scope_role=scope.role,
        )
    if proposal.action == "replicate" and scope.role != "replication":
        raise _error(
            "PROPOSAL_SCOPE_ROLE_MISMATCH",
            "replication Proposal requires a replication scope",
            evaluation_scope_id=scope.id,
            evaluation_scope_role=scope.role,
        )

    pointers = proposal.intervention_json_pointers
    surface = state.contract.intervention_surface
    if proposal.action == "replicate":
        if pointers:
            raise _error(
                "PROPOSAL_INTERVENTION_INVALID",
                "replication Proposal intervention pointers must be empty",
            )
    elif (
        not pointers
        or len(pointers) > surface.max_changes
        or not set(pointers).issubset(surface.allowed_json_pointers)
    ):
        raise _error(
            "PROPOSAL_INTERVENTION_INVALID",
            "Proposal interventions exceed or escape the declared surface",
            declared_json_pointers=list(pointers),
        )

    if proposal.action == "explore":
        if registration.parent_id is not None:
            raise _error(
                "PROPOSAL_PARENT_MISMATCH",
                "explore Proposal requires a null parent",
            )
        parent = None
    else:
        if registration.parent_id is None:
            raise _error(
                "PROPOSAL_PARENT_MISMATCH",
                f"{proposal.action} Proposal requires a parent experiment",
            )
        parent = state.registration(registration.parent_id)
        if parent is None:
            raise _error(
                "PROPOSAL_PARENT_MISMATCH",
                "Proposal parent is not registered in the active generation",
                parent_experiment_id=registration.parent_id,
            )
        if not parent.is_terminal:
            raise _error(
                "PROPOSAL_PARENT_NOT_TERMINAL",
                "Proposal parent must have terminal evidence",
                parent_experiment_id=registration.parent_id,
            )
        if parent.compatibility_digest != registration.compatibility_digest:
            raise _error(
                "PROPOSAL_PARENT_COMPATIBILITY_MISMATCH",
                "Proposal parent must share the active compatibility seal",
                parent_experiment_id=registration.parent_id,
            )

    if proposal.action in {"exploit", "ablate"}:
        assert parent is not None
        if registration.candidate_digest == parent.candidate_digest:
            raise _error(
                "PROPOSAL_CANDIDATE_CHANGE_REQUIRED",
                f"{proposal.action} Proposal must change the parent candidate",
            )
        observed = canonical_json_diff_pointers(
            parent.candidate,
            registration.candidate,
        )
        if pointers != observed:
            raise _error(
                "PROPOSAL_INTERVENTION_MISMATCH",
                "declared intervention pointers do not match the canonical candidate diff",
                declared_json_pointers=list(pointers),
                observed_json_pointers=list(observed),
            )
    elif proposal.action == "replicate":
        assert parent is not None
        if (
            registration.candidate_digest != parent.candidate_digest
            or registration.candidate_json != parent.candidate_json
        ):
            raise _error(
                "PROPOSAL_REPLICATION_CANDIDATE_MISMATCH",
                "replication requires the exact frozen parent candidate",
            )
        if proposal.hypothesis_class_id != parent.proposal.hypothesis_class_id:
            raise _error(
                "PROPOSAL_REPLICATION_CLASS_MISMATCH",
                "replication must preserve the parent hypothesis class",
            )
        parent_scope = _evaluation_scope(state, parent.evaluation_scope_id)
        if (
            parent_scope is None
            or scope.id == parent_scope.id
            or scope.manifest_digest == parent_scope.manifest_digest
        ):
            raise _error(
                "PROPOSAL_REPLICATION_SCOPE_UNCHANGED",
                "replication requires a distinct preregistered scope",
            )
        if not _is_evidence_supported(state, parent):
            raise _error(
                "PROPOSAL_PARENT_NOT_SUPPORTED",
                "replication parent lacks exact diagnosed support evidence",
                parent_experiment_id=registration.parent_id,
            )

    _require_scope_baseline(state, registration)
    uniqueness_key = (
        registration.generation_id,
        registration.candidate_digest,
        registration.evaluation_scope_id,
    )
    if uniqueness_key in state.used_candidate_scope_keys:
        raise _error(
            "PROPOSAL_EVALUATION_SCOPE_REUSED",
            "candidate has already used this evaluation scope in the active generation",
            generation_id=registration.generation_id,
            candidate_digest=registration.candidate_digest,
            evaluation_scope_id=registration.evaluation_scope_id,
        )
    return proposal.action == "replicate"


def _pre_registration_gate(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> None:
    if state.contract is None or state.contract.schema_version != 2:
        return
    stop = state.study_stop
    if stop["stopped"]:
        raise _error(
            "STUDY_STOPPED",
            "the active study generation is stopped",
            reasons=stop["reasons"],
        )
    pending = state.pending_diagnosis_experiment_ids
    if pending:
        raise _error(
            "DIAGNOSIS_REQUIRED",
            "all terminal typed experiments require Diagnosis before registration",
            pending_diagnosis_experiment_ids=list(pending),
        )

    hypothesis_class_id: str | None = None
    retry_of = payload.get("retry_of")
    if isinstance(retry_of, str):
        prior = state.registration(retry_of)
        if prior is not None:
            hypothesis_class_id = prior.proposal.hypothesis_class_id
    if hypothesis_class_id is None:
        proposal = payload.get("proposal")
        if isinstance(proposal, Mapping) and isinstance(
            proposal.get("hypothesis_class_id"), str
        ):
            hypothesis_class_id = cast(str, proposal["hypothesis_class_id"])
    if hypothesis_class_id is None:
        return
    class_state = _class_state_by_id(state, hypothesis_class_id)
    if class_state is not None and class_state.lifecycle == "closed":
        raise _error(
            "HYPOTHESIS_CLASS_CLOSED",
            "the Proposal hypothesis class is canonically closed",
            hypothesis_class_id=hypothesis_class_id,
        )
    _pre_replication_parent_gate(state, payload)


def validate_registration_preflight(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> None:
    """Reject state-derived registration blockers before external work.

    ``payload`` may be only the intent fields available before candidate and
    evaluator materialization (``retry_of``, ``proposal``, and ``parent_id``).
    The complete canonical registration is still validated again by
    :func:`validate_registration` or :func:`reserve_registration` at the
    locked append boundary.
    """

    if not isinstance(state, ScientificState):
        raise _error(
            "STUDY_STATE_INVALID",
            "registration preflight requires a ScientificState",
        )
    if not isinstance(payload, Mapping):
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "registration preflight payload must be an object",
        )
    _pre_registration_gate(state, payload)


def _pre_replication_parent_gate(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> None:
    proposal = payload.get("proposal")
    if not isinstance(proposal, Mapping) or proposal.get("action") != "replicate":
        return
    parent_id = payload.get("parent_id")
    if not isinstance(parent_id, str):
        return
    parent = state.registration(parent_id)
    if parent is None:
        raise _error(
            "PROPOSAL_PARENT_MISMATCH",
            "Proposal parent is not registered in the active generation",
            parent_experiment_id=parent_id,
        )
    if not parent.is_terminal:
        raise _error(
            "PROPOSAL_PARENT_NOT_TERMINAL",
            "Proposal parent must have terminal evidence",
            parent_experiment_id=parent_id,
        )
    active_compatibility = (
        None if state.evaluation_seal is None else state.evaluation_seal.compatibility_digest
    )
    if parent.compatibility_digest != active_compatibility:
        raise _error(
            "PROPOSAL_PARENT_COMPATIBILITY_MISMATCH",
            "Proposal parent must share the active compatibility seal",
            parent_experiment_id=parent_id,
        )
    if not _is_evidence_supported(state, parent):
        raise _error(
            "PROPOSAL_PARENT_NOT_SUPPORTED",
            "replication parent lacks exact diagnosed support evidence",
            parent_experiment_id=parent_id,
        )


def _validated_registration(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> tuple[tuple[int, int, int, int | None], ScientificRegistration | None, bool]:
    _pre_registration_gate(state, payload)
    registration = _typed_registration_evidence(state, payload)
    if registration is None:
        debit = _registration_debit(state, payload)
        return debit, None, False
    if registration.retry_of is not None:
        _validate_retry_registration(state, registration)
        debit = _registration_debit(state, payload)
        return debit, registration, False
    is_replication = _validate_first_typed_registration(state, registration)
    debit = _registration_debit(state, payload)
    return debit, registration, is_replication


def validate_registration(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> None:
    """Validate binding, Proposal semantics, and debit without consuming it."""

    _validated_registration(state, payload)


def _budget_exceeded(
    code: str,
    state: ScientificState,
    *,
    dimension: str,
    limit: int,
    reserved: int,
    requested: int,
) -> ScientificStateError:
    return _error(
        code,
        f"{dimension} reservation exceeds the active generation budget",
        generation_id=state.active_generation_id,
        dimension=dimension,
        limit=limit,
        reserved=reserved,
        requested=requested,
    )


def reserve_registration(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> ScientificState:
    """Validate and non-refundably reserve one versioned registration."""

    debit, registration, is_replication = _validated_registration(state, payload)
    attempts, retries, elapsed, cost = debit
    assert state.contract is not None  # guarded by _registration_debit
    budget = state.contract.budget
    next_attempts = state.attempts_used + attempts
    if next_attempts > budget.max_attempts:
        raise _budget_exceeded(
            "BUDGET_ATTEMPTS_EXCEEDED",
            state,
            dimension="attempts",
            limit=budget.max_attempts,
            reserved=state.attempts_used,
            requested=attempts,
        )
    next_retries = state.retries_used + retries
    if next_retries > budget.max_retries:
        raise _budget_exceeded(
            "BUDGET_RETRIES_EXCEEDED",
            state,
            dimension="retries",
            limit=budget.max_retries,
            reserved=state.retries_used,
            requested=retries,
        )
    next_elapsed = state.elapsed_reserved_milliseconds + elapsed
    if next_elapsed > budget.max_elapsed_milliseconds:
        raise _budget_exceeded(
            "BUDGET_ELAPSED_EXCEEDED",
            state,
            dimension="elapsed_milliseconds",
            limit=budget.max_elapsed_milliseconds,
            reserved=state.elapsed_reserved_milliseconds,
            requested=elapsed,
        )
    if budget.max_cost_microunits is None:
        if cost is not None or state.cost_reserved_microunits is not None:
            raise _error(
                "STUDY_REGISTRATION_INVALID",
                "an unconfigured cost ledger must remain null",
            )
        next_cost = None
    else:
        if cost is None or state.cost_reserved_microunits is None:
            raise _error(
                "STUDY_REGISTRATION_INVALID",
                "a configured cost ledger requires a fixed reservation",
            )
        next_cost = state.cost_reserved_microunits + cost
        if next_cost > budget.max_cost_microunits:
            raise _budget_exceeded(
                "BUDGET_COST_EXCEEDED",
                state,
                dimension="cost_microunits",
                limit=budget.max_cost_microunits,
                reserved=state.cost_reserved_microunits,
                requested=cost,
            )
    registrations = state.registrations
    proposal_ids = state.proposal_ids
    used_candidate_scope_keys = state.used_candidate_scope_keys
    replication_count = state.replication_count
    if registration is not None:
        registrations = (*registrations, registration)
        proposal_ids = proposal_ids | {registration.proposal_id}
        if registration.retry_of is None:
            used_candidate_scope_keys = used_candidate_scope_keys | {
                (
                    registration.generation_id,
                    registration.candidate_digest,
                    registration.evaluation_scope_id,
                )
            }
            replication_count += int(is_replication)
    return replace(
        state,
        attempts_used=next_attempts,
        retries_used=next_retries,
        elapsed_reserved_milliseconds=next_elapsed,
        cost_reserved_microunits=next_cost,
        registrations=registrations,
        proposal_ids=frozenset(proposal_ids),
        used_candidate_scope_keys=frozenset(used_candidate_scope_keys),
        replication_count=replication_count,
    )


def _apply_scope_baseline(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> ScientificState:
    present = _TYPED_BASELINE_KEYS.intersection(payload)
    if state.active_generation_id is None or state.contract is None:
        if present:
            raise _error(
                "STUDY_GENERATION_REQUIRED",
                "scope-bound baseline requires an active study generation",
            )
        return state
    if state.contract.schema_version == 1:
        if present:
            raise _error(
                "STUDY_SCOPE_CONTRACT_VERSION_REQUIRED",
                "evaluation-scoped baseline requires StudyContract version 2",
            )
        return state
    has_scope_id = "evaluation_scope_id" in payload
    has_scope_body = "evaluation_scope" in payload
    if not has_scope_id and not has_scope_body:
        # Legacy unscoped baselines remain replayable but cannot authorize a
        # typed registration because no ScopeBaseline record is created.
        return state
    if has_scope_id is not has_scope_body:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "scope-bound baseline has an incomplete evaluation-scope bundle",
        )
    if present != _TYPED_BASELINE_KEYS:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "scope-bound baseline has a partial scientific-state bundle",
            missing_fields=sorted(_TYPED_BASELINE_KEYS - present),
        )
    _literal_version(
        payload["science_state_version"],
        code="STUDY_REGISTRATION_INVALID",
    )
    if payload["generation_id"] != state.active_generation_id:
        raise _error(
            "STUDY_GENERATION_MISMATCH",
            "baseline generation does not match the active generation",
        )
    if payload["study_contract_digest"] != state.study_contract_digest:
        raise _error(
            "STUDY_CONTRACT_MISMATCH",
            "baseline contract digest does not match the active generation",
        )
    if payload["evaluation_seal_digest"] != state.evaluation_seal_digest:
        raise _error(
            "STUDY_EVALUATION_SEAL_MISMATCH",
            "baseline evaluation seal does not match the active generation",
        )
    evaluation_scope_id = payload["evaluation_scope_id"]
    if not isinstance(evaluation_scope_id, str):
        raise _error(
            "STUDY_EVALUATION_SCOPE_UNKNOWN",
            "baseline evaluation scope ID must be text",
        )
    scope = _evaluation_scope(state, evaluation_scope_id)
    if scope is None:
        raise _error(
            "STUDY_EVALUATION_SCOPE_UNKNOWN",
            "baseline evaluation scope is not declared by the active contract",
            evaluation_scope_id=evaluation_scope_id,
        )
    if scope.role == "holdout":
        raise _error(
            "STUDY_SCOPE_BASELINE_FORBIDDEN",
            "holdout scope cannot be consumed by the iterative baseline path",
            evaluation_scope_id=evaluation_scope_id,
        )
    if payload["evaluation_scope"] != scope.to_dict():
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "baseline evaluation scope body does not match the active contract",
        )
    compatibility_digest = payload.get("compatibility_digest")
    active_compatibility = (
        None if state.evaluation_seal is None else state.evaluation_seal.compatibility_digest
    )
    if compatibility_digest != active_compatibility:
        raise _error(
            "STUDY_EVALUATION_SEAL_MISMATCH",
            "baseline compatibility does not match the active evaluation seal",
        )
    if payload.get("authorized_action") is not None:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "scope-bound baseline authorized_action must be null",
        )
    baseline_id = payload.get("baseline_id")
    if not isinstance(baseline_id, str) or not baseline_id.strip():
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "scope-bound baseline requires a non-empty baseline ID",
        )
    if any(item.baseline_id == baseline_id for item in state.scope_baselines):
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "scope-bound baseline ID is already present",
            baseline_id=baseline_id,
        )
    baseline = ScopeBaseline(
        baseline_id=baseline_id,
        generation_id=state.active_generation_id,
        compatibility_digest=cast(str, compatibility_digest),
        evaluation_scope_id=evaluation_scope_id,
        evaluation_scope=scope,
        primary_metric=(
            payload.get("primary_metric")
            if isinstance(payload.get("primary_metric"), str)
            and bool(cast(str, payload.get("primary_metric")).strip())
            else None
        ),
    )
    return replace(state, scope_baselines=(*state.scope_baselines, baseline))


def _terminal_retryable(
    status: LifecycleState,
    payload: Mapping[str, Any],
) -> bool:
    if status in _NON_RETRYABLE_TERMINAL_STATES:
        return False
    if status in {LifecycleState.TIMED_OUT, LifecycleState.CANCELLED}:
        return True
    if (
        status is LifecycleState.INFRA_FAILED
        and payload.get("reason_code") == "RECOVERED_INTERRUPTED_RUN"
    ):
        return True
    error = payload.get("error")
    expected_category = {
        LifecycleState.INFRA_FAILED: "INFRASTRUCTURE",
        LifecycleState.INSUFFICIENT_EVIDENCE: "INSUFFICIENT_EVIDENCE",
    }.get(status)
    return (
        expected_category is not None
        and isinstance(error, Mapping)
        and error.get("type") == "AdapterOperationError"
        and error.get("category") == expected_category
        and error.get("code") == payload.get("reason_code")
        and error.get("retryable") is True
    )


def _apply_artifact_evidence(
    state: ScientificState,
    payload: Mapping[str, Any],
    *,
    event_id: str | None,
    event_hash: str | None,
    event_sequence: int | None,
) -> ScientificState:
    if state.contract is None or state.contract.schema_version != 2:
        return state
    experiment_id = payload.get("experiment_id")
    if not isinstance(experiment_id, str) or state.registration(experiment_id) is None:
        return state
    if event_id is None or event_hash is None or event_sequence is None:
        # Loose legacy dictionaries are intentionally non-authoritative. They
        # cannot satisfy a later exact Diagnosis artifact reference.
        return state
    evidence = ArtifactEventEvidence(
        experiment_id=experiment_id,
        event_id=event_id,
        event_hash=event_hash,
        event_sequence=event_sequence,
        payload_json=canonical_json(payload),
    )
    return replace(state, artifact_events=(*state.artifact_events, evidence))


def _diagnosis_structural_parts(
    payload: Mapping[str, Any],
) -> Diagnosis:
    if set(payload) != _DIAGNOSIS_PAYLOAD_KEYS:
        raise _error(
            "DIAGNOSIS_INVALID",
            "Diagnosis event payload must have exact version-one fields",
            path="$",
        )
    if isinstance(payload.get("science_state_version"), bool) or payload.get(
        "science_state_version"
    ) != 1:
        raise _error(
            "DIAGNOSIS_INVALID",
            "Diagnosis event version must be literal 1",
            path="$.science_state_version",
        )
    if payload.get("authorized_action") is not None:
        raise _error(
            "DIAGNOSIS_INVALID",
            "Diagnosis event authority must be null",
            path="$.authorized_action",
        )
    raw = payload.get("diagnosis")
    if not isinstance(raw, Mapping):
        raise _error("DIAGNOSIS_INVALID", "diagnosis must be an object", path="$")
    try:
        return Diagnosis.from_mapping(raw)
    except ScientificStateError as exc:
        path = exc.details.get("path")
        if (
            exc.code == "DIAGNOSIS_INVALID"
            and isinstance(path, str)
            and path.startswith("$.observation.gate_evaluations[")
            and "normalized_slack" in str(exc)
            and "inconsistent" in str(exc)
        ):
            raise _error(
                "DIAGNOSIS_INVALID",
                str(exc),
                path=f"{path}.normalized_slack",
            ) from exc
        raise


def _parsed_decision(
    registration: ScientificRegistration,
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    if "decision" not in payload:
        return None
    raw = payload["decision"]
    if not isinstance(raw, Mapping) or set(raw) != _DECISION_KEYS:
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal Decision must have exact version-one fields",
            experiment_id=registration.experiment_id,
            path="$.terminal_evidence.decision",
        )
    if raw.get("authorized_action") is not None:
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal Decision authority must be null",
            experiment_id=registration.experiment_id,
            path="$.terminal_evidence.decision.authorized_action",
        )
    status = raw.get("status")
    reason = raw.get("reason_code")
    primary_metric = raw.get("primary_metric")
    if not isinstance(status, str) or not isinstance(reason, str) or not isinstance(
        primary_metric, str
    ):
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal Decision status, reason, and primary metric must be text",
            experiment_id=registration.experiment_id,
            path="$.terminal_evidence.decision",
        )
    try:
        normalized_status = TerminalStatus.parse(status).value
    except (TypeError, ValueError) as exc:
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal Decision status is invalid",
            experiment_id=registration.experiment_id,
            path="$.terminal_evidence.decision.status",
        ) from exc
    for field in (
        "candidate_value",
        "baseline_value",
        "improvement",
        "promotion_margin",
    ):
        value = raw.get(field)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise _error(
                "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
                "terminal Decision quantitative fields must be finite or null",
                experiment_id=registration.experiment_id,
                path=f"$.terminal_evidence.decision.{field}",
            )
    evaluations: list[dict[str, Any]] = []
    raw_evaluations = raw.get("gate_evaluations")
    if not isinstance(raw_evaluations, Sequence) or isinstance(
        raw_evaluations, (str, bytes, bytearray, memoryview)
    ):
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal Decision gate evaluations must be an array",
            experiment_id=registration.experiment_id,
            path="$.terminal_evidence.decision.gate_evaluations",
        )
    try:
        for item in raw_evaluations:
            evaluation = GateEvaluation.from_mapping(item)
            if evaluation.to_dict() != dict(cast(Mapping[str, Any], item)):
                raise ValueError("gate evaluation is not canonical")
            evaluations.append(evaluation.to_dict())
    except (TypeError, ValueError) as exc:
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal Decision gate evidence is invalid",
            experiment_id=registration.experiment_id,
            path="$.terminal_evidence.decision.gate_evaluations",
        ) from exc
    gate_ids = [item["id"] for item in evaluations]
    if gate_ids != sorted(gate_ids) or len(gate_ids) != len(set(gate_ids)):
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal Decision gates must be unique and ordered by ID",
            experiment_id=registration.experiment_id,
            path="$.terminal_evidence.decision.gate_evaluations",
        )
    decision = dict(raw)
    decision["status"] = normalized_status
    decision["gate_evaluations"] = evaluations
    if decision != dict(raw):
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal Decision must use canonical status and gate values",
            experiment_id=registration.experiment_id,
            path="$.terminal_evidence.decision",
        )
    return decision


def _parsed_result(
    registration: ScientificRegistration,
    payload: Mapping[str, Any],
) -> ResultEnvelope | None:
    if "result" not in payload:
        return None
    raw = payload["result"]
    if not isinstance(raw, Mapping) or set(raw) not in {
        _RESULT_BASE_KEYS,
        _RESULT_BASE_KEYS | {"status"},
    }:
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal ResultEnvelope must have its exact current fields",
            experiment_id=registration.experiment_id,
            path="$.terminal_evidence.result",
        )
    artifacts = raw.get("artifacts")
    if isinstance(artifacts, Sequence) and not isinstance(
        artifacts, (str, bytes, bytearray, memoryview)
    ):
        for index, artifact in enumerate(artifacts):
            if not isinstance(artifact, Mapping) or frozenset(artifact) not in {
                frozenset({"path", "media_type", "retention", "sensitivity"}),
                frozenset(
                    {
                    "path",
                    "media_type",
                    "retention",
                    "sensitivity",
                    "sha256",
                    "size_bytes",
                    }
                ),
            }:
                raise _error(
                    "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
                    "terminal ResultEnvelope artifact has non-exact fields",
                    experiment_id=registration.experiment_id,
                    path=f"$.terminal_evidence.result.artifacts[{index}]",
                )
    try:
        result = ResultEnvelope.from_mapping(raw)
    except (TypeError, ValueError) as exc:
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal ResultEnvelope is invalid",
            experiment_id=registration.experiment_id,
            path="$.terminal_evidence.result",
        ) from exc
    if result.status is not None:
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal ResultEnvelope cannot declare kernel status",
            experiment_id=registration.experiment_id,
            path="$.terminal_evidence.result.status",
        )
    if result.to_dict() != dict(raw):
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal ResultEnvelope is not canonical",
            experiment_id=registration.experiment_id,
            path="$.terminal_evidence.result",
        )
    return result


def _expected_observation(
    state: ScientificState,
    registration: ScientificRegistration,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    decision = _parsed_decision(registration, payload)
    _parsed_result(registration, payload)
    if payload.get("authorized_action") is not None:
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal event authority must be null",
            experiment_id=registration.experiment_id,
            path="$.terminal_evidence.authorized_action",
        )
    status = registration.terminal_status
    assert status is not None
    raw_reason = payload.get("reason_code")
    reason = (
        raw_reason
        if isinstance(raw_reason, str) and bool(raw_reason.strip())
        else (
            "STATUS_CHANGED"
            if registration.terminal_event_type == "EXPERIMENT_STATUS_CHANGED"
            else "TERMINATED"
        )
    )
    verified_raw = payload.get("verified", False)
    if not isinstance(verified_raw, bool):
        raise _error(
            "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
            "terminal verified must be a literal boolean",
            experiment_id=registration.experiment_id,
        )
    if decision is not None:
        if decision["status"] != status:
            raise _error(
                "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
                "terminal status conflicts with its Decision",
                experiment_id=registration.experiment_id,
                path="$.terminal_evidence.decision.status",
            )
        if decision["reason_code"] != reason:
            raise _error(
                "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
                "terminal reason conflicts with its Decision",
                experiment_id=registration.experiment_id,
                path="$.terminal_evidence.decision.reason_code",
            )
        terminal_metric = payload.get("primary_metric")
        if (
            isinstance(terminal_metric, str)
            and bool(terminal_metric.strip())
            and terminal_metric != decision["primary_metric"]
        ):
            raise _error(
                "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
                "terminal primary metric conflicts with its Decision",
                experiment_id=registration.experiment_id,
                path="$.terminal_evidence.decision.primary_metric",
            )
    terminal_metric = payload.get("primary_metric")
    primary_metric: str | None = (
        terminal_metric
        if isinstance(terminal_metric, str) and bool(terminal_metric.strip())
        else cast(str | None, None if decision is None else decision["primary_metric"])
    )
    if primary_metric is None:
        primary_metric = registration.primary_metric
    if primary_metric is None:
        baseline = next(
            (
                item
                for item in reversed(state.scope_baselines)
                if item.baseline_id == registration.baseline_id
            ),
            None,
        )
        primary_metric = None if baseline is None else baseline.primary_metric
    return {
        "terminal_status": status,
        "reason_code": reason,
        "verified": verified_raw,
        "retryable": registration.retryable,
        "primary_metric": primary_metric,
        "candidate_value": None if decision is None else decision["candidate_value"],
        "baseline_value": None if decision is None else decision["baseline_value"],
        "improvement": None if decision is None else decision["improvement"],
        "promotion_margin": None if decision is None else decision["promotion_margin"],
        "gate_evaluations": [] if decision is None else decision["gate_evaluations"],
    }


def _validated_artifact_records(
    state: ScientificState,
    registration: ScientificRegistration,
) -> tuple[tuple[ArtifactEventEvidence, ArtifactRecord], ...]:
    terminal_sequence = registration.terminal_event_sequence
    relevant = tuple(
        item
        for item in state.artifact_events
        if item.experiment_id == registration.experiment_id
    )
    records: list[tuple[ArtifactEventEvidence, ArtifactRecord]] = []
    for item in relevant:
        raw = item.payload
        if (
            terminal_sequence is None
            or item.event_sequence >= terminal_sequence
            or set(raw) != _ARTIFACT_EVENT_KEYS
            or raw.get("authorized_action") is not None
        ):
            raise _error(
                "DIAGNOSIS_ARTIFACT_EVIDENCE_MISMATCH",
                "canonical artifact evidence is malformed or not prior to terminal",
                experiment_id=registration.experiment_id,
                path="$.artifact_evidence",
            )
        try:
            record = ArtifactRecord.from_mapping(raw)
        except (IntegrityError, TypeError, ValueError) as exc:
            raise _error(
                "DIAGNOSIS_ARTIFACT_EVIDENCE_MISMATCH",
                "canonical artifact evidence is invalid",
                experiment_id=registration.experiment_id,
                path="$.artifact_evidence",
            ) from exc
        if (
            record.project_id != state.project_id
            or record.experiment_id != registration.experiment_id
            or record.role is not None
            or record.media_type is None
            or set(record.metadata) != {"retention", "sensitivity"}
        ):
            raise _error(
                "DIAGNOSIS_ARTIFACT_EVIDENCE_MISMATCH",
                "artifact ownership or capture metadata is not canonical",
                experiment_id=registration.experiment_id,
                path="$.artifact_evidence",
            )
        records.append((item, record))
    records.sort(key=lambda pair: (pair[1].artifact_id, pair[0].event_id))
    return tuple(records)


def _validate_artifact_binding(
    state: ScientificState,
    registration: ScientificRegistration,
    diagnosis: Diagnosis,
) -> None:
    records = _validated_artifact_records(state, registration)
    expected_refs = [
        {
            "artifact_id": record.artifact_id,
            "artifact_digest": record.digest,
            "event_id": event.event_id,
            "event_hash": event.event_hash,
        }
        for event, record in records
    ]
    observed_refs = [item.to_dict() for item in diagnosis.artifact_evidence]
    if len(observed_refs) != len(expected_refs):
        raise _error(
            "DIAGNOSIS_ARTIFACT_EVIDENCE_MISMATCH",
            "Diagnosis artifact references do not equal the canonical full set",
            experiment_id=registration.experiment_id,
            path="$.artifact_evidence",
        )
    for index, (observed, expected) in enumerate(
        zip(observed_refs, expected_refs, strict=True)
    ):
        differences = [key for key in expected if observed.get(key) != expected[key]]
        if differences:
            suffix = f".{differences[0]}" if len(differences) == 1 else ""
            raise _error(
                "DIAGNOSIS_ARTIFACT_EVIDENCE_MISMATCH",
                "Diagnosis artifact reference does not match canonical evidence",
                experiment_id=registration.experiment_id,
                path=f"$.artifact_evidence[{index}]{suffix}",
            )
    payload = registration.terminal_payload
    assert payload is not None
    result = _parsed_result(registration, payload)
    result_refs = () if result is None else result.artifacts
    if len(result_refs) != len(records):
        raise _error(
            "DIAGNOSIS_ARTIFACT_EVIDENCE_MISMATCH",
            "ResultEnvelope artifacts do not equal the canonical artifact set",
            experiment_id=registration.experiment_id,
            path="$.artifact_evidence",
        )
    by_path = {record.relative_path: record for _, record in records}
    for ref in result_refs:
        record = by_path.get(ref.path)
        if (
            record is None
            or ref.sha256 != record.digest
            or ref.size_bytes != record.size
            or ref.media_type != record.media_type
            or ref.retention != record.metadata["retention"]
            or ref.sensitivity != record.metadata["sensitivity"]
        ):
            raise _error(
                "DIAGNOSIS_ARTIFACT_EVIDENCE_MISMATCH",
                "ResultEnvelope artifact does not match its canonical record",
                experiment_id=registration.experiment_id,
                path="$.artifact_evidence",
            )


def _validate_diagnosis_binding(
    state: ScientificState,
    payload: DiagnosisEventPayload,
) -> ScientificRegistration:
    diagnosis = payload.diagnosis
    if payload.generation_id != state.active_generation_id:
        raise _error(
            "DIAGNOSIS_GENERATION_MISMATCH",
            "Diagnosis generation does not match the active generation",
            path="$.generation_id",
        )
    if payload.study_contract_digest != state.study_contract_digest:
        raise _error(
            "STUDY_CONTRACT_MISMATCH",
            "Diagnosis contract digest does not match the active generation",
            path="$.study_contract_digest",
        )
    if payload.evaluation_seal_digest != state.evaluation_seal_digest:
        raise _error(
            "STUDY_EVALUATION_SEAL_MISMATCH",
            "Diagnosis evaluation seal does not match the active generation",
            path="$.evaluation_seal_digest",
        )
    active_compatibility = (
        None if state.evaluation_seal is None else state.evaluation_seal.compatibility_digest
    )
    if payload.compatibility_digest != active_compatibility:
        raise _error(
            "DIAGNOSIS_COMPATIBILITY_MISMATCH",
            "Diagnosis compatibility does not match the active generation",
            path="$.compatibility_digest",
        )
    registration = state.registration(diagnosis.experiment_id)
    if registration is None:
        raise _error(
            "DIAGNOSIS_EXPERIMENT_UNKNOWN",
            "Diagnosis experiment is not registered in the active generation",
            experiment_id=diagnosis.experiment_id,
            path="$.experiment_id",
        )
    proposal_bindings = (
        ("proposal_id", diagnosis.proposal_id, registration.proposal_id),
        ("proposal_digest", diagnosis.proposal_digest, registration.proposal_digest),
        (
            "hypothesis_class_id",
            diagnosis.hypothesis_class_id,
            registration.proposal.hypothesis_class_id,
        ),
        (
            "evaluation_scope_id",
            diagnosis.evaluation_scope_id,
            registration.evaluation_scope_id,
        ),
    )
    for field, observed, expected in proposal_bindings:
        if observed != expected:
            raise _error(
                "DIAGNOSIS_PROPOSAL_MISMATCH",
                "Diagnosis Proposal or scope does not match persisted evidence",
                experiment_id=diagnosis.experiment_id,
                path=f"$.{field}",
            )
    if not registration.is_terminal:
        raise _error(
            "DIAGNOSIS_TERMINAL_REQUIRED",
            "Diagnosis requires prior terminal evidence",
            experiment_id=diagnosis.experiment_id,
            path="$.terminal_evidence",
        )
    terminal_ref = diagnosis.terminal_evidence
    terminal_bindings = (
        ("experiment_id", terminal_ref.experiment_id, registration.experiment_id),
        ("event_id", terminal_ref.event_id, registration.terminal_event_id),
        ("event_hash", terminal_ref.event_hash, registration.terminal_event_hash),
    )
    for field, observed, expected in terminal_bindings:
        if observed != expected:
            raise _error(
                "DIAGNOSIS_TERMINAL_EVIDENCE_MISMATCH",
                "Diagnosis terminal reference does not match canonical evidence",
                experiment_id=diagnosis.experiment_id,
                path=f"$.terminal_evidence.{field}",
            )
    terminal_payload = registration.terminal_payload
    assert terminal_payload is not None
    expected_observation = _expected_observation(state, registration, terminal_payload)
    observed_observation = diagnosis.observation.to_dict()
    for field in (
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
    ):
        if observed_observation[field] != expected_observation[field]:
            raise _error(
                "DIAGNOSIS_OBSERVATION_MISMATCH",
                "Diagnosis observation does not match kernel-derived evidence",
                experiment_id=diagnosis.experiment_id,
                path=f"$.observation.{field}",
            )
    _validate_artifact_binding(state, registration, diagnosis)
    return registration


def _apply_diagnosis_event(
    state: ScientificState,
    raw_payload: Mapping[str, Any],
    *,
    event_id: str | None,
    event_hash: str | None,
    event_sequence: int | None,
) -> ScientificState:
    diagnosis = _diagnosis_structural_parts(raw_payload)
    canonical_payload = canonical_json(raw_payload)
    if any(
        experiment_id == diagnosis.experiment_id
        and payload_json == canonical_payload
        for experiment_id, payload_json in state.historical_diagnosis_payloads
    ):
        raise _error(
            "DIAGNOSIS_ALREADY_RECORDED",
            "the experiment already has a canonical Diagnosis",
            experiment_id=diagnosis.experiment_id,
            diagnosis_id=derive_diagnosis_id(state.project_id, diagnosis.digest),
            path="$.experiment_id",
        )
    if raw_payload.get("study_contract_digest") != state.study_contract_digest:
        raise _error(
            "STUDY_CONTRACT_MISMATCH",
            "Diagnosis contract digest does not match the active generation",
            path="$.study_contract_digest",
        )
    observed_digest = raw_payload.get("diagnosis_digest")
    if observed_digest != diagnosis.digest:
        raise _error(
            "DIAGNOSIS_DIGEST_MISMATCH",
            "Diagnosis digest does not match its canonical body",
            path="$.diagnosis_digest",
        )
    expected_id = derive_diagnosis_id(state.project_id, diagnosis.digest)
    if raw_payload.get("diagnosis_id") != expected_id:
        raise _error(
            "DIAGNOSIS_ID_MISMATCH",
            "Diagnosis ID does not match its project-scoped identity",
            path="$.diagnosis_id",
        )
    if (
        raw_payload.get("generation_id") != state.active_generation_id
        or diagnosis.generation_id != state.active_generation_id
    ):
        raise _error(
            "DIAGNOSIS_GENERATION_MISMATCH",
            "Diagnosis generation does not match the active generation",
            path="$.generation_id",
        )
    if raw_payload.get("evaluation_seal_digest") != state.evaluation_seal_digest:
        raise _error(
            "STUDY_EVALUATION_SEAL_MISMATCH",
            "Diagnosis evaluation seal does not match the active generation",
            path="$.evaluation_seal_digest",
        )
    active_compatibility = (
        None if state.evaluation_seal is None else state.evaluation_seal.compatibility_digest
    )
    if (
        raw_payload.get("compatibility_digest") != active_compatibility
        or diagnosis.compatibility_digest != active_compatibility
    ):
        raise _error(
            "DIAGNOSIS_COMPATIBILITY_MISMATCH",
            "Diagnosis compatibility does not match the active generation",
            path="$.compatibility_digest",
        )
    payload = DiagnosisEventPayload.from_mapping(raw_payload, project_id=state.project_id)
    _validate_diagnosis_binding(state, payload)
    existing = _diagnosis_for(state, diagnosis.experiment_id)
    if existing is not None:
        raise _error(
            "DIAGNOSIS_ALREADY_RECORDED",
            "the experiment already has a canonical Diagnosis",
            experiment_id=diagnosis.experiment_id,
            diagnosis_id=existing.diagnosis_id,
            path="$.experiment_id",
        )
    if event_id is None or event_hash is None or event_sequence is None:
        raise _error(
            "DIAGNOSIS_INVALID",
            "Diagnosis replay requires a canonical event envelope",
            path="$",
        )
    record = DiagnosisRecord(
        diagnosis_id=payload.diagnosis_id,
        diagnosis_digest=payload.diagnosis_digest,
        diagnosis_event_id=event_id,
        diagnosis_event_hash=event_hash,
        event_sequence=event_sequence,
        diagnosis=payload.diagnosis,
    )
    return replace(
        state,
        diagnoses=(*state.diagnoses, record),
        historical_diagnosis_payloads=(
            *state.historical_diagnosis_payloads,
            (diagnosis.experiment_id, canonical_payload),
        ),
    )


def _apply_terminal_evidence(
    state: ScientificState,
    event_type: str,
    payload: Mapping[str, Any],
    *,
    event_id: str | None,
    event_hash: str | None,
    event_sequence: int | None,
) -> ScientificState:
    if state.contract is None or state.contract.schema_version != 2:
        return state
    experiment_id = payload.get("experiment_id", payload.get("id"))
    if not isinstance(experiment_id, str):
        return state
    registration = state.registration(experiment_id)
    if registration is None:
        return state
    if event_type == "EXPERIMENT_TERMINATED":
        target_value = payload.get(
            "status",
            payload.get("state", payload.get("outcome")),
        )
    else:
        target_value = payload.get("status", payload.get("state"))
    try:
        target = coerce_state(target_value)
    except LifecycleError as exc:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "typed experiment terminal evidence has an invalid status",
            experiment_id=experiment_id,
        ) from exc
    if target not in TERMINAL_STATES:
        if event_type == "EXPERIMENT_STATUS_CHANGED":
            return state
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "EXPERIMENT_TERMINATED must declare a terminal status",
            experiment_id=experiment_id,
        )
    if registration.is_terminal:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "typed experiment has duplicate terminal evidence",
            experiment_id=experiment_id,
        )
    if "attempt" in payload and payload["attempt"] != registration.attempt:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "terminal attempt does not match its typed registration",
            experiment_id=experiment_id,
        )
    if "retry_of" in payload and payload["retry_of"] != registration.retry_of:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "terminal retry_of does not match its typed registration",
            experiment_id=experiment_id,
        )
    retryable = _terminal_retryable(target, payload)
    if "retryable" in payload:
        declared = payload["retryable"]
        if not isinstance(declared, bool) or declared is not retryable:
            raise _error(
                "STUDY_REGISTRATION_INVALID",
                "terminal retryable metadata conflicts with terminal evidence",
                experiment_id=experiment_id,
            )
    updated = replace(
        registration,
        terminal_status=target.value,
        retryable=retryable,
        terminal_event_type=event_type,
        terminal_event_id=event_id,
        terminal_event_hash=event_hash,
        terminal_event_sequence=event_sequence,
        terminal_payload_json=canonical_json(payload),
    )
    registrations = tuple(
        updated if item.experiment_id == experiment_id else item for item in state.registrations
    )
    return replace(state, registrations=registrations)


def _apply_generation(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> ScientificState:
    if state.active_generation_id is not None:
        _validate_successor_gate(state)
    code = "STUDY_GENERATION_INVALID"
    if set(payload) != _GENERATION_PAYLOAD_KEYS:
        raise _error(
            code,
            "generation payload must have exact version-one fields",
            missing_fields=sorted(_GENERATION_PAYLOAD_KEYS - set(payload)),
            unknown_fields=sorted(set(payload) - _GENERATION_PAYLOAD_KEYS),
        )
    _literal_version(payload["science_state_version"], code=code)
    if payload["authorized_action"] is not None:
        raise _error(code, "generation authorized_action must be null")
    contract_raw = payload["contract"]
    seal_raw = payload["evaluation_seal"]
    if not isinstance(contract_raw, Mapping) or not isinstance(seal_raw, Mapping):
        raise _error(code, "generation contract and evaluation_seal must be objects")
    contract = StudyContract.from_mapping(contract_raw)
    evaluation_seal = EvaluationSeal.from_mapping(seal_raw)
    if payload["study_contract_digest"] != contract.digest:
        raise _error(code, "generation contract digest does not match its contract")
    if payload["evaluation_seal_digest"] != evaluation_seal.digest:
        raise _error(code, "generation evaluation seal digest does not match its seal")
    predecessor = payload["predecessor_generation_id"]
    reason = payload["change_reason"]
    if state.active_generation_id is None:
        if predecessor is not None or reason is not None:
            raise _error(
                "STUDY_GENERATION_MISMATCH",
                "the first generation must have null predecessor and change reason",
            )
    else:
        if predecessor != state.active_generation_id:
            raise _error(
                "STUDY_GENERATION_MISMATCH",
                "generation predecessor does not match the active generation",
                active_generation_id=state.active_generation_id,
                predecessor_generation_id=predecessor,
            )
        if not isinstance(reason, str) or not reason.strip() or reason != reason.strip():
            raise _error(
                "STUDY_CHANGE_REASON_REQUIRED",
                "a trimmed non-empty change reason is required",
            )
        if (
            contract.digest == state.study_contract_digest
            and evaluation_seal.digest == state.evaluation_seal_digest
        ):
            raise _error(
                "STUDY_GENERATION_UNCHANGED",
                "an unchanged successor cannot reset the generation budget",
            )
    expected_id = derive_generation_id(
        state.project_id,
        None if state.active_generation_id is None else state.active_generation_id,
        contract.digest,
        evaluation_seal.digest,
    )
    observed_id = _generation_identifier(payload["generation_id"], code=code, field="generation_id")
    if observed_id != expected_id:
        raise _error(
            code,
            "generation_id does not match the canonical generation identity",
            expected_generation_id=expected_id,
            observed_generation_id=observed_id,
        )
    return ScientificState(
        project_id=state.project_id,
        generation_count=state.generation_count + 1,
        active_generation_id=observed_id,
        contract=contract,
        evaluation_seal=evaluation_seal,
        attempts_used=0,
        retries_used=0,
        elapsed_reserved_milliseconds=0,
        cost_reserved_microunits=(None if contract.budget.max_cost_microunits is None else 0),
        legacy_unstructured_registrations=(state.legacy_unstructured_registrations),
        historical_diagnosis_payloads=state.historical_diagnosis_payloads,
    )


def reduce_scientific_state(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
) -> ScientificState:
    """Replay scientific state from canonical events without I/O or clocks."""

    if not isinstance(project_id, str) or not project_id.strip():
        raise _error("STUDY_STATE_INVALID", "project_id must be non-empty text")
    state = ScientificState(project_id=project_id)
    for event in events:
        event_type, payload = _event_parts(
            event,
            expected_project_id=project_id,
        )
        event_id, event_hash, event_sequence = _event_identity(event)
        if event_type == GENERATION_EVENT_TYPE:
            state = _apply_generation(state, payload)
            continue
        normalized_event_type = _normalized_event_type(event_type)
        if normalized_event_type == "BASELINE_RECORDED":
            state = _apply_scope_baseline(state, payload)
            continue
        if normalized_event_type in {
            "EXPERIMENT_TERMINATED",
            "EXPERIMENT_STATUS_CHANGED",
        }:
            state = _apply_terminal_evidence(
                state,
                normalized_event_type,
                payload,
                event_id=event_id,
                event_hash=event_hash,
                event_sequence=event_sequence,
            )
            continue
        if normalized_event_type == _ARTIFACT_EVENT_TYPE:
            state = _apply_artifact_evidence(
                state,
                payload,
                event_id=event_id,
                event_hash=event_hash,
                event_sequence=event_sequence,
            )
            continue
        if event_type == DIAGNOSIS_EVENT_TYPE:
            state = _apply_diagnosis_event(
                state,
                payload,
                event_id=event_id,
                event_hash=event_hash,
                event_sequence=event_sequence,
            )
            continue
        if normalized_event_type != _REGISTRATION_EVENT_TYPE:
            continue
        present = (_REGISTRATION_SCIENCE_KEYS | _TYPED_REGISTRATION_KEYS).intersection(payload)
        if state.active_generation_id is None:
            if present:
                raise _error(
                    "STUDY_REGISTRATION_INVALID",
                    "pre-generation registration has a partial versioned bundle",
                    present_fields=sorted(present),
                )
            state = replace(
                state,
                legacy_unstructured_registrations=(state.legacy_unstructured_registrations + 1),
            )
            continue
        state = reserve_registration(state, payload)
    return state
