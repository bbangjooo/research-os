from __future__ import annotations

import hashlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from research_os.errors import IntegrityError
from research_os.kernel._canonical import (
    canonical_bytes,
    sha256_hex,
    strict_json_loads,
)
from research_os.kernel.events import EVENT_VERSION, Event, EventLog
from research_os.kernel.ids import new_experiment_id, stable_id
from research_os.kernel.projection import ProjectionStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "scientific_state" / "v1"
PROJECT_ID = "generation-projection-test"
CANDIDATE_DIGEST = "a" * 64
COMPATIBILITY_DIGEST = "b" * 64
GENERATION_A = "generation_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
GENERATION_B = "generation_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"


def chained_event(
    previous: Event | None,
    event_type: str,
    payload: dict[str, object],
    *,
    event_id: str,
    project_id: str = PROJECT_ID,
) -> Event:
    unsigned = {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2026-08-10T00:00:00.000000Z",
        "payload": payload,
        "prev_hash": previous.hash if previous is not None else None,
        "project_id": project_id,
        "sequence": previous.sequence + 1 if previous is not None else 1,
        "version": EVENT_VERSION,
    }
    return Event.from_mapping(
        {**unsigned, "hash": sha256_hex(canonical_bytes(unsigned))}
    )


def registration_payload(
    experiment_id: str,
    *,
    candidate_digest: str = CANDIDATE_DIGEST,
    generation_id: str | None,
    parent_id: str | None = None,
    attempt: int = 1,
    retry_of: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "experiment_id": experiment_id,
        "candidate_digest": candidate_digest,
        "compatibility_digest": COMPATIBILITY_DIGEST,
        "parent_id": parent_id,
        "attempt": attempt,
        "retry_of": retry_of,
        "status": "registered",
        "authorized_action": None,
    }
    if generation_id is not None:
        payload.update(
            {
                "science_state_version": 1,
                "generation_id": generation_id,
                "study_contract_digest": "c" * 64,
                "evaluation_seal_digest": "d" * 64,
                "budget_debit": {
                    "attempts": 1,
                    "retries": int(retry_of is not None),
                    "reserved_elapsed_milliseconds": 1000,
                    "reserved_cost_microunits": 2500,
                },
            }
        )
    return payload


class GenerationIdentityTests(unittest.TestCase):
    def test_legacy_id_is_exact_and_generation_is_an_orthogonal_axis(self):
        legacy = new_experiment_id(
            "fixture-legacy-v1",
            CANDIDATE_DIGEST,
            compatibility_digest=COMPATIBILITY_DIGEST,
        )
        self.assertEqual(legacy, "exp_9c077608f342414ce35c5dec5d7aa07b")
        self.assertEqual(
            new_experiment_id(
                "fixture-legacy-v1",
                CANDIDATE_DIGEST,
                compatibility_digest=COMPATIBILITY_DIGEST,
                generation_id=None,
            ),
            legacy,
        )

        generation_a = new_experiment_id(
            "fixture-legacy-v1",
            CANDIDATE_DIGEST,
            compatibility_digest=COMPATIBILITY_DIGEST,
            generation_id=GENERATION_A,
        )
        generation_b = new_experiment_id(
            "fixture-legacy-v1",
            CANDIDATE_DIGEST,
            compatibility_digest=COMPATIBILITY_DIGEST,
            generation_id=GENERATION_B,
        )
        self.assertEqual(
            generation_a,
            stable_id(
                "experiment",
                "fixture-legacy-v1",
                GENERATION_A,
                COMPATIBILITY_DIGEST,
                None,
                CANDIDATE_DIGEST,
                1,
            ),
        )
        self.assertEqual(len({legacy, generation_a, generation_b}), 3)


class GenerationProjectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "state.db"
        self.projection = ProjectionStore(self.database)
        self.initialized = chained_event(
            None,
            "PROJECT_INITIALIZED",
            {"project_id": PROJECT_ID, "status": "active"},
            event_id="evt_generation_init",
        )
        self.projection.apply(self.initialized)

    def test_same_candidate_attempt_can_coexist_and_query_by_generation(self):
        experiment_a = new_experiment_id(
            PROJECT_ID,
            CANDIDATE_DIGEST,
            compatibility_digest=COMPATIBILITY_DIGEST,
            generation_id=GENERATION_A,
        )
        experiment_b = new_experiment_id(
            PROJECT_ID,
            CANDIDATE_DIGEST,
            compatibility_digest=COMPATIBILITY_DIGEST,
            generation_id=GENERATION_B,
        )
        registered_a = chained_event(
            self.initialized,
            "EXPERIMENT_REGISTERED",
            registration_payload(experiment_a, generation_id=GENERATION_A),
            event_id="evt_generation_a",
        )
        registered_b = chained_event(
            registered_a,
            "EXPERIMENT_REGISTERED",
            registration_payload(experiment_b, generation_id=GENERATION_B),
            event_id="evt_generation_b",
        )
        self.projection.apply(registered_a)
        self.projection.apply(registered_b)

        self.assertFalse(
            self.projection.candidate_exists(
                PROJECT_ID,
                CANDIDATE_DIGEST,
                None,
                COMPATIBILITY_DIGEST,
            )
        )
        for generation_id, expected_id in (
            (GENERATION_A, experiment_a),
            (GENERATION_B, experiment_b),
        ):
            with self.subTest(generation_id=generation_id):
                self.assertTrue(
                    self.projection.candidate_exists(
                        PROJECT_ID,
                        CANDIDATE_DIGEST,
                        None,
                        COMPATIBILITY_DIGEST,
                        generation_id,
                    )
                )
                attempts = self.projection.candidate_attempts(
                    PROJECT_ID,
                    CANDIDATE_DIGEST,
                    None,
                    COMPATIBILITY_DIGEST,
                    generation_id,
                )
                self.assertEqual(
                    [(row["experiment_id"], row["generation_id"], row["attempt"])
                     for row in attempts],
                    [(expected_id, generation_id, 1)],
                )

    def test_parent_must_belong_to_the_same_generation(self):
        parent_id = new_experiment_id(
            PROJECT_ID,
            CANDIDATE_DIGEST,
            compatibility_digest=COMPATIBILITY_DIGEST,
            generation_id=GENERATION_A,
        )
        parent = chained_event(
            self.initialized,
            "EXPERIMENT_REGISTERED",
            registration_payload(parent_id, generation_id=GENERATION_A),
            event_id="evt_parent_generation_a",
        )
        self.projection.apply(parent)
        child = chained_event(
            parent,
            "EXPERIMENT_REGISTERED",
            registration_payload(
                "exp_cross_generation_child",
                candidate_digest="e" * 64,
                generation_id=GENERATION_B,
                parent_id=parent_id,
            ),
            event_id="evt_cross_generation_child",
        )

        with self.assertRaisesRegex(IntegrityError, "same generation"):
            self.projection.apply(child)
        self.assertEqual(
            self.projection.project_status(PROJECT_ID)["last_sequence"],
            parent.sequence,
        )

    def test_retry_must_belong_to_the_same_generation(self):
        first_id = new_experiment_id(
            PROJECT_ID,
            CANDIDATE_DIGEST,
            compatibility_digest=COMPATIBILITY_DIGEST,
            generation_id=GENERATION_A,
        )
        first = chained_event(
            self.initialized,
            "EXPERIMENT_REGISTERED",
            registration_payload(first_id, generation_id=GENERATION_A),
            event_id="evt_retry_generation_a",
        )
        terminal = chained_event(
            first,
            "EXPERIMENT_TERMINATED",
            {
                "experiment_id": first_id,
                "status": "TIMED_OUT",
                "attempt": 1,
                "retry_of": None,
                "retryable": True,
            },
            event_id="evt_retry_generation_a_terminal",
        )
        self.projection.apply(first)
        self.projection.apply(terminal)
        retry = chained_event(
            terminal,
            "EXPERIMENT_REGISTERED",
            registration_payload(
                "exp_cross_generation_retry",
                generation_id=GENERATION_B,
                attempt=2,
                retry_of=first_id,
            ),
            event_id="evt_cross_generation_retry",
        )

        with self.assertRaisesRegex(IntegrityError, "generation"):
            self.projection.apply(retry)
        self.assertEqual(
            self.projection.project_status(PROJECT_ID)["last_sequence"],
            terminal.sequence,
        )


class LegacyProjectionParityTests(unittest.TestCase):
    def test_fixed_v1_corpus_keeps_bytes_id_status_and_projection_exact(self):
        events_fixture = FIXTURES / "legacy-v1-events.jsonl"
        expected_fixture = FIXTURES / "legacy-v1-projection.json"
        raw_events = events_fixture.read_bytes()
        self.assertEqual(
            hashlib.sha256(raw_events).hexdigest(),
            "b35e9d74a64c729ceea3c5ca66303a7f4e14043129d4e4686741c5939cf178d6",
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            event_path = root / "events.jsonl"
            event_path.write_bytes(raw_events)
            os.chmod(event_path, 0o600)
            event_log = EventLog(event_path, "fixture-legacy-v1")
            projection = ProjectionStore(root / "state.db")

            self.assertTrue(event_log.verify())
            self.assertEqual(projection.rebuild(event_log), 2)
            self.assertEqual(event_path.read_bytes(), raw_events)
            actual = {
                "experiment": projection.experiment(
                    "fixture-legacy-v1",
                    "exp_9c077608f342414ce35c5dec5d7aa07b",
                ),
                "status": projection.project_status("fixture-legacy-v1"),
            }

        expected = strict_json_loads(expected_fixture.read_text(encoding="utf-8"))
        self.assertEqual(actual, expected)
        self.assertNotIn("generation_id", actual["experiment"])
        self.assertNotIn("generation_id", actual["experiment"]["payload"])
        self.assertEqual(
            sha256_hex(canonical_bytes(actual)),
            "9acf4e08a01756d39e4789a7e13f635d891cb426c183abcbfc4793c53d472e88",
        )
        self.assertEqual(
            new_experiment_id(
                "fixture-legacy-v1",
                CANDIDATE_DIGEST,
                compatibility_digest=COMPATIBILITY_DIGEST,
            ),
            actual["experiment"]["experiment_id"],
        )

    def test_existing_pre_generation_schema_migrates_and_backfills_safely(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "state.db"
            projection = ProjectionStore(database)
            initialized = chained_event(
                None,
                "PROJECT_INITIALIZED",
                {"project_id": PROJECT_ID, "status": "active"},
                event_id="evt_migration_init",
            )
            legacy = chained_event(
                initialized,
                "EXPERIMENT_REGISTERED",
                registration_payload(
                    "exp_migration_legacy",
                    candidate_digest="1" * 64,
                    generation_id=None,
                ),
                event_id="evt_migration_legacy",
            )
            versioned = chained_event(
                legacy,
                "EXPERIMENT_REGISTERED",
                registration_payload(
                    "exp_migration_versioned",
                    candidate_digest="2" * 64,
                    generation_id=GENERATION_A,
                ),
                event_id="evt_migration_versioned",
            )
            for event in (initialized, legacy, versioned):
                projection.apply(event)
            legacy_before = projection.experiment(PROJECT_ID, "exp_migration_legacy")

            with sqlite3.connect(database) as connection:
                connection.execute(
                    "DROP INDEX "
                    "experiments_candidate_parent_compatibility_generation_attempt_unique_idx"
                )
                connection.execute("DROP INDEX experiments_candidate_idx")
                connection.execute(
                    "ALTER TABLE experiments DROP COLUMN generation_id"
                )
                connection.execute(
                    "CREATE INDEX experiments_candidate_idx "
                    "ON experiments(project_id, candidate_digest, parent_id)"
                )
                connection.execute(
                    "CREATE UNIQUE INDEX "
                    "experiments_candidate_parent_compatibility_attempt_unique_idx "
                    "ON experiments(project_id, candidate_digest, "
                    "COALESCE(parent_id, ''), compatibility_digest, attempt)"
                )

            migrated = ProjectionStore(database)
            self.assertEqual(
                migrated.experiment(PROJECT_ID, "exp_migration_legacy"),
                legacy_before,
            )
            self.assertEqual(
                migrated.experiment(PROJECT_ID, "exp_migration_versioned")[
                    "generation_id"
                ],
                GENERATION_A,
            )
            self.assertEqual(list(root.glob("state.db.corrupt-*")), [])


if __name__ == "__main__":
    unittest.main()
