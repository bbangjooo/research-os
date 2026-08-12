from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest

from research_os.agent import build_agent_context_v3, validate_agent_context_v3_retrieval
from research_os.autonomy import (
    AutonomyLoopError,
    AutonomyPolicy,
    DecisionPacketError,
    FiniteAutonomyLoop,
    NextQueryPlan,
    ProviderDecisionRequest,
    ProviderDiagnosisPacket,
    ProviderDiagnosisRequest,
    ProviderPortError,
    ProviderSynthesisPacket,
    ProviderSynthesisRequest,
    build_decision_packet,
    canonical_token_units,
    reduce_autonomy_events,
    verify_autonomy_evidence,
)
from research_os.contracts import canonical_json_bytes, sha256_json
from research_os.kernel.ids import new_experiment_id, stable_id
from research_os.memory import (
    Claim,
    ClaimRelation,
    OriginEvidenceRef,
    ProgramManifest,
    ProgramSnapshot,
    ProgramStore,
    RetrievalQuery,
    create_proposal_knowledge_disposition,
)
from research_os.science import (
    Diagnosis,
    Proposal,
    proposal_id,
    reduce_scientific_state,
    registration_payload_fields,
)
from research_os.service import ResearchService
from tests.test_m1c_service_cli import _scoped_project
from tests.test_m2d_knowledge_disposition import _entry, _real_vertical

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/autonomy/v1/m3b-manifest.json"
MANIFEST_BYTES = MANIFEST_PATH.read_bytes()
MANIFEST = json.loads(MANIFEST_BYTES)
CASES = tuple(MANIFEST["cases"])
M1D_ROOT = ROOT / "tests/fixtures/scientific_state/v3"


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _pending_history(vertical: dict[str, Any]) -> tuple[Any, Any]:
    valid = _json(M1D_ROOT / "m1d-diagnosis-valid.json")
    corpus = _json(M1D_ROOT / "m1d-terminal-corpus.json")
    diagnosis_case = next(
        item for item in valid["cases"] if item["id"] == "conclusive-no-meaningful-improvement"
    )
    record = next(
        item for item in corpus["records"] if item["id"] == diagnosis_case["terminal_record_id"]
    )
    appended = []
    for raw in record["canonical_history"][2:]:
        appended.append(
            vertical["project_log"].append(
                raw["event_type"],
                copy.deepcopy(raw["payload"]),
                event_id=raw["event_id"],
                occurred_at=raw["occurred_at"],
            )
        )
    state = reduce_scientific_state(
        vertical["project_log"].read(), project_id=vertical["project_log"].project_id
    )
    pending_id = state.pending_diagnosis_experiment_ids[0]
    registration = state.registration(pending_id)
    terminal = next(
        event
        for event in appended
        if event.payload.get("experiment_id", event.payload.get("id")) == pending_id
        and event.sequence == registration.terminal_event_sequence
    )
    return registration, terminal


def _expanded_store(root: Path, vertical: dict[str, Any]) -> tuple[Any, Any]:
    prior, _ = vertical["store"].snapshot()
    raw_binding = prior.program_manifest.bindings[0].to_dict()
    scope = {"id": "diagnostic-1", "role": "diagnostic", "manifest_digest": "c" * 64}
    raw_binding["evaluation_scope"] = scope
    raw_binding["evaluation_scope_digest"] = sha256_json(
        {"evaluation_scope_schema_version": 1, "evaluation_scope": scope}
    )
    manifest = ProgramManifest.from_mapping(
        {
            "program_manifest_schema_version": 1,
            "program_id": prior.program_id,
            "bindings": [prior.program_manifest.bindings[0].to_dict(), raw_binding],
            "authorized_action": None,
        }
    )
    store = ProgramStore(root / "expanded-program", manifest.program_id)
    head = store.initialize(manifest, {vertical["project_log"].project_id: vertical["project_log"]})
    for origin in prior.origins:
        head = store.append_origin(
            origin,
            vertical["project_log"],
            expected_program_head=(head.sequence, head.hash),
        )
    claims = vertical["store"].claim_snapshot()
    for view in claims.claims:
        head = store.append_claim(
            view.claim,
            vertical["project_log"],
            expected_program_head=(head.sequence, head.hash),
        )
    for relation in claims.relations:
        head = store.append_relation(
            relation, expected_program_head=(head.sequence, head.hash)
        )
    query_raw = vertical["result"].query.to_dict()
    query_raw["query_id"] = "query_m3b-current-program-head"
    query_raw["program_head"] = {"sequence": head.sequence, "hash": head.hash}
    return store, RetrievalQuery.from_mapping(query_raw)


class _ReplayResearchService:
    """Public ResearchService diagnosis code plus one sealed replay-run fixture."""

    record_diagnosis = ResearchService.record_diagnosis
    diagnosis_template = ResearchService.diagnosis_template

    def __init__(self, root: Path, project_log: Any):
        runtime = root / "runtime"
        runtime.mkdir()
        self.config = SimpleNamespace(
            project_id=project_log.project_id,
            root=root,
            resolved_runtime_dir=runtime,
        )
        self.event_log = project_log
        self.terminal = None
        self.run_once_calls = 0
        self.adapter_direct_calls = 0
        self.workspace_direct_calls = 0

    def _assert_config_unchanged(self) -> None:
        return None

    def _sync(self) -> None:
        return None

    def project_token(self) -> str:
        head = self.event_log.read()[-1]
        return sha256_json({"project_id": self.config.project_id, "head": [head.sequence, head.hash]})

    def agent_context(self, *, limit: int, schema_version: int) -> dict[str, Any]:
        assert schema_version == 3
        head = self.event_log.read()[-1]
        science = reduce_scientific_state(
            self.event_log.read(), project_id=self.config.project_id
        )
        return build_agent_context_v3(
            project={},
            status={},
            lineage=[],
            findings=[],
            artifacts=[],
            agent_spec={},
            snapshot={
                "schema_version": 2,
                "project_id": self.config.project_id,
                "last_sequence": head.sequence,
                "last_hash": head.hash,
                "context_token": self.project_token(),
            },
            scientific_state=science.to_dict(),
            limit=limit,
        )

    def run_once(
        self,
        candidate_path: Path,
        *,
        context_token: str,
        proposal: Mapping[str, Any],
    ) -> dict[str, Any]:
        self.run_once_calls += 1
        assert context_token == self.project_token()
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        parsed_proposal = Proposal.from_mapping(proposal)
        state = reduce_scientific_state(
            self.event_log.read(), project_id=self.config.project_id
        )
        assert state.active_generation_id is not None and state.evaluation_seal is not None
        experiment_id = new_experiment_id(
            self.config.project_id,
            sha256_json(candidate),
            compatibility_digest=state.evaluation_seal.compatibility_digest,
            parent_id=parsed_proposal.parent_experiment_id,
            generation_id=state.active_generation_id,
            evaluation_scope_id=parsed_proposal.evaluation_scope_id,
            attempt=1,
        )
        template = next(
            copy.deepcopy(event.payload)
            for event in self.event_log.read()
            if event.event_type == "EXPERIMENT_REGISTERED"
        )
        template.update(
            {
                "experiment_id": experiment_id,
                "parent_id": parsed_proposal.parent_experiment_id,
                "candidate_digest": sha256_json(candidate),
                "candidate": candidate,
                "attempt": 1,
                "retry_of": None,
                "status": "registered",
                **registration_payload_fields(state, retry_of=None),
                "proposal": parsed_proposal.to_dict(),
                "proposal_digest": parsed_proposal.digest,
                "proposal_id": proposal_id(self.config.project_id, parsed_proposal.digest),
                "evaluation_scope_id": parsed_proposal.evaluation_scope_id,
                "authorized_action": None,
            }
        )
        self.event_log.append("EXPERIMENT_REGISTERED", template)
        self.terminal = self.event_log.append(
            "EXPERIMENT_STATUS_CHANGED",
            {"experiment_id": experiment_id, "status": "COMPLETED", "authorized_action": None},
        )
        return {
            "experiment_id": experiment_id,
            "status": "COMPLETED",
            "reason_code": "STATUS_CHANGED",
            "attempt": 1,
            "retry_of": None,
            "retryable": False,
            "verified": False,
            "primary_metric": None,
            "authorized_action": None,
            "project_id": self.config.project_id,
            "event_sequence": self.terminal.sequence,
        }


class _EpisodeProvider:
    def __init__(
        self,
        project_id: str,
        store: Any,
        proposal: Any,
        candidate: Mapping[str, Any],
        entries: Sequence[Any],
        *,
        decision: str,
        failure: str | None = None,
    ) -> None:
        self.project_id = project_id
        self.store = store
        self.proposal = proposal
        self.candidate = dict(candidate)
        self.entries = tuple(entries)
        self.decision = decision
        self.failure = failure
        self.calls: list[str] = []
        self.proposal_requests: list[ProviderDecisionRequest] = []

    def _claim(self, request: ProviderSynthesisRequest) -> Claim:
        diagnosis = Diagnosis.from_mapping(cast(Mapping[str, Any], request.diagnosis))
        origin = OriginEvidenceRef.from_mapping(
            cast(Mapping[str, Any], request.origin_evidence)
        )
        snapshot = ProgramSnapshot.from_mapping(
            cast(Mapping[str, Any], request.program_snapshot)
        )
        binding = snapshot.program_manifest.binding(
            origin.project_id, origin.generation_id, origin.evaluation_scope_id
        )
        assert binding is not None
        raw = {
            "claim_schema_version": 1,
            "claim_id": "claim_placeholder",
            "statement": {
                "kind": "effect",
                "summary": "The exact terminal Diagnosis changed the next bounded research context.",
                "falsifier": "A compatible replication fails to reproduce this evidence-bound effect.",
            },
            "applicability": {
                "claim_applicability_schema_version": 1,
                "project_id": origin.project_id,
                "generation_id": origin.generation_id,
                "hypothesis_class_id": diagnosis.hypothesis_class_id,
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
                "terminal_evidence": diagnosis.terminal_evidence.to_dict(),
                "artifact_evidence": [item.to_dict() for item in diagnosis.artifact_evidence],
                "evaluation_seal_digest": binding.evaluation_seal_digest,
                "compatibility_digest": binding.compatibility_digest,
                "authorized_action": None,
            },
            "claim_status": "active",
            "claim_maturity": "observed",
            "limitations": ["Research evidence only; no production or live authority."],
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
        if self.failure == "claim_evidence":
            raw["evidence"]["diagnosis_digest"] = "f" * 64
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

    def invoke(self, request: Any) -> Mapping[str, Any]:
        if self.failure == "transport":
            raise ProviderPortError("PROVIDER_PROTOCOL_INVALID", "fixture transport failure")
        if isinstance(request, ProviderDecisionRequest):
            self.calls.append("proposal")
            self.proposal_requests.append(request)
            if self.failure == "proposal_transport":
                raise ProviderPortError(
                    "PROVIDER_PROTOCOL_INVALID", "fixture proposal transport failure"
                )
            if self.failure == "proposal":
                return {"invalid": True}
            proposal = self.proposal
            candidate = self.candidate
            if len(self.proposal_requests) > 1:
                candidate = {"x": len(self.proposal_requests) + 1}
                proposal_raw = self.proposal.to_dict()
                proposal_raw.update(
                    {
                        "candidate_digest": sha256_json(candidate),
                        "mechanism": "A subsequent finite-loop mechanism consumes the updated Program head.",
                        "predicted_effect": "The updated memory context yields a fresh sealed candidate.",
                        "falsifier": "The next packet cannot bind the updated Program head.",
                    }
                )
                proposal = Proposal.from_mapping(proposal_raw)
            retrieval = validate_agent_context_v3_retrieval(
                request.context,
                current_project_context_token=FiniteAutonomyLoop._project_token(
                    request.context
                ),
                current_claim_snapshot=self.store.claim_snapshot(),
            )
            disposition = create_proposal_knowledge_disposition(
                project_id=self.project_id,
                proposal=proposal,
                retrieval=retrieval,
                context_token=cast(str, request.context["snapshot"]["context_token"]),
                entries=[
                    *(_entry(hit, "used") for hit in retrieval.active),
                    *(_entry(hit, "rejected") for hit in retrieval.contradictions),
                ],
            )
            return build_decision_packet(
                request=request,
                project_id=self.project_id,
                candidate=candidate,
                proposal=proposal,
                knowledge_disposition=disposition,
                retrieval=retrieval,
            ).to_dict()
        if isinstance(request, ProviderDiagnosisRequest):
            self.calls.append("diagnosis")
            if self.failure == "diagnosis_transport":
                raise ProviderPortError(
                    "PROVIDER_PROTOCOL_INVALID", "fixture diagnosis transport failure"
                )
            if self.failure == "diagnosis":
                return {"invalid": True}
            diagnosis = json.loads(canonical_json_bytes(request.diagnosis_template))
            diagnosis.update(
                {
                    "interpretation": "The isolated mechanism did not clear its frozen threshold.",
                    "failure_type": "mechanism",
                    "falsifier": "A compatible replication clears the threshold.",
                    "recommendation": "ablate",
                }
            )
            return ProviderDiagnosisPacket(
                1,
                request.provider_request_id,
                request.episode_id,
                Diagnosis.from_mapping(diagnosis),
            ).to_dict()
        assert isinstance(request, ProviderSynthesisRequest)
        self.calls.append("synthesis")
        if self.failure == "synthesis_transport":
            raise ProviderPortError(
                "PROVIDER_PROTOCOL_INVALID", "fixture synthesis transport failure"
            )
        claim = self._claim(request)
        diagnosis = Diagnosis.from_mapping(cast(Mapping[str, Any], request.diagnosis))
        origin = OriginEvidenceRef.from_mapping(
            cast(Mapping[str, Any], request.origin_evidence)
        )
        class_ref = cast(Mapping[str, Any], request.class_state)
        plan = None
        reason = "provider_complete"
        if self.decision == "next":
            binding = ProgramSnapshot.from_mapping(
                cast(Mapping[str, Any], request.program_snapshot)
            ).program_manifest.bindings[0]
            plan = NextQueryPlan.from_mapping(
                {
                    "next_query_plan_schema_version": 1,
                    "hypothesis_class_id": diagnosis.hypothesis_class_id,
                    "compatibility_digest": binding.compatibility_digest,
                    "evaluation_scope": {
                        "id": binding.evaluation_scope_id,
                        "role": binding.evaluation_scope_role,
                        "manifest_digest": binding.evaluation_scope_manifest_digest,
                    },
                    "claim_kinds": ["effect"],
                    "diagnosis_digest": None,
                    "relation_types": ["contradicts"],
                    "limit": 10,
                    "authorized_action": None,
                }
            )
            reason = None
        return ProviderSynthesisPacket(
            1,
            request.provider_request_id,
            request.episode_id,
            origin.diagnosis_id,
            origin.diagnosis_digest,
            origin.origin_id,
            origin.digest,
            cast(str, class_ref["class_state_id"]),
            cast(str, class_ref["class_state_digest"]),
            claim,
            self.decision,
            plan,
            reason,
        ).to_dict()


@dataclass(slots=True)
class Harness:
    loop: FiniteAutonomyLoop
    service: Any
    store: Any
    provider: _EpisodeProvider
    episode_id: str

    def state(self) -> Any:
        return self.loop.episode(self.episode_id).state()

    def bytes(self) -> tuple[bytes, bytes, bytes]:
        return (
            self.service.event_log.path.read_bytes(),
            self.store.log.path.read_bytes(),
            self.loop.episode(self.episode_id).log.path.read_bytes(),
        )


def _policy(**changes: int) -> AutonomyPolicy:
    raw = {
        "autonomy_policy_schema_version": 1,
        "max_experiments": 2,
        "max_provider_calls": 6,
        "max_invalid_packets": 1,
        "max_token_units": 600_000,
        "max_elapsed_milliseconds": 10_000,
        "provider_token_reservation": 200_000,
        "provider_elapsed_reservation_milliseconds": 10,
        "context_limit": 10,
        "authorized_action": None,
    }
    raw.update(changes)
    return AutonomyPolicy.from_mapping(raw)


def _harness(
    root: Path,
    *,
    decision: str = "next",
    failure: str | None = None,
    policy: AutonomyPolicy | None = None,
) -> Harness:
    vertical = _real_vertical(root / "vertical")
    store, query = _expanded_store(root, vertical)
    state = reduce_scientific_state(
        vertical["project_log"].read(), project_id=vertical["project_log"].project_id
    )
    prior = state.registrations[0]
    candidate = {"x": 2}
    proposal_raw = prior.proposal.to_dict()
    proposal_raw.update(
        {
            "candidate_digest": sha256_json(candidate),
            "mechanism": "A fresh finite-loop mechanism consumes the bounded Program read set.",
            "predicted_effect": "One sealed experiment creates an exact Diagnosis and Claim writeback.",
            "falsifier": "The terminal evidence cannot support exact memory writeback.",
        }
    )
    proposal = Proposal.from_mapping(proposal_raw)
    service = _ReplayResearchService(root, vertical["project_log"])
    provider = _EpisodeProvider(
        service.config.project_id,
        store,
        proposal,
        candidate,
        vertical["disposition"].entries,
        decision=decision,
        failure=failure,
    )
    loop = FiniteAutonomyLoop(
        cast(Any, service),
        store,
        provider,
        autonomy_root=root / "autonomy",
    )
    state = loop.start(query, policy or _policy())
    return Harness(loop, service, store, provider, state.episode_id)


def _actual_service_harness(root: Path) -> Harness:
    _, service, proposal_raw = _scoped_project(root / "actual-service")
    service.baseline(evaluation_scope_id="development")
    seed_candidate = {"x": 2.0, "y": 1.0}
    seed_path = root / "actual-service-seed.json"
    seed_path.write_text(json.dumps(seed_candidate) + "\n", encoding="utf-8")
    seed_result = service.run_once(seed_path, proposal=proposal_raw)
    seed_diagnosis_raw = service.diagnosis_template(cast(str, seed_result["experiment_id"]))
    seed_diagnosis_raw.update(
        {
            "interpretation": "The actual sealed evaluator produced the seed observation.",
            "failure_type": "mechanism",
            "falsifier": "A compatible replication reverses the observed effect.",
            "recommendation": "ablate",
        }
    )
    seed_diagnosis = Diagnosis.from_mapping(seed_diagnosis_raw)
    seed_record = service.record_diagnosis(seed_diagnosis.to_dict())
    science = reduce_scientific_state(
        service.event_log.read(), project_id=service.config.project_id
    )
    assert science.contract is not None and science.evaluation_seal is not None
    scope = next(item for item in science.contract.evaluation_scopes if item.id == "development")
    scope_raw = {
        "id": scope.id,
        "role": scope.role,
        "manifest_digest": scope.manifest_digest,
    }
    manifest = ProgramManifest.from_mapping(
        {
            "program_manifest_schema_version": 1,
            "program_id": "program_m3b-actual-service",
            "bindings": [
                {
                    "project_id": service.config.project_id,
                    "science_state_schema_version": 1,
                    "study_contract_schema_version": science.contract.schema_version,
                    "study_contract_digest": science.contract.digest,
                    "generation_id": science.active_generation_id,
                    "evaluation_scope_schema_version": 1,
                    "evaluation_scope": scope_raw,
                    "evaluation_scope_digest": sha256_json(
                        {
                            "evaluation_scope_schema_version": 1,
                            "evaluation_scope": scope_raw,
                        }
                    ),
                    "evaluation_seal_digest": science.evaluation_seal.digest,
                    "compatibility_digest": science.evaluation_seal.compatibility_digest,
                    "authorized_action": None,
                }
            ],
            "authorized_action": None,
        }
    )
    store = ProgramStore(root / "actual-program", manifest.program_id)
    head = store.initialize(manifest, {service.config.project_id: service.event_log})
    origin, head = store.link_origin(
        service.event_log,
        cast(str, seed_record["diagnosis_id"]),
        expected_program_head=(head.sequence, head.hash),
    )
    seed_provider = _EpisodeProvider(
        service.config.project_id,
        store,
        Proposal.from_mapping(proposal_raw),
        seed_candidate,
        (),
        decision="stop",
    )
    seed_claim = seed_provider._claim(
        cast(
            Any,
            SimpleNamespace(
                diagnosis=seed_diagnosis.to_dict(),
                origin_evidence=origin.to_dict(),
                program_snapshot=store.snapshot()[0].to_dict(),
            ),
        )
    )
    store.append_claim(
        seed_claim,
        service.event_log,
        expected_program_head=(head.sequence, head.hash),
    )
    snapshot = store.claim_snapshot()
    query = RetrievalQuery.from_mapping(
        {
            "retrieval_query_schema_version": 1,
            "query_id": "query_m3b-actual-service",
            "program_id": snapshot.program_id,
            "program_head": {
                "sequence": snapshot.program_head[0],
                "hash": snapshot.program_head[1],
            },
            "hypothesis_class_id": "class-a",
            "compatibility_digest": science.evaluation_seal.compatibility_digest,
            "evaluation_scope": scope_raw,
            "claim_kinds": ["effect"],
            "diagnosis_digest": None,
            "relation_types": ["contradicts"],
            "limit": 10,
            "authorized_action": None,
        }
    )
    candidate = {"x": 3.0, "y": 1.0}
    proposal_raw.update(
        {
            "candidate_digest": sha256_json(candidate),
            "mechanism": "The actual loop changes one typed candidate value after memory retrieval.",
            "predicted_effect": "The sealed evaluator emits another evidence-bound terminal node.",
            "falsifier": "The actual service cannot execute the current typed proposal.",
        }
    )
    proposal = Proposal.from_mapping(proposal_raw)
    assert proposal.candidate_digest == sha256_json(candidate)
    provider = _EpisodeProvider(
        service.config.project_id,
        store,
        proposal,
        candidate,
        (),
        decision="stop",
    )
    loop = FiniteAutonomyLoop(
        service,
        store,
        provider,
        autonomy_root=root / "actual-autonomy",
    )
    state = loop.start(query, _policy())
    return Harness(loop, service, store, provider, state.episode_id)


def _reach(harness: Harness, phase: str) -> Any:
    while harness.state().phase != phase:
        state = harness.state()
        assert state.phase != "stop"
        harness.loop.advance(harness.episode_id, expected_phase=state.phase)
    return harness.state()


def _non_null_authority(value: object) -> int:
    if isinstance(value, Mapping):
        return int(value.get("authorized_action") is not None) + sum(
            _non_null_authority(item) for item in value.values()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return sum(_non_null_authority(item) for item in value)
    return 0


def _forbidden_surface(value: object) -> int:
    if isinstance(value, Mapping):
        return sum(key in {"deploy", "merge", "trade"} for key in value) + sum(
            _forbidden_surface(item) for item in value.values()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return sum(_forbidden_surface(item) for item in value)
    return int(callable(value) or isinstance(value, Path))


def _transition(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    expected = case["expected"]
    source = cast(str, expected["from"])
    harness = _harness(
        root,
        decision="stop" if expected["to"] == "stop" else "next",
    )
    _reach(harness, source)
    harness.loop.advance(harness.episode_id, expected_phase=source)
    state = harness.state()
    event = harness.loop.episode(harness.episode_id).read()[-1]
    assert state.phase == expected["to"]
    return {
        "from": source,
        "to": state.phase,
        "event_type": event.event_type,
        "authorized_action": event.payload["authorized_action"],
    }


def _memory(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    checkpoint = cast(str, case["checkpoint"])
    harness = _harness(root, decision="next")
    initial_program_events = len(harness.store.log.read())
    state = _reach(harness, "next")
    result = cast(Mapping[str, Any], state.current_context["memory"])["retrieval_result"]
    if checkpoint == "next_active":
        active = cast(Sequence[Mapping[str, Any]], result["active"])
        assert state.claim_history[-1]["claim_id"] in {
            cast(Mapping[str, Any], item["claim"])["claim_id"] for item in active
        }
        assert all(item["reasons"] for item in active)
    elif checkpoint == "next_contradictions":
        contradictions = cast(Sequence[Mapping[str, Any]], result["contradictions"])
        assert contradictions and all(item["relation_ids"] for item in contradictions)
    elif checkpoint == "disposition":
        assert len(state.disposition_history) == 1
        assert len(harness.store.log.read()) - initial_program_events == 3
    elif checkpoint == "origin":
        assert len(state.origin_history) == 1
        assert (
            state.origin_history[-1]["origin_evidence"]["diagnosis_id"]
            == state.diagnosis_history[-1]["diagnosis_id"]
        )
    elif checkpoint == "claim":
        claim_id = state.claim_history[-1]["claim_id"]
        view = next(item for item in harness.store.claim_snapshot().claims if item.claim.claim_id == claim_id)
        assert view.claim_digest == state.claim_history[-1]["claim_digest"]
        assert view.claim.evidence.diagnosis_id == state.diagnosis_history[-1]["diagnosis_id"]
    else:
        assert checkpoint == "class_state"
        assert state.class_state_history[-1]["class_state_digest"] == (
            state.origin_history[-1]["origin_evidence"]["class_state_digest"]
        )
    return copy.deepcopy(case["expected"])


def _idempotency(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    target = cast(str, case["checkpoint"]).replace("_", "-")
    source_by_checkpoint = {
        "context-to-proposal": "context",
        "proposal-to-preflight": "proposal",
        "preflight-to-run": "preflight",
        "run-to-diagnosis": "run",
        "diagnosis-to-synthesis": "diagnosis",
        "synthesis-to-next": "synthesis",
        "synthesis-to-stop": "synthesis",
    }
    source = source_by_checkpoint[target]
    harness = _harness(root, decision="stop" if target.endswith("stop") else "next")
    _reach(harness, source)
    harness.loop.advance(harness.episode_id, expected_phase=source)
    before = harness.bytes()
    state_before = harness.state().to_dict()
    repeated = harness.loop.advance(harness.episode_id, expected_phase=source)
    after = harness.bytes()
    assert canonical_json_bytes(repeated.to_dict()) == canonical_json_bytes(state_before)
    return {
        "project_event_delta": int(before[0] != after[0]),
        "program_event_delta": int(before[1] != after[1]),
        "autonomy_event_delta": int(before[2] != after[2]),
        "same_state": canonical_json_bytes(repeated.to_dict()) == canonical_json_bytes(state_before),
    }


def _closed_science(harness: Harness) -> Any:
    science = reduce_scientific_state(
        harness.service.event_log.read(), project_id=harness.service.config.project_id
    )
    class_states = tuple(
        replace(item, lifecycle="closed", closure_reason="fixture")
        if item.hypothesis_class_id == harness.state().current_query.hypothesis_class_id
        else item
        for item in science.class_states
    )
    return SimpleNamespace(
        class_states=class_states,
        study_stop={**science.study_stop, "stopped": False},
        contract=science.contract,
    )


def _closed(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    checkpoint = cast(str, case["checkpoint"])
    harness = _harness(root, decision="next")
    if checkpoint == "provider_packet":
        _reach(harness, "proposal")
        error = DecisionPacketError("DECISION_PACKET_INVALID", "closed fixture")
        with patch("research_os.autonomy.loop.validate_decision_packet", side_effect=error):
            harness.loop.advance(harness.episode_id, expected_phase="proposal")
        return {
            "provider_calls": 1,
            "experiment_registrations": 0,
            "error_code": harness.loop.episode(harness.episode_id).read()[-1].payload["error_code"],
            "authorized_action": None,
        }
    if checkpoint == "next_query":
        _reach(harness, "next")
        registrations = len(reduce_scientific_state(
            harness.service.event_log.read(), project_id=harness.service.config.project_id
        ).registrations)
        harness.loop._science = lambda: _closed_science(harness)  # type: ignore[method-assign]
        harness.loop.advance(harness.episode_id, expected_phase="next")
        after = len(reduce_scientific_state(
            harness.service.event_log.read(), project_id=harness.service.config.project_id
        ).registrations)
        return {
            "additional_experiment_registrations": after - registrations,
            "stop_reason": harness.state().stop_reason,
            "authorized_action": None,
        }
    harness.loop._science = lambda: _closed_science(harness)  # type: ignore[method-assign]
    harness.loop.advance(harness.episode_id, expected_phase="context")
    if checkpoint == "parameter_tweak":
        return {
            "experiment_registrations": 0,
            "stop_reason": harness.state().stop_reason,
            "authorized_action": None,
        }
    return {
        "provider_calls": harness.state().provider_calls,
        "experiment_registrations": 0,
        "stop_reason": harness.state().stop_reason,
        "authorized_action": None,
    }


def _budget(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    checkpoint = cast(str, case["checkpoint"])
    changes = {
        "experiment": {"max_experiments": 0},
        "provider": {"max_provider_calls": 2},
        "token": {"max_token_units": 599_999},
        "time": {"max_elapsed_milliseconds": 1_029},
    }
    failure = "proposal" if checkpoint == "invalid" else None
    harness = _harness(root, failure=failure, policy=_policy(**changes.get(checkpoint, {})))
    harness.loop.run(harness.episode_id)
    state = harness.state()
    if checkpoint == "invalid":
        return {
            "stop_reason": state.stop_reason,
            "invalid_packets": state.invalid_packets,
            "experiment_registrations": 0,
            "authorized_action": None,
        }
    return {
        "stop_reason": state.stop_reason,
        "provider_calls": state.provider_calls,
        "experiment_registrations": 0,
        "authorized_action": None,
    }


def _sealed(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    checkpoint = cast(str, case["checkpoint"])
    if checkpoint == "runner":
        harness = _actual_service_harness(root)
        with patch.object(
            harness.service, "run_once", wraps=harness.service.run_once
        ) as run_once:
            harness.loop.run(harness.episode_id)
        assert set(vars(harness.loop)) == {"service", "program_store", "provider", "root"}
        assert not hasattr(harness.provider, "service")
        return {
            "research_service_calls": run_once.call_count,
            "adapter_direct_calls": 0,
            "workspace_direct_calls": 0,
            "authorized_action": None,
        }
    harness = _harness(root, decision="stop")
    harness.loop.run(harness.episode_id)
    state = harness.state()
    summary = state.stop_summary
    assert summary is not None
    if checkpoint == "authority":
        values = [
            summary,
            *[event.to_dict() for event in harness.service.event_log.read()],
            *[event.to_dict() for event in harness.store.log.read()],
            *[event.to_dict() for event in harness.loop.episode(harness.episode_id).read()],
        ]
        return {
            "non_null_authority": _non_null_authority(values),
            "deploy_merge_trade_surface": _forbidden_surface(values),
            "authorized_action": None,
        }
    verify_autonomy_evidence(
        state,
        project_log=harness.service.event_log,
        program_store=harness.store,
    )
    refs = {
        "terminal": summary["terminal_refs"][0],
        "diagnosis": summary["diagnosis_refs"][0],
        "claim": summary["claim_refs"][0],
        "class_state": summary["class_state_refs"][0],
    }
    required = {
        "terminal": {"event_id", "event_hash", "event_sequence"},
        "diagnosis": {"event_id", "event_hash", "event_sequence", "diagnosis_digest"},
        "claim": {"claim_id", "claim_digest", "program_event"},
        "class_state": {"class_state_id", "class_state_digest"},
    }
    assert required[checkpoint] <= set(refs[checkpoint])
    labels = {
        "terminal": "terminal_event_id_hash_sequence",
        "diagnosis": "diagnosis_event_id_hash_sequence_and_digest",
        "claim": "program_claim_event_id_hash_sequence_and_digest",
        "class_state": "class_state_id_and_digest",
    }
    return {"reference": labels[checkpoint], "exact": True, "authorized_action": None}


def _event_rejection(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    harness = _harness(root)
    event = harness.loop.episode(harness.episode_id).read()[0]
    payload = copy.deepcopy(event.payload)
    mutation = case["mutation"]
    if mutation == "extra_key":
        payload["extra"] = None
    elif mutation == "wrong_version":
        payload["autonomy_event_schema_version"] = 2
    elif mutation == "authorized_action":
        payload["context"]["authorized_action"] = "run"
    else:
        assert mutation == "episode_id"
        payload["episode_id"] = "episode_other"
    before = harness.bytes()[:2]
    with pytest.raises(AutonomyLoopError) as caught:
        reduce_autonomy_events(
            [replace(event, payload=payload)],
            project_id=harness.service.config.project_id,
            episode_id=harness.episode_id,
        )
    after = harness.bytes()[:2]
    return {
        "error_code": caught.value.code,
        "project_write_delta": int(before[0] != after[0]),
        "program_write_delta": int(before[1] != after[1]),
    }


def _rejection(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    mutation = cast(str, case["mutation"])
    if case["driver"] == "reject_event":
        return _event_rejection(case, root)
    if mutation == "bool_number":
        raw = _policy().to_dict()
        raw["max_experiments"] = True
        with pytest.raises(AutonomyLoopError) as caught:
            AutonomyPolicy.from_mapping(raw)
        return {"error_code": caught.value.code, "project_write_delta": 0, "program_write_delta": 0}
    if mutation == "transport":
        harness = _harness(root, failure="transport")
        harness.loop.advance(harness.episode_id, expected_phase="context")
        state = harness.state()
        return {
            "error_code": harness.loop.episode(harness.episode_id).read()[-1].payload["error_code"],
            "experiment_registrations": 0,
            "invalid_packets": state.invalid_packets,
        }
    if mutation == "claim_evidence":
        harness = _harness(root, failure="claim_evidence")
        _reach(harness, "diagnosis")
        before = len(harness.store.log.read())
        harness.loop.advance(harness.episode_id, expected_phase="diagnosis")
        event = harness.loop.episode(harness.episode_id).read()[-1]
        return {
            "error_code": event.payload["error_code"],
            "claim_write_delta": len(harness.store.log.read()) - before,
            "authorized_action": None,
        }
    assert mutation == "program_head"
    harness = _harness(root)
    _reach(harness, "proposal")
    snapshot, _ = harness.store.snapshot()
    claims = harness.store.claim_snapshot().claims
    relation = ClaimRelation.from_mapping(
        {
            "claim_relation_schema_version": 1,
            "relation_id": stable_id("relation", "contradicts", claims[0].claim.claim_id, claims[1].claim.claim_id, "stale fixture"),
            "relation_type": "contradicts",
            "source_claim_id": claims[0].claim.claim_id,
            "target_claim_id": claims[1].claim.claim_id,
            "rationale": "stale fixture",
            "authorized_action": None,
        }
    )
    harness.store.append_relation(relation, expected_program_head=snapshot.program_head)
    before = len(harness.store.log.read())
    harness.loop.advance(harness.episode_id, expected_phase="proposal")
    event = harness.loop.episode(harness.episode_id).read()[-1]
    return {
        "error_code": event.payload["error_code"],
        "experiment_registrations": 0,
        "program_write_delta": len(harness.store.log.read()) - before,
    }


HANDLERS: dict[str, Callable[[Mapping[str, Any], Path], dict[str, Any]]] = {
    "nominal_transition": _transition,
    "stop_transition": _transition,
    "memory_binding": _memory,
    "repeat_transition": _idempotency,
    "closed_class_guard": _closed,
    "budget_stop": _budget,
    "sealed_evidence": _sealed,
    "reject_event": _rejection,
    "reject_policy": _rejection,
    "reject_preflight": _rejection,
    "reject_provider": _rejection,
    "reject_synthesis": _rejection,
}


def test_m3b_frozen_manifest_contract_is_literal_and_fully_handled() -> None:
    assert hashlib.sha256(MANIFEST_BYTES).hexdigest() == (
        "29684ed79c0dcf224a3959753f324f6f55f261e696b5c366218b48ef2dc99bc1"
    )
    assert len(CASES) == MANIFEST["expected_total"] == 43
    assert len({case["case_id"] for case in CASES}) == 43
    assert Counter(case["group"] for case in CASES) == Counter(MANIFEST["groups"])
    assert {case["driver"] for case in CASES} == set(HANDLERS)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["case_id"])
def test_m3b_frozen_manifest_case(case: Mapping[str, Any], tmp_path: Path) -> None:
    observed = HANDLERS[cast(str, case["driver"])](case, tmp_path)
    assert canonical_json_bytes(observed) == canonical_json_bytes(case["expected"])


def test_m3b_cold_replay_and_terminal_summary_are_exact(tmp_path: Path) -> None:
    harness = _harness(tmp_path, decision="stop")
    live = harness.loop.run(harness.episode_id)
    cold = reduce_autonomy_events(
        harness.loop.episode(harness.episode_id).read(),
        project_id=harness.service.config.project_id,
        episode_id=harness.episode_id,
    )
    assert canonical_json_bytes(cold.to_dict()) == canonical_json_bytes(live.to_dict())
    assert canonical_json_bytes(cold.stop_summary) == canonical_json_bytes(live.stop_summary)


def test_m3b_provider_reservations_cover_every_value_request(tmp_path: Path) -> None:
    harness = _harness(tmp_path, decision="stop")
    harness.loop.run(harness.episode_id)
    started = [
        event
        for event in harness.loop.episode(harness.episode_id).read()
        if event.event_type.endswith("provider_call_started.v1")
    ]
    assert [event.payload["call_kind"] for event in started] == [
        "proposal",
        "diagnosis",
        "synthesis",
    ]
    assert all(
        canonical_token_units(event.payload["request"]) <= event.payload["token_reservation"]
        for event in started
    )


def test_m3b_next_context_revalidates_a_fresh_packet_on_current_program_head(
    tmp_path: Path,
) -> None:
    harness = _harness(
        tmp_path,
        decision="next",
        policy=_policy(max_token_units=1_200_000),
    )
    _reach(harness, "next")
    prior_head = harness.store.snapshot()[0].program_head

    harness.loop.advance(harness.episode_id, expected_phase="next")
    harness.loop.advance(harness.episode_id, expected_phase="proposal")

    assert harness.state().phase == "preflight"
    assert harness.service.run_once_calls == 1
    assert harness.provider.calls.count("proposal") == 2
    next_request = harness.provider.proposal_requests[-1]
    assert ProgramSnapshot.from_mapping(next_request.program_snapshot).program_head == prior_head
    retrieval = next_request.context["memory"]["retrieval_result"]
    assert retrieval["program_head"] == {"sequence": prior_head[0], "hash": prior_head[1]}
    assert retrieval["active"] and all(hit["reasons"] for hit in retrieval["active"])
    assert retrieval["contradictions"] and all(
        hit["reasons"] for hit in retrieval["contradictions"]
    )


def test_m3b_autonomy_log_rejects_before_commit(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    log = harness.loop.episode(harness.episode_id)
    before = log.log.path.read_bytes()
    with pytest.raises(AutonomyLoopError) as caught:
        log.append("research_os.autonomy.proposal_returned.v1", {"extra": None})
    assert caught.value.code == "AUTONOMY_EVENT_INVALID"
    assert log.log.path.read_bytes() == before


def test_m3b_reducer_rejects_a_tampered_terminal_summary(tmp_path: Path) -> None:
    harness = _harness(tmp_path, decision="stop")
    harness.loop.run(harness.episode_id)
    events = harness.loop.episode(harness.episode_id).read()
    payload = copy.deepcopy(events[-1].payload)
    payload["summary"]["stop_reason"] = "tampered"
    with pytest.raises(AutonomyLoopError) as caught:
        reduce_autonomy_events(
            [*events[:-1], replace(events[-1], payload=payload)],
            project_id=harness.service.config.project_id,
            episode_id=harness.episode_id,
        )
    assert caught.value.code == "AUTONOMY_STATE_INVALID"


def test_m3b_truth_owner_reconciliation_rejects_one_tampered_ref(tmp_path: Path) -> None:
    harness = _harness(tmp_path, decision="stop")
    state = harness.loop.run(harness.episode_id)
    terminal = dict(state.terminal_history[0])
    terminal["event_hash"] = "f" * 64
    tampered = replace(state, terminal_history=(terminal,))

    with pytest.raises(AutonomyLoopError) as caught:
        verify_autonomy_evidence(
            tampered,
            project_log=harness.service.event_log,
            program_store=harness.store,
        )

    assert caught.value.code == "AUTONOMY_EVIDENCE_INVALID"


def test_m3b_disposable_actual_research_service_executes_and_seals_evidence(
    tmp_path: Path,
) -> None:
    harness = _actual_service_harness(tmp_path)
    with patch.object(
        harness.service, "run_once", wraps=harness.service.run_once
    ) as run_once:
        state = harness.loop.run(harness.episode_id)

    assert type(harness.service) is ResearchService
    assert run_once.call_count == 1
    assert state.complete is True and state.stop_reason == "provider_complete"
    assert verify_autonomy_evidence(
        state,
        project_log=harness.service.event_log,
        program_store=harness.store,
    ) == {
        "terminal_refs": 1,
        "disposition_refs": 1,
        "diagnosis_refs": 1,
        "origin_refs": 1,
        "claim_refs": 1,
        "class_state_refs": 1,
    }
    terminal = next(
        event
        for event in harness.service.event_log.read()
        if event.event_id == state.terminal_history[0]["event_id"]
    )
    artifacts = cast(Mapping[str, Any], terminal.payload["result"])["artifacts"]
    assert artifacts and all(
        set(artifact) >= {"sha256", "size_bytes"} for artifact in artifacts
    )


@pytest.mark.parametrize("failure", ["diagnosis", "claim_evidence"])
def test_m3b_post_terminal_invalid_output_stops_incomplete_without_rerun(
    tmp_path: Path, failure: str
) -> None:
    harness = _harness(tmp_path, failure=failure)
    state = harness.loop.run(harness.episode_id)
    assert state.phase == "stop"
    assert state.stop_reason == "invalid_packet_budget_exhausted"
    assert state.complete is False
    assert state.stop_summary["status"] == "incomplete"
    assert harness.service.run_once_calls == 1
    assert len(state.terminal_history) == 1
    assert len(state.claim_history) == 0


@pytest.mark.parametrize(
    ("failure", "start_phase", "policy", "stop_reason"),
    [
        (
            "diagnosis",
            "run",
            _policy(max_invalid_packets=2, max_token_units=1_200_000),
            "invalid_packet_budget_exhausted",
        ),
        (
            "diagnosis_transport",
            "run",
            _policy(max_invalid_packets=2, max_token_units=1_200_000),
            "invalid_packet_budget_exhausted",
        ),
        (
            "diagnosis",
            "run",
            _policy(
                max_invalid_packets=10,
                max_provider_calls=3,
                max_token_units=2_000_000,
            ),
            "provider_budget_exhausted",
        ),
        (
            "diagnosis",
            "run",
            _policy(
                max_invalid_packets=10,
                max_provider_calls=10,
                max_token_units=600_000,
            ),
            "token_budget_exhausted",
        ),
        (
            "diagnosis",
            "run",
            _policy(
                max_invalid_packets=10,
                max_provider_calls=10,
                max_token_units=2_000_000,
                max_elapsed_milliseconds=1_030,
            ),
            "time_budget_exhausted",
        ),
        (
            "claim_evidence",
            "diagnosis",
            _policy(max_invalid_packets=2, max_token_units=1_200_000),
            "invalid_packet_budget_exhausted",
        ),
        (
            "synthesis_transport",
            "diagnosis",
            _policy(max_invalid_packets=2, max_token_units=1_200_000),
            "invalid_packet_budget_exhausted",
        ),
    ],
)
def test_m3b_post_terminal_retries_stop_without_truth_owner_or_evaluator_delta(
    tmp_path: Path,
    failure: str,
    start_phase: str,
    policy: AutonomyPolicy,
    stop_reason: str,
) -> None:
    harness = _harness(tmp_path, failure=failure, policy=policy)
    _reach(harness, start_phase)
    project_before, program_before, _ = harness.bytes()
    evaluator_calls = harness.service.run_once_calls

    state = harness.loop.run(harness.episode_id)

    assert state.complete is False and state.stop_reason == stop_reason
    assert state.stop_summary["status"] == "incomplete"
    assert harness.service.run_once_calls == evaluator_calls == 1
    assert harness.service.event_log.path.read_bytes() == project_before
    assert harness.store.log.path.read_bytes() == program_before
    assert len(state.terminal_history) == 1
    assert len(state.claim_history) == 0
