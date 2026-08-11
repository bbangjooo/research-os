"""Canonical program manifests, origin evidence, log, and rebuildable projection."""

from __future__ import annotations

import fcntl
import os
import stat
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, cast

from research_os.contracts.common import sha256_json
from research_os.errors import IntegrityError, ProgramMemoryError
from research_os.kernel._canonical import (
    JSONValue,
    canonical_bytes,
    json_value,
    require_text,
    sha256_hex,
    strict_json_loads,
    utc_now,
    validate_timestamp,
)
from research_os.kernel.events import EventLog
from research_os.kernel.ids import new_id, stable_id, validate_namespaced_id
from research_os.memory.claims import (
    PROGRAM_CLAIM_RECORDED_EVENT,
    PROGRAM_CLAIM_RELATED_EVENT,
    Claim,
    ClaimRelation,
    ClaimSnapshot,
    claim_event_payload,
    claim_from_event_payload,
    reduce_claim_records,
    relation_event_payload,
    relation_from_event_payload,
)
from research_os.science.state import ScientificState, reduce_scientific_state

PROGRAM_EVENT_VERSION = 1
PROGRAM_MANIFEST_SCHEMA_VERSION = 1
ORIGIN_EVIDENCE_SCHEMA_VERSION = 1
PROGRAM_PROJECTION_SCHEMA_VERSION = 1
PROGRAM_INITIALIZED_EVENT = "research.program.initialized.v1"
PROGRAM_ORIGIN_LINKED_EVENT = "research.program.origin_linked.v1"

_HASH_LENGTH = 64
_SCOPE_ROLES = frozenset({"development", "diagnostic", "replication", "holdout"})
_PROGRAM_EVENT_TYPES = frozenset(
    {
        PROGRAM_INITIALIZED_EVENT,
        PROGRAM_ORIGIN_LINKED_EVENT,
        PROGRAM_CLAIM_RECORDED_EVENT,
        PROGRAM_CLAIM_RELATED_EVENT,
    }
)
_UNSAFE_WRITE_BITS = stat.S_IWGRP | stat.S_IWOTH
ProgramHead = tuple[int, str | None]


def _error(
    code: str,
    message: str,
    *,
    path: str | None = None,
    **details: object,
) -> ProgramMemoryError:
    if path is not None:
        details.setdefault("path", path)
    return ProgramMemoryError(code, message, details=details)


def _object(
    value: Any,
    keys: set[str] | frozenset[str],
    *,
    path: str,
    code: str,
) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise _error(code, f"{path} must be an object", path=path)
    actual = set(value)
    if actual != set(keys):
        raise _error(
            code,
            f"{path} must have exact keys",
            path=path,
            missing=sorted(set(keys) - actual),
            unknown=sorted(actual - set(keys)),
        )
    return value


def _array(value: Any, *, path: str, code: str) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        raise _error(code, f"{path} must be an array", path=path)
    return value


def _text(value: Any, *, path: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise _error(code, f"{path} must be non-empty trimmed text", path=path)
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise _error(code, f"{path} must contain Unicode scalar values", path=path)
    return value


def _literal_version(value: Any, expected: int, *, path: str, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != expected:
        raise _error(code, f"{path} must equal literal integer {expected}", path=path)
    return expected


def _positive_integer(value: Any, *, path: str, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise _error(code, f"{path} must be a positive integer", path=path)
    return value


def _digest(value: Any, *, path: str, code: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != _HASH_LENGTH
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise _error(code, f"{path} must be a lowercase SHA-256 digest", path=path)
    return value


def _namespaced_id(value: Any, namespace: str, *, path: str, code: str) -> str:
    text = _text(value, path=path, code=code)
    try:
        return validate_namespaced_id(text, namespace)
    except (TypeError, ValueError) as exc:
        raise _error(code, f"{path} must be a {namespace} ID", path=path) from exc


def _null_authority(value: Any, *, path: str, code: str) -> None:
    if value is not None:
        raise _error(code, f"{path} must be literal null", path=path)
    return None


def _validated_head(value: ProgramHead) -> ProgramHead:
    if not isinstance(value, tuple) or len(value) != 2:
        raise TypeError("expected_head must be a (sequence, hash) tuple")
    sequence, digest = value
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
        raise ValueError("expected_head sequence must be a non-negative integer")
    if sequence == 0:
        if digest is not None:
            raise ValueError("the empty expected_head must be (0, None)")
    else:
        _digest(
            digest,
            path="$.expected_head.hash",
            code="PROGRAM_HEAD_INVALID",
        )
    return sequence, digest


class ProgramHeadMismatchError(ProgramMemoryError):
    """The canonical ProgramLog head changed before append."""

    code = "PROGRAM_HEAD_MISMATCH"

    def __init__(self, expected_head: ProgramHead, actual_head: ProgramHead):
        self.expected_head = expected_head
        self.actual_head = actual_head
        super().__init__(
            self.code,
            "program log head changed before append",
            details={"expected_head": expected_head, "actual_head": actual_head},
        )


@dataclass(frozen=True, slots=True)
class ProgramBinding:
    """One exact M1 study-generation/scope identity admitted by a program."""

    project_id: str
    science_state_schema_version: int
    study_contract_schema_version: int
    study_contract_digest: str
    generation_id: str
    evaluation_scope_schema_version: int
    evaluation_scope_id: str
    evaluation_scope_role: str
    evaluation_scope_manifest_digest: str
    evaluation_scope_digest: str
    evaluation_seal_digest: str
    compatibility_digest: str
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "project_id",
            "science_state_schema_version",
            "study_contract_schema_version",
            "study_contract_digest",
            "generation_id",
            "evaluation_scope_schema_version",
            "evaluation_scope",
            "evaluation_scope_digest",
            "evaluation_seal_digest",
            "compatibility_digest",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProgramBinding:
        code = "PROGRAM_MANIFEST_INVALID"
        value = _object(raw, cls._KEYS, path="$.bindings[]", code=code)
        scope = _object(
            value["evaluation_scope"],
            {"id", "role", "manifest_digest"},
            path="$.bindings[].evaluation_scope",
            code=code,
        )
        project_id = _text(value["project_id"], path="$.bindings[].project_id", code=code)
        science_version = _literal_version(
            value["science_state_schema_version"],
            1,
            path="$.bindings[].science_state_schema_version",
            code=code,
        )
        contract_version = _literal_version(
            value["study_contract_schema_version"],
            2,
            path="$.bindings[].study_contract_schema_version",
            code=code,
        )
        scope_version = _literal_version(
            value["evaluation_scope_schema_version"],
            1,
            path="$.bindings[].evaluation_scope_schema_version",
            code=code,
        )
        scope_id = _text(scope["id"], path="$.bindings[].evaluation_scope.id", code=code)
        scope_role = _text(
            scope["role"], path="$.bindings[].evaluation_scope.role", code=code
        )
        if scope_role not in _SCOPE_ROLES:
            raise _error(
                code,
                "$.bindings[].evaluation_scope.role is unsupported",
                path="$.bindings[].evaluation_scope.role",
            )
        scope_manifest_digest = _digest(
            scope["manifest_digest"],
            path="$.bindings[].evaluation_scope.manifest_digest",
            code=code,
        )
        expected_scope_digest = sha256_json(
            {
                "evaluation_scope_schema_version": scope_version,
                "evaluation_scope": {
                    "id": scope_id,
                    "role": scope_role,
                    "manifest_digest": scope_manifest_digest,
                },
            }
        )
        observed_scope_digest = _digest(
            value["evaluation_scope_digest"],
            path="$.bindings[].evaluation_scope_digest",
            code=code,
        )
        if observed_scope_digest != expected_scope_digest:
            raise _error(
                code,
                "evaluation_scope_digest does not match the exact scope body",
                path="$.bindings[].evaluation_scope_digest",
                expected_digest=expected_scope_digest,
                observed_digest=observed_scope_digest,
            )
        _null_authority(
            value["authorized_action"],
            path="$.bindings[].authorized_action",
            code=code,
        )
        return cls(
            project_id=project_id,
            science_state_schema_version=science_version,
            study_contract_schema_version=contract_version,
            study_contract_digest=_digest(
                value["study_contract_digest"],
                path="$.bindings[].study_contract_digest",
                code=code,
            ),
            generation_id=_namespaced_id(
                value["generation_id"],
                "generation",
                path="$.bindings[].generation_id",
                code=code,
            ),
            evaluation_scope_schema_version=scope_version,
            evaluation_scope_id=scope_id,
            evaluation_scope_role=scope_role,
            evaluation_scope_manifest_digest=scope_manifest_digest,
            evaluation_scope_digest=observed_scope_digest,
            evaluation_seal_digest=_digest(
                value["evaluation_seal_digest"],
                path="$.bindings[].evaluation_seal_digest",
                code=code,
            ),
            compatibility_digest=_digest(
                value["compatibility_digest"],
                path="$.bindings[].compatibility_digest",
                code=code,
            ),
        )

    @property
    def key(self) -> tuple[str, str, str]:
        return self.project_id, self.generation_id, self.evaluation_scope_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "science_state_schema_version": self.science_state_schema_version,
            "study_contract_schema_version": self.study_contract_schema_version,
            "study_contract_digest": self.study_contract_digest,
            "generation_id": self.generation_id,
            "evaluation_scope_schema_version": self.evaluation_scope_schema_version,
            "evaluation_scope": {
                "id": self.evaluation_scope_id,
                "role": self.evaluation_scope_role,
                "manifest_digest": self.evaluation_scope_manifest_digest,
            },
            "evaluation_scope_digest": self.evaluation_scope_digest,
            "evaluation_seal_digest": self.evaluation_seal_digest,
            "compatibility_digest": self.compatibility_digest,
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class ProgramManifest:
    """Immutable program membership and exact study-identity bindings."""

    program_manifest_schema_version: int
    program_id: str
    bindings: tuple[ProgramBinding, ...]
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {"program_manifest_schema_version", "program_id", "bindings", "authorized_action"}
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProgramManifest:
        code = "PROGRAM_MANIFEST_INVALID"
        value = _object(raw, cls._KEYS, path="$", code=code)
        version = _literal_version(
            value["program_manifest_schema_version"],
            PROGRAM_MANIFEST_SCHEMA_VERSION,
            path="$.program_manifest_schema_version",
            code=code,
        )
        program_id = _namespaced_id(
            value["program_id"], "program", path="$.program_id", code=code
        )
        binding_items = _array(value["bindings"], path="$.bindings", code=code)
        if not binding_items:
            raise _error(code, "$.bindings must not be empty", path="$.bindings")
        bindings = tuple(
            ProgramBinding.from_mapping(cast(Mapping[str, Any], item))
            for item in binding_items
        )
        keys = tuple(binding.key for binding in bindings)
        if len(set(keys)) != len(keys):
            raise _error(code, "program bindings must be unique", path="$.bindings")
        if keys != tuple(sorted(keys)):
            raise _error(code, "program bindings must be sorted by identity", path="$.bindings")
        _null_authority(
            value["authorized_action"], path="$.authorized_action", code=code
        )
        manifest = cls(version, program_id, bindings)
        sha256_json(manifest.to_dict())
        return manifest

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def binding(self, project_id: str, generation_id: str, scope_id: str) -> ProgramBinding | None:
        key = (project_id, generation_id, scope_id)
        return next((item for item in self.bindings if item.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_manifest_schema_version": self.program_manifest_schema_version,
            "program_id": self.program_id,
            "bindings": [item.to_dict() for item in self.bindings],
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class OriginEvidenceRef:
    """Exact project-log prefix, Diagnosis, and derived ClassState provenance."""

    origin_evidence_schema_version: int
    origin_id: str
    project_id: str
    project_head_sequence: int
    project_head_hash: str
    generation_id: str
    evaluation_scope_id: str
    diagnosis_event_sequence: int
    diagnosis_event_id: str
    diagnosis_event_hash: str
    diagnosis_id: str
    diagnosis_digest: str
    class_state_id: str
    class_state_digest: str
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "origin_evidence_schema_version",
            "origin_id",
            "project_id",
            "project_head",
            "generation_id",
            "evaluation_scope_id",
            "diagnosis_event",
            "diagnosis_id",
            "diagnosis_digest",
            "class_state_id",
            "class_state_digest",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> OriginEvidenceRef:
        code = "PROGRAM_ORIGIN_INVALID"
        value = _object(raw, cls._KEYS, path="$", code=code)
        head = _object(
            value["project_head"], {"sequence", "hash"}, path="$.project_head", code=code
        )
        diagnosis_event = _object(
            value["diagnosis_event"],
            {"sequence", "event_id", "event_hash"},
            path="$.diagnosis_event",
            code=code,
        )
        version = _literal_version(
            value["origin_evidence_schema_version"],
            ORIGIN_EVIDENCE_SCHEMA_VERSION,
            path="$.origin_evidence_schema_version",
            code=code,
        )
        project_id = _text(value["project_id"], path="$.project_id", code=code)
        head_sequence = _positive_integer(
            head["sequence"], path="$.project_head.sequence", code=code
        )
        head_hash = _digest(head["hash"], path="$.project_head.hash", code=code)
        generation_id = _namespaced_id(
            value["generation_id"], "generation", path="$.generation_id", code=code
        )
        scope_id = _text(
            value["evaluation_scope_id"], path="$.evaluation_scope_id", code=code
        )
        diagnosis_sequence = _positive_integer(
            diagnosis_event["sequence"], path="$.diagnosis_event.sequence", code=code
        )
        if diagnosis_sequence > head_sequence:
            raise _error(
                code,
                "diagnosis event cannot follow the referenced project head",
                path="$.diagnosis_event.sequence",
            )
        diagnosis_event_id = _namespaced_id(
            diagnosis_event["event_id"],
            "event",
            path="$.diagnosis_event.event_id",
            code=code,
        )
        diagnosis_event_hash = _digest(
            diagnosis_event["event_hash"], path="$.diagnosis_event.event_hash", code=code
        )
        diagnosis_id = _namespaced_id(
            value["diagnosis_id"], "diagnosis", path="$.diagnosis_id", code=code
        )
        diagnosis_digest = _digest(
            value["diagnosis_digest"], path="$.diagnosis_digest", code=code
        )
        class_state_id = _namespaced_id(
            value["class_state_id"], "classstate", path="$.class_state_id", code=code
        )
        class_state_digest = _digest(
            value["class_state_digest"], path="$.class_state_digest", code=code
        )
        _null_authority(
            value["authorized_action"], path="$.authorized_action", code=code
        )
        components: tuple[object, ...] = (
            project_id,
            {"sequence": head_sequence, "hash": head_hash},
            generation_id,
            scope_id,
            diagnosis_id,
            diagnosis_digest,
            class_state_id,
            class_state_digest,
        )
        expected_id = stable_id("origin", *components)
        observed_id = _namespaced_id(
            value["origin_id"], "origin", path="$.origin_id", code=code
        )
        if observed_id != expected_id:
            raise _error(
                code,
                "origin_id does not match the exact evidence body",
                path="$.origin_id",
                expected_origin_id=expected_id,
                observed_origin_id=observed_id,
            )
        origin = cls(
            version,
            observed_id,
            project_id,
            head_sequence,
            head_hash,
            generation_id,
            scope_id,
            diagnosis_sequence,
            diagnosis_event_id,
            diagnosis_event_hash,
            diagnosis_id,
            diagnosis_digest,
            class_state_id,
            class_state_digest,
        )
        sha256_json(origin.to_dict())
        return origin

    @property
    def project_head(self) -> ProgramHead:
        return self.project_head_sequence, self.project_head_hash

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin_evidence_schema_version": self.origin_evidence_schema_version,
            "origin_id": self.origin_id,
            "project_id": self.project_id,
            "project_head": {
                "sequence": self.project_head_sequence,
                "hash": self.project_head_hash,
            },
            "generation_id": self.generation_id,
            "evaluation_scope_id": self.evaluation_scope_id,
            "diagnosis_event": {
                "sequence": self.diagnosis_event_sequence,
                "event_id": self.diagnosis_event_id,
                "event_hash": self.diagnosis_event_hash,
            },
            "diagnosis_id": self.diagnosis_id,
            "diagnosis_digest": self.diagnosis_digest,
            "class_state_id": self.class_state_id,
            "class_state_digest": self.class_state_digest,
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class ProgramEvent(Mapping[str, Any]):
    """The fixed ProgramLog envelope with an explicit program identity."""

    version: int
    sequence: int
    program_id: str
    event_id: str
    event_type: str
    occurred_at: str
    payload: dict[str, JSONValue]
    prev_hash: str | None
    hash: str

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "version",
        "sequence",
        "program_id",
        "event_id",
        "event_type",
        "occurred_at",
        "payload",
        "prev_hash",
        "hash",
    )

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "payload": json_value(self.payload),
            "prev_hash": self.prev_hash,
            "program_id": self.program_id,
            "sequence": self.sequence,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        result = self.unsigned_dict()
        result["hash"] = self.hash
        return result

    def __getitem__(self, key: str) -> Any:
        if key not in self._FIELDS:
            raise KeyError(key)
        if key == "payload":
            return json_value(self.payload)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._FIELDS)

    def __len__(self) -> int:
        return len(self._FIELDS)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProgramEvent:
        if not isinstance(raw, Mapping) or set(raw) != set(cls._FIELDS):
            raise IntegrityError("invalid program event envelope keys")
        try:
            version = raw["version"]
            sequence = raw["sequence"]
            if isinstance(version, bool) or version != PROGRAM_EVENT_VERSION:
                raise ValueError("unsupported program event version")
            if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
                raise ValueError("program event sequence must be a positive integer")
            program_id = validate_namespaced_id(
                require_text(raw["program_id"], "program_id"), "program"
            )
            event_id = validate_namespaced_id(
                require_text(raw["event_id"], "event_id"), "event"
            )
            event_type = require_text(raw["event_type"], "event_type")
            occurred_at = validate_timestamp(raw["occurred_at"])
            payload = json_value(raw["payload"], path="$.payload")
            prev_hash = raw["prev_hash"]
            digest = raw["hash"]
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrityError(f"invalid program event envelope: {exc}") from exc
        if not isinstance(payload, dict):
            raise IntegrityError("program event payload must be an object")
        if prev_hash is not None:
            try:
                _digest(prev_hash, path="$.prev_hash", code="PROGRAM_EVENT_INVALID")
            except ProgramMemoryError as exc:
                raise IntegrityError(str(exc)) from exc
        try:
            digest = _digest(digest, path="$.hash", code="PROGRAM_EVENT_INVALID")
        except ProgramMemoryError as exc:
            raise IntegrityError(str(exc)) from exc
        event = cls(
            version,
            sequence,
            program_id,
            event_id,
            event_type,
            occurred_at,
            payload,
            prev_hash,
            digest,
        )
        expected = sha256_hex(canonical_bytes(event.unsigned_dict()))
        if expected != digest:
            raise IntegrityError(
                f"program event {sequence} hash mismatch: expected {expected}, found {digest}"
            )
        return event


def _program_event_from_line(line: bytes, line_number: int) -> ProgramEvent:
    try:
        text = line.decode("utf-8")
        raw = strict_json_loads(text)
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        raise IntegrityError(f"invalid program log line {line_number}: {exc}") from exc
    if not isinstance(raw, dict):
        raise IntegrityError(f"program log line {line_number} is not an object")
    event = ProgramEvent.from_mapping(raw)
    if canonical_bytes(event.to_dict()) != line:
        raise IntegrityError(f"program log line {line_number} is not canonical JSON")
    return event


def verify_program_events(
    events: Sequence[ProgramEvent], *, program_id: str | None = None
) -> None:
    previous: ProgramEvent | None = None
    seen_ids: set[str] = set()
    for supplied in events:
        event = ProgramEvent.from_mapping(supplied.to_dict())
        expected_sequence = 1 if previous is None else previous.sequence + 1
        expected_hash = None if previous is None else previous.hash
        if event.sequence != expected_sequence:
            raise IntegrityError(
                f"program event sequence discontinuity: expected {expected_sequence}, found {event.sequence}"
            )
        if event.prev_hash != expected_hash:
            raise IntegrityError(
                f"program event {event.sequence} prev_hash does not match its predecessor"
            )
        if program_id is not None and event.program_id != program_id:
            raise IntegrityError(
                f"program event {event.sequence} belongs to {event.program_id!r}, expected {program_id!r}"
            )
        if event.event_id in seen_ids:
            raise IntegrityError(f"duplicate program event ID: {event.event_id}")
        seen_ids.add(event.event_id)
        previous = event


def _manifest_payload(payload: Mapping[str, Any]) -> ProgramManifest:
    value = _object(
        payload,
        {"program_manifest", "program_manifest_digest", "authorized_action"},
        path="$.payload",
        code="PROGRAM_LOG_INVALID",
    )
    _null_authority(
        value["authorized_action"], path="$.payload.authorized_action", code="PROGRAM_LOG_INVALID"
    )
    manifest = ProgramManifest.from_mapping(
        cast(Mapping[str, Any], value["program_manifest"])
    )
    observed = _digest(
        value["program_manifest_digest"],
        path="$.payload.program_manifest_digest",
        code="PROGRAM_LOG_INVALID",
    )
    if observed != manifest.digest:
        raise _error(
            "PROGRAM_LOG_INVALID",
            "program manifest digest mismatch",
            path="$.payload.program_manifest_digest",
        )
    return manifest


def _origin_payload(payload: Mapping[str, Any]) -> OriginEvidenceRef:
    value = _object(
        payload,
        {"origin_evidence", "origin_evidence_digest", "authorized_action"},
        path="$.payload",
        code="PROGRAM_LOG_INVALID",
    )
    _null_authority(
        value["authorized_action"], path="$.payload.authorized_action", code="PROGRAM_LOG_INVALID"
    )
    origin = OriginEvidenceRef.from_mapping(
        cast(Mapping[str, Any], value["origin_evidence"])
    )
    observed = _digest(
        value["origin_evidence_digest"],
        path="$.payload.origin_evidence_digest",
        code="PROGRAM_LOG_INVALID",
    )
    if observed != origin.digest:
        raise _error(
            "PROGRAM_LOG_INVALID",
            "origin evidence digest mismatch",
            path="$.payload.origin_evidence_digest",
        )
    return origin


def _validate_claim_program_binding(
    claim: Claim,
    manifest: ProgramManifest,
    origins: Sequence[OriginEvidenceRef],
) -> OriginEvidenceRef:
    evidence = claim.evidence
    applicability = claim.applicability
    origin = next((item for item in origins if item.origin_id == evidence.origin_id), None)
    exact_origin = (
        origin is not None
        and origin.digest == evidence.origin_digest
        and origin.diagnosis_event_sequence == evidence.diagnosis_event_sequence
        and origin.diagnosis_event_id == evidence.diagnosis_event_id
        and origin.diagnosis_event_hash == evidence.diagnosis_event_hash
        and origin.diagnosis_id == evidence.diagnosis_id
        and origin.diagnosis_digest == evidence.diagnosis_digest
    )
    if not exact_origin or origin is None:
        raise _error(
            "CLAIM_EVIDENCE_MISMATCH",
            "Claim evidence does not match a prior linked origin",
            claim_id=claim.claim_id,
        )
    binding = manifest.binding(
        applicability.project_id,
        applicability.generation_id,
        applicability.evaluation_scope_id,
    )
    if binding is None:
        raise _error(
            "CLAIM_EVIDENCE_MISMATCH",
            "Claim applicability is not admitted by the ProgramManifest",
            claim_id=claim.claim_id,
        )
    exact_applicability = (
        origin.project_id == applicability.project_id
        and origin.generation_id == applicability.generation_id
        and origin.evaluation_scope_id == applicability.evaluation_scope_id
        and origin.class_state_id
        == stable_id(
            "classstate",
            applicability.project_id,
            applicability.generation_id,
            applicability.hypothesis_class_id,
        )
        and binding.evaluation_scope_role == applicability.evaluation_scope_role
        and binding.evaluation_scope_manifest_digest
        == applicability.evaluation_scope_manifest_digest
        and binding.evaluation_scope_digest == applicability.evaluation_scope_digest
    )
    if not exact_applicability:
        raise _error(
            "CLAIM_EVIDENCE_MISMATCH",
            "Claim applicability does not match its origin and manifest binding",
            claim_id=claim.claim_id,
        )
    exact_seal = (
        binding.evaluation_seal_digest == applicability.evaluation_seal_digest
        == evidence.evaluation_seal_digest
        and binding.compatibility_digest == applicability.compatibility_digest
        == evidence.compatibility_digest
    )
    if not exact_seal:
        raise _error(
            "CLAIM_SCOPE_INCOMPATIBLE",
            "Claim seal or compatibility does not match the bound evaluation scope",
            claim_id=claim.claim_id,
        )
    return origin


def _program_stream_parts(
    events: Sequence[ProgramEvent],
    *,
    program_id: str,
    semantic_errors_as_integrity: bool = True,
) -> tuple[
    ProgramManifest | None,
    tuple[OriginEvidenceRef, ...],
    ClaimSnapshot | None,
]:
    verify_program_events(events, program_id=program_id)
    if not events:
        return None, (), None
    try:
        first = events[0]
        if first.event_type != PROGRAM_INITIALIZED_EVENT:
            raise _error(
                "PROGRAM_LOG_INVALID",
                "the first program event must initialize the program",
            )
        manifest = _manifest_payload(first.payload)
        if manifest.program_id != program_id:
            raise _error(
                "PROGRAM_LOG_INVALID",
                "initialized manifest program ID does not match the stream",
            )
        origins: list[OriginEvidenceRef] = []
        seen: set[str] = set()
        claim_records: list[Claim | ClaimRelation] = []
        for event in events[1:]:
            if event.event_type == PROGRAM_ORIGIN_LINKED_EVENT:
                origin = _origin_payload(event.payload)
                if manifest.binding(
                    origin.project_id, origin.generation_id, origin.evaluation_scope_id
                ) is None:
                    raise _error(
                        "PROGRAM_LOG_INVALID",
                        "origin evidence is not admitted by the program manifest",
                    )
                if origin.origin_id in seen:
                    raise _error(
                        "PROGRAM_LOG_INVALID", "duplicate origin evidence in ProgramLog"
                    )
                seen.add(origin.origin_id)
                origins.append(origin)
                continue
            if event.event_type == PROGRAM_CLAIM_RECORDED_EVENT:
                claim = claim_from_event_payload(event.payload)
                _validate_claim_program_binding(claim, manifest, origins)
                claim_records.append(claim)
                continue
            if event.event_type == PROGRAM_CLAIM_RELATED_EVENT:
                claim_records.append(relation_from_event_payload(event.payload))
                continue
            else:
                raise _error(
                    "PROGRAM_LOG_INVALID",
                    f"unsupported program event type: {event.event_type}",
                )
        head = events[-1]
        claim_snapshot = reduce_claim_records(
            claim_records,
            program_id=program_id,
            program_head=(head.sequence, head.hash),
        )
        return manifest, tuple(origins), claim_snapshot
    except ProgramMemoryError as exc:
        if semantic_errors_as_integrity:
            raise IntegrityError(
                f"invalid ProgramLog semantics ({exc.code}): {exc}"
            ) from exc
        raise


class _ProgramStorage(EventLog):
    """Reuse hardened descriptor mechanics while replacing the wire envelope."""

    def _events_from_bytes(self, data: bytes) -> list[Any]:
        if not data:
            return []
        if not data.endswith(b"\n"):
            raise IntegrityError("program log has an unterminated final line")
        lines = data[:-1].split(b"\n")
        if any(not line for line in lines):
            raise IntegrityError("program log contains an empty line")
        events = [_program_event_from_line(line, index) for index, line in enumerate(lines, 1)]
        verify_program_events(events, program_id=self.project_id)
        return events


class ProgramLog:
    """Dedicated append-only ProgramEvent stream with a program envelope."""

    def __init__(self, path: str | os.PathLike[str], program_id: str):
        try:
            self.program_id = validate_namespaced_id(program_id, "program")
        except (TypeError, ValueError) as exc:
            raise _error(
                "PROGRAM_LOG_INVALID", "program_id must be a program ID", path="$.program_id"
            ) from exc
        self._storage = _ProgramStorage(path, self.program_id)
        self.path = self._storage.path

    def read(self) -> list[ProgramEvent]:
        events = cast(list[ProgramEvent], self._storage.read())
        _program_stream_parts(events, program_id=self.program_id)
        return events

    @contextmanager
    def locked_read(self) -> Iterator[list[ProgramEvent]]:
        with self._storage.locked_read() as raw_events:
            events = cast(list[ProgramEvent], raw_events)
            _program_stream_parts(events, program_id=self.program_id)
            yield events

    def head(self) -> ProgramEvent | None:
        events = self.read()
        return events[-1] if events else None

    def verify(self) -> bool:
        self.read()
        return True

    def recover_tail(self) -> int:
        removed = self._storage.recover_tail()
        self.read()
        return removed

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        expected_head: ProgramHead,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> ProgramEvent:
        event_type = require_text(event_type, "event_type")
        if event_type not in _PROGRAM_EVENT_TYPES:
            raise _error(
                "PROGRAM_LOG_INVALID", f"unsupported ProgramLog event type: {event_type}"
            )
        converted = json_value(payload, path="$.payload")
        if not isinstance(converted, dict):
            raise TypeError("program event payload must be a mapping")
        event_id = new_id("event") if event_id is None else validate_namespaced_id(event_id, "event")
        occurred_at = utc_now() if occurred_at is None else validate_timestamp(occurred_at)
        expected_head = _validated_head(expected_head)

        fd, _created = self._storage._open_append_descriptor()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            self._storage._assert_canonical_append_inode(fd)
            os.fchmod(fd, 0o600)
            _, raw_events, prefix_bytes = self._storage._recover_tail_fd(fd)
            events = cast(list[ProgramEvent], raw_events)
            _program_stream_parts(events, program_id=self.program_id)
            previous = events[-1] if events else None
            actual_head: ProgramHead = (
                (previous.sequence, previous.hash) if previous else (0, None)
            )
            if expected_head != actual_head:
                raise ProgramHeadMismatchError(expected_head, actual_head)
            if any(existing.event_id == event_id for existing in events):
                raise IntegrityError(f"duplicate program event ID: {event_id}")
            unsigned = {
                "event_id": event_id,
                "event_type": event_type,
                "occurred_at": occurred_at,
                "payload": converted,
                "prev_hash": previous.hash if previous else None,
                "program_id": self.program_id,
                "sequence": previous.sequence + 1 if previous else 1,
                "version": PROGRAM_EVENT_VERSION,
            }
            digest = sha256_hex(canonical_bytes(unsigned))
            event = ProgramEvent.from_mapping({**unsigned, "hash": digest})
            _program_stream_parts(
                [*events, event],
                program_id=self.program_id,
                semantic_errors_as_integrity=False,
            )
            encoded = canonical_bytes(event.to_dict())
            provisional_bytes = prefix_bytes + encoded
            committed_bytes = provisional_bytes + b"\n"
            try:
                self._storage._assert_descriptor_bytes(
                    fd, prefix_bytes, stage="program append precondition"
                )
                self._storage._write_all_fd(fd, encoded)
                os.fsync(fd)
                self._storage._fsync_parent()
                self._storage._assert_descriptor_bytes(
                    fd, provisional_bytes, stage="provisional program append"
                )
                self._storage._assert_canonical_append_inode(fd)
                self._storage._write_all_fd(fd, b"\n")
                os.fsync(fd)
                self._storage._assert_descriptor_bytes(
                    fd, committed_bytes, stage="program append commit"
                )
                self._storage._assert_canonical_append_inode(fd)
            except BaseException as append_error:
                try:
                    self._storage._restore_append_prefix(fd, prefix_bytes)
                except BaseException as rollback_error:
                    raise IntegrityError(
                        "program append failed and rollback durability could not be confirmed"
                    ) from rollback_error
                raise append_error
            return event
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


@dataclass(frozen=True, slots=True)
class ProgramSnapshot:
    """Non-authoritative materialization rebuilt from one ProgramLog head."""

    program_projection_schema_version: int
    program_id: str
    program_manifest: ProgramManifest
    program_manifest_digest: str
    program_head_sequence: int
    program_head_hash: str
    origins: tuple[OriginEvidenceRef, ...]
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "program_projection_schema_version",
            "program_id",
            "program_manifest",
            "program_manifest_digest",
            "program_head",
            "origins",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ProgramSnapshot:
        code = "PROGRAM_PROJECTION_INVALID"
        value = _object(raw, cls._KEYS, path="$", code=code)
        version = _literal_version(
            value["program_projection_schema_version"],
            PROGRAM_PROJECTION_SCHEMA_VERSION,
            path="$.program_projection_schema_version",
            code=code,
        )
        program_id = _namespaced_id(
            value["program_id"], "program", path="$.program_id", code=code
        )
        manifest = ProgramManifest.from_mapping(
            cast(Mapping[str, Any], value["program_manifest"])
        )
        manifest_digest = _digest(
            value["program_manifest_digest"], path="$.program_manifest_digest", code=code
        )
        if manifest.program_id != program_id or manifest.digest != manifest_digest:
            raise _error(code, "projection manifest binding is inconsistent")
        head = _object(
            value["program_head"], {"sequence", "hash"}, path="$.program_head", code=code
        )
        head_sequence = _positive_integer(
            head["sequence"], path="$.program_head.sequence", code=code
        )
        head_hash = _digest(head["hash"], path="$.program_head.hash", code=code)
        origins = tuple(
            OriginEvidenceRef.from_mapping(cast(Mapping[str, Any], item))
            for item in _array(value["origins"], path="$.origins", code=code)
        )
        origin_ids = tuple(item.origin_id for item in origins)
        if len(set(origin_ids)) != len(origin_ids):
            raise _error(code, "projection contains duplicate origin evidence")
        _null_authority(
            value["authorized_action"], path="$.authorized_action", code=code
        )
        return cls(
            version,
            program_id,
            manifest,
            manifest_digest,
            head_sequence,
            head_hash,
            origins,
        )

    @property
    def program_head(self) -> ProgramHead:
        return self.program_head_sequence, self.program_head_hash

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_projection_schema_version": self.program_projection_schema_version,
            "program_id": self.program_id,
            "program_manifest": self.program_manifest.to_dict(),
            "program_manifest_digest": self.program_manifest_digest,
            "program_head": {
                "sequence": self.program_head_sequence,
                "hash": self.program_head_hash,
            },
            "origins": [item.to_dict() for item in self.origins],
            "authorized_action": None,
        }


def reduce_program_events(events: Sequence[ProgramEvent], *, program_id: str) -> ProgramSnapshot:
    manifest, origins, _ = _program_stream_parts(events, program_id=program_id)
    if manifest is None or not events:
        raise _error("PROGRAM_NOT_INITIALIZED", "ProgramLog is not initialized")
    head = events[-1]
    return ProgramSnapshot(
        PROGRAM_PROJECTION_SCHEMA_VERSION,
        program_id,
        manifest,
        manifest.digest,
        head.sequence,
        head.hash,
        origins,
    )


class ProgramProjection:
    """Canonical-JSON cache that is always checked against the ProgramLog."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise IntegrityError(f"program projection must not be a symbolic link: {self.path}")

    @contextmanager
    def _maintenance_lock(self) -> Iterator[None]:
        path = self.path.with_name(f".{self.path.name}.lock")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(path, flags, 0o600)
        except OSError as exc:
            raise IntegrityError(f"cannot open program projection lock: {exc}") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise IntegrityError("program projection lock must be a private regular file")
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _read_unlocked(self) -> ProgramSnapshot | None:
        if not self.path.exists():
            return None
        if self.path.is_symlink():
            raise IntegrityError("program projection must not be a symbolic link")
        try:
            info = self.path.stat()
            if not stat.S_ISREG(info.st_mode) or info.st_mode & _UNSAFE_WRITE_BITS:
                raise IntegrityError("program projection must be a private regular file")
            data = self.path.read_bytes()
            raw = strict_json_loads(data.decode("utf-8"))
            if not isinstance(raw, dict):
                return None
            snapshot = ProgramSnapshot.from_mapping(raw)
            if canonical_bytes(snapshot.to_dict()) != data:
                return None
            return snapshot
        except IntegrityError:
            raise
        except (OSError, UnicodeDecodeError, TypeError, ValueError, ProgramMemoryError):
            return None

    def _fsync_parent(self) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        fd = os.open(self.path.parent, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write_unlocked(self, snapshot: ProgramSnapshot) -> None:
        data = canonical_bytes(snapshot.to_dict())
        temp_fd, temp_name = tempfile.mkstemp(prefix=f".{self.path.name}.", dir=self.path.parent)
        temp_path = Path(temp_name)
        try:
            os.fchmod(temp_fd, 0o600)
            offset = 0
            while offset < len(data):
                written = os.write(temp_fd, data[offset:])
                if written <= 0:
                    raise OSError("short write while replacing program projection")
                offset += written
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = -1
            if self.path.is_symlink():
                raise IntegrityError("program projection path changed to a symbolic link")
            os.replace(temp_path, self.path)
            self._fsync_parent()
        finally:
            if temp_fd >= 0:
                os.close(temp_fd)
            if temp_path.exists():
                temp_path.unlink()

    def load_or_rebuild(self, log: ProgramLog) -> tuple[ProgramSnapshot, bool]:
        with log.locked_read() as events:
            expected = reduce_program_events(events, program_id=log.program_id)
            with self._maintenance_lock():
                observed = self._read_unlocked()
                if observed is not None and observed.to_dict() == expected.to_dict():
                    return expected, False
                self._write_unlocked(expected)
                return expected, True

    def rebuild(self, log: ProgramLog) -> ProgramSnapshot:
        with log.locked_read() as events:
            snapshot = reduce_program_events(events, program_id=log.program_id)
            with self._maintenance_lock():
                self._write_unlocked(snapshot)
            return snapshot


def _scope_body(state: ScientificState, scope_id: str) -> dict[str, Any] | None:
    if state.contract is None:
        return None
    scope = next((item for item in state.contract.evaluation_scopes if item.id == scope_id), None)
    return None if scope is None else scope.to_dict()


def _validate_binding(binding: ProgramBinding, state: ScientificState) -> None:
    scope_body = _scope_body(state, binding.evaluation_scope_id)
    actual = {
        "science_state_schema_version": 1,
        "study_contract_schema_version": (
            None if state.contract is None else state.contract.schema_version
        ),
        "study_contract_digest": state.study_contract_digest,
        "generation_id": state.active_generation_id,
        "evaluation_scope_schema_version": 1,
        "evaluation_scope": scope_body,
        "evaluation_scope_digest": (
            None
            if scope_body is None
            else sha256_json(
                {"evaluation_scope_schema_version": 1, "evaluation_scope": scope_body}
            )
        ),
        "evaluation_seal_digest": state.evaluation_seal_digest,
        "compatibility_digest": (
            None if state.evaluation_seal is None else state.evaluation_seal.compatibility_digest
        ),
    }
    expected = binding.to_dict()
    expected.pop("project_id")
    expected.pop("authorized_action")
    if actual != expected:
        raise _error(
            "PROGRAM_BINDING_MISMATCH",
            "program binding does not match the replayed project scientific state",
            project_id=binding.project_id,
            expected=expected,
            actual=actual,
        )


def validate_program_manifest(
    manifest: ProgramManifest,
    project_events: Mapping[str, Sequence[Any]],
) -> None:
    expected_projects = {binding.project_id for binding in manifest.bindings}
    if set(project_events) != expected_projects:
        raise _error(
            "PROGRAM_MANIFEST_INVALID",
            "project event snapshots must exactly cover manifest projects",
            expected_projects=sorted(expected_projects),
            observed_projects=sorted(project_events),
        )
    states = {
        project_id: reduce_scientific_state(events, project_id=project_id)
        for project_id, events in project_events.items()
    }
    for binding in manifest.bindings:
        _validate_binding(binding, states[binding.project_id])


def _origin_from_state(
    *,
    events: Sequence[Any],
    state: ScientificState,
    diagnosis_id: str,
) -> OriginEvidenceRef:
    if not events:
        raise _error("PROGRAM_ORIGIN_MISMATCH", "origin project event stream is empty")
    diagnosis = next(
        (item for item in state.diagnoses if item.diagnosis_id == diagnosis_id), None
    )
    if diagnosis is None:
        raise _error(
            "PROGRAM_ORIGIN_MISMATCH", "diagnosis is absent from the replayed project prefix"
        )
    class_state = next(
        (
            item
            for item in state.class_states
            if item.hypothesis_class_id == diagnosis.diagnosis.hypothesis_class_id
        ),
        None,
    )
    if class_state is None:
        raise _error(
            "PROGRAM_ORIGIN_MISMATCH", "derived ClassState is absent from the project prefix"
        )
    head = events[-1]
    raw: dict[str, Any] = {
        "origin_evidence_schema_version": ORIGIN_EVIDENCE_SCHEMA_VERSION,
        "origin_id": "origin_placeholder",
        "project_id": state.project_id,
        "project_head": {"sequence": head.sequence, "hash": head.hash},
        "generation_id": diagnosis.diagnosis.generation_id,
        "evaluation_scope_id": diagnosis.diagnosis.evaluation_scope_id,
        "diagnosis_event": {
            "sequence": diagnosis.event_sequence,
            "event_id": diagnosis.diagnosis_event_id,
            "event_hash": diagnosis.diagnosis_event_hash,
        },
        "diagnosis_id": diagnosis.diagnosis_id,
        "diagnosis_digest": diagnosis.diagnosis_digest,
        "class_state_id": class_state.class_state_id,
        "class_state_digest": class_state.class_state_digest,
        "authorized_action": None,
    }
    raw["origin_id"] = stable_id(
        "origin",
        raw["project_id"],
        raw["project_head"],
        raw["generation_id"],
        raw["evaluation_scope_id"],
        raw["diagnosis_id"],
        raw["diagnosis_digest"],
        raw["class_state_id"],
        raw["class_state_digest"],
    )
    return OriginEvidenceRef.from_mapping(raw)


def validate_origin_evidence(
    origin: OriginEvidenceRef,
    events: Sequence[Any],
    manifest: ProgramManifest,
    *,
    require_current_head: bool,
) -> None:
    if origin.project_head_sequence > len(events):
        raise _error(
            "PROGRAM_PROJECT_HEAD_MISMATCH",
            "origin references a project head beyond the canonical stream",
        )
    current_head: ProgramHead = (
        (events[-1].sequence, events[-1].hash) if events else (0, None)
    )
    if require_current_head and current_head != origin.project_head:
        raise _error(
            "PROGRAM_PROJECT_HEAD_MISMATCH",
            "project log head changed before origin append",
            expected_head=origin.project_head,
            actual_head=current_head,
        )
    prefix = events[: origin.project_head_sequence]
    if not prefix:
        raise _error("PROGRAM_PROJECT_HEAD_MISMATCH", "origin project prefix is empty")
    prefix_head = prefix[-1]
    if (prefix_head.sequence, prefix_head.hash) != origin.project_head:
        raise _error(
            "PROGRAM_PROJECT_HEAD_MISMATCH",
            "origin project prefix head does not match its exact reference",
        )
    state = reduce_scientific_state(prefix, project_id=origin.project_id)
    binding = manifest.binding(
        origin.project_id, origin.generation_id, origin.evaluation_scope_id
    )
    if binding is None:
        raise _error(
            "PROGRAM_ORIGIN_MISMATCH", "origin is not admitted by the ProgramManifest"
        )
    _validate_binding(binding, state)
    diagnosis = next(
        (item for item in state.diagnoses if item.diagnosis_id == origin.diagnosis_id), None
    )
    class_state = next(
        (item for item in state.class_states if item.class_state_id == origin.class_state_id),
        None,
    )
    exact_diagnosis = (
        diagnosis is not None
        and diagnosis.event_sequence == origin.diagnosis_event_sequence
        and diagnosis.diagnosis_event_id == origin.diagnosis_event_id
        and diagnosis.diagnosis_event_hash == origin.diagnosis_event_hash
        and diagnosis.diagnosis_digest == origin.diagnosis_digest
        and diagnosis.diagnosis.generation_id == origin.generation_id
        and diagnosis.diagnosis.evaluation_scope_id == origin.evaluation_scope_id
    )
    exact_class_state = (
        class_state is not None
        and class_state.generation_id == origin.generation_id
        and class_state.class_state_digest == origin.class_state_digest
        and diagnosis is not None
        and class_state.hypothesis_class_id == diagnosis.diagnosis.hypothesis_class_id
    )
    if not exact_diagnosis or not exact_class_state:
        raise _error(
            "PROGRAM_ORIGIN_MISMATCH",
            "origin evidence does not match replayed Diagnosis and ClassState",
        )


def validate_claim_evidence(
    claim: Claim,
    events: Sequence[Any],
    manifest: ProgramManifest,
    origins: Sequence[OriginEvidenceRef],
) -> None:
    """Replay and compare the complete external evidence referenced by one Claim."""

    origin = _validate_claim_program_binding(claim, manifest, origins)
    if not events or getattr(events[0], "project_id", None) != origin.project_id:
        raise _error(
            "CLAIM_EVIDENCE_MISMATCH",
            "Claim project evidence resolver does not match the origin project",
        )
    validate_origin_evidence(origin, events, manifest, require_current_head=False)
    prefix = events[: origin.project_head_sequence]
    state = reduce_scientific_state(prefix, project_id=origin.project_id)
    diagnosis = next(
        (item for item in state.diagnoses if item.diagnosis_id == origin.diagnosis_id),
        None,
    )
    if diagnosis is None:
        raise _error(
            "CLAIM_EVIDENCE_MISMATCH",
            "Claim Diagnosis is absent from the referenced project prefix",
        )
    evidence = claim.evidence
    applicability = claim.applicability
    exact_diagnosis = (
        diagnosis.event_sequence == evidence.diagnosis_event_sequence
        and diagnosis.diagnosis_event_id == evidence.diagnosis_event_id
        and diagnosis.diagnosis_event_hash == evidence.diagnosis_event_hash
        and diagnosis.diagnosis_id == evidence.diagnosis_id
        and diagnosis.diagnosis_digest == evidence.diagnosis_digest
        and diagnosis.diagnosis.generation_id == applicability.generation_id
        and diagnosis.diagnosis.hypothesis_class_id
        == applicability.hypothesis_class_id
        and diagnosis.diagnosis.evaluation_scope_id
        == applicability.evaluation_scope_id
    )
    exact_terminal = (
        evidence.terminal_evidence.to_dict()
        == diagnosis.diagnosis.terminal_evidence.to_dict()
    )
    exact_artifacts = [item.to_dict() for item in evidence.artifact_evidence] == [
        item.to_dict() for item in diagnosis.diagnosis.artifact_evidence
    ]
    exact_seal = (
        state.evaluation_seal_digest == evidence.evaluation_seal_digest
        == applicability.evaluation_seal_digest
        and state.evaluation_seal is not None
        and state.evaluation_seal.compatibility_digest
        == evidence.compatibility_digest
        == applicability.compatibility_digest
        == diagnosis.diagnosis.compatibility_digest
    )
    if not exact_diagnosis or not exact_terminal or not exact_artifacts:
        raise _error(
            "CLAIM_EVIDENCE_MISMATCH",
            "Claim does not match the complete Diagnosis, terminal, and artifact evidence",
            exact_diagnosis=exact_diagnosis,
            exact_terminal=exact_terminal,
            exact_artifacts=exact_artifacts,
        )
    if not exact_seal:
        raise _error(
            "CLAIM_SCOPE_INCOMPATIBLE",
            "Claim evidence seal or compatibility does not match project replay",
        )


class ProgramStore:
    """Coordinates project evidence locks, ProgramLog appends, and projection repair."""

    def __init__(self, root: str | os.PathLike[str], program_id: str):
        self.root = Path(os.path.abspath(os.fspath(Path(root).expanduser())))
        if self.root.is_symlink():
            raise IntegrityError("program root must not be a symbolic link")
        self.root.mkdir(parents=True, exist_ok=True)
        self.log = ProgramLog(self.root / "program-events.jsonl", program_id)
        self.projection = ProgramProjection(self.root / "program-projection.json")
        self.program_id = self.log.program_id

    def initialize(
        self,
        manifest: ProgramManifest | Mapping[str, Any],
        project_logs: Mapping[str, EventLog],
        *,
        expected_program_head: ProgramHead = (0, None),
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> ProgramEvent:
        if not isinstance(manifest, ProgramManifest):
            manifest = ProgramManifest.from_mapping(manifest)
        if manifest.program_id != self.program_id:
            raise _error(
                "PROGRAM_MANIFEST_INVALID", "manifest program ID does not match ProgramStore"
            )
        expected_projects = {binding.project_id for binding in manifest.bindings}
        if set(project_logs) != expected_projects:
            raise _error(
                "PROGRAM_MANIFEST_INVALID",
                "project logs must exactly cover manifest projects",
            )
        with ExitStack() as stack:
            snapshots: dict[str, Sequence[Any]] = {}
            for project_id in sorted(project_logs):
                log = project_logs[project_id]
                if log.project_id != project_id:
                    raise _error(
                        "PROGRAM_MANIFEST_INVALID",
                        "project log identity does not match its resolver key",
                    )
                snapshots[project_id] = stack.enter_context(log.locked_read())
            validate_program_manifest(manifest, snapshots)
            event = self.log.append(
                PROGRAM_INITIALIZED_EVENT,
                {
                    "program_manifest": manifest.to_dict(),
                    "program_manifest_digest": manifest.digest,
                    "authorized_action": None,
                },
                expected_head=expected_program_head,
                event_id=event_id,
                occurred_at=occurred_at,
            )
        self.projection.rebuild(self.log)
        return event

    def _manifest(self) -> ProgramManifest:
        events = self.log.read()
        manifest, _, _ = _program_stream_parts(events, program_id=self.program_id)
        if manifest is None:
            raise _error("PROGRAM_NOT_INITIALIZED", "ProgramStore is not initialized")
        return manifest

    def append_origin(
        self,
        origin: OriginEvidenceRef | Mapping[str, Any],
        project_log: EventLog,
        *,
        expected_program_head: ProgramHead,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> ProgramEvent:
        if not isinstance(origin, OriginEvidenceRef):
            origin = OriginEvidenceRef.from_mapping(origin)
        if project_log.project_id != origin.project_id:
            raise _error(
                "PROGRAM_ORIGIN_MISMATCH", "origin project ID does not match project log"
            )
        manifest = self._manifest()
        with project_log.locked_read() as events:
            validate_origin_evidence(
                origin, events, manifest, require_current_head=True
            )
            event = self.log.append(
                PROGRAM_ORIGIN_LINKED_EVENT,
                {
                    "origin_evidence": origin.to_dict(),
                    "origin_evidence_digest": origin.digest,
                    "authorized_action": None,
                },
                expected_head=expected_program_head,
                event_id=event_id,
                occurred_at=occurred_at,
            )
        self.projection.load_or_rebuild(self.log)
        return event

    def link_origin(
        self,
        project_log: EventLog,
        diagnosis_id: str,
        *,
        expected_program_head: ProgramHead,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> tuple[OriginEvidenceRef, ProgramEvent]:
        manifest = self._manifest()
        with project_log.locked_read() as events:
            state = reduce_scientific_state(events, project_id=project_log.project_id)
            origin = _origin_from_state(events=events, state=state, diagnosis_id=diagnosis_id)
            validate_origin_evidence(
                origin, events, manifest, require_current_head=True
            )
            event = self.log.append(
                PROGRAM_ORIGIN_LINKED_EVENT,
                {
                    "origin_evidence": origin.to_dict(),
                    "origin_evidence_digest": origin.digest,
                    "authorized_action": None,
                },
                expected_head=expected_program_head,
                event_id=event_id,
                occurred_at=occurred_at,
            )
        self.projection.load_or_rebuild(self.log)
        return origin, event

    def snapshot(self) -> tuple[ProgramSnapshot, bool]:
        return self.projection.load_or_rebuild(self.log)

    def append_claim(
        self,
        claim: Claim | Mapping[str, Any],
        project_log: EventLog,
        *,
        expected_program_head: ProgramHead,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> ProgramEvent:
        if not isinstance(claim, Claim):
            claim = Claim.from_mapping(claim)
        if project_log.project_id != claim.applicability.project_id:
            raise _error(
                "CLAIM_EVIDENCE_MISMATCH",
                "Claim project ID does not match the project log",
            )
        manifest = self._manifest()
        with project_log.locked_read() as project_events:
            _, origins, _ = _program_stream_parts(
                self.log.read(), program_id=self.program_id
            )
            validate_claim_evidence(claim, project_events, manifest, origins)
            event = self.log.append(
                PROGRAM_CLAIM_RECORDED_EVENT,
                claim_event_payload(claim),
                expected_head=expected_program_head,
                event_id=event_id,
                occurred_at=occurred_at,
            )
        self.projection.load_or_rebuild(self.log)
        return event

    def append_relation(
        self,
        relation: ClaimRelation | Mapping[str, Any],
        *,
        expected_program_head: ProgramHead,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> ProgramEvent:
        if not isinstance(relation, ClaimRelation):
            relation = ClaimRelation.from_mapping(relation)
        event = self.log.append(
            PROGRAM_CLAIM_RELATED_EVENT,
            relation_event_payload(relation),
            expected_head=expected_program_head,
            event_id=event_id,
            occurred_at=occurred_at,
        )
        self.projection.load_or_rebuild(self.log)
        return event

    def claim_snapshot(self) -> ClaimSnapshot:
        _, _, snapshot = _program_stream_parts(
            self.log.read(), program_id=self.program_id
        )
        if snapshot is None:
            raise _error("PROGRAM_NOT_INITIALIZED", "ProgramStore is not initialized")
        return snapshot

    def audit_origins(self, project_logs: Mapping[str, EventLog]) -> int:
        snapshot, _ = self.snapshot()
        expected_projects = {origin.project_id for origin in snapshot.origins}
        if set(project_logs) != expected_projects:
            raise _error(
                "PROGRAM_ORIGIN_MISMATCH",
                "project logs must exactly cover stored origin projects",
            )
        validated = 0
        with ExitStack() as stack:
            event_sets = {
                project_id: stack.enter_context(project_logs[project_id].locked_read())
                for project_id in sorted(project_logs)
            }
            for origin in snapshot.origins:
                validate_origin_evidence(
                    origin,
                    event_sets[origin.project_id],
                    snapshot.program_manifest,
                    require_current_head=False,
                )
                validated += 1
        return validated

    def audit_claims(self, project_logs: Mapping[str, EventLog]) -> int:
        snapshot = self.claim_snapshot()
        program_snapshot, _ = self.snapshot()
        expected_projects = {
            view.claim.applicability.project_id for view in snapshot.claims
        }
        if set(project_logs) != expected_projects:
            raise _error(
                "CLAIM_EVIDENCE_MISMATCH",
                "project logs must exactly cover stored Claim projects",
            )
        validated = 0
        with ExitStack() as stack:
            event_sets = {
                project_id: stack.enter_context(project_logs[project_id].locked_read())
                for project_id in sorted(project_logs)
            }
            for view in snapshot.claims:
                claim = view.claim
                validate_claim_evidence(
                    claim,
                    event_sets[claim.applicability.project_id],
                    program_snapshot.program_manifest,
                    program_snapshot.origins,
                )
                validated += 1
        return validated
