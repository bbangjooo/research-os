from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from research_os.contracts.common import sha256_json
from research_os.errors import IntegrityError, ScientificStateError
from research_os.kernel._canonical import canonical_bytes, canonical_json, sha256_hex
from research_os.kernel.events import EVENT_VERSION, Event, EventLog
from research_os.kernel.projection import ProjectionStore

PROJECT_ID = "m1c-projection-test"
CANDIDATE_DIGEST = "a" * 64
COMPATIBILITY_DIGEST = "b" * 64
GENERATION_ID = "generation_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
V1_COMPAT_PROJECT_ID = "fixture-m1c-v1-compat"
V1_PROJECTION_DIGEST = "a7efa9d03083f3c865633fa08258630bada7376c6add9d9d6c5864349d0e8439"


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
        "occurred_at": "2026-08-10T00:00:00.000000Z",
        "payload": payload,
        "prev_hash": previous.hash if previous is not None else None,
        "project_id": PROJECT_ID,
        "sequence": previous.sequence + 1 if previous is not None else 1,
        "version": EVENT_VERSION,
    }
    return Event.from_mapping({**unsigned, "hash": sha256_hex(canonical_bytes(unsigned))})


def registration_payload(
    experiment_id: str,
    *,
    evaluation_scope_id: str | None = None,
    attempt: int = 1,
    retry_of: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "experiment_id": experiment_id,
        "generation_id": GENERATION_ID,
        "parent_id": None,
        "candidate_digest": CANDIDATE_DIGEST,
        "compatibility_digest": COMPATIBILITY_DIGEST,
        "attempt": attempt,
        "retry_of": retry_of,
        "status": "registered",
        "authorized_action": None,
    }
    if evaluation_scope_id is not None:
        payload.update(
            {
                "evaluation_scope_id": evaluation_scope_id,
                "proposal": {"authorized_action": None},
                "proposal_digest": "c" * 64,
                "proposal_id": "proposal_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            }
        )
    return payload


def downgrade_scope_schema(database: Path, *, experiment_id: str, evaluation_scope_id: str) -> None:
    payload = dict(registration_payload(experiment_id))
    payload["evaluation_scope_id"] = evaluation_scope_id
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE experiments SET payload_json = ? WHERE experiment_id = ?",
            (canonical_json(payload), experiment_id),
        )
        connection.execute(
            "DROP INDEX experiments_candidate_parent_compatibility_generation_attempt_unique_idx"
        )
        connection.execute("DROP INDEX experiments_candidate_idx")
        connection.execute("DROP INDEX experiments_scope_idx")
        connection.execute("ALTER TABLE experiments DROP COLUMN evaluation_scope_id")
        connection.execute(
            "CREATE INDEX experiments_candidate_idx ON experiments("
            "project_id, generation_id, candidate_digest, parent_id)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX "
            "experiments_candidate_parent_compatibility_generation_attempt_unique_idx "
            "ON experiments(project_id, candidate_digest, COALESCE(parent_id, ''), "
            "compatibility_digest, COALESCE(generation_id, ''), attempt)"
        )


class M1CProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.database = self.root / "state.db"
        self.projection = ProjectionStore(self.database)
        self.initialized = chained_event(
            None,
            "PROJECT_INITIALIZED",
            {"project_id": PROJECT_ID, "status": "active"},
            event_id="evt_m1c_projection_init",
        )

    def test_fresh_schema_and_v1_null_scope_preserve_decoded_api(self) -> None:
        self.projection.apply(self.initialized)
        registered = chained_event(
            self.initialized,
            "EXPERIMENT_REGISTERED",
            registration_payload("exp_m1c_unscoped"),
            event_id="evt_m1c_unscoped",
        )
        self.projection.apply(registered)

        with sqlite3.connect(self.database) as connection:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(experiments)")}
            indexes = {row[1] for row in connection.execute("PRAGMA index_list(experiments)")}
        self.assertIn("evaluation_scope_id", columns)
        self.assertIn("experiments_scope_idx", indexes)

        experiment = self.projection.experiment(PROJECT_ID, "exp_m1c_unscoped")
        self.assertNotIn("evaluation_scope_id", experiment)
        self.assertNotIn("evaluation_scope_id", experiment["payload"])
        self.assertTrue(
            self.projection.candidate_exists(
                PROJECT_ID,
                CANDIDATE_DIGEST,
                None,
                COMPATIBILITY_DIGEST,
                GENERATION_ID,
            )
        )

    def test_fixed_v1_projection_digest_and_keyset_are_exact(self) -> None:
        source = (
            Path(__file__).parent
            / "fixtures"
            / "scientific_state"
            / "v2"
            / "m1b-v1-generation-events.jsonl"
        )
        event_path = self.root / "v1-events.jsonl"
        event_path.write_bytes(source.read_bytes())
        event_log = EventLog(event_path, V1_COMPAT_PROJECT_ID)

        self.projection.rebuild(event_log)
        observed = {
            "status": self.projection.project_status(V1_COMPAT_PROJECT_ID),
            "lineage": self.projection.lineage(V1_COMPAT_PROJECT_ID),
        }

        self.assertEqual(sha256_json(observed), V1_PROJECTION_DIGEST)
        for row in observed["lineage"]:
            self.assertNotIn("evaluation_scope_id", row)
            self.assertNotIn("evaluation_scope_id", row["payload"])

    def test_concurrent_initializers_serialize_schema_maintenance(self) -> None:
        worker_count = 8
        barrier = threading.Barrier(worker_count)
        failures: list[BaseException] = []
        cold_database = self.root / "concurrent-cold-state.db"

        def initialize() -> None:
            try:
                barrier.wait(timeout=5)
                ProjectionStore(cold_database)
            except BaseException as exc:  # pragma: no cover - asserted below
                failures.append(exc)

        workers = [threading.Thread(target=initialize) for _ in range(worker_count)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10)

        self.assertFalse(any(worker.is_alive() for worker in workers))
        self.assertEqual(failures, [])
        self.assertEqual(list(self.root.glob("concurrent-cold-state.db.corrupt-*")), [])
        self.assertFalse(
            ProjectionStore(cold_database).project_status(PROJECT_ID)["initialized"]
        )

    def test_rebuild_persists_and_queries_evaluation_scope_axis(self) -> None:
        event_log = EventLog(self.root / "events.jsonl", PROJECT_ID)
        event_log.append(
            "PROJECT_INITIALIZED",
            {"project_id": PROJECT_ID, "status": "active"},
        )
        event_log.append(
            "EXPERIMENT_REGISTERED",
            registration_payload("exp_m1c_development", evaluation_scope_id="development"),
        )
        event_log.append(
            "EXPERIMENT_REGISTERED",
            registration_payload("exp_m1c_replication", evaluation_scope_id="replication-1"),
        )

        with mock.patch("research_os.kernel.projection._validate_scientific_history"):
            self.assertEqual(self.projection.rebuild(event_log), 3)

        rows = self.projection.lineage(PROJECT_ID)
        self.assertEqual(
            [row["evaluation_scope_id"] for row in rows],
            ["development", "replication-1"],
        )
        self.assertFalse(
            self.projection.candidate_exists(
                PROJECT_ID,
                CANDIDATE_DIGEST,
                None,
                COMPATIBILITY_DIGEST,
                GENERATION_ID,
            )
        )
        for scope_id, experiment_id in (
            ("development", "exp_m1c_development"),
            ("replication-1", "exp_m1c_replication"),
        ):
            with self.subTest(scope_id=scope_id):
                self.assertTrue(
                    self.projection.candidate_exists(
                        PROJECT_ID,
                        CANDIDATE_DIGEST,
                        None,
                        COMPATIBILITY_DIGEST,
                        GENERATION_ID,
                        scope_id,
                    )
                )
                attempts = self.projection.candidate_attempts(
                    PROJECT_ID,
                    CANDIDATE_DIGEST,
                    None,
                    COMPATIBILITY_DIGEST,
                    GENERATION_ID,
                    scope_id,
                )
                self.assertEqual([row["experiment_id"] for row in attempts], [experiment_id])

    def test_retry_scope_mismatch_rolls_back_rebuild(self) -> None:
        event_log = EventLog(self.root / "events.jsonl", PROJECT_ID)
        event_log.append(
            "PROJECT_INITIALIZED",
            {"project_id": PROJECT_ID, "status": "active"},
        )
        event_log.append(
            "EXPERIMENT_REGISTERED",
            registration_payload("exp_m1c_retry_first", evaluation_scope_id="development"),
        )
        event_log.append(
            "EXPERIMENT_TERMINATED",
            {
                "experiment_id": "exp_m1c_retry_first",
                "status": "TIMED_OUT",
                "attempt": 1,
                "retry_of": None,
                "retryable": True,
            },
        )
        event_log.append(
            "EXPERIMENT_REGISTERED",
            registration_payload(
                "exp_m1c_retry_second",
                evaluation_scope_id="replication-1",
                attempt=2,
                retry_of="exp_m1c_retry_first",
            ),
        )

        with (
            mock.patch("research_os.kernel.projection._validate_scientific_history"),
            self.assertRaisesRegex(IntegrityError, "evaluation scope"),
        ):
            self.projection.rebuild(event_log)

        status = self.projection.project_status(PROJECT_ID)
        self.assertFalse(status["initialized"])
        self.assertEqual(status["last_sequence"], 0)

    def test_historyless_apply_rejects_typed_events_without_mutation(self) -> None:
        self.projection.apply(self.initialized)
        cases = (
            (
                "registration",
                chained_event(
                    self.initialized,
                    "EXPERIMENT_REGISTERED",
                    registration_payload("exp_m1c_historyless", evaluation_scope_id="development"),
                    event_id="evt_m1c_historyless_registration",
                ),
            ),
            (
                "baseline",
                chained_event(
                    self.initialized,
                    "BASELINE_RECORDED",
                    {
                        "baseline_id": "base_m1c_historyless",
                        "evaluation_scope_id": "development",
                        "evaluation_scope": {
                            "id": "development",
                            "role": "development",
                            "manifest_digest": "d" * 64,
                        },
                    },
                    event_id="evt_m1c_historyless_baseline",
                ),
            ),
            (
                "partial-baseline",
                chained_event(
                    self.initialized,
                    "BASELINE_RECORDED",
                    {
                        "baseline_id": "base_m1c_partial_historyless",
                        "science_state_version": 1,
                    },
                    event_id="evt_m1c_partial_historyless_baseline",
                ),
            ),
        )
        for label, event in cases:
            with (
                self.subTest(label=label),
                self.assertRaisesRegex(IntegrityError, "require canonical history"),
            ):
                self.projection.apply(event)
            self.assertEqual(self.projection.project_status(PROJECT_ID)["last_sequence"], 1)

    def test_sync_and_rebuild_reduce_full_history_before_sql_mutation(self) -> None:
        for operation in ("sync", "rebuild"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                projection = ProjectionStore(root / "state.db")
                event_log = EventLog(root / "events.jsonl", PROJECT_ID)
                initialized = event_log.append(
                    "PROJECT_INITIALIZED",
                    {"project_id": PROJECT_ID, "status": "active"},
                )
                event_log.append("vendor.note", {"authorized_action": None})
                projection.apply(initialized)
                failure = ScientificStateError("PROPOSAL_DIGEST_MISMATCH", "forged typed history")
                with mock.patch(
                    "research_os.science.state.reduce_scientific_state",
                    side_effect=failure,
                ) as reduce:
                    with self.assertRaises(ScientificStateError) as caught:
                        getattr(projection, operation)(event_log)
                self.assertIs(caught.exception, failure)
                self.assertEqual(caught.exception.code, "PROPOSAL_DIGEST_MISMATCH")
                self.assertEqual(reduce.call_count, 1)
                self.assertEqual(projection.project_status(PROJECT_ID)["last_sequence"], 1)

    def test_pre_scope_schema_migrates_payload_without_quarantine(self) -> None:
        self.projection.apply(self.initialized)
        registered = chained_event(
            self.initialized,
            "EXPERIMENT_REGISTERED",
            registration_payload("exp_m1c_scope_migration"),
            event_id="evt_m1c_scope_migration",
        )
        self.projection.apply(registered)

        downgrade_scope_schema(
            self.database,
            experiment_id="exp_m1c_scope_migration",
            evaluation_scope_id="development",
        )

        migrated = ProjectionStore(self.database)
        self.assertEqual(
            migrated.experiment(PROJECT_ID, "exp_m1c_scope_migration")["evaluation_scope_id"],
            "development",
        )
        self.assertEqual(list(self.root.glob("state.db.corrupt-*")), [])

    def test_pre_scope_schema_rejects_untrimmed_scope_backfill(self) -> None:
        self.projection.apply(self.initialized)
        registered = chained_event(
            self.initialized,
            "EXPERIMENT_REGISTERED",
            registration_payload("exp_m1c_bad_scope_migration"),
            event_id="evt_m1c_bad_scope_migration",
        )
        self.projection.apply(registered)
        downgrade_scope_schema(
            self.database,
            experiment_id="exp_m1c_bad_scope_migration",
            evaluation_scope_id=" development ",
        )

        rebuilt = ProjectionStore(self.database)

        self.assertFalse(rebuilt.project_status(PROJECT_ID)["initialized"])
        self.assertEqual(len(list(self.root.glob("state.db.corrupt-*"))), 1)


if __name__ == "__main__":
    unittest.main()
