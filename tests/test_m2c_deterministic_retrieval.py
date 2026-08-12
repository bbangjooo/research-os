from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from research_os.agent import (
    build_agent_context_v3,
    validate_agent_context_v3_retrieval,
)
from research_os.contracts.common import canonical_json_bytes, sha256_json
from research_os.errors import ProgramMemoryError, StaleAgentContextError
from research_os.kernel._canonical import canonical_bytes
from research_os.kernel.events import Event, EventLog
from research_os.kernel.ids import stable_id
from research_os.memory.claims import Claim, ClaimRelation, ClaimSnapshot, ClaimView
from research_os.memory.program import OriginEvidenceRef, ProgramManifest, ProgramStore
from research_os.memory.retrieval import RetrievalQuery, retrieve_claims

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "program_memory" / "retrieval-v1.json"
M2B_FIXTURE = ROOT / "tests" / "fixtures" / "program_memory" / "v2" / "claims-manifest.json"
M2A_FIXTURE = ROOT / "tests" / "fixtures" / "program_memory" / "v1" / "manifest.json"
M1D_ROOT = ROOT / "tests" / "fixtures" / "scientific_state" / "v3"
FROZEN_SHA256 = "dd638da527cae0aa7f035473507a0d07f1d53ba3679066bfbbee88ac16514d81"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


ORACLE = _json(FIXTURE)
M2B = _json(M2B_FIXTURE)
M2A = _json(M2A_FIXTURE)
CANDIDATES = {item["claim_id"]: item for item in ORACLE["candidates"]}
RELATIONS = {item["relation_id"]: item for item in ORACLE["relations"]}


def _canonical_claim(candidate: dict[str, Any]) -> Claim:
    template = Claim.from_mapping(copy.deepcopy(M2B["fixtures"]["valid_claim"]))
    scope = candidate["evaluation_scope"]
    scope_digest = sha256_json(
        {"evaluation_scope_schema_version": 1, "evaluation_scope": scope}
    )
    statement = replace(template.statement, kind=candidate["claim_kind"])
    applicability = replace(
        template.applicability,
        hypothesis_class_id=candidate["hypothesis_class_id"],
        evaluation_scope_id=scope["id"],
        evaluation_scope_role=scope["role"],
        evaluation_scope_manifest_digest=scope["manifest_digest"],
        evaluation_scope_digest=scope_digest,
        compatibility_digest=candidate["compatibility_digest"],
    )
    evidence = replace(
        template.evidence,
        diagnosis_digest=candidate["diagnosis_digest"],
        compatibility_digest=candidate["compatibility_digest"],
    )
    claim = replace(
        template,
        claim_id="claim_placeholder",
        statement=statement,
        applicability=applicability,
        evidence=evidence,
        limitations=(f"Frozen retrieval limitation for {candidate['claim_id']}.",),
    )
    claim_id = stable_id(
        "claim",
        claim.statement.to_dict(),
        claim.applicability.to_dict(),
        claim.evidence.to_dict(),
        claim.claim_status,
        claim.claim_maturity,
        list(claim.limitations),
    )
    return replace(claim, claim_id=claim_id)


def _oracle_snapshot(
    candidate_order: list[str] | None = None,
) -> tuple[ClaimSnapshot, dict[str, str]]:
    order = candidate_order or list(CANDIDATES)
    claims = {alias: _canonical_claim(CANDIDATES[alias]) for alias in CANDIDATES}
    aliases_by_id = {claim.claim_id: alias for alias, claim in claims.items()}
    relations: list[ClaimRelation] = []
    for relation in ORACLE["relations"]:
        relations.append(
            ClaimRelation(
                1,
                relation["relation_id"],
                relation["relation_type"],
                claims[relation["source_claim_id"]].claim_id,
                claims[relation["target_claim_id"]].claim_id,
                f"Frozen retrieval {relation['relation_type']} witness.",
            )
        )
    relation_by_alias = {
        alias: next(item for item in relations if item.relation_id == alias)
        for alias in RELATIONS
    }
    views = []
    for alias in order:
        candidate = CANDIDATES[alias]
        claim = claims[alias]
        views.append(
            ClaimView(
                claim,
                claim.digest,
                candidate["effective_status"],
                candidate["effective_maturity"],
                (
                    (relation_by_alias["relation_03_supports"].relation_id,)
                    if alias == "claim_01_exact_active"
                    else ()
                ),
                (
                    (relation_by_alias["relation_01_contradicts"].relation_id,)
                    if alias == "claim_03_exact_contested"
                    else ()
                ),
                (
                    relation_by_alias["relation_02_supersedes"].relation_id
                    if alias == "claim_05_superseded"
                    else None
                ),
                (),
            )
        )
    program = ORACLE["program"]
    head = program["program_head"]
    return (
        ClaimSnapshot(
            1,
            program["program_id"],
            head["sequence"],
            head["hash"],
            tuple(views),
            tuple(relations),
        ),
        aliases_by_id,
    )


def _query(raw_case: dict[str, Any], snapshot: ClaimSnapshot) -> RetrievalQuery:
    query = raw_case["query"]
    return RetrievalQuery.from_mapping(
        {
            "retrieval_query_schema_version": 1,
            "query_id": "query_" + raw_case["query_id"],
            "program_id": snapshot.program_id,
            "program_head": {
                "sequence": snapshot.program_head[0],
                "hash": snapshot.program_head[1],
            },
            **copy.deepcopy(query),
            "authorized_action": None,
        }
    )


def _aliases(items: tuple[Any, ...], aliases_by_id: dict[str, str]) -> list[str]:
    return [aliases_by_id[item.claim_id] for item in items]


def oracle_receipt() -> dict[str, Any]:
    cases = []
    totals = {
        "relevant_expected": 0,
        "relevant_true_positive": 0,
        "contradiction_expected": 0,
        "contradiction_true_positive": 0,
        "superseded_expected": 0,
        "superseded_leak": 0,
        "returned": 0,
        "irrelevant_false_positive": 0,
    }
    for raw_case in ORACLE["queries"]:
        snapshot, aliases_by_id = _oracle_snapshot(raw_case["candidate_claim_ids"])
        result = retrieve_claims(snapshot, _query(raw_case, snapshot))
        active = _aliases(result.active, aliases_by_id)
        contradictions = _aliases(result.contradictions, aliases_by_id)
        superseded = [aliases_by_id[item] for item in result.excluded_superseded_claim_ids]
        returned = set((*active, *contradictions))
        expected_active = raw_case["expected_active_claim_ids"]
        expected_contradictions = raw_case["expected_contradiction_claim_ids"]
        expected_superseded = raw_case["expected_superseded_claim_ids"]
        expected_irrelevant = raw_case["expected_irrelevant_claim_ids"]
        record = {
            "query_id": raw_case["query_id"],
            "expected_active": len(expected_active),
            "returned_active": len(active),
            "active_true_positive": len(set(active) & set(expected_active)),
            "active_false_negative": len(set(expected_active) - set(active)),
            "expected_contradictions": len(expected_contradictions),
            "returned_contradictions": len(contradictions),
            "contradiction_true_positive": len(
                set(contradictions) & set(expected_contradictions)
            ),
            "contradiction_false_negative": len(
                set(expected_contradictions) - set(contradictions)
            ),
            "expected_superseded": len(expected_superseded),
            "superseded_leak": len(returned & set(expected_superseded)),
            "irrelevant_false_positive": len(returned & set(expected_irrelevant)),
            "ordered_active_exact": active == expected_active,
            "ordered_contradictions_exact": contradictions == expected_contradictions,
            "excluded_superseded_exact": superseded == expected_superseded,
            "expected_empty_exact": bool(expected_active or expected_contradictions)
            or not returned,
            "truncated": result.truncated,
        }
        cases.append(record)
        totals["relevant_expected"] += len(expected_active)
        totals["relevant_true_positive"] += record["active_true_positive"]
        totals["contradiction_expected"] += len(expected_contradictions)
        totals["contradiction_true_positive"] += record[
            "contradiction_true_positive"
        ]
        totals["superseded_expected"] += len(expected_superseded)
        totals["superseded_leak"] += record["superseded_leak"]
        totals["returned"] += len(returned)
        totals["irrelevant_false_positive"] += record["irrelevant_false_positive"]
    return {
        "receipt_schema_version": 1,
        "fixture_sha256": hashlib.sha256(FIXTURE.read_bytes()).hexdigest(),
        "queries": cases,
        "metrics": {
            **totals,
            "relevant_recall_percent": 100
            * totals["relevant_true_positive"]
            / totals["relevant_expected"],
            "contradiction_recall_percent": 100
            * totals["contradiction_true_positive"]
            / totals["contradiction_expected"],
            "superseded_exclusion_percent": 100
            * (totals["superseded_expected"] - totals["superseded_leak"])
            / totals["superseded_expected"],
            "irrelevant_contamination_percent": 100
            * totals["irrelevant_false_positive"]
            / totals["returned"],
        },
        "authority": {"authorized_action": None},
    }


def test_frozen_oracle_exact_order_metrics_empty_and_shuffle() -> None:
    receipt = oracle_receipt()
    assert receipt["fixture_sha256"] == FROZEN_SHA256
    assert receipt["metrics"] == {
        "relevant_expected": 11,
        "relevant_true_positive": 11,
        "contradiction_expected": 3,
        "contradiction_true_positive": 3,
        "superseded_expected": 2,
        "superseded_leak": 0,
        "returned": 14,
        "irrelevant_false_positive": 0,
        "relevant_recall_percent": 100.0,
        "contradiction_recall_percent": 100.0,
        "superseded_exclusion_percent": 100.0,
        "irrelevant_contamination_percent": 0.0,
    }
    assert all(
        item["ordered_active_exact"]
        and item["ordered_contradictions_exact"]
        and item["excluded_superseded_exact"]
        and item["expected_empty_exact"]
        and not item["truncated"]
        for item in receipt["queries"]
    )
    assert receipt["queries"][0] | {"query_id": "shuffled-broad-class-scope"} == (
        receipt["queries"][3]
    )


def _broad_snapshot_query() -> tuple[ClaimSnapshot, RetrievalQuery, dict[str, str]]:
    raw_case = ORACLE["queries"][0]
    snapshot, aliases = _oracle_snapshot(raw_case["candidate_claim_ids"])
    return snapshot, _query(raw_case, snapshot), aliases


def test_query_is_strict_and_stale_head_fails_closed() -> None:
    snapshot, query, _ = _broad_snapshot_query()
    mutations = []
    extra = query.to_dict()
    extra["extra"] = True
    mutations.append(extra)
    boolean_limit = query.to_dict()
    boolean_limit["limit"] = True
    mutations.append(boolean_limit)
    unsorted = query.to_dict()
    unsorted["claim_kinds"] = ["invariance", "effect"]
    mutations.append(unsorted)
    authority = query.to_dict()
    authority["authorized_action"] = "trade"
    mutations.append(authority)
    boolean_version = query.to_dict()
    boolean_version["retrieval_query_schema_version"] = True
    mutations.append(boolean_version)
    for raw in mutations:
        with pytest.raises(ProgramMemoryError) as caught:
            RetrievalQuery.from_mapping(raw)
        assert caught.value.code == "RETRIEVAL_QUERY_INVALID"
    stale = replace(query, program_head_sequence=query.program_head_sequence + 1)
    with pytest.raises(ProgramMemoryError) as caught:
        retrieve_claims(snapshot, stale)
    assert caught.value.code == "RETRIEVAL_STALE"


def test_relation_expansion_boundaries_are_one_factor_and_deduplicated() -> None:
    snapshot, broad, aliases = _broad_snapshot_query()
    no_relations = replace(broad, relation_types=())
    observed = retrieve_claims(snapshot, no_relations)
    assert observed.contradictions == ()
    assert "claim_04_contradiction" in _aliases(observed.active, aliases)

    exact_case = ORACLE["queries"][1]
    exact = _query(exact_case, snapshot)
    contradiction = snapshot.relations[0]
    reverse = replace(
        contradiction,
        source_claim_id=contradiction.target_claim_id,
        target_claim_id=contradiction.source_claim_id,
    )
    reversed_result = retrieve_claims(replace(snapshot, relations=(reverse,)), exact)
    assert _aliases(reversed_result.active, aliases) == ["claim_03_exact_contested"]
    assert reversed_result.contradictions == ()

    target_irrelevant = replace(exact, diagnosis_digest="1" * 64)
    irrelevant_result = retrieve_claims(snapshot, target_irrelevant)
    assert _aliases(irrelevant_result.active, aliases) == ["claim_01_exact_active"]
    assert irrelevant_result.contradictions == ()

    source_id = contradiction.source_claim_id
    source_index = next(
        index for index, view in enumerate(snapshot.claims) if view.claim.claim_id == source_id
    )
    source = snapshot.claims[source_index]
    superseded_source = replace(source, effective_status="superseded")
    views = list(snapshot.claims)
    views[source_index] = superseded_source
    superseded_result = retrieve_claims(replace(snapshot, claims=tuple(views)), exact)
    assert superseded_result.contradictions == ()

    duplicate = replace(contradiction, relation_id="relation_duplicate_endpoint")
    duplicate_result = retrieve_claims(
        replace(snapshot, relations=(*snapshot.relations, duplicate)), exact
    )
    assert len(duplicate_result.contradictions) == 1
    assert len(duplicate_result.contradictions[0].relation_ids) == 2

    for field, value in (("hypothesis_class_id", "class-b"), ("compatibility_digest", "e" * 64)):
        changed_applicability = replace(source.claim.applicability, **{field: value})
        changed_claim = replace(source.claim, applicability=changed_applicability)
        changed_view = replace(source, claim=changed_claim, claim_digest=changed_claim.digest)
        views = list(snapshot.claims)
        views[source_index] = changed_view
        mismatch = retrieve_claims(replace(snapshot, claims=tuple(views)), exact)
        assert mismatch.contradictions == ()


def _supported_history() -> list[dict[str, Any]]:
    terminal = _json(M1D_ROOT / "m1d-terminal-corpus.json")
    valid = _json(M1D_ROOT / "m1d-diagnosis-valid.json")
    diagnosis_case = next(item for item in valid["cases"] if item["id"] == "supported")
    terminal_record = next(
        item
        for item in terminal["records"]
        if item["id"] == diagnosis_case["terminal_record_id"]
    )
    return copy.deepcopy([*terminal_record["canonical_history"], diagnosis_case["diagnosis_event"]])


def _real_program(root: Path) -> tuple[ProgramStore, EventLog, Any, list[Claim]]:
    project_path = root / "project-events.jsonl"
    project_path.write_bytes(
        b"".join(
            canonical_bytes(Event.from_mapping(item).to_dict()) + b"\n"
            for item in _supported_history()
        )
    )
    project_path.chmod(0o600)
    project_log = EventLog(project_path, M2A["fixtures"]["project_id"])
    manifest = ProgramManifest.from_mapping(
        {
            "program_manifest_schema_version": 1,
            "program_id": M2A["fixtures"]["program_id"],
            "bindings": [copy.deepcopy(M2A["fixtures"]["binding"])],
            "authorized_action": None,
        }
    )
    store = ProgramStore(root / "program", manifest.program_id)
    head = store.initialize(manifest, {project_log.project_id: project_log})
    head = store.append_origin(
        OriginEvidenceRef.from_mapping(copy.deepcopy(M2A["fixtures"]["origin"])),
        project_log,
        expected_program_head=(head.sequence, head.hash),
    )
    claims = []
    for index in range(2):
        raw = copy.deepcopy(M2B["fixtures"]["valid_claim"])
        raw["statement"]["summary"] = f"Real retrieval vertical claim {index}."
        raw["claim_id"] = stable_id(
            "claim",
            raw["statement"],
            raw["applicability"],
            raw["evidence"],
            raw["claim_status"],
            raw["claim_maturity"],
            raw["limitations"],
        )
        claim = Claim.from_mapping(raw)
        head = store.append_claim(
            claim,
            project_log,
            expected_program_head=(head.sequence, head.hash),
        )
        claims.append(claim)
    relation_raw = {
        "claim_relation_schema_version": 1,
        "relation_id": stable_id(
            "relation",
            "contradicts",
            claims[1].claim_id,
            claims[0].claim_id,
            "Real retrieval contradiction.",
        ),
        "relation_type": "contradicts",
        "source_claim_id": claims[1].claim_id,
        "target_claim_id": claims[0].claim_id,
        "rationale": "Real retrieval contradiction.",
        "authorized_action": None,
    }
    head = store.append_relation(
        ClaimRelation.from_mapping(relation_raw),
        expected_program_head=(head.sequence, head.hash),
    )
    return store, project_log, head, claims


def _real_query(snapshot: ClaimSnapshot, claim: Claim) -> RetrievalQuery:
    applicability = claim.applicability
    return RetrievalQuery.from_mapping(
        {
            "retrieval_query_schema_version": 1,
            "query_id": "query_real-program-vertical",
            "program_id": snapshot.program_id,
            "program_head": {
                "sequence": snapshot.program_head[0],
                "hash": snapshot.program_head[1],
            },
            "hypothesis_class_id": applicability.hypothesis_class_id,
            "compatibility_digest": applicability.compatibility_digest,
            "evaluation_scope": {
                "id": applicability.evaluation_scope_id,
                "role": applicability.evaluation_scope_role,
                "manifest_digest": applicability.evaluation_scope_manifest_digest,
            },
            "claim_kinds": [claim.statement.kind],
            "diagnosis_digest": claim.evidence.diagnosis_digest,
            "relation_types": ["contradicts"],
            "limit": 10,
            "authorized_action": None,
        }
    )


def _context_args(project_token: str) -> dict[str, Any]:
    return {
        "project": {},
        "status": {},
        "lineage": [],
        "findings": [],
        "artifacts": [],
        "agent_spec": {},
        "snapshot": {
            "schema_version": 2,
            "project_id": "real-project",
            "last_sequence": 3,
            "last_hash": "a" * 64,
            "context_token": project_token,
        },
        "scientific_state": {},
        "limit": 10,
    }


def test_real_program_vertical_context_and_canonical_head_stale_no_write(
    tmp_path: Path,
) -> None:
    store, project_log, head, claims = _real_program(tmp_path)
    snapshot = store.claim_snapshot()
    result = retrieve_claims(snapshot, _real_query(snapshot, claims[0]))
    assert [item.claim_id for item in result.active] == [claims[0].claim_id]
    assert [item.claim_id for item in result.contradictions] == [claims[1].claim_id]
    assert result.active[0].view.claim.limitations
    assert "diagnosis:exact" in result.active[0].reasons
    assert result.contradictions[0].relation_ids

    project_token = sha256_json({"project": "real-program-vertical"})
    legacy = build_agent_context_v3(**_context_args(project_token))
    explicit_none = build_agent_context_v3(**_context_args(project_token), retrieval=None)
    assert canonical_json_bytes(legacy) == canonical_json_bytes(explicit_none)
    assert "memory" not in legacy
    context = build_agent_context_v3(**_context_args(project_token), retrieval=result)
    assert context["memory"]["retrieval_result"] == result.to_dict()
    assert validate_agent_context_v3_retrieval(
        context,
        current_project_context_token=project_token,
        current_claim_snapshot=snapshot,
    ).digest == result.digest

    for path, value in (
        (("snapshot", "project_snapshot", "context_token"), "forged-project"),
        (("memory", "query_digest"), "f" * 64),
        (("memory", "retrieval_result_digest"), "f" * 64),
        (("snapshot", "context_token"), "f" * 64),
    ):
        forged = copy.deepcopy(context)
        cursor = forged
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = value
        before = store.log.path.read_bytes()
        with pytest.raises(StaleAgentContextError):
            validate_agent_context_v3_retrieval(
                forged,
                current_project_context_token=project_token,
                current_claim_snapshot=snapshot,
            )
        assert store.log.path.read_bytes() == before

    third_raw = copy.deepcopy(M2B["fixtures"]["valid_claim"])
    third_raw["statement"]["summary"] = "Canonical Program head stale witness."
    third_raw["claim_id"] = stable_id(
        "claim",
        third_raw["statement"],
        third_raw["applicability"],
        third_raw["evidence"],
        third_raw["claim_status"],
        third_raw["claim_maturity"],
        third_raw["limitations"],
    )
    third = Claim.from_mapping(third_raw)
    store.append_claim(
        third,
        project_log,
        expected_program_head=(head.sequence, head.hash),
    )
    advanced = store.claim_snapshot()
    before = store.log.path.read_bytes()
    with pytest.raises(StaleAgentContextError):
        validate_agent_context_v3_retrieval(
            context,
            current_project_context_token=project_token,
            current_claim_snapshot=advanced,
        )
    assert store.log.path.read_bytes() == before


if __name__ == "__main__":
    print(json.dumps(oracle_receipt(), sort_keys=True, separators=(",", ":")))
