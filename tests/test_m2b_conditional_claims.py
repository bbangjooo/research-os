from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable

import pytest

from research_os.contracts.common import sha256_json
from research_os.errors import ProgramMemoryError
from research_os.kernel._canonical import canonical_bytes
from research_os.kernel.events import Event, EventLog
from research_os.kernel.ids import new_experiment_id, stable_id
from research_os.memory.claims import (
    Claim,
    ClaimRelation,
    ClaimSnapshot,
    claim_event_payload,
    reduce_claim_records,
)
from research_os.memory.program import (
    PROGRAM_CLAIM_RECORDED_EVENT,
    PROGRAM_INITIALIZED_EVENT,
    PROGRAM_ORIGIN_LINKED_EVENT,
    OriginEvidenceRef,
    ProgramBinding,
    ProgramEvent,
    ProgramManifest,
    ProgramStore,
)
from research_os.science import (
    DIAGNOSIS_EVENT_TYPE,
    Proposal,
    build_diagnosis_template,
    plan_diagnosis_append,
    proposal_id,
    reduce_scientific_state,
    registration_payload_fields,
    validate_registration,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "program_memory"
M2B_PATH = FIXTURE_ROOT / "v2" / "claims-manifest.json"
M2A_PATH = FIXTURE_ROOT / "v1" / "manifest.json"
M1D_ROOT = ROOT / "tests" / "fixtures" / "scientific_state" / "v3"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


ORACLE = _json(M2B_PATH)
M2A = _json(M2A_PATH)
CASES = {case["id"]: case for case in ORACLE["cases"]}
CASE_IDS = tuple(CASES)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _supported_history() -> list[dict[str, Any]]:
    terminal = _json(M1D_ROOT / "m1d-terminal-corpus.json")
    valid = _json(M1D_ROOT / "m1d-diagnosis-valid.json")
    diagnosis_case = next(item for item in valid["cases"] if item["id"] == "supported")
    terminal_record = next(
        item for item in terminal["records"] if item["id"] == diagnosis_case["terminal_record_id"]
    )
    return copy.deepcopy([*terminal_record["canonical_history"], diagnosis_case["diagnosis_event"]])


def _project_log(root: Path) -> EventLog:
    path = root / "project-events.jsonl"
    path.write_bytes(
        b"".join(
            canonical_bytes(Event.from_mapping(item).to_dict()) + b"\n"
            for item in _supported_history()
        )
    )
    path.chmod(0o600)
    return EventLog(path, M2A["fixtures"]["project_id"])


def _manifest_raw(*bindings: dict[str, Any]) -> dict[str, Any]:
    return {
        "program_manifest_schema_version": 1,
        "program_id": M2A["fixtures"]["program_id"],
        "bindings": [copy.deepcopy(item) for item in bindings]
        or [copy.deepcopy(M2A["fixtures"]["binding"])],
        "authorized_action": None,
    }


def _origin_raw() -> dict[str, Any]:
    return copy.deepcopy(M2A["fixtures"]["origin"])


def _claim_raw() -> dict[str, Any]:
    return copy.deepcopy(ORACLE["fixtures"]["valid_claim"])


def _rebind_claim(raw: dict[str, Any]) -> None:
    raw["claim_id"] = stable_id(
        "claim",
        raw["statement"],
        raw["applicability"],
        raw["evidence"],
        raw["claim_status"],
        raw["claim_maturity"],
        raw["limitations"],
    )


def _relation_raw(
    relation_type: str,
    source_claim_id: str,
    target_claim_id: str,
    *,
    rationale: str | None = None,
) -> dict[str, Any]:
    rationale = rationale or f"Frozen {relation_type} relation rationale."
    return {
        "claim_relation_schema_version": 1,
        "relation_id": stable_id(
            "relation", relation_type, source_claim_id, target_claim_id, rationale
        ),
        "relation_type": relation_type,
        "source_claim_id": source_claim_id,
        "target_claim_id": target_claim_id,
        "rationale": rationale,
        "authorized_action": None,
    }


def _initialize(root: Path) -> tuple[EventLog, ProgramStore, ProgramEvent]:
    project_log = _project_log(root)
    manifest = ProgramManifest.from_mapping(_manifest_raw())
    store = ProgramStore(root / "program", manifest.program_id)
    initialized = store.initialize(
        manifest,
        {project_log.project_id: project_log},
        event_id="evt_m2b_program_initialized",
        occurred_at="2026-08-11T03:00:00.000000Z",
    )
    linked = store.append_origin(
        OriginEvidenceRef.from_mapping(_origin_raw()),
        project_log,
        expected_program_head=(initialized.sequence, initialized.hash),
        event_id="evt_m2b_origin_linked",
        occurred_at="2026-08-11T03:00:01.000000Z",
    )
    return project_log, store, linked


def _append_claim(
    store: ProgramStore,
    project_log: EventLog,
    head: ProgramEvent,
    raw: dict[str, Any],
    suffix: str,
) -> tuple[Claim, ProgramEvent]:
    claim = Claim.from_mapping(raw)
    event = store.append_claim(
        claim,
        project_log,
        expected_program_head=(head.sequence, head.hash),
        event_id=f"evt_m2b_claim_{suffix}",
        occurred_at=f"2026-08-11T03:01:{int(head.sequence):02d}.000000Z",
    )
    return claim, event


def _two_same_scope_claims(
    root: Path, *, same_statement: bool = False
) -> tuple[EventLog, ProgramStore, Claim, Claim, ProgramEvent]:
    project_log, store, head = _initialize(root)
    target, head = _append_claim(store, project_log, head, _claim_raw(), "target")
    source_raw = _claim_raw()
    if same_statement:
        source_raw["limitations"] = [
            "Independent synthesis wording; this still is not deployment authorization."
        ]
    else:
        source_raw["statement"]["summary"] = (
            "A second bounded interpretation addresses the same exact development evidence."
        )
    _rebind_claim(source_raw)
    source, head = _append_claim(store, project_log, head, source_raw, "source")
    return project_log, store, target, source, head


def _reject_claim_parse(raw: dict[str, Any]) -> dict[str, Any]:
    with pytest.raises(ProgramMemoryError) as caught:
        Claim.from_mapping(raw)
    return {"error_code": caught.value.code, "program_event_delta": 0, "claim_state_delta": 0}


def _reject_claim_append(root: Path, raw: dict[str, Any]) -> dict[str, Any]:
    project_log, store, head = _initialize(root)
    before_events = len(store.log.read())
    before_claims = len(store.claim_snapshot().claims)
    with pytest.raises(ProgramMemoryError) as caught:
        store.append_claim(
            raw,
            project_log,
            expected_program_head=(head.sequence, head.hash),
        )
    return {
        "error_code": caught.value.code,
        "program_event_delta": len(store.log.read()) - before_events,
        "claim_state_delta": len(store.claim_snapshot().claims) - before_claims,
    }


def _parse_valid_claim(_root: Path) -> dict[str, Any]:
    claim = Claim.from_mapping(_claim_raw())
    return {
        "claim_status": claim.claim_status,
        "claim_maturity": claim.claim_maturity,
        "applicability_role": claim.applicability.evaluation_scope_role,
        "artifact_evidence_count": len(claim.evidence.artifact_evidence),
        "authorized_action": claim.authorized_action,
    }


def _reject_extra(_root: Path) -> dict[str, Any]:
    raw = _claim_raw()
    raw["unexpected"] = None
    return _reject_claim_parse(raw)


def _reject_version(_root: Path) -> dict[str, Any]:
    raw = _claim_raw()
    raw["claim_schema_version"] = 2
    return _reject_claim_parse(raw)


def _reject_status(_root: Path) -> dict[str, Any]:
    raw = _claim_raw()
    raw["claim_status"] = "contested"
    _rebind_claim(raw)
    return _reject_claim_parse(raw)


def _reject_maturity(_root: Path) -> dict[str, Any]:
    raw = _claim_raw()
    raw["claim_maturity"] = "replicated"
    _rebind_claim(raw)
    return _reject_claim_parse(raw)


def _append_exact(root: Path) -> dict[str, Any]:
    project_log, store, head = _initialize(root)
    claim, event = _append_claim(store, project_log, head, _claim_raw(), "exact")
    snapshot = store.claim_snapshot()
    view = snapshot.claim(claim.claim_id)
    assert view is not None
    return {
        "program_head_sequence": event.sequence,
        "claim_count": len(snapshot.claims),
        "relation_count": len(snapshot.relations),
        "effective_status": view.effective_status,
        "effective_maturity": view.effective_maturity,
        "authorized_action": snapshot.authorized_action,
    }


def _forged_claim(root: Path, mutation: str) -> dict[str, Any]:
    raw = _claim_raw()
    if mutation == "origin":
        raw["evidence"]["origin_digest"] = "a" * 64
    elif mutation == "diagnosis":
        raw["evidence"]["diagnosis_event"]["event_hash"] = "a" * 64
    elif mutation == "terminal":
        raw["evidence"]["terminal_evidence"]["event_hash"] = "a" * 64
    elif mutation == "artifact":
        raw["evidence"]["artifact_evidence"][0]["artifact_digest"] = "a" * 64
    elif mutation == "seal":
        raw["evidence"]["evaluation_seal_digest"] = "a" * 64
        raw["applicability"]["evaluation_seal_digest"] = "a" * 64
    elif mutation == "class":
        raw["applicability"]["hypothesis_class_id"] = "class-b"
    else:  # pragma: no cover
        raise AssertionError(mutation)
    _rebind_claim(raw)
    return _reject_claim_append(root, raw)


def _relation_view(root: Path, relation_type: str) -> tuple[Any, Any, Any]:
    project_log, store, target, source, head = _two_same_scope_claims(root)
    relation = ClaimRelation.from_mapping(
        _relation_raw(relation_type, source.claim_id, target.claim_id)
    )
    store.append_relation(
        relation,
        expected_program_head=(head.sequence, head.hash),
        event_id=f"evt_m2b_relation_{relation_type}",
        occurred_at="2026-08-11T03:02:00.000000Z",
    )
    snapshot = store.claim_snapshot()
    return snapshot, snapshot.claim(target.claim_id), snapshot.claim(source.claim_id)


def _supports(root: Path) -> dict[str, Any]:
    snapshot, target, _ = _relation_view(root, "supports")
    return {
        "target_effective_status": target.effective_status,
        "target_effective_maturity": target.effective_maturity,
        "support_count": len(target.supported_by),
        "relation_count": len(snapshot.relations),
    }


def _contradicts(root: Path) -> dict[str, Any]:
    snapshot, target, _ = _relation_view(root, "contradicts")
    return {
        "target_effective_status": target.effective_status,
        "target_effective_maturity": target.effective_maturity,
        "contradiction_count": len(target.contradicted_by),
        "relation_count": len(snapshot.relations),
    }


def _supersedes(root: Path) -> dict[str, Any]:
    snapshot, target, source = _relation_view(root, "supersedes")
    return {
        "target_effective_status": target.effective_status,
        "source_effective_status": source.effective_status,
        "superseded_by_count": int(target.superseded_by is not None),
        "relation_count": len(snapshot.relations),
    }


def _binding_for_scope(project_log: EventLog, scope_id: str) -> dict[str, Any]:
    state = reduce_scientific_state(project_log.read(), project_id=project_log.project_id)
    assert state.contract is not None and state.evaluation_seal is not None
    scope = next(item for item in state.contract.evaluation_scopes if item.id == scope_id)
    return {
        "project_id": project_log.project_id,
        "science_state_schema_version": 1,
        "study_contract_schema_version": state.contract.schema_version,
        "study_contract_digest": state.contract.digest,
        "generation_id": state.active_generation_id,
        "evaluation_scope_schema_version": 1,
        "evaluation_scope": scope.to_dict(),
        "evaluation_scope_digest": sha256_json(
            {"evaluation_scope_schema_version": 1, "evaluation_scope": scope.to_dict()}
        ),
        "evaluation_seal_digest": state.evaluation_seal.digest,
        "compatibility_digest": state.evaluation_seal.compatibility_digest,
        "authorized_action": None,
    }


def _append_replication_history(project_log: EventLog) -> str:
    state = reduce_scientific_state(project_log.read(), project_id=project_log.project_id)
    assert state.contract is not None and state.evaluation_seal is not None
    scope = next(item for item in state.contract.evaluation_scopes if item.id == "replication-1")
    baseline_id = stable_id("baseline", project_log.project_id, state.active_generation_id, scope.id)
    project_log.append(
        "BASELINE_RECORDED",
        {
            "baseline_id": baseline_id,
            "compatibility_digest": state.evaluation_seal.compatibility_digest,
            "science_state_version": 1,
            "generation_id": state.active_generation_id,
            "study_contract_digest": state.contract.digest,
            "evaluation_seal_digest": state.evaluation_seal.digest,
            "evaluation_scope_id": scope.id,
            "evaluation_scope": scope.to_dict(),
            "authorized_action": None,
        },
        event_id="evt_m2b_replication_baseline",
        occurred_at="2026-08-11T03:10:00.000000Z",
    )
    state = reduce_scientific_state(project_log.read(), project_id=project_log.project_id)
    candidate = {"x": 1}
    candidate_digest = sha256_json(candidate)
    parent = state.diagnoses[0].diagnosis.experiment_id
    proposal = Proposal.from_mapping(
        {
            "proposal_schema_version": 1,
            "generation_id": state.active_generation_id,
            "candidate_digest": candidate_digest,
            "hypothesis_class_id": "class-a",
            "action": "replicate",
            "mechanism": "Repeat the frozen class-a candidate on replication-1.",
            "predicted_effect": "The verified score improvement survives replication-1.",
            "falsifier": "The same candidate fails the sealed replication evaluation.",
            "parent_experiment_id": parent,
            "evaluation_scope_id": "replication-1",
            "intervention_json_pointers": [],
            "authorized_action": None,
        }
    )
    experiment_id = new_experiment_id(
        project_log.project_id,
        candidate_digest,
        parent_id=parent,
        compatibility_digest=state.evaluation_seal.compatibility_digest,
        generation_id=state.active_generation_id,
        evaluation_scope_id="replication-1",
    )
    registration = {
        "experiment_id": experiment_id,
        "candidate": candidate,
        "candidate_digest": candidate_digest,
        "parent_id": parent,
        "compatibility_digest": state.evaluation_seal.compatibility_digest,
        "baseline_id": baseline_id,
        "attempt": 1,
        "retry_of": None,
        "authorized_action": None,
        "proposal": proposal.to_dict(),
        "proposal_digest": proposal.digest,
        "proposal_id": proposal_id(project_log.project_id, proposal.digest),
        "evaluation_scope_id": "replication-1",
        **registration_payload_fields(state, retry_of=None),
    }
    validate_registration(state, registration)
    project_log.append(
        "EXPERIMENT_REGISTERED",
        registration,
        event_id="evt_m2b_replication_registered",
        occurred_at="2026-08-11T03:10:01.000000Z",
    )
    artifact_metadata = {"retention": "run", "sensitivity": "internal"}
    artifacts = tuple(
        (
            stable_id(
                "artifact", project_log.project_id, experiment_id, relative_path,
                digest, None, "application/json", artifact_metadata,
            ),
            digest, relative_path, size,
        )
        for digest, relative_path, size in (
            ("1" * 64, "replication-a.json", 101),
            ("2" * 64, "replication-b.json", 102),
        )
    )
    for index, (artifact_id, digest, relative_path, size) in enumerate(artifacts, 1):
        project_log.append(
            "ARTIFACT_RECORDED",
            {
                "artifact_id": artifact_id,
                "project_id": project_log.project_id,
                "experiment_id": experiment_id,
                "digest": digest,
                "algorithm": "sha256",
                "size": size,
                "relative_path": relative_path,
                "storage_path": f"blobs/sha256/{digest[:2]}/{digest}",
                "role": None,
                "media_type": "application/json",
                "metadata": artifact_metadata,
                "captured_at": f"2026-08-11T03:10:0{index + 1}.000000Z",
                "authorized_action": None,
            },
            event_id=f"evt_m2b_replication_artifact_{index}",
            occurred_at=f"2026-08-11T03:10:0{index + 1}.000000Z",
        )
    project_log.append(
        "EXPERIMENT_TERMINATED",
        {
            "experiment_id": experiment_id,
            "status": "VALIDATED",
            "reason_code": "PRIMARY_METRIC_IMPROVED",
            "attempt": 1,
            "retry_of": None,
            "retryable": False,
            "verified": True,
            "primary_metric": "score",
            "decision": {
                "status": "VALIDATED",
                "reason_code": "PRIMARY_METRIC_IMPROVED",
                "primary_metric": "score",
                "candidate_value": 109.0,
                "baseline_value": 100.0,
                "improvement": 9.0,
                "promotion_margin": 3.0,
                "gate_evaluations": [],
                "authorized_action": None,
            },
            "result": {
                "metrics": {"score": 109.0},
                "constraints": [],
                "resource_usage": {},
                "artifacts": [
                    {
                        "path": path,
                        "media_type": "application/json",
                        "retention": "run",
                        "sensitivity": "internal",
                        "sha256": digest,
                        "size_bytes": size,
                    }
                    for _, digest, path, size in artifacts
                ],
                "provenance": {},
                "diagnostics": [],
            },
            "authorized_action": None,
        },
        event_id="evt_m2b_replication_terminal",
        occurred_at="2026-08-11T03:10:04.000000Z",
    )
    events = project_log.read()
    state = reduce_scientific_state(events, project_id=project_log.project_id)
    diagnosis = build_diagnosis_template(state, experiment_id=experiment_id)
    diagnosis.update(
        {
            "interpretation": "The preregistered replication retained the verified improvement.",
            "failure_type": "supported",
            "falsifier": "A second sealed replication fails the frozen threshold.",
            "recommendation": "replicate",
        }
    )
    plan = plan_diagnosis_append(events, project_id=project_log.project_id, diagnosis=diagnosis)
    project_log.append(
        DIAGNOSIS_EVENT_TYPE,
        plan.payload,
        event_id="evt_m2b_replication_diagnosis",
        occurred_at="2026-08-11T03:10:05.000000Z",
    )
    return plan.diagnosis_id


def _claim_from_origin(
    project_log: EventLog,
    origin: OriginEvidenceRef,
    binding: ProgramBinding,
    *,
    statement: dict[str, Any],
) -> Claim:
    state = reduce_scientific_state(
        project_log.read()[: origin.project_head_sequence], project_id=project_log.project_id
    )
    diagnosis = next(item for item in state.diagnoses if item.diagnosis_id == origin.diagnosis_id)
    raw = {
        "claim_schema_version": 1,
        "claim_id": "claim_placeholder",
        "statement": copy.deepcopy(statement),
        "applicability": {
            "claim_applicability_schema_version": 1,
            "project_id": binding.project_id,
            "generation_id": binding.generation_id,
            "hypothesis_class_id": diagnosis.diagnosis.hypothesis_class_id,
            "evaluation_scope": {
                "id": binding.evaluation_scope_id,
                "role": binding.evaluation_scope_role,
                "manifest_digest": binding.evaluation_scope_manifest_digest,
            },
            "evaluation_scope_digest": binding.evaluation_scope_digest,
            "evaluation_seal_digest": binding.evaluation_seal_digest,
            "compatibility_digest": binding.compatibility_digest,
            "authorized_action": None,
        },
        "evidence": {
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
            "terminal_evidence": diagnosis.diagnosis.terminal_evidence.to_dict(),
            "artifact_evidence": [
                item.to_dict() for item in diagnosis.diagnosis.artifact_evidence
            ],
            "evaluation_seal_digest": binding.evaluation_seal_digest,
            "compatibility_digest": binding.compatibility_digest,
            "authorized_action": None,
        },
        "claim_status": "active",
        "claim_maturity": "observed",
        "limitations": ["This observation remains bounded to its exact sealed scope."],
        "authorized_action": None,
    }
    _rebind_claim(raw)
    return Claim.from_mapping(raw)


def _replication_claims(
    root: Path, *, append_source: bool = True
) -> tuple[EventLog, ProgramStore, Claim, Claim, ProgramEvent]:
    project_log = _project_log(root)
    replication_diagnosis_id = _append_replication_history(project_log)
    manifest = ProgramManifest.from_mapping(
        _manifest_raw(
            _binding_for_scope(project_log, "development"),
            _binding_for_scope(project_log, "replication-1"),
        )
    )
    store = ProgramStore(root / "program", manifest.program_id)
    head = store.initialize(manifest, {project_log.project_id: project_log})
    development_id = M2A["fixtures"]["origin"]["diagnosis_id"]
    development_origin, head = store.link_origin(
        project_log, development_id, expected_program_head=(head.sequence, head.hash)
    )
    replication_origin, head = store.link_origin(
        project_log,
        replication_diagnosis_id,
        expected_program_head=(head.sequence, head.hash),
    )
    statement = copy.deepcopy(ORACLE["fixtures"]["valid_claim"]["statement"])
    target = _claim_from_origin(
        project_log,
        development_origin,
        manifest.binding(project_log.project_id, development_origin.generation_id, "development"),
        statement=statement,
    )
    source = _claim_from_origin(
        project_log,
        replication_origin,
        manifest.binding(project_log.project_id, replication_origin.generation_id, "replication-1"),
        statement=statement,
    )
    target, head = _append_claim(store, project_log, head, target.to_dict(), "rep_target")
    if append_source:
        source, head = _append_claim(store, project_log, head, source.to_dict(), "rep_source")
    return project_log, store, target, source, head


def _replicates(root: Path) -> dict[str, Any]:
    _, store, target, source, head = _replication_claims(root)
    relation = ClaimRelation.from_mapping(
        _relation_raw("replicates", source.claim_id, target.claim_id)
    )
    store.append_relation(relation, expected_program_head=(head.sequence, head.hash))
    snapshot = store.claim_snapshot()
    target_view = snapshot.claim(target.claim_id)
    source_view = snapshot.claim(source.claim_id)
    return {
        "target_effective_maturity": target_view.effective_maturity,
        "source_effective_maturity": source_view.effective_maturity,
        "replication_count": len(target_view.replicated_by),
        "relation_count": len(snapshot.relations),
    }


def _relation_no_write(
    store: ProgramStore, relation: ClaimRelation, head: ProgramEvent
) -> dict[str, Any]:
    before_log = store.log.path.read_bytes()
    before_relations = len(store.claim_snapshot().relations)
    with pytest.raises(ProgramMemoryError) as caught:
        store.append_relation(relation, expected_program_head=(head.sequence, head.hash))
    assert store.log.path.read_bytes() == before_log
    return {"error_code": caught.value.code,
            "relation_delta": len(store.claim_snapshot().relations) - before_relations}


def _duplicate_relation(root: Path) -> dict[str, Any]:
    _, store, target, source, head = _two_same_scope_claims(root)
    first = ClaimRelation.from_mapping(_relation_raw("supports", source.claim_id, target.claim_id))
    head = store.append_relation(first, expected_program_head=(head.sequence, head.hash))
    duplicate = ClaimRelation.from_mapping(
        _relation_raw(
            "supports", source.claim_id, target.claim_id, rationale="A different duplicate rationale."
        )
    )
    return _relation_no_write(store, duplicate, head)


def _unknown_relation(root: Path) -> dict[str, Any]:
    project_log, store, head = _initialize(root)
    claim, head = _append_claim(store, project_log, head, _claim_raw(), "known")
    unknown = "claim_00000000000000000000000000000000"
    relation = ClaimRelation.from_mapping(_relation_raw("supports", claim.claim_id, unknown))
    return _relation_no_write(store, relation, head)


def _immutable(root: Path) -> dict[str, Any]:
    _, store, target, source, head = _two_same_scope_claims(root)
    before = canonical_bytes(target.to_dict())
    before_digest = target.digest
    relation = ClaimRelation.from_mapping(
        _relation_raw("supersedes", source.claim_id, target.claim_id)
    )
    store.append_relation(relation, expected_program_head=(head.sequence, head.hash))
    target_view = store.claim_snapshot().claim(target.claim_id)
    source_view = store.claim_snapshot().claim(source.claim_id)
    return {
        "original_claim_bytes_unchanged": canonical_bytes(target_view.claim.to_dict()) == before,
        "original_claim_digest_unchanged": target_view.claim.digest == before_digest,
        "target_effective_status": target_view.effective_status,
        "source_effective_status": source_view.effective_status,
    }


def _three_claims(root: Path) -> tuple[ProgramStore, list[Claim], ProgramEvent]:
    project_log, store, head = _initialize(root)
    claims = []
    for index in range(3):
        raw = _claim_raw()
        raw["statement"]["summary"] = f"Bounded supersession candidate {index}."
        _rebind_claim(raw)
        claim, head = _append_claim(store, project_log, head, raw, f"chain_{index}")
        claims.append(claim)
    return store, claims, head


def _second_successor(root: Path) -> dict[str, Any]:
    store, claims, head = _three_claims(root)
    first = ClaimRelation.from_mapping(_relation_raw("supersedes", claims[1].claim_id, claims[0].claim_id))
    head = store.append_relation(first, expected_program_head=(head.sequence, head.hash))
    second = ClaimRelation.from_mapping(_relation_raw("supersedes", claims[2].claim_id, claims[0].claim_id))
    return _relation_no_write(store, second, head)


def _cycle(root: Path) -> dict[str, Any]:
    _, store, target, source, head = _two_same_scope_claims(root)
    forward = ClaimRelation.from_mapping(_relation_raw("supersedes", source.claim_id, target.claim_id))
    head = store.append_relation(forward, expected_program_head=(head.sequence, head.hash))
    reverse = ClaimRelation.from_mapping(_relation_raw("supersedes", target.claim_id, source.claim_id))
    return _relation_no_write(store, reverse, head)


def _synthetic_binding(
    label: str, *, role: str, manifest_digest: str, seal_digest: str | None = None,
    compatibility_digest: str | None = None,
) -> dict[str, Any]:
    target = M2A["fixtures"]["binding"]
    project_id = f"fixture-m2b-{label}"
    scope = {"id": f"{role}-{label}", "role": role, "manifest_digest": manifest_digest}
    return {
        "project_id": project_id,
        "science_state_schema_version": 1,
        "study_contract_schema_version": 2,
        "study_contract_digest": sha256_json({"contract": label}),
        "generation_id": stable_id("generation", project_id),
        "evaluation_scope_schema_version": 1,
        "evaluation_scope": scope,
        "evaluation_scope_digest": sha256_json({
            "evaluation_scope_schema_version": 1, "evaluation_scope": scope
        }),
        "evaluation_seal_digest": seal_digest or target["evaluation_seal_digest"],
        "compatibility_digest": compatibility_digest or target["compatibility_digest"],
        "authorized_action": None,
    }


def _synthetic_origin(
    binding: ProgramBinding, label: str, *, hypothesis_class_id: str = "class-a"
) -> OriginEvidenceRef:
    project_head = {"sequence": 3, "hash": sha256_json({"head": label})}
    diagnosis_id = stable_id("diagnosis", label)
    diagnosis_digest = sha256_json({"diagnosis": label})
    class_state_id = stable_id("classstate", binding.project_id, binding.generation_id,
                               hypothesis_class_id)
    class_state_digest = sha256_json({"class-state": label})
    raw = {
        "origin_evidence_schema_version": 1,
        "origin_id": "origin_placeholder",
        "project_id": binding.project_id,
        "project_head": project_head,
        "generation_id": binding.generation_id,
        "evaluation_scope_id": binding.evaluation_scope_id,
        "diagnosis_event": {"sequence": 2, "event_id": stable_id("event", "diagnosis", label),
                            "event_hash": sha256_json({"diagnosis-event": label})},
        "diagnosis_id": diagnosis_id,
        "diagnosis_digest": diagnosis_digest,
        "class_state_id": class_state_id,
        "class_state_digest": class_state_digest,
        "authorized_action": None,
    }
    raw["origin_id"] = stable_id(
        "origin", binding.project_id, project_head, binding.generation_id,
        binding.evaluation_scope_id, diagnosis_id, diagnosis_digest,
        class_state_id, class_state_digest,
    )
    return OriginEvidenceRef.from_mapping(raw)


def _synthetic_claim(
    binding: ProgramBinding, origin: OriginEvidenceRef, label: str, *,
    hypothesis_class_id: str = "class-a",
) -> Claim:
    raw = _claim_raw()
    raw["applicability"].update(
        {
            "project_id": binding.project_id,
            "generation_id": binding.generation_id,
            "hypothesis_class_id": hypothesis_class_id,
            "evaluation_scope": {"id": binding.evaluation_scope_id,
                                 "role": binding.evaluation_scope_role,
                                 "manifest_digest": binding.evaluation_scope_manifest_digest},
            "evaluation_scope_digest": binding.evaluation_scope_digest,
            "evaluation_seal_digest": binding.evaluation_seal_digest,
            "compatibility_digest": binding.compatibility_digest,
        }
    )
    raw["evidence"].update(
        {
            "origin_id": origin.origin_id,
            "origin_digest": origin.digest,
            "diagnosis_event": {"sequence": origin.diagnosis_event_sequence,
                                "event_id": origin.diagnosis_event_id,
                                "event_hash": origin.diagnosis_event_hash},
            "diagnosis_id": origin.diagnosis_id,
            "diagnosis_digest": origin.diagnosis_digest,
            "evaluation_seal_digest": binding.evaluation_seal_digest,
            "compatibility_digest": binding.compatibility_digest,
        }
    )
    raw["limitations"] = [f"Synthetic no-write witness: {label}."]
    _rebind_claim(raw)
    return Claim.from_mapping(raw)


def _direct_program(
    root: Path, bindings: list[ProgramBinding], origins: list[OriginEvidenceRef],
    claims: list[Claim],
) -> tuple[ProgramStore, ProgramEvent]:
    manifest = ProgramManifest.from_mapping(
        _manifest_raw(*(item.to_dict() for item in sorted(bindings, key=lambda item: item.key)))
    )
    store = ProgramStore(root / "direct-program", manifest.program_id)
    head = store.log.append(
        PROGRAM_INITIALIZED_EVENT,
        {"program_manifest": manifest.to_dict(), "program_manifest_digest": manifest.digest,
         "authorized_action": None},
        expected_head=(0, None),
    )
    for origin in origins:
        head = store.log.append(
            PROGRAM_ORIGIN_LINKED_EVENT,
            {"origin_evidence": origin.to_dict(), "origin_evidence_digest": origin.digest,
             "authorized_action": None},
            expected_head=(head.sequence, head.hash),
        )
    for claim in claims:
        head = store.log.append(
            PROGRAM_CLAIM_RECORDED_EVENT,
            claim_event_payload(claim),
            expected_head=(head.sequence, head.hash),
        )
    return store, head


def _relation_rejection(root: Path, mutation: str) -> dict[str, Any]:
    target_binding = ProgramBinding.from_mapping(M2A["fixtures"]["binding"])
    target_origin = OriginEvidenceRef.from_mapping(M2A["fixtures"]["origin"])
    target = Claim.from_mapping(_claim_raw())
    relation_type = "supports"
    hypothesis_class_id = "class-a"
    if mutation == "same_scope_different_origin":
        binding_raw = _synthetic_binding(mutation, role="replication", manifest_digest="c" * 64)
        target_binding = ProgramBinding.from_mapping(binding_raw)
        source_binding = target_binding
        target_origin = _synthetic_origin(target_binding, f"{mutation}-target")
        target = _synthetic_claim(target_binding, target_origin, f"{mutation}-target")
        relation_type = "replicates"
    else:
        role = "diagnostic" if mutation == "wrong_role" else "replication"
        manifest_digest = (target_binding.evaluation_scope_manifest_digest
                           if mutation == "overlap"
                           else sha256_json({"scope-manifest": mutation}))
        source_binding = ProgramBinding.from_mapping(
            _synthetic_binding(
                mutation,
                role=role,
                manifest_digest=manifest_digest,
                seal_digest="a" * 64 if mutation == "seal" else None,
                compatibility_digest="a" * 64 if mutation == "compatibility" else None,
            )
        )
        if mutation in {"wrong_role", "class"}:
            relation_type = "replicates"
        if mutation == "class":
            hypothesis_class_id = "class-b"
    source_origin = _synthetic_origin(
        source_binding, f"{mutation}-source", hypothesis_class_id=hypothesis_class_id
    )
    source = _synthetic_claim(source_binding, source_origin, f"{mutation}-source",
                              hypothesis_class_id=hypothesis_class_id)
    store, head = _direct_program(
        root,
        list({item.key: item for item in (target_binding, source_binding)}.values()),
        [target_origin, source_origin],
        [target, source],
    )
    relation = ClaimRelation.from_mapping(
        _relation_raw(relation_type, source.claim_id, target.claim_id)
    )
    before_log = store.log.path.read_bytes()
    before_relations = len(store.claim_snapshot().relations)
    with pytest.raises(ProgramMemoryError) as caught:
        store.append_relation(relation, expected_program_head=(head.sequence, head.hash))
    assert store.log.path.read_bytes() == before_log
    return {
        "error_code": caught.value.code,
        "relation_delta": len(store.claim_snapshot().relations) - before_relations,
    }


def _same_origin_replication(root: Path) -> dict[str, Any]:
    _, store, target, source, head = _two_same_scope_claims(root, same_statement=True)
    relation = ClaimRelation.from_mapping(
        _relation_raw("replicates", source.claim_id, target.claim_id)
    )
    return _relation_no_write(store, relation, head)


Operation = Callable[[Path], dict[str, Any]]
OPERATIONS: dict[str, Operation] = {
    "parse_valid_claim": _parse_valid_claim,
    "reject_claim_extra_key": _reject_extra,
    "reject_claim_unknown_version": _reject_version,
    "reject_claim_forged_initial_status": _reject_status,
    "reject_claim_forged_initial_maturity": _reject_maturity,
    "append_exact_evidence_claim": _append_exact,
    "reject_claim_origin_digest_forgery": lambda root: _forged_claim(root, "origin"),
    "reject_claim_diagnosis_event_hash_forgery": lambda root: _forged_claim(root, "diagnosis"),
    "reject_claim_terminal_event_hash_forgery": lambda root: _forged_claim(root, "terminal"),
    "reject_claim_artifact_digest_forgery": lambda root: _forged_claim(root, "artifact"),
    "reject_claim_evaluation_seal_forgery": lambda root: _forged_claim(root, "seal"),
    "reject_claim_hypothesis_class_forgery": lambda root: _forged_claim(root, "class"),
    "reduce_supports_relation": _supports,
    "reduce_contradicts_relation": _contradicts,
    "reduce_supersedes_relation": _supersedes,
    "reduce_replicates_relation": _replicates,
    "reject_duplicate_relation_triple": _duplicate_relation,
    "reject_unknown_relation_claim": _unknown_relation,
    "verify_immutable_supersession": _immutable,
    "reject_second_successor": _second_successor,
    "reject_supersession_cycle": _cycle,
    "reject_relation_incompatible_seal": lambda root: _relation_rejection(root, "seal"),
    "reject_relation_incompatible_compatibility": lambda root: _relation_rejection(
        root, "compatibility"
    ),
    "reject_relation_overlapping_manifest": lambda root: _relation_rejection(root, "overlap"),
    "reject_same_origin_replication": _same_origin_replication,
}


def test_m2b_frozen_sources_ids_and_dispatch_are_exact() -> None:
    assert _sha256(M2A_PATH) == ORACLE["source"]["m2a_manifest_raw_sha256"]
    assert _sha256(M1D_ROOT / "m1d-diagnosis-valid.json") == ORACLE["source"][
        "diagnosis_valid_raw_sha256"
    ]
    assert len(CASE_IDS) == len(CASES) == len(OPERATIONS) == 25
    assert set(OPERATIONS) == {case["operation"] for case in ORACLE["cases"]}
    assert ORACLE["comparison"] == "exact canonical JSON equality"
    claim = Claim.from_mapping(_claim_raw())
    assert claim.digest == ORACLE["fixtures"]["valid_claim_digest"]


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_m2b_frozen_case(case_id: str, tmp_path: Path) -> None:
    actual = OPERATIONS[CASES[case_id]["operation"]](tmp_path)
    assert canonical_bytes(actual) == canonical_bytes(CASES[case_id]["expected"])


@pytest.mark.parametrize("mutation", ["omission", "addition", "substitution", "reorder"])
def test_complete_artifact_set_mutations_are_no_write(mutation: str, tmp_path: Path) -> None:
    project_log, store, _, source, head = _replication_claims(
        tmp_path, append_source=False
    )
    raw = source.to_dict()
    artifacts = raw["evidence"]["artifact_evidence"]
    assert len(artifacts) == 2
    fake = copy.deepcopy(artifacts[0])
    fake.update(
        {
            "artifact_id": stable_id("artifact", "m2b-addition"),
            "artifact_digest": "1" * 64,
            "event_id": stable_id("event", "m2b-addition"),
            "event_hash": "2" * 64,
        }
    )
    if mutation == "omission":
        artifacts.pop()
    elif mutation == "addition":
        artifacts.append(fake)
        artifacts.sort(key=lambda item: item["artifact_id"])
    elif mutation == "substitution":
        artifacts[0]["artifact_digest"] = "3" * 64
    else:
        artifacts.reverse()
    _rebind_claim(raw)
    before_log = store.log.path.read_bytes()
    before_claims = len(store.claim_snapshot().claims)
    before_projection = store.projection.path.read_bytes()
    with pytest.raises(ProgramMemoryError) as caught:
        store.append_claim(
            raw,
            project_log,
            expected_program_head=(head.sequence, head.hash),
        )
    assert caught.value.code == (
        "CLAIM_INVALID" if mutation == "reorder" else "CLAIM_EVIDENCE_MISMATCH"
    )
    assert store.log.path.read_bytes() == before_log
    assert len(store.claim_snapshot().claims) == before_claims
    assert store.projection.path.read_bytes() == before_projection


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [("wrong_role", "CLAIM_REPLICATION_NOT_INDEPENDENT"),
     ("same_scope_different_origin", "CLAIM_REPLICATION_NOT_INDEPENDENT"),
     ("class", "CLAIM_SCOPE_INCOMPATIBLE")],
)
def test_replication_counterfactuals_are_writer_no_write(
    mutation: str, expected_code: str, tmp_path: Path
) -> None:
    assert _relation_rejection(tmp_path, mutation) == {
        "error_code": expected_code,
        "relation_delta": 0,
    }


def test_same_origin_different_scope_claim_is_writer_no_write(tmp_path: Path) -> None:
    target_binding = ProgramBinding.from_mapping(M2A["fixtures"]["binding"])
    target_origin = OriginEvidenceRef.from_mapping(M2A["fixtures"]["origin"])
    other_raw = copy.deepcopy(M2A["fixtures"]["binding"])
    other_raw["evaluation_scope"] = {
        "id": "replication-1", "role": "replication", "manifest_digest": "c" * 64
    }
    other_raw["evaluation_scope_digest"] = sha256_json(
        {"evaluation_scope_schema_version": 1, "evaluation_scope": other_raw["evaluation_scope"]}
    )
    other_binding = ProgramBinding.from_mapping(other_raw)
    target = Claim.from_mapping(_claim_raw())
    store, head = _direct_program(tmp_path, [target_binding, other_binding], [target_origin], [target])
    invalid = _synthetic_claim(other_binding, target_origin, "same-origin-different-scope")
    project_log = _project_log(tmp_path)
    before_log = store.log.path.read_bytes()
    before_claims = len(store.claim_snapshot().claims)
    with pytest.raises(ProgramMemoryError) as caught:
        store.append_claim(invalid, project_log, expected_program_head=(head.sequence, head.hash))
    assert caught.value.code == "CLAIM_EVIDENCE_MISMATCH"
    assert store.log.path.read_bytes() == before_log
    assert len(store.claim_snapshot().claims) == before_claims


def test_mixed_relation_precedence_is_deterministic_and_claims_are_immutable() -> None:
    target_raw = _claim_raw()
    support_raw = _claim_raw()
    support_raw["statement"]["summary"] = "Support source."
    _rebind_claim(support_raw)
    contradiction_raw = _claim_raw()
    contradiction_raw["statement"]["summary"] = "Contradiction source."
    _rebind_claim(contradiction_raw)
    successor_raw = _claim_raw()
    successor_raw["statement"]["summary"] = "Successor source."
    _rebind_claim(successor_raw)
    target, support, contradiction, successor = map(
        Claim.from_mapping, [target_raw, support_raw, contradiction_raw, successor_raw]
    )
    original = canonical_bytes(target.to_dict())
    relations = [
        ClaimRelation.from_mapping(_relation_raw("supports", support.claim_id, target.claim_id)),
        ClaimRelation.from_mapping(
            _relation_raw("contradicts", contradiction.claim_id, target.claim_id)
        ),
        ClaimRelation.from_mapping(
            _relation_raw("supersedes", successor.claim_id, target.claim_id)
        ),
    ]
    snapshot = reduce_claim_records(
        [target, support, contradiction, successor, *relations],
        program_id=M2A["fixtures"]["program_id"],
        program_head=(8, "e" * 64),
    )
    view = snapshot.claim(target.claim_id)
    assert view is not None and view.effective_status == "superseded"
    assert canonical_bytes(view.claim.to_dict()) == original


def test_new_claim_surfaces_recursively_have_null_authority(tmp_path: Path) -> None:
    snapshot, _, _ = _relation_view(tmp_path, "contradicts")
    values: list[Any] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "authorized_action":
                    values.append(child)
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(snapshot.to_dict())
    assert len(values) >= 10
    assert all(value is None for value in values)


def test_claim_snapshot_strict_parser_replays_and_rejects_forged_state(tmp_path: Path) -> None:
    snapshot, _, _ = _relation_view(tmp_path, "contradicts")
    parsed = ClaimSnapshot.from_mapping(snapshot.to_dict())
    assert parsed.to_dict() == snapshot.to_dict()
    forged = snapshot.to_dict()
    forged["claims"][0]["effective_status"] = "active"
    with pytest.raises(ProgramMemoryError) as caught:
        ClaimSnapshot.from_mapping(forged)
    assert caught.value.code == "CLAIM_PROJECTION_INVALID"
