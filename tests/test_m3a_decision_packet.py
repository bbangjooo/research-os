from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from research_os.agent import build_agent_context_v3
from research_os.autonomy import (
    DecisionPacket,
    DecisionPacketError,
    JSONSubprocessProvider,
    ProviderDecisionRequest,
    ProviderPortError,
    PythonProviderPort,
    build_decision_packet,
    build_provider_decision_request,
    build_retrieval_manifest,
    validate_decision_packet,
)
from research_os.autonomy.protocol import _validate_current_proposal
from research_os.contracts import canonical_json_bytes, sha256_json
from research_os.kernel.events import EventLog
from research_os.kernel.ids import stable_id
from research_os.memory import (
    create_proposal_knowledge_disposition,
    validate_proposal_knowledge_disposition,
)
from research_os.science import Proposal, reduce_scientific_state
from tests.test_m2d_knowledge_disposition import _real_vertical

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/autonomy/v1/m3a-manifest.json"
PROVIDER_FIXTURE = ROOT / "tests/fixtures/autonomy/v1/provider_fixture.py"
MANIFEST_BYTES = MANIFEST_PATH.read_bytes()
MANIFEST = json.loads(MANIFEST_BYTES)
CASES = tuple(MANIFEST["cases"])


@dataclass(slots=True)
class Harness:
    store: Any
    project_log: Any
    result: Any
    proposal: Proposal
    context: dict[str, Any]
    project_token: str
    request: ProviderDecisionRequest
    packet: DecisionPacket

    def log_bytes(self) -> tuple[bytes, bytes]:
        return self.project_log.path.read_bytes(), self.store.log.path.read_bytes()


def _harness(root: Path) -> Harness:
    vertical = _real_vertical(root)
    state = reduce_scientific_state(
        vertical["project_log"].read(), project_id=vertical["project_log"].project_id
    )
    context = build_agent_context_v3(
        project={},
        status={},
        lineage=[],
        findings=[],
        artifacts=[],
        agent_spec={},
        snapshot={
            "schema_version": 2,
            "project_id": vertical["project_log"].project_id,
            "last_sequence": 1,
            "last_hash": "a" * 64,
            "context_token": vertical["project_token"],
        },
        scientific_state=state.to_dict(),
        limit=10,
        retrieval=vertical["result"],
    )
    snapshot, _ = vertical["store"].snapshot()
    request = build_provider_decision_request(
        context=context,
        program_snapshot=snapshot,
        provider_request_id="providerrequest_m3a-fixture",
    )
    disposition = create_proposal_knowledge_disposition(
        project_id=vertical["project_log"].project_id,
        proposal=vertical["proposal"],
        retrieval=vertical["result"],
        context_token=context["snapshot"]["context_token"],
        entries=vertical["disposition"].entries,
    )
    packet = build_decision_packet(
        request=request,
        project_id=vertical["project_log"].project_id,
        candidate={"x": 1},
        proposal=vertical["proposal"],
        knowledge_disposition=disposition,
        retrieval=vertical["result"],
    )
    return Harness(
        vertical["store"],
        vertical["project_log"],
        vertical["result"],
        vertical["proposal"],
        context,
        vertical["project_token"],
        request,
        packet,
    )


def _validate(harness: Harness, packet: DecisionPacket | Mapping[str, Any]) -> Any:
    return validate_decision_packet(
        packet,
        request=harness.request,
        program_store=harness.store,
        project_log=harness.project_log,
        current_project_context_token=harness.project_token,
    )


def _reseal_packet(raw: dict[str, Any]) -> dict[str, Any]:
    identity = copy.deepcopy(raw)
    identity.pop("packet_id")
    raw["packet_id"] = stable_id("decisionpacket", identity)
    return raw


def _reseal_disposition(raw: dict[str, Any]) -> dict[str, Any]:
    identity = copy.deepcopy(raw)
    identity.pop("disposition_id")
    raw["disposition_id"] = stable_id("disposition", identity)
    return raw


def _mutated_packet(harness: Harness, mutation: str) -> dict[str, Any]:
    raw = copy.deepcopy(harness.packet.to_dict())
    if mutation == "wrong_version":
        raw["decision_packet_schema_version"] = 2
    elif mutation == "bool_version":
        raw["decision_packet_schema_version"] = True
    elif mutation == "extra_key":
        raw["extra"] = None
    elif mutation == "packet_id":
        raw["packet_id"] = "decisionpacket_forged"
        return raw
    elif mutation == "provider_request_id":
        raw["provider_request_id"] = "providerrequest_other"
    elif mutation == "context_token":
        raw["context_token"] = "f" * 64
    elif mutation == "program_snapshot_digest":
        raw["program_snapshot_digest"] = "f" * 64
    elif mutation == "program_snapshot":
        raw["program_snapshot"]["program_head"]["hash"] = "f" * 64
        raw["program_snapshot_digest"] = sha256_json(raw["program_snapshot"])
    elif mutation == "query_digest":
        raw["retrieval_manifest"]["query_digest"] = "f" * 64
    elif mutation == "retrieval_result_digest":
        raw["retrieval_manifest"]["retrieval_result_digest"] = "f" * 64
    elif mutation == "missing_claim":
        raw["retrieval_manifest"]["returned_claims"].pop()
    elif mutation == "duplicate_claim":
        claims = raw["retrieval_manifest"]["returned_claims"]
        claims.append(copy.deepcopy(claims[0]))
        claims.sort(key=lambda item: item["claim_id"])
    elif mutation == "reason":
        raw["retrieval_manifest"]["returned_claims"][0]["reasons"] = ["forged"]
    elif mutation == "candidate":
        raw["candidate"] = {"x": 2}
    elif mutation in {"generation_id", "hypothesis_class_id", "evaluation_scope_id"}:
        values = {
            "generation_id": "generation_inactive",
            "hypothesis_class_id": "class-b",
            "evaluation_scope_id": "diagnostic-1",
        }
        raw["proposal"][mutation] = values[mutation]
    elif mutation == "knowledge_disposition":
        disposition = raw["knowledge_disposition"]
        disposition["entries"][0]["claim_digest"] = "f" * 64
        _reseal_disposition(disposition)
    elif mutation == "authorized_action":
        raw["authorized_action"] = "run"
    else:  # pragma: no cover - the literal handler table prevents fallback
        raise AssertionError(f"unhandled mutation {mutation}")
    return _reseal_packet(raw)


class _StaticProvider:
    def __init__(self, packet: Mapping[str, Any]):
        self.packet = copy.deepcopy(packet)
        self.request_bytes: bytes | None = None

    def decide(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        self.request_bytes = canonical_json_bytes(request)
        return copy.deepcopy(self.packet)


def _subprocess(
    mode: str,
    *arguments: str,
    timeout: float = 2.0,
    output_limit: int = 2 * 1024 * 1024,
) -> JSONSubprocessProvider:
    return JSONSubprocessProvider(
        [sys.executable, str(PROVIDER_FIXTURE), mode, *arguments],
        timeout_seconds=timeout,
        max_output_bytes=output_limit,
    )


def _packet_file(harness: Harness, root: Path) -> Path:
    path = root / "packet.json"
    path.write_bytes(canonical_json_bytes(harness.packet.to_dict()))
    return path


def _assert_no_write(before: tuple[bytes, bytes], harness: Harness) -> None:
    assert harness.log_bytes() == before


def _python_provider_valid(harness: Harness, _: Path) -> dict[str, Any]:
    before = harness.log_bytes()
    result = PythonProviderPort(_StaticProvider(harness.packet.to_dict())).invoke(harness.request)
    _validate(harness, result)
    _assert_no_write(before, harness)
    return {"accepted": True, "write_delta": 0}


def _subprocess_provider_valid(harness: Harness, root: Path) -> dict[str, Any]:
    before = harness.log_bytes()
    record = root / "request.json"
    result = _subprocess("valid", str(_packet_file(harness, root)), str(record)).invoke(
        harness.request
    )
    _validate(harness, result)
    assert record.read_bytes().rstrip(b"\n") == canonical_json_bytes(harness.request.to_dict())
    _assert_no_write(before, harness)
    return {"accepted": True, "write_delta": 0}


def _provider_parity(harness: Harness, root: Path) -> dict[str, Any]:
    python_provider = _StaticProvider(harness.packet.to_dict())
    python_result = PythonProviderPort(python_provider).invoke(harness.request)
    record = root / "subprocess-request.json"
    process_result = _subprocess("valid", str(_packet_file(harness, root)), str(record)).invoke(
        harness.request
    )
    assert python_provider.request_bytes == record.read_bytes().rstrip(b"\n")
    assert canonical_json_bytes(python_result) == canonical_json_bytes(process_result)
    assert _validate(harness, python_result).packet == _validate(harness, process_result).packet
    return {"packets_equal": True}


def _current_read_set(harness: Harness, _: Path) -> dict[str, Any]:
    result = _validate(harness, harness.packet)
    current, _ = harness.store.snapshot()
    return {
        "accepted": True,
        "program_head_current": result.packet.program_snapshot.program_head == current.program_head,
    }


def _retrieval_binding(harness: Harness, _: Path) -> dict[str, Any]:
    _validate(harness, harness.packet)
    assert harness.packet.retrieval_manifest == build_retrieval_manifest(harness.result)
    return {"accepted": True, "coverage": "exact"}


def _proposal_disposition(harness: Harness, _: Path) -> dict[str, Any]:
    validated = _validate(harness, harness.packet)
    parsed = validate_proposal_knowledge_disposition(
        validated.packet.knowledge_disposition,
        project_id=harness.project_log.project_id,
        proposal=validated.packet.proposal,
        retrieval=validated.retrieval,
        context_token=validated.packet.context_token,
    )
    assert len(parsed.entries) == len(validated.retrieval.returned_claim_ids)
    return {"accepted": True, "disposition_coverage": "exact"}


def _validation_no_write(harness: Harness, _: Path) -> dict[str, Any]:
    before = harness.log_bytes()
    _validate(harness, harness.packet)
    after = harness.log_bytes()
    return {
        "project_log_delta": int(before[0] != after[0]),
        "program_log_delta": int(before[1] != after[1]),
    }


def _scan_provider_value(value: object) -> tuple[int, int]:
    forbidden = 0
    authorities = 0
    if isinstance(value, Mapping):
        forbidden += sum(
            key in {"event_log", "program_store", "research_service", "workspace_manager"}
            for key in value
        )
        authorities += int("authorized_action" in value and value["authorized_action"] is not None)
        for item in value.values():
            nested_forbidden, nested_authorities = _scan_provider_value(item)
            forbidden += nested_forbidden
            authorities += nested_authorities
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        for item in value:
            nested_forbidden, nested_authorities = _scan_provider_value(item)
            forbidden += nested_forbidden
            authorities += nested_authorities
    elif isinstance(value, Path) or callable(value):
        forbidden += 1
    return forbidden, authorities


def _provider_no_capability(harness: Harness, _: Path) -> dict[str, Any]:
    forbidden, authorities = _scan_provider_value(harness.request.frozen_mapping())
    assert authorities == 0
    return {"forbidden_capability_count": forbidden, "authorized_action": None}


def _reject_packet(
    harness: Harness,
    _: Path,
    mutation: str,
    expected_code: str,
) -> dict[str, Any]:
    if mutation == "program_head":
        head = harness.packet.program_snapshot.program_head
        harness.store.append_knowledge_disposition(
            harness.packet.knowledge_disposition,
            harness.proposal,
            harness.result,
            harness.project_log,
            context_token=harness.packet.context_token,
            expected_program_head=head,
        )
        packet: Mapping[str, Any] = harness.packet.to_dict()
    else:
        packet = _mutated_packet(harness, mutation)
    before = harness.log_bytes()
    with pytest.raises(DecisionPacketError) as caught:
        _validate(harness, packet)
    assert caught.value.code == expected_code
    _assert_no_write(before, harness)
    return {"error_code": caught.value.code, "write_delta": 0}


def _pid_is_gone(pid: int) -> bool:
    deadline = time.monotonic() + 1.0
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        time.sleep(0.01)
    return False


def _reject_subprocess(
    harness: Harness,
    root: Path,
    mode: str,
    expected_code: str,
) -> dict[str, Any]:
    before = harness.log_bytes()
    arguments: tuple[str, ...] = ()
    timeout = 2.0
    output_limit = 2 * 1024 * 1024
    pid_path = root / "child.pid"
    if mode == "timeout":
        arguments = (str(pid_path),)
        timeout = 0.05
    elif mode == "output_limit":
        output_limit = 128
    with pytest.raises(ProviderPortError) as caught:
        _subprocess(mode, *arguments, timeout=timeout, output_limit=output_limit).invoke(
            harness.request
        )
    assert caught.value.code == expected_code
    if mode == "timeout":
        assert _pid_is_gone(int(pid_path.read_text(encoding="ascii")))
    _assert_no_write(before, harness)
    return {"error_code": caught.value.code, "write_delta": 0}


CaseHandler = Callable[[Harness, Path], dict[str, Any]]


def _packet_case(mutation: str, code: str) -> CaseHandler:
    return lambda harness, root: _reject_packet(harness, root, mutation, code)


def _process_case(mode: str, code: str) -> CaseHandler:
    return lambda harness, root: _reject_subprocess(harness, root, mode, code)


CASE_HANDLERS: dict[str, CaseHandler] = {
    "python-provider-valid": _python_provider_valid,
    "subprocess-provider-valid": _subprocess_provider_valid,
    "provider-port-canonical-parity": _provider_parity,
    "packet-current-context-program-binding": _current_read_set,
    "packet-retrieved-ids-reasons-binding": _retrieval_binding,
    "packet-proposal-disposition-binding": _proposal_disposition,
    "packet-validation-no-write": _validation_no_write,
    "provider-no-direct-capability": _provider_no_capability,
    "reject-wrong-packet-version": _packet_case("wrong_version", "DECISION_PACKET_INVALID"),
    "reject-bool-packet-version": _packet_case("bool_version", "DECISION_PACKET_INVALID"),
    "reject-extra-packet-key": _packet_case("extra_key", "DECISION_PACKET_INVALID"),
    "reject-forged-packet-id": _packet_case("packet_id", "DECISION_PACKET_INVALID"),
    "reject-request-id-mismatch": _packet_case("provider_request_id", "DECISION_PACKET_INVALID"),
    "reject-stale-context-token": _packet_case("context_token", "DECISION_PACKET_STALE"),
    "reject-forged-program-snapshot-digest": _packet_case(
        "program_snapshot_digest", "DECISION_PACKET_INVALID"
    ),
    "reject-forged-program-snapshot": _packet_case("program_snapshot", "DECISION_PACKET_INVALID"),
    "reject-stale-program-head": _packet_case("program_head", "DECISION_PACKET_STALE"),
    "reject-forged-query-digest": _packet_case("query_digest", "DECISION_PACKET_INVALID"),
    "reject-forged-result-digest": _packet_case(
        "retrieval_result_digest", "DECISION_PACKET_INVALID"
    ),
    "reject-missing-returned-claim": _packet_case("missing_claim", "DECISION_PACKET_INVALID"),
    "reject-duplicate-returned-claim": _packet_case("duplicate_claim", "DECISION_PACKET_INVALID"),
    "reject-forged-retrieval-reason": _packet_case("reason", "DECISION_PACKET_INVALID"),
    "reject-candidate-digest-mismatch": _packet_case("candidate", "DECISION_PACKET_INVALID"),
    "reject-proposal-generation-mismatch": _packet_case("generation_id", "DECISION_PACKET_INVALID"),
    "reject-proposal-class-mismatch": _packet_case(
        "hypothesis_class_id", "DECISION_PACKET_INVALID"
    ),
    "reject-proposal-scope-mismatch": _packet_case(
        "evaluation_scope_id", "DECISION_PACKET_INVALID"
    ),
    "reject-disposition-mismatch": _packet_case("knowledge_disposition", "DECISION_PACKET_INVALID"),
    "reject-non-null-authority": _packet_case("authorized_action", "DECISION_PACKET_INVALID"),
    "reject-subprocess-duplicate-key": _process_case("duplicate_key", "PROVIDER_PROTOCOL_INVALID"),
    "reject-subprocess-extra-stdout": _process_case("extra_stdout", "PROVIDER_PROTOCOL_INVALID"),
    "reject-subprocess-timeout": _process_case("timeout", "PROVIDER_TIMEOUT"),
    "reject-subprocess-output-limit": _process_case("output_limit", "PROVIDER_OUTPUT_LIMIT"),
}


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_frozen_m3a_contract_cases(case: dict[str, Any], tmp_path: Path) -> None:
    assert set(CASE_HANDLERS) == {item["id"] for item in CASES}
    harness = _harness(tmp_path / "vertical")
    actual = CASE_HANDLERS[case["id"]](harness, tmp_path)
    assert actual == case["expected"]


def test_manifest_contract_is_still_the_precommitted_32_case_set() -> None:
    assert (
        hashlib.sha256(MANIFEST_BYTES).hexdigest()
        == "a43ba5980c257706fe49f0c5107b520683f85ff46b3d7d9848071a0382d747a2"
    )
    assert len(CASES) == len({case["id"] for case in CASES}) == 32
    assert MANIFEST["case_groups"] == {"conformance": 8, "rejection": 24, "total": 32}


def test_recursive_nested_authority_extra_key_bool_and_live_values_fail_closed(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    mutations = []
    nested_authority = copy.deepcopy(harness.packet.to_dict())
    nested_authority["candidate"]["authorized_action"] = "trade"
    mutations.append(nested_authority)
    nested_extra = copy.deepcopy(harness.packet.to_dict())
    nested_extra["retrieval_manifest"]["returned_claims"][0]["extra"] = None
    mutations.append(nested_extra)
    nested_bool = copy.deepcopy(harness.packet.to_dict())
    nested_bool["program_snapshot"]["program_projection_schema_version"] = True
    mutations.append(nested_bool)
    live_path = copy.deepcopy(harness.packet.to_dict())
    live_path["candidate"]["path"] = tmp_path
    mutations.append(live_path)
    live_callable = copy.deepcopy(harness.packet.to_dict())
    live_callable["candidate"]["callback"] = lambda: None
    mutations.append(live_callable)
    before = harness.log_bytes()
    for raw in mutations:
        with pytest.raises(DecisionPacketError) as caught:
            _validate(harness, raw)
        assert caught.value.code == "DECISION_PACKET_INVALID"
    _assert_no_write(before, harness)


def test_provider_request_exact_schema_and_recursive_authority_fail_closed(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    extra = copy.deepcopy(harness.request.to_dict())
    extra["extra"] = None
    bool_version = copy.deepcopy(harness.request.to_dict())
    bool_version["provider_decision_request_schema_version"] = True
    nested_authority = copy.deepcopy(harness.request.to_dict())
    nested_authority["context"]["authority"]["authorized_action"] = "run"
    live_path = copy.deepcopy(harness.request.to_dict())
    live_path["context"]["path"] = tmp_path
    for raw in (extra, bool_version, nested_authority, live_path):
        with pytest.raises(DecisionPacketError) as caught:
            ProviderDecisionRequest.from_mapping(raw)
        assert caught.value.code == "DECISION_PACKET_INVALID"


def test_packet_canonical_size_limit_is_fail_closed_and_no_write(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    raw = copy.deepcopy(harness.packet.to_dict())
    raw["candidate"] = {"blob": "x" * (2 * 1024 * 1024)}
    before = harness.log_bytes()
    with pytest.raises(DecisionPacketError) as caught:
        _validate(harness, raw)
    assert caught.value.code == "DECISION_PACKET_INVALID"
    _assert_no_write(before, harness)


def test_subprocess_nonfinite_json_is_protocol_invalid(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with pytest.raises(ProviderPortError) as caught:
        _subprocess("nonfinite").invoke(harness.request)
    assert caught.value.code == "PROVIDER_PROTOCOL_INVALID"


def test_request_and_python_callback_are_recursively_immutable_value_data(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)

    class MutatingProvider:
        def decide(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
            with pytest.raises(TypeError):
                request["authorized_action"] = "run"  # type: ignore[index]
            context = request["context"]
            assert isinstance(context, Mapping)
            with pytest.raises(TypeError):
                context["new"] = None  # type: ignore[index]
            return harness.packet.to_dict()

    PythonProviderPort(MutatingProvider()).invoke(harness.request)


def test_python_provider_live_output_value_is_protocol_invalid(tmp_path: Path) -> None:
    harness = _harness(tmp_path)

    class LiveValueProvider:
        def decide(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
            del request
            return {"path": tmp_path}

    with pytest.raises(ProviderPortError) as caught:
        PythonProviderPort(LiveValueProvider()).invoke(harness.request)
    assert caught.value.code == "PROVIDER_PROTOCOL_INVALID"


def test_packet_acceptance_has_no_append_or_execution_side_effect(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    before = harness.log_bytes()
    validated = _validate(harness, harness.packet)
    assert validated.authorized_action is None
    assert validated.packet.authorized_action is None
    _assert_no_write(before, harness)


def test_closed_class_uses_existing_registration_preflight_without_log_mutation(
    tmp_path: Path,
) -> None:
    matrix = json.loads(
        (ROOT / "tests/fixtures/scientific_state/v3/m1d-transition-matrix.json").read_text(
            encoding="utf-8"
        )
    )
    case = next(
        item
        for item in matrix["gate_cases"]
        if item["id"] == "closed-class-precedes-parent-support-gate"
    )
    log = EventLog(tmp_path / "closed-class.jsonl", matrix["project_id"])
    for raw in case["input"]["event_history"]:
        log.append(
            raw["event_type"],
            raw["payload"],
            event_id=raw["event_id"],
            occurred_at=raw["occurred_at"],
        )
    state = reduce_scientific_state(log.read(), project_id=log.project_id)
    proposal = Proposal.from_mapping(case["input"]["request"]["proposal"])
    before = log.path.read_bytes()
    with pytest.raises(DecisionPacketError) as caught:
        _validate_current_proposal(packet=SimpleNamespace(proposal=proposal), state=state)
    assert caught.value.code == "DECISION_PACKET_INVALID"
    assert log.path.read_bytes() == before
