from __future__ import annotations

import copy
import hashlib
import json
import multiprocessing
import queue
import shutil
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest import mock

import pytest

from research_os.errors import ScientificStateError
from research_os.kernel.events import EventLog
from research_os.kernel.projection import ProjectionStore
from research_os.science import (
    EvaluationSeal,
    StudyContract,
    plan_generation_open,
    reduce_scientific_state,
    registration_payload_fields,
    reserve_registration,
)
from research_os.service import ResearchService
from tests.test_m1b_atomic_races import _reservation_worker
from tests.test_m1b_authority_surfaces import _authority_values, _cli_json
from tests.test_m1b_science_core import _negative_contract
from tests.test_m1b_service_cli import (
    CONTRACT_PATH,
    ROOT,
    _configure_agent_files,
    _passing_review,
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "scientific_state" / "v1"
MANIFEST_RAW_SHA256 = (
    "a1ba1a6eccd2a10ead5ef0d2006a0fa850e15c0f73fc8b928e981c74c4e2f659"
)
MANIFEST_SORTED_COMPACT_DIGEST = (
    "7ddf837bceedebd2d4dca243e48d2cd734e34db9472f67f1273fcfe30dd11e2e"
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sorted_compact_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return _sha256(encoded)


def _load_object(name: str) -> dict[str, object]:
    value = json.loads((FIXTURE_ROOT / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


_MANIFEST = _load_object("manifest.json")
_MANIFEST_CASES = tuple(_MANIFEST["cases"])
assert all(isinstance(case, dict) for case in _MANIFEST_CASES)
_CASE_BY_ID = {str(case["id"]): case for case in _MANIFEST_CASES}
_CASE_IDS = tuple(_CASE_BY_ID)


def _replace_pointer(document: dict[str, object], pointer: str, value: object) -> None:
    tokens = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    parent: object = document
    for token in tokens[:-1]:
        parent = parent[int(token)] if isinstance(parent, list) else parent[token]  # type: ignore[index]
    if isinstance(parent, list):
        parent[int(tokens[-1])] = value
    else:
        assert isinstance(parent, dict)
        parent[tokens[-1]] = value


def _contract_for(case: Mapping[str, object]) -> StudyContract:
    inputs = case["input"]
    assert isinstance(inputs, Mapping)
    fixture = inputs.get("fixture", "m1b-contract.json")
    assert isinstance(fixture, str)
    raw = _load_object(fixture)
    for operation in ("add", "replace"):
        changes = inputs.get(operation, {})
        assert isinstance(changes, Mapping)
        for pointer, value in changes.items():
            assert isinstance(pointer, str) and pointer.startswith("/")
            _replace_pointer(raw, pointer, value)
    transform = inputs.get("transform")
    if transform == "reverse_semantically_unordered_arrays":
        for field in ("hypothesis_classes", "evaluation_scopes"):
            values = raw[field]
            assert isinstance(values, list)
            values.reverse()
        surface = raw["intervention_surface"]
        assert isinstance(surface, dict)
        pointers = surface["allowed_json_pointers"]
        assert isinstance(pointers, list)
        pointers.reverse()
    elif transform is not None:
        raise AssertionError(f"unsupported manifest contract transform: {transform}")
    return StudyContract.from_mapping(raw)


def _evaluation_seal() -> EvaluationSeal:
    fixtures = _MANIFEST["fixtures"]
    assert isinstance(fixtures, Mapping)
    raw = fixtures["evaluation_seal"]
    assert isinstance(raw, Mapping)
    return EvaluationSeal.from_mapping(raw)


def _science_event(
    event_type: str,
    payload: Mapping[str, object],
    *,
    project_id: str = "fixture-m1b",
) -> dict[str, object]:
    return {
        "event_type": event_type,
        "project_id": project_id,
        "payload": dict(payload),
    }


def _opened_state(
    *,
    contract: StudyContract | None = None,
    project_id: str = "fixture-m1b",
) -> tuple[list[dict[str, object]], object]:
    selected = (
        StudyContract.from_mapping(_load_object("m1b-contract.json"))
        if contract is None
        else contract
    )
    plan = plan_generation_open(
        [],
        project_id=project_id,
        contract=selected,
        evaluation_seal=_evaluation_seal(),
    )
    events = [_science_event(plan.event_type, plan.payload, project_id=project_id)]
    return events, reduce_scientific_state(events, project_id=project_id)


def _registration(
    state: object,
    *,
    experiment_id: str,
    retry_of: str | None = None,
    candidate_digest: str = "a" * 64,
    attempt: int = 1,
) -> dict[str, object]:
    return {
        "experiment_id": experiment_id,
        "parent_id": None,
        "candidate_digest": candidate_digest,
        "compatibility_digest": _evaluation_seal().compatibility_digest,
        "attempt": attempt,
        "retry_of": retry_of,
        "status": "registered",
        "authorized_action": None,
        **registration_payload_fields(state, retry_of=retry_of),  # type: ignore[arg-type]
    }


def _error_code(operation: Callable[[], object]) -> str:
    with pytest.raises(ScientificStateError) as caught:
        operation()
    return caught.value.code


def _observe_contract_case(case: Mapping[str, object]) -> dict[str, object]:
    case_id = str(case["id"])
    if case_id == "contract-negative-matrix":
        inputs = case["input"]
        assert isinstance(inputs, Mapping)
        fixture = inputs["fixture"]
        assert isinstance(fixture, str)
        matrix = _load_object(fixture)
        cases = matrix["cases"]
        assert isinstance(cases, list)
        base = _load_object(str(matrix["base_fixture"]))
        codes = [
            _error_code(
                lambda negative=negative: StudyContract.from_mapping(
                    _negative_contract(base, negative)
                )
            )
            for negative in cases
        ]
        return {
            "cases": len(cases),
            "rejections": len(codes),
            "error_code": codes[0] if len(set(codes)) == 1 else "MIXED",
        }
    try:
        contract = _contract_for(case)
    except ScientificStateError as exc:
        return {"error_code": exc.code}
    if case_id == "contract-exact-round-trip":
        return {
            "contract_digest": contract.digest,
            "hypothesis_class_ids": [item.id for item in contract.hypothesis_classes],
            "evaluation_scope_ids": [item.id for item in contract.evaluation_scopes],
        }
    if case_id == "contract-order-invariance":
        return {"contract_digest": contract.digest}
    if case_id == "contract-null-cost":
        return {
            "cost_ledger": (
                None
                if contract.budget.max_cost_microunits is None
                else contract.budget.to_dict()
            )
        }
    raise AssertionError(f"unbound contract manifest case: {case_id}")


def _observe_generation_case(case: Mapping[str, object]) -> dict[str, object]:
    case_id = str(case["id"])
    contract = _contract_for(case)
    seal = _evaluation_seal()
    first_contract = StudyContract.from_mapping(_load_object("m1b-contract.json"))
    first = plan_generation_open(
        [],
        project_id="fixture-m1b",
        contract=first_contract,
        evaluation_seal=seal,
    )
    if case_id == "generation-first-open":
        return {
            "generation_id": first.generation_id,
            "event_type": first.event_type,
            "appended_events": int(first.append_required),
            "authorized_action": first.payload["authorized_action"],
        }
    events = [_science_event(first.event_type, first.payload)]
    if case_id == "generation-identical-reopen":
        second = plan_generation_open(
            events,
            project_id="fixture-m1b",
            contract=contract,
            evaluation_seal=seal,
        )
        return {
            "generation_id": second.generation_id,
            "total_generation_events": 1 + int(second.append_required),
            "second_append_delta": int(second.append_required),
        }
    inputs = case["input"]
    assert isinstance(inputs, Mapping)
    try:
        successor = plan_generation_open(
            events,
            project_id="fixture-m1b",
            contract=contract,
            evaluation_seal=seal,
            predecessor_generation_id=inputs.get("predecessor_generation_id"),  # type: ignore[arg-type]
            change_reason=inputs.get("change_reason"),  # type: ignore[arg-type]
        )
    except ScientificStateError as exc:
        return {"error_code": exc.code, "appended_events": 0}
    successor_events = [
        *events,
        _science_event(successor.event_type, successor.payload),
    ]
    state = reduce_scientific_state(successor_events, project_id="fixture-m1b")
    return {
        "contract_digest": successor.contract.digest,
        "generation_id": successor.generation_id,
        "active_generation_id": state.active_generation_id,
        "appended_events": int(successor.append_required),
    }


def _observe_legacy_projection(tmp_path: Path) -> dict[str, object]:
    source = FIXTURE_ROOT / "legacy-v1-events.jsonl"
    raw = source.read_bytes()
    destination = tmp_path / "legacy-events.jsonl"
    destination.write_bytes(raw)
    log = EventLog(destination, "fixture-legacy-v1")
    events = log.read()
    projection = ProjectionStore(tmp_path / "legacy-state.db")
    projection.rebuild(log)
    experiment_id = str(_MANIFEST["fixtures"]["legacy_v1_experiment_id"])  # type: ignore[index]
    observed_projection = {
        "experiment": projection.experiment("fixture-legacy-v1", experiment_id),
        "status": projection.project_status("fixture-legacy-v1"),
    }
    science = reduce_scientific_state(events, project_id="fixture-legacy-v1")
    return {
        "event_bytes_sha256": _sha256(raw),
        "last_event_hash": events[-1].hash,
        "experiment_id": experiment_id,
        "projection_canonical_digest": _sorted_compact_digest(observed_projection),
        "legacy_unstructured_registrations": (
            science.legacy_unstructured_registrations
        ),
    }


def _observe_replay_binding_case(case: Mapping[str, object]) -> dict[str, object]:
    case_id = str(case["id"])
    legacy = _science_event(
        "EXPERIMENT_REGISTERED",
        {"experiment_id": "exp_legacy", "authorized_action": None},
    )
    if case_id == "legacy-registration-before-generation":
        state = reduce_scientific_state([legacy], project_id="fixture-m1b")
        return {
            "active_generation_id": state.active_generation_id,
            "legacy_unstructured_registrations": (
                state.legacy_unstructured_registrations
            ),
        }
    events, _ = _opened_state()
    if case_id == "unbound-registration-after-generation":
        return {
            "error_code": _error_code(
                lambda: reduce_scientific_state(
                    [*events, legacy], project_id="fixture-m1b"
                )
            )
        }
    if case_id == "registration-partial-science-metadata":
        partial = copy.deepcopy(legacy)
        partial_payload = partial["payload"]
        assert isinstance(partial_payload, dict)
        partial_payload["generation_id"] = _MANIFEST["fixtures"][  # type: ignore[index]
            "first_generation_id"
        ]
        return {
            "error_code": _error_code(
                lambda: reduce_scientific_state(
                    [*events, partial], project_id="fixture-m1b"
                )
            )
        }
    raise AssertionError(f"unbound replay manifest case: {case_id}")


def _observe_seal_mismatch() -> dict[str, object]:
    _, state = _opened_state()
    payload = _registration(state, experiment_id="exp_bad_seal")
    payload["evaluation_seal_digest"] = "9" * 64
    return {
        "error_code": _error_code(lambda: reserve_registration(state, payload)),  # type: ignore[arg-type]
        "appended_events": 0,
    }


def _observe_live_replay_rebuild(tmp_path: Path) -> dict[str, object]:
    project_id = "fixture-m1b"
    log = EventLog(tmp_path / "parity-events.jsonl", project_id)
    log.append(
        "PROJECT_INITIALIZED",
        {"project_id": project_id, "status": "active"},
    )
    contract = StudyContract.from_mapping(_load_object("m1b-contract.json"))
    plan = plan_generation_open(
        log.read(),
        project_id=project_id,
        contract=contract,
        evaluation_seal=_evaluation_seal(),
    )
    log.append(plan.event_type, plan.payload)
    initial = reduce_scientific_state(log.read(), project_id=project_id)
    ordinary = _registration(initial, experiment_id="exp_parity_ordinary", attempt=1)
    log.append("EXPERIMENT_REGISTERED", ordinary)
    log.append(
        "EXPERIMENT_TERMINATED",
        {
            "experiment_id": "exp_parity_ordinary",
            "status": "TIMED_OUT",
            "attempt": 1,
            "retry_of": None,
            "retryable": True,
        },
    )
    after_ordinary = reduce_scientific_state(log.read(), project_id=project_id)
    retry = _registration(
        after_ordinary,
        experiment_id="exp_parity_retry",
        retry_of="exp_parity_ordinary",
        attempt=2,
    )
    log.append("EXPERIMENT_REGISTERED", retry)
    post_append = reduce_scientific_state(log.read(), project_id=project_id)
    post_append_dict = post_append.to_dict()
    cold = reduce_scientific_state(log.read(), project_id=project_id).to_dict()
    projection = ProjectionStore(tmp_path / "parity-state.db")
    projection.rebuild(log)
    after_rebuild = reduce_scientific_state(log.read(), project_id=project_id).to_dict()
    states = (post_append_dict, cold, after_rebuild)
    forbidden = _registration(
        post_append,
        experiment_id="exp_parity_forbidden",
        retry_of="exp_parity_retry",
        attempt=3,
    )
    return {
        "path_state_match_count": sum(state == post_append_dict for state in states),
        "active_generation_id": post_append.active_generation_id,
        "study_contract_digest": post_append.study_contract_digest,
        "evaluation_seal_digest": post_append.evaluation_seal_digest,
        "attempts_used": post_append.attempts_used,
        "retries_used": post_append.retries_used,
        "elapsed_reserved_milliseconds": post_append.elapsed_reserved_milliseconds,
        "cost_reserved_microunits": post_append.cost_reserved_microunits,
        "forbidden_error_code": _error_code(
            lambda: reserve_registration(post_append, forbidden)
        ),
    }


def _observe_malformed_matrix() -> dict[str, object]:
    case_names = (
        "unbound_after_generation",
        "partial_science_bundle",
        "contract_digest_mismatch",
        "evaluation_seal_mismatch",
        "generation_mismatch",
        "budget_debit_tamper",
        "attempts_overrun",
    )
    codes: list[str] = []
    for case_name in case_names:
        events, state = _opened_state()
        payload = _registration(state, experiment_id=f"exp_{case_name}")
        if case_name == "unbound_after_generation":
            for key in tuple(registration_payload_fields(state, retry_of=None)):  # type: ignore[arg-type]
                payload.pop(key)
        elif case_name == "partial_science_bundle":
            for key in tuple(registration_payload_fields(state, retry_of=None)):  # type: ignore[arg-type]
                if key != "generation_id":
                    payload.pop(key)
        elif case_name == "contract_digest_mismatch":
            payload["study_contract_digest"] = "9" * 64
        elif case_name == "evaluation_seal_mismatch":
            payload["evaluation_seal_digest"] = "9" * 64
        elif case_name == "generation_mismatch":
            payload["generation_id"] = (
                "generation_00000000000000000000000000000000"
            )
        elif case_name == "budget_debit_tamper":
            debit = payload["budget_debit"]
            assert isinstance(debit, dict)
            debit["attempts"] = 0
        elif case_name == "attempts_overrun":
            for index in range(4):
                prior = _registration(state, experiment_id=f"exp_prior_{index}")
                events.append(_science_event("EXPERIMENT_REGISTERED", prior))
                state = reserve_registration(state, prior)  # type: ignore[arg-type]
            payload = _registration(state, experiment_id="exp_attempts_overrun")
        codes.append(
            _error_code(
                lambda events=events, payload=payload: reduce_scientific_state(
                    [*events, _science_event("EXPERIMENT_REGISTERED", payload)],
                    project_id="fixture-m1b",
                )
            )
        )
    return {"rejections": len(codes), "error_codes": codes}


def _observe_terminal_ledger(case: Mapping[str, object]) -> dict[str, object]:
    inputs = case["input"]
    assert isinstance(inputs, Mapping)
    registrations = inputs["registrations"]
    assert isinstance(registrations, list)
    events, state = _opened_state()
    for index, registration_spec in enumerate(registrations):
        assert isinstance(registration_spec, Mapping)
        retry = registration_spec["retry"] is True
        retry_of = "exp_terminal_0" if retry else None
        payload = _registration(
            state,
            experiment_id=f"exp_terminal_{index}",
            retry_of=retry_of,
            attempt=2 if retry else 1,
        )
        events.append(_science_event("EXPERIMENT_REGISTERED", payload))
        events.append(
            _science_event(
                "EXPERIMENT_TERMINATED",
                {
                    "experiment_id": f"exp_terminal_{index}",
                    "status": registration_spec["terminal_status"],
                },
            )
        )
        state = reserve_registration(state, payload)  # type: ignore[arg-type]
    budget = reduce_scientific_state(events, project_id="fixture-m1b").to_dict()[
        "budget"
    ]
    assert isinstance(budget, dict)
    return budget


def _observe_budget_overrun(case: Mapping[str, object]) -> dict[str, object]:
    case_id = str(case["id"])
    inputs = case["input"]
    assert isinstance(inputs, Mapping)
    raw = _load_object("m1b-contract.json")
    override = inputs.get("contract_override", {})
    assert isinstance(override, Mapping)
    budget = raw["budget"]
    assert isinstance(budget, dict)
    budget.update(override)
    contract = StudyContract.from_mapping(raw)
    _, state = _opened_state(contract=contract)
    prior_attempts = int(inputs.get("prior_attempts", 0))
    prior_retries = int(inputs.get("prior_retries", 0))
    for index in range(prior_attempts):
        is_retry = index >= prior_attempts - prior_retries
        payload = _registration(
            state,
            experiment_id=f"exp_budget_prior_{index}",
            retry_of="exp_budget_prior_0" if is_retry else None,
            attempt=2 if is_retry else 1,
        )
        state = reserve_registration(state, payload)  # type: ignore[arg-type]
    proposed_retry = inputs.get("retry") is True
    proposed = _registration(
        state,
        experiment_id=f"exp_{case_id}",
        retry_of="exp_budget_prior_last" if proposed_retry else None,
        attempt=2 if proposed_retry else 1,
    )
    return {
        "error_code": _error_code(lambda: reserve_registration(state, proposed)),  # type: ignore[arg-type]
        "appended_events": 0,
    }


def _certified_project(
    root: Path,
    *,
    project_id: str | None = None,
) -> tuple[Path, ResearchService]:
    project = root / "project"
    shutil.copytree(ROOT / "examples" / "toy_optimization", project)
    runtime = project / ".research-os" / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    if project_id is not None:
        config_path = project / ".research-os" / "project.toml"
        config_path.write_text(
            config_path.read_text(encoding="utf-8").replace(
                'id = "toy-optimization"',
                f'id = "{project_id}"',
                1,
            ),
            encoding="utf-8",
        )
    _configure_agent_files(project)
    service = ResearchService(project)
    subject = service.evaluator_review_subject()
    service.certify_evaluator(
        _passing_review(
            root / "review.json",
            subject_digest=str(subject["digest"]),
        )
    )
    return project, service


def _generation_events(service: ResearchService) -> list[object]:
    return [
        event
        for event in service.event_log.read()
        if event.event_type == "research.study_generation_opened.v1"
    ]


def _observe_generation_race(case: Mapping[str, object], tmp_path: Path) -> dict[str, object]:
    case_id = str(case["id"])
    project, service = _certified_project(tmp_path, project_id="fixture-m1b")
    original_append = EventLog.append
    barrier = Barrier(2)

    def append_after_barrier(event_log: EventLog, event_type: str, *args: object, **kwargs: object):
        if event_type == "research.study_generation_opened.v1":
            barrier.wait(timeout=15)
        return original_append(event_log, event_type, *args, **kwargs)

    if case_id == "generation-first-open-race":
        def open_one(_: int) -> dict[str, object]:
            return ResearchService(project).open_generation(CONTRACT_PATH)

        with mock.patch.object(
            ResearchService,
            "_evaluation_seal_from_report",
            new=lambda _service, _report: _evaluation_seal(),
        ), mock.patch.object(EventLog, "append", new=append_after_barrier):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(open_one, range(2)))
        events = _generation_events(service)
        return {
            "successful_results": len(results),
            "generation_ids": sorted(str(result["generation_id"]) for result in results),
            "generation_event_delta": len(events),
            "active_generation_id": service.study_status()["active_generation_id"],
        }

    with mock.patch.object(
        ResearchService,
        "_evaluation_seal_from_report",
        new=lambda _service, _report: _evaluation_seal(),
    ):
        first = service.open_generation(CONTRACT_PATH)

    def open_successor(max_attempts: int) -> tuple[str, object]:
        contract = _load_object("m1b-contract.json")
        budget = contract["budget"]
        assert isinstance(budget, dict)
        budget["max_attempts"] = max_attempts
        try:
            result = ResearchService(project).open_generation(
                contract,
                predecessor_generation_id=str(first["generation_id"]),
                change_reason=f"set successor attempt budget to {max_attempts}",
            )
            return "ok", result
        except ScientificStateError as exc:
            return "error", exc

    with mock.patch.object(
        ResearchService,
        "_evaluation_seal_from_report",
        new=lambda _service, _report: _evaluation_seal(),
    ), mock.patch.object(EventLog, "append", new=append_after_barrier):
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(open_successor, (5, 6)))
    successes = [value for kind, value in outcomes if kind == "ok"]
    failures = [value for kind, value in outcomes if kind == "error"]
    assert len(successes) == 1 and isinstance(successes[0], Mapping)
    assert len(failures) == 1 and isinstance(failures[0], ScientificStateError)
    base_contract = StudyContract.from_mapping(_load_object("m1b-contract.json"))
    fixture_first = plan_generation_open(
        [],
        project_id="fixture-m1b",
        contract=base_contract,
        evaluation_seal=_evaluation_seal(),
    )
    fixture_events = [_science_event(fixture_first.event_type, fixture_first.payload)]
    allowed_ids: list[str] = []
    for limit in (5, 6):
        raw = _load_object("m1b-contract.json")
        raw_budget = raw["budget"]
        assert isinstance(raw_budget, dict)
        raw_budget["max_attempts"] = limit
        allowed_ids.append(
            plan_generation_open(
                fixture_events,
                project_id="fixture-m1b",
                contract=StudyContract.from_mapping(raw),
                evaluation_seal=_evaluation_seal(),
                predecessor_generation_id=fixture_first.generation_id,
                change_reason="derive allowed successor ID",
            ).generation_id
        )
    active = service.study_status()["active_generation_id"]
    assert active == successes[0]["generation_id"]
    assert active in allowed_ids
    return {
        "winner_count": len(successes),
        "rejection_count": len(failures),
        "rejection_code": failures[0].code,
        "generation_event_delta": len(_generation_events(service)) - 1,
        "allowed_active_generation_ids": allowed_ids,
    }


def _collect_process_results(workers: list[object], result_queue: object) -> list[tuple[object, ...]]:
    for worker in workers:
        worker.start()  # type: ignore[attr-defined]
    for worker in workers:
        worker.join(timeout=25)  # type: ignore[attr-defined]
        if worker.is_alive():  # type: ignore[attr-defined]
            worker.terminate()  # type: ignore[attr-defined]
            worker.join(timeout=5)  # type: ignore[attr-defined]
            pytest.fail("manifest race worker did not terminate")
        assert worker.exitcode == 0  # type: ignore[attr-defined]
    results: list[tuple[object, ...]] = []
    for _ in workers:
        try:
            results.append(result_queue.get(timeout=5))  # type: ignore[attr-defined]
        except queue.Empty:
            pytest.fail("manifest race worker produced no result")
    return results


def _append_service_registration(service: ResearchService, payload: dict[str, object]) -> None:
    events = service.event_log.read()
    service._append_registration_event(
        payload,
        report=service._doctor_snapshot(event_count=len(events)),
        context_token=None,
        snapshot=None,
    )


def _observe_locked_races(tmp_path: Path) -> dict[str, object]:
    configurations = {
        "attempts": ({"max_attempts": 1, "max_retries": 0, "max_elapsed_milliseconds": 1000, "max_cost_microunits": 2500}, False, False),
        "retries": ({"max_attempts": 3, "max_retries": 1, "max_elapsed_milliseconds": 3000, "max_cost_microunits": 7500}, True, True),
        "elapsed_milliseconds": ({"max_attempts": 3, "max_retries": 0, "max_elapsed_milliseconds": 2000, "max_cost_microunits": 7500}, True, False),
        "cost_microunits": ({"max_attempts": 3, "max_retries": 0, "max_elapsed_milliseconds": 3000, "max_cost_microunits": 5000}, True, False),
    }
    rejection_codes: dict[str, object] = {}
    winner_counts: list[int] = []
    rejection_counts: list[int] = []
    deltas: list[int] = []
    for dimension, (overrides, with_prior, retry) in configurations.items():
        project, service = _certified_project(tmp_path / dimension)
        raw = _load_object("m1b-contract.json")
        budget = raw["budget"]
        assert isinstance(budget, dict)
        budget.update(overrides)
        service.open_generation(raw)
        state = reduce_scientific_state(
            service.event_log.read(), project_id=service.config.project_id
        )
        if with_prior:
            _append_service_registration(
                service, _registration(state, experiment_id="exp_prior")
            )
            state = reduce_scientific_state(
                service.event_log.read(), project_id=service.config.project_id
            )
        payload = _registration(
            state,
            experiment_id="exp_competing",
            retry_of="exp_prior" if retry else None,
        )
        before = sum(
            event.event_type == "EXPERIMENT_REGISTERED"
            for event in service.event_log.read()
        )
        spawn = multiprocessing.get_context("spawn")
        barrier = spawn.Barrier(2)
        result_queue = spawn.Queue()
        workers = [
            spawn.Process(
                target=_reservation_worker,
                args=(str(project), payload, index, barrier, result_queue),
            )
            for index in range(2)
        ]
        results = _collect_process_results(workers, result_queue)
        winners = sum(result[0] == "committed" for result in results)
        rejected = [result for result in results if result[0] == "rejected"]
        assert len(rejected) == 1
        winner_counts.append(winners)
        rejection_counts.append(len(rejected))
        rejection_codes[dimension] = rejected[0][1]
        after = sum(
            event.event_type == "EXPERIMENT_REGISTERED"
            for event in service.event_log.read()
        )
        deltas.append(after - before)
    total = len(configurations)
    return {
        "winners_per_dimension": winner_counts[0] if len(set(winner_counts)) == 1 else -1,
        "rejections_per_dimension": rejection_counts[0] if len(set(rejection_counts)) == 1 else -1,
        "registration_delta_per_dimension": deltas[0] if len(set(deltas)) == 1 else -1,
        "overrun_block_rate": sum(rejection_counts) / total,
        "rejection_codes": rejection_codes,
    }


def _observe_context_race(tmp_path: Path) -> dict[str, object]:
    project, service = _certified_project(tmp_path)
    service.open_generation(CONTRACT_PATH)
    service.baseline()
    packet = service.agent_context()
    snapshot = dict(packet["snapshot"])
    context_token = str(snapshot["context_token"])
    state = reduce_scientific_state(
        service.event_log.read(), project_id=service.config.project_id
    )
    payload = {
        **_registration(state, experiment_id="exp_context_competing"),
        "agent_context_token": context_token,
        "agent_context_snapshot": snapshot,
    }
    spawn = multiprocessing.get_context("spawn")
    barrier = spawn.Barrier(2)
    result_queue = spawn.Queue()
    workers = [
        spawn.Process(
            target=_reservation_worker,
            args=(
                str(project),
                payload,
                index,
                barrier,
                result_queue,
                context_token,
                snapshot,
            ),
        )
        for index in range(2)
    ]
    results = _collect_process_results(workers, result_queue)
    rejected = [result for result in results if result[0] == "rejected"]
    return {
        "winner_count": sum(result[0] == "committed" for result in results),
        "rejection_count": len(rejected),
        "rejection_code": rejected[0][1] if len(rejected) == 1 else "MIXED",
        "counts_toward_budget_race_denominator": False,
    }


def _observe_authority_surfaces(tmp_path: Path, case: Mapping[str, object]) -> dict[str, object]:
    project, service = _certified_project(tmp_path)
    opened = service.open_generation(CONTRACT_PATH)
    opened_cli = _cli_json(project, "open-generation", str(CONTRACT_PATH))
    first_outcome = service.run_once(project / "candidates" / "improve.json")
    generation_event = next(
        event
        for event in service.event_log.read()
        if event.event_type == "research.study_generation_opened.v1"
    )
    registration_event = next(
        event
        for event in service.event_log.read()
        if event.event_type == "EXPERIMENT_REGISTERED"
    )
    second_candidate = tmp_path / "second-candidate.json"
    second_candidate.write_text('{"x":3.0}\n', encoding="utf-8")
    second_outcome_cli = _cli_json(
        project, "run-once", str(second_candidate)
    )
    surfaces = {
        "generation_event_payload": generation_event.payload,
        "open_generation_service_result": opened,
        "open_generation_cli_json": opened_cli,
        "experiment_registration_payload": registration_event.payload,
        "run_once_service_result": first_outcome,
        "run_once_cli_json": second_outcome_cli,
        "study_status_cli_json": _cli_json(project, "study-status"),
        "replay_cli_json": _cli_json(project, "replay"),
    }
    inputs = case["input"]
    assert isinstance(inputs, Mapping)
    assert list(surfaces) == inputs["surfaces"]
    for outcome in (first_outcome, second_outcome_cli):
        decision = outcome.get("decision")
        assert isinstance(decision, Mapping)
        assert "authorized_action" in decision
        assert decision["authorized_action"] is None
    recursive_values = [
        authority
        for surface in surfaces.values()
        for authority in _authority_values(surface)
    ]
    return {
        "surface_count": len(surfaces),
        "authorized_action_key_count": sum(
            "authorized_action" in surface for surface in surfaces.values()
        ),
        "authorized_action_non_null_count": sum(
            authority is not None for authority in recursive_values
        ),
    }


def _observe_manifest_case(case: Mapping[str, object], tmp_path: Path) -> dict[str, object]:
    case_id = str(case["id"])
    operation = str(case["operation"])
    if operation in {"parse_contract", "parse_contract_negative_matrix"}:
        return _observe_contract_case(case)
    if operation in {"open_generation", "open_generation_twice"}:
        return _observe_generation_case(case)
    if operation == "race_generation_open":
        return _observe_generation_race(case, tmp_path)
    if operation == "replay_legacy_corpus":
        return _observe_legacy_projection(tmp_path)
    if case_id in {
        "legacy-registration-before-generation",
        "unbound-registration-after-generation",
        "registration-partial-science-metadata",
    }:
        return _observe_replay_binding_case(case)
    if case_id == "registration-evaluation-seal-mismatch":
        return _observe_seal_mismatch()
    if operation == "compare_science_state_paths":
        return _observe_live_replay_rebuild(tmp_path)
    if operation == "replay_malformed_direct_appends":
        return _observe_malformed_matrix()
    if operation == "reduce_budget":
        return _observe_terminal_ledger(case)
    if case_id.startswith("budget-"):
        return _observe_budget_overrun(case)
    if operation == "race_reservations":
        return _observe_locked_races(tmp_path)
    if operation == "race_context_registration":
        return _observe_context_race(tmp_path)
    if operation == "scan_authority_surfaces":
        return _observe_authority_surfaces(tmp_path, case)
    raise AssertionError(f"unbound manifest case: {case_id} ({operation})")


@pytest.mark.parametrize("manifest_case_id", _CASE_IDS, ids=_CASE_IDS)
def test_every_manifest_case_has_an_executable_expectation_binding(
    manifest_case_id: str,
    tmp_path: Path,
) -> None:
    case = _CASE_BY_ID[manifest_case_id]
    expected = case["expected"]
    assert isinstance(expected, dict)
    observed = _observe_manifest_case(case, tmp_path)
    assert observed == expected


def test_all_manifest_binding_nodes_are_collected(request: pytest.FixtureRequest) -> None:
    expected_suffixes = {
        "test_every_manifest_case_has_an_executable_expectation_binding"
        f"[{case_id}]"
        for case_id in _CASE_IDS
    }
    collected_suffixes = {
        item.nodeid.rsplit("::", 1)[-1]
        for item in request.session.items
        if "test_every_manifest_case_has_an_executable_expectation_binding[" in item.nodeid
    }
    assert collected_suffixes == expected_suffixes
    assert set(_CASE_BY_ID) == set(_CASE_IDS)


def test_m1b_manifest_and_linked_fixture_digests_are_pre_spec_fixed() -> None:
    manifest_path = FIXTURE_ROOT / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)

    assert _sha256(manifest_bytes) == MANIFEST_RAW_SHA256
    assert _sorted_compact_digest(manifest) == MANIFEST_SORTED_COMPACT_DIGEST
    assert len(manifest["cases"]) == 29
    assert len({case["id"] for case in manifest["cases"]}) == 29

    fixtures = manifest["fixtures"]
    for path_key, digest_key in (
        ("contract_negative_matrix", "contract_negative_matrix_raw_sha256"),
        ("legacy_v1_events", "legacy_v1_events_raw_sha256"),
        ("legacy_v1_projection", "legacy_v1_projection_raw_sha256"),
    ):
        assert _sha256((FIXTURE_ROOT / fixtures[path_key]).read_bytes()) == fixtures[
            digest_key
        ]


def test_contract_negative_matrix_has_the_fixed_24_row_denominator() -> None:
    matrix = json.loads(
        (FIXTURE_ROOT / "m1b-contract-negative-matrix.json").read_text(
            encoding="utf-8"
        )
    )
    case_ids = [case["id"] for case in matrix["cases"]]

    assert len(case_ids) == 24
    assert len(set(case_ids)) == 24
    assert matrix["expected_error_code"] == "STUDY_CONTRACT_INVALID"
    assert {
        "missing-top-level",
        "unknown-nested",
        "null-required",
        "duplicate-hypothesis-id",
        "duplicate-scope-id",
        "duplicate-pointer",
        "bool-number",
        "nonfinite-number",
        "unsafe-integer",
        "bad-candidate-schema-digest",
        "bad-scope-manifest-digest",
        "bad-rfc6901-pointer",
        "invalid-scope-role",
        "missing-development-role",
        "retries-equal-attempts",
        "partial-cost-triple",
        "stop-policy-not-literal",
        "change-control-false",
    }.issubset(case_ids)


def test_fixed_v1_event_bytes_id_and_projection_remain_exact(tmp_path: Path) -> None:
    source = FIXTURE_ROOT / "legacy-v1-events.jsonl"
    expected = json.loads(
        (FIXTURE_ROOT / "legacy-v1-projection.json").read_text(encoding="utf-8")
    )
    destination = tmp_path / "events.jsonl"
    original_bytes = source.read_bytes()
    destination.write_bytes(original_bytes)

    log = EventLog(destination, "fixture-legacy-v1")
    events = log.read()
    assert _sha256(destination.read_bytes()) == (
        "b35e9d74a64c729ceea3c5ca66303a7f4e14043129d4e4686741c5939cf178d6"
    )
    assert events[-1].hash == (
        "3b3fcaa193ac3af814a67c605c253d86b5d993b4e277ceed78b7b97ed367d901"
    )

    projection = ProjectionStore(tmp_path / "state.db")
    assert projection.rebuild(log) == 2
    experiment_id = "exp_9c077608f342414ce35c5dec5d7aa07b"
    observed = {
        "experiment": projection.experiment("fixture-legacy-v1", experiment_id),
        "status": projection.project_status("fixture-legacy-v1"),
    }

    assert observed == expected
    assert _sorted_compact_digest(observed) == (
        "9acf4e08a01756d39e4789a7e13f635d891cb426c183abcbfc4793c53d472e88"
    )
    assert destination.read_bytes() == original_bytes
