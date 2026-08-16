"""Pure deterministic retrieval over one audited ClaimSnapshot."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, cast

from research_os.contracts.common import sha256_json
from research_os.errors import ProgramMemoryError
from research_os.kernel.ids import validate_namespaced_id

from .claims import (
    CLAIM_KINDS,
    CLAIM_SCOPE_ROLES,
    ClaimRelation,
    ClaimSnapshot,
    ClaimView,
)

RETRIEVAL_QUERY_SCHEMA_VERSION = 1
RETRIEVAL_RESULT_SCHEMA_VERSION = 1
ANALOGY_QUERY_SCHEMA_VERSION = 1
ANALOGY_RESULT_SCHEMA_VERSION = 1
MAX_RETRIEVAL_LIMIT = 100
_HASH_LENGTH = 64
_RETRIEVAL_RELATION_TYPES = frozenset({"contradicts"})


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


@dataclass(frozen=True, slots=True)
class RetrievalScope:
    evaluation_scope_id: str
    evaluation_scope_role: str
    evaluation_scope_manifest_digest: str

    _KEYS: ClassVar[frozenset[str]] = frozenset({"id", "role", "manifest_digest"})

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> RetrievalScope:
        code = "RETRIEVAL_QUERY_INVALID"
        value = _object(raw, cls._KEYS, path="$.evaluation_scope", code=code)
        role = _text(value["role"], path="$.evaluation_scope.role", code=code)
        if role not in CLAIM_SCOPE_ROLES:
            raise _error(
                code,
                "$.evaluation_scope.role is unsupported",
                path="$.evaluation_scope.role",
            )
        return cls(
            _text(value["id"], path="$.evaluation_scope.id", code=code),
            role,
            _digest(
                value["manifest_digest"],
                path="$.evaluation_scope.manifest_digest",
                code=code,
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.evaluation_scope_id,
            "role": self.evaluation_scope_role,
            "manifest_digest": self.evaluation_scope_manifest_digest,
        }


@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    retrieval_query_schema_version: int
    query_id: str
    program_id: str
    program_head_sequence: int
    program_head_hash: str
    hypothesis_class_id: str
    compatibility_digest: str
    evaluation_scope: RetrievalScope
    claim_kinds: tuple[str, ...]
    diagnosis_digest: str | None
    relation_types: tuple[str, ...]
    limit: int
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "retrieval_query_schema_version",
            "query_id",
            "program_id",
            "program_head",
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
    def from_mapping(cls, raw: Mapping[str, Any]) -> RetrievalQuery:
        code = "RETRIEVAL_QUERY_INVALID"
        value = _object(raw, cls._KEYS, path="$", code=code)
        version = value["retrieval_query_schema_version"]
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version != RETRIEVAL_QUERY_SCHEMA_VERSION
        ):
            raise _error(code, "unsupported retrieval query schema", path="$.retrieval_query_schema_version")
        head = _object(
            value["program_head"], {"sequence", "hash"}, path="$.program_head", code=code
        )
        sequence = head["sequence"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise _error(code, "program head sequence must be positive", path="$.program_head.sequence")
        kinds = tuple(
            _text(item, path="$.claim_kinds[]", code=code)
            for item in _array(value["claim_kinds"], path="$.claim_kinds", code=code)
        )
        if not kinds or kinds != tuple(sorted(set(kinds))) or any(
            item not in CLAIM_KINDS for item in kinds
        ):
            raise _error(code, "claim_kinds must be non-empty, unique, sorted, and supported")
        relations = tuple(
            _text(item, path="$.relation_types[]", code=code)
            for item in _array(value["relation_types"], path="$.relation_types", code=code)
        )
        if relations != tuple(sorted(set(relations))) or any(
            item not in _RETRIEVAL_RELATION_TYPES for item in relations
        ):
            raise _error(code, "relation_types must be unique, sorted, and supported")
        diagnosis_raw = value["diagnosis_digest"]
        diagnosis = (
            None
            if diagnosis_raw is None
            else _digest(diagnosis_raw, path="$.diagnosis_digest", code=code)
        )
        limit = value["limit"]
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_RETRIEVAL_LIMIT
        ):
            raise _error(code, f"limit must be an integer from 1 to {MAX_RETRIEVAL_LIMIT}")
        if value["authorized_action"] is not None:
            raise _error(code, "authorized_action must be literal null", path="$.authorized_action")
        return cls(
            RETRIEVAL_QUERY_SCHEMA_VERSION,
            _identifier(value["query_id"], "query", path="$.query_id", code=code),
            _identifier(value["program_id"], "program", path="$.program_id", code=code),
            sequence,
            _digest(head["hash"], path="$.program_head.hash", code=code),
            _text(value["hypothesis_class_id"], path="$.hypothesis_class_id", code=code),
            _digest(value["compatibility_digest"], path="$.compatibility_digest", code=code),
            RetrievalScope.from_mapping(cast(Mapping[str, Any], value["evaluation_scope"])),
            kinds,
            diagnosis,
            relations,
            limit,
        )

    @property
    def program_head(self) -> tuple[int, str]:
        return self.program_head_sequence, self.program_head_hash

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "retrieval_query_schema_version": self.retrieval_query_schema_version,
            "query_id": self.query_id,
            "program_id": self.program_id,
            "program_head": {
                "sequence": self.program_head_sequence,
                "hash": self.program_head_hash,
            },
            "hypothesis_class_id": self.hypothesis_class_id,
            "compatibility_digest": self.compatibility_digest,
            "evaluation_scope": self.evaluation_scope.to_dict(),
            "claim_kinds": list(self.claim_kinds),
            "diagnosis_digest": self.diagnosis_digest,
            "relation_types": list(self.relation_types),
            "limit": self.limit,
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class RetrievalHit:
    view: ClaimView
    relation_role: Literal["active", "contradiction"]
    relation_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    order_key: tuple[int, int, int, str]
    authorized_action: None = None

    @property
    def claim_id(self) -> str:
        return self.view.claim.claim_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.view.claim.to_dict(),
            "claim_digest": self.view.claim_digest,
            "effective_status": self.view.effective_status,
            "effective_maturity": self.view.effective_maturity,
            "relation_role": self.relation_role,
            "relation_ids": list(self.relation_ids),
            "reasons": list(self.reasons),
            "order_key": list(self.order_key),
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    retrieval_result_schema_version: int
    query: RetrievalQuery
    active: tuple[RetrievalHit, ...]
    contradictions: tuple[RetrievalHit, ...]
    excluded_superseded_claim_ids: tuple[str, ...]
    candidate_count: int
    matched_before_limit: int
    truncated: bool
    authorized_action: None = None

    @property
    def program_id(self) -> str:
        return self.query.program_id

    @property
    def program_head(self) -> tuple[int, str]:
        return self.query.program_head

    @property
    def returned_claim_ids(self) -> tuple[str, ...]:
        return tuple(item.claim_id for item in (*self.active, *self.contradictions))

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "retrieval_result_schema_version": self.retrieval_result_schema_version,
            "query_digest": self.query.digest,
            "program_id": self.program_id,
            "program_head": {
                "sequence": self.program_head[0],
                "hash": self.program_head[1],
            },
            "active": [item.to_dict() for item in self.active],
            "contradictions": [item.to_dict() for item in self.contradictions],
            "excluded_superseded_claim_ids": list(self.excluded_superseded_claim_ids),
            "candidate_count": self.candidate_count,
            "matched_before_limit": self.matched_before_limit,
            "returned_count": len(self.active) + len(self.contradictions),
            "truncated": self.truncated,
            "authorized_action": None,
        }


def _base_match(view: ClaimView, query: RetrievalQuery) -> bool:
    applicability = view.claim.applicability
    return (
        applicability.hypothesis_class_id == query.hypothesis_class_id
        and applicability.compatibility_digest == query.compatibility_digest
        and view.claim.statement.kind in query.claim_kinds
        and (
            query.diagnosis_digest is None
            or view.claim.evidence.diagnosis_digest == query.diagnosis_digest
        )
    )


def _relation_scope_match(view: ClaimView, query: RetrievalQuery) -> bool:
    applicability = view.claim.applicability
    return (
        applicability.hypothesis_class_id == query.hypothesis_class_id
        and applicability.compatibility_digest == query.compatibility_digest
    )


def _scope_specificity(view: ClaimView, query: RetrievalQuery) -> tuple[int, str]:
    applicability = view.claim.applicability
    scope = query.evaluation_scope
    if (
        applicability.evaluation_scope_id == scope.evaluation_scope_id
        and applicability.evaluation_scope_role == scope.evaluation_scope_role
        and applicability.evaluation_scope_manifest_digest
        == scope.evaluation_scope_manifest_digest
    ):
        return 0, "scope:exact"
    if applicability.evaluation_scope_role == scope.evaluation_scope_role:
        return 1, "scope:same_role"
    return 2, "scope:cross_role"


def _hit(
    view: ClaimView,
    query: RetrievalQuery,
    *,
    role: Literal["active", "contradiction"],
    relations: Sequence[ClaimRelation] = (),
) -> RetrievalHit:
    specificity, scope_reason = _scope_specificity(view, query)
    status_priority = 0 if view.effective_status == "active" else 1
    relation_priority = 0 if role == "active" else 1
    reasons = [
        "program:exact",
        "class:exact",
        "compatibility:exact",
        f"kind:{view.claim.statement.kind}",
        scope_reason,
        f"status:{view.effective_status}",
    ]
    if query.diagnosis_digest is not None and role == "active":
        reasons.append("diagnosis:exact")
    reasons.extend(
        f"relation:{relation.relation_type}:{relation.relation_id}"
        for relation in sorted(relations, key=lambda item: item.relation_id)
    )
    return RetrievalHit(
        view,
        role,
        tuple(sorted(relation.relation_id for relation in relations)),
        tuple(reasons),
        (relation_priority, specificity, status_priority, view.claim.claim_id),
    )


def retrieve_claims(
    snapshot: ClaimSnapshot,
    query: RetrievalQuery | Mapping[str, Any],
) -> RetrievalResult:
    """Select relevant Claims and direct contradictions with a canonical order."""

    if not isinstance(snapshot, ClaimSnapshot):
        raise TypeError("snapshot must be a ClaimSnapshot")
    if not isinstance(query, RetrievalQuery):
        query = RetrievalQuery.from_mapping(query)
    if snapshot.program_id != query.program_id or snapshot.program_head != query.program_head:
        raise _error(
            "RETRIEVAL_STALE",
            "retrieval query does not bind the current Program head",
            expected_program_id=snapshot.program_id,
            expected_program_head=snapshot.program_head,
            observed_program_id=query.program_id,
            observed_program_head=query.program_head,
        )

    views = {item.claim.claim_id: item for item in snapshot.claims}
    base = {claim_id: view for claim_id, view in views.items() if _base_match(view, query)}
    superseded = tuple(
        sorted(
            claim_id
            for claim_id, view in base.items()
            if view.effective_status == "superseded"
        )
    )
    active_ids = {
        claim_id for claim_id, view in base.items() if view.effective_status != "superseded"
    }

    contradiction_edges: dict[str, list[ClaimRelation]] = {}
    for relation in snapshot.relations:
        if (
            relation.relation_type in query.relation_types
            and relation.target_claim_id in active_ids
        ):
            source = views[relation.source_claim_id]
            if (
                source.effective_status != "superseded"
                and _relation_scope_match(source, query)
            ):
                contradiction_edges.setdefault(relation.source_claim_id, []).append(relation)
    active_ids.difference_update(contradiction_edges)

    hits = [
        *(_hit(base[claim_id], query, role="active") for claim_id in active_ids),
        *(
            _hit(
                views[claim_id],
                query,
                role="contradiction",
                relations=relations,
            )
            for claim_id, relations in contradiction_edges.items()
        ),
    ]
    hits.sort(key=lambda item: item.order_key)
    selected = hits[: query.limit]
    return RetrievalResult(
        RETRIEVAL_RESULT_SCHEMA_VERSION,
        query,
        tuple(item for item in selected if item.relation_role == "active"),
        tuple(item for item in selected if item.relation_role == "contradiction"),
        superseded,
        len(snapshot.claims),
        len(hits),
        len(hits) > query.limit,
    )


@dataclass(frozen=True, slots=True)
class AnalogyQuery:
    """A deliberately cross-frame query over the same audited ClaimSnapshot.

    This is a distinct type from :class:`RetrievalQuery` on purpose.  Canonical
    registration binds a proposal to a ``RetrievalQuery`` whose
    ``hypothesis_class_id`` must equal the proposal's class, so an advisory
    analogy read cannot be substituted for confirmatory retrieval by accident.
    The excluded-field names below make an accidental swap fail loudly rather
    than silently widen canonical evidence.
    """

    analogy_query_schema_version: int
    query_id: str
    program_id: str
    program_head_sequence: int
    program_head_hash: str
    excluded_hypothesis_class_id: str
    excluded_compatibility_digest: str
    claim_kinds: tuple[str, ...]
    limit: int
    authorized_action: None = None

    _KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "analogy_query_schema_version",
            "query_id",
            "program_id",
            "program_head",
            "excluded_hypothesis_class_id",
            "excluded_compatibility_digest",
            "claim_kinds",
            "limit",
            "authorized_action",
        }
    )

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> AnalogyQuery:
        code = "ANALOGY_QUERY_INVALID"
        value = _object(raw, cls._KEYS, path="$", code=code)
        version = value["analogy_query_schema_version"]
        if (
            isinstance(version, bool)
            or not isinstance(version, int)
            or version != ANALOGY_QUERY_SCHEMA_VERSION
        ):
            raise _error(
                code,
                "unsupported analogy query schema",
                path="$.analogy_query_schema_version",
            )
        head = _object(
            value["program_head"], {"sequence", "hash"}, path="$.program_head", code=code
        )
        sequence = head["sequence"]
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 1:
            raise _error(
                code,
                "program head sequence must be positive",
                path="$.program_head.sequence",
            )
        kinds = tuple(
            _text(item, path="$.claim_kinds[]", code=code)
            for item in _array(value["claim_kinds"], path="$.claim_kinds", code=code)
        )
        if not kinds or kinds != tuple(sorted(set(kinds))) or any(
            item not in CLAIM_KINDS for item in kinds
        ):
            raise _error(code, "claim_kinds must be non-empty, unique, sorted, and supported")
        limit = value["limit"]
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= MAX_RETRIEVAL_LIMIT
        ):
            raise _error(code, f"limit must be an integer from 1 to {MAX_RETRIEVAL_LIMIT}")
        if value["authorized_action"] is not None:
            raise _error(code, "authorized_action must be literal null", path="$.authorized_action")
        return cls(
            ANALOGY_QUERY_SCHEMA_VERSION,
            _identifier(value["query_id"], "query", path="$.query_id", code=code),
            _identifier(value["program_id"], "program", path="$.program_id", code=code),
            sequence,
            _digest(head["hash"], path="$.program_head.hash", code=code),
            _text(
                value["excluded_hypothesis_class_id"],
                path="$.excluded_hypothesis_class_id",
                code=code,
            ),
            _digest(
                value["excluded_compatibility_digest"],
                path="$.excluded_compatibility_digest",
                code=code,
            ),
            kinds,
            limit,
        )

    @property
    def program_head(self) -> tuple[int, str]:
        return self.program_head_sequence, self.program_head_hash

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "analogy_query_schema_version": self.analogy_query_schema_version,
            "query_id": self.query_id,
            "program_id": self.program_id,
            "program_head": {
                "sequence": self.program_head_sequence,
                "hash": self.program_head_hash,
            },
            "excluded_hypothesis_class_id": self.excluded_hypothesis_class_id,
            "excluded_compatibility_digest": self.excluded_compatibility_digest,
            "claim_kinds": list(self.claim_kinds),
            "limit": self.limit,
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class AnalogyHit:
    """One cross-frame claim, permanently marked advisory.

    ``source_generation_id`` and ``source_compatibility_digest`` are carried so
    that a hit can be quoted directly as an advisory exhaustion signal without
    a lossy conversion step.
    """

    view: ClaimView
    distance: str
    reasons: tuple[str, ...]
    order_key: tuple[int, int, str]
    lane: ClassVar[Literal["advisory"]] = "advisory"
    authorized_action: None = None

    @property
    def claim_id(self) -> str:
        return self.view.claim.claim_id

    def to_dict(self) -> dict[str, Any]:
        applicability = self.view.claim.applicability
        return {
            "claim": self.view.claim.to_dict(),
            "claim_digest": self.view.claim_digest,
            "effective_status": self.view.effective_status,
            "effective_maturity": self.view.effective_maturity,
            "lane": self.lane,
            "distance": self.distance,
            "source_generation_id": applicability.generation_id,
            "source_hypothesis_class_id": applicability.hypothesis_class_id,
            "source_compatibility_digest": applicability.compatibility_digest,
            "reasons": list(self.reasons),
            "order_key": list(self.order_key),
            "authorized_action": None,
        }


@dataclass(frozen=True, slots=True)
class AnalogyResult:
    analogy_result_schema_version: int
    query: AnalogyQuery
    hits: tuple[AnalogyHit, ...]
    excluded_superseded_claim_ids: tuple[str, ...]
    candidate_count: int
    matched_before_limit: int
    truncated: bool
    lane: ClassVar[Literal["advisory"]] = "advisory"
    authorized_action: None = None

    @property
    def program_id(self) -> str:
        return self.query.program_id

    @property
    def program_head(self) -> tuple[int, str]:
        return self.query.program_head

    @property
    def returned_claim_ids(self) -> tuple[str, ...]:
        return tuple(item.claim_id for item in self.hits)

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "analogy_result_schema_version": self.analogy_result_schema_version,
            "query_digest": self.query.digest,
            "program_id": self.program_id,
            "program_head": {
                "sequence": self.program_head[0],
                "hash": self.program_head[1],
            },
            "lane": self.lane,
            "hits": [item.to_dict() for item in self.hits],
            "excluded_superseded_claim_ids": list(self.excluded_superseded_claim_ids),
            "candidate_count": self.candidate_count,
            "matched_before_limit": self.matched_before_limit,
            "returned_count": len(self.hits),
            "truncated": self.truncated,
            "authorized_action": None,
        }


def _analogy_distance(view: ClaimView, query: AnalogyQuery) -> tuple[int, str] | None:
    """Rank how far a claim sits from the query's frame, or reject same-frame.

    Rank 0 is cross-class material inside the same compatibility digest, which
    is the most directly comparable analogy source.  Rank 1 is the same class
    seen under a different compatibility digest.  Rank 2 differs on both axes.
    A claim matching the query on both axes is same-frame canonical material and
    is never returned here.
    """

    applicability = view.claim.applicability
    same_class = applicability.hypothesis_class_id == query.excluded_hypothesis_class_id
    same_compatibility = (
        applicability.compatibility_digest == query.excluded_compatibility_digest
    )
    if same_class and same_compatibility:
        return None
    if same_compatibility:
        return 0, "distance:cross_class"
    if same_class:
        return 1, "distance:cross_compatibility"
    return 2, "distance:cross_class_and_compatibility"


def retrieve_analogies(
    snapshot: ClaimSnapshot,
    query: AnalogyQuery | Mapping[str, Any],
) -> AnalogyResult:
    """Select cross-frame Claims as advisory material with a canonical order.

    This never returns a claim from the query's own class and compatibility
    digest, so it cannot restate canonical same-frame evidence in an advisory
    wrapper.  Superseded claims are excluded and reported, matching
    :func:`retrieve_claims`.
    """

    if not isinstance(snapshot, ClaimSnapshot):
        raise TypeError("snapshot must be a ClaimSnapshot")
    if not isinstance(query, AnalogyQuery):
        query = AnalogyQuery.from_mapping(query)
    if snapshot.program_id != query.program_id or snapshot.program_head != query.program_head:
        raise _error(
            "ANALOGY_STALE",
            "analogy query does not bind the current Program head",
            expected_program_id=snapshot.program_id,
            expected_program_head=snapshot.program_head,
            observed_program_id=query.program_id,
            observed_program_head=query.program_head,
        )

    superseded: list[str] = []
    hits: list[AnalogyHit] = []
    for view in snapshot.claims:
        if view.claim.statement.kind not in query.claim_kinds:
            continue
        ranked = _analogy_distance(view, query)
        if ranked is None:
            continue
        if view.effective_status == "superseded":
            superseded.append(view.claim.claim_id)
            continue
        rank, distance = ranked
        status_priority = 0 if view.effective_status == "active" else 1
        hits.append(
            AnalogyHit(
                view,
                distance,
                (
                    "program:exact",
                    "lane:advisory",
                    distance,
                    f"kind:{view.claim.statement.kind}",
                    f"status:{view.effective_status}",
                ),
                (rank, status_priority, view.claim.claim_id),
            )
        )

    hits.sort(key=lambda item: item.order_key)
    selected = hits[: query.limit]
    return AnalogyResult(
        ANALOGY_RESULT_SCHEMA_VERSION,
        query,
        tuple(selected),
        tuple(sorted(superseded)),
        len(snapshot.claims),
        len(hits),
        len(hits) > query.limit,
    )


__all__ = [
    "ANALOGY_QUERY_SCHEMA_VERSION",
    "ANALOGY_RESULT_SCHEMA_VERSION",
    "MAX_RETRIEVAL_LIMIT",
    "RETRIEVAL_QUERY_SCHEMA_VERSION",
    "RETRIEVAL_RESULT_SCHEMA_VERSION",
    "AnalogyHit",
    "AnalogyQuery",
    "AnalogyResult",
    "RetrievalHit",
    "RetrievalQuery",
    "RetrievalResult",
    "RetrievalScope",
    "retrieve_analogies",
    "retrieve_claims",
]
