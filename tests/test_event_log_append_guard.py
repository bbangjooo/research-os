from __future__ import annotations

import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from research_os.errors import IntegrityError
from research_os.kernel import events as events_module
from research_os.kernel.events import Event, EventHeadMismatchError, EventLog


class EventLogAppendGuardTests(unittest.TestCase):
    def event_log(self) -> tuple[tempfile.TemporaryDirectory[str], EventLog, Path]:
        temporary = tempfile.TemporaryDirectory()
        path = Path(temporary.name) / "events.jsonl"
        return temporary, EventLog(path, "append-guard-test"), path

    def test_expected_head_accepts_empty_and_current_canonical_heads(self):
        temporary, log, _ = self.event_log()
        self.addCleanup(temporary.cleanup)

        first = log.append(
            "PROJECT_INITIALIZED",
            {},
            event_id="evt_first",
            expected_head=(0, None),
        )
        second = log.append(
            "X_TEST_EXTENSION",
            {},
            event_id="evt_second",
            expected_head=(first.sequence, first.hash),
        )

        self.assertEqual(log.read(), [first, second])

    def test_stale_expected_head_rejects_without_appending(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        before = path.read_bytes()

        with self.assertRaises(EventHeadMismatchError) as raised:
            log.append(
                "X_TEST_EXTENSION",
                {},
                event_id="evt_stale",
                expected_head=(0, None),
            )

        self.assertEqual(raised.exception.expected_head, (0, None))
        self.assertEqual(
            raised.exception.actual_head,
            (first.sequence, first.hash),
        )
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(log.read(), [first])

    def test_head_mismatch_is_checked_before_precondition(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        before = path.read_bytes()
        called = False

        def guard(_: tuple[Event, ...]) -> None:
            nonlocal called
            called = True

        with self.assertRaises(EventHeadMismatchError):
            log.append(
                "X_TEST_EXTENSION",
                {},
                event_id="evt_stale",
                expected_head=(0, None),
                precondition=guard,
            )

        self.assertFalse(called)
        self.assertEqual(path.read_bytes(), before)

    def test_raising_precondition_rejects_without_appending(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        before = path.read_bytes()
        observed: tuple[Event, ...] | None = None

        def reject(events: tuple[Event, ...]) -> None:
            nonlocal observed
            observed = events
            raise RuntimeError("external certification changed")

        with self.assertRaisesRegex(RuntimeError, "certification changed"):
            log.append(
                "X_TEST_EXTENSION",
                {},
                event_id="evt_rejected",
                expected_head=(first.sequence, first.hash),
                precondition=reject,
            )

        self.assertEqual(observed, (first,))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(log.read(), [first])

    def test_raising_postcondition_rolls_back_durable_append(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        before = path.read_bytes()
        observed: tuple[Event, ...] | None = None
        provisional = b""

        def reject(events: tuple[Event, ...]) -> None:
            nonlocal observed, provisional
            observed = events
            provisional = path.read_bytes()
            raise RuntimeError("post-commit certification changed")

        with self.assertRaisesRegex(RuntimeError, "certification changed"):
            log.append(
                "X_TEST_EXTENSION",
                {},
                event_id="evt_rejected",
                expected_head=(first.sequence, first.hash),
                postcondition=reject,
            )

        self.assertEqual(observed, (first,))
        self.assertGreater(len(provisional), len(before))
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(log.read(), [first])

    def test_precondition_same_inode_append_is_detected_and_rolled_back(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        before = path.read_bytes()

        def append_to_prefix(_: tuple[Event, ...]) -> None:
            descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
            try:
                os.write(descriptor, b"same-inode corruption")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

        with self.assertRaisesRegex(IntegrityError, "bytes changed during append precondition"):
            log.append(
                "X_TEST_EXTENSION",
                {},
                event_id="evt_corrupt_precondition",
                expected_head=(first.sequence, first.hash),
                precondition=append_to_prefix,
            )

        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(log.read(), [first])

    def test_verified_recovery_bytes_are_the_append_prefix_anchor(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        before = path.read_bytes()
        original_read = log._read_bytes_fd
        corrupted = False

        def read_then_corrupt(descriptor: int) -> bytes:
            nonlocal corrupted
            data = original_read(descriptor)
            if not corrupted:
                corrupted = True
                os.pwrite(descriptor, b"X", 0)
                os.fsync(descriptor)
            return data

        with (
            mock.patch.object(
                log,
                "_read_bytes_fd",
                side_effect=read_then_corrupt,
            ),
            self.assertRaisesRegex(IntegrityError, "bytes changed during append precondition"),
        ):
            log.append(
                "X_TEST_EXTENSION",
                {},
                event_id="evt_recovery_read_race",
                expected_head=(first.sequence, first.hash),
            )

        self.assertTrue(corrupted)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(log.read(), [first])

    def test_postcondition_same_inode_overwrite_is_detected_and_repaired(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        before = path.read_bytes()

        def overwrite_prefix(_: tuple[Event, ...]) -> None:
            descriptor = os.open(path, os.O_RDWR)
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                os.write(descriptor, b"X")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

        with self.assertRaisesRegex(IntegrityError, "bytes changed during append postcondition"):
            log.append(
                "X_TEST_EXTENSION",
                {},
                event_id="evt_corrupt_postcondition",
                expected_head=(first.sequence, first.hash),
                postcondition=overwrite_prefix,
            )

        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(log.read(), [first])

    def test_raising_postcondition_repairs_same_inode_overwrite(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        before = path.read_bytes()

        def overwrite_then_reject(_: tuple[Event, ...]) -> None:
            descriptor = os.open(path, os.O_RDWR)
            try:
                os.lseek(descriptor, 0, os.SEEK_SET)
                os.write(descriptor, b"X")
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            raise RuntimeError("postcondition rejected after same-inode overwrite")

        with self.assertRaisesRegex(RuntimeError, "same-inode overwrite"):
            log.append(
                "X_TEST_EXTENSION",
                {},
                event_id="evt_corrupt_and_reject",
                expected_head=(first.sequence, first.hash),
                postcondition=overwrite_then_reject,
            )

        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(log.read(), [first])

    def test_process_exit_in_postcondition_leaves_only_recoverable_tail(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        before = path.read_bytes()
        process_id = os.fork()
        if process_id == 0:  # pragma: no cover - assertions run in the parent
            child_log = EventLog(path, "append-guard-test")

            def terminate(_: tuple[Event, ...]) -> None:
                os._exit(23)

            child_log.append(
                "X_TEST_EXTENSION",
                {},
                event_id="evt_crash_window",
                expected_head=(first.sequence, first.hash),
                postcondition=terminate,
            )
            os._exit(24)

        _, wait_status = os.waitpid(process_id, 0)

        self.assertEqual(os.waitstatus_to_exitcode(wait_status), 23)
        self.assertGreater(path.stat().st_size, len(before))
        with self.assertRaisesRegex(IntegrityError, "partially written"):
            log.read()
        self.assertGreater(log.recover_tail(), 0)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(log.read(), [first])

    def test_append_rejects_path_replacement_after_flock(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        before = path.read_bytes()
        displaced = path.with_name("events.displaced.jsonl")
        replacement = b"replacement event-log inode\n"
        real_flock = events_module.fcntl.flock
        replaced = False

        def replace_after_lock(descriptor: int, operation: int) -> None:
            nonlocal replaced
            real_flock(descriptor, operation)
            if operation == events_module.fcntl.LOCK_EX and not replaced:
                replaced = True
                os.replace(path, displaced)
                path.write_bytes(replacement)

        with (
            mock.patch.object(
                events_module.fcntl,
                "flock",
                side_effect=replace_after_lock,
            ),
            self.assertRaisesRegex(IntegrityError, "canonical inode changed"),
        ):
            log.append(
                "X_TEST_EXTENSION",
                {},
                event_id="evt_replaced",
                expected_head=(first.sequence, first.hash),
            )

        self.assertTrue(replaced)
        self.assertEqual(displaced.read_bytes(), before)
        self.assertEqual(path.read_bytes(), replacement)

    def test_append_rolls_back_detached_inode_on_commit_replacement(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        before = path.read_bytes()
        displaced = path.with_name("events.displaced.jsonl")
        replacement = b"replacement event-log inode\n"
        real_write = os.write
        replaced = False

        def replace_before_write(descriptor: int, data: bytes) -> int:
            nonlocal replaced
            if not replaced:
                replaced = True
                os.replace(path, displaced)
                path.write_bytes(replacement)
            return real_write(descriptor, data)

        with (
            mock.patch.object(
                events_module.os,
                "write",
                side_effect=replace_before_write,
            ),
            self.assertRaisesRegex(IntegrityError, "canonical inode changed"),
        ):
            log.append(
                "X_TEST_EXTENSION",
                {},
                event_id="evt_replaced",
                expected_head=(first.sequence, first.hash),
            )

        self.assertTrue(replaced)
        self.assertEqual(displaced.read_bytes(), before)
        self.assertEqual(path.read_bytes(), replacement)

    def test_commit_marker_write_detects_provisional_body_corruption(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        before = path.read_bytes()
        real_write = os.write
        corrupted = False

        def corrupt_before_marker(descriptor: int, data: bytes) -> int:
            nonlocal corrupted
            if data == b"\n" and not corrupted:
                corrupted = True
                provisional_size = os.fstat(descriptor).st_size
                os.pwrite(descriptor, b"X", provisional_size - 1)
                os.fsync(descriptor)
            return real_write(descriptor, data)

        with (
            mock.patch.object(
                events_module.os,
                "write",
                side_effect=corrupt_before_marker,
            ),
            self.assertRaisesRegex(IntegrityError, "bytes changed during append commit"),
        ):
            log.append(
                "X_TEST_EXTENSION",
                {},
                event_id="evt_corrupt_at_marker",
                expected_head=(first.sequence, first.hash),
            )

        self.assertTrue(corrupted)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(log.read(), [first])

    def test_postcondition_replacement_dominates_callback_error_after_rollback(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        before = path.read_bytes()
        displaced = path.with_name("events.displaced.jsonl")
        replacement = b"replacement event-log inode\n"

        def replace_then_reject(_: tuple[Event, ...]) -> None:
            os.replace(path, displaced)
            path.write_bytes(replacement)
            raise RuntimeError("postcondition rejected after path replacement")

        with self.assertRaisesRegex(IntegrityError, "canonical inode identity") as raised:
            log.append(
                "X_TEST_EXTENSION",
                {},
                event_id="evt_replaced_in_postcondition",
                expected_head=(first.sequence, first.hash),
                postcondition=replace_then_reject,
            )

        self.assertIsInstance(raised.exception.__cause__, RuntimeError)
        self.assertEqual(displaced.read_bytes(), before)
        self.assertEqual(path.read_bytes(), replacement)

    def test_actual_create_after_open_race_fsyncs_parent(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        path.write_bytes(b"")
        real_open = os.open
        removed = False

        def unlink_before_existing_open(
            target: os.PathLike[str] | str,
            flags: int,
            mode: int = 0o777,
        ) -> int:
            nonlocal removed
            if (
                os.fspath(target) == os.fspath(path)
                and not flags & os.O_CREAT
                and not removed
            ):
                removed = True
                path.unlink()
            return real_open(target, flags, mode)

        with (
            mock.patch.object(
                events_module.os,
                "open",
                side_effect=unlink_before_existing_open,
            ),
            mock.patch.object(log, "_fsync_parent") as parent_fsync,
        ):
            event = log.append(
                "PROJECT_INITIALIZED",
                {},
                event_id="evt_created_after_race",
            )

        self.assertTrue(removed)
        parent_fsync.assert_called_once_with()
        self.assertEqual(log.read(), [event])

    def test_new_log_parent_open_failure_rolls_back_event(self):
        temporary, log, path = self.event_log()
        self.addCleanup(temporary.cleanup)
        real_open = os.open
        parent_open_failed = False

        def fail_parent_open(
            target: os.PathLike[str] | str,
            flags: int,
            mode: int = 0o777,
        ) -> int:
            nonlocal parent_open_failed
            if os.fspath(target) == os.fspath(path.parent):
                parent_open_failed = True
                raise PermissionError("injected parent-directory open failure")
            return real_open(target, flags, mode)

        with (
            mock.patch.object(
                events_module.os,
                "open",
                side_effect=fail_parent_open,
            ),
            self.assertRaisesRegex(IntegrityError, "parent for durability"),
        ):
            log.append(
                "PROJECT_INITIALIZED",
                {},
                event_id="evt_parent_fsync_failed",
                expected_head=(0, None),
            )

        self.assertTrue(parent_open_failed)
        self.assertTrue(path.exists())
        self.assertEqual(path.read_bytes(), b"")
        self.assertEqual(log.read(), [])

        with mock.patch.object(
            log,
            "_fsync_parent",
            wraps=log._fsync_parent,
        ) as parent_fsync:
            event = log.append(
                "PROJECT_INITIALIZED",
                {},
                event_id="evt_parent_fsync_retry",
                expected_head=(0, None),
            )

        parent_fsync.assert_called_once_with()
        self.assertEqual(log.read(), [event])

    def test_precondition_runs_while_competing_append_is_excluded(self):
        temporary, log, _ = self.event_log()
        self.addCleanup(temporary.cleanup)
        first = log.append("PROJECT_INITIALIZED", {}, event_id="evt_first")
        guard_started = threading.Event()
        release_guard = threading.Event()
        competitor_started = threading.Event()
        competitor_finished = threading.Event()
        failures: list[BaseException] = []

        def pause(_: tuple[Event, ...]) -> None:
            guard_started.set()
            if not release_guard.wait(5):
                raise AssertionError("test did not release append precondition")

        def guarded_append() -> None:
            try:
                log.append(
                    "X_TEST_EXTENSION",
                    {},
                    event_id="evt_guarded",
                    expected_head=(first.sequence, first.hash),
                    precondition=pause,
                )
            except BaseException as exc:
                failures.append(exc)

        def competing_append() -> None:
            competitor_started.set()
            try:
                log.append(
                    "X_TEST_EXTENSION",
                    {},
                    event_id="evt_competing",
                )
            except BaseException as exc:
                failures.append(exc)
            finally:
                competitor_finished.set()

        guarded_thread = threading.Thread(target=guarded_append)
        guarded_thread.start()
        self.assertTrue(guard_started.wait(5))
        competing_thread = threading.Thread(target=competing_append)
        competing_thread.start()
        self.assertTrue(competitor_started.wait(5))
        self.assertFalse(competitor_finished.wait(0.1))

        release_guard.set()
        guarded_thread.join(5)
        competing_thread.join(5)

        self.assertFalse(guarded_thread.is_alive())
        self.assertFalse(competing_thread.is_alive())
        self.assertEqual(failures, [])
        self.assertEqual(
            [event.event_id for event in log.read()],
            ["evt_first", "evt_guarded", "evt_competing"],
        )


if __name__ == "__main__":
    unittest.main()
