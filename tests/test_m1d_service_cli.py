from __future__ import annotations

import copy
import io
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from threading import Barrier
from threading import Event as ThreadEvent
from typing import Any
from unittest import mock

import pytest

from research_os.cli import main
from research_os.contracts import sha256_json
from research_os.errors import IntegrityError, ScientificStateError
from research_os.kernel.events import EventLog
from research_os.science import EvaluationSeal
from research_os.service import DoctorReport, ResearchService

ROOT = Path(__file__).resolve().parents[1]
V3_FIXTURES = ROOT / "tests" / "fixtures" / "scientific_state" / "v3"
DIAGNOSIS_EVENT_TYPE = "research.experiment_diagnosed.v1"
DIAGNOSIS_RESULT_KEYS = {
    "project_id",
    "event_type",
    "event_id",
    "event_hash",
    "event_sequence",
    "experiment_id",
    "diagnosis_id",
    "diagnosis_digest",
    "appended",
    "appended_events",
    "idempotent_reuse",
    "authorized_action",
}


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _fixture_record(record_id: str) -> dict[str, Any]:
    fixture = _json(V3_FIXTURES / "m1d-terminal-corpus.json")
    records = fixture["records"]
    assert isinstance(records, list)
    return next(record for record in records if record["id"] == record_id)


def _fixture_diagnosis(case_id: str) -> dict[str, Any]:
    fixture = _json(V3_FIXTURES / "m1d-diagnosis-valid.json")
    cases = fixture["cases"]
    assert isinstance(cases, list)
    selected = next(case for case in cases if case["id"] == case_id)
    return copy.deepcopy(selected["diagnosis_event"]["payload"]["diagnosis"])


def _service_with_history(
    tmp_path: Path,
    *,
    record_id: str = "timed-out",
    include_terminal: bool = True,
) -> tuple[Path, ResearchService, dict[str, Any] | None]:
    project = tmp_path / "project"
    shutil.copytree(ROOT / "examples" / "toy_optimization", project)
    runtime = project / ".research-os" / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    config_path = project / ".research-os" / "project.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'id = "toy-optimization"',
            'id = "fixture-m1d"',
        ),
        encoding="utf-8",
    )
    service = ResearchService(project)
    fixture = _fixture_record(record_id)
    raw_history = fixture["canonical_history"]
    assert isinstance(raw_history, list)
    terminal: dict[str, Any] | None = None
    for raw in raw_history:
        if raw["event_type"] == "EXPERIMENT_TERMINATED" and not include_terminal:
            terminal = copy.deepcopy(raw)
            continue
        appended = service.event_log.append(
            raw["event_type"],
            raw["payload"],
            event_id=raw["event_id"],
            occurred_at=raw["occurred_at"],
        )
        assert appended.to_dict() == raw
    return project, service, terminal


def _matching_report(service: ResearchService) -> DoctorReport:
    return DoctorReport(
        project_id=service.config.project_id,
        project_root=str(service.config.root),
        capabilities=(),
        side_effects=(),
        adapter_fingerprint={},
        fingerprints={
            "compatibility_digest": "d" * 64,
            "source_tree_digest": "a" * 64,
        },
        event_count=len(service.event_log.read()),
    )


def _fresh_explore_proposal(candidate: dict[str, Any]) -> dict[str, Any]:
    proposal = copy.deepcopy(
        next(
            event["payload"]["proposal"]
            for event in _fixture_record("timed-out")["canonical_history"]
            if event["event_type"] == "EXPERIMENT_REGISTERED"
        )
    )
    proposal.update(
        {
            "candidate_digest": sha256_json(candidate),
            "hypothesis_class_id": "class-a",
            "mechanism": "A distinct locked-registration race mechanism.",
            "predicted_effect": "The primary metric changes under one intervention.",
            "falsifier": "The frozen terminal evidence does not support the prediction.",
        }
    )
    return proposal


def test_record_diagnosis_is_exact_idempotent_and_rejects_a_different_body(
    tmp_path: Path,
) -> None:
    _, service, _ = _service_with_history(tmp_path)
    diagnosis = _fixture_diagnosis("retryable-timeout")

    first = service.record_diagnosis(diagnosis)
    bytes_after_first = service.event_log.path.read_bytes()
    projection_after_first = service.projection.path.read_bytes()
    second = service.record_diagnosis(copy.deepcopy(diagnosis))

    assert set(first) == DIAGNOSIS_RESULT_KEYS
    assert set(second) == DIAGNOSIS_RESULT_KEYS
    assert first["appended"] is True
    assert first["appended_events"] == 1
    assert first["idempotent_reuse"] is False
    assert second["appended"] is False
    assert second["appended_events"] == 0
    assert second["idempotent_reuse"] is True
    for key in (
        "event_id",
        "event_hash",
        "event_sequence",
        "experiment_id",
        "diagnosis_id",
        "diagnosis_digest",
    ):
        assert second[key] == first[key]
    assert first["authorized_action"] is None
    assert second["authorized_action"] is None
    assert service.event_log.path.read_bytes() == bytes_after_first
    assert service.projection.path.read_bytes() == projection_after_first

    different = copy.deepcopy(diagnosis)
    different["interpretation"] = "A different evidence-bound interpretation."
    before_rejection = service.event_log.path.read_bytes()
    before_projection = service.projection.path.read_bytes()
    with pytest.raises(ScientificStateError) as caught:
        service.record_diagnosis(different)

    assert caught.value.code == "DIAGNOSIS_ALREADY_RECORDED"
    assert service.event_log.path.read_bytes() == before_rejection
    assert service.projection.path.read_bytes() == before_projection
    diagnosis_events = [
        event
        for event in service.event_log.read()
        if event.event_type == DIAGNOSIS_EVENT_TYPE
    ]
    assert len(diagnosis_events) == 1


def test_concurrent_identical_diagnoses_return_two_successes_and_one_event(
    tmp_path: Path,
) -> None:
    project, _, _ = _service_with_history(tmp_path)
    diagnosis = _fixture_diagnosis("retryable-timeout")
    barrier = Barrier(2)
    original_append = EventLog.append

    def append_after_barrier(event_log, event_type, *args, **kwargs):
        if event_type == DIAGNOSIS_EVENT_TYPE:
            barrier.wait(timeout=15)
        return original_append(event_log, event_type, *args, **kwargs)

    def submit(_: int) -> dict[str, Any]:
        return ResearchService(project).record_diagnosis(copy.deepcopy(diagnosis))

    with (
        mock.patch.object(EventLog, "append", new=append_after_barrier),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        results = list(executor.map(submit, range(2)))

    events = ResearchService(project).event_log.read()
    diagnosis_events = [
        event for event in events if event.event_type == DIAGNOSIS_EVENT_TYPE
    ]
    assert len(diagnosis_events) == 1
    assert sum(int(result["appended_events"]) for result in results) == 1
    assert sum(int(result["idempotent_reuse"]) for result in results) == 1
    assert {result["event_id"] for result in results} == {
        diagnosis_events[0].event_id
    }
    assert {result["event_hash"] for result in results} == {
        diagnosis_events[0].hash
    }
    assert all(result["authorized_action"] is None for result in results)


def test_record_diagnosis_revalidates_the_complete_canonical_history(
    tmp_path: Path,
) -> None:
    _, service, _ = _service_with_history(tmp_path)
    diagnosis = _fixture_diagnosis("retryable-timeout")
    corrupted = service.event_log.path.read_bytes().replace(
        b'"status":"active"',
        b'"status":"stale"',
        1,
    )
    assert corrupted != service.event_log.path.read_bytes()
    service.event_log.path.write_bytes(corrupted)
    before = service.event_log.path.read_bytes()

    with pytest.raises(IntegrityError):
        service.record_diagnosis(diagnosis)

    assert service.event_log.path.read_bytes() == before


@pytest.mark.parametrize("retry", [False, True])
def test_run_once_first_and_retry_stop_at_the_pending_diagnosis_gate(
    tmp_path: Path,
    retry: bool,
) -> None:
    project, service, _ = _service_with_history(tmp_path)
    candidate = {"x": 5 if retry else 9}
    candidate_path = project / "candidate-m1d.json"
    candidate_path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")
    registration = next(
        event.payload
        for event in service.event_log.read()
        if event.event_type == "EXPERIMENT_REGISTERED"
    )
    run_arguments = (
        {"retry_of": registration["experiment_id"]}
        if retry
        else {"proposal": _fresh_explore_proposal(candidate)}
    )
    before = service.event_log.path.read_bytes()

    with (
        mock.patch.object(service, "_doctor", return_value=_matching_report(service)),
        mock.patch.object(service, "_recover_incomplete_experiments"),
        mock.patch.object(
            service,
            "_evaluation_seal_from_report",
            return_value=EvaluationSeal.from_mapping(
                service.study_status()["evaluation_seal"]
            ),
        ),
        mock.patch.object(service, "_validate_typed_generation_environment"),
        mock.patch.object(
            service,
            "_call_sealed",
            side_effect=AssertionError("adapter must not run past a pending gate"),
        ),
    ):
        with pytest.raises(ScientificStateError) as caught:
            service.run_once(candidate_path, **run_arguments)

    assert caught.value.code == "DIAGNOSIS_REQUIRED"
    assert service.event_log.path.read_bytes() == before


def test_locked_registration_rechecks_a_terminal_that_wins_the_race(
    tmp_path: Path,
) -> None:
    project, service, terminal = _service_with_history(
        tmp_path,
        include_terminal=False,
    )
    assert terminal is not None
    candidate = {"x": 9}
    candidate_path = project / "candidate-m1d-race.json"
    candidate_path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")
    proposal = _fresh_explore_proposal(candidate)
    registration_reached = ThreadEvent()
    terminal_committed = ThreadEvent()
    original_registration_append = service._append_registration_event
    existing_registration = next(
        event.payload
        for event in service.event_log.read()
        if event.event_type == "EXPERIMENT_REGISTERED"
    )

    def append_after_terminal(*args, **kwargs):
        registration_reached.set()
        assert terminal_committed.wait(timeout=15)
        return original_registration_append(*args, **kwargs)

    def run() -> ScientificStateError:
        try:
            service.run_once(candidate_path, proposal=proposal)
        except ScientificStateError as exc:
            return exc
        raise AssertionError("registration unexpectedly won the forced race")

    with (
        mock.patch.object(service, "_doctor", return_value=_matching_report(service)),
        mock.patch.object(service, "_recover_incomplete_experiments"),
        mock.patch.object(
            service,
            "_evaluation_seal_from_report",
            return_value=EvaluationSeal.from_mapping(
                service.study_status()["evaluation_seal"]
            ),
        ),
        mock.patch.object(service, "_validate_typed_generation_environment"),
        mock.patch.object(service, "_assert_static_compatibility"),
        mock.patch.object(
            service,
            "_compatible_baseline",
            return_value={"baseline_id": existing_registration["baseline_id"]},
        ),
        mock.patch.object(
            service,
            "_append_registration_event",
            side_effect=append_after_terminal,
        ),
        mock.patch.object(
            service,
            "_call_sealed",
            side_effect=AssertionError("adapter must not run for the race loser"),
        ),
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        future = executor.submit(run)
        if not registration_reached.wait(timeout=15):
            failure = future.exception(timeout=1)
            raise AssertionError(
                "registration did not reach the forced-race append boundary"
            ) from failure
        appended = service.event_log.append(
            terminal["event_type"],
            terminal["payload"],
            event_id=terminal["event_id"],
            occurred_at=terminal["occurred_at"],
        )
        assert appended.to_dict() == terminal
        terminal_committed.set()
        error = future.result(timeout=30)

    assert error.code == "DIAGNOSIS_REQUIRED"
    events = service.event_log.read()
    assert sum(event.event_type == "EXPERIMENT_REGISTERED" for event in events) == 1
    assert sum(event.event_type == "EXPERIMENT_TERMINATED" for event in events) == 1


def test_diagnose_cli_prints_the_actual_public_service_result(tmp_path: Path) -> None:
    project, _, _ = _service_with_history(tmp_path)
    diagnosis_path = project / "diagnosis.json"
    diagnosis_path.write_text(
        json.dumps(_fixture_diagnosis("retryable-timeout"), sort_keys=True) + "\n",
        encoding="utf-8",
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    with redirect_stdout(stdout), redirect_stderr(stderr):
        code = main(
            [
                "--project",
                str(project),
                "diagnose",
                str(diagnosis_path),
            ]
        )

    assert code == 0
    assert stderr.getvalue() == ""
    result = json.loads(stdout.getvalue())
    assert set(result) == DIAGNOSIS_RESULT_KEYS
    assert result["event_type"] == DIAGNOSIS_EVENT_TYPE
    assert result["appended"] is True
    assert result["appended_events"] == 1
    assert result["idempotent_reuse"] is False
    assert result["authorized_action"] is None
    diagnosis_events = [
        event
        for event in ResearchService(project).event_log.read()
        if event.event_type == DIAGNOSIS_EVENT_TYPE
    ]
    assert len(diagnosis_events) == 1
    assert result["event_id"] == diagnosis_events[0].event_id
    assert result["event_hash"] == diagnosis_events[0].hash
