from __future__ import annotations

import json
import multiprocessing
import queue
import shutil
from pathlib import Path
from typing import Any

import pytest

from research_os.errors import ScientificStateError, StaleAgentContextError
from research_os.science import (
    StudyContract,
    reduce_scientific_state,
    registration_payload_fields,
    reserve_registration,
)
from research_os.service import ResearchService
from tests.test_m1b_service_cli import (
    ROOT,
    _configure_agent_files,
    _passing_review,
)

FIXTURES = Path(__file__).parent / "fixtures" / "scientific_state" / "v1"


def _reservation_worker(
    project_path: str,
    payload: dict[str, Any],
    worker_index: int,
    barrier: Any,
    result_queue: Any,
    context_token: str | None = None,
    snapshot: dict[str, Any] | None = None,
) -> None:
    service = ResearchService(Path(project_path))
    try:
        events = service.event_log.read()
        preflight = reduce_scientific_state(
            events,
            project_id=service.config.project_id,
        )
        worker_payload = {**payload, "experiment_id": f"exp_competing_{worker_index}"}
        reserve_registration(preflight, worker_payload)
        report = service._doctor_snapshot(event_count=len(events))
        barrier.wait(timeout=15)
        event = service._append_registration_event(
            worker_payload,
            report=report,
            context_token=context_token,
            snapshot=snapshot,
        )
        result_queue.put(("committed", event.sequence))
    except ScientificStateError as exc:
        result_queue.put(("rejected", exc.code))
    except StaleAgentContextError as exc:
        result_queue.put(("rejected", exc.code))
    except BaseException as exc:  # pragma: no cover - surfaced in parent assertion
        result_queue.put(("unexpected", type(exc).__name__, str(exc)))


def _contract(**budget_overrides: Any) -> StudyContract:
    raw = json.loads(
        (FIXTURES / "m1b-contract.json").read_text(encoding="utf-8")
    )
    raw["budget"].update(budget_overrides)
    return StudyContract.from_mapping(raw)


def _manifest_case(case_id: str) -> dict[str, Any]:
    manifest = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
    return next(case for case in manifest["cases"] if case["id"] == case_id)


def _certified_project(tmp_path: Path) -> tuple[Path, ResearchService]:
    project = tmp_path / "project"
    shutil.copytree(ROOT / "examples" / "toy_optimization", project)
    runtime = project / ".research-os" / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    _configure_agent_files(project)
    service = ResearchService(project)
    subject = service.evaluator_review_subject()
    service.certify_evaluator(
        _passing_review(
            tmp_path / "review.json",
            subject_digest=str(subject["digest"]),
        )
    )
    return project, service


def _append_registration(
    service: ResearchService,
    payload: dict[str, Any],
) -> None:
    events = service.event_log.read()
    report = service._doctor_snapshot(event_count=len(events))
    service._append_registration_event(
        payload,
        report=report,
        context_token=None,
        snapshot=None,
    )


def _registration(
    state: Any,
    *,
    experiment_id: str,
    retry_of: str | None = None,
) -> dict[str, Any]:
    return {
        "experiment_id": experiment_id,
        "retry_of": retry_of,
        "authorized_action": None,
        **registration_payload_fields(state, retry_of=retry_of),
    }


@pytest.mark.parametrize(
    ("dimension", "budget", "with_prior", "retry", "expected_code"),
    [
        (
            "attempts",
            {
                "max_attempts": 1,
                "max_retries": 0,
                "max_elapsed_milliseconds": 1000,
                "max_cost_microunits": 2500,
            },
            False,
            False,
            "BUDGET_ATTEMPTS_EXCEEDED",
        ),
        (
            "retries",
            {
                "max_attempts": 3,
                "max_retries": 1,
                "max_elapsed_milliseconds": 3000,
                "max_cost_microunits": 7500,
            },
            True,
            True,
            "BUDGET_RETRIES_EXCEEDED",
        ),
        (
            "elapsed_milliseconds",
            {
                "max_attempts": 3,
                "max_retries": 0,
                "max_elapsed_milliseconds": 2000,
                "max_cost_microunits": 7500,
            },
            True,
            False,
            "BUDGET_ELAPSED_EXCEEDED",
        ),
        (
            "cost_microunits",
            {
                "max_attempts": 3,
                "max_retries": 0,
                "max_elapsed_milliseconds": 3000,
                "max_cost_microunits": 5000,
            },
            True,
            False,
            "BUDGET_COST_EXCEEDED",
        ),
    ],
)
def test_locked_append_rejects_every_concurrent_last_slot_overrun(
    tmp_path: Path,
    dimension: str,
    budget: dict[str, int],
    with_prior: bool,
    retry: bool,
    expected_code: str,
) -> None:
    race_case = _manifest_case("locked-append-races")
    assert race_case["input"]["registration_path"] == (
        "common_tokenless_registration_gate"
    )
    assert dimension in race_case["input"]["dimensions"]
    assert race_case["expected"]["rejection_codes"][dimension] == expected_code

    project, service = _certified_project(tmp_path)
    contract = _contract(**budget)
    service.open_generation(contract.to_dict())
    state = reduce_scientific_state(
        service.event_log.read(),
        project_id=service.config.project_id,
    )
    prior_id = "exp_prior"
    if with_prior:
        _append_registration(
            service,
            _registration(state, experiment_id=prior_id),
        )
        state = reduce_scientific_state(
            service.event_log.read(),
            project_id=service.config.project_id,
        )
    payload = _registration(
        state,
        experiment_id="exp_competing",
        retry_of=prior_id if retry else None,
    )
    before_registrations = sum(
        event.event_type == "EXPERIMENT_REGISTERED"
        for event in service.event_log.read()
    )

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(2)
    result_queue = context.Queue()
    workers = [
        context.Process(
            target=_reservation_worker,
            args=(
                str(project),
                payload,
                worker_index,
                barrier,
                result_queue,
            ),
        )
        for worker_index in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)
        if worker.is_alive():  # pragma: no cover - defensive cleanup
            worker.terminate()
            worker.join(timeout=5)
            pytest.fail("reservation race worker did not terminate")
        assert worker.exitcode == 0

    results: list[tuple[Any, ...]] = []
    for _ in workers:
        try:
            results.append(result_queue.get(timeout=5))
        except queue.Empty:  # pragma: no cover - defensive failure detail
            pytest.fail("reservation race worker produced no result")
    assert sum(result[0] == "committed" for result in results) == 1
    assert results.count(("rejected", expected_code)) == 1
    assert not [result for result in results if result[0] == "unexpected"]

    after = service.event_log.read()
    after_registrations = sum(
        event.event_type == "EXPERIMENT_REGISTERED" for event in after
    )
    assert after_registrations - before_registrations == 1
    final_state = reduce_scientific_state(
        after,
        project_id=service.config.project_id,
    )
    ledger = final_state.to_dict()["budget"]
    assert ledger is not None
    assert ledger[dimension]["remaining"] == 0


def test_shared_context_head_race_is_separate_from_budget_race_denominator(
    tmp_path: Path,
) -> None:
    race_case = _manifest_case("context-head-race-is-separate")
    assert race_case["input"] == {
        "workers": 2,
        "shared_context_token": True,
    }
    assert race_case["expected"]["counts_toward_budget_race_denominator"] is False

    project, service = _certified_project(tmp_path)
    service.open_generation(_contract().to_dict())
    service.baseline()
    context_packet = service.agent_context()
    snapshot = dict(context_packet["snapshot"])
    context_token = str(snapshot["context_token"])
    state = reduce_scientific_state(
        service.event_log.read(),
        project_id=service.config.project_id,
    )
    payload = {
        **_registration(state, experiment_id="exp_competing_context"),
        "agent_context_token": context_token,
        "agent_context_snapshot": snapshot,
    }
    before_registrations = sum(
        event.event_type == "EXPERIMENT_REGISTERED"
        for event in service.event_log.read()
    )

    spawn = multiprocessing.get_context("spawn")
    barrier = spawn.Barrier(2)
    result_queue = spawn.Queue()
    workers = [
        spawn.Process(
            target=_reservation_worker,
            args=(
                str(project),
                payload,
                worker_index,
                barrier,
                result_queue,
                context_token,
                snapshot,
            ),
        )
        for worker_index in range(2)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=20)
        if worker.is_alive():  # pragma: no cover - defensive cleanup
            worker.terminate()
            worker.join(timeout=5)
            pytest.fail("context race worker did not terminate")
        assert worker.exitcode == 0

    results: list[tuple[Any, ...]] = []
    for _ in workers:
        try:
            results.append(result_queue.get(timeout=5))
        except queue.Empty:  # pragma: no cover - defensive failure detail
            pytest.fail("context race worker produced no result")

    expected = race_case["expected"]
    assert sum(result[0] == "committed" for result in results) == expected[
        "winner_count"
    ]
    assert results.count(("rejected", expected["rejection_code"])) == expected[
        "rejection_count"
    ]
    assert not [result for result in results if result[0] == "unexpected"]
    after_registrations = sum(
        event.event_type == "EXPERIMENT_REGISTERED"
        for event in service.event_log.read()
    )
    assert after_registrations - before_registrations == 1
