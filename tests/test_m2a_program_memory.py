from __future__ import annotations

import copy
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event as ThreadEvent
from typing import Any, Callable

import pytest

from research_os.contracts.common import sha256_json
from research_os.errors import IntegrityError, ProgramMemoryError
from research_os.kernel._canonical import canonical_bytes
from research_os.kernel.events import Event, EventLog
from research_os.kernel.ids import stable_id
from research_os.memory.program import (
    PROGRAM_INITIALIZED_EVENT,
    PROGRAM_ORIGIN_LINKED_EVENT,
    OriginEvidenceRef,
    ProgramEvent,
    ProgramHeadMismatchError,
    ProgramManifest,
    ProgramStore,
    validate_program_manifest,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "program_memory" / "v1"
MANIFEST_PATH = FIXTURE_ROOT / "manifest.json"
M1D_ROOT = ROOT / "tests" / "fixtures" / "scientific_state" / "v3"

CASE_IDS = (
    "manifest-valid-exact",
    "manifest-contract-digest-forged",
    "manifest-duplicate-binding",
    "manifest-unknown-version",
    "manifest-non-null-authority",
    "origin-valid-exact",
    "origin-diagnosis-event-hash-forged",
    "origin-class-state-forged",
    "origin-scope-mismatch",
    "origin-stale-project-head",
    "program-canonical-two-events",
    "program-stale-head",
    "program-project-envelope-mixing",
    "program-committed-hash-corruption",
    "projection-missing-rebuild",
    "projection-corrupt-rebuild",
    "projection-stale-rebuild",
    "lock-order-project-vs-origin",
    "lock-order-program-head-race",
)


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


ORACLE = _json(MANIFEST_PATH)
CASES = {case["id"]: case for case in ORACLE["cases"]}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _supported_history() -> list[dict[str, Any]]:
    terminal = _json(M1D_ROOT / "m1d-terminal-corpus.json")
    valid = _json(M1D_ROOT / "m1d-diagnosis-valid.json")
    diagnosis_case = next(item for item in valid["cases"] if item["id"] == "supported")
    terminal_record = next(
        item
        for item in terminal["records"]
        if item["id"] == diagnosis_case["terminal_record_id"]
    )
    return copy.deepcopy(
        [*terminal_record["canonical_history"], diagnosis_case["diagnosis_event"]]
    )


def _project_log(root: Path) -> EventLog:
    history = _supported_history()
    path = root / "project-events.jsonl"
    path.write_bytes(
        b"".join(
            canonical_bytes(Event.from_mapping(item).to_dict()) + b"\n"
            for item in history
        )
    )
    path.chmod(0o600)
    return EventLog(path, ORACLE["fixtures"]["project_id"])


def _manifest_raw() -> dict[str, Any]:
    fixtures = ORACLE["fixtures"]
    return {
        "program_manifest_schema_version": 1,
        "program_id": fixtures["program_id"],
        "bindings": [copy.deepcopy(fixtures["binding"])],
        "authorized_action": None,
    }


def _origin_raw() -> dict[str, Any]:
    return copy.deepcopy(ORACLE["fixtures"]["origin"])


def _rebind_origin(raw: dict[str, Any]) -> None:
    raw["origin_id"] = stable_id(
        "origin",
        raw["project_id"],
        raw["project_head"],
        raw["generation_id"],
        raw["evaluation_scope_id"],
        raw["diagnosis_id"],
        raw["diagnosis_digest"],
        raw["class_state_id"],
        raw["class_state_digest"],
    )


def _initialize(root: Path) -> tuple[EventLog, ProgramStore, ProgramEvent]:
    project_log = _project_log(root)
    manifest = ProgramManifest.from_mapping(_manifest_raw())
    store = ProgramStore(root / "program", manifest.program_id)
    event = store.initialize(
        manifest,
        {project_log.project_id: project_log},
        event_id="evt_m2a_program_initialized",
        occurred_at="2026-08-11T00:00:00.000000Z",
    )
    return project_log, store, event


def _append_valid(
    project_log: EventLog,
    store: ProgramStore,
    initialized: ProgramEvent,
) -> ProgramEvent:
    return store.append_origin(
        OriginEvidenceRef.from_mapping(_origin_raw()),
        project_log,
        expected_program_head=(initialized.sequence, initialized.hash),
        event_id="evt_m2a_origin_linked",
        occurred_at="2026-08-11T00:00:01.000000Z",
    )


def _program_bytes(store: ProgramStore) -> bytes:
    return store.log.path.read_bytes() if store.log.path.exists() else b""


def _projection_bytes(store: ProgramStore) -> bytes | None:
    return store.projection.path.read_bytes() if store.projection.path.exists() else None


def _reject_manifest(root: Path, raw: dict[str, Any]) -> dict[str, Any]:
    project_log = _project_log(root)
    store = ProgramStore(root / "program", ORACLE["fixtures"]["program_id"])
    before_log = _program_bytes(store)
    before_projection = _projection_bytes(store)
    try:
        store.initialize(raw, {project_log.project_id: project_log})
    except ProgramMemoryError as exc:
        code = exc.code
    else:  # pragma: no cover - frozen rejection contract
        raise AssertionError("invalid manifest was accepted")
    return {
        "error_code": code,
        "program_event_delta": len(store.log.read()) if _program_bytes(store) != before_log else 0,
        "projection_delta": int(_projection_bytes(store) != before_projection),
    }


def _reject_origin(root: Path, raw: dict[str, Any]) -> dict[str, Any]:
    project_log, store, initialized = _initialize(root)
    before_count = len(store.log.read())
    before_projection = _projection_bytes(store)
    try:
        store.append_origin(
            raw,
            project_log,
            expected_program_head=(initialized.sequence, initialized.hash),
        )
    except ProgramMemoryError as exc:
        code = exc.code
    else:  # pragma: no cover - frozen rejection contract
        raise AssertionError("invalid origin was accepted")
    return {
        "error_code": code,
        "program_event_delta": len(store.log.read()) - before_count,
        "projection_delta": int(_projection_bytes(store) != before_projection),
    }


def _parse_and_validate_manifest(root: Path) -> dict[str, Any]:
    project_log = _project_log(root)
    manifest = ProgramManifest.from_mapping(_manifest_raw())
    validate_program_manifest(manifest, {project_log.project_id: project_log.read()})
    return {
        "manifest_digest": manifest.digest,
        "binding_count": len(manifest.bindings),
        "program_event_delta": 0,
        "projection_delta": 0,
    }


def _reject_contract_digest(root: Path) -> dict[str, Any]:
    raw = _manifest_raw()
    raw["bindings"][0]["study_contract_digest"] = "a" * 64
    return _reject_manifest(root, raw)


def _reject_duplicate_binding(root: Path) -> dict[str, Any]:
    raw = _manifest_raw()
    raw["bindings"].append(copy.deepcopy(raw["bindings"][0]))
    return _reject_manifest(root, raw)


def _reject_unknown_manifest_version(root: Path) -> dict[str, Any]:
    raw = _manifest_raw()
    raw["program_manifest_schema_version"] = 2
    return _reject_manifest(root, raw)


def _reject_manifest_authority(root: Path) -> dict[str, Any]:
    raw = _manifest_raw()
    raw["authorized_action"] = "deploy"
    return _reject_manifest(root, raw)


def _append_exact_origin(root: Path) -> dict[str, Any]:
    project_log, store, initialized = _initialize(root)
    event = _append_valid(project_log, store, initialized)
    snapshot, recovered = store.snapshot()
    assert recovered is False
    origin = snapshot.origins[0]
    return {
        "origin_id": origin.origin_id,
        "origin_digest": origin.digest,
        "program_head_sequence": event.sequence,
        "program_head_hash": event.hash,
        "origin_count": len(snapshot.origins),
        "authorized_action": snapshot.authorized_action,
    }


def _reject_diagnosis_hash(root: Path) -> dict[str, Any]:
    raw = _origin_raw()
    raw["diagnosis_event"]["event_hash"] = "a" * 64
    _rebind_origin(raw)
    return _reject_origin(root, raw)


def _reject_class_state(root: Path) -> dict[str, Any]:
    raw = _origin_raw()
    raw["class_state_digest"] = "a" * 64
    _rebind_origin(raw)
    return _reject_origin(root, raw)


def _reject_scope(root: Path) -> dict[str, Any]:
    raw = _origin_raw()
    raw["evaluation_scope_id"] = "diagnostic-1"
    _rebind_origin(raw)
    return _reject_origin(root, raw)


def _reject_stale_project_head(root: Path) -> dict[str, Any]:
    project_log, store, initialized = _initialize(root)
    project_log.append(
        "vendor.project_advanced.v1",
        {"authorized_action": None},
        event_id="evt_m2a_project_advanced",
        occurred_at="2026-08-11T00:00:02.000000Z",
    )
    before_count = len(store.log.read())
    before_projection = _projection_bytes(store)
    try:
        store.append_origin(
            _origin_raw(),
            project_log,
            expected_program_head=(initialized.sequence, initialized.hash),
        )
    except ProgramMemoryError as exc:
        code = exc.code
    else:  # pragma: no cover
        raise AssertionError("stale project head was accepted")
    return {
        "error_code": code,
        "program_event_delta": len(store.log.read()) - before_count,
        "projection_delta": int(_projection_bytes(store) != before_projection),
    }


def _verify_program_events(root: Path) -> dict[str, Any]:
    project_log, store, initialized = _initialize(root)
    linked = _append_valid(project_log, store, initialized)
    events = store.log.read()
    return {
        "event_count": len(events),
        "initialized_event_hash": events[0].hash,
        "linked_event_hash": linked.hash,
    }


def _reject_stale_program_head(root: Path) -> dict[str, Any]:
    project_log, store, initialized = _initialize(root)
    _append_valid(project_log, store, initialized)
    before_count = len(store.log.read())
    try:
        store.append_origin(
            _origin_raw(),
            project_log,
            expected_program_head=(initialized.sequence, initialized.hash),
            event_id="evt_m2a_stale_origin",
            occurred_at="2026-08-11T00:00:02.000000Z",
        )
    except ProgramHeadMismatchError as exc:
        code = exc.code
    else:  # pragma: no cover
        raise AssertionError("stale ProgramLog head was accepted")
    return {
        "error_code": code,
        "winner_count": 1,
        "loser_program_event_delta": len(store.log.read()) - before_count,
    }


def _reject_project_envelope(root: Path) -> dict[str, Any]:
    project_log = _project_log(root)
    store = ProgramStore(root / "program", ORACLE["fixtures"]["program_id"])
    store.log.path.write_bytes(project_log.path.read_bytes())
    store.log.path.chmod(0o600)
    with pytest.raises(IntegrityError):
        store.log.read()
    return {"error_type": "IntegrityError", "program_event_delta": 0}


def _reject_committed_corruption(root: Path) -> dict[str, Any]:
    project_log, store, initialized = _initialize(root)
    _append_valid(project_log, store, initialized)
    lines = store.log.path.read_bytes().splitlines()
    raw = json.loads(lines[-1])
    raw["hash"] = "a" * 64
    lines[-1] = canonical_bytes(raw)
    store.log.path.write_bytes(b"\n".join(lines) + b"\n")
    store.log.path.chmod(0o600)
    with pytest.raises(IntegrityError):
        store.snapshot()
    return {"error_type": "IntegrityError", "projection_used_as_fallback": False}


def _projection_observation(store: ProgramStore, recovered: bool) -> dict[str, Any]:
    snapshot, actual_recovered = store.snapshot()
    assert actual_recovered is recovered
    return {
        "recovered": actual_recovered,
        "program_head_sequence": snapshot.program_head_sequence,
        "origin_count": len(snapshot.origins),
        "authorized_action": snapshot.authorized_action,
    }


def _rebuild_missing_projection(root: Path) -> dict[str, Any]:
    project_log, store, initialized = _initialize(root)
    _append_valid(project_log, store, initialized)
    store.projection.path.unlink()
    return _projection_observation(store, True)


def _rebuild_corrupt_projection(root: Path) -> dict[str, Any]:
    project_log, store, initialized = _initialize(root)
    _append_valid(project_log, store, initialized)
    store.projection.path.write_bytes(b"{")
    store.projection.path.chmod(0o600)
    return _projection_observation(store, True)


def _rebuild_stale_projection(root: Path) -> dict[str, Any]:
    project_log, store, initialized = _initialize(root)
    _append_valid(project_log, store, initialized)
    snapshot = json.loads(store.projection.path.read_text(encoding="utf-8"))
    snapshot["program_head"]["sequence"] = 1
    snapshot["program_head"]["hash"] = initialized.hash
    snapshot["origins"] = []
    store.projection.path.write_bytes(canonical_bytes(snapshot))
    store.projection.path.chmod(0o600)
    return _projection_observation(store, True)


def _race_project_vs_origin(root: Path) -> dict[str, Any]:
    project_log, store, initialized = _initialize(root)
    locked = ThreadEvent()
    release = ThreadEvent()

    def project_guard(_events: tuple[Event, ...]) -> None:
        locked.set()
        assert release.wait(5)

    def append_project() -> Event:
        return project_log.append(
            "vendor.concurrent_advance.v1",
            {"authorized_action": None},
            event_id="evt_m2a_concurrent_project_advance",
            occurred_at="2026-08-11T00:00:02.000000Z",
            precondition=project_guard,
        )

    def append_origin() -> str | None:
        try:
            store.append_origin(
                _origin_raw(),
                project_log,
                expected_program_head=(initialized.sequence, initialized.hash),
                event_id="evt_m2a_concurrent_origin",
                occurred_at="2026-08-11T00:00:03.000000Z",
            )
        except ProgramMemoryError as exc:
            return exc.code
        return None

    with ThreadPoolExecutor(max_workers=2) as executor:
        project_future = executor.submit(append_project)
        assert locked.wait(5)
        origin_future = executor.submit(append_origin)
        time.sleep(0.05)
        assert not origin_future.done()
        release.set()
        project_event = project_future.result(timeout=5)
        origin_code = origin_future.result(timeout=5)
    snapshot, _ = store.snapshot()
    return {
        "deadlock": False,
        "project_append_count": int(project_event.sequence == 8),
        "origin_append_count": int(origin_code is None),
        "origin_error_code": origin_code,
        "program_origin_count": len(snapshot.origins),
    }


def _race_same_program_head(root: Path) -> dict[str, Any]:
    project_log, store, initialized = _initialize(root)

    def append(index: int) -> str:
        try:
            store.append_origin(
                _origin_raw(),
                project_log,
                expected_program_head=(initialized.sequence, initialized.hash),
                event_id=f"evt_m2a_program_race_{index}",
                occurred_at=f"2026-08-11T00:00:0{index}.000000Z",
            )
        except ProgramHeadMismatchError:
            return "PROGRAM_HEAD_MISMATCH"
        return "WIN"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(append, (1, 2), timeout=10))
    snapshot, _ = store.snapshot()
    return {
        "deadlock": False,
        "winner_count": results.count("WIN"),
        "loser_error_code": next(item for item in results if item != "WIN"),
        "program_origin_count": len(snapshot.origins),
    }


Operation = Callable[[Path], dict[str, Any]]
OPERATIONS: dict[str, Operation] = {
    "parse_and_validate_manifest": _parse_and_validate_manifest,
    "reject_manifest_contract_digest_forgery": _reject_contract_digest,
    "reject_manifest_duplicate_binding": _reject_duplicate_binding,
    "reject_manifest_unknown_version": _reject_unknown_manifest_version,
    "reject_manifest_non_null_authority": _reject_manifest_authority,
    "append_exact_origin": _append_exact_origin,
    "reject_origin_diagnosis_event_hash_forgery": _reject_diagnosis_hash,
    "reject_origin_class_state_forgery": _reject_class_state,
    "reject_origin_scope_mismatch": _reject_scope,
    "reject_origin_stale_project_head": _reject_stale_project_head,
    "verify_canonical_program_events": _verify_program_events,
    "reject_stale_program_head": _reject_stale_program_head,
    "reject_project_envelope_in_program_log": _reject_project_envelope,
    "reject_committed_program_log_corruption": _reject_committed_corruption,
    "rebuild_missing_projection": _rebuild_missing_projection,
    "rebuild_corrupt_projection": _rebuild_corrupt_projection,
    "rebuild_stale_projection": _rebuild_stale_projection,
    "race_project_append_against_origin_append": _race_project_vs_origin,
    "race_same_program_head": _race_same_program_head,
}


def test_m2a_frozen_sources_literal_ids_and_dispatch_are_exact() -> None:
    fixtures = ORACLE["fixtures"]
    assert _sha256(M1D_ROOT / "m1d-terminal-corpus.json") == fixtures[
        "terminal_corpus_raw_sha256"
    ]
    assert _sha256(M1D_ROOT / "m1d-diagnosis-valid.json") == fixtures[
        "diagnosis_valid_raw_sha256"
    ]
    assert _sha256(M1D_ROOT / "m1d-contract.json") == fixtures["contract_raw_sha256"]
    assert tuple(case["id"] for case in ORACLE["cases"]) == CASE_IDS
    assert len(CASES) == len(CASE_IDS) == 19
    assert set(OPERATIONS) == {case["operation"] for case in ORACLE["cases"]}
    assert len(set(OPERATIONS)) == 19
    assert ORACLE["comparison"] == "exact canonical JSON equality"


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_m2a_frozen_case(case_id: str, tmp_path: Path) -> None:
    case = CASES[case_id]
    actual = OPERATIONS[case["operation"]](tmp_path)
    assert canonical_bytes(actual) == canonical_bytes(case["expected"])


def test_program_event_envelope_is_distinct_from_project_event() -> None:
    fixtures = ORACLE["fixtures"]
    manifest = ProgramManifest.from_mapping(_manifest_raw())
    payload = {
        "program_manifest": manifest.to_dict(),
        "program_manifest_digest": manifest.digest,
        "authorized_action": None,
    }
    unsigned = {
        "event_id": "evt_m2a_program_initialized",
        "event_type": PROGRAM_INITIALIZED_EVENT,
        "occurred_at": "2026-08-11T00:00:00.000000Z",
        "payload": payload,
        "prev_hash": None,
        "program_id": fixtures["program_id"],
        "sequence": 1,
        "version": 1,
    }
    raw = {**unsigned, "hash": fixtures["initialized_event_hash"]}
    assert ProgramEvent.from_mapping(raw).to_dict() == raw
    project_envelope = dict(raw)
    project_envelope["project_id"] = project_envelope.pop("program_id")
    with pytest.raises(IntegrityError):
        ProgramEvent.from_mapping(project_envelope)
    assert sha256_json(_manifest_raw()) == fixtures["manifest_digest"]


def test_link_origin_builds_the_same_frozen_reference_under_one_project_lock(
    tmp_path: Path,
) -> None:
    project_log, store, initialized = _initialize(tmp_path)
    diagnosis_id = ORACLE["fixtures"]["origin"]["diagnosis_id"]
    origin, event = store.link_origin(
        project_log,
        diagnosis_id,
        expected_program_head=(initialized.sequence, initialized.hash),
        event_id="evt_m2a_origin_linked",
        occurred_at="2026-08-11T00:00:01.000000Z",
    )
    assert origin.to_dict() == ORACLE["fixtures"]["origin"]
    assert origin.digest == ORACLE["fixtures"]["origin_digest"]
    assert event.event_type == PROGRAM_ORIGIN_LINKED_EVENT
    assert event.hash == ORACLE["fixtures"]["linked_event_hash"]
    assert store.audit_origins({project_log.project_id: project_log}) == 1
