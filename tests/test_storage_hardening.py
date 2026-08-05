from __future__ import annotations

import os
import sqlite3
import stat
import tempfile
import threading
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import research_os.kernel.events as events_module
import research_os.kernel.projection as projection_module
from research_os.errors import IntegrityError
from research_os.kernel._canonical import canonical_bytes, sha256_hex
from research_os.kernel.events import EVENT_VERSION, Event, EventLog
from research_os.kernel.projection import ProjectionStore


def chained_event(
    previous: Event | None,
    event_type: str,
    payload: dict[str, object],
    *,
    event_id: str,
) -> Event:
    unsigned = {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2026-08-04T00:00:00Z",
        "payload": payload,
        "prev_hash": previous.hash if previous is not None else None,
        "project_id": "storage-test",
        "sequence": previous.sequence + 1 if previous is not None else 1,
        "version": EVENT_VERSION,
    }
    return Event.from_mapping(
        {**unsigned, "hash": sha256_hex(canonical_bytes(unsigned))}
    )


class StorageHardeningTests(unittest.TestCase):
    def paths(self) -> tuple[tempfile.TemporaryDirectory[str], Path, Path]:
        temporary = tempfile.TemporaryDirectory()
        root = Path(temporary.name)
        return temporary, root / "events.jsonl", root / "state.db"

    def test_projection_rejects_reused_event_id_at_later_sequence(self):
        temporary, _, database_path = self.paths()
        self.addCleanup(temporary.cleanup)
        projection = ProjectionStore(database_path)
        initialized = chained_event(
            None, "PROJECT_INITIALIZED", {}, event_id="evt_reused"
        )
        projection.apply(initialized)
        reused = chained_event(
            initialized, "X_TEST_EXTENSION", {}, event_id="evt_reused"
        )

        with self.assertRaisesRegex(IntegrityError, "already projected"):
            projection.apply(reused)
        self.assertEqual(projection.project_status("storage-test")["last_sequence"], 1)

    def test_projection_path_swap_is_rejected_before_sql_writes(self):
        temporary, _, database_path = self.paths()
        self.addCleanup(temporary.cleanup)
        projection = ProjectionStore(database_path)
        outside = database_path.parent / "outside.db"
        with sqlite3.connect(outside) as connection:
            connection.execute("CREATE TABLE sentinel (value TEXT)")
            connection.execute("INSERT INTO sentinel VALUES ('unchanged')")
        outside_before = outside.read_bytes()
        backup = database_path.parent / "original-state.db"
        real_connect = projection_module.sqlite3.connect

        def swap_then_connect(database, *args, **kwargs):
            database_path.rename(backup)
            database_path.symlink_to(outside)
            return real_connect(database, *args, **kwargs)

        try:
            with patch.object(
                projection_module.sqlite3,
                "connect",
                side_effect=swap_then_connect,
            ):
                with self.assertRaisesRegex(IntegrityError, "changed while opening"):
                    projection.project_status("storage-test")
        finally:
            if database_path.is_symlink():
                database_path.unlink()
            if backup.exists():
                backup.rename(database_path)
        self.assertEqual(outside.read_bytes(), outside_before)

    def test_stage_is_rejected_after_experiment_terminal_event(self):
        temporary, _, database_path = self.paths()
        self.addCleanup(temporary.cleanup)
        projection = ProjectionStore(database_path)
        initialized = chained_event(
            None, "PROJECT_INITIALIZED", {}, event_id="evt_init"
        )
        registered = chained_event(
            initialized,
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": "exp_terminal",
                "candidate_digest": "candidate-digest",
            },
            event_id="evt_registered",
        )
        terminated = chained_event(
            registered,
            "EXPERIMENT_TERMINATED",
            {"experiment_id": "exp_terminal", "status": "REJECTED"},
            event_id="evt_terminated",
        )
        stage = chained_event(
            terminated,
            "STAGE_COMPLETED",
            {"experiment_id": "exp_terminal", "stage": "verify"},
            event_id="evt_late_stage",
        )
        for event in (initialized, registered, terminated):
            projection.apply(event)

        with self.assertRaisesRegex(IntegrityError, "after experiment"):
            projection.apply(stage)
        status = projection.project_status("storage-test")
        self.assertEqual(status["last_sequence"], 3)
        self.assertEqual(status["experiments_by_status"], {"REJECTED": 1})

    def test_session_finding_cannot_claim_a_different_project(self):
        temporary, _, database_path = self.paths()
        self.addCleanup(temporary.cleanup)
        projection = ProjectionStore(database_path)
        initialized = chained_event(
            None, "PROJECT_INITIALIZED", {}, event_id="evt_init"
        )
        projection.apply(initialized)
        finding = chained_event(
            initialized,
            "FINDING_RECORDED",
            {
                "scope": "session",
                "session_id": "session-1",
                "project_id": "different-project",
                "content": {"message": "not from this project"},
            },
            event_id="evt_finding",
        )

        with self.assertRaisesRegex(IntegrityError, "different event project"):
            projection.apply(finding)

    def test_partial_write_is_truncated_back_to_last_valid_event(self):
        temporary, log_path, _ = self.paths()
        self.addCleanup(temporary.cleanup)
        log = EventLog(log_path, "storage-test")
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_init")
        before = log_path.read_bytes()
        real_write = os.write
        calls = 0

        def partial_then_fail(descriptor: int, data: bytes) -> int:
            nonlocal calls
            calls += 1
            if calls == 1:
                amount = max(1, len(data) // 3)
                return real_write(descriptor, data[:amount])
            raise OSError("injected write failure")

        with patch.object(events_module.os, "write", side_effect=partial_then_fail):
            with self.assertRaises(OSError):
                log.append("X_TEST_EXTENSION", {}, event_id="evt_failed")

        self.assertEqual(log_path.read_bytes(), before)
        self.assertEqual(log.read(), [first])

    def test_fsync_failure_is_truncated_back_to_last_valid_event(self):
        temporary, log_path, _ = self.paths()
        self.addCleanup(temporary.cleanup)
        log = EventLog(log_path, "storage-test")
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_init")
        before = log_path.read_bytes()
        real_fsync = os.fsync
        calls = 0

        def fail_once(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("injected fsync failure")
            real_fsync(descriptor)

        with patch.object(events_module.os, "fsync", side_effect=fail_once):
            with self.assertRaises(OSError):
                log.append("X_TEST_EXTENSION", {}, event_id="evt_failed")

        self.assertEqual(log_path.read_bytes(), before)
        self.assertEqual(log.read(), [first])

    def test_read_and_verify_reject_unsafe_write_permissions(self):
        temporary, log_path, _ = self.paths()
        self.addCleanup(temporary.cleanup)
        log = EventLog(log_path, "storage-test")
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_init")
        os.chmod(log_path, 0o666)

        with self.assertRaisesRegex(IntegrityError, "group- or world-writable"):
            log.read()
        with self.assertRaisesRegex(IntegrityError, "group- or world-writable"):
            log.verify()
        with self.assertRaisesRegex(IntegrityError, "group- or world-writable"):
            with log.locked_read():
                pass

        second = log.append("X_TEST_EXTENSION", {}, event_id="evt_second")
        self.assertEqual(stat.S_IMODE(log_path.stat().st_mode), 0o600)
        self.assertEqual(log.read(), [first, second])

    def test_explicit_recovery_discards_only_a_non_newline_tail(self):
        temporary, log_path, _ = self.paths()
        self.addCleanup(temporary.cleanup)
        log = EventLog(log_path, "storage-test")
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_init")
        committed = log_path.read_bytes()
        fragment = b'{"event_id":"evt_interrupted","event_type":'
        with log_path.open("ab") as stream:
            stream.write(fragment)
            stream.flush()
            os.fsync(stream.fileno())

        with self.assertRaisesRegex(IntegrityError, "partially written"):
            log.read()
        self.assertEqual(log.recover_tail(), len(fragment))
        self.assertEqual(log_path.read_bytes(), committed)
        self.assertEqual(log.read(), [first])
        self.assertEqual(log.recover_tail(), 0)

    def test_append_recovers_crash_fragment_before_hashing_next_event(self):
        temporary, log_path, _ = self.paths()
        self.addCleanup(temporary.cleanup)
        log = EventLog(log_path, "storage-test")
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_init")
        with log_path.open("ab") as stream:
            stream.write(b'{"uncommitted":true')
            stream.flush()
            os.fsync(stream.fileno())

        second = log.append("X_TEST_EXTENSION", {}, event_id="evt_after_crash")

        self.assertEqual(log.read(), [first, second])
        self.assertEqual(second.sequence, 2)
        self.assertEqual(second.prev_hash, first.hash)

    def test_recovery_never_hides_corruption_in_committed_prefix(self):
        temporary, log_path, _ = self.paths()
        self.addCleanup(temporary.cleanup)
        log = EventLog(log_path, "storage-test")
        log.append("PROJECT_INITIALIZED", {}, event_id="evt_init")
        log.append("X_TEST_EXTENSION", {}, event_id="evt_second")
        corrupted = log_path.read_bytes().replace(
            b"PROJECT_INITIALIZED", b"QROJECT_INITIALIZED", 1
        )
        corrupted += b'{"event_id":"evt_interrupted"'
        log_path.write_bytes(corrupted)

        with self.assertRaisesRegex(IntegrityError, "hash mismatch"):
            log.recover_tail()
        self.assertEqual(log_path.read_bytes(), corrupted)
        with self.assertRaisesRegex(IntegrityError, "hash mismatch"):
            log.append("X_TEST_EXTENSION", {}, event_id="evt_must_not_append")
        self.assertEqual(log_path.read_bytes(), corrupted)

    def test_rebuild_cannot_regress_a_concurrent_projection_writer(self):
        temporary, log_path, database_path = self.paths()
        self.addCleanup(temporary.cleanup)
        log = EventLog(log_path, "storage-test")
        initialized = log.append("PROJECT_INITIALIZED", {}, event_id="evt_initialized")
        projection = ProjectionStore(database_path)
        projection.sync(log)
        next_event = chained_event(
            initialized, "X_TEST_EXTENSION", {}, event_id="evt_next"
        )

        snapshot_taken = threading.Event()
        release_snapshot = threading.Event()
        apply_started = threading.Event()
        apply_finished = threading.Event()
        failures: list[BaseException] = []
        original_locked_read = log.locked_read

        @contextmanager
        def paused_locked_read():
            with original_locked_read() as events:
                snapshot_taken.set()
                if not release_snapshot.wait(5):
                    raise AssertionError("test did not release the event snapshot")
                yield events

        log.locked_read = paused_locked_read  # type: ignore[method-assign]

        def rebuild() -> None:
            try:
                projection.rebuild(log)
            except BaseException as exc:
                failures.append(exc)

        def apply() -> None:
            apply_started.set()
            try:
                projection.apply(next_event)
            except BaseException as exc:
                failures.append(exc)
            finally:
                apply_finished.set()

        rebuild_thread = threading.Thread(target=rebuild)
        rebuild_thread.start()
        self.assertTrue(snapshot_taken.wait(5))
        apply_thread = threading.Thread(target=apply)
        apply_thread.start()
        self.assertTrue(apply_started.wait(5))
        self.assertFalse(apply_finished.wait(0.1))
        release_snapshot.set()
        rebuild_thread.join(5)
        apply_thread.join(5)

        self.assertFalse(rebuild_thread.is_alive())
        self.assertFalse(apply_thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(projection.project_status("storage-test")["last_sequence"], 2)


if __name__ == "__main__":
    unittest.main()
