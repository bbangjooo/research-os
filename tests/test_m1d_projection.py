from __future__ import annotations

import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from research_os.errors import IntegrityError, ScientificStateError
from research_os.kernel._canonical import canonical_bytes, sha256_hex
from research_os.kernel.events import Event, EventLog
from research_os.kernel.projection import ProjectionStore

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "scientific_state"
M1D_ROOT = FIXTURE_ROOT / "v3"
LEGACY_ROOT = FIXTURE_ROOT / "v1"
M1D_PROJECT_ID = "fixture-m1d"
LEGACY_PROJECT_ID = "fixture-legacy-v1"
LEGACY_EXPERIMENT_ID = "exp_9c077608f342414ce35c5dec5d7aa07b"


def _json_fixture(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):  # pragma: no cover - frozen fixture invariant
        raise AssertionError(f"fixture must contain an object: {path}")
    return value


def _supported_diagnosis_history() -> list[dict[str, Any]]:
    terminal_fixture = _json_fixture(M1D_ROOT / "m1d-terminal-corpus.json")
    diagnosis_fixture = _json_fixture(M1D_ROOT / "m1d-diagnosis-valid.json")
    diagnosis_case = next(case for case in diagnosis_fixture["cases"] if case["id"] == "supported")
    terminal_record = next(
        record
        for record in terminal_fixture["records"]
        if record["id"] == diagnosis_case["terminal_record_id"]
    )
    history = copy.deepcopy(terminal_record["canonical_history"])
    history.append(copy.deepcopy(diagnosis_case["diagnosis_event"]))
    return history


def _event_log(path: Path, history: list[dict[str, Any]], project_id: str) -> EventLog:
    encoded = b"".join(
        canonical_bytes(Event.from_mapping(event).to_dict()) + b"\n" for event in history
    )
    path.write_bytes(encoded)
    path.chmod(0o600)
    return EventLog(path, project_id)


def _projection_observation(projection: ProjectionStore, project_id: str) -> dict[str, Any]:
    return {
        "status": projection.project_status(project_id),
        "lineage": projection.lineage(project_id),
        "artifacts": projection.artifacts(project_id),
    }


class M1DProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_direct_apply_rejects_diagnosis_without_full_history(self) -> None:
        history = _supported_diagnosis_history()
        projection = ProjectionStore(self.root / "state.db")
        prefix_log = _event_log(
            self.root / "prefix-events.jsonl",
            history[:-1],
            M1D_PROJECT_ID,
        )
        self.assertEqual(projection.rebuild(prefix_log), len(history) - 1)
        before = _projection_observation(projection, M1D_PROJECT_ID)

        with self.assertRaisesRegex(IntegrityError, "require canonical history"):
            projection.apply(history[-1])

        self.assertEqual(_projection_observation(projection, M1D_PROJECT_ID), before)

    def test_sync_and_rebuild_have_exact_diagnosis_projection_parity(self) -> None:
        history = _supported_diagnosis_history()
        event_log = _event_log(
            self.root / "events.jsonl",
            history,
            M1D_PROJECT_ID,
        )
        observations: dict[str, dict[str, Any]] = {}

        for operation in ("sync", "rebuild"):
            with self.subTest(operation=operation):
                database = self.root / f"{operation}.db"
                projection = ProjectionStore(database)
                self.assertEqual(getattr(projection, operation)(event_log), len(history))
                observations[operation] = _projection_observation(
                    projection,
                    M1D_PROJECT_ID,
                )
                self.assertEqual(
                    observations[operation]["status"]["last_hash"],
                    history[-1]["hash"],
                )
                with sqlite3.connect(database) as connection:
                    tables = {
                        row[0]
                        for row in connection.execute(
                            "SELECT name FROM sqlite_master WHERE type = 'table'"
                        )
                    }
                    projected = connection.execute(
                        "SELECT event_sequence, event_hash FROM projected_events "
                        "WHERE event_id = ?",
                        (history[-1]["event_id"],),
                    ).fetchone()
                self.assertNotIn("diagnoses", tables)
                self.assertNotIn("class_states", tables)
                self.assertEqual(projected, (len(history), history[-1]["hash"]))

        self.assertEqual(observations["sync"], observations["rebuild"])

    def test_corrupt_diagnosis_history_fails_closed_for_sync_and_rebuild(self) -> None:
        valid_history = _supported_diagnosis_history()
        corrupt_history = copy.deepcopy(valid_history)
        corrupt_history[-1]["payload"]["diagnosis"]["recommendation"] = "ship"
        unsigned = {
            key: value for key, value in corrupt_history[-1].items() if key != "hash"
        }
        corrupt_history[-1]["hash"] = sha256_hex(canonical_bytes(unsigned))
        corrupt_log = _event_log(
            self.root / "corrupt-events.jsonl",
            corrupt_history,
            M1D_PROJECT_ID,
        )
        self.assertTrue(corrupt_log.verify())

        for operation in ("sync", "rebuild"):
            with self.subTest(operation=operation):
                operation_root = self.root / operation
                operation_root.mkdir()
                projection = ProjectionStore(operation_root / "state.db")
                prefix_log = _event_log(
                    operation_root / "prefix-events.jsonl",
                    valid_history[:-1],
                    M1D_PROJECT_ID,
                )
                projection.rebuild(prefix_log)
                before = _projection_observation(projection, M1D_PROJECT_ID)

                with self.assertRaises(ScientificStateError) as caught:
                    getattr(projection, operation)(corrupt_log)

                self.assertEqual(caught.exception.code, "DIAGNOSIS_INVALID")
                self.assertEqual(_projection_observation(projection, M1D_PROJECT_ID), before)
                self.assertEqual(list(operation_root.glob("state.db.corrupt-*")), [])

    def test_legacy_v1_bytes_head_projection_and_query_shapes_are_exact(self) -> None:
        source = LEGACY_ROOT / "legacy-v1-events.jsonl"
        event_path = self.root / "legacy-v1-events.jsonl"
        event_path.write_bytes(source.read_bytes())
        event_path.chmod(0o600)
        event_log = EventLog(event_path, LEGACY_PROJECT_ID)
        original_bytes = event_path.read_bytes()
        original_head = event_log.head()
        expected = _json_fixture(LEGACY_ROOT / "legacy-v1-projection.json")
        projection = ProjectionStore(self.root / "legacy-state.db")

        self.assertEqual(projection.rebuild(event_log), 2)

        self.assertEqual(event_path.read_bytes(), original_bytes)
        self.assertEqual(event_log.head(), original_head)
        self.assertEqual(projection.project_status(LEGACY_PROJECT_ID), expected["status"])
        experiment = projection.experiment(LEGACY_PROJECT_ID, LEGACY_EXPERIMENT_ID)
        self.assertEqual(experiment, expected["experiment"])
        self.assertEqual(projection.lineage(LEGACY_PROJECT_ID), [expected["experiment"]])


if __name__ == "__main__":
    unittest.main()
