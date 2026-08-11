"""DecisionPacket v1 and its current-state, no-write validation boundary."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar, cast

from research_os.agent import validate_agent_context_v3_retrieval
from research_os.contracts.common import (
    FrozenJSONObject,
    canonical_json_bytes,
    copy_json_object,
    freeze_json_object,
    normalize_json_object,
    sha256_json,
)
from research_os.errors import (
    ConfigurationError,
    ProgramMemoryError,
    ScientificStateError,
    StaleAgentContextError,
)
from research_os.kernel.events import EventLog
from research_os.kernel.ids import new_id, stable_id, validate_namespaced_id
from research_os.memory import (
    ProgramSnapshot,
    ProgramStore,
    ProposalKnowledgeDisposition,
    RetrievalResult,
    validate_proposal_knowledge_disposition,
)
from research_os.science import Proposal, reduce_scientific_state, validate_registration_preflight

PROVIDER_DECISION_REQUEST_SCHEMA_VERSION = 1
DECISION_PACKET_SCHEMA_VERSION = 1
MAX_DECISION_PACKET_BYTES = 2 * 1024 * 1024

_DIGEST_LENGTH = 64
_REQUEST_KEYS = frozenset(
    {
        "provider_decision_request_schema_version",
        "provider_request_id",
        "context",
        "program_snapshot",
        "authorized_action",
    }
)
_PACKET_KEYS = frozenset(
    {
        "decision_packet_schema_version",
        "packet_id",
        "provider_request_id",
        "project_id",
        "context_token",
        "program_snapshot",
        "program_snapshot_digest",
        "retrieval_manifest",
        "candidate",
        "proposal",
        "knowledge_disposition",
        "authorized_action",
    }
)
_RETRIEVAL_KEYS = frozenset(
    {"query_digest", "retrieval_result_digest", "returned_claims", "authorized_action"}
)
_RETURNED_CLAIM_KEYS = frozenset(
    {
        "claim_id",
        "claim_digest",
        "retrieval_role",
        "relation_ids",
        "reasons",
        "authorized_action",
    }
)


class DecisionPacketError(ConfigurationError):
    """Stable invalid/stale classification at the untrusted packet boundary."""

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


def _invalid(message: str, *, path: str | None = None) -> DecisionPacketError:
    details: dict[str, object] = {}
    if path is not None:
        details["path"] = path
    return DecisionPacketError("DECISION_PACKET_INVALID", message, details=details)


def _stale(message: str) -> DecisionPacketError:
    return DecisionPacketError("DECISION_PACKET_STALE", message)


def _assert_value_only(value: object, *, path: str = "$", active: set[int] | None = None) -> None:
    """Reject live Python capabilities before JSON normalization can stringify them."""

    if value is None or isinstance(value, (bool, int, float, str)):
        return
    if callable(value):
        raise _invalid("callable values are not permitted", path=path)
    if active is None:
        active = set()
    identity = id(value)
    if identity in active:
        raise _invalid("cyclic values are not permitted", path=path)
    if isinstance(value, Mapping):
        active.add(identity)
        try:
            for key, item in value.items():
                if not isinstance(key, str):
                    raise _invalid("object keys must be strings", path=path)
                _assert_value_only(item, path=f"{path}.{key}", active=active)
        finally:
            active.remove(identity)
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        active.add(identity)
        try:
            for index, item in enumerate(value):
                _assert_value_only(item, path=f"{path}[{index}]", active=active)
        finally:
            active.remove(identity)
        return
    raise _invalid(f"live {type(value).__name__} values are not permitted", path=path)


def _object(
    value: object,
    keys: frozenset[str],
    *,
    path: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _invalid("value must be an object", path=path)
    actual = set(value)
    if actual != set(keys):
        raise _invalid(
            f"object must have exact keys; missing={sorted(set(keys) - actual)!r}, "
            f"unknown={sorted(actual - set(keys))!r}",
            path=path,
        )
    return value


def _array(value: object, *, path: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray, memoryview)):
        raise _invalid("value must be an array", path=path)
    return value


def _text(value: object, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise _invalid("value must be non-empty trimmed text", path=path)
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise _invalid("text must contain Unicode scalar values", path=path)
    return value


def _version(value: object, expected: int, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise _invalid(f"value must equal literal integer {expected}", path=path)
    return expected


def _digest(value: object, *, path: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _DIGEST_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _invalid("value must be a lowercase SHA-256 digest", path=path)
    return value


def _identifier(value: object, namespace: str, *, path: str) -> str:
    text = _text(value, path=path)
    try:
        return validate_namespaced_id(text, namespace)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"value must be a {namespace} ID", path=path) from exc


def _non_null_authority(value: object) -> int:
    if isinstance(value, Mapping):
        return int("authorized_action" in value and value["authorized_action"] is not None) + sum(
            _non_null_authority(item) for item in value.values()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        return sum(_non_null_authority(item) for item in value)
    return 0


def _normalized_value_object(value: object, *, name: str) -> dict[str, Any]:
    _assert_value_only(value, path=f"$.{name}")
    try:
        result = normalize_json_object(value, field_name=name)
    except (TypeError, ValueError) as exc:
        raise _invalid(f"{name} is not canonical JSON: {exc}", path=f"$.{name}") from exc
    if _non_null_authority(result):
        raise _invalid("authorized_action must be literal null recursively", path=f"$.{name}")
    return result


def _context_token(context: Mapping[str, Any]) -> str:
    snapshot = context.get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise _invalid("Context v3 snapshot is missing", path="$.context.snapshot")
    return _digest(snapshot.get("context_token"), path="$.context.snapshot.context_token")


def _context_project_id(context: Mapping[str, Any]) -> str:
    snapshot = context.get("snapshot")
    project = snapshot.get("project_snapshot") if isinstance(snapshot, Mapping) else None
    if not isinstance(project, Mapping):
        raise _invalid("Context v3 project snapshot is missing", path="$.context.snapshot")
    return _text(project.get("project_id"), path="$.context.snapshot.project_snapshot.project_id")


@dataclass(frozen=True, slots=True)
class ProviderDecisionRequest:
    provider_decision_request_schema_version: int
    provider_request_id: str
    context: FrozenJSONObject
    program_snapshot: FrozenJSONObject
    authorized_action: None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProviderDecisionRequest:
        normalized = _normalized_value_object(raw, name="provider_request")
        root = _object(normalized, _REQUEST_KEYS, path="$")
        if root["authorized_action"] is not None:
            raise _invalid("authorized_action must be literal null", path="$.authorized_action")
        try:
            snapshot = ProgramSnapshot.from_mapping(
                cast(Mapping[str, Any], root["program_snapshot"])
            )
        except (ProgramMemoryError, TypeError, ValueError) as exc:
            raise _invalid("provider request ProgramSnapshot is invalid") from exc
        context = cast(Mapping[str, Any], root["context"])
        if not isinstance(context, Mapping):
            raise _invalid("context must be an object", path="$.context")
        return cls(
            _version(
                root["provider_decision_request_schema_version"],
                PROVIDER_DECISION_REQUEST_SCHEMA_VERSION,
                path="$.provider_decision_request_schema_version",
            ),
            _identifier(
                root["provider_request_id"], "providerrequest", path="$.provider_request_id"
            ),
            freeze_json_object(context, field_name="context"),
            freeze_json_object(snapshot.to_dict(), field_name="program_snapshot"),
        )

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_decision_request_schema_version": self.provider_decision_request_schema_version,
            "provider_request_id": self.provider_request_id,
            "context": copy_json_object(self.context),
            "program_snapshot": copy_json_object(self.program_snapshot),
            "authorized_action": None,
        }

    def frozen_mapping(self) -> FrozenJSONObject:
        return freeze_json_object(self.to_dict(), field_name="provider_request")


def build_provider_decision_request(
    *,
    context: Mapping[str, Any],
    program_snapshot: ProgramSnapshot | Mapping[str, Any],
    provider_request_id: str | None = None,
) -> ProviderDecisionRequest:
    snapshot = (
        program_snapshot.to_dict()
        if isinstance(program_snapshot, ProgramSnapshot)
        else program_snapshot
    )
    return ProviderDecisionRequest.from_mapping(
        {
            "provider_decision_request_schema_version": (PROVIDER_DECISION_REQUEST_SCHEMA_VERSION),
            "provider_request_id": provider_request_id or new_id("providerrequest"),
            "context": context,
            "program_snapshot": snapshot,
            "authorized_action": None,
        }
    )


@dataclass(frozen=True, slots=True)
class RetrievalManifest:
    query_digest: str
    retrieval_result_digest: str
    returned_claims: tuple[FrozenJSONObject, ...]
    authorized_action: None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> RetrievalManifest:
        root = _object(raw, _RETRIEVAL_KEYS, path="$.retrieval_manifest")
        if root["authorized_action"] is not None:
            raise _invalid(
                "authorized_action must be literal null",
                path="$.retrieval_manifest.authorized_action",
            )
        claims: list[FrozenJSONObject] = []
        for index, item in enumerate(
            _array(root["returned_claims"], path="$.retrieval_manifest.returned_claims")
        ):
            path = f"$.retrieval_manifest.returned_claims[{index}]"
            claim = _object(item, _RETURNED_CLAIM_KEYS, path=path)
            role = _text(claim["retrieval_role"], path=f"{path}.retrieval_role")
            if role not in {"active", "contradiction"}:
                raise _invalid("unsupported retrieval role", path=f"{path}.retrieval_role")
            relation_ids = tuple(
                _identifier(value, "relation", path=f"{path}.relation_ids[]")
                for value in _array(claim["relation_ids"], path=f"{path}.relation_ids")
            )
            reasons = tuple(
                _text(value, path=f"{path}.reasons[]")
                for value in _array(claim["reasons"], path=f"{path}.reasons")
            )
            if relation_ids != tuple(sorted(set(relation_ids))):
                raise _invalid("relation IDs must be sorted and unique", path=path)
            if claim["authorized_action"] is not None:
                raise _invalid("authorized_action must be literal null", path=path)
            parsed = {
                "claim_id": _identifier(claim["claim_id"], "claim", path=f"{path}.claim_id"),
                "claim_digest": _digest(claim["claim_digest"], path=f"{path}.claim_digest"),
                "retrieval_role": role,
                "relation_ids": list(relation_ids),
                "reasons": list(reasons),
                "authorized_action": None,
            }
            claims.append(freeze_json_object(parsed, field_name="returned_claim"))
        claim_ids = tuple(cast(str, item["claim_id"]) for item in claims)
        if claim_ids != tuple(sorted(set(claim_ids))):
            raise _invalid("returned Claims must be claim-sorted and unique")
        return cls(
            _digest(root["query_digest"], path="$.retrieval_manifest.query_digest"),
            _digest(
                root["retrieval_result_digest"],
                path="$.retrieval_manifest.retrieval_result_digest",
            ),
            tuple(claims),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "query_digest": self.query_digest,
            "retrieval_result_digest": self.retrieval_result_digest,
            "returned_claims": [copy_json_object(item) for item in self.returned_claims],
            "authorized_action": None,
        }


def build_retrieval_manifest(retrieval: RetrievalResult) -> RetrievalManifest:
    if not isinstance(retrieval, RetrievalResult):
        raise TypeError("retrieval must be a RetrievalResult")
    claims = [
        {
            "claim_id": hit.claim_id,
            "claim_digest": hit.view.claim_digest,
            "retrieval_role": hit.relation_role,
            "relation_ids": list(hit.relation_ids),
            "reasons": list(hit.reasons),
            "authorized_action": None,
        }
        for hit in (*retrieval.active, *retrieval.contradictions)
    ]
    claims.sort(key=lambda item: cast(str, item["claim_id"]))
    return RetrievalManifest.from_mapping(
        {
            "query_digest": retrieval.query.digest,
            "retrieval_result_digest": retrieval.digest,
            "returned_claims": claims,
            "authorized_action": None,
        }
    )


@dataclass(frozen=True, slots=True)
class DecisionPacket:
    decision_packet_schema_version: int
    packet_id: str
    provider_request_id: str
    project_id: str
    context_token: str
    program_snapshot: ProgramSnapshot
    program_snapshot_digest: str
    retrieval_manifest: RetrievalManifest
    candidate: FrozenJSONObject
    proposal: Proposal
    knowledge_disposition: ProposalKnowledgeDisposition
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = _PACKET_KEYS

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> DecisionPacket:
        normalized = _normalized_value_object(raw, name="decision_packet")
        if len(canonical_json_bytes(normalized)) > MAX_DECISION_PACKET_BYTES:
            raise _invalid("DecisionPacket exceeds the 2 MiB canonical size limit")
        root = _object(normalized, cls._KEYS, path="$")
        if root["authorized_action"] is not None:
            raise _invalid("authorized_action must be literal null", path="$.authorized_action")
        try:
            snapshot = ProgramSnapshot.from_mapping(
                cast(Mapping[str, Any], root["program_snapshot"])
            )
            proposal = Proposal.from_mapping(cast(Mapping[str, Any], root["proposal"]))
            disposition = ProposalKnowledgeDisposition.from_mapping(
                cast(Mapping[str, Any], root["knowledge_disposition"])
            )
        except (ProgramMemoryError, ScientificStateError, TypeError, ValueError) as exc:
            raise _invalid("typed DecisionPacket member is invalid") from exc
        snapshot_digest = _digest(root["program_snapshot_digest"], path="$.program_snapshot_digest")
        if snapshot_digest != sha256_json(snapshot.to_dict()):
            raise _invalid("ProgramSnapshot digest does not match its body")
        manifest_raw = root["retrieval_manifest"]
        if not isinstance(manifest_raw, Mapping):
            raise _invalid("retrieval_manifest must be an object")
        candidate_raw = root["candidate"]
        if not isinstance(candidate_raw, Mapping):
            raise _invalid("candidate must be an object", path="$.candidate")
        packet = cls(
            _version(
                root["decision_packet_schema_version"],
                DECISION_PACKET_SCHEMA_VERSION,
                path="$.decision_packet_schema_version",
            ),
            _identifier(root["packet_id"], "decisionpacket", path="$.packet_id"),
            _identifier(
                root["provider_request_id"], "providerrequest", path="$.provider_request_id"
            ),
            _text(root["project_id"], path="$.project_id"),
            _digest(root["context_token"], path="$.context_token"),
            snapshot,
            snapshot_digest,
            RetrievalManifest.from_mapping(manifest_raw),
            freeze_json_object(candidate_raw, field_name="candidate"),
            proposal,
            disposition,
        )
        if packet.packet_id != packet.expected_id:
            raise _invalid("packet_id does not match the canonical packet body")
        return packet

    def _identity_dict(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("packet_id")
        return value

    @property
    def expected_id(self) -> str:
        return stable_id("decisionpacket", self._identity_dict())

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_packet_schema_version": self.decision_packet_schema_version,
            "packet_id": self.packet_id,
            "provider_request_id": self.provider_request_id,
            "project_id": self.project_id,
            "context_token": self.context_token,
            "program_snapshot": self.program_snapshot.to_dict(),
            "program_snapshot_digest": self.program_snapshot_digest,
            "retrieval_manifest": self.retrieval_manifest.to_dict(),
            "candidate": copy_json_object(self.candidate),
            "proposal": self.proposal.to_dict(),
            "knowledge_disposition": self.knowledge_disposition.to_dict(),
            "authorized_action": None,
        }


def build_decision_packet(
    *,
    request: ProviderDecisionRequest,
    project_id: str,
    candidate: Mapping[str, Any],
    proposal: Proposal,
    knowledge_disposition: ProposalKnowledgeDisposition,
    retrieval: RetrievalResult,
) -> DecisionPacket:
    if not isinstance(request, ProviderDecisionRequest):
        raise TypeError("request must be a ProviderDecisionRequest")
    snapshot = ProgramSnapshot.from_mapping(request.program_snapshot)
    raw: dict[str, Any] = {
        "decision_packet_schema_version": DECISION_PACKET_SCHEMA_VERSION,
        "packet_id": "decisionpacket_placeholder",
        "provider_request_id": request.provider_request_id,
        "project_id": project_id,
        "context_token": _context_token(request.context),
        "program_snapshot": snapshot.to_dict(),
        "program_snapshot_digest": sha256_json(snapshot.to_dict()),
        "retrieval_manifest": build_retrieval_manifest(retrieval).to_dict(),
        "candidate": candidate,
        "proposal": proposal.to_dict(),
        "knowledge_disposition": knowledge_disposition.to_dict(),
        "authorized_action": None,
    }
    identity = dict(raw)
    identity.pop("packet_id")
    raw["packet_id"] = stable_id("decisionpacket", identity)
    return DecisionPacket.from_mapping(raw)


def _validate_current_proposal(
    *,
    packet: DecisionPacket,
    state: Any,
) -> None:
    proposal = packet.proposal
    if state.active_generation_id != proposal.generation_id or state.contract is None:
        raise _invalid("Proposal generation is not the active generation")
    declared_classes = {item.id for item in state.contract.hypothesis_classes}
    if proposal.hypothesis_class_id not in declared_classes:
        raise _invalid("Proposal hypothesis class is not declared by the active contract")
    try:
        validate_registration_preflight(
            state,
            {
                "retry_of": None,
                "proposal": proposal.to_dict(),
                "parent_id": proposal.parent_experiment_id,
            },
        )
    except ScientificStateError as exc:
        raise _invalid("Proposal fails current registration preflight") from exc
    scope = next(
        (
            item
            for item in state.contract.evaluation_scopes
            if item.id == proposal.evaluation_scope_id
        ),
        None,
    )
    if scope is None:
        raise _invalid("Proposal evaluation scope is not declared by the active contract")
    iterative = proposal.action in {"explore", "exploit", "ablate"}
    if (iterative and scope.role not in {"development", "diagnostic"}) or (
        proposal.action == "replicate" and scope.role != "replication"
    ):
        raise _invalid("Proposal action does not match the evaluation-scope role")
    surface = state.contract.intervention_surface
    pointers = proposal.intervention_json_pointers
    if proposal.action == "replicate":
        if pointers:
            raise _invalid("replication Proposal must not declare intervention pointers")
    elif (
        not pointers
        or len(pointers) > surface.max_changes
        or not set(pointers).issubset(surface.allowed_json_pointers)
    ):
        raise _invalid("Proposal intervention escapes the active contract")


def _validate_program_binding(
    *,
    packet: DecisionPacket,
    state: Any,
    project_id: str,
) -> None:
    proposal = packet.proposal
    manifest = packet.program_snapshot.program_manifest
    binding = manifest.binding(project_id, proposal.generation_id, proposal.evaluation_scope_id)
    if binding is None or state.contract is None or state.evaluation_seal is None:
        raise _invalid("ProgramManifest has no current Proposal binding")
    scope = next(
        (
            item
            for item in state.contract.evaluation_scopes
            if item.id == proposal.evaluation_scope_id
        ),
        None,
    )
    expected = (
        state.contract.digest,
        state.active_generation_id,
        None if scope is None else scope.role,
        None if scope is None else scope.manifest_digest,
        state.evaluation_seal.digest,
        state.evaluation_seal.compatibility_digest,
    )
    observed = (
        binding.study_contract_digest,
        binding.generation_id,
        binding.evaluation_scope_role,
        binding.evaluation_scope_manifest_digest,
        binding.evaluation_seal_digest,
        binding.compatibility_digest,
    )
    if observed != expected:
        raise _invalid("ProgramManifest Proposal binding is not current")


@dataclass(frozen=True, slots=True)
class ValidatedDecision:
    packet: DecisionPacket
    retrieval: RetrievalResult
    authorized_action: None = None


def validate_decision_packet(
    packet: DecisionPacket | Mapping[str, Any],
    *,
    request: ProviderDecisionRequest | Mapping[str, Any],
    program_store: ProgramStore,
    project_log: EventLog,
    current_project_context_token: str,
) -> ValidatedDecision:
    """Validate against canonical stores without appending or executing anything."""

    try:
        parsed_request = (
            request
            if isinstance(request, ProviderDecisionRequest)
            else ProviderDecisionRequest.from_mapping(request)
        )
        parsed_request = ProviderDecisionRequest.from_mapping(parsed_request.to_dict())
        parsed_packet = (
            packet if isinstance(packet, DecisionPacket) else DecisionPacket.from_mapping(packet)
        )
        parsed_packet = DecisionPacket.from_mapping(parsed_packet.to_dict())
    except DecisionPacketError:
        raise
    except (ProgramMemoryError, ScientificStateError, TypeError, ValueError) as exc:
        raise _invalid("DecisionPacket or provider request is malformed") from exc

    request_context = copy_json_object(parsed_request.context)
    request_snapshot = copy_json_object(parsed_request.program_snapshot)
    request_token = _context_token(request_context)
    request_project_id = _context_project_id(request_context)
    if parsed_packet.provider_request_id != parsed_request.provider_request_id:
        raise _invalid("provider_request_id does not match the outbound request")
    if parsed_packet.context_token != request_token:
        raise _stale("DecisionPacket context token is stale")
    if (
        parsed_packet.project_id != request_project_id
        or project_log.project_id != request_project_id
    ):
        raise _invalid("DecisionPacket project identity is inconsistent")
    if canonical_json_bytes(parsed_packet.program_snapshot.to_dict()) != canonical_json_bytes(
        request_snapshot
    ):
        raise _invalid("provider changed the trusted outbound ProgramSnapshot")

    current_snapshot, _ = program_store.snapshot()
    if canonical_json_bytes(current_snapshot.to_dict()) != canonical_json_bytes(request_snapshot):
        raise _stale("ProgramSnapshot advanced after the provider request")
    try:
        retrieval = validate_agent_context_v3_retrieval(
            request_context,
            current_project_context_token=current_project_context_token,
            current_claim_snapshot=program_store.claim_snapshot(),
        )
    except StaleAgentContextError as exc:
        raise _stale("Context v3 read set is no longer current") from exc

    project_events = project_log.read()
    project_head = (
        (project_events[-1].sequence, project_events[-1].hash) if project_events else (0, None)
    )
    state = reduce_scientific_state(project_events, project_id=project_log.project_id)
    science = request_context.get("science")
    if not isinstance(science, Mapping) or canonical_json_bytes(science) != canonical_json_bytes(
        state.to_dict()
    ):
        raise _stale("Context v3 scientific state is no longer current")
    expected_manifest = build_retrieval_manifest(retrieval)
    if canonical_json_bytes(parsed_packet.retrieval_manifest.to_dict()) != canonical_json_bytes(
        expected_manifest.to_dict()
    ):
        raise _invalid("retrieval manifest does not match current canonical retrieval")
    if parsed_packet.proposal.candidate_digest != sha256_json(parsed_packet.candidate):
        raise _invalid("candidate does not match the Proposal candidate digest")
    if (
        retrieval.query.hypothesis_class_id != parsed_packet.proposal.hypothesis_class_id
        or retrieval.query.evaluation_scope.evaluation_scope_id
        != parsed_packet.proposal.evaluation_scope_id
    ):
        raise _invalid("Proposal class or scope does not match the retrieval query")
    _validate_current_proposal(packet=parsed_packet, state=state)
    _validate_program_binding(
        packet=parsed_packet,
        state=state,
        project_id=request_project_id,
    )
    try:
        validate_proposal_knowledge_disposition(
            parsed_packet.knowledge_disposition,
            project_id=request_project_id,
            proposal=parsed_packet.proposal,
            retrieval=retrieval,
            context_token=request_token,
        )
    except ProgramMemoryError as exc:
        raise _invalid("knowledge disposition does not match the current read set") from exc
    final_snapshot, _ = program_store.snapshot()
    if canonical_json_bytes(final_snapshot.to_dict()) != canonical_json_bytes(request_snapshot):
        raise _stale("ProgramSnapshot advanced during DecisionPacket validation")
    final_project_events = project_log.read()
    final_project_head = (
        (final_project_events[-1].sequence, final_project_events[-1].hash)
        if final_project_events
        else (0, None)
    )
    if final_project_head != project_head:
        raise _stale("project state advanced during DecisionPacket validation")
    return ValidatedDecision(parsed_packet, retrieval)
