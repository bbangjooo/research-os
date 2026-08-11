"""Durable Proposal knowledge disposition and opaque legacy records."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, cast

from research_os.contracts.common import sha256_json
from research_os.errors import ProgramMemoryError
from research_os.kernel.ids import stable_id, validate_namespaced_id
from research_os.science.proposals import Proposal, proposal_id

from .retrieval import RetrievalResult

KNOWLEDGE_DISPOSITION_SCHEMA_VERSION = 1
LEGACY_OPAQUE_SCHEMA_VERSION = 1
KNOWLEDGE_DISPOSITIONS = frozenset({"used", "rejected", "not_applicable"})
NOT_APPLICABLE_REASON_CODES = frozenset(
    {
        "evidence_not_applicable",
        "mechanism_not_applicable",
        "scope_not_applicable",
    }
)
PROPOSAL_FIELD_REFS = frozenset(
    {
        "action",
        "evaluation_scope_id",
        "falsifier",
        "hypothesis_class_id",
        "intervention_json_pointers",
        "mechanism",
        "predicted_effect",
    }
)
LEGACY_SOURCE_KINDS = frozenset({"branch_conclusion", "event", "file", "finding", "note"})
MAX_DISPOSITION_RATIONALE_UTF8_BYTES = 4096
MAX_LEGACY_SOURCE_LOCATOR_UTF8_BYTES = 4096
MAX_LEGACY_CONTENT_BYTES = 1_048_576

_HASH_LENGTH = 64


def _error(code: str, message: str, *, path: str | None = None) -> ProgramMemoryError:
    details = {} if path is None else {"path": path}
    return ProgramMemoryError(code, message, details=details)


def _object(
    value: Any, keys: set[str] | frozenset[str], *, path: str, code: str
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _error(code, f"{path} must be an object", path=path)
    actual = set(value)
    if actual != set(keys):
        raise _error(code, f"{path} must have exact keys", path=path)
    return value


def _array(value: Any, *, path: str, code: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray, memoryview)):
        raise _error(code, f"{path} must be an array", path=path)
    return value


def _text(value: Any, *, path: str, code: str, maximum: int | None = None) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise _error(code, f"{path} must be non-empty trimmed text", path=path)
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise _error(code, f"{path} must contain Unicode scalar values", path=path)
    if maximum is not None and len(value.encode("utf-8")) > maximum:
        raise _error(code, f"{path} exceeds its UTF-8 byte limit", path=path)
    return value


def _digest(value: Any, *, path: str, code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _HASH_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _error(code, f"{path} must be a lowercase SHA-256 digest", path=path)
    return value


def _identifier(value: Any, namespace: str, *, path: str, code: str) -> str:
    text = _text(value, path=path, code=code)
    try:
        return validate_namespaced_id(text, namespace)
    except (TypeError, ValueError) as exc:
        raise _error(code, f"{path} must be a {namespace} ID", path=path) from exc


def _literal_version(value: Any, expected: int, *, path: str, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise _error(code, f"{path} must equal literal integer {expected}", path=path)
    return expected


def _positive_integer(value: Any, *, path: str, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _error(code, f"{path} must be a positive integer", path=path)
    return value


def _sorted_unique_text(
    value: Any,
    *,
    path: str,
    code: str,
    allowed: frozenset[str] | None = None,
    nonempty: bool,
) -> tuple[str, ...]:
    result = tuple(
        _text(item, path=f"{path}[]", code=code) for item in _array(value, path=path, code=code)
    )
    if (nonempty and not result) or result != tuple(sorted(set(result))):
        raise _error(code, f"{path} must be sorted and unique", path=path)
    if allowed is not None and any(item not in allowed for item in result):
        raise _error(code, f"{path} contains an unsupported value", path=path)
    return result


@dataclass(frozen=True, slots=True)
class KnowledgeDispositionEntry:
    claim_id: str
    claim_digest: str
    retrieval_role: Literal["active", "contradiction"]
    relation_ids: tuple[str, ...]
    disposition: Literal["used", "rejected", "not_applicable"]
    proposal_field_refs: tuple[str, ...]
    reason_code: str | None
    rationale: str
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "claim_id",
            "claim_digest",
            "retrieval_role",
            "relation_ids",
            "disposition",
            "proposal_field_refs",
            "reason_code",
            "rationale",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> KnowledgeDispositionEntry:
        code = "KNOWLEDGE_DISPOSITION_INVALID"
        value = _object(raw, cls._KEYS, path="$.entries[]", code=code)
        role = _text(value["retrieval_role"], path="$.entries[].retrieval_role", code=code)
        if role not in {"active", "contradiction"}:
            raise _error(code, "unsupported retrieval role", path="$.entries[].retrieval_role")
        disposition = _text(value["disposition"], path="$.entries[].disposition", code=code)
        if disposition not in KNOWLEDGE_DISPOSITIONS:
            raise _error(code, "unsupported disposition", path="$.entries[].disposition")
        relation_ids = _sorted_unique_text(
            value["relation_ids"],
            path="$.entries[].relation_ids",
            code=code,
            nonempty=disposition == "rejected",
        )
        for index, relation_id in enumerate(relation_ids):
            _identifier(
                relation_id,
                "relation",
                path=f"$.entries[].relation_ids[{index}]",
                code=code,
            )
        proposal_refs = _sorted_unique_text(
            value["proposal_field_refs"],
            path="$.entries[].proposal_field_refs",
            code=code,
            allowed=PROPOSAL_FIELD_REFS,
            nonempty=True,
        )
        reason_raw = value["reason_code"]
        reason = (
            None
            if reason_raw is None
            else _text(reason_raw, path="$.entries[].reason_code", code=code)
        )
        if disposition == "not_applicable":
            if reason not in NOT_APPLICABLE_REASON_CODES:
                raise _error(code, "not_applicable requires an exact reason code")
            if role != "active":
                raise _error(code, "only active retrieval hits may be not_applicable")
        elif reason is not None:
            raise _error(code, "reason_code must be null unless disposition is not_applicable")
        if disposition == "used" and role != "active":
            raise _error(code, "only active retrieval hits may be used")
        if disposition == "rejected" and role != "contradiction":
            raise _error(code, "only contradiction hits may be rejected")
        if value["authorized_action"] is not None:
            raise _error(code, "authorized_action must be literal null")
        return cls(
            _identifier(value["claim_id"], "claim", path="$.entries[].claim_id", code=code),
            _digest(value["claim_digest"], path="$.entries[].claim_digest", code=code),
            role,
            relation_ids,
            cast(Literal["used", "rejected", "not_applicable"], disposition),
            proposal_refs,
            reason,
            _text(
                value["rationale"],
                path="$.entries[].rationale",
                code=code,
                maximum=MAX_DISPOSITION_RATIONALE_UTF8_BYTES,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "claim_digest": self.claim_digest,
            "retrieval_role": self.retrieval_role,
            "relation_ids": list(self.relation_ids),
            "disposition": self.disposition,
            "proposal_field_refs": list(self.proposal_field_refs),
            "reason_code": self.reason_code,
            "rationale": self.rationale,
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class ProposalKnowledgeDisposition:
    knowledge_disposition_schema_version: int
    disposition_id: str
    proposal_id: str
    proposal_digest: str
    generation_id: str
    hypothesis_class_id: str
    evaluation_scope_id: str
    context_token: str
    program_id: str
    program_head_sequence: int
    program_head_hash: str
    query_digest: str
    retrieval_result_digest: str
    entries: tuple[KnowledgeDispositionEntry, ...]
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "knowledge_disposition_schema_version",
            "disposition_id",
            "proposal_id",
            "proposal_digest",
            "generation_id",
            "hypothesis_class_id",
            "evaluation_scope_id",
            "context_token",
            "program_id",
            "program_head",
            "query_digest",
            "retrieval_result_digest",
            "entries",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProposalKnowledgeDisposition:
        code = "KNOWLEDGE_DISPOSITION_INVALID"
        value = _object(raw, cls._KEYS, path="$", code=code)
        head = _object(
            value["program_head"], {"sequence", "hash"}, path="$.program_head", code=code
        )
        entries = tuple(
            KnowledgeDispositionEntry.from_mapping(cast(Mapping[str, Any], item))
            for item in _array(value["entries"], path="$.entries", code=code)
        )
        claim_ids = tuple(item.claim_id for item in entries)
        if not entries or claim_ids != tuple(sorted(set(claim_ids))):
            raise _error(code, "entries must be non-empty, claim-sorted, and unique")
        if value["authorized_action"] is not None:
            raise _error(code, "authorized_action must be literal null")
        disposition = cls(
            _literal_version(
                value["knowledge_disposition_schema_version"],
                KNOWLEDGE_DISPOSITION_SCHEMA_VERSION,
                path="$.knowledge_disposition_schema_version",
                code=code,
            ),
            _identifier(value["disposition_id"], "disposition", path="$.disposition_id", code=code),
            _identifier(value["proposal_id"], "proposal", path="$.proposal_id", code=code),
            _digest(value["proposal_digest"], path="$.proposal_digest", code=code),
            _identifier(value["generation_id"], "generation", path="$.generation_id", code=code),
            _text(value["hypothesis_class_id"], path="$.hypothesis_class_id", code=code),
            _text(value["evaluation_scope_id"], path="$.evaluation_scope_id", code=code),
            _digest(value["context_token"], path="$.context_token", code=code),
            _identifier(value["program_id"], "program", path="$.program_id", code=code),
            _positive_integer(head["sequence"], path="$.program_head.sequence", code=code),
            _digest(head["hash"], path="$.program_head.hash", code=code),
            _digest(value["query_digest"], path="$.query_digest", code=code),
            _digest(
                value["retrieval_result_digest"],
                path="$.retrieval_result_digest",
                code=code,
            ),
            entries,
        )
        if disposition.disposition_id != disposition.expected_id:
            raise _error(code, "disposition_id does not match the canonical body")
        return disposition

    @property
    def program_head(self) -> tuple[int, str]:
        return self.program_head_sequence, self.program_head_hash

    def _identity_dict(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("disposition_id")
        return value

    @property
    def expected_id(self) -> str:
        return stable_id("disposition", self._identity_dict())

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_disposition_schema_version": self.knowledge_disposition_schema_version,
            "disposition_id": self.disposition_id,
            "proposal_id": self.proposal_id,
            "proposal_digest": self.proposal_digest,
            "generation_id": self.generation_id,
            "hypothesis_class_id": self.hypothesis_class_id,
            "evaluation_scope_id": self.evaluation_scope_id,
            "context_token": self.context_token,
            "program_id": self.program_id,
            "program_head": {
                "sequence": self.program_head_sequence,
                "hash": self.program_head_hash,
            },
            "query_digest": self.query_digest,
            "retrieval_result_digest": self.retrieval_result_digest,
            "entries": [entry.to_dict() for entry in self.entries],
            "authorized_action": None,
        }


def create_proposal_knowledge_disposition(
    *,
    project_id: str,
    proposal: Proposal,
    retrieval: RetrievalResult,
    context_token: str,
    entries: Sequence[KnowledgeDispositionEntry | Mapping[str, Any]],
) -> ProposalKnowledgeDisposition:
    """Build one canonical disposition body; cross-validation remains explicit."""

    parsed_entries = tuple(
        item
        if isinstance(item, KnowledgeDispositionEntry)
        else KnowledgeDispositionEntry.from_mapping(item)
        for item in entries
    )
    raw: dict[str, Any] = {
        "knowledge_disposition_schema_version": KNOWLEDGE_DISPOSITION_SCHEMA_VERSION,
        "disposition_id": "disposition_placeholder",
        "proposal_id": proposal_id(project_id, proposal.digest),
        "proposal_digest": proposal.digest,
        "generation_id": proposal.generation_id,
        "hypothesis_class_id": proposal.hypothesis_class_id,
        "evaluation_scope_id": proposal.evaluation_scope_id,
        "context_token": context_token,
        "program_id": retrieval.program_id,
        "program_head": {
            "sequence": retrieval.program_head[0],
            "hash": retrieval.program_head[1],
        },
        "query_digest": retrieval.query.digest,
        "retrieval_result_digest": retrieval.digest,
        "entries": [
            item.to_dict() for item in sorted(parsed_entries, key=lambda item: item.claim_id)
        ],
        "authorized_action": None,
    }
    identity = dict(raw)
    identity.pop("disposition_id")
    raw["disposition_id"] = stable_id("disposition", identity)
    return ProposalKnowledgeDisposition.from_mapping(raw)


def validate_proposal_knowledge_disposition(
    disposition: ProposalKnowledgeDisposition | Mapping[str, Any],
    *,
    project_id: str,
    proposal: Proposal,
    retrieval: RetrievalResult,
    context_token: str,
) -> ProposalKnowledgeDisposition:
    """Reject any disposition that does not exactly cover its retrieval read set."""

    code = "KNOWLEDGE_DISPOSITION_INVALID"
    parsed = (
        disposition
        if isinstance(disposition, ProposalKnowledgeDisposition)
        else ProposalKnowledgeDisposition.from_mapping(disposition)
    )
    parsed = ProposalKnowledgeDisposition.from_mapping(parsed.to_dict())
    expected_bindings = (
        proposal_id(project_id, proposal.digest),
        proposal.digest,
        proposal.generation_id,
        proposal.hypothesis_class_id,
        proposal.evaluation_scope_id,
        context_token,
        retrieval.program_id,
        retrieval.program_head,
        retrieval.query.digest,
        retrieval.digest,
    )
    observed_bindings = (
        parsed.proposal_id,
        parsed.proposal_digest,
        parsed.generation_id,
        parsed.hypothesis_class_id,
        parsed.evaluation_scope_id,
        parsed.context_token,
        parsed.program_id,
        parsed.program_head,
        parsed.query_digest,
        parsed.retrieval_result_digest,
    )
    if observed_bindings != expected_bindings:
        raise _error(code, "disposition does not match its Proposal/context/retrieval bindings")
    if (
        retrieval.query.hypothesis_class_id != proposal.hypothesis_class_id
        or retrieval.query.evaluation_scope.evaluation_scope_id != proposal.evaluation_scope_id
    ):
        raise _error(code, "retrieval query does not match the Proposal class and scope")
    hits = {item.claim_id: item for item in (*retrieval.active, *retrieval.contradictions)}
    entries_by_id = {item.claim_id: item for item in parsed.entries}
    if set(entries_by_id) != set(hits) or len(entries_by_id) != len(parsed.entries):
        raise _error(code, "entries must exactly cover every returned Claim once")
    for claim_id, hit in hits.items():
        entry = entries_by_id[claim_id]
        if (
            entry.claim_digest != hit.view.claim_digest
            or entry.retrieval_role != hit.relation_role
            or entry.relation_ids != hit.relation_ids
        ):
            raise _error(code, "entry Claim digest, role, or relation refs do not match retrieval")
    return parsed


@dataclass(frozen=True, slots=True)
class LegacyOpaqueRecord:
    legacy_opaque_schema_version: int
    legacy_opaque_id: str
    program_id: str
    source_project_id: str
    source_kind: str
    source_locator: str
    content_sha256: str
    content_size: int
    media_type: str
    classification: Literal["legacy_unstructured"] = "legacy_unstructured"
    typed_claim_ids: tuple[()] = ()
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "legacy_opaque_schema_version",
            "legacy_opaque_id",
            "program_id",
            "source_project_id",
            "source_kind",
            "source_locator",
            "content_sha256",
            "content_size",
            "media_type",
            "classification",
            "typed_claim_ids",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> LegacyOpaqueRecord:
        code = "LEGACY_OPAQUE_INVALID"
        value = _object(raw, cls._KEYS, path="$", code=code)
        source_kind = _text(value["source_kind"], path="$.source_kind", code=code)
        if source_kind not in LEGACY_SOURCE_KINDS:
            raise _error(code, "unsupported legacy source_kind", path="$.source_kind")
        size = value["content_size"]
        if (
            isinstance(size, bool)
            or not isinstance(size, int)
            or not 0 <= size <= MAX_LEGACY_CONTENT_BYTES
        ):
            raise _error(code, "content_size is outside the bounded legacy range")
        typed = _array(value["typed_claim_ids"], path="$.typed_claim_ids", code=code)
        if list(typed):
            raise _error(code, "typed_claim_ids must be an empty array")
        if value["classification"] != "legacy_unstructured":
            raise _error(code, "classification must be literal legacy_unstructured")
        if value["authorized_action"] is not None:
            raise _error(code, "authorized_action must be literal null")
        record = cls(
            _literal_version(
                value["legacy_opaque_schema_version"],
                LEGACY_OPAQUE_SCHEMA_VERSION,
                path="$.legacy_opaque_schema_version",
                code=code,
            ),
            _identifier(value["legacy_opaque_id"], "legacy", path="$.legacy_opaque_id", code=code),
            _identifier(value["program_id"], "program", path="$.program_id", code=code),
            _text(value["source_project_id"], path="$.source_project_id", code=code),
            source_kind,
            _text(
                value["source_locator"],
                path="$.source_locator",
                code=code,
                maximum=MAX_LEGACY_SOURCE_LOCATOR_UTF8_BYTES,
            ),
            _digest(value["content_sha256"], path="$.content_sha256", code=code),
            size,
            _text(value["media_type"], path="$.media_type", code=code, maximum=255),
        )
        if record.legacy_opaque_id != record.expected_id:
            raise _error(code, "legacy_opaque_id does not match the canonical body")
        return record

    def _identity_dict(self) -> dict[str, Any]:
        value = self.to_dict()
        value.pop("legacy_opaque_id")
        return value

    @property
    def expected_id(self) -> str:
        return stable_id("legacy", self._identity_dict())

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "legacy_opaque_schema_version": self.legacy_opaque_schema_version,
            "legacy_opaque_id": self.legacy_opaque_id,
            "program_id": self.program_id,
            "source_project_id": self.source_project_id,
            "source_kind": self.source_kind,
            "source_locator": self.source_locator,
            "content_sha256": self.content_sha256,
            "content_size": self.content_size,
            "media_type": self.media_type,
            "classification": "legacy_unstructured",
            "typed_claim_ids": [],
            "authorized_action": None,
        }


def create_legacy_opaque_record(
    *,
    program_id: str,
    source_project_id: str,
    source_kind: str,
    source_locator: str,
    content: bytes,
    media_type: str = "text/plain",
) -> LegacyOpaqueRecord:
    """Create metadata for bounded legacy bytes without retaining their content."""

    if not isinstance(content, bytes):
        raise TypeError("legacy content must be bytes")
    if len(content) > MAX_LEGACY_CONTENT_BYTES:
        raise _error("LEGACY_OPAQUE_INVALID", "legacy content exceeds its byte limit")
    raw: dict[str, Any] = {
        "legacy_opaque_schema_version": LEGACY_OPAQUE_SCHEMA_VERSION,
        "legacy_opaque_id": "legacy_placeholder",
        "program_id": program_id,
        "source_project_id": source_project_id,
        "source_kind": source_kind,
        "source_locator": source_locator,
        "content_sha256": hashlib.sha256(content).hexdigest(),
        "content_size": len(content),
        "media_type": media_type,
        "classification": "legacy_unstructured",
        "typed_claim_ids": [],
        "authorized_action": None,
    }
    identity = dict(raw)
    identity.pop("legacy_opaque_id")
    raw["legacy_opaque_id"] = stable_id("legacy", identity)
    return LegacyOpaqueRecord.from_mapping(raw)


def validate_legacy_content(record: LegacyOpaqueRecord, content: bytes) -> None:
    if not isinstance(content, bytes):
        raise TypeError("legacy content must be bytes")
    if (
        len(content) != record.content_size
        or hashlib.sha256(content).hexdigest() != record.content_sha256
    ):
        raise _error("LEGACY_OPAQUE_INVALID", "legacy content digest or size mismatch")


@dataclass(frozen=True, slots=True)
class KnowledgeDispositionSnapshot:
    program_id: str
    program_head_sequence: int
    program_head_hash: str
    dispositions: tuple[ProposalKnowledgeDisposition, ...]
    authorized_action: None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "knowledge_disposition_projection_schema_version": 1,
            "program_id": self.program_id,
            "program_head": {
                "sequence": self.program_head_sequence,
                "hash": self.program_head_hash,
            },
            "dispositions": [item.to_dict() for item in self.dispositions],
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class LegacyOpaqueSnapshot:
    program_id: str
    program_head_sequence: int
    program_head_hash: str
    records: tuple[LegacyOpaqueRecord, ...]
    authorized_action: None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "legacy_opaque_projection_schema_version": 1,
            "program_id": self.program_id,
            "program_head": {
                "sequence": self.program_head_sequence,
                "hash": self.program_head_hash,
            },
            "records": [item.to_dict() for item in self.records],
            "authorized_action": None,
        }
