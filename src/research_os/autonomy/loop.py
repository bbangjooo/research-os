"""Finite, event-derived, provider-neutral single-agent research episodes."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, cast

from research_os.agent import (
    bind_agent_context_v3_retrieval,
    record_agent_context_v3_knowledge_disposition,
)
from research_os.contracts.common import (
    FrozenJSONObject,
    canonical_json_bytes,
    copy_json_object,
    freeze_json_object,
    normalize_json_object,
    sha256_json,
)
from research_os.errors import ConfigurationError, IntegrityError
from research_os.kernel.events import Event, EventLog
from research_os.kernel.ids import new_id, stable_id, validate_namespaced_id
from research_os.memory import (
    Claim,
    OriginEvidenceRef,
    ProgramEvent,
    ProgramSnapshot,
    ProgramStore,
    RetrievalQuery,
    RetrievalScope,
    retrieve_claims,
)
from research_os.science import Diagnosis, diagnosis_id, reduce_scientific_state
from research_os.service import ResearchService

from .protocol import (
    DecisionPacket,
    DecisionPacketError,
    ProviderDecisionRequest,
    ProviderRequest,
    build_provider_decision_request,
    validate_decision_packet,
)
from .provider import ProviderPortError

AUTONOMY_EVENT_SCHEMA_VERSION = 1
AUTONOMY_POLICY_SCHEMA_VERSION = 1
PROVIDER_DIAGNOSIS_REQUEST_SCHEMA_VERSION = 1
PROVIDER_DIAGNOSIS_PACKET_SCHEMA_VERSION = 1
PROVIDER_SYNTHESIS_REQUEST_SCHEMA_VERSION = 1
PROVIDER_SYNTHESIS_PACKET_SCHEMA_VERSION = 1
NEXT_QUERY_PLAN_SCHEMA_VERSION = 1

EPISODE_STARTED = "research_os.autonomy.episode_started.v1"
PROVIDER_CALL_STARTED = "research_os.autonomy.provider_call_started.v1"
PROPOSAL_RETURNED = "research_os.autonomy.proposal_returned.v1"
PREFLIGHT_ACCEPTED = "research_os.autonomy.preflight_accepted.v1"
EXPERIMENT_STARTED = "research_os.autonomy.experiment_started.v1"
EXPERIMENT_LINKED = "research_os.autonomy.experiment_linked.v1"
DIAGNOSIS_LINKED = "research_os.autonomy.diagnosis_linked.v1"
SYNTHESIS_LINKED = "research_os.autonomy.synthesis_linked.v1"
NEXT_PLANNED = "research_os.autonomy.next_planned.v1"
STOPPED = "research_os.autonomy.stopped.v1"
PROVIDER_REJECTED = "research_os.autonomy.provider_rejected.v1"

AUTONOMY_EVENT_TYPES = frozenset(
    {
        EPISODE_STARTED,
        PROVIDER_CALL_STARTED,
        PROPOSAL_RETURNED,
        PREFLIGHT_ACCEPTED,
        EXPERIMENT_STARTED,
        EXPERIMENT_LINKED,
        DIAGNOSIS_LINKED,
        SYNTHESIS_LINKED,
        NEXT_PLANNED,
        STOPPED,
        PROVIDER_REJECTED,
    }
)

_DIGEST_LENGTH = 64
_CALL_KINDS = frozenset({"proposal", "diagnosis", "synthesis"})
_PHASES = frozenset({"context", "proposal", "preflight", "run", "diagnosis", "synthesis", "next", "stop"})
_STOP_PRECEDENCE = (
    "closed_class",
    "study_stop",
    "experiment_budget_exhausted",
    "provider_budget_exhausted",
    "invalid_packet_budget_exhausted",
    "token_budget_exhausted",
    "time_budget_exhausted",
)


class AutonomyLoopError(ConfigurationError):
    """Stable fail-closed error raised by the autonomy control plane."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.details = MappingProxyType(dict(details or {}))
        super().__init__(f"{code}: {message}")


def _fail(code: str, message: str, **details: object) -> AutonomyLoopError:
    return AutonomyLoopError(code, message, details=details)


def _object(value: object, keys: frozenset[str], *, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail("AUTONOMY_EVENT_INVALID", f"{path} must be an object", path=path)
    observed = set(value)
    if observed != keys:
        raise _fail(
            "AUTONOMY_EVENT_INVALID",
            f"{path} has invalid keys",
            path=path,
            missing=sorted(keys - observed),
            extra=sorted(observed - keys),
        )
    return value


def _integer(value: object, *, path: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _fail("AUTONOMY_EVENT_INVALID", f"{path} must be an integer >= {minimum}")
    return value


def _text(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail("AUTONOMY_EVENT_INVALID", f"{path} must be non-empty text")
    return value


def _identifier(value: object, namespace: str, *, path: str) -> str:
    try:
        return validate_namespaced_id(cast(str, value), namespace)
    except (TypeError, ValueError) as exc:
        raise _fail("AUTONOMY_EVENT_INVALID", f"{path} has an invalid identity") from exc


def _digest(value: object, *, path: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _DIGEST_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _fail("AUTONOMY_EVENT_INVALID", f"{path} must be a lowercase SHA-256 digest")
    return value


def _non_null_authority(value: object) -> int:
    if isinstance(value, Mapping):
        return int(value.get("authorized_action") is not None) + sum(
            _non_null_authority(item) for item in value.values()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        return sum(_non_null_authority(item) for item in value)
    return 0


def canonical_token_units(value: Mapping[str, Any]) -> int:
    """Return the fixed provider-neutral token accounting unit for JSON values."""

    size = len(canonical_json_bytes(value))
    return (size + 3) // 4


@dataclass(frozen=True, slots=True)
class AutonomyPolicy:
    autonomy_policy_schema_version: int
    max_experiments: int
    max_provider_calls: int
    max_invalid_packets: int
    max_token_units: int
    max_elapsed_milliseconds: int
    provider_token_reservation: int
    provider_elapsed_reservation_milliseconds: int
    context_limit: int
    authorized_action: None = None

    _KEYS = frozenset(
        {
            "autonomy_policy_schema_version",
            "max_experiments",
            "max_provider_calls",
            "max_invalid_packets",
            "max_token_units",
            "max_elapsed_milliseconds",
            "provider_token_reservation",
            "provider_elapsed_reservation_milliseconds",
            "context_limit",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> AutonomyPolicy:
        try:
            value = _object(raw, cls._KEYS, path="$.policy")
            if value["authorized_action"] is not None:
                raise _fail("AUTONOMY_POLICY_INVALID", "policy authority must be null")
            version = _integer(value["autonomy_policy_schema_version"], path="$.policy.version", minimum=1)
            if version != AUTONOMY_POLICY_SCHEMA_VERSION:
                raise _fail("AUTONOMY_POLICY_INVALID", "unsupported policy schema")
            maxima = [
                _integer(
                    value[name],
                    path=f"$.policy.{name}",
                    minimum=1 if name == "max_invalid_packets" else 0,
                )
                for name in (
                    "max_experiments",
                    "max_provider_calls",
                    "max_invalid_packets",
                    "max_token_units",
                    "max_elapsed_milliseconds",
                )
            ]
            reservations = [
                _integer(value[name], path=f"$.policy.{name}", minimum=1)
                for name in (
                    "provider_token_reservation",
                    "provider_elapsed_reservation_milliseconds",
                    "context_limit",
                )
            ]
            if reservations[2] > 100:
                raise _fail("AUTONOMY_POLICY_INVALID", "context_limit must not exceed 100")
            return cls(version, *maxima, *reservations)
        except AutonomyLoopError as exc:
            if exc.code == "AUTONOMY_POLICY_INVALID":
                raise
            raise _fail("AUTONOMY_POLICY_INVALID", "AutonomyPolicy is invalid") from exc

    def to_dict(self) -> dict[str, Any]:
        return {
            "autonomy_policy_schema_version": self.autonomy_policy_schema_version,
            "max_experiments": self.max_experiments,
            "max_provider_calls": self.max_provider_calls,
            "max_invalid_packets": self.max_invalid_packets,
            "max_token_units": self.max_token_units,
            "max_elapsed_milliseconds": self.max_elapsed_milliseconds,
            "provider_token_reservation": self.provider_token_reservation,
            "provider_elapsed_reservation_milliseconds": self.provider_elapsed_reservation_milliseconds,
            "context_limit": self.context_limit,
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class NextQueryPlan:
    next_query_plan_schema_version: int
    hypothesis_class_id: str
    compatibility_digest: str
    evaluation_scope: RetrievalScope
    claim_kinds: tuple[str, ...]
    diagnosis_digest: str | None
    relation_types: tuple[str, ...]
    limit: int
    authorized_action: None = None

    _KEYS = frozenset(
        {
            "next_query_plan_schema_version",
            "hypothesis_class_id",
            "compatibility_digest",
            "evaluation_scope",
            "claim_kinds",
            "diagnosis_digest",
            "relation_types",
            "limit",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> NextQueryPlan:
        value = _object(raw, cls._KEYS, path="$.next_query_plan")
        if value["authorized_action"] is not None:
            raise _fail("AUTONOMY_SYNTHESIS_INVALID", "next query authority must be null")
        version = _integer(value["next_query_plan_schema_version"], path="$.next_query_plan.version", minimum=1)
        if version != NEXT_QUERY_PLAN_SCHEMA_VERSION:
            raise _fail("AUTONOMY_SYNTHESIS_INVALID", "unsupported next query plan schema")
        diagnosis_raw = value["diagnosis_digest"]
        diagnosis = None if diagnosis_raw is None else _digest(diagnosis_raw, path="$.next_query_plan.diagnosis_digest")
        raw_kinds = value["claim_kinds"]
        raw_relations = value["relation_types"]
        if not isinstance(raw_kinds, Sequence) or isinstance(raw_kinds, (str, bytes, bytearray)):
            raise _fail("AUTONOMY_SYNTHESIS_INVALID", "claim_kinds must be an array")
        if not isinstance(raw_relations, Sequence) or isinstance(raw_relations, (str, bytes, bytearray)):
            raise _fail("AUTONOMY_SYNTHESIS_INVALID", "relation_types must be an array")
        kinds = tuple(_text(item, path="$.next_query_plan.claim_kinds[]") for item in raw_kinds)
        relations = tuple(_text(item, path="$.next_query_plan.relation_types[]") for item in raw_relations)
        return cls(
            version,
            _text(value["hypothesis_class_id"], path="$.next_query_plan.hypothesis_class_id"),
            _digest(value["compatibility_digest"], path="$.next_query_plan.compatibility_digest"),
            RetrievalScope.from_mapping(cast(Mapping[str, Any], value["evaluation_scope"])),
            kinds,
            diagnosis,
            relations,
            _integer(value["limit"], path="$.next_query_plan.limit", minimum=1),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "next_query_plan_schema_version": self.next_query_plan_schema_version,
            "hypothesis_class_id": self.hypothesis_class_id,
            "compatibility_digest": self.compatibility_digest,
            "evaluation_scope": self.evaluation_scope.to_dict(),
            "claim_kinds": list(self.claim_kinds),
            "diagnosis_digest": self.diagnosis_digest,
            "relation_types": list(self.relation_types),
            "limit": self.limit,
            "authorized_action": None,
        }

    def bind(self, snapshot: ProgramSnapshot) -> RetrievalQuery:
        body = self.to_dict()
        return RetrievalQuery.from_mapping(
            {
                "retrieval_query_schema_version": 1,
                "query_id": stable_id("query", snapshot.program_id, snapshot.program_head, body),
                "program_id": snapshot.program_id,
                "program_head": {"sequence": snapshot.program_head[0], "hash": snapshot.program_head[1]},
                "hypothesis_class_id": self.hypothesis_class_id,
                "compatibility_digest": self.compatibility_digest,
                "evaluation_scope": self.evaluation_scope.to_dict(),
                "claim_kinds": list(self.claim_kinds),
                "diagnosis_digest": self.diagnosis_digest,
                "relation_types": list(self.relation_types),
                "limit": self.limit,
                "authorized_action": None,
            }
        )


@dataclass(frozen=True, slots=True)
class ProviderDiagnosisRequest(ProviderRequest):
    provider_diagnosis_request_schema_version: int
    provider_request_id: str
    episode_id: str
    experiment_id: str
    decision_packet_id: str
    proposal: FrozenJSONObject
    terminal_ref: FrozenJSONObject
    diagnosis_template: FrozenJSONObject
    authorized_action: None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProviderDiagnosisRequest:
        keys = frozenset({"provider_diagnosis_request_schema_version", "provider_request_id", "episode_id", "experiment_id", "decision_packet_id", "proposal", "terminal_ref", "diagnosis_template", "authorized_action"})
        value = _object(raw, keys, path="$.provider_diagnosis_request")
        if value["authorized_action"] is not None or _non_null_authority(value):
            raise _fail("AUTONOMY_DIAGNOSIS_INVALID", "diagnosis request authority must be null")
        version = _integer(value["provider_diagnosis_request_schema_version"], path="$.provider_diagnosis_request.version", minimum=1)
        if version != PROVIDER_DIAGNOSIS_REQUEST_SCHEMA_VERSION:
            raise _fail("AUTONOMY_DIAGNOSIS_INVALID", "unsupported diagnosis request schema")
        objects: list[FrozenJSONObject] = []
        for name in ("proposal", "terminal_ref", "diagnosis_template"):
            item = value[name]
            if not isinstance(item, Mapping):
                raise _fail("AUTONOMY_DIAGNOSIS_INVALID", f"{name} must be an object")
            objects.append(freeze_json_object(item, field_name=name))
        return cls(
            version,
            _identifier(value["provider_request_id"], "providerrequest", path="$.provider_diagnosis_request.provider_request_id"),
            _identifier(value["episode_id"], "episode", path="$.provider_diagnosis_request.episode_id"),
            _identifier(value["experiment_id"], "experiment", path="$.provider_diagnosis_request.experiment_id"),
            _identifier(value["decision_packet_id"], "decisionpacket", path="$.provider_diagnosis_request.decision_packet_id"),
            *objects,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_diagnosis_request_schema_version": self.provider_diagnosis_request_schema_version,
            "provider_request_id": self.provider_request_id,
            "episode_id": self.episode_id,
            "experiment_id": self.experiment_id,
            "decision_packet_id": self.decision_packet_id,
            "proposal": copy_json_object(self.proposal),
            "terminal_ref": copy_json_object(self.terminal_ref),
            "diagnosis_template": copy_json_object(self.diagnosis_template),
            "authorized_action": None,
        }

    def frozen_mapping(self) -> FrozenJSONObject:
        return freeze_json_object(self.to_dict(), field_name="provider_diagnosis_request")


@dataclass(frozen=True, slots=True)
class ProviderDiagnosisPacket:
    provider_diagnosis_packet_schema_version: int
    provider_request_id: str
    episode_id: str
    diagnosis: Diagnosis
    authorized_action: None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProviderDiagnosisPacket:
        keys = frozenset({"provider_diagnosis_packet_schema_version", "provider_request_id", "episode_id", "diagnosis", "authorized_action"})
        value = _object(raw, keys, path="$.provider_diagnosis_packet")
        if value["authorized_action"] is not None or _non_null_authority(value):
            raise _fail("AUTONOMY_DIAGNOSIS_INVALID", "diagnosis packet authority must be null")
        version = _integer(value["provider_diagnosis_packet_schema_version"], path="$.provider_diagnosis_packet.version", minimum=1)
        if version != PROVIDER_DIAGNOSIS_PACKET_SCHEMA_VERSION:
            raise _fail("AUTONOMY_DIAGNOSIS_INVALID", "unsupported diagnosis packet schema")
        try:
            diagnosis = Diagnosis.from_mapping(cast(Mapping[str, Any], value["diagnosis"]))
        except Exception as exc:
            raise _fail("AUTONOMY_DIAGNOSIS_INVALID", "provider Diagnosis is invalid") from exc
        return cls(
            version,
            _identifier(value["provider_request_id"], "providerrequest", path="$.provider_diagnosis_packet.provider_request_id"),
            _identifier(value["episode_id"], "episode", path="$.provider_diagnosis_packet.episode_id"),
            diagnosis,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_diagnosis_packet_schema_version": self.provider_diagnosis_packet_schema_version,
            "provider_request_id": self.provider_request_id,
            "episode_id": self.episode_id,
            "diagnosis": self.diagnosis.to_dict(),
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class ProviderSynthesisRequest(ProviderRequest):
    provider_synthesis_request_schema_version: int
    provider_request_id: str
    episode_id: str
    experiment_id: str
    diagnosis: FrozenJSONObject
    origin_evidence: FrozenJSONObject
    class_state: FrozenJSONObject
    program_snapshot: FrozenJSONObject
    decision_packet: FrozenJSONObject
    authorized_action: None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProviderSynthesisRequest:
        keys = frozenset({"provider_synthesis_request_schema_version", "provider_request_id", "episode_id", "experiment_id", "diagnosis", "origin_evidence", "class_state", "program_snapshot", "decision_packet", "authorized_action"})
        value = _object(raw, keys, path="$.provider_synthesis_request")
        if value["authorized_action"] is not None or _non_null_authority(value):
            raise _fail("AUTONOMY_SYNTHESIS_INVALID", "synthesis request authority must be null")
        version = _integer(value["provider_synthesis_request_schema_version"], path="$.provider_synthesis_request.version", minimum=1)
        if version != PROVIDER_SYNTHESIS_REQUEST_SCHEMA_VERSION:
            raise _fail("AUTONOMY_SYNTHESIS_INVALID", "unsupported synthesis request schema")
        objects: list[FrozenJSONObject] = []
        for name in ("diagnosis", "origin_evidence", "class_state", "program_snapshot", "decision_packet"):
            item = value[name]
            if not isinstance(item, Mapping):
                raise _fail("AUTONOMY_SYNTHESIS_INVALID", f"{name} must be an object")
            objects.append(freeze_json_object(item, field_name=name))
        return cls(
            version,
            _identifier(value["provider_request_id"], "providerrequest", path="$.provider_synthesis_request.provider_request_id"),
            _identifier(value["episode_id"], "episode", path="$.provider_synthesis_request.episode_id"),
            _identifier(value["experiment_id"], "experiment", path="$.provider_synthesis_request.experiment_id"),
            *objects,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_synthesis_request_schema_version": self.provider_synthesis_request_schema_version,
            "provider_request_id": self.provider_request_id,
            "episode_id": self.episode_id,
            "experiment_id": self.experiment_id,
            "diagnosis": copy_json_object(self.diagnosis),
            "origin_evidence": copy_json_object(self.origin_evidence),
            "class_state": copy_json_object(self.class_state),
            "program_snapshot": copy_json_object(self.program_snapshot),
            "decision_packet": copy_json_object(self.decision_packet),
            "authorized_action": None,
        }

    def frozen_mapping(self) -> FrozenJSONObject:
        return freeze_json_object(self.to_dict(), field_name="provider_synthesis_request")


@dataclass(frozen=True, slots=True)
class ProviderSynthesisPacket:
    provider_synthesis_packet_schema_version: int
    provider_request_id: str
    episode_id: str
    diagnosis_id: str
    diagnosis_digest: str
    origin_id: str
    origin_digest: str
    class_state_id: str
    class_state_digest: str
    claim: Claim
    decision: str
    next_query_plan: NextQueryPlan | None
    stop_reason: str | None
    authorized_action: None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProviderSynthesisPacket:
        keys = frozenset({"provider_synthesis_packet_schema_version", "provider_request_id", "episode_id", "diagnosis_id", "diagnosis_digest", "origin_id", "origin_digest", "class_state_id", "class_state_digest", "claim", "decision", "next_query_plan", "stop_reason", "authorized_action"})
        value = _object(raw, keys, path="$.provider_synthesis_packet")
        if value["authorized_action"] is not None or _non_null_authority(value):
            raise _fail("AUTONOMY_SYNTHESIS_INVALID", "synthesis packet authority must be null")
        version = _integer(value["provider_synthesis_packet_schema_version"], path="$.provider_synthesis_packet.version", minimum=1)
        if version != PROVIDER_SYNTHESIS_PACKET_SCHEMA_VERSION:
            raise _fail("AUTONOMY_SYNTHESIS_INVALID", "unsupported synthesis packet schema")
        decision = _text(value["decision"], path="$.provider_synthesis_packet.decision")
        if decision not in {"next", "stop"}:
            raise _fail("AUTONOMY_SYNTHESIS_INVALID", "synthesis decision must be next or stop")
        plan_raw = value["next_query_plan"]
        reason_raw = value["stop_reason"]
        if decision == "next":
            if not isinstance(plan_raw, Mapping) or reason_raw is not None:
                raise _fail("AUTONOMY_SYNTHESIS_INVALID", "next requires a query plan and null stop reason")
            plan = NextQueryPlan.from_mapping(plan_raw)
            reason = None
        else:
            if plan_raw is not None:
                raise _fail("AUTONOMY_SYNTHESIS_INVALID", "stop requires null next query plan")
            plan = None
            reason = _text(reason_raw, path="$.provider_synthesis_packet.stop_reason")
        try:
            claim = Claim.from_mapping(cast(Mapping[str, Any], value["claim"]))
        except Exception as exc:
            raise _fail("AUTONOMY_SYNTHESIS_INVALID", "provider Claim is invalid") from exc
        return cls(
            version,
            _identifier(value["provider_request_id"], "providerrequest", path="$.provider_synthesis_packet.provider_request_id"),
            _identifier(value["episode_id"], "episode", path="$.provider_synthesis_packet.episode_id"),
            _identifier(value["diagnosis_id"], "diagnosis", path="$.provider_synthesis_packet.diagnosis_id"),
            _digest(value["diagnosis_digest"], path="$.provider_synthesis_packet.diagnosis_digest"),
            _identifier(value["origin_id"], "origin", path="$.provider_synthesis_packet.origin_id"),
            _digest(value["origin_digest"], path="$.provider_synthesis_packet.origin_digest"),
            _identifier(value["class_state_id"], "classstate", path="$.provider_synthesis_packet.class_state_id"),
            _digest(value["class_state_digest"], path="$.provider_synthesis_packet.class_state_digest"),
            claim,
            decision,
            plan,
            reason,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_synthesis_packet_schema_version": self.provider_synthesis_packet_schema_version,
            "provider_request_id": self.provider_request_id,
            "episode_id": self.episode_id,
            "diagnosis_id": self.diagnosis_id,
            "diagnosis_digest": self.diagnosis_digest,
            "origin_id": self.origin_id,
            "origin_digest": self.origin_digest,
            "class_state_id": self.class_state_id,
            "class_state_digest": self.class_state_digest,
            "claim": self.claim.to_dict(),
            "decision": self.decision,
            "next_query_plan": None if self.next_query_plan is None else self.next_query_plan.to_dict(),
            "stop_reason": self.stop_reason,
            "authorized_action": None,
        }


class ProviderInvoker(Protocol):
    def invoke(self, request: ProviderRequest) -> Mapping[str, Any]: ...


@dataclass(frozen=True, slots=True)
class AutonomyEpisodeState:
    project_id: str
    episode_id: str
    policy: AutonomyPolicy
    phase: str
    initial_query: RetrievalQuery
    context: FrozenJSONObject
    project_context_token: str
    proposal_request: ProviderDecisionRequest
    packet: DecisionPacket | None = None
    experiment_started: bool = False
    execution_id: str | None = None
    experiment_result: FrozenJSONObject | None = None
    terminal_ref: FrozenJSONObject | None = None
    disposition_ref: FrozenJSONObject | None = None
    diagnosis_packet: ProviderDiagnosisPacket | None = None
    diagnosis_ref: FrozenJSONObject | None = None
    origin_ref: FrozenJSONObject | None = None
    synthesis_packet: ProviderSynthesisPacket | None = None
    claim_ref: FrozenJSONObject | None = None
    class_state_ref: FrozenJSONObject | None = None
    terminal_history: tuple[FrozenJSONObject, ...] = ()
    disposition_history: tuple[FrozenJSONObject, ...] = ()
    diagnosis_history: tuple[FrozenJSONObject, ...] = ()
    origin_history: tuple[FrozenJSONObject, ...] = ()
    claim_history: tuple[FrozenJSONObject, ...] = ()
    class_state_history: tuple[FrozenJSONObject, ...] = ()
    next_query: RetrievalQuery | None = None
    next_context: FrozenJSONObject | None = None
    next_project_context_token: str | None = None
    next_proposal_request: ProviderDecisionRequest | None = None
    pending_call_kind: str | None = None
    pending_call_id: str | None = None
    pending_request: FrozenJSONObject | None = None
    provider_calls: int = 0
    invalid_packets: int = 0
    token_units_reserved: int = 0
    elapsed_milliseconds_reserved: int = 0
    experiments: int = 0
    stop_reason: str | None = None
    complete: bool = False
    stop_summary: FrozenJSONObject | None = None
    last_event_sequence: int = 0
    last_event_hash: str | None = None
    authorized_action: None = None

    @property
    def current_query(self) -> RetrievalQuery:
        return self.next_query or self.initial_query

    @property
    def current_context(self) -> FrozenJSONObject:
        return self.next_context or self.context

    @property
    def current_project_context_token(self) -> str:
        return self.next_project_context_token or self.project_context_token

    @property
    def current_proposal_request(self) -> ProviderDecisionRequest:
        return self.next_proposal_request or self.proposal_request

    def budget_dict(self) -> dict[str, Any]:
        return {
            "experiments": {"used": self.experiments, "limit": self.policy.max_experiments},
            "provider_calls": {"used": self.provider_calls, "limit": self.policy.max_provider_calls},
            "invalid_packets": {"used": self.invalid_packets, "limit": self.policy.max_invalid_packets},
            "token_units": {"reserved": self.token_units_reserved, "limit": self.policy.max_token_units},
            "elapsed_milliseconds": {"reserved": self.elapsed_milliseconds_reserved, "limit": self.policy.max_elapsed_milliseconds},
            "authorized_action": None,
        }

    def to_dict(self) -> dict[str, Any]:
        return normalize_json_object(
            {
                "autonomy_episode_state_schema_version": 1,
                "project_id": self.project_id,
                "episode_id": self.episode_id,
                "phase": self.phase,
                "policy": self.policy.to_dict(),
                "current_query": self.current_query.to_dict(),
                "packet_id": None if self.packet is None else self.packet.packet_id,
                "experiment_result": None if self.experiment_result is None else copy_json_object(self.experiment_result),
                "terminal_ref": None if self.terminal_ref is None else copy_json_object(self.terminal_ref),
                "disposition_ref": None if self.disposition_ref is None else copy_json_object(self.disposition_ref),
                "diagnosis_ref": None if self.diagnosis_ref is None else copy_json_object(self.diagnosis_ref),
                "origin_ref": None if self.origin_ref is None else copy_json_object(self.origin_ref),
                "claim_ref": None if self.claim_ref is None else copy_json_object(self.claim_ref),
                "class_state_ref": None if self.class_state_ref is None else copy_json_object(self.class_state_ref),
                "history_counts": {
                    "terminals": len(self.terminal_history),
                    "dispositions": len(self.disposition_history),
                    "diagnoses": len(self.diagnosis_history),
                    "origins": len(self.origin_history),
                    "claims": len(self.claim_history),
                    "class_states": len(self.class_state_history),
                },
                "pending_call_kind": self.pending_call_kind,
                "budget": self.budget_dict(),
                "stop_reason": self.stop_reason,
                "complete": self.complete,
                "last_autonomy_head": {"sequence": self.last_event_sequence, "hash": self.last_event_hash},
                "authorized_action": None,
            },
            field_name="autonomy episode state",
        )


def _episode_summary(
    state: AutonomyEpisodeState, reason: str, complete: bool
) -> dict[str, Any]:
    return normalize_json_object(
        {
            "autonomy_summary_schema_version": 1,
            "project_id": state.project_id,
            "episode_id": state.episode_id,
            "status": "complete" if complete else "incomplete",
            "stop_reason": reason,
            "terminal_refs": [copy_json_object(item) for item in state.terminal_history],
            "disposition_refs": [copy_json_object(item) for item in state.disposition_history],
            "diagnosis_refs": [copy_json_object(item) for item in state.diagnosis_history],
            "origin_refs": [copy_json_object(item) for item in state.origin_history],
            "claim_refs": [copy_json_object(item) for item in state.claim_history],
            "class_state_refs": [copy_json_object(item) for item in state.class_state_history],
            "budget": state.budget_dict(),
            "autonomy_head": {
                "sequence": state.last_event_sequence,
                "hash": state.last_event_hash,
            },
            "authorized_action": None,
        },
        field_name="autonomy summary",
    )


_BASE_EVENT_KEYS = frozenset(
    {"autonomy_event_schema_version", "episode_id", "authorized_action"}
)


def _payload(event: Event, keys: frozenset[str], episode_id: str | None) -> Mapping[str, Any]:
    value = _object(event.payload, _BASE_EVENT_KEYS | keys, path=f"$.events[{event.sequence}].payload")
    version = _integer(
        value["autonomy_event_schema_version"],
        path=f"$.events[{event.sequence}].payload.autonomy_event_schema_version",
        minimum=1,
    )
    if version != AUTONOMY_EVENT_SCHEMA_VERSION:
        raise _fail("AUTONOMY_EVENT_INVALID", "unsupported autonomy event schema")
    observed_episode = _identifier(
        value["episode_id"], "episode", path=f"$.events[{event.sequence}].payload.episode_id"
    )
    if episode_id is not None and observed_episode != episode_id:
        raise _fail("AUTONOMY_STATE_INVALID", "autonomy event belongs to another episode")
    if value["authorized_action"] is not None or _non_null_authority(value):
        raise _fail("AUTONOMY_EVENT_INVALID", "autonomy event authority must be recursively null")
    return value


def _frozen_object(value: object, *, field_name: str) -> FrozenJSONObject:
    if not isinstance(value, Mapping):
        raise _fail("AUTONOMY_EVENT_INVALID", f"{field_name} must be an object")
    try:
        return freeze_json_object(value, field_name=field_name)
    except (TypeError, ValueError) as exc:
        raise _fail("AUTONOMY_EVENT_INVALID", f"{field_name} is not strict JSON") from exc


def _provider_request(kind: str, value: object) -> ProviderRequest:
    if not isinstance(value, Mapping):
        raise _fail("AUTONOMY_EVENT_INVALID", "provider request must be an object")
    if kind == "proposal":
        return ProviderDecisionRequest.from_mapping(value)
    if kind == "diagnosis":
        return ProviderDiagnosisRequest.from_mapping(value)
    if kind == "synthesis":
        return ProviderSynthesisRequest.from_mapping(value)
    raise _fail("AUTONOMY_EVENT_INVALID", "provider call kind is unsupported")


def _head(state: AutonomyEpisodeState, event: Event) -> AutonomyEpisodeState:
    return replace(state, last_event_sequence=event.sequence, last_event_hash=event.hash)


def reduce_autonomy_events(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    episode_id: str | None = None,
) -> AutonomyEpisodeState:
    """Replay one exact episode from its independent append-only AutonomyLog."""

    try:
        validate_namespaced_id(episode_id, "episode") if episode_id is not None else None
    except (TypeError, ValueError) as exc:
        raise _fail("AUTONOMY_STATE_INVALID", "episode_id is invalid") from exc
    state: AutonomyEpisodeState | None = None
    normalized_events = [
        event if isinstance(event, Event) else Event.from_mapping(event) for event in events
    ]
    for event in normalized_events:
        if event.project_id != project_id:
            raise _fail("AUTONOMY_STATE_INVALID", "AutonomyLog project identity changed")
        if event.event_type not in AUTONOMY_EVENT_TYPES:
            raise _fail("AUTONOMY_EVENT_INVALID", "unsupported autonomy event type")
        if state is None:
            if event.event_type != EPISODE_STARTED:
                raise _fail("AUTONOMY_STATE_INVALID", "first autonomy event must start the episode")
            value = _payload(
                event,
                frozenset(
                    {
                        "policy",
                        "initial_query",
                        "context",
                        "project_context_token",
                        "proposal_request",
                    }
                ),
                episode_id,
            )
            observed_episode = cast(str, value["episode_id"])
            try:
                policy = AutonomyPolicy.from_mapping(cast(Mapping[str, Any], value["policy"]))
                query = RetrievalQuery.from_mapping(cast(Mapping[str, Any], value["initial_query"]))
                request = ProviderDecisionRequest.from_mapping(
                    cast(Mapping[str, Any], value["proposal_request"])
                )
            except AutonomyLoopError:
                raise
            except Exception as exc:
                raise _fail("AUTONOMY_STATE_INVALID", "episode start contract is invalid") from exc
            context = _frozen_object(value["context"], field_name="episode context")
            if canonical_json_bytes(request.context) != canonical_json_bytes(context):
                raise _fail("AUTONOMY_STATE_INVALID", "proposal request does not bind episode context")
            state = AutonomyEpisodeState(
                project_id,
                observed_episode,
                policy,
                "context",
                query,
                context,
                _digest(value["project_context_token"], path="$.project_context_token"),
                request,
                last_event_sequence=event.sequence,
                last_event_hash=event.hash,
            )
            continue

        if event.event_type == EPISODE_STARTED:
            raise _fail("AUTONOMY_STATE_INVALID", "episode start is duplicated")
        if state.phase == "stop":
            raise _fail("AUTONOMY_STATE_INVALID", "events cannot follow an episode stop")

        if event.event_type == PROVIDER_CALL_STARTED:
            value = _payload(
                event,
                frozenset(
                    {
                        "call_id",
                        "call_kind",
                        "request",
                        "request_digest",
                        "token_reservation",
                        "elapsed_reservation_milliseconds",
                    }
                ),
                state.episode_id,
            )
            if state.pending_call_id is not None:
                raise _fail("AUTONOMY_STATE_INVALID", "a provider call is already pending")
            kind = _text(value["call_kind"], path="$.call_kind")
            if kind not in _CALL_KINDS:
                raise _fail("AUTONOMY_EVENT_INVALID", "provider call kind is unsupported")
            allowed = {"proposal": {"context", "next"}, "diagnosis": {"run"}, "synthesis": {"diagnosis"}}
            if state.phase not in allowed[kind]:
                raise _fail("AUTONOMY_STATE_INVALID", "provider call is illegal in the current phase")
            request = _provider_request(kind, value["request"])
            request_dict = cast(Any, request).to_dict()
            if _digest(value["request_digest"], path="$.request_digest") != sha256_json(request_dict):
                raise _fail("AUTONOMY_EVENT_INVALID", "provider request digest changed")
            token_reservation = _integer(value["token_reservation"], path="$.token_reservation", minimum=1)
            elapsed_reservation = _integer(
                value["elapsed_reservation_milliseconds"],
                path="$.elapsed_reservation_milliseconds",
                minimum=1,
            )
            if (
                token_reservation != state.policy.provider_token_reservation
                or elapsed_reservation != state.policy.provider_elapsed_reservation_milliseconds
                or canonical_token_units(request_dict) > token_reservation
            ):
                raise _fail("AUTONOMY_STATE_INVALID", "provider reservation does not cover the request")
            provider_calls = state.provider_calls + 1
            token_units = state.token_units_reserved + token_reservation
            elapsed = state.elapsed_milliseconds_reserved + elapsed_reservation
            if (
                provider_calls > state.policy.max_provider_calls
                or token_units > state.policy.max_token_units
                or elapsed > state.policy.max_elapsed_milliseconds
            ):
                raise _fail("AUTONOMY_STATE_INVALID", "provider call exceeded the episode budget")
            state = replace(
                state,
                pending_call_kind=kind,
                pending_call_id=_identifier(value["call_id"], "providercall", path="$.call_id"),
                pending_request=freeze_json_object(request_dict, field_name="pending provider request"),
                provider_calls=provider_calls,
                token_units_reserved=token_units,
                elapsed_milliseconds_reserved=elapsed,
            )
        elif event.event_type == PROPOSAL_RETURNED:
            value = _payload(
                event,
                frozenset({"call_id", "packet", "packet_digest"}),
                state.episode_id,
            )
            if state.pending_call_kind != "proposal" or value["call_id"] != state.pending_call_id:
                raise _fail("AUTONOMY_STATE_INVALID", "proposal result has no matching provider call")
            try:
                packet = DecisionPacket.from_mapping(cast(Mapping[str, Any], value["packet"]))
            except DecisionPacketError as exc:
                raise _fail("AUTONOMY_EVENT_INVALID", "committed proposal packet is invalid") from exc
            if packet.digest != _digest(value["packet_digest"], path="$.packet_digest"):
                raise _fail("AUTONOMY_EVENT_INVALID", "proposal packet digest changed")
            request_raw = cast(Mapping[str, Any], state.pending_request)
            request = ProviderDecisionRequest.from_mapping(request_raw)
            if packet.provider_request_id != request.provider_request_id:
                raise _fail("AUTONOMY_STATE_INVALID", "proposal result request identity changed")
            state = replace(
                state,
                phase="proposal",
                packet=packet,
                pending_call_kind=None,
                pending_call_id=None,
                pending_request=None,
            )
        elif event.event_type == PREFLIGHT_ACCEPTED:
            value = _payload(
                event,
                frozenset({"packet_id", "packet_digest"}),
                state.episode_id,
            )
            if state.phase != "proposal" or state.packet is None:
                raise _fail("AUTONOMY_STATE_INVALID", "preflight has no proposal")
            if value["packet_id"] != state.packet.packet_id or value["packet_digest"] != state.packet.digest:
                raise _fail("AUTONOMY_STATE_INVALID", "preflight packet binding changed")
            state = replace(state, phase="preflight")
        elif event.event_type == EXPERIMENT_STARTED:
            value = _payload(
                event,
                frozenset({"execution_id", "packet_id", "elapsed_reservation_milliseconds"}),
                state.episode_id,
            )
            if state.phase != "preflight" or state.packet is None or state.experiment_started:
                raise _fail("AUTONOMY_STATE_INVALID", "experiment start is illegal")
            if value["packet_id"] != state.packet.packet_id:
                raise _fail("AUTONOMY_STATE_INVALID", "experiment packet binding changed")
            execution_id = _identifier(value["execution_id"], "execution", path="$.execution_id")
            reservation = _integer(
                value["elapsed_reservation_milliseconds"],
                path="$.elapsed_reservation_milliseconds",
                minimum=1,
            )
            elapsed = state.elapsed_milliseconds_reserved + reservation
            experiments = state.experiments + 1
            if experiments > state.policy.max_experiments or elapsed > state.policy.max_elapsed_milliseconds:
                raise _fail("AUTONOMY_STATE_INVALID", "experiment start exceeded the episode budget")
            state = replace(
                state,
                experiment_started=True,
                execution_id=execution_id,
                experiments=experiments,
                elapsed_milliseconds_reserved=elapsed,
            )
        elif event.event_type == EXPERIMENT_LINKED:
            value = _payload(
                event,
                frozenset({"execution_id", "experiment_result", "terminal_ref", "disposition_ref"}),
                state.episode_id,
            )
            if state.phase != "preflight" or not state.experiment_started:
                raise _fail("AUTONOMY_STATE_INVALID", "experiment result has no started execution")
            execution_id = _identifier(value["execution_id"], "execution", path="$.execution_id")
            if execution_id != state.execution_id:
                raise _fail("AUTONOMY_STATE_INVALID", "experiment execution identity changed")
            terminal_ref = _frozen_object(value["terminal_ref"], field_name="terminal ref")
            disposition_ref = _frozen_object(value["disposition_ref"], field_name="disposition ref")
            result = _frozen_object(value["experiment_result"], field_name="experiment result")
            if state.packet is None or (
                result.get("experiment_id") != terminal_ref.get("experiment_id")
                or disposition_ref.get("proposal_id")
                != state.packet.knowledge_disposition.proposal_id
                or disposition_ref.get("proposal_digest") != state.packet.proposal.digest
                or disposition_ref.get("knowledge_disposition_digest")
                != state.packet.knowledge_disposition.digest
            ):
                raise _fail("AUTONOMY_STATE_INVALID", "experiment evidence binding changed")
            state = replace(
                state,
                phase="run",
                experiment_result=result,
                terminal_ref=terminal_ref,
                disposition_ref=disposition_ref,
                experiment_started=False,
                terminal_history=(*state.terminal_history, terminal_ref),
                disposition_history=(*state.disposition_history, disposition_ref),
            )
        elif event.event_type == DIAGNOSIS_LINKED:
            value = _payload(
                event,
                frozenset({"call_id", "diagnosis_packet", "diagnosis_ref", "origin_ref", "class_state_ref"}),
                state.episode_id,
            )
            if state.phase != "run" or state.pending_call_kind != "diagnosis" or value["call_id"] != state.pending_call_id:
                raise _fail("AUTONOMY_STATE_INVALID", "Diagnosis result has no matching call")
            packet = ProviderDiagnosisPacket.from_mapping(cast(Mapping[str, Any], value["diagnosis_packet"]))
            diagnosis_ref = _frozen_object(value["diagnosis_ref"], field_name="diagnosis ref")
            origin_ref = _frozen_object(value["origin_ref"], field_name="origin ref")
            class_state_ref = _frozen_object(value["class_state_ref"], field_name="class state ref")
            request = ProviderDiagnosisRequest.from_mapping(cast(Mapping[str, Any], state.pending_request))
            origin_raw = origin_ref.get("origin_evidence")
            if not isinstance(origin_raw, Mapping):
                raise _fail("AUTONOMY_STATE_INVALID", "Diagnosis origin evidence is missing")
            origin = OriginEvidenceRef.from_mapping(origin_raw)
            expected_diagnosis_id = diagnosis_id(state.project_id, packet.diagnosis.digest)
            if (
                packet.provider_request_id != request.provider_request_id
                or packet.episode_id != state.episode_id
                or packet.diagnosis.experiment_id != request.experiment_id
                or diagnosis_ref.get("diagnosis_id") != expected_diagnosis_id
                or diagnosis_ref.get("diagnosis_digest") != packet.diagnosis.digest
                or origin.diagnosis_id != expected_diagnosis_id
                or origin.diagnosis_digest != packet.diagnosis.digest
                or class_state_ref.get("class_state_id") != origin.class_state_id
                or class_state_ref.get("class_state_digest") != origin.class_state_digest
            ):
                raise _fail("AUTONOMY_STATE_INVALID", "Diagnosis evidence binding changed")
            state = replace(
                state,
                phase="diagnosis",
                diagnosis_packet=packet,
                diagnosis_ref=diagnosis_ref,
                origin_ref=origin_ref,
                class_state_ref=class_state_ref,
                diagnosis_history=(*state.diagnosis_history, diagnosis_ref),
                origin_history=(*state.origin_history, origin_ref),
                class_state_history=(*state.class_state_history, class_state_ref),
                pending_call_kind=None,
                pending_call_id=None,
                pending_request=None,
            )
        elif event.event_type == SYNTHESIS_LINKED:
            value = _payload(
                event,
                frozenset({"call_id", "synthesis_packet", "claim_ref"}),
                state.episode_id,
            )
            if state.phase != "diagnosis" or state.pending_call_kind != "synthesis" or value["call_id"] != state.pending_call_id:
                raise _fail("AUTONOMY_STATE_INVALID", "synthesis result has no matching call")
            packet = ProviderSynthesisPacket.from_mapping(cast(Mapping[str, Any], value["synthesis_packet"]))
            claim_ref = _frozen_object(value["claim_ref"], field_name="claim ref")
            request = ProviderSynthesisRequest.from_mapping(cast(Mapping[str, Any], state.pending_request))
            evidence = packet.claim.evidence
            if (
                packet.provider_request_id != request.provider_request_id
                or packet.episode_id != state.episode_id
                or state.diagnosis_ref is None
                or state.origin_ref is None
                or state.class_state_ref is None
                or packet.diagnosis_id != state.diagnosis_ref.get("diagnosis_id")
                or packet.diagnosis_digest != state.diagnosis_ref.get("diagnosis_digest")
                or packet.origin_id
                != cast(Mapping[str, Any], state.origin_ref.get("origin_evidence", {})).get("origin_id")
                or packet.origin_digest != state.origin_ref.get("origin_digest")
                or packet.class_state_id != state.class_state_ref.get("class_state_id")
                or packet.class_state_digest != state.class_state_ref.get("class_state_digest")
                or evidence.origin_id != packet.origin_id
                or evidence.diagnosis_id != packet.diagnosis_id
                or evidence.diagnosis_digest != packet.diagnosis_digest
                or claim_ref.get("claim_id") != packet.claim.claim_id
                or claim_ref.get("claim_digest") != packet.claim.digest
            ):
                raise _fail("AUTONOMY_STATE_INVALID", "synthesis evidence binding changed")
            state = replace(
                state,
                phase="synthesis",
                synthesis_packet=packet,
                claim_ref=claim_ref,
                claim_history=(*state.claim_history, claim_ref),
                pending_call_kind=None,
                pending_call_id=None,
                pending_request=None,
            )
        elif event.event_type == NEXT_PLANNED:
            value = _payload(
                event,
                frozenset({"next_query", "context", "project_context_token", "proposal_request"}),
                state.episode_id,
            )
            if state.phase != "synthesis" or state.synthesis_packet is None or state.synthesis_packet.decision != "next":
                raise _fail("AUTONOMY_STATE_INVALID", "next transition has no next synthesis decision")
            query = RetrievalQuery.from_mapping(cast(Mapping[str, Any], value["next_query"]))
            request = ProviderDecisionRequest.from_mapping(cast(Mapping[str, Any], value["proposal_request"]))
            context = _frozen_object(value["context"], field_name="next context")
            if canonical_json_bytes(request.context) != canonical_json_bytes(context):
                raise _fail("AUTONOMY_STATE_INVALID", "next request does not bind next context")
            request_snapshot = ProgramSnapshot.from_mapping(request.program_snapshot)
            if query.program_id != request_snapshot.program_id or query.program_head != request_snapshot.program_head:
                raise _fail("AUTONOMY_STATE_INVALID", "next query does not bind request Program head")
            state = replace(
                state,
                phase="next",
                next_query=query,
                next_context=context,
                next_project_context_token=_digest(value["project_context_token"], path="$.project_context_token"),
                next_proposal_request=request,
                packet=None,
                experiment_result=None,
                terminal_ref=None,
                disposition_ref=None,
                diagnosis_packet=None,
                diagnosis_ref=None,
                origin_ref=None,
                synthesis_packet=None,
                claim_ref=None,
                class_state_ref=None,
            )
        elif event.event_type == PROVIDER_REJECTED:
            value = _payload(
                event,
                frozenset({"call_id", "call_kind", "error_code", "error_details"}),
                state.episode_id,
            )
            kind = _text(value["call_kind"], path="$.call_kind")
            call_id = _identifier(value["call_id"], "providercall", path="$.call_id")
            preflight_rejection = kind == "proposal" and state.phase == "proposal" and state.pending_call_id is None
            if not preflight_rejection and (kind != state.pending_call_kind or call_id != state.pending_call_id):
                raise _fail("AUTONOMY_STATE_INVALID", "provider rejection has no matching call")
            _text(value["error_code"], path="$.error_code")
            _frozen_object(value["error_details"], field_name="provider error details")
            invalid = state.invalid_packets + 1
            if invalid > state.policy.max_invalid_packets:
                raise _fail("AUTONOMY_STATE_INVALID", "invalid packet count exceeded its budget")
            phase = ("next" if state.next_query is not None else "context") if kind == "proposal" else state.phase
            state = replace(
                state,
                phase=phase,
                packet=None if kind == "proposal" else state.packet,
                invalid_packets=invalid,
                pending_call_kind=None,
                pending_call_id=None,
                pending_request=None,
            )
        elif event.event_type == STOPPED:
            value = _payload(
                event,
                frozenset({"stop_reason", "complete", "summary"}),
                state.episode_id,
            )
            if state.pending_call_id is not None:
                raise _fail("AUTONOMY_STATE_INVALID", "cannot stop with a pending provider call")
            complete = value["complete"]
            if not isinstance(complete, bool):
                raise _fail("AUTONOMY_EVENT_INVALID", "stop completion must be boolean")
            reason = _text(value["stop_reason"], path="$.stop_reason")
            summary = _frozen_object(value["summary"], field_name="stop summary")
            if canonical_json_bytes(summary) != canonical_json_bytes(
                _episode_summary(state, reason, complete)
            ):
                raise _fail("AUTONOMY_STATE_INVALID", "stop summary does not match replay")
            state = replace(
                state,
                phase="stop",
                stop_reason=reason,
                complete=complete,
                stop_summary=summary,
            )
        else:  # pragma: no cover - event type set is exhaustive
            raise _fail("AUTONOMY_EVENT_INVALID", "unhandled autonomy event")
        state = _head(state, event)
    if state is None:
        raise _fail("AUTONOMY_STATE_INVALID", "AutonomyLog is empty")
    if state.phase not in _PHASES:  # pragma: no cover - reducer construction invariant
        raise _fail("AUTONOMY_STATE_INVALID", "derived phase is invalid")
    return state


class AutonomyEpisodeLog:
    """One canonical hash-chained file per finite episode."""

    def __init__(self, root: str | os.PathLike[str], project_id: str, episode_id: str):
        try:
            self.episode_id = validate_namespaced_id(episode_id, "episode")
        except (TypeError, ValueError) as exc:
            raise _fail("AUTONOMY_STATE_INVALID", "episode ID is invalid") from exc
        self.root = Path(os.path.abspath(os.fspath(Path(root).expanduser())))
        if self.root.is_symlink():
            raise IntegrityError("autonomy root must not be a symbolic link")
        self.root.mkdir(parents=True, exist_ok=True)
        self.log = EventLog(self.root / f"{self.episode_id}.jsonl", project_id)
        self.project_id = self.log.project_id
        self.log.recover_tail()

    def read(self) -> list[Event]:
        events = self.log.read()
        if events:
            reduce_autonomy_events(events, project_id=self.project_id, episode_id=self.episode_id)
        return events

    def state(self) -> AutonomyEpisodeState:
        return reduce_autonomy_events(
            self.log.read(), project_id=self.project_id, episode_id=self.episode_id
        )

    def append(self, event_type: str, payload: Mapping[str, Any]) -> Event:
        if event_type not in AUTONOMY_EVENT_TYPES:
            raise _fail("AUTONOMY_EVENT_INVALID", "unsupported autonomy event type")
        complete = normalize_json_object({
            "autonomy_event_schema_version": AUTONOMY_EVENT_SCHEMA_VERSION,
            "episode_id": self.episode_id,
            **dict(payload),
            "authorized_action": None,
        }, field_name="autonomy event payload")
        if _non_null_authority(complete):
            raise _fail("AUTONOMY_EVENT_INVALID", "autonomy event authority must be null")
        event_id = new_id("event")

        def validate(events: tuple[Event, ...]) -> None:
            previous = events[-1] if events else None
            prospective = Event(
                1,
                len(events) + 1,
                self.project_id,
                event_id,
                event_type,
                "1970-01-01T00:00:00.000000Z",
                complete,
                None if previous is None else previous.hash,
                "0" * 64,
            )
            reduce_autonomy_events(
                (*events, prospective),
                project_id=self.project_id,
                episode_id=self.episode_id,
            )

        event = self.log.append(
            event_type,
            complete,
            event_id=event_id,
            precondition=validate,
            postcondition=validate,
        )
        self.state()
        return event


def _event_ref(event: Event) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_hash": event.hash,
        "event_sequence": event.sequence,
        "authorized_action": None,
    }


def _program_event_ref(event: ProgramEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "event_hash": event.hash,
        "event_sequence": event.sequence,
        "authorized_action": None,
    }


def verify_autonomy_evidence(
    state: AutonomyEpisodeState,
    *,
    project_log: EventLog,
    program_store: ProgramStore,
) -> dict[str, int]:
    """Reconcile copied episode refs against their canonical truth-owner logs."""

    if project_log.project_id != state.project_id:
        raise _fail("AUTONOMY_EVIDENCE_INVALID", "project evidence identity changed")
    project_events = project_log.read()
    program_events = program_store.log.read()
    project_by_id = {event.event_id: event for event in project_events}
    program_by_id = {event.event_id: event for event in program_events}

    def project_event(ref: Mapping[str, Any], label: str) -> Event:
        event = project_by_id.get(ref.get("event_id"))
        if event is None or (
            ref.get("event_sequence"),
            ref.get("event_hash"),
        ) != (event.sequence, event.hash):
            raise _fail(
                "AUTONOMY_EVIDENCE_INVALID", f"{label} does not match ProjectLog"
            )
        return event

    def program_event(ref: object, label: str) -> ProgramEvent:
        if not isinstance(ref, Mapping):
            raise _fail("AUTONOMY_EVIDENCE_INVALID", f"{label} ProgramLog ref is missing")
        event = program_by_id.get(ref.get("event_id"))
        if event is None or (
            ref.get("event_sequence"),
            ref.get("event_hash"),
        ) != (event.sequence, event.hash):
            raise _fail(
                "AUTONOMY_EVIDENCE_INVALID", f"{label} does not match ProgramLog"
            )
        return event

    try:
        for ref in state.terminal_history:
            event = project_event(ref, "terminal ref")
            if (
                ref.get("event_type") != event.event_type
                or ref.get("experiment_id")
                != event.payload.get("experiment_id", event.payload.get("id"))
            ):
                raise _fail(
                    "AUTONOMY_EVIDENCE_INVALID", "terminal semantic identity changed"
                )
        for ref in state.disposition_history:
            event = program_event(ref.get("program_event"), "disposition ref")
            if (
                event.payload.get("proposal_digest") != ref.get("proposal_digest")
                or event.payload.get("knowledge_disposition_digest")
                != ref.get("knowledge_disposition_digest")
                or cast(Mapping[str, Any], event.payload.get("knowledge_disposition", {})).get(
                    "proposal_id"
                )
                != ref.get("proposal_id")
            ):
                raise _fail(
                    "AUTONOMY_EVIDENCE_INVALID", "disposition semantic identity changed"
                )
        for ref in state.diagnosis_history:
            event = project_event(ref, "Diagnosis ref")
            diagnosis = Diagnosis.from_mapping(
                cast(Mapping[str, Any], event.payload.get("diagnosis", {}))
            )
            if (
                diagnosis.digest != ref.get("diagnosis_digest")
                or diagnosis_id(state.project_id, diagnosis.digest)
                != ref.get("diagnosis_id")
            ):
                raise _fail(
                    "AUTONOMY_EVIDENCE_INVALID", "Diagnosis semantic identity changed"
                )
        for ref in state.origin_history:
            event = program_event(ref.get("program_event"), "origin ref")
            origin = OriginEvidenceRef.from_mapping(
                cast(Mapping[str, Any], event.payload.get("origin_evidence", {}))
            )
            if (
                origin.to_dict() != ref.get("origin_evidence")
                or origin.digest != ref.get("origin_digest")
            ):
                raise _fail(
                    "AUTONOMY_EVIDENCE_INVALID", "origin semantic identity changed"
                )
        for ref in state.claim_history:
            event = program_event(ref.get("program_event"), "Claim ref")
            claim = Claim.from_mapping(cast(Mapping[str, Any], event.payload.get("claim", {})))
            if claim.claim_id != ref.get("claim_id") or claim.digest != ref.get("claim_digest"):
                raise _fail("AUTONOMY_EVIDENCE_INVALID", "Claim semantic identity changed")
        if len(state.class_state_history) != len(state.diagnosis_history):
            raise _fail("AUTONOMY_EVIDENCE_INVALID", "ClassState/Diagnosis history diverged")
        for diagnosis_ref, class_ref in zip(
            state.diagnosis_history, state.class_state_history, strict=True
        ):
            diagnosis_event = project_event(diagnosis_ref, "ClassState Diagnosis ref")
            science = reduce_scientific_state(
                project_events[: diagnosis_event.sequence], project_id=state.project_id
            )
            class_state = next(
                (
                    item
                    for item in science.class_states
                    if item.class_state_id == class_ref.get("class_state_id")
                ),
                None,
            )
            if class_state is None or canonical_json_bytes(
                class_state.to_dict()
            ) != canonical_json_bytes(class_ref):
                raise _fail(
                    "AUTONOMY_EVIDENCE_INVALID", "ClassState does not match ProjectLog prefix"
                )
    except AutonomyLoopError:
        raise
    except Exception as exc:
        raise _fail("AUTONOMY_EVIDENCE_INVALID", "episode evidence is malformed") from exc

    return {
        "terminal_refs": len(state.terminal_history),
        "disposition_refs": len(state.disposition_history),
        "diagnosis_refs": len(state.diagnosis_history),
        "origin_refs": len(state.origin_history),
        "claim_refs": len(state.claim_history),
        "class_state_refs": len(state.class_state_history),
    }


class FiniteAutonomyLoop:
    """Drive one finite episode exclusively through canonical public stores."""

    def __init__(
        self,
        service: ResearchService,
        program_store: ProgramStore,
        provider: ProviderInvoker,
        *,
        autonomy_root: str | os.PathLike[str] | None = None,
    ) -> None:
        if service.config.project_id not in {
            binding.project_id for binding in program_store.snapshot()[0].program_manifest.bindings
        }:
            raise _fail("AUTONOMY_CONFIG_INVALID", "ProgramManifest does not bind the project")
        self.service = service
        self.program_store = program_store
        self.provider = provider
        self.root = Path(autonomy_root or service.config.resolved_runtime_dir / "autonomy")

    def episode(self, episode_id: str) -> AutonomyEpisodeLog:
        return AutonomyEpisodeLog(self.root, self.service.config.project_id, episode_id)

    @staticmethod
    def _project_token(context: Mapping[str, Any]) -> str:
        snapshot = context.get("snapshot")
        project = (
            snapshot.get("project_snapshot", snapshot)
            if isinstance(snapshot, Mapping)
            else None
        )
        if not isinstance(project, Mapping):
            raise _fail("AUTONOMY_CONTEXT_INVALID", "Context v3 project snapshot is missing")
        return _digest(project.get("context_token"), path="$.snapshot.project_snapshot.context_token")

    def _bound_request(
        self, query: RetrievalQuery, *, limit: int
    ) -> tuple[dict[str, Any], str, ProviderDecisionRequest]:
        snapshot, _ = self.program_store.snapshot()
        if query.program_id != snapshot.program_id or query.program_head != snapshot.program_head:
            raise _fail("AUTONOMY_CONTEXT_STALE", "RetrievalQuery does not bind current Program head")
        retrieval = retrieve_claims(self.program_store.claim_snapshot(), query)
        base = self.service.agent_context(limit=limit, schema_version=3)
        project_token = self._project_token(base)
        context = bind_agent_context_v3_retrieval(base, retrieval)
        request = build_provider_decision_request(context=context, program_snapshot=snapshot)
        return context, project_token, request

    def start(
        self,
        initial_query: RetrievalQuery | Mapping[str, Any],
        policy: AutonomyPolicy | Mapping[str, Any],
        *,
        episode_id: str | None = None,
    ) -> AutonomyEpisodeState:
        query = (
            initial_query
            if isinstance(initial_query, RetrievalQuery)
            else RetrievalQuery.from_mapping(initial_query)
        )
        parsed_policy = policy if isinstance(policy, AutonomyPolicy) else AutonomyPolicy.from_mapping(policy)
        resolved_id = episode_id or new_id("episode")
        log = self.episode(resolved_id)
        if log.read():
            raise _fail("AUTONOMY_EPISODE_EXISTS", "episode already exists")
        context, token, request = self._bound_request(query, limit=parsed_policy.context_limit)
        log.append(
            EPISODE_STARTED,
            {
                "policy": parsed_policy.to_dict(),
                "initial_query": query.to_dict(),
                "context": context,
                "project_context_token": token,
                "proposal_request": request.to_dict(),
            },
        )
        return log.state()

    def _science(self) -> Any:
        return reduce_scientific_state(
            self.service.event_log.read(), project_id=self.service.config.project_id
        )

    def _guard(self, state: AutonomyEpisodeState, *, full_cycle: bool) -> str | None:
        science = self._science()
        class_state = next(
            (
                item
                for item in science.class_states
                if item.hypothesis_class_id == state.current_query.hypothesis_class_id
            ),
            None,
        )
        if class_state is not None and class_state.lifecycle == "closed":
            return "closed_class"
        if science.study_stop["stopped"] or science.contract is None:
            return "study_stop"
        calls = 3 if full_cycle else 1
        if full_cycle and state.experiments + 1 > state.policy.max_experiments:
            return "experiment_budget_exhausted"
        if state.provider_calls + calls > state.policy.max_provider_calls:
            return "provider_budget_exhausted"
        if state.invalid_packets and state.invalid_packets >= state.policy.max_invalid_packets:
            return "invalid_packet_budget_exhausted"
        if state.token_units_reserved + calls * state.policy.provider_token_reservation > state.policy.max_token_units:
            return "token_budget_exhausted"
        elapsed = state.elapsed_milliseconds_reserved + calls * state.policy.provider_elapsed_reservation_milliseconds
        if full_cycle:
            elapsed += science.contract.budget.elapsed_reservation_per_attempt_milliseconds
        if elapsed > state.policy.max_elapsed_milliseconds:
            return "time_budget_exhausted"
        return None

    def _stop(
        self, log: AutonomyEpisodeLog, state: AutonomyEpisodeState, reason: str, *, complete: bool
    ) -> AutonomyEpisodeState:
        if state.phase == "stop":
            return state
        verify_autonomy_evidence(
            state,
            project_log=self.service.event_log,
            program_store=self.program_store,
        )
        log.append(
            STOPPED,
            {
                "stop_reason": reason,
                "complete": complete,
                "summary": _episode_summary(state, reason, complete),
            },
        )
        return log.state()

    def _reject(
        self,
        log: AutonomyEpisodeLog,
        *,
        call_id: str,
        kind: str,
        code: str,
        stage: str,
    ) -> AutonomyEpisodeState:
        log.append(
            PROVIDER_REJECTED,
            {
                "call_id": call_id,
                "call_kind": kind,
                "error_code": code,
                "error_details": {"stage": stage, "authorized_action": None},
            },
        )
        return log.state()

    def _invoke(
        self, log: AutonomyEpisodeLog, state: AutonomyEpisodeState, kind: str, request: ProviderRequest
    ) -> tuple[str, Mapping[str, Any]] | None:
        request_dict = cast(Any, request).to_dict()
        if canonical_token_units(request_dict) > state.policy.provider_token_reservation:
            self._stop(
                log,
                state,
                "token_budget_exhausted",
                complete=self._is_complete(state),
            )
            return None
        call_id = new_id("providercall")
        log.append(
            PROVIDER_CALL_STARTED,
            {
                "call_id": call_id,
                "call_kind": kind,
                "request": request_dict,
                "request_digest": sha256_json(request_dict),
                "token_reservation": state.policy.provider_token_reservation,
                "elapsed_reservation_milliseconds": state.policy.provider_elapsed_reservation_milliseconds,
            },
        )
        try:
            raw = self.provider.invoke(request)
            normalized = normalize_json_object(raw, field_name=f"provider {kind} result")
            if canonical_token_units(normalized) > state.policy.provider_token_reservation:
                raise ProviderPortError("PROVIDER_OUTPUT_LIMIT", "provider response exceeded reservation")
            return call_id, normalized
        except ProviderPortError as exc:
            self._reject(log, call_id=call_id, kind=kind, code=exc.code, stage="transport")
            return None
        except Exception:
            self._reject(
                log,
                call_id=call_id,
                kind=kind,
                code="PROVIDER_PROTOCOL_INVALID",
                stage="transport",
            )
            return None

    @staticmethod
    def _is_complete(state: AutonomyEpisodeState) -> bool:
        return len(state.terminal_history) == len(state.claim_history)

    def _proposal_step(
        self, log: AutonomyEpisodeLog, state: AutonomyEpisodeState
    ) -> AutonomyEpisodeState:
        invoked = self._invoke(log, state, "proposal", state.current_proposal_request)
        if invoked is None:
            return log.state()
        call_id, raw = invoked
        try:
            packet = DecisionPacket.from_mapping(raw)
        except DecisionPacketError as exc:
            return self._reject(
                log, call_id=call_id, kind="proposal", code=exc.code, stage="proposal"
            )
        log.append(
            PROPOSAL_RETURNED,
            {"call_id": call_id, "packet": packet.to_dict(), "packet_digest": packet.digest},
        )
        return log.state()

    def _preflight_step(
        self, log: AutonomyEpisodeLog, state: AutonomyEpisodeState
    ) -> AutonomyEpisodeState:
        assert state.packet is not None
        try:
            validate_decision_packet(
                state.packet,
                request=state.current_proposal_request,
                program_store=self.program_store,
                project_log=self.service.event_log,
                current_project_context_token=state.current_project_context_token,
            )
        except DecisionPacketError as exc:
            return self._reject(
                log,
                call_id=new_id("providercall"),
                kind="proposal",
                code=exc.code,
                stage="preflight",
            )
        log.append(
            PREFLIGHT_ACCEPTED,
            {"packet_id": state.packet.packet_id, "packet_digest": state.packet.digest},
        )
        return log.state()

    def _run_step(
        self, log: AutonomyEpisodeLog, state: AutonomyEpisodeState
    ) -> AutonomyEpisodeState:
        assert state.packet is not None
        science = self._science()
        if science.contract is None:
            return self._stop(log, state, "study_stop", complete=True)
        execution_id = new_id("execution")
        log.append(
            EXPERIMENT_STARTED,
            {
                "execution_id": execution_id,
                "packet_id": state.packet.packet_id,
                "elapsed_reservation_milliseconds": (
                    science.contract.budget.elapsed_reservation_per_attempt_milliseconds
                ),
            },
        )
        with tempfile.TemporaryDirectory(
            prefix="research-os-autonomy-", dir=self.service.config.resolved_runtime_dir
        ) as directory:
            candidate_path = Path(directory) / "candidate.json"
            candidate_path.write_bytes(canonical_json_bytes(state.packet.candidate))
            result = self.service.run_once(
                candidate_path,
                context_token=state.current_project_context_token,
                proposal=state.packet.proposal.to_dict(),
            )
        experiment_id = _identifier(result.get("experiment_id"), "experiment", path="$.result.experiment_id")
        sequence = _integer(result.get("event_sequence"), path="$.result.event_sequence", minimum=1)
        terminal = next(
            (
                event
                for event in self.service.event_log.read()
                if event.sequence == sequence
                and event.payload.get("experiment_id", event.payload.get("id")) == experiment_id
            ),
            None,
        )
        if terminal is None:
            raise _fail("AUTONOMY_EXECUTION_INVALID", "ResearchService omitted its terminal event")
        snapshot, _ = self.program_store.snapshot()
        disposition_event = record_agent_context_v3_knowledge_disposition(
            state.current_context,
            current_project_context_token=state.current_project_context_token,
            current_claim_snapshot=self.program_store.claim_snapshot(),
            proposal=state.packet.proposal,
            disposition=state.packet.knowledge_disposition,
            program_store=self.program_store,
            project_log=self.service.event_log,
            expected_program_head=snapshot.program_head,
        )
        terminal_ref = {
            **_event_ref(terminal),
            "event_type": terminal.event_type,
            "experiment_id": experiment_id,
        }
        disposition_ref = {
            "program_event": _program_event_ref(disposition_event),
            "proposal_id": state.packet.knowledge_disposition.proposal_id,
            "proposal_digest": state.packet.proposal.digest,
            "knowledge_disposition_digest": state.packet.knowledge_disposition.digest,
            "authorized_action": None,
        }
        log.append(
            EXPERIMENT_LINKED,
            {
                "execution_id": execution_id,
                "experiment_result": result,
                "terminal_ref": terminal_ref,
                "disposition_ref": disposition_ref,
            },
        )
        return log.state()

    def _diagnosis_step(
        self, log: AutonomyEpisodeLog, state: AutonomyEpisodeState
    ) -> AutonomyEpisodeState:
        assert state.packet is not None and state.terminal_ref is not None
        experiment_id = cast(str, state.terminal_ref["experiment_id"])
        request = ProviderDiagnosisRequest.from_mapping(
            {
                "provider_diagnosis_request_schema_version": 1,
                "provider_request_id": new_id("providerrequest"),
                "episode_id": state.episode_id,
                "experiment_id": experiment_id,
                "decision_packet_id": state.packet.packet_id,
                "proposal": state.packet.proposal.to_dict(),
                "terminal_ref": copy_json_object(state.terminal_ref),
                "diagnosis_template": self.service.diagnosis_template(experiment_id),
                "authorized_action": None,
            }
        )
        invoked = self._invoke(log, state, "diagnosis", request)
        if invoked is None:
            return log.state()
        call_id, raw = invoked
        try:
            packet = ProviderDiagnosisPacket.from_mapping(raw)
            if (
                packet.provider_request_id != request.provider_request_id
                or packet.episode_id != state.episode_id
                or packet.diagnosis.experiment_id != experiment_id
            ):
                raise _fail("AUTONOMY_DIAGNOSIS_INVALID", "Diagnosis packet binding changed")
            diagnosis_result = self.service.record_diagnosis(packet.diagnosis.to_dict())
            snapshot, _ = self.program_store.snapshot()
            origin = next(
                (item for item in snapshot.origins if item.diagnosis_id == diagnosis_result["diagnosis_id"]),
                None,
            )
            if origin is None:
                origin, origin_event = self.program_store.link_origin(
                    self.service.event_log,
                    cast(str, diagnosis_result["diagnosis_id"]),
                    expected_program_head=snapshot.program_head,
                )
            else:
                origin_event = next(
                    event
                    for event in self.program_store.log.read()
                    if cast(Mapping[str, Any], event.payload.get("origin_evidence", {})).get("origin_id")
                    == origin.origin_id
                )
            science = self._science()
            class_state = next(
                item
                for item in science.class_states
                if item.hypothesis_class_id == state.packet.proposal.hypothesis_class_id
            )
        except Exception as exc:
            code = getattr(exc, "code", "AUTONOMY_DIAGNOSIS_INVALID")
            return self._reject(log, call_id=call_id, kind="diagnosis", code=code, stage="diagnosis")
        diagnosis_ref = {
            "event_id": diagnosis_result["event_id"],
            "event_hash": diagnosis_result["event_hash"],
            "event_sequence": diagnosis_result["event_sequence"],
            "diagnosis_id": diagnosis_result["diagnosis_id"],
            "diagnosis_digest": diagnosis_result["diagnosis_digest"],
            "authorized_action": None,
        }
        origin_ref = {
            "origin_evidence": origin.to_dict(),
            "origin_digest": origin.digest,
            "program_event": _program_event_ref(origin_event),
            "authorized_action": None,
        }
        log.append(
            DIAGNOSIS_LINKED,
            {
                "call_id": call_id,
                "diagnosis_packet": packet.to_dict(),
                "diagnosis_ref": diagnosis_ref,
                "origin_ref": origin_ref,
                "class_state_ref": class_state.to_dict(),
            },
        )
        return log.state()

    def _synthesis_step(
        self, log: AutonomyEpisodeLog, state: AutonomyEpisodeState
    ) -> AutonomyEpisodeState:
        assert (
            state.packet is not None
            and state.diagnosis_packet is not None
            and state.diagnosis_ref is not None
            and state.origin_ref is not None
            and state.class_state_ref is not None
            and state.terminal_ref is not None
        )
        snapshot, _ = self.program_store.snapshot()
        request = ProviderSynthesisRequest.from_mapping(
            {
                "provider_synthesis_request_schema_version": 1,
                "provider_request_id": new_id("providerrequest"),
                "episode_id": state.episode_id,
                "experiment_id": state.terminal_ref["experiment_id"],
                "diagnosis": state.diagnosis_packet.diagnosis.to_dict(),
                "origin_evidence": state.origin_ref["origin_evidence"],
                "class_state": state.class_state_ref,
                "program_snapshot": snapshot.to_dict(),
                "decision_packet": state.packet.to_dict(),
                "authorized_action": None,
            }
        )
        invoked = self._invoke(log, state, "synthesis", request)
        if invoked is None:
            return log.state()
        call_id, raw = invoked
        try:
            packet = ProviderSynthesisPacket.from_mapping(raw)
            expected = (
                request.provider_request_id,
                state.episode_id,
                state.diagnosis_ref["diagnosis_id"],
                state.diagnosis_ref["diagnosis_digest"],
                cast(Mapping[str, Any], state.origin_ref["origin_evidence"])["origin_id"],
                state.origin_ref["origin_digest"],
                state.class_state_ref["class_state_id"],
                state.class_state_ref["class_state_digest"],
            )
            observed = (
                packet.provider_request_id,
                packet.episode_id,
                packet.diagnosis_id,
                packet.diagnosis_digest,
                packet.origin_id,
                packet.origin_digest,
                packet.class_state_id,
                packet.class_state_digest,
            )
            if observed != expected:
                raise _fail("AUTONOMY_SYNTHESIS_INVALID", "synthesis evidence binding changed")
            claim_event = self.program_store.append_claim(
                packet.claim,
                self.service.event_log,
                expected_program_head=snapshot.program_head,
            )
        except Exception:
            return self._reject(
                log,
                call_id=call_id,
                kind="synthesis",
                code="AUTONOMY_SYNTHESIS_INVALID",
                stage="synthesis",
            )
        claim_ref = {
            "claim_id": packet.claim.claim_id,
            "claim_digest": packet.claim.digest,
            "program_event": _program_event_ref(claim_event),
            "authorized_action": None,
        }
        log.append(
            SYNTHESIS_LINKED,
            {"call_id": call_id, "synthesis_packet": packet.to_dict(), "claim_ref": claim_ref},
        )
        return log.state()

    def _next_step(
        self, log: AutonomyEpisodeLog, state: AutonomyEpisodeState
    ) -> AutonomyEpisodeState:
        assert state.synthesis_packet is not None
        packet = state.synthesis_packet
        if packet.decision == "stop":
            assert packet.stop_reason is not None
            return self._stop(log, state, packet.stop_reason, complete=True)
        assert packet.next_query_plan is not None
        snapshot, _ = self.program_store.snapshot()
        query = packet.next_query_plan.bind(snapshot)
        context, token, request = self._bound_request(query, limit=state.policy.context_limit)
        log.append(
            NEXT_PLANNED,
            {
                "next_query": query.to_dict(),
                "context": context,
                "project_context_token": token,
                "proposal_request": request.to_dict(),
            },
        )
        return log.state()

    def advance(
        self, episode_id: str, *, expected_phase: str | None = None
    ) -> AutonomyEpisodeState:
        """Commit at most one nominal FSM transition; stale retries are no-ops."""

        log = self.episode(episode_id)
        state = log.state()
        if expected_phase is not None and state.phase != expected_phase:
            return state
        if state.phase == "stop":
            return state
        if state.pending_call_id is not None or state.experiment_started:
            raise _fail(
                "AUTONOMY_INCOMPLETE_STEP",
                "incomplete-step recovery belongs to M3-C",
                phase=state.phase,
            )
        if state.phase in {"context", "next"}:
            reason = self._guard(state, full_cycle=True)
            return (
                self._stop(log, state, reason, complete=self._is_complete(state))
                if reason is not None
                else self._proposal_step(log, state)
            )
        if state.phase == "proposal":
            return self._preflight_step(log, state)
        if state.phase == "preflight":
            return self._run_step(log, state)
        if state.phase == "run":
            reason = self._guard(state, full_cycle=False)
            return (
                self._stop(log, state, reason, complete=False)
                if reason is not None
                else self._diagnosis_step(log, state)
            )
        if state.phase == "diagnosis":
            reason = self._guard(state, full_cycle=False)
            return (
                self._stop(log, state, reason, complete=False)
                if reason is not None
                else self._synthesis_step(log, state)
            )
        if state.phase == "synthesis":
            return self._next_step(log, state)
        raise _fail("AUTONOMY_STATE_INVALID", "episode phase cannot advance")

    def run(self, episode_id: str) -> AutonomyEpisodeState:
        """Run until one canonical stop; all loop bounds come from AutonomyPolicy."""

        while True:
            state = self.episode(episode_id).state()
            if state.phase == "stop":
                return state
            self.advance(episode_id, expected_phase=state.phase)
