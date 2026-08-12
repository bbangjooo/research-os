from __future__ import annotations

import copy
import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from research_os.contracts.common import MAX_SAFE_JSON_INTEGER
from research_os.errors import ScientificStateError
from research_os.science import (
    MAX_DIAGNOSIS_NARRATIVE_UTF8_BYTES,
    Diagnosis,
    DiagnosisEventPayload,
    default_terminal_reason_code,
    diagnosis_id,
    normalize_terminal_status,
)

FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "scientific_state"
    / "v3"
    / "m1d-diagnosis-valid.json"
)


def _fixture() -> dict[str, Any]:
    value = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _first_payload() -> dict[str, Any]:
    return copy.deepcopy(_fixture()["cases"][0]["diagnosis_event"]["payload"])


def _assert_invalid(operation: Any, path: str) -> ScientificStateError:
    with pytest.raises(ScientificStateError) as caught:
        operation()
    assert caught.value.code == "DIAGNOSIS_INVALID"
    assert caught.value.details["path"] == path
    return caught.value


def test_frozen_canonical_eighteen_round_trip_with_prespecified_identities() -> None:
    fixture = _fixture()

    assert len(fixture["cases"]) == fixture["expected"]["cases"] == 18
    for case in fixture["cases"]:
        payload_raw = case["diagnosis_event"]["payload"]
        diagnosis = Diagnosis.from_mapping(payload_raw["diagnosis"])
        payload = DiagnosisEventPayload.from_mapping(
            payload_raw,
            project_id=fixture["project_id"],
        )

        assert diagnosis.to_dict() == payload_raw["diagnosis"]
        assert diagnosis.digest == case["expected"]["diagnosis_digest"]
        assert payload.diagnosis_digest == case["expected"]["diagnosis_digest"]
        assert payload.diagnosis_id == case["expected"]["diagnosis_id"]
        assert payload.to_dict() == payload_raw


def test_diagnosis_is_deeply_immutable_and_to_dict_is_detached() -> None:
    diagnosis = Diagnosis.from_mapping(_first_payload()["diagnosis"])

    with pytest.raises(FrozenInstanceError):
        diagnosis.failure_type = "evidence"  # type: ignore[misc]
    with pytest.raises(TypeError):
        diagnosis.artifact_evidence[0] = diagnosis.artifact_evidence[0]  # type: ignore[index]

    exported = diagnosis.to_dict()
    exported["artifact_evidence"].clear()
    exported["observation"]["gate_evaluations"].append({"id": "forged"})
    assert diagnosis.to_dict() == _first_payload()["diagnosis"]


def test_event_payload_builder_reconstructs_the_frozen_wrapper() -> None:
    fixture = _fixture()
    raw = _first_payload()
    body = Diagnosis.from_mapping(raw["diagnosis"])

    built = DiagnosisEventPayload.from_diagnosis(
        project_id=fixture["project_id"],
        generation_id=raw["generation_id"],
        study_contract_digest=raw["study_contract_digest"],
        evaluation_seal_digest=raw["evaluation_seal_digest"],
        compatibility_digest=raw["compatibility_digest"],
        diagnosis=body,
    )

    assert built.to_dict() == raw


@pytest.mark.parametrize("value", [True, False, 0, 2, 1.0, "1"])
def test_event_payload_version_requires_literal_integer_one(value: Any) -> None:
    fixture = _fixture()
    raw = _first_payload()
    raw["science_state_version"] = value
    _assert_invalid(
        lambda: DiagnosisEventPayload.from_mapping(
            raw,
            project_id=fixture["project_id"],
        ),
        "$.science_state_version",
    )


@pytest.mark.parametrize(
    ("mutate", "path"),
    [
        (lambda body: body.pop("falsifier"), "$"),
        (lambda body: body.__setitem__("unknown", None), "$"),
        (
            lambda body: body["terminal_evidence"].pop("event_hash"),
            "$.terminal_evidence",
        ),
        (
            lambda body: body["artifact_evidence"][0].__setitem__("unknown", None),
            "$.artifact_evidence[0]",
        ),
        (
            lambda body: body["observation"].pop("retryable"),
            "$.observation",
        ),
    ],
)
def test_nested_objects_require_exact_key_sets(mutate: Any, path: str) -> None:
    body = _first_payload()["diagnosis"]
    mutate(body)
    _assert_invalid(lambda: Diagnosis.from_mapping(body), path)


@pytest.mark.parametrize("value", [True, False, 0, 2, 1.0, "1"])
def test_diagnosis_schema_version_requires_literal_integer_one(value: Any) -> None:
    body = _first_payload()["diagnosis"]
    body["diagnosis_schema_version"] = value
    _assert_invalid(
        lambda: Diagnosis.from_mapping(body),
        "$.diagnosis_schema_version",
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("verified", 1),
        ("verified", 0),
        ("retryable", 1),
        ("retryable", "false"),
    ],
)
def test_observation_booleans_are_literal(field: str, value: Any) -> None:
    body = _first_payload()["diagnosis"]
    body["observation"][field] = value
    _assert_invalid(
        lambda: Diagnosis.from_mapping(body),
        f"$.observation.{field}",
    )


@pytest.mark.parametrize("field", ["interpretation", "falsifier"])
def test_narratives_use_exact_utf8_byte_limit(field: str) -> None:
    body = _first_payload()["diagnosis"]
    boundary = "🔬" * (MAX_DIAGNOSIS_NARRATIVE_UTF8_BYTES // 4)
    assert len(boundary.encode("utf-8")) == MAX_DIAGNOSIS_NARRATIVE_UTF8_BYTES
    body[field] = boundary
    parsed = Diagnosis.from_mapping(body)
    assert getattr(parsed, field) == boundary

    body[field] += "x"
    _assert_invalid(lambda: Diagnosis.from_mapping(body), f"$.{field}")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("interpretation", " leading"),
        ("interpretation", "trailing "),
        ("interpretation", "\ud800"),
        ("falsifier", "\udfff"),
    ],
)
def test_narratives_reject_noncanonical_text(field: str, value: str) -> None:
    body = _first_payload()["diagnosis"]
    body[field] = value
    _assert_invalid(lambda: Diagnosis.from_mapping(body), f"$.{field}")


def test_artifact_and_gate_evidence_require_canonical_unique_order() -> None:
    canonical = _fixture()["cases"][2]["diagnosis_event"]["payload"]["diagnosis"]

    body = copy.deepcopy(canonical)

    body["artifact_evidence"].reverse()
    _assert_invalid(lambda: Diagnosis.from_mapping(body), "$.artifact_evidence")

    body = copy.deepcopy(canonical)
    body["artifact_evidence"] = [body["artifact_evidence"][0]] * 2
    _assert_invalid(lambda: Diagnosis.from_mapping(body), "$.artifact_evidence")

    body = copy.deepcopy(canonical)
    body["observation"]["gate_evaluations"].reverse()
    _assert_invalid(
        lambda: Diagnosis.from_mapping(body),
        "$.observation.gate_evaluations",
    )

    body = copy.deepcopy(canonical)
    body["observation"]["gate_evaluations"][0]["passed"] = 0
    _assert_invalid(
        lambda: Diagnosis.from_mapping(body),
        "$.observation.gate_evaluations[0].passed",
    )

    body = copy.deepcopy(canonical)
    gate = body["observation"]["gate_evaluations"][0]
    body["observation"]["gate_evaluations"] = [gate, copy.deepcopy(gate)]
    _assert_invalid(
        lambda: Diagnosis.from_mapping(body),
        "$.observation.gate_evaluations",
    )


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), MAX_SAFE_JSON_INTEGER + 1])
def test_observation_numbers_are_canonical_finite_json_or_null(value: Any) -> None:
    body = _first_payload()["diagnosis"]
    body["observation"]["candidate_value"] = value
    _assert_invalid(
        lambda: Diagnosis.from_mapping(body),
        "$.observation.candidate_value",
    )


def test_status_normalization_and_reason_fallback_are_frozen() -> None:
    expected = {
        "SUCCESS": "SUCCEEDED",
        "PASSED": "SUCCEEDED",
        "COMPLETE": "COMPLETED",
        "TIMEOUT": "TIMED_OUT",
        "TIMEDOUT": "TIMED_OUT",
        "CANCELED": "CANCELLED",
        "ERROR": "FAILED",
    }
    assert {value: normalize_terminal_status(value) for value in expected} == expected
    assert default_terminal_reason_code("EXPERIMENT_STATUS_CHANGED") == "STATUS_CHANGED"
    assert default_terminal_reason_code("EXPERIMENT_TERMINATED") == "TERMINATED"

    body = _first_payload()["diagnosis"]
    body["observation"]["terminal_status"] = "PASSED"
    _assert_invalid(
        lambda: Diagnosis.from_mapping(body),
        "$.observation.terminal_status",
    )


def test_digest_and_id_mismatches_have_stable_codes_and_paths() -> None:
    fixture = _fixture()
    raw = _first_payload()

    raw["diagnosis_digest"] = "0" * 64
    with pytest.raises(ScientificStateError) as caught:
        DiagnosisEventPayload.from_mapping(raw, project_id=fixture["project_id"])
    assert caught.value.code == "DIAGNOSIS_DIGEST_MISMATCH"
    assert caught.value.details["path"] == "$.diagnosis_digest"

    raw = _first_payload()
    raw["diagnosis_id"] = "diagnosis_00000000000000000000000000000000"
    with pytest.raises(ScientificStateError) as caught:
        DiagnosisEventPayload.from_mapping(raw, project_id=fixture["project_id"])
    assert caught.value.code == "DIAGNOSIS_ID_MISMATCH"
    assert caught.value.details["path"] == "$.diagnosis_id"


def test_diagnosis_identity_is_project_scoped() -> None:
    raw = _first_payload()
    digest = Diagnosis.from_mapping(raw["diagnosis"]).digest

    assert diagnosis_id(_fixture()["project_id"], digest) == raw["diagnosis_id"]
    assert diagnosis_id("a-distinct-project", digest) != raw["diagnosis_id"]


def test_authority_is_always_literal_null() -> None:
    fixture = _fixture()
    raw = _first_payload()
    raw["diagnosis"]["authorized_action"] = False
    _assert_invalid(
        lambda: DiagnosisEventPayload.from_mapping(raw, project_id=fixture["project_id"]),
        "$.authorized_action",
    )

    raw = _first_payload()
    raw["authorized_action"] = {}
    _assert_invalid(
        lambda: DiagnosisEventPayload.from_mapping(raw, project_id=fixture["project_id"]),
        "$.authorized_action",
    )
