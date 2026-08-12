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
from research_os.kernel._canonical import canonical_bytes, sha256_hex
from research_os.kernel.events import Event, EventLog
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


def test_diagnosis_retry_after_successor_reuses_the_original_event(
    tmp_path: Path,
) -> None:
    matrix = _json(V3_FIXTURES / "m1d-transition-matrix.json")
    gate_cases = matrix["gate_cases"]
    assert isinstance(gate_cases, list)
    case = next(
        item
        for item in gate_cases
        if item["id"] == "diagnosed-stop-allows-genuine-changed-successor"
    )
    history = copy.deepcopy(case["input"]["event_history"])
    successor = copy.deepcopy(case["expected"]["appended_event"])
    diagnosis_event = next(
        event for event in history if event["event_type"] == DIAGNOSIS_EVENT_TYPE
    )

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
    for raw in [*history, successor]:
        appended = service.event_log.append(
            raw["event_type"],
            raw["payload"],
            event_id=raw["event_id"],
            occurred_at=raw["occurred_at"],
        )
        assert appended.to_dict() == raw

    before = service.event_log.path.read_bytes()
    result = service.record_diagnosis(diagnosis_event["payload"]["diagnosis"])

    assert result["appended"] is False
    assert result["appended_events"] == 0
    assert result["idempotent_reuse"] is True
    assert result["event_id"] == diagnosis_event["event_id"]
    assert result["event_hash"] == diagnosis_event["hash"]
    assert service.event_log.path.read_bytes() == before


def test_replay_rejects_a_persisted_duplicate_diagnosis_after_successor(
    tmp_path: Path,
) -> None:
    matrix = _json(V3_FIXTURES / "m1d-transition-matrix.json")
    gate_cases = matrix["gate_cases"]
    assert isinstance(gate_cases, list)
    case = next(
        item
        for item in gate_cases
        if item["id"] == "diagnosed-stop-allows-genuine-changed-successor"
    )
    history = copy.deepcopy(case["input"]["event_history"])
    successor = copy.deepcopy(case["expected"]["appended_event"])
    diagnosis_event = next(
        event for event in history if event["event_type"] == DIAGNOSIS_EVENT_TYPE
    )

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
    for raw in [*history, successor]:
        appended = service.event_log.append(
            raw["event_type"],
            raw["payload"],
            event_id=raw["event_id"],
            occurred_at=raw["occurred_at"],
        )
        assert appended.to_dict() == raw
    service.event_log.append(
        DIAGNOSIS_EVENT_TYPE,
        diagnosis_event["payload"],
        event_id="evt_successor_duplicate_diagnosis_08",
        occurred_at="2026-08-10T01:00:08.000000Z",
    )

    with pytest.raises(ScientificStateError) as caught:
        service.replay()

    assert caught.value.code == "DIAGNOSIS_ALREADY_RECORDED"
    assert caught.value.details["path"] == "$.experiment_id"


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
        mock.patch.object(
            service,
            "_doctor",
            side_effect=AssertionError("doctor must not run before a pending gate"),
        ) as doctor,
        mock.patch.object(
            service,
            "_recover_incomplete_experiments",
            side_effect=AssertionError("recovery must not run before a pending gate"),
        ) as recover,
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
    doctor.assert_not_called()
    recover.assert_not_called()


def test_run_once_stopped_state_rejects_before_doctor_or_recovery(
    tmp_path: Path,
) -> None:
    project, service, _ = _service_with_history(tmp_path, record_id="untrusted")
    candidate = {"x": 9}
    candidate_path = project / "candidate-m1d-stopped.json"
    candidate_path.write_text(json.dumps(candidate) + "\n", encoding="utf-8")
    before = service.event_log.path.read_bytes()

    with (
        mock.patch.object(
            service,
            "_doctor",
            side_effect=AssertionError("doctor must not run before a stop gate"),
        ) as doctor,
        mock.patch.object(
            service,
            "_recover_incomplete_experiments",
            side_effect=AssertionError("recovery must not run before a stop gate"),
        ) as recover,
    ):
        with pytest.raises(ScientificStateError) as caught:
            service.run_once(
                candidate_path,
                proposal=_fresh_explore_proposal(candidate),
            )

    assert caught.value.code == "STUDY_STOPPED"
    assert service.event_log.path.read_bytes() == before
    doctor.assert_not_called()
    recover.assert_not_called()


@pytest.mark.parametrize(
    ("record_id", "error_code"),
    [("timed-out", "DIAGNOSIS_REQUIRED"), ("untrusted", "STUDY_STOPPED")],
)
def test_recovery_created_terminal_rechecks_state_gate_before_candidate_work(
    tmp_path: Path,
    record_id: str,
    error_code: str,
) -> None:
    project, service, terminal = _service_with_history(
        tmp_path,
        record_id=record_id,
        include_terminal=False,
    )
    assert terminal is not None
    missing_candidate = project / "candidate-must-not-be-read.json"
    proposal = _fresh_explore_proposal({"x": 9})

    def recover_terminal() -> list[str]:
        appended = service.event_log.append(
            terminal["event_type"],
            terminal["payload"],
            event_id=terminal["event_id"],
            occurred_at=terminal["occurred_at"],
        )
        assert appended.to_dict() == terminal
        return [str(terminal["payload"]["experiment_id"])]

    with (
        mock.patch.object(
            service,
            "_doctor",
            return_value=_matching_report(service),
        ) as doctor,
        mock.patch.object(
            service,
            "_recover_incomplete_experiments",
            side_effect=recover_terminal,
        ) as recover,
    ):
        with pytest.raises(ScientificStateError) as caught:
            service.run_once(missing_candidate, proposal=proposal)

    assert caught.value.code == error_code
    assert not missing_candidate.exists()
    doctor.assert_called_once_with()
    recover.assert_called_once_with()


def test_typed_first_attempt_without_proposal_keeps_public_error_code(
    tmp_path: Path,
) -> None:
    project, service, _ = _service_with_history(tmp_path)
    service.record_diagnosis(_fixture_diagnosis("retryable-timeout"))
    candidate_path = project / "candidate-missing-proposal.json"
    candidate_path.write_text('{"x":9}\n', encoding="utf-8")

    with mock.patch.object(
        service,
        "_doctor",
        side_effect=AssertionError("doctor must not run for a missing Proposal"),
    ) as doctor:
        with pytest.raises(ScientificStateError) as caught:
            service.run_once(candidate_path)

    assert caught.value.code == "PROPOSAL_REQUIRED"
    doctor.assert_not_called()


@pytest.mark.parametrize(
    ("record_id", "error_code"),
    [
        ("timed-out", "DIAGNOSIS_REQUIRED"),
        ("nonterminal-running", "STUDY_ACTIVE_EXPERIMENTS"),
    ],
)
def test_explicit_successor_gate_precedes_contract_and_evaluator_work(
    tmp_path: Path,
    record_id: str,
    error_code: str,
) -> None:
    _, service, _ = _service_with_history(tmp_path, record_id=record_id)
    generation_event = next(
        event
        for event in service.event_log.read()
        if event.event_type == "research.study_generation_opened.v1"
    )

    with mock.patch.object(
        service,
        "_doctor_snapshot",
        side_effect=AssertionError("evaluator must not run before successor gates"),
    ) as doctor:
        with pytest.raises(ScientificStateError) as caught:
            service.open_generation(
                {},
                predecessor_generation_id=generation_event.payload["generation_id"],
                change_reason="A genuine changed successor request.",
            )

    assert caught.value.code == error_code
    doctor.assert_not_called()


def test_changed_contract_without_explicit_metadata_still_preflights_successor(
    tmp_path: Path,
) -> None:
    _, service, _ = _service_with_history(tmp_path)
    generation_event = next(
        event
        for event in service.event_log.read()
        if event.event_type == "research.study_generation_opened.v1"
    )
    changed_contract = copy.deepcopy(generation_event.payload["contract"])
    changed_contract["budget"]["max_attempts"] += 1

    with mock.patch.object(
        service,
        "_doctor_snapshot",
        side_effect=AssertionError("evaluator must not run before successor gates"),
    ) as doctor:
        with pytest.raises(ScientificStateError) as caught:
            service.open_generation(changed_contract)

    assert caught.value.code == "DIAGNOSIS_REQUIRED"
    doctor.assert_not_called()


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


def test_replay_retries_instead_of_mixing_projection_and_science_heads(
    tmp_path: Path,
) -> None:
    project, service, _ = _service_with_history(tmp_path)
    diagnosis = _fixture_diagnosis("retryable-timeout")
    second_rebuild_finished = ThreadEvent()
    diagnosis_committed = ThreadEvent()
    original_rebuild = service.projection.rebuild
    rebuild_calls = 0

    def rebuild_then_pause(event_log):
        nonlocal rebuild_calls
        count = original_rebuild(event_log)
        rebuild_calls += 1
        if rebuild_calls == 2:
            second_rebuild_finished.set()
            assert diagnosis_committed.wait(timeout=15)
        return count

    with (
        mock.patch.object(
            service.projection,
            "rebuild",
            side_effect=rebuild_then_pause,
        ),
        mock.patch.object(
            service,
            "_validate_baseline_payload",
            side_effect=lambda payload, *_args, **_kwargs: dict(payload),
        ),
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        future = executor.submit(service.replay)
        assert second_rebuild_finished.wait(timeout=15)
        try:
            recorded = ResearchService(project).record_diagnosis(diagnosis)
            assert recorded["appended_events"] == 1
        finally:
            diagnosis_committed.set()
        replayed = future.result(timeout=30)

    canonical_count = len(service.event_log.read())
    assert rebuild_calls >= 3
    assert replayed["events_replayed"] == canonical_count
    assert replayed["status"]["last_sequence"] == canonical_count
    assert replayed["science"]["diagnosis_count"] == 1


def test_replay_rebuilds_a_direct_projection_write_before_returning(
    tmp_path: Path,
) -> None:
    _, service, _ = _service_with_history(tmp_path)
    first_status_read = ThreadEvent()
    direct_apply_finished = ThreadEvent()
    original_status = service.projection.project_status
    status_calls = 0

    def status_then_pause(project_id: str) -> dict[str, Any]:
        nonlocal status_calls
        result = original_status(project_id)
        status_calls += 1
        if status_calls == 1:
            first_status_read.set()
            assert direct_apply_finished.wait(timeout=15)
        return result

    with (
        mock.patch.object(
            service.projection,
            "project_status",
            side_effect=status_then_pause,
        ),
        mock.patch.object(
            service,
            "_validate_baseline_payload",
            side_effect=lambda payload, *_args, **_kwargs: dict(payload),
        ),
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        future = executor.submit(service.replay)
        assert first_status_read.wait(timeout=15)
        try:
            canonical_events = service.event_log.read()
            canonical_head = canonical_events[-1]
            unsigned = {
                "event_id": "evt_direct_projection_race",
                "event_type": "vendor.projection_race.v1",
                "occurred_at": "2026-08-10T23:59:59.000000Z",
                "payload": {"authorized_action": None},
                "prev_hash": canonical_head.hash,
                "project_id": service.config.project_id,
                "sequence": canonical_head.sequence + 1,
                "version": 1,
            }
            direct_event = Event.from_mapping(
                {**unsigned, "hash": sha256_hex(canonical_bytes(unsigned))}
            )
            assert service.projection.apply(direct_event) is True
        finally:
            direct_apply_finished.set()
        replayed = future.result(timeout=30)

    canonical_events = service.event_log.read()
    canonical_head = canonical_events[-1]
    canonical_count = len(canonical_events)
    assert status_calls >= 4
    assert replayed["events_replayed"] == canonical_count
    assert replayed["status"]["last_sequence"] == canonical_count
    assert replayed["status"]["last_hash"] == canonical_head.hash
    assert service.projection.project_status(service.config.project_id) == replayed[
        "status"
    ]


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
