from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_os.errors import IntegrityError
from research_os.kernel.events import EventLog
from research_os.kernel.projection import ProjectionStore


class ProjectionRecoveryTests(unittest.TestCase):
    def projection_with_log(
        self,
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, EventLog, ProjectionStore]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        log = EventLog(root / "events.jsonl", "recovery-test")
        log.append("PROJECT_INITIALIZED", {"status": "active"})
        projection = ProjectionStore(root / "state.db")
        self.assertEqual(projection.sync(log), 1)
        return temporary, root, log, projection

    def test_sync_recovers_database_corrupted_after_construction(self):
        _, root, log, projection = self.projection_with_log()
        corrupt_bytes = b"not a sqlite database\n"
        projection.path.write_bytes(corrupt_bytes)

        self.assertEqual(projection.sync(log), 1)
        self.assertEqual(
            projection.project_status("recovery-test")["last_sequence"], 1
        )
        backups = list(root.glob("state.db.corrupt-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), corrupt_bytes)

    def test_rebuild_recovers_incompatible_schema_after_construction(self):
        _, root, log, projection = self.projection_with_log()
        replacement = root / "incompatible.db"
        with sqlite3.connect(replacement) as connection:
            connection.execute("CREATE TABLE projects(foo TEXT)")
            connection.execute("INSERT INTO projects VALUES ('forensic-value')")
        os.replace(replacement, projection.path)

        self.assertEqual(projection.rebuild(log), 1)
        self.assertEqual(
            projection.project_status("recovery-test")["last_sequence"], 1
        )
        backups = list(root.glob("state.db.corrupt-*"))
        self.assertEqual(len(backups), 1)
        with sqlite3.connect(backups[0]) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(projects)")
            }
            value = connection.execute("SELECT foo FROM projects").fetchone()[0]
        self.assertEqual(columns, {"foo"})
        self.assertEqual(value, "forensic-value")

    def test_constructor_recovers_an_existing_incompatible_schema(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        database = root / "state.db"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE projects(foo TEXT)")

        projection = ProjectionStore(database)

        self.assertEqual(projection.project_status("recovery-test")["last_sequence"], 0)
        self.assertEqual(len(list(root.glob("state.db.corrupt-*"))), 1)

    def test_non_cache_sqlite_failure_is_wrapped_without_quarantine(self):
        _, root, log, projection = self.projection_with_log()
        failure = sqlite3.OperationalError("attempt to write a readonly database")

        with patch.object(
            projection, "_sync_once", side_effect=failure
        ) as sync_once:
            with self.assertRaisesRegex(IntegrityError, "cannot sync projection"):
                projection.sync(log)

        self.assertEqual(sync_once.call_count, 1)
        self.assertEqual(list(root.glob("state.db.corrupt-*")), [])

    def test_repeated_schema_sql_error_is_wrapped_after_one_retry(self):
        _, root, log, projection = self.projection_with_log()

        def missing_schema(_: EventLog) -> int:
            raise sqlite3.OperationalError("no such table: event_cursor")

        with patch.object(
            projection, "_sync_once", side_effect=missing_schema
        ) as sync_once:
            with self.assertRaisesRegex(
                IntegrityError, "cannot sync projection database after recovery"
            ):
                projection.sync(log)

        self.assertEqual(sync_once.call_count, 2)
        self.assertEqual(len(list(root.glob("state.db.corrupt-*"))), 1)

    def test_rebuild_quarantines_an_unexpected_unique_index(self):
        _, root, log, projection = self.projection_with_log()
        with sqlite3.connect(projection.path) as connection:
            connection.execute(
                "CREATE UNIQUE INDEX unexpected_artifact_digest "
                "ON artifacts(digest)"
            )

        self.assertEqual(projection.rebuild(log), 1)
        self.assertEqual(len(list(root.glob("state.db.corrupt-*"))), 1)
        with sqlite3.connect(projection.path) as connection:
            unexpected = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = ?",
                ("unexpected_artifact_digest",),
            ).fetchone()
        self.assertIsNone(unexpected)

    def test_rebuild_quarantines_an_unexpected_trigger(self):
        _, root, log, projection = self.projection_with_log()
        with sqlite3.connect(projection.path) as connection:
            connection.execute(
                "CREATE TRIGGER veto_project_insert BEFORE INSERT ON projects "
                "BEGIN SELECT RAISE(ABORT, 'projection veto'); END"
            )

        self.assertEqual(projection.rebuild(log), 1)
        self.assertEqual(len(list(root.glob("state.db.corrupt-*"))), 1)
        with sqlite3.connect(projection.path) as connection:
            trigger = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'trigger' AND name = ?",
                ("veto_project_insert",),
            ).fetchone()
        self.assertIsNone(trigger)

    def test_rebuild_quarantines_a_hidden_generated_column(self):
        _, root, log, projection = self.projection_with_log()
        with sqlite3.connect(projection.path) as connection:
            connection.execute(
                "ALTER TABLE artifacts ADD COLUMN evil INTEGER "
                "GENERATED ALWAYS AS (NULL) VIRTUAL NOT NULL"
            )

        self.assertEqual(projection.rebuild(log), 1)
        self.assertEqual(len(list(root.glob("state.db.corrupt-*"))), 1)
        with sqlite3.connect(projection.path) as connection:
            columns = {
                row[1] for row in connection.execute("PRAGMA table_xinfo(artifacts)")
            }
        self.assertNotIn("evil", columns)

    def test_constructor_quarantines_corrupt_legacy_migration_rows(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        database = root / "state.db"
        with sqlite3.connect(database) as connection:
            connection.executescript(
                """
                CREATE TABLE experiments (
                    experiment_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    parent_id TEXT,
                    candidate_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    terminated_at TEXT,
                    created_sequence INTEGER NOT NULL UNIQUE,
                    updated_sequence INTEGER NOT NULL
                );
                INSERT INTO experiments VALUES (
                    'exp_bad', 'recovery-test', NULL, 'digest', 'REGISTERED',
                    'not-json', '2026-01-01T00:00:00Z', NULL, 1, 1
                );
                """
            )

        projection = ProjectionStore(database)

        self.assertEqual(projection.project_status("recovery-test")["last_sequence"], 0)
        self.assertEqual(len(list(root.glob("state.db.corrupt-*"))), 1)


if __name__ == "__main__":
    unittest.main()
