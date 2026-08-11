from __future__ import annotations

import copy
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from research_os.agent import (
    build_agent_context_v3,
    record_agent_context_v3_knowledge_disposition,
    validate_agent_context_v3_retrieval,
)
from research_os.contracts import sha256_json
from research_os.errors import ProgramMemoryError, StaleAgentContextError
from research_os.kernel.events import EventLog
from research_os.kernel.ids import stable_id
from research_os.memory import (
    Claim,
    ClaimRelation,
    KnowledgeDispositionEntry,
    LegacyOpaqueRecord,
    ProgramManifest,
    ProgramStore,
    ProposalKnowledgeDisposition,
    RetrievalQuery,
    create_legacy_opaque_record,
    create_proposal_knowledge_disposition,
    retrieve_claims,
    validate_proposal_knowledge_disposition,
)
from research_os.science import Diagnosis, DiagnosisEventPayload, Proposal, reduce_scientific_state
from tests.test_m2c_deterministic_retrieval import (
    M1D_ROOT,
    M2A,
    M2B,
    _oracle_snapshot,
    _query,
    _real_program,
    _real_query,
)
from tests.test_m2c_deterministic_retrieval import (
    ORACLE as RETRIEVAL_ORACLE,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/program_memory/v3/m2d-manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
DISPOSITION_CASES = tuple(
    case for case in MANIFEST["cases"] if case["id"].startswith("disposition-")
)
LEGACY_CASES = tuple(case for case in MANIFEST["cases"] if case["id"].startswith("legacy-"))


def _context(project_id: str, project_token: str, retrieval: Any) -> dict[str, Any]:
    return build_agent_context_v3(
        project={},
        status={},
        lineage=[],
        findings=[],
        artifacts=[],
        agent_spec={},
        snapshot={
            "schema_version": 2,
            "project_id": project_id,
            "last_sequence": 1,
            "last_hash": "a" * 64,
            "context_token": project_token,
        },
        scientific_state={},
        limit=10,
        retrieval=retrieval,
    )


def _entry(hit: Any, disposition: str) -> KnowledgeDispositionEntry:
    reason = "scope_not_applicable" if disposition == "not_applicable" else None
    refs = ["mechanism"] if disposition != "rejected" else ["falsifier"]
    return KnowledgeDispositionEntry.from_mapping(
        {
            "claim_id": hit.claim_id,
            "claim_digest": hit.view.claim_digest,
            "retrieval_role": hit.relation_role,
            "relation_ids": list(hit.relation_ids),
            "disposition": disposition,
            "proposal_field_refs": refs,
            "reason_code": reason,
            "rationale": f"Exact {disposition} rationale bound to canonical references.",
            "authorized_action": None,
        }
    )


def _proposal(query: Any, *, generation_id: str = "generation_m2d-fixture") -> Proposal:
    return Proposal.from_mapping(
        {
            "proposal_schema_version": 1,
            "generation_id": generation_id,
            "candidate_digest": "c" * 64,
            "hypothesis_class_id": query.hypothesis_class_id,
            "action": "explore",
            "mechanism": "Use relevant prior knowledge without granting authority.",
            "predicted_effect": "The bounded experiment should expose the mechanism.",
            "falsifier": "The expected evidence-bound effect is absent.",
            "parent_experiment_id": None,
            "evaluation_scope_id": query.evaluation_scope.evaluation_scope_id,
            "intervention_json_pointers": ["/alpha"],
            "authorized_action": None,
        }
    )


def _three_way() -> tuple[Any, Any, Proposal, dict[str, Any], ProposalKnowledgeDisposition]:
    snapshot, aliases = _oracle_snapshot()
    claim_ids = {alias: claim_id for claim_id, alias in aliases.items()}
    keep = {
        claim_ids["claim_03_exact_contested"],
        claim_ids["claim_04_contradiction"],
        claim_ids["claim_10_cross_role"],
    }
    snapshot = replace(
        snapshot,
        claims=tuple(view for view in snapshot.claims if view.claim.claim_id in keep),
        relations=tuple(
            relation
            for relation in snapshot.relations
            if relation.source_claim_id in keep and relation.target_claim_id in keep
        ),
    )
    query = _query(RETRIEVAL_ORACLE["queries"][0], snapshot)
    result = retrieve_claims(snapshot, query)
    assert len(result.active) == 2 and len(result.contradictions) == 1
    proposal = _proposal(query)
    project_id = "fixture-m2d"
    project_token = sha256_json({"project": project_id})
    context = _context(project_id, project_token, result)
    entries = [
        _entry(
            hit,
            "not_applicable" if "scope:cross_role" in hit.reasons else "used",
        )
        for hit in result.active
    ] + [_entry(result.contradictions[0], "rejected")]
    disposition = create_proposal_knowledge_disposition(
        project_id=project_id,
        proposal=proposal,
        retrieval=result,
        context_token=context["snapshot"]["context_token"],
        entries=entries,
    )
    return snapshot, result, proposal, context, disposition


def _real_vertical(root: Path) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    store, project_log, head, claims = _real_program(root)
    snapshot = store.claim_snapshot()
    result = retrieve_claims(snapshot, _real_query(snapshot, claims[0]))
    state = reduce_scientific_state(project_log.read(), project_id=project_log.project_id)
    proposal = state.registrations[0].proposal
    project_token = sha256_json({"project": project_log.project_id, "phase": "m2d"})
    context = _context(project_log.project_id, project_token, result)
    disposition = create_proposal_knowledge_disposition(
        project_id=project_log.project_id,
        proposal=proposal,
        retrieval=result,
        context_token=context["snapshot"]["context_token"],
        entries=[
            *(_entry(hit, "used") for hit in result.active),
            *(_entry(hit, "rejected") for hit in result.contradictions),
        ],
    )
    return {
        "store": store,
        "project_log": project_log,
        "head": head,
        "snapshot": snapshot,
        "result": result,
        "proposal": proposal,
        "project_token": project_token,
        "context": context,
        "disposition": disposition,
    }


def _combined_diagnosed_project(root: Path) -> tuple[EventLog, Any]:
    terminal = json.loads((M1D_ROOT / "m1d-terminal-corpus.json").read_text(encoding="utf-8"))
    valid = json.loads((M1D_ROOT / "m1d-diagnosis-valid.json").read_text(encoding="utf-8"))
    project_id = "fixture-m1d"
    log = EventLog(root / "combined-project.jsonl", project_id)
    by_id = {}
    for case_index, diagnosis_case_id in enumerate(
        ("supported", "conclusive-no-meaningful-improvement")
    ):
        diagnosis_case = next(
            item for item in valid["cases"] if item["id"] == diagnosis_case_id
        )
        terminal_record = next(
            item
            for item in terminal["records"]
            if item["id"] == diagnosis_case["terminal_record_id"]
        )
        history = terminal_record["canonical_history"]
        if case_index:
            history = history[2:]
        for raw_event in history:
            event = log.append(
                raw_event["event_type"],
                copy.deepcopy(raw_event["payload"]),
                event_id=raw_event["event_id"],
                occurred_at=raw_event["occurred_at"],
            )
            by_id[event.event_id] = event

        wrapper = diagnosis_case["diagnosis_event"]["payload"]
        diagnosis_raw = copy.deepcopy(wrapper["diagnosis"])
        terminal_ref = diagnosis_raw["terminal_evidence"]
        terminal_ref["event_hash"] = by_id[terminal_ref["event_id"]].hash
        for artifact_ref in diagnosis_raw["artifact_evidence"]:
            artifact_ref["event_hash"] = by_id[artifact_ref["event_id"]].hash
        diagnosis = Diagnosis.from_mapping(diagnosis_raw)
        payload = DiagnosisEventPayload.from_diagnosis(
            project_id=project_id,
            generation_id=wrapper["generation_id"],
            study_contract_digest=wrapper["study_contract_digest"],
            evaluation_seal_digest=wrapper["evaluation_seal_digest"],
            compatibility_digest=wrapper["compatibility_digest"],
            diagnosis=diagnosis,
        )
        diagnosis_event = diagnosis_case["diagnosis_event"]
        event = log.append(
            diagnosis_event["event_type"],
            payload.to_dict(),
            event_id=diagnosis_event["event_id"],
            occurred_at=diagnosis_event["occurred_at"],
        )
        by_id[event.event_id] = event
    return log, reduce_scientific_state(log.read(), project_id=project_id)


def _program_binding(
    *, project_id: str, scope_id: str, role: str, manifest_digest: str
) -> dict[str, Any]:
    raw = copy.deepcopy(M2A["fixtures"]["binding"])
    scope = {"id": scope_id, "role": role, "manifest_digest": manifest_digest}
    raw["project_id"] = project_id
    raw["evaluation_scope"] = scope
    raw["evaluation_scope_digest"] = sha256_json(
        {"evaluation_scope_schema_version": 1, "evaluation_scope": scope}
    )
    return raw


def _claim_for_origin(
    *,
    origin: Any,
    binding: dict[str, Any],
    diagnosis_record: Any,
    summary: str,
) -> Claim:
    raw = copy.deepcopy(M2B["fixtures"]["valid_claim"])
    raw["statement"]["summary"] = summary
    scope = binding["evaluation_scope"]
    raw["applicability"] = {
        "claim_applicability_schema_version": 1,
        "project_id": binding["project_id"],
        "generation_id": binding["generation_id"],
        "hypothesis_class_id": diagnosis_record.diagnosis.hypothesis_class_id,
        "evaluation_scope": copy.deepcopy(scope),
        "evaluation_scope_digest": binding["evaluation_scope_digest"],
        "evaluation_seal_digest": binding["evaluation_seal_digest"],
        "compatibility_digest": binding["compatibility_digest"],
        "authorized_action": None,
    }
    raw["evidence"] = {
        "claim_evidence_schema_version": 1,
        "origin_id": origin.origin_id,
        "origin_digest": origin.digest,
        "diagnosis_event": {
            "sequence": origin.diagnosis_event_sequence,
            "event_id": origin.diagnosis_event_id,
            "event_hash": origin.diagnosis_event_hash,
        },
        "diagnosis_id": origin.diagnosis_id,
        "diagnosis_digest": origin.diagnosis_digest,
        "terminal_evidence": diagnosis_record.diagnosis.terminal_evidence.to_dict(),
        "artifact_evidence": [
            item.to_dict() for item in diagnosis_record.diagnosis.artifact_evidence
        ],
        "evaluation_seal_digest": binding["evaluation_seal_digest"],
        "compatibility_digest": binding["compatibility_digest"],
        "authorized_action": None,
    }
    raw["claim_id"] = stable_id(
        "claim",
        raw["statement"],
        raw["applicability"],
        raw["evidence"],
        raw["claim_status"],
        raw["claim_maturity"],
        raw["limitations"],
    )
    return Claim.from_mapping(raw)


def _durable_three_way_vertical(root: Path) -> dict[str, Any]:
    project_log, state = _combined_diagnosed_project(root)
    development_binding = _program_binding(
        project_id=project_log.project_id,
        scope_id="development",
        role="development",
        manifest_digest="b" * 64,
    )
    diagnostic_binding = _program_binding(
        project_id=project_log.project_id,
        scope_id="diagnostic-1",
        role="diagnostic",
        manifest_digest="c" * 64,
    )
    manifest = ProgramManifest.from_mapping(
        {
            "program_manifest_schema_version": 1,
            "program_id": M2A["fixtures"]["program_id"],
            "bindings": [development_binding, diagnostic_binding],
            "authorized_action": None,
        }
    )
    store = ProgramStore(root / "program", manifest.program_id)
    head = store.initialize(
        manifest,
        {project_log.project_id: project_log},
    )
    development_diagnosis = next(
        item for item in state.diagnoses if item.diagnosis.evaluation_scope_id == "development"
    )
    diagnostic_diagnosis = next(
        item for item in state.diagnoses if item.diagnosis.evaluation_scope_id == "diagnostic-1"
    )
    development_origin, head = store.link_origin(
        project_log,
        development_diagnosis.diagnosis_id,
        expected_program_head=(head.sequence, head.hash),
    )
    diagnostic_origin, head = store.link_origin(
        project_log,
        diagnostic_diagnosis.diagnosis_id,
        expected_program_head=(head.sequence, head.hash),
    )
    claims = [
        _claim_for_origin(
            origin=development_origin,
            binding=development_binding,
            diagnosis_record=development_diagnosis,
            summary=f"Durable development disposition claim {index}.",
        )
        for index in range(2)
    ]
    cross_scope = _claim_for_origin(
        origin=diagnostic_origin,
        binding=diagnostic_binding,
        diagnosis_record=diagnostic_diagnosis,
        summary="Durable cross-role disposition claim.",
    )
    for claim in claims:
        head = store.append_claim(
            claim,
            project_log,
            expected_program_head=(head.sequence, head.hash),
        )
    head = store.append_claim(
        cross_scope,
        project_log,
        expected_program_head=(head.sequence, head.hash),
    )
    relation = ClaimRelation.from_mapping(
        {
            "claim_relation_schema_version": 1,
            "relation_id": stable_id(
                "relation",
                "contradicts",
                claims[1].claim_id,
                claims[0].claim_id,
                "Durable three-way contradiction.",
            ),
            "relation_type": "contradicts",
            "source_claim_id": claims[1].claim_id,
            "target_claim_id": claims[0].claim_id,
            "rationale": "Durable three-way contradiction.",
            "authorized_action": None,
        }
    )
    head = store.append_relation(
        relation,
        expected_program_head=(head.sequence, head.hash),
    )
    snapshot = store.claim_snapshot()
    query_raw = _real_query(snapshot, claims[0]).to_dict()
    query_raw["query_id"] = "query_durable-three-way"
    query_raw["diagnosis_digest"] = None
    query = RetrievalQuery.from_mapping(query_raw)
    result = retrieve_claims(snapshot, query)
    assert {hit.claim_id for hit in result.active} == {
        claims[0].claim_id,
        cross_scope.claim_id,
    }
    assert [hit.claim_id for hit in result.contradictions] == [claims[1].claim_id]
    proposal = next(
        item.proposal for item in state.registrations if item.evaluation_scope_id == "development"
    )
    project_token = sha256_json({"project": project_log.project_id, "phase": "m2d-three-way"})
    context = _context(project_log.project_id, project_token, result)
    entries = [
        _entry(
            hit,
            "not_applicable" if hit.claim_id == cross_scope.claim_id else "used",
        )
        for hit in result.active
    ] + [_entry(result.contradictions[0], "rejected")]
    disposition = create_proposal_knowledge_disposition(
        project_id=project_log.project_id,
        proposal=proposal,
        retrieval=result,
        context_token=context["snapshot"]["context_token"],
        entries=entries,
    )
    record_agent_context_v3_knowledge_disposition(
        context,
        current_project_context_token=project_token,
        current_claim_snapshot=snapshot,
        proposal=proposal,
        disposition=disposition,
        program_store=store,
        project_log=project_log,
        expected_program_head=(head.sequence, head.hash),
    )
    return {
        "store": store,
        "disposition": disposition,
        "returned_claim_ids": {
            *(hit.claim_id for hit in result.active),
            *(hit.claim_id for hit in result.contradictions),
        },
    }


def _rebind_disposition(raw: dict[str, Any]) -> None:
    identity = copy.deepcopy(raw)
    identity.pop("disposition_id")
    raw["disposition_id"] = stable_id("disposition", identity)


def _record(vertical: dict[str, Any], raw: dict[str, Any]) -> None:
    record_agent_context_v3_knowledge_disposition(
        vertical["context"],
        current_project_context_token=vertical["project_token"],
        current_claim_snapshot=vertical["snapshot"],
        proposal=vertical["proposal"],
        disposition=raw,
        program_store=vertical["store"],
        project_log=vertical["project_log"],
        expected_program_head=(vertical["head"].sequence, vertical["head"].hash),
    )


def _reject_disposition(case_id: str, root: Path) -> dict[str, Any]:
    vertical = _real_vertical(root)
    raw = vertical["disposition"].to_dict()
    context = vertical["context"]
    if case_id == "disposition-missing-returned-claim":
        raw["entries"].pop()
    elif case_id == "disposition-duplicate-claim":
        raw["entries"].append(copy.deepcopy(raw["entries"][0]))
    elif case_id == "disposition-unknown-claim":
        raw["entries"][0]["claim_id"] = "claim_unknown"
    elif case_id == "disposition-forged-claim-digest":
        raw["entries"][0]["claim_digest"] = "f" * 64
    elif case_id == "disposition-forged-role":
        raw["entries"][0]["retrieval_role"] = "contradiction"
    elif case_id == "disposition-forged-relation-ref":
        raw["entries"][0]["relation_ids"] = ["relation_forged"]
    elif case_id == "disposition-forged-proposal-binding":
        raw["proposal_digest"] = "f" * 64
    elif case_id == "disposition-stale-context-token":
        context = copy.deepcopy(context)
        context["memory"]["query_digest"] = "f" * 64
    elif case_id == "disposition-used-without-proposal-ref":
        raw["entries"][0]["proposal_field_refs"] = []
    elif case_id == "disposition-rejected-without-contradiction-ref":
        rejected = next(item for item in raw["entries"] if item["disposition"] == "rejected")
        rejected["relation_ids"] = []
    elif case_id == "disposition-not-applicable-without-code":
        raw["entries"][0]["disposition"] = "not_applicable"
        raw["entries"][0]["reason_code"] = None
    elif case_id == "disposition-non-null-authority":
        raw["authorized_action"] = "deploy"
    else:
        raise AssertionError(case_id)
    _rebind_disposition(raw)
    before = vertical["store"].log.path.read_bytes()
    try:
        record_agent_context_v3_knowledge_disposition(
            context,
            current_project_context_token=vertical["project_token"],
            current_claim_snapshot=vertical["snapshot"],
            proposal=vertical["proposal"],
            disposition=raw,
            program_store=vertical["store"],
            project_log=vertical["project_log"],
            expected_program_head=(vertical["head"].sequence, vertical["head"].hash),
        )
    except (ProgramMemoryError, StaleAgentContextError) as exc:
        code = "STALE_AGENT_CONTEXT" if isinstance(exc, StaleAgentContextError) else exc.code
        return {
            "error_code": code,
            "write_delta": len(vertical["store"].log.path.read_bytes()) - len(before),
        }
    raise AssertionError("invalid disposition was accepted")


def _observe_disposition(case_id: str, root: Path) -> dict[str, Any]:
    if case_id == "disposition-valid-three-way":
        snapshot, result, proposal, context, disposition = _three_way()
        project_token = context["snapshot"]["project_snapshot"]["context_token"]
        validated_result = validate_agent_context_v3_retrieval(
            context,
            current_project_context_token=project_token,
            current_claim_snapshot=snapshot,
        )
        parsed = validate_proposal_knowledge_disposition(
            disposition,
            project_id="fixture-m2d",
            proposal=proposal,
            retrieval=validated_result,
            context_token=context["snapshot"]["context_token"],
        )
        counts = {name: 0 for name in ("used", "rejected", "not_applicable")}
        for entry in parsed.entries:
            counts[entry.disposition] += 1
        return {
            "entry_count": len(parsed.entries),
            **counts,
            "authorized_action": parsed.authorized_action,
        }
    if case_id == "disposition-stale-program-head":
        vertical = _real_vertical(root)
        marker = create_legacy_opaque_record(
            program_id=vertical["store"].program_id,
            source_project_id="fixture",
            source_kind="note",
            source_locator="stale-marker",
            content=b"advance",
        )
        vertical["store"].append_legacy_opaque(
            marker,
            b"advance",
            expected_program_head=(vertical["head"].sequence, vertical["head"].hash),
        )
        before = vertical["store"].log.path.read_bytes()
        with pytest.raises(StaleAgentContextError):
            record_agent_context_v3_knowledge_disposition(
                vertical["context"],
                current_project_context_token=vertical["project_token"],
                current_claim_snapshot=vertical["store"].claim_snapshot(),
                proposal=vertical["proposal"],
                disposition=vertical["disposition"],
                program_store=vertical["store"],
                project_log=vertical["project_log"],
                expected_program_head=vertical["store"].claim_snapshot().program_head,
            )
        return {
            "error_code": "STALE_AGENT_CONTEXT",
            "write_delta": len(vertical["store"].log.path.read_bytes()) - len(before),
        }
    return _reject_disposition(case_id, root)


def _rebind_legacy(raw: dict[str, Any]) -> None:
    identity = copy.deepcopy(raw)
    identity.pop("legacy_opaque_id")
    raw["legacy_opaque_id"] = stable_id("legacy", identity)


def _observe_legacy(case_id: str, root: Path) -> dict[str, Any]:
    vertical = _real_vertical(root)
    store = vertical["store"]
    content = (
        b'{"claim_status":"active","relation_type":"supports",'
        b'"authorized_action":"deploy"}\nClaim: guaranteed alpha.'
    )
    record = create_legacy_opaque_record(
        program_id=store.program_id,
        source_project_id="legacy-project",
        source_kind="note",
        source_locator="legacy/free-text.txt",
        content=content,
    )
    raw = record.to_dict()
    if case_id == "legacy-forged-content-digest":
        raw["content_sha256"] = "f" * 64
    elif case_id == "legacy-extra-key":
        raw["unexpected"] = True
    elif case_id == "legacy-non-null-authority":
        raw["authorized_action"] = "trade"
    if case_id in {
        "legacy-forged-content-digest",
        "legacy-extra-key",
        "legacy-non-null-authority",
    }:
        _rebind_legacy(raw)
        before = store.log.path.read_bytes()
        try:
            store.append_legacy_opaque(
                raw,
                content,
                expected_program_head=(vertical["head"].sequence, vertical["head"].hash),
            )
        except ProgramMemoryError as exc:
            return {
                "error_code": exc.code,
                "write_delta": len(store.log.path.read_bytes()) - len(before),
            }
        raise AssertionError("invalid legacy record was accepted")

    claims_before = store.claim_snapshot()
    event = store.append_legacy_opaque(
        record,
        content,
        expected_program_head=(vertical["head"].sequence, vertical["head"].hash),
    )
    if case_id == "legacy-duplicate-id":
        before = store.log.path.read_bytes()
        with pytest.raises(ProgramMemoryError) as caught:
            store.append_legacy_opaque(
                record,
                content,
                expected_program_head=(event.sequence, event.hash),
            )
        return {
            "error_code": caught.value.code,
            "write_delta": len(store.log.path.read_bytes()) - len(before),
        }
    legacy = store.legacy_opaque_snapshot()
    claims_after = store.claim_snapshot()
    assert len(claims_after.claims) == len(claims_before.claims)
    assert len(claims_after.relations) == len(claims_before.relations)
    assert content not in store.log.path.read_bytes()
    if case_id == "legacy-free-text-never-inferred":
        return {
            "classification": legacy.records[0].classification,
            "typed_claim_count": len(legacy.records[0].typed_claim_ids),
        }
    return {
        "legacy_count": len(legacy.records),
        "typed_claim_count": len(legacy.records[0].typed_claim_ids),
        "raw_content_stored": content in store.log.path.read_bytes(),
        "authorized_action": legacy.records[0].authorized_action,
    }


def test_m2d_frozen_case_ids_and_counts_are_exact() -> None:
    ids = [case["id"] for case in MANIFEST["cases"]]
    assert len(ids) == len(set(ids)) == 23
    assert len(DISPOSITION_CASES) == 14
    assert len(LEGACY_CASES) == 6


@pytest.mark.parametrize("case", DISPOSITION_CASES, ids=lambda case: case["id"])
def test_frozen_disposition_case(case: dict[str, Any], tmp_path: Path) -> None:
    assert _observe_disposition(case["id"], tmp_path / case["id"]) == case["expected"]


@pytest.mark.parametrize("case", LEGACY_CASES, ids=lambda case: case["id"])
def test_frozen_legacy_case(case: dict[str, Any], tmp_path: Path) -> None:
    assert _observe_legacy(case["id"], tmp_path / case["id"]) == case["expected"]


def test_durable_three_way_disposition_replays_from_registered_proposal(
    tmp_path: Path,
) -> None:
    vertical = _durable_three_way_vertical(tmp_path)
    original = vertical["disposition"]
    cold_store = ProgramStore(vertical["store"].root, vertical["store"].program_id)
    replayed = cold_store.knowledge_disposition_snapshot()

    assert replayed.dispositions == (original,)
    assert {entry.claim_id for entry in replayed.dispositions[0].entries} == vertical[
        "returned_claim_ids"
    ]
    assert {entry.disposition for entry in replayed.dispositions[0].entries} == {
        "used",
        "rejected",
        "not_applicable",
    }
    assert len(replayed.dispositions[0].entries) == 3
    assert replayed.authorized_action is None


def test_durable_disposition_replays_and_duplicate_is_no_write(tmp_path: Path) -> None:
    vertical = _real_vertical(tmp_path)
    _record(vertical, vertical["disposition"].to_dict())
    snapshot = vertical["store"].knowledge_disposition_snapshot()
    assert snapshot.dispositions == (vertical["disposition"],)
    assert snapshot.dispositions[0].proposal_id == vertical["disposition"].proposal_id
    before = vertical["store"].log.path.read_bytes()
    head = vertical["store"].log.head()
    assert head is not None
    refreshed_snapshot = vertical["store"].claim_snapshot()
    refreshed_result = retrieve_claims(
        refreshed_snapshot,
        replace(
            vertical["result"].query,
            program_head_sequence=head.sequence,
            program_head_hash=head.hash,
        ),
    )
    refreshed_context = _context(
        vertical["project_log"].project_id,
        vertical["project_token"],
        refreshed_result,
    )
    duplicate = create_proposal_knowledge_disposition(
        project_id=vertical["project_log"].project_id,
        proposal=vertical["proposal"],
        retrieval=refreshed_result,
        context_token=refreshed_context["snapshot"]["context_token"],
        entries=[
            *(_entry(hit, "used") for hit in refreshed_result.active),
            *(_entry(hit, "rejected") for hit in refreshed_result.contradictions),
        ],
    )
    with pytest.raises(ProgramMemoryError, match="already recorded"):
        record_agent_context_v3_knowledge_disposition(
            refreshed_context,
            current_project_context_token=vertical["project_token"],
            current_claim_snapshot=refreshed_snapshot,
            proposal=vertical["proposal"],
            disposition=duplicate,
            program_store=vertical["store"],
            project_log=vertical["project_log"],
            expected_program_head=(head.sequence, head.hash),
        )
    assert vertical["store"].log.path.read_bytes() == before


def test_legacy_strict_replay_rejects_forged_projection_shape(tmp_path: Path) -> None:
    vertical = _real_vertical(tmp_path)
    record = create_legacy_opaque_record(
        program_id=vertical["store"].program_id,
        source_project_id="legacy-project",
        source_kind="file",
        source_locator="archive/result.txt",
        content=b"unstructured result",
    )
    parsed = LegacyOpaqueRecord.from_mapping(record.to_dict())
    assert parsed == record
    forged = parsed.to_dict()
    forged["typed_claim_ids"] = ["claim_forged"]
    _rebind_legacy(forged)
    with pytest.raises(ProgramMemoryError, match="typed_claim_ids"):
        LegacyOpaqueRecord.from_mapping(forged)
