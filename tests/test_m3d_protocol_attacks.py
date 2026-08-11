from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tests.test_m3a_decision_packet import CASE_HANDLERS, CASES, _harness

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/protocol_attacks/v1/manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
ATTACKS = tuple(MANIFEST["cases"])
FROZEN_SHA = "8018d01c684c100b7d61acbb2232e09aa36a0925df7818d135e1dc32136b11b8"


def test_protocol_attack_manifest_is_exact_literal_non_vacuous_set() -> None:
    assert hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest() == FROZEN_SHA
    assert MANIFEST["case_count"] == len(ATTACKS) == len({item["id"] for item in ATTACKS}) == 24
    source_rejections = {
        item["id"]: item
        for item in CASES
        if isinstance(item.get("expected"), dict) and "error_code" in item["expected"]
    }
    assert set(source_rejections) == {item["source_case_id"] for item in ATTACKS}
    assert set(CASE_HANDLERS).issuperset(source_rejections)
    for attack in ATTACKS:
        source = source_rejections[attack["source_case_id"]]
        assert attack["malformed_input"] == source["mutation"]
        assert attack["expected"]["error_code"] == source["expected"]["error_code"]
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
    before_project, before_program = harness.log_bytes()
    autonomy = tmp_path / "autonomy-sentinel.jsonl"
    autonomy.write_bytes(b"")
    before_autonomy = autonomy.read_bytes()
    actual = CASE_HANDLERS[attack["source_case_id"]](harness, tmp_path)
    assert actual["error_code"] == attack["expected"]["error_code"]
    assert actual["write_delta"] == 0
    assert harness.project_log.path.read_bytes() == before_project
    if attack["id"] == "reject-stale-program-head":
        assert harness.store.log.path.read_bytes() != before_program
    else:
        assert harness.store.log.path.read_bytes() == before_program
    assert autonomy.read_bytes() == before_autonomy
