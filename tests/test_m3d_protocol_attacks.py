from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from research_os.autonomy import AutonomyEpisodeLog, DecisionPacketError, ProviderPortError
from research_os.kernel.ids import stable_id
from tests.test_m3a_decision_packet import (
    Harness,
    _harness,
    _mutated_packet,
    _pid_is_gone,
    _subprocess,
    _validate,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/protocol_attacks/v1/manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
ATTACKS = tuple(MANIFEST["cases"])
FROZEN_SHA = "8018d01c684c100b7d61acbb2232e09aa36a0925df7818d135e1dc32136b11b8"


@dataclass(frozen=True, slots=True)
class AttackHandler:
    malformed_input: str
    expected_code: str
    execute: Callable[[Harness, Path], dict[str, Any]]


def _actual_autonomy_snapshot(
    harness: Harness, root: Path, label: str
) -> tuple[Path, bytes | None]:
    log = AutonomyEpisodeLog(
        root / "autonomy",
        harness.project_log.project_id,
        stable_id("episode", "m3d-attack", label),
    )
    path = log.log.path
    return path, path.read_bytes() if path.exists() else None


def _packet_attack(
    harness: Harness,
    root: Path,
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
    autonomy_path, before_autonomy = _actual_autonomy_snapshot(harness, root, mutation)
    before_project = harness.project_log.path.read_bytes()
    before_program = harness.store.log.path.read_bytes()
    with pytest.raises(DecisionPacketError) as caught:
        _validate(harness, packet)
    assert caught.value.code == expected_code
    assert harness.project_log.path.read_bytes() == before_project
    assert harness.store.log.path.read_bytes() == before_program
    assert (autonomy_path.read_bytes() if autonomy_path.exists() else None) == before_autonomy
    return {"error_code": caught.value.code, "write_delta": 0}


def _process_attack(
    harness: Harness,
    root: Path,
    mode: str,
    expected_code: str,
) -> dict[str, Any]:
    autonomy_path, before_autonomy = _actual_autonomy_snapshot(harness, root, mode)
    before_project = harness.project_log.path.read_bytes()
    before_program = harness.store.log.path.read_bytes()
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
    assert harness.project_log.path.read_bytes() == before_project
    assert harness.store.log.path.read_bytes() == before_program
    assert (autonomy_path.read_bytes() if autonomy_path.exists() else None) == before_autonomy
    return {"error_code": caught.value.code, "write_delta": 0}


def _packet_case(mutation: str, code: str) -> AttackHandler:
    return AttackHandler(
        mutation,
        code,
        lambda harness, root: _packet_attack(harness, root, mutation, code),
    )


def _process_case(mode: str, code: str) -> AttackHandler:
    return AttackHandler(
        mode,
        code,
        lambda harness, root: _process_attack(harness, root, mode, code),
    )


# This is the M3-D-owned literal denominator. It intentionally does not import
# M3-A's CASE_HANDLERS or derive handlers from the older manifest.
ATTACK_HANDLERS = {
    "reject-wrong-packet-version": _packet_case("wrong_version", "DECISION_PACKET_INVALID"),
    "reject-bool-packet-version": _packet_case("bool_version", "DECISION_PACKET_INVALID"),
    "reject-extra-packet-key": _packet_case("extra_key", "DECISION_PACKET_INVALID"),
    "reject-forged-packet-id": _packet_case("packet_id", "DECISION_PACKET_INVALID"),
    "reject-request-id-mismatch": _packet_case("provider_request_id", "DECISION_PACKET_INVALID"),
    "reject-stale-context-token": _packet_case("context_token", "DECISION_PACKET_STALE"),
    "reject-forged-program-snapshot-digest": _packet_case(
        "program_snapshot_digest", "DECISION_PACKET_INVALID"
    ),
    "reject-forged-program-snapshot": _packet_case(
        "program_snapshot", "DECISION_PACKET_INVALID"
    ),
    "reject-stale-program-head": _packet_case("program_head", "DECISION_PACKET_STALE"),
    "reject-forged-query-digest": _packet_case("query_digest", "DECISION_PACKET_INVALID"),
    "reject-forged-result-digest": _packet_case(
        "retrieval_result_digest", "DECISION_PACKET_INVALID"
    ),
    "reject-missing-returned-claim": _packet_case(
        "missing_claim", "DECISION_PACKET_INVALID"
    ),
    "reject-duplicate-returned-claim": _packet_case(
        "duplicate_claim", "DECISION_PACKET_INVALID"
    ),
    "reject-forged-retrieval-reason": _packet_case("reason", "DECISION_PACKET_INVALID"),
    "reject-candidate-digest-mismatch": _packet_case("candidate", "DECISION_PACKET_INVALID"),
    "reject-proposal-generation-mismatch": _packet_case(
        "generation_id", "DECISION_PACKET_INVALID"
    ),
    "reject-proposal-class-mismatch": _packet_case(
        "hypothesis_class_id", "DECISION_PACKET_INVALID"
    ),
    "reject-proposal-scope-mismatch": _packet_case(
        "evaluation_scope_id", "DECISION_PACKET_INVALID"
    ),
    "reject-disposition-mismatch": _packet_case(
        "knowledge_disposition", "DECISION_PACKET_INVALID"
    ),
    "reject-non-null-authority": _packet_case(
        "authorized_action", "DECISION_PACKET_INVALID"
    ),
    "reject-subprocess-duplicate-key": _process_case(
        "duplicate_key", "PROVIDER_PROTOCOL_INVALID"
    ),
    "reject-subprocess-extra-stdout": _process_case(
        "extra_stdout", "PROVIDER_PROTOCOL_INVALID"
    ),
    "reject-subprocess-timeout": _process_case("timeout", "PROVIDER_TIMEOUT"),
    "reject-subprocess-output-limit": _process_case(
        "output_limit", "PROVIDER_OUTPUT_LIMIT"
    ),
}


def test_protocol_attack_manifest_is_exact_literal_non_vacuous_set() -> None:
    assert hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest() == FROZEN_SHA
    assert MANIFEST["case_count"] == len(ATTACKS) == len({item["id"] for item in ATTACKS}) == 24
    assert set(ATTACK_HANDLERS) == {item["id"] for item in ATTACKS}
    for attack in ATTACKS:
        handler = ATTACK_HANDLERS[attack["id"]]
        assert handler.malformed_input == attack["malformed_input"]
        assert handler.expected_code == attack["expected"]["error_code"]
        assert attack["expected"] | {
            "project_log_delta": 0,
            "program_log_delta": 0,
            "autonomy_log_delta": 0,
        } == attack["expected"]


@pytest.mark.parametrize("attack", ATTACKS, ids=lambda item: item["id"])
def test_every_protocol_attack_executes_once_without_truth_owner_write(
    attack: dict[str, Any], tmp_path: Path
) -> None:
    harness = _harness(tmp_path / "vertical")
    actual = ATTACK_HANDLERS[attack["id"]].execute(harness, tmp_path)
    assert actual == {
        "error_code": attack["expected"]["error_code"],
        "write_delta": 0,
    }
