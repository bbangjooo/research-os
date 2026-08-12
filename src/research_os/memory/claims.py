"""Immutable, evidence-bound program Claims and deterministic relation reduction."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, TypeAlias, cast

from research_os.contracts.common import sha256_json
from research_os.errors import ProgramMemoryError
from research_os.kernel.ids import stable_id, validate_namespaced_id

CLAIM_SCHEMA_VERSION = 1
CLAIM_APPLICABILITY_SCHEMA_VERSION = 1
CLAIM_EVIDENCE_SCHEMA_VERSION = 1
CLAIM_RELATION_SCHEMA_VERSION = 1
CLAIM_PROJECTION_SCHEMA_VERSION = 1

PROGRAM_CLAIM_RECORDED_EVENT = "research.program.claim_recorded.v1"
PROGRAM_CLAIM_RELATED_EVENT = "research.program.claim_related.v1"

CLAIM_KINDS = frozenset({"effect", "constraint", "failure_mode", "invariance"})
CLAIM_RELATION_TYPES = frozenset(
    {
        "supports",
        "contradicts",
        "supersedes",
        "replicates",
        "derived_from",
        "applies_to",
    }
)
CLAIM_EFFECTIVE_STATUSES = frozenset({"active", "contested", "superseded"})
CLAIM_EFFECTIVE_MATURITIES = frozenset({"observed", "replicated"})
CLAIM_SCOPE_ROLES = frozenset(
    {"development", "diagnostic", "replication", "holdout"}
)

MAX_STATEMENT_UTF8_BYTES = 4096
MAX_FALSIFIER_UTF8_BYTES = 4096
MAX_LIMITATIONS = 8
MAX_LIMITATION_UTF8_BYTES = 2048
MAX_RATIONALE_UTF8_BYTES = 4096
_HASH_LENGTH = 64


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


def _bounded_text(
    value: Any,
    *,
    path: str,
    code: str,
    max_utf8_bytes: int,
) -> str:
    text = _text(value, path=path, code=code)
    if len(text.encode("utf-8")) > max_utf8_bytes:
        raise _error(
            code,
            f"{path} must not exceed {max_utf8_bytes} UTF-8 bytes",
            path=path,
        )
    return text


def _version(value: Any, expected: int, *, path: str, code: str) -> int:
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


def _identifier(value: Any, namespace: str, *, path: str, code: str) -> str:
    text = _text(value, path=path, code=code)
    try:
        return validate_namespaced_id(text, namespace)
    except (TypeError, ValueError) as exc:
        raise _error(code, f"{path} must be a {namespace} ID", path=path) from exc


def _null_authority(value: Any, *, path: str, code: str) -> None:
    if value is not None:
        raise _error(code, f"{path} must be literal null", path=path)
    return None


@dataclass(frozen=True, slots=True)
class ClaimStatement:
    kind: str
    summary: str
    falsifier: str

    _KEYS: ClassVar[frozenset[str]] = frozenset({"kind", "summary", "falsifier"})

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ClaimStatement:
        code = "CLAIM_INVALID"
        value = _object(raw, cls._KEYS, path="$.statement", code=code)
        kind = _text(value["kind"], path="$.statement.kind", code=code)
        if kind not in CLAIM_KINDS:
            raise _error(code, "$.statement.kind is unsupported", path="$.statement.kind")
        return cls(
            kind,
            _bounded_text(
                value["summary"],
                path="$.statement.summary",
                code=code,
                max_utf8_bytes=MAX_STATEMENT_UTF8_BYTES,
            ),
            _bounded_text(
                value["falsifier"],
                path="$.statement.falsifier",
                code=code,
                max_utf8_bytes=MAX_FALSIFIER_UTF8_BYTES,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "summary": self.summary, "falsifier": self.falsifier}


@dataclass(frozen=True, slots=True)
class ClaimApplicability:
    claim_applicability_schema_version: int
    project_id: str
    generation_id: str
    hypothesis_class_id: str
    evaluation_scope_id: str
    evaluation_scope_role: str
    evaluation_scope_manifest_digest: str
    evaluation_scope_digest: str
    evaluation_seal_digest: str
    compatibility_digest: str
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "claim_applicability_schema_version",
            "project_id",
            "generation_id",
            "hypothesis_class_id",
            "evaluation_scope",
            "evaluation_scope_digest",
            "evaluation_seal_digest",
            "compatibility_digest",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ClaimApplicability:
        code = "CLAIM_INVALID"
        value = _object(raw, cls._KEYS, path="$.applicability", code=code)
        scope = _object(
            value["evaluation_scope"],
            {"id", "role", "manifest_digest"},
            path="$.applicability.evaluation_scope",
            code=code,
        )
        role = _text(
            scope["role"], path="$.applicability.evaluation_scope.role", code=code
        )
        if role not in CLAIM_SCOPE_ROLES:
            raise _error(
                code,
                "$.applicability.evaluation_scope.role is unsupported",
                path="$.applicability.evaluation_scope.role",
            )
        parsed = cls(
            _version(
                value["claim_applicability_schema_version"],
                CLAIM_APPLICABILITY_SCHEMA_VERSION,
                path="$.applicability.claim_applicability_schema_version",
                code=code,
            ),
            _text(value["project_id"], path="$.applicability.project_id", code=code),
            _identifier(
                value["generation_id"],
                "generation",
                path="$.applicability.generation_id",
                code=code,
            ),
            _text(
                value["hypothesis_class_id"],
                path="$.applicability.hypothesis_class_id",
                code=code,
            ),
            _text(scope["id"], path="$.applicability.evaluation_scope.id", code=code),
            role,
            _digest(
                scope["manifest_digest"],
                path="$.applicability.evaluation_scope.manifest_digest",
                code=code,
            ),
            _digest(
                value["evaluation_scope_digest"],
                path="$.applicability.evaluation_scope_digest",
                code=code,
            ),
            _digest(
                value["evaluation_seal_digest"],
                path="$.applicability.evaluation_seal_digest",
                code=code,
            ),
            _digest(
                value["compatibility_digest"],
                path="$.applicability.compatibility_digest",
                code=code,
            ),
        )
        _null_authority(
            value["authorized_action"], path="$.applicability.authorized_action", code=code
        )
        expected_scope_digest = sha256_json(
            {
                "evaluation_scope_schema_version": 1,
                "evaluation_scope": {
                    "id": parsed.evaluation_scope_id,
                    "role": parsed.evaluation_scope_role,
                    "manifest_digest": parsed.evaluation_scope_manifest_digest,
                },
            }
        )
        if parsed.evaluation_scope_digest != expected_scope_digest:
            raise _error(
                code,
                "applicability evaluation-scope digest does not match its body",
                path="$.applicability.evaluation_scope_digest",
            )
        return parsed

    @property
    def scope_identity(self) -> tuple[str, str, str]:
        return self.project_id, self.generation_id, self.evaluation_scope_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_applicability_schema_version": self.claim_applicability_schema_version,
            "project_id": self.project_id,
            "generation_id": self.generation_id,
            "hypothesis_class_id": self.hypothesis_class_id,
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
class ClaimTerminalEvidence:
    experiment_id: str
    event_id: str
    event_hash: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ClaimTerminalEvidence:
        code = "CLAIM_INVALID"
        value = _object(
            raw,
            {"experiment_id", "event_id", "event_hash"},
            path="$.evidence.terminal_evidence",
            code=code,
        )
        return cls(
            _identifier(
                value["experiment_id"],
                "experiment",
                path="$.evidence.terminal_evidence.experiment_id",
                code=code,
            ),
            _identifier(
                value["event_id"],
                "event",
                path="$.evidence.terminal_evidence.event_id",
                code=code,
            ),
            _digest(
                value["event_hash"],
                path="$.evidence.terminal_evidence.event_hash",
                code=code,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "event_id": self.event_id,
            "event_hash": self.event_hash,
        }


@dataclass(frozen=True, slots=True)
class ClaimArtifactEvidence:
    artifact_id: str
    artifact_digest: str
    event_id: str
    event_hash: str

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], *, index: int
    ) -> ClaimArtifactEvidence:
        code = "CLAIM_INVALID"
        path = f"$.evidence.artifact_evidence[{index}]"
        value = _object(
            raw,
            {"artifact_id", "artifact_digest", "event_id", "event_hash"},
            path=path,
            code=code,
        )
        return cls(
            _identifier(value["artifact_id"], "artifact", path=f"{path}.artifact_id", code=code),
            _digest(value["artifact_digest"], path=f"{path}.artifact_digest", code=code),
            _identifier(value["event_id"], "event", path=f"{path}.event_id", code=code),
            _digest(value["event_hash"], path=f"{path}.event_hash", code=code),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_digest": self.artifact_digest,
            "event_id": self.event_id,
            "event_hash": self.event_hash,
        }


@dataclass(frozen=True, slots=True)
class ClaimEvidenceRef:
    claim_evidence_schema_version: int
    origin_id: str
    origin_digest: str
    diagnosis_event_sequence: int
    diagnosis_event_id: str
    diagnosis_event_hash: str
    diagnosis_id: str
    diagnosis_digest: str
    terminal_evidence: ClaimTerminalEvidence
    artifact_evidence: tuple[ClaimArtifactEvidence, ...]
    evaluation_seal_digest: str
    compatibility_digest: str
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "claim_evidence_schema_version",
            "origin_id",
            "origin_digest",
            "diagnosis_event",
            "diagnosis_id",
            "diagnosis_digest",
            "terminal_evidence",
            "artifact_evidence",
            "evaluation_seal_digest",
            "compatibility_digest",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ClaimEvidenceRef:
        code = "CLAIM_INVALID"
        value = _object(raw, cls._KEYS, path="$.evidence", code=code)
        diagnosis_event = _object(
            value["diagnosis_event"],
            {"sequence", "event_id", "event_hash"},
            path="$.evidence.diagnosis_event",
            code=code,
        )
        artifacts = tuple(
            ClaimArtifactEvidence.from_mapping(cast(Mapping[str, Any], item), index=index)
            for index, item in enumerate(
                _array(value["artifact_evidence"], path="$.evidence.artifact_evidence", code=code)
            )
        )
        artifact_keys = tuple((item.artifact_id, item.event_id) for item in artifacts)
        if len(set(artifact_keys)) != len(artifact_keys) or artifact_keys != tuple(
            sorted(artifact_keys)
        ):
            raise _error(
                code,
                "$.evidence.artifact_evidence must be ordered and unique",
                path="$.evidence.artifact_evidence",
            )
        parsed = cls(
            _version(
                value["claim_evidence_schema_version"],
                CLAIM_EVIDENCE_SCHEMA_VERSION,
                path="$.evidence.claim_evidence_schema_version",
                code=code,
            ),
            _identifier(value["origin_id"], "origin", path="$.evidence.origin_id", code=code),
            _digest(value["origin_digest"], path="$.evidence.origin_digest", code=code),
            _positive_integer(
                diagnosis_event["sequence"],
                path="$.evidence.diagnosis_event.sequence",
                code=code,
            ),
            _identifier(
                diagnosis_event["event_id"],
                "event",
                path="$.evidence.diagnosis_event.event_id",
                code=code,
            ),
            _digest(
                diagnosis_event["event_hash"],
                path="$.evidence.diagnosis_event.event_hash",
                code=code,
            ),
            _identifier(
                value["diagnosis_id"], "diagnosis", path="$.evidence.diagnosis_id", code=code
            ),
            _digest(value["diagnosis_digest"], path="$.evidence.diagnosis_digest", code=code),
            ClaimTerminalEvidence.from_mapping(
                cast(Mapping[str, Any], value["terminal_evidence"])
            ),
            artifacts,
            _digest(
                value["evaluation_seal_digest"],
                path="$.evidence.evaluation_seal_digest",
                code=code,
            ),
            _digest(
                value["compatibility_digest"],
                path="$.evidence.compatibility_digest",
                code=code,
            ),
        )
        _null_authority(
            value["authorized_action"], path="$.evidence.authorized_action", code=code
        )
        return parsed

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_evidence_schema_version": self.claim_evidence_schema_version,
            "origin_id": self.origin_id,
            "origin_digest": self.origin_digest,
            "diagnosis_event": {
                "sequence": self.diagnosis_event_sequence,
                "event_id": self.diagnosis_event_id,
                "event_hash": self.diagnosis_event_hash,
            },
            "diagnosis_id": self.diagnosis_id,
            "diagnosis_digest": self.diagnosis_digest,
            "terminal_evidence": self.terminal_evidence.to_dict(),
            "artifact_evidence": [item.to_dict() for item in self.artifact_evidence],
            "evaluation_seal_digest": self.evaluation_seal_digest,
            "compatibility_digest": self.compatibility_digest,
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class Claim:
    claim_schema_version: int
    claim_id: str
    statement: ClaimStatement
    applicability: ClaimApplicability
    evidence: ClaimEvidenceRef
    claim_status: str
    claim_maturity: str
    limitations: tuple[str, ...]
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "claim_schema_version",
            "claim_id",
            "statement",
            "applicability",
            "evidence",
            "claim_status",
            "claim_maturity",
            "limitations",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> Claim:
        code = "CLAIM_INVALID"
        value = _object(raw, cls._KEYS, path="$", code=code)
        statement = ClaimStatement.from_mapping(cast(Mapping[str, Any], value["statement"]))
        applicability = ClaimApplicability.from_mapping(
            cast(Mapping[str, Any], value["applicability"])
        )
        evidence = ClaimEvidenceRef.from_mapping(cast(Mapping[str, Any], value["evidence"]))
        status = _text(value["claim_status"], path="$.claim_status", code=code)
        maturity = _text(value["claim_maturity"], path="$.claim_maturity", code=code)
        if status != "active":
            raise _error(code, "new Claim status must be literal active", path="$.claim_status")
        if maturity != "observed":
            raise _error(
                code, "new Claim maturity must be literal observed", path="$.claim_maturity"
            )
        raw_limitations = _array(value["limitations"], path="$.limitations", code=code)
        if not 1 <= len(raw_limitations) <= MAX_LIMITATIONS:
            raise _error(
                code,
                f"$.limitations must contain 1 to {MAX_LIMITATIONS} items",
                path="$.limitations",
            )
        limitations = tuple(
            _bounded_text(
                item,
                path=f"$.limitations[{index}]",
                code=code,
                max_utf8_bytes=MAX_LIMITATION_UTF8_BYTES,
            )
            for index, item in enumerate(raw_limitations)
        )
        if len(set(limitations)) != len(limitations):
            raise _error(code, "$.limitations must be unique", path="$.limitations")
        _null_authority(value["authorized_action"], path="$.authorized_action", code=code)
        expected_id = stable_id(
            "claim",
            statement.to_dict(),
            applicability.to_dict(),
            evidence.to_dict(),
            status,
            maturity,
            list(limitations),
        )
        observed_id = _identifier(value["claim_id"], "claim", path="$.claim_id", code=code)
        if observed_id != expected_id:
            raise _error(
                code,
                "claim_id does not match the canonical Claim body",
                path="$.claim_id",
                expected_claim_id=expected_id,
                observed_claim_id=observed_id,
            )
        claim = cls(
            _version(
                value["claim_schema_version"],
                CLAIM_SCHEMA_VERSION,
                path="$.claim_schema_version",
                code=code,
            ),
            observed_id,
            statement,
            applicability,
            evidence,
            status,
            maturity,
            limitations,
        )
        sha256_json(claim.to_dict())
        return claim

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_schema_version": self.claim_schema_version,
            "claim_id": self.claim_id,
            "statement": self.statement.to_dict(),
            "applicability": self.applicability.to_dict(),
            "evidence": self.evidence.to_dict(),
            "claim_status": self.claim_status,
            "claim_maturity": self.claim_maturity,
            "limitations": list(self.limitations),
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class ClaimRelation:
    claim_relation_schema_version: int
    relation_id: str
    relation_type: str
    source_claim_id: str
    target_claim_id: str
    rationale: str
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "claim_relation_schema_version",
            "relation_id",
            "relation_type",
            "source_claim_id",
            "target_claim_id",
            "rationale",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ClaimRelation:
        code = "CLAIM_RELATION_INVALID"
        value = _object(raw, cls._KEYS, path="$", code=code)
        relation_type = _text(value["relation_type"], path="$.relation_type", code=code)
        if relation_type not in CLAIM_RELATION_TYPES:
            raise _error(code, "$.relation_type is unsupported", path="$.relation_type")
        source = _identifier(
            value["source_claim_id"], "claim", path="$.source_claim_id", code=code
        )
        target = _identifier(
            value["target_claim_id"], "claim", path="$.target_claim_id", code=code
        )
        if source == target:
            raise _error(code, "Claim relations cannot be self edges", path="$.target_claim_id")
        rationale = _bounded_text(
            value["rationale"],
            path="$.rationale",
            code=code,
            max_utf8_bytes=MAX_RATIONALE_UTF8_BYTES,
        )
        _null_authority(value["authorized_action"], path="$.authorized_action", code=code)
        expected_id = stable_id("relation", relation_type, source, target, rationale)
        observed_id = _identifier(
            value["relation_id"], "relation", path="$.relation_id", code=code
        )
        if observed_id != expected_id:
            raise _error(
                code,
                "relation_id does not match the canonical relation body",
                path="$.relation_id",
            )
        return cls(
            _version(
                value["claim_relation_schema_version"],
                CLAIM_RELATION_SCHEMA_VERSION,
                path="$.claim_relation_schema_version",
                code=code,
            ),
            observed_id,
            relation_type,
            source,
            target,
            rationale,
        )

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    @property
    def triple(self) -> tuple[str, str, str]:
        return self.relation_type, self.source_claim_id, self.target_claim_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_relation_schema_version": self.claim_relation_schema_version,
            "relation_id": self.relation_id,
            "relation_type": self.relation_type,
            "source_claim_id": self.source_claim_id,
            "target_claim_id": self.target_claim_id,
            "rationale": self.rationale,
            "authorized_action": None,
        }


ClaimRecord: TypeAlias = Claim | ClaimRelation


@dataclass(frozen=True, slots=True)
class ClaimView:
    claim: Claim
    claim_digest: str
    effective_status: str
    effective_maturity: str
    supported_by: tuple[str, ...]
    contradicted_by: tuple[str, ...]
    superseded_by: str | None
    replicated_by: tuple[str, ...]
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "claim",
            "claim_digest",
            "effective_status",
            "effective_maturity",
            "supported_by",
            "contradicted_by",
            "superseded_by",
            "replicated_by",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, index: int) -> ClaimView:
        code = "CLAIM_PROJECTION_INVALID"
        path = f"$.claims[{index}]"
        value = _object(raw, cls._KEYS, path=path, code=code)
        claim = Claim.from_mapping(cast(Mapping[str, Any], value["claim"]))
        digest = _digest(value["claim_digest"], path=f"{path}.claim_digest", code=code)
        if digest != claim.digest:
            raise _error(code, "Claim view digest mismatch", path=f"{path}.claim_digest")
        status = _text(value["effective_status"], path=f"{path}.effective_status", code=code)
        maturity = _text(
            value["effective_maturity"], path=f"{path}.effective_maturity", code=code
        )
        if status not in CLAIM_EFFECTIVE_STATUSES or maturity not in CLAIM_EFFECTIVE_MATURITIES:
            raise _error(code, "Claim view has an unsupported derived state", path=path)

        def relation_ids(field: str) -> tuple[str, ...]:
            items = tuple(
                _identifier(item, "relation", path=f"{path}.{field}[]", code=code)
                for item in _array(value[field], path=f"{path}.{field}", code=code)
            )
            if len(set(items)) != len(items):
                raise _error(code, f"{path}.{field} must be unique", path=f"{path}.{field}")
            return items

        superseded_by_raw = value["superseded_by"]
        superseded_by = (
            None
            if superseded_by_raw is None
            else _identifier(
                superseded_by_raw,
                "relation",
                path=f"{path}.superseded_by",
                code=code,
            )
        )
        _null_authority(value["authorized_action"], path=f"{path}.authorized_action", code=code)
        return cls(
            claim,
            digest,
            status,
            maturity,
            relation_ids("supported_by"),
            relation_ids("contradicted_by"),
            superseded_by,
            relation_ids("replicated_by"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim.to_dict(),
            "claim_digest": self.claim_digest,
            "effective_status": self.effective_status,
            "effective_maturity": self.effective_maturity,
            "supported_by": list(self.supported_by),
            "contradicted_by": list(self.contradicted_by),
            "superseded_by": self.superseded_by,
            "replicated_by": list(self.replicated_by),
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class ClaimSnapshot:
    claim_projection_schema_version: int
    program_id: str
    program_head_sequence: int
    program_head_hash: str
    claims: tuple[ClaimView, ...]
    relations: tuple[ClaimRelation, ...]
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "claim_projection_schema_version",
            "program_id",
            "program_head",
            "claims",
            "relations",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> ClaimSnapshot:
        code = "CLAIM_PROJECTION_INVALID"
        value = _object(raw, cls._KEYS, path="$", code=code)
        _version(
            value["claim_projection_schema_version"],
            CLAIM_PROJECTION_SCHEMA_VERSION,
            path="$.claim_projection_schema_version",
            code=code,
        )
        program_id = _identifier(value["program_id"], "program", path="$.program_id", code=code)
        head = _object(
            value["program_head"], {"sequence", "hash"}, path="$.program_head", code=code
        )
        program_head = (
            _positive_integer(head["sequence"], path="$.program_head.sequence", code=code),
            _digest(head["hash"], path="$.program_head.hash", code=code),
        )
        views = tuple(
            ClaimView.from_mapping(cast(Mapping[str, Any], item), index=index)
            for index, item in enumerate(_array(value["claims"], path="$.claims", code=code))
        )
        relations = tuple(
            ClaimRelation.from_mapping(cast(Mapping[str, Any], item))
            for item in _array(value["relations"], path="$.relations", code=code)
        )
        _null_authority(value["authorized_action"], path="$.authorized_action", code=code)
        expected = reduce_claim_records(
            [*(view.claim for view in views), *relations],
            program_id=program_id,
            program_head=program_head,
        )
        if expected.to_dict() != {
            "claim_projection_schema_version": CLAIM_PROJECTION_SCHEMA_VERSION,
            "program_id": program_id,
            "program_head": {"sequence": program_head[0], "hash": program_head[1]},
            "claims": [view.to_dict() for view in views],
            "relations": [relation.to_dict() for relation in relations],
            "authorized_action": None,
        }:
            raise _error(code, "Claim snapshot does not match deterministic relation replay")
        return expected

    @property
    def program_head(self) -> tuple[int, str]:
        return self.program_head_sequence, self.program_head_hash

    def claim(self, claim_id: str) -> ClaimView | None:
        return next((item for item in self.claims if item.claim.claim_id == claim_id), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_projection_schema_version": self.claim_projection_schema_version,
            "program_id": self.program_id,
            "program_head": {
                "sequence": self.program_head_sequence,
                "hash": self.program_head_hash,
            },
            "claims": [item.to_dict() for item in self.claims],
            "relations": [item.to_dict() for item in self.relations],
            "authorized_action": None,
        }


def _validate_relation_scope(relation: ClaimRelation, source: Claim, target: Claim) -> None:
    source_scope = source.applicability
    target_scope = target.applicability
    compatible = (
        source_scope.hypothesis_class_id == target_scope.hypothesis_class_id
        and source_scope.evaluation_seal_digest == target_scope.evaluation_seal_digest
        and source_scope.compatibility_digest == target_scope.compatibility_digest
    )
    if not compatible:
        raise _error(
            "CLAIM_SCOPE_INCOMPATIBLE",
            "Claim relation endpoints have incompatible class, seal, or compatibility",
            relation_id=relation.relation_id,
        )
    same_identity = source_scope.scope_identity == target_scope.scope_identity
    same_manifest = (
        source_scope.evaluation_scope_manifest_digest
        == target_scope.evaluation_scope_manifest_digest
    )
    if not same_identity and same_manifest:
        raise _error(
            "CLAIM_SCOPE_OVERLAP",
            "distinct scope identities reuse the same manifest digest",
            relation_id=relation.relation_id,
        )
    if relation.relation_type == "replicates":
        independent = (
            source_scope.evaluation_scope_role == "replication"
            and source.evidence.origin_id != target.evidence.origin_id
            and not same_identity
            and not same_manifest
            and source.statement.to_dict() == target.statement.to_dict()
        )
        if not independent:
            raise _error(
                "CLAIM_REPLICATION_NOT_INDEPENDENT",
                "replication requires a distinct replication scope, manifest, and origin",
                relation_id=relation.relation_id,
            )


def reduce_claim_records(
    records: Sequence[ClaimRecord],
    *,
    program_id: str,
    program_head: tuple[int, str],
) -> ClaimSnapshot:
    """Reduce ordered canonical Claim/relation records without mutating Claim bodies."""

    try:
        program_id = validate_namespaced_id(program_id, "program")
    except (TypeError, ValueError) as exc:
        raise _error("CLAIM_PROJECTION_INVALID", "invalid program ID") from exc
    sequence, head_hash = program_head
    if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
        raise _error("CLAIM_PROJECTION_INVALID", "program head sequence must be positive")
    _digest(head_hash, path="$.program_head.hash", code="CLAIM_PROJECTION_INVALID")

    claims: dict[str, Claim] = {}
    relations: list[ClaimRelation] = []
    triples: set[tuple[str, str, str]] = set()
    supports: dict[str, list[str]] = {}
    contradictions: dict[str, list[str]] = {}
    superseded: dict[str, str] = {}
    replications: dict[str, list[str]] = {}

    for supplied in records:
        if isinstance(supplied, Claim):
            claim = Claim.from_mapping(supplied.to_dict())
            if claim.claim_id in claims:
                raise _error("CLAIM_DUPLICATE", "duplicate Claim in ProgramLog")
            claims[claim.claim_id] = claim
            supports[claim.claim_id] = []
            contradictions[claim.claim_id] = []
            replications[claim.claim_id] = []
            continue

        relation = ClaimRelation.from_mapping(supplied.to_dict())
        if relation.triple in triples:
            raise _error(
                "CLAIM_RELATION_DUPLICATE", "duplicate Claim relation triple"
            )
        source = claims.get(relation.source_claim_id)
        target = claims.get(relation.target_claim_id)
        if source is None or target is None:
            raise _error(
                "CLAIM_RELATION_UNKNOWN",
                "Claim relation endpoints must be prior canonical Claims",
            )
        if relation.source_claim_id in superseded or relation.target_claim_id in superseded:
            raise _error(
                "CLAIM_SUPERSESSION_INVALID",
                "superseded Claims cannot participate in a new relation",
            )
        _validate_relation_scope(relation, source, target)

        if relation.relation_type == "supersedes":
            cursor = relation.source_claim_id
            visited: set[str] = set()
            while cursor in superseded:
                if cursor in visited:
                    raise _error(
                        "CLAIM_SUPERSESSION_INVALID", "supersession graph contains a cycle"
                    )
                visited.add(cursor)
                successor_relation_id = superseded[cursor]
                successor_relation = next(
                    item for item in relations if item.relation_id == successor_relation_id
                )
                cursor = successor_relation.source_claim_id
            if cursor == relation.target_claim_id:
                raise _error(
                    "CLAIM_SUPERSESSION_INVALID", "supersession would create a cycle"
                )
            superseded[relation.target_claim_id] = relation.relation_id
        elif relation.relation_type == "supports":
            supports[relation.target_claim_id].append(relation.relation_id)
        elif relation.relation_type == "contradicts":
            contradictions[relation.target_claim_id].append(relation.relation_id)
        elif relation.relation_type == "replicates":
            replications[relation.source_claim_id].append(relation.relation_id)
            replications[relation.target_claim_id].append(relation.relation_id)

        triples.add(relation.triple)
        relations.append(relation)

    views = tuple(
        ClaimView(
            claim=claim,
            claim_digest=claim.digest,
            effective_status=(
                "superseded"
                if claim_id in superseded
                else "contested"
                if contradictions[claim_id]
                else "active"
            ),
            effective_maturity=("replicated" if replications[claim_id] else "observed"),
            supported_by=tuple(supports[claim_id]),
            contradicted_by=tuple(contradictions[claim_id]),
            superseded_by=superseded.get(claim_id),
            replicated_by=tuple(replications[claim_id]),
        )
        for claim_id, claim in claims.items()
    )
    return ClaimSnapshot(
        CLAIM_PROJECTION_SCHEMA_VERSION,
        program_id,
        sequence,
        head_hash,
        views,
        tuple(relations),
    )


def claim_event_payload(claim: Claim | Mapping[str, Any]) -> dict[str, Any]:
    parsed = claim if isinstance(claim, Claim) else Claim.from_mapping(claim)
    return {
        "claim": parsed.to_dict(),
        "claim_digest": parsed.digest,
        "authorized_action": None,
    }


def relation_event_payload(
    relation: ClaimRelation | Mapping[str, Any],
) -> dict[str, Any]:
    parsed = (
        relation if isinstance(relation, ClaimRelation) else ClaimRelation.from_mapping(relation)
    )
    return {
        "claim_relation": parsed.to_dict(),
        "claim_relation_digest": parsed.digest,
        "authorized_action": None,
    }


def claim_from_event_payload(payload: Mapping[str, Any]) -> Claim:
    code = "PROGRAM_LOG_INVALID"
    value = _object(
        payload,
        {"claim", "claim_digest", "authorized_action"},
        path="$.payload",
        code=code,
    )
    _null_authority(value["authorized_action"], path="$.payload.authorized_action", code=code)
    claim = Claim.from_mapping(cast(Mapping[str, Any], value["claim"]))
    observed = _digest(
        value["claim_digest"], path="$.payload.claim_digest", code=code
    )
    if observed != claim.digest:
        raise _error(code, "Claim payload digest mismatch", path="$.payload.claim_digest")
    return claim


def relation_from_event_payload(payload: Mapping[str, Any]) -> ClaimRelation:
    code = "PROGRAM_LOG_INVALID"
    value = _object(
        payload,
        {"claim_relation", "claim_relation_digest", "authorized_action"},
        path="$.payload",
        code=code,
    )
    _null_authority(value["authorized_action"], path="$.payload.authorized_action", code=code)
    relation = ClaimRelation.from_mapping(
        cast(Mapping[str, Any], value["claim_relation"])
    )
    observed = _digest(
        value["claim_relation_digest"],
        path="$.payload.claim_relation_digest",
        code=code,
    )
    if observed != relation.digest:
        raise _error(
            code,
            "Claim relation payload digest mismatch",
            path="$.payload.claim_relation_digest",
        )
    return relation
