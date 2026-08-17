"""The advisory analogy lane returns cross-frame material and nothing else."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from research_os.errors import ProgramMemoryError
from research_os.memory.claims import ClaimSnapshot
from research_os.memory.retrieval import (
    AnalogyQuery,
    AnalogyResult,
    RetrievalQuery,
    RetrievalResult,
    retrieve_analogies,
    retrieve_claims,
)
from tests.test_m2c_deterministic_retrieval import ORACLE, _oracle_snapshot

_ACTIVE_CLASS = "class-a"
_ACTIVE_COMPATIBILITY = next(
    item["compatibility_digest"]
    for item in ORACLE["candidates"]
    if item["claim_id"] == "claim_01_exact_active"
)


def _analogy_query(snapshot: ClaimSnapshot, **overrides: Any) -> dict[str, Any]:
    raw = {
        "analogy_query_schema_version": 1,
        "query_id": "query_analogy_lane",
        "program_id": snapshot.program_id,
        "program_head": {
            "sequence": snapshot.program_head[0],
            "hash": snapshot.program_head[1],
        },
        "excluded_hypothesis_class_id": _ACTIVE_CLASS,
        "excluded_compatibility_digest": _ACTIVE_COMPATIBILITY,
        "claim_kinds": ["effect"],
        "limit": 10,
        "authorized_action": None,
    }
    raw.update(overrides)
    return raw


def test_analogy_lane_returns_only_cross_frame_claims() -> None:
    snapshot, aliases = _oracle_snapshot()
    result = retrieve_analogies(snapshot, _analogy_query(snapshot))

    returned = {aliases[claim_id] for claim_id in result.returned_claim_ids}
    assert returned == {"claim_07_wrong_class", "claim_08_wrong_compatibility"}


def test_analogy_lane_orders_cross_class_before_cross_compatibility() -> None:
    snapshot, aliases = _oracle_snapshot()
    result = retrieve_analogies(snapshot, _analogy_query(snapshot))

    ordered = [aliases[hit.claim_id] for hit in result.hits]
    assert ordered == ["claim_07_wrong_class", "claim_08_wrong_compatibility"]
    assert [hit.distance for hit in result.hits] == [
        "distance:cross_class",
        "distance:cross_compatibility",
    ]


def test_analogy_lane_never_returns_same_frame_material() -> None:
    snapshot, aliases = _oracle_snapshot()
    result = retrieve_analogies(snapshot, _analogy_query(snapshot))

    for hit in result.hits:
        applicability = hit.view.claim.applicability
        same_frame = (
            applicability.hypothesis_class_id == _ACTIVE_CLASS
            and applicability.compatibility_digest == _ACTIVE_COMPATIBILITY
        )
        assert not same_frame, aliases[hit.claim_id]


def test_every_analogy_hit_is_marked_advisory_with_its_source_frame() -> None:
    snapshot, _ = _oracle_snapshot()
    result = retrieve_analogies(snapshot, _analogy_query(snapshot))
    body = result.to_dict()

    assert body["lane"] == "advisory"
    assert body["authorized_action"] is None
    for hit in body["hits"]:
        assert hit["lane"] == "advisory"
        assert hit["authorized_action"] is None
        # An advisory exhaustion signal needs exactly these two fields, so a hit
        # must be quotable without a lossy conversion step.
        assert hit["source_generation_id"]
        assert hit["source_compatibility_digest"]


def test_analogy_result_is_not_a_retrieval_result() -> None:
    snapshot, _ = _oracle_snapshot()
    result = retrieve_analogies(snapshot, _analogy_query(snapshot))

    # Canonical registration binds a RetrievalQuery whose hypothesis_class_id
    # must equal the proposal's class.  Keeping these types disjoint is what
    # makes an advisory read structurally unusable as confirmatory evidence.
    assert isinstance(result, AnalogyResult)
    assert not isinstance(result, RetrievalResult)
    assert not issubclass(AnalogyResult, RetrievalResult)
    assert not issubclass(AnalogyQuery, RetrievalQuery)
    # The query does not even carry the field canonical binding reads, so an
    # accidental swap fails on a missing attribute rather than widening evidence.
    assert not hasattr(result.query, "hypothesis_class_id")
    assert "hypothesis_class_id" not in result.query.to_dict()


def test_analogy_query_rejects_a_retrieval_query_body() -> None:
    snapshot, _ = _oracle_snapshot()
    retrieval_body = {
        "retrieval_query_schema_version": 1,
        "query_id": "query_swap_attempt",
        "program_id": snapshot.program_id,
        "program_head": {
            "sequence": snapshot.program_head[0],
            "hash": snapshot.program_head[1],
        },
        "hypothesis_class_id": _ACTIVE_CLASS,
        "compatibility_digest": _ACTIVE_COMPATIBILITY,
        "evaluation_scope": {
            "id": "scope",
            "role": "holdout",
            "manifest_digest": "0" * 64,
        },
        "claim_kinds": ["effect"],
        "diagnosis_digest": None,
        "relation_types": [],
        "limit": 5,
        "authorized_action": None,
    }
    with pytest.raises(ProgramMemoryError) as excinfo:
        retrieve_analogies(snapshot, retrieval_body)
    assert excinfo.value.code == "ANALOGY_QUERY_INVALID"


def test_analogy_query_rejects_non_null_authority() -> None:
    snapshot, _ = _oracle_snapshot()
    with pytest.raises(ProgramMemoryError) as excinfo:
        retrieve_analogies(snapshot, _analogy_query(snapshot, authorized_action="deploy"))
    assert excinfo.value.code == "ANALOGY_QUERY_INVALID"


def test_analogy_query_must_bind_the_current_program_head() -> None:
    snapshot, _ = _oracle_snapshot()
    stale = _analogy_query(snapshot)
    stale["program_head"] = {
        "sequence": snapshot.program_head[0] + 1,
        "hash": snapshot.program_head[1],
    }
    with pytest.raises(ProgramMemoryError) as excinfo:
        retrieve_analogies(snapshot, stale)
    assert excinfo.value.code == "ANALOGY_STALE"


def test_analogy_lane_is_deterministic_and_truncates_explicitly() -> None:
    snapshot, _ = _oracle_snapshot()
    first = retrieve_analogies(snapshot, _analogy_query(snapshot))
    reordered, _ = _oracle_snapshot(
        candidate_order=list(reversed(list({item["claim_id"]: None for item in ORACLE["candidates"]})))
    )
    second = retrieve_analogies(reordered, _analogy_query(reordered))
    assert first.digest == second.digest

    limited = retrieve_analogies(snapshot, _analogy_query(snapshot, limit=1))
    assert limited.truncated is True
    assert limited.matched_before_limit == 2
    assert len(limited.hits) == 1


def test_canonical_retrieval_is_unchanged_by_the_analogy_lane() -> None:
    snapshot, aliases = _oracle_snapshot()
    case = copy.deepcopy(ORACLE["queries"][0])
    query = RetrievalQuery.from_mapping(
        {
            "retrieval_query_schema_version": 1,
            "query_id": "query_" + case["query_id"],
            "program_id": snapshot.program_id,
            "program_head": {
                "sequence": snapshot.program_head[0],
                "hash": snapshot.program_head[1],
            },
            **case["query"],
            "authorized_action": None,
        }
    )
    before = retrieve_claims(snapshot, query)
    retrieve_analogies(snapshot, _analogy_query(snapshot))
    after = retrieve_claims(snapshot, query)

    assert before.digest == after.digest
    for hit in after.active:
        assert aliases[hit.claim_id] != "claim_07_wrong_class"
        assert aliases[hit.claim_id] != "claim_08_wrong_compatibility"
