from __future__ import annotations

import ast
import hashlib
import inspect
import json
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest

import research_os.autonomy as autonomy_api
from research_os.autonomy import (
    AutonomyLoopError,
    DecisionPacket,
    DecisionPacketError,
    FiniteAutonomyLoop,
    ProviderDecisionRequest,
    ProviderDiagnosisRequest,
    ProviderSynthesisPacket,
    ProviderSynthesisRequest,
    reduce_autonomy_events,
)
from research_os.contracts import canonical_json_bytes, sha256_json
from research_os.kernel.events import EventLog
from research_os.kernel.ids import stable_id
from research_os.memory import (
    PROGRAM_CLAIM_RECORDED_EVENT,
    PROGRAM_KNOWLEDGE_DISPOSITION_RECORDED_EVENT,
    PROGRAM_ORIGIN_LINKED_EVENT,
    ClaimRelation,
    ProgramStore,
)
from research_os.science import (
    DIAGNOSIS_EVENT_TYPE,
    StudyContract,
    plan_generation_open,
    reduce_scientific_state,
)
from research_os.service import ResearchService
from tests.test_m3b_finite_autonomy import (
    Harness,
    _actual_service_harness,
    _EpisodeProvider,
    _harness,
    _non_null_authority,
    _policy,
    _reach,
    _ReplayResearchService,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/autonomy/v1/m3c-manifest.json"
MANIFEST_BYTES = MANIFEST_PATH.read_bytes()
MANIFEST = json.loads(MANIFEST_BYTES)
CASES = tuple(MANIFEST["cases"])


class _ProcessDeath(BaseException):
    pass


class _CrashLoop(FiniteAutonomyLoop):
    def __init__(self, *args: Any, checkpoint: str, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.target_checkpoint = checkpoint
        self.crashed = False

    def _checkpoint(self, name: str) -> None:
        if name == self.target_checkpoint and not self.crashed:
            self.crashed = True
            raise _ProcessDeath(name)


class _RegistrationMismatchLoop(FiniteAutonomyLoop):
    _target_proposal_digest: str = ""

    def _science(self) -> Any:
        state = super()._science()
        matches = tuple(
            replace(item, generation_id="generation_ffffffffffffffffffffffffffffffff")
            if item.proposal_digest == self._target_proposal_digest
            else item
            for item in state.registrations
        )
        return replace(state, registrations=matches)


class _ChangingProvider(_EpisodeProvider):
    def __init__(self, *args: Any, sequence: Counter[str], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.sequence = sequence

    def invoke(self, request: Any) -> Mapping[str, Any]:
        raw = dict(super().invoke(request))
        if isinstance(request, ProviderDiagnosisRequest):
            self.sequence["diagnosis"] += 1
            diagnosis = cast(dict[str, Any], raw["diagnosis"])
            diagnosis["interpretation"] = (
                f"Nondeterministic diagnosis output {self.sequence['diagnosis']}."
            )
        elif isinstance(request, ProviderSynthesisRequest):
            self.sequence["synthesis"] += 1
            claim = cast(dict[str, Any], raw["claim"])
            claim["limitations"] = [
                f"Nondeterministic synthesis output {self.sequence['synthesis']}."
            ]
            claim["claim_id"] = stable_id(
                "claim",
                claim["statement"],
                claim["applicability"],
                claim["evidence"],
                claim["claim_status"],
                claim["claim_maturity"],
                claim["limitations"],
            )
        return raw


class _InjectedProvider(_EpisodeProvider):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.forbidden_calls = Counter[str]()

    def deploy(self) -> None:
        self.forbidden_calls["deploy"] += 1

    def merge(self) -> None:
        self.forbidden_calls["merge"] += 1

    def trade(self) -> None:
        self.forbidden_calls["trade"] += 1


def _crash(harness: Harness, checkpoint: str) -> None:
    harness.loop = _CrashLoop(
        harness.service,
        harness.store,
        harness.provider,
        autonomy_root=harness.loop.root,
        checkpoint=checkpoint,
    )
    with pytest.raises(_ProcessDeath, match=checkpoint):
        harness.loop.run(harness.episode_id)


def _reopen(harness: Harness) -> Harness:
    old_service = harness.service
    service = object.__new__(_ReplayResearchService)
    service.config = SimpleNamespace(
        project_id=old_service.config.project_id,
        root=old_service.config.root,
        resolved_runtime_dir=old_service.config.resolved_runtime_dir,
    )
    service.event_log = EventLog(old_service.event_log.path, old_service.config.project_id)
    service.terminal = None
    service.run_once_calls = 0
    service.adapter_direct_calls = 0
    service.workspace_direct_calls = 0
    store = ProgramStore(harness.store.root, harness.store.program_id)
    old_provider = harness.provider
    provider = _EpisodeProvider(
        service.config.project_id,
        store,
        old_provider.proposal,
        old_provider.candidate,
        old_provider.entries,
        decision=old_provider.decision,
        failure=old_provider.failure,
    )
    loop = FiniteAutonomyLoop(
        cast(Any, service), store, provider, autonomy_root=harness.loop.root
    )
    return Harness(loop, service, store, provider, harness.episode_id)


def _replace_provider(
    harness: Harness,
    provider_type: type[_EpisodeProvider],
    **kwargs: Any,
) -> Harness:
    old = harness.provider
    provider = provider_type(
        harness.service.config.project_id,
        harness.store,
        old.proposal,
        old.candidate,
        old.entries,
        decision=old.decision,
        failure=old.failure,
        **kwargs,
    )
    harness.provider = cast(Any, provider)
    harness.loop = FiniteAutonomyLoop(
        harness.service,
        harness.store,
        provider,
        autonomy_root=harness.loop.root,
    )
    return harness


def _reopen_actual(harness: Harness) -> Harness:
    service = ResearchService(harness.service.config.root)
    store = ProgramStore(harness.store.root, harness.store.program_id)
    old = harness.provider
    provider = _EpisodeProvider(
        service.config.project_id,
        store,
        old.proposal,
        old.candidate,
        old.entries,
        decision=old.decision,
        failure=old.failure,
    )
    loop = FiniteAutonomyLoop(
        service, store, provider, autonomy_root=harness.loop.root
    )
    return Harness(loop, service, store, provider, harness.episode_id)


def _semantic_counts(harness: Harness) -> dict[str, int]:
    state = harness.state()
    terminal_id = cast(str, state.terminal_history[0]["event_id"])
    disposition_id = cast(
        str, cast(Mapping[str, Any], state.disposition_history[0]["program_event"])["event_id"]
    )
    diagnosis_id = cast(str, state.diagnosis_history[0]["event_id"])
    origin_id = cast(
        str, cast(Mapping[str, Any], state.origin_history[0]["program_event"])["event_id"]
    )
    claim_id = cast(str, cast(Mapping[str, Any], state.claim_history[0]["program_event"])["event_id"])
    project = harness.service.event_log.read()
    program = harness.store.log.read()
    return {
        "terminal": sum(event.event_id == terminal_id for event in project),
        "disposition": sum(event.event_id == disposition_id for event in program),
        "diagnosis": sum(event.event_id == diagnosis_id for event in project),
        "origin": sum(event.event_id == origin_id for event in program),
        "claim": sum(event.event_id == claim_id for event in program),
    }


def _truth_type_counts(harness: Harness) -> dict[str, int]:
    state = harness.state()
    experiment_id = cast(str, state.terminal_history[0]["experiment_id"])
    project = harness.service.event_log.read()
    program = harness.store.log.read()
    return {
        "terminal": sum(
            event.payload.get("experiment_id", event.payload.get("id")) == experiment_id
            and event.event_type == "EXPERIMENT_STATUS_CHANGED"
            for event in project
        ),
        "disposition": sum(
            event.event_type == PROGRAM_KNOWLEDGE_DISPOSITION_RECORDED_EVENT
            and event.payload.get("proposal_digest")
            == state.disposition_history[0]["proposal_digest"]
            for event in program
        ),
        "diagnosis": sum(
            event.event_type == DIAGNOSIS_EVENT_TYPE
            and event.event_id == state.diagnosis_history[0]["event_id"]
            for event in project
        ),
        "origin": sum(
            event.event_type == PROGRAM_ORIGIN_LINKED_EVENT
            and cast(Mapping[str, Any], event.payload.get("origin_evidence", {})).get(
                "origin_id"
            )
            == cast(Mapping[str, Any], state.origin_history[0]["origin_evidence"])[
                "origin_id"
            ]
            for event in program
        ),
        "claim": sum(
            event.event_type == PROGRAM_CLAIM_RECORDED_EVENT
            and cast(Mapping[str, Any], event.payload.get("claim", {})).get("claim_id")
            == state.claim_history[0]["claim_id"]
            for event in program
        ),
    }


def _crash_resume(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    checkpoint = cast(str, case["checkpoint"])
    decision = "next" if checkpoint == "next_context_before_append" else "stop"
    harness = _harness(root, decision=decision, policy=_policy(max_experiments=1))
    _crash(harness, checkpoint)
    reopened = _reopen(harness)
    final = reopened.loop.run(reopened.episode_id)
    assert final.phase == "stop" and final.complete is True
    assert _semantic_counts(reopened) == {name: 1 for name in _semantic_counts(reopened)}
    expected = cast(Mapping[str, Any], case["expected"])
    if "budget_recharge" in expected:
        kind = ""
        if checkpoint.startswith("proposal_"):
            kind = "proposal"
        elif checkpoint.startswith("diagnosis_"):
            kind = "diagnosis"
        elif checkpoint.startswith("synthesis_"):
            kind = "synthesis"
        return {
            "provider_reinvoke": reopened.provider.calls.count(kind),
            "budget_recharge": max(0, final.provider_calls - 3),
            "terminal": "complete",
        }
    if "service_calls_after_restart" in expected:
        observed = {
            "service_calls_after_restart": reopened.service.run_once_calls,
            "terminal": "complete",
        }
        if "experiment_reregistration" in expected:
            observed["experiment_reregistration"] = max(
                0, _truth_type_counts(reopened)["terminal"] - 1
            )
        return observed
    if "program_reappend" in expected:
        return {
            "program_reappend": max(0, _truth_type_counts(reopened)["disposition"] - 1),
            "terminal": "complete",
        }
    if "diagnosis_append" in expected:
        return {"provider_reinvoke": reopened.provider.calls.count("diagnosis"), "diagnosis_append": _truth_type_counts(reopened)["diagnosis"], "terminal": "complete"}
    if "diagnosis_reappend" in expected:
        return {"provider_reinvoke": reopened.provider.calls.count("diagnosis"), "diagnosis_reappend": max(0, _truth_type_counts(reopened)["diagnosis"] - 1), "terminal": "complete"}
    if "origin_reappend" in expected:
        return {"provider_reinvoke": reopened.provider.calls.count("diagnosis"), "origin_reappend": max(0, _truth_type_counts(reopened)["origin"] - 1), "terminal": "complete"}
    if "claim_append" in expected:
        return {"provider_reinvoke": reopened.provider.calls.count("synthesis"), "claim_append": _truth_type_counts(reopened)["claim"], "terminal": "complete"}
    if "claim_reappend" in expected:
        return {"provider_reinvoke": reopened.provider.calls.count("synthesis"), "claim_reappend": max(0, _truth_type_counts(reopened)["claim"] - 1), "terminal": "complete"}
    cold = reduce_autonomy_events(
        reopened.loop.episode(reopened.episode_id).read(),
        project_id=reopened.service.config.project_id,
        episode_id=reopened.episode_id,
    )
    return {
        "rederive_exact": canonical_json_bytes(final.to_dict())
        == canonical_json_bytes(cold.to_dict()),
        "terminal": "complete",
    }


def _duplicate(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    harness = _harness(root, decision="stop", policy=_policy(max_experiments=1))
    checkpoint = {
        "terminal": "project_terminal_before_disposition",
        "disposition": "disposition_before_experiment_link",
        "diagnosis": "project_diagnosis_before_origin",
        "origin": "origin_before_diagnosis_link",
        "claim": "claim_before_synthesis_link",
    }[cast(str, case["checkpoint"])]
    _crash(harness, checkpoint)
    reopened = _reopen(harness)
    reopened.loop.run(reopened.episode_id)
    counts = _truth_type_counts(reopened)
    before = reopened.bytes()
    reopened.loop.advance(reopened.episode_id, expected_phase="context")
    return {
        "canonical_count": counts[cast(str, case["checkpoint"])],
        "duplicate_delta": int(before != reopened.bytes()),
    }


def _advance_program_head(harness: Harness) -> None:
    snapshot, _ = harness.store.snapshot()
    claims = harness.store.claim_snapshot().claims
    relation = ClaimRelation.from_mapping(
        {
            "claim_relation_schema_version": 1,
            "relation_id": stable_id(
                "relation",
                "contradicts",
                claims[0].claim.claim_id,
                claims[1].claim.claim_id,
                "M3-C one-factor recovery race.",
            ),
            "relation_type": "contradicts",
            "source_claim_id": claims[0].claim.claim_id,
            "target_claim_id": claims[1].claim.claim_id,
            "rationale": "M3-C one-factor recovery race.",
            "authorized_action": None,
        }
    )
    harness.store.append_relation(relation, expected_program_head=snapshot.program_head)


def _advance_generation(harness: Harness) -> None:
    events = tuple(harness.service.event_log.read())
    state = reduce_scientific_state(events, project_id=harness.service.config.project_id)
    assert state.contract is not None and state.evaluation_seal is not None
    raw = state.contract.to_dict()
    raw["budget"]["max_attempts"] += 1
    successor = StudyContract.from_mapping(raw)
    plan = plan_generation_open(
        events,
        project_id=state.project_id,
        contract=successor,
        evaluation_seal=state.evaluation_seal,
        predecessor_generation_id=state.active_generation_id,
        change_reason="M3-C one-factor recovery race.",
    )
    assert plan.append_required
    harness.service.event_log.append(plan.event_type, plan.payload)


def _stale(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    checkpoint = cast(str, case["checkpoint"])
    harness = _harness(root, decision="stop", policy=_policy(max_experiments=1))
    _crash(harness, checkpoint)
    if case["mutation"] == "program_head":
        _advance_program_head(harness)
    elif case["mutation"] == "generation_head":
        _advance_generation(harness)
    reopened = _reopen(harness)
    if case["mutation"] == "registration_binding":
        assert reopened.state().packet is not None
        loop = _RegistrationMismatchLoop(
            reopened.service,
            reopened.store,
            reopened.provider,
            autonomy_root=reopened.loop.root,
        )
        loop._target_proposal_digest = reopened.state().packet.proposal.digest
        reopened.loop = loop
    project_before = len(reopened.service.event_log.read())
    program_before = len(reopened.store.log.read())
    with pytest.raises(AutonomyLoopError) as caught:
        reopened.loop.advance(reopened.episode_id, expected_phase=reopened.state().phase)
    expected = cast(Mapping[str, Any], case["expected"])
    assert caught.value.code == expected["code"]
    if "provider_calls_after_restart" in expected:
        return {
            "code": caught.value.code,
            "provider_calls_after_restart": len(reopened.provider.calls),
            "project_program_delta": f"{len(reopened.service.event_log.read()) - project_before}/{len(reopened.store.log.read()) - program_before}",
        }
    if "service_calls_after_restart" in expected:
        return {
            "code": caught.value.code,
            "service_calls_after_restart": reopened.service.run_once_calls,
            "project_program_delta": f"{len(reopened.service.event_log.read()) - project_before}/{len(reopened.store.log.read()) - program_before}",
        }
    if "program_delta" in expected:
        return {
            "code": caught.value.code,
            "program_delta": len(reopened.store.log.read()) - program_before,
        }
    return {
        "code": caught.value.code,
        "claim_delta": sum(
            event.event_type == PROGRAM_CLAIM_RECORDED_EVENT
            for event in reopened.store.log.read()[program_before:]
        ),
    }


def _authority(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    harness = _harness(root, decision="stop", policy=_policy(max_experiments=1))
    state = harness.loop.run(harness.episode_id)
    assert state.synthesis_packet is not None
    events = harness.loop.episode(harness.episode_id).read()
    surface = cast(str, case["surface"])
    values: dict[str, object] = {
        "context": state.current_context,
        "decision_packet": next(
            event.payload["packet"] for event in events if event.event_type.endswith("proposal_returned.v1")
        ),
        "autonomy_events": [event.payload for event in events],
        "diagnosis_request_packet": next(
            event.payload["request"]
            for event in events
            if event.event_type.endswith("provider_call_started.v1")
            and event.payload["call_kind"] == "diagnosis"
        ),
        "synthesis_request_packet": next(
            event.payload["request"]
            for event in events
            if event.event_type.endswith("provider_call_started.v1")
            and event.payload["call_kind"] == "synthesis"
        ),
        "claim": state.synthesis_packet.claim.to_dict(),
    }
    return {"recursive_non_null": _non_null_authority(values[surface])}


def _forbidden(case: Mapping[str, Any], root: Path) -> dict[str, Any]:
    operation = cast(str, case["operation"])
    tree = ast.parse(inspect.getsource(FiniteAutonomyLoop))
    calls = sum(
        isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == operation)
            or (isinstance(node.func, ast.Name) and node.func.id == operation)
            or (
                isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and len(node.args) >= 2
                and isinstance(node.args[1], ast.Constant)
                and node.args[1].value == operation
            )
        )
        for node in ast.walk(tree)
    )
    exports = sum(
        name == operation and callable(getattr(autonomy_api, name))
        for name in getattr(autonomy_api, "__all__", ())
    )
    return {"callable_surface_count": calls + exports}


HANDLERS: dict[str, Callable[[Mapping[str, Any], Path], dict[str, Any]]] = {
    "crash_resume": _crash_resume,
    "duplicate_suppression": _duplicate,
    "stale_head": _stale,
    "null_authority": _authority,
    "forbidden_operation": _forbidden,
}


def test_m3c_frozen_manifest_contract_is_literal_and_fully_handled() -> None:
    assert hashlib.sha256(MANIFEST_BYTES).hexdigest() == (
        "c3752c811e44cebd7c542a3653ee19c8c5d2b2b7c1daf11a9a11b23565e27c7b"
    )
    assert len(CASES) == MANIFEST["expected_total"] == 31
    assert len({case["case_id"] for case in CASES}) == 31
    assert Counter(case["group"] for case in CASES) == Counter(MANIFEST["groups"])
    assert set(MANIFEST["groups"]) == set(HANDLERS)


@pytest.mark.parametrize(
    "case",
    CASES,
    ids=lambda case: case["case_id"],
)
def test_m3c_frozen_case(case: Mapping[str, Any], tmp_path: Path) -> None:
    observed = HANDLERS[cast(str, case["group"])](case, tmp_path)
    assert canonical_json_bytes(observed) == canonical_json_bytes(case["expected"])


@pytest.mark.parametrize("kind", ["diagnosis", "synthesis"])
@pytest.mark.parametrize("captured", [False, True], ids=["before-capture", "after-capture"])
def test_m3c_nondeterministic_provider_capture_boundary(
    kind: str, captured: bool, tmp_path: Path
) -> None:
    sequence: Counter[str] = Counter()
    harness = _replace_provider(
        _harness(tmp_path, decision="stop", policy=_policy(max_experiments=1)),
        _ChangingProvider,
        sequence=sequence,
    )
    suffix = "output_captured" if captured else "output_before_capture"
    _crash(harness, f"{kind}_{suffix}")
    assert sequence[kind] == 1
    reopened = _replace_provider(_reopen(harness), _ChangingProvider, sequence=sequence)
    final = reopened.loop.run(reopened.episode_id)
    assert final.complete is True and final.provider_calls == 3
    assert _truth_type_counts(reopened) == {
        "terminal": 1,
        "disposition": 1,
        "diagnosis": 1,
        "origin": 1,
        "claim": 1,
    }
    assert reopened.provider.calls.count(kind) == int(not captured)
    assert sequence[kind] == (1 if captured else 2)


def test_m3c_service_registration_without_terminal_recovers_publicly(tmp_path: Path) -> None:
    harness = _actual_service_harness(tmp_path)
    harness.provider.decision = "stop"
    original_append = harness.service.event_log.append

    def interrupted_append(event_type: str, payload: Mapping[str, Any], **kwargs: Any) -> Any:
        event = original_append(event_type, payload, **kwargs)
        if event_type == "EXPERIMENT_REGISTERED":
            raise _ProcessDeath("registration_without_terminal")
        return event

    with patch.object(harness.service.event_log, "append", side_effect=interrupted_append):
        with pytest.raises(_ProcessDeath, match="registration_without_terminal"):
            harness.loop.run(harness.episode_id)
    before = reduce_scientific_state(
        harness.service.event_log.read(), project_id=harness.service.config.project_id
    )
    pending = [item for item in before.registrations if not item.is_terminal]
    assert len(pending) == 1
    reopened = _reopen_actual(harness)
    final = reopened.loop.run(reopened.episode_id)
    after = reduce_scientific_state(
        reopened.service.event_log.read(), project_id=reopened.service.config.project_id
    )
    recovered = [
        item for item in after.registrations if item.experiment_id == pending[0].experiment_id
    ]
    assert final.complete is True
    assert len(recovered) == 1 and recovered[0].is_terminal
    assert recovered[0].terminal_payload is not None
    assert recovered[0].terminal_payload["reason_code"] == "RECOVERED_INTERRUPTED_RUN"


def test_m3c_adversarial_authority_and_injected_operations_are_unreachable(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path / "parsers", decision="stop", policy=_policy(max_experiments=1))
    proposal_request = harness.state().current_proposal_request.to_dict()
    proposal_request["program_snapshot"]["authorized_action"] = {"trade": True}
    _reach(harness, "proposal")
    assert harness.state().packet is not None
    packet = harness.state().packet.to_dict()
    packet["candidate"]["authorized_action"] = {"merge": True}
    final = harness.loop.run(harness.episode_id)
    assert final.synthesis_packet is not None
    synthesis = final.synthesis_packet.to_dict()
    synthesis["claim"]["authorized_action"] = {"deploy": True}
    for parser, raw in (
        (ProviderDecisionRequest.from_mapping, proposal_request),
        (DecisionPacket.from_mapping, packet),
        (ProviderSynthesisPacket.from_mapping, synthesis),
    ):
        with pytest.raises((AutonomyLoopError, DecisionPacketError)):
            parser(raw)

    capture = _harness(
        tmp_path / "capture", decision="stop", policy=_policy(max_experiments=1)
    )
    _crash(capture, "diagnosis_call_started")
    pending = capture.state()
    assert pending.pending_call_id is not None and pending.pending_request is not None
    forged_output = {"authorized_action": {"deploy": True}}
    log = capture.loop.episode(capture.episode_id)
    before_bytes = log.log.path.read_bytes()
    with pytest.raises(AutonomyLoopError, match="authority must be null"):
        log.append(
            "research_os.autonomy.provider_output_captured.v1",
            {
                "call_id": pending.pending_call_id,
                "call_kind": "diagnosis",
                "request_digest": sha256_json(pending.pending_request),
                "output": forged_output,
                "output_digest": sha256_json(forged_output),
            },
        )
    assert log.log.path.read_bytes() == before_bytes

    injected = _replace_provider(
        _harness(tmp_path / "injected", decision="stop", policy=_policy(max_experiments=1)),
        _InjectedProvider,
    )
    injected.loop.run(injected.episode_id)
    assert cast(_InjectedProvider, injected.provider).forbidden_calls == Counter()
