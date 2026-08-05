from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_os.contracts import (
    Operation,
    ProtocolResponse,
    TerminalStatus,
    sha256_json,
)
from research_os.errors import ConfigurationError, IntegrityError
from research_os.execution.workspace import WorkspaceManager
from research_os.kernel._canonical import canonical_bytes, sha256_hex
from research_os.kernel.events import EVENT_VERSION, Event
from research_os.kernel.ids import new_experiment_id
from research_os.kernel.projection import ProjectionStore
from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]


def _chained_event(
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
        "project_id": "retry-test",
        "sequence": previous.sequence + 1 if previous is not None else 1,
        "version": EVENT_VERSION,
    }
    return Event.from_mapping(
        {**unsigned, "hash": sha256_hex(canonical_bytes(unsigned))}
    )


class RetryServiceTests(unittest.TestCase):
    def copy_example(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        project = Path(temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        return temporary, project

    @staticmethod
    def adapter_failure(*, retryable: bool) -> ProtocolResponse:
        return ProtocolResponse.failure(
            request_id="req_injected_failure",
            error={
                "category": "INFRASTRUCTURE",
                "code": "TRANSIENT_EVALUATOR_FAILURE",
                "message": "injected adapter failure",
            },
            retryable=retryable,
        )

    def test_retryable_adapter_failure_requires_explicit_attempt_and_replays(self):
        temporary, project = self.copy_example()
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        service.baseline()
        original_call = service._call_sealed
        failed = False

        def fail_first_run(report, operation, **kwargs):
            nonlocal failed
            if operation is Operation.RUN and not failed:
                failed = True
                return self.adapter_failure(retryable=True)
            return original_call(report, operation, **kwargs)

        with patch.object(service, "_call_sealed", side_effect=fail_first_run):
            first = service.run_once(project / "candidates" / "improve.json")

        self.assertEqual(first["status"], TerminalStatus.INFRA_FAILED.value)
        self.assertEqual(first["attempt"], 1)
        self.assertIsNone(first["retry_of"])
        self.assertTrue(first["retryable"])

        with self.assertRaisesRegex(ConfigurationError, "duplicate evidence"):
            service.run_once(project / "candidates" / "improve.json")

        second = service.run_once(
            project / "candidates" / "improve.json",
            retry_of=first["experiment_id"],
        )
        self.assertEqual(second["status"], TerminalStatus.VALIDATED.value)
        self.assertEqual(second["attempt"], 2)
        self.assertEqual(second["retry_of"], first["experiment_id"])
        self.assertFalse(second["retryable"])

        attempts = service.projection.candidate_attempts(
            service.config.project_id,
            sha256_json({"x": 2.0}),
            None,
            attempts_compatibility := str(
                service.projection.experiment(
                    service.config.project_id, first["experiment_id"]
                )["compatibility_digest"]
            ),
        )
        self.assertEqual([row["attempt"] for row in attempts], [1, 2])
        self.assertEqual(
            [row["retry_of"] for row in attempts],
            [None, first["experiment_id"]],
        )
        self.assertEqual(
            first["experiment_id"],
            new_experiment_id(
                service.config.project_id,
                sha256_json({"x": 2.0}),
                compatibility_digest=attempts_compatibility,
                attempt=1,
            ),
        )
        self.assertEqual(
            second["experiment_id"],
            new_experiment_id(
                service.config.project_id,
                sha256_json({"x": 2.0}),
                compatibility_digest=attempts_compatibility,
                attempt=2,
            ),
        )

        before_replay = [
            (
                row["experiment_id"],
                row["attempt"],
                row["retry_of"],
                row["retryable"],
                row["status"],
            )
            for row in attempts
        ]
        service.replay()
        after_replay = service.projection.candidate_attempts(
            service.config.project_id,
            sha256_json({"x": 2.0}),
            None,
            attempts_compatibility,
        )
        self.assertEqual(
            before_replay,
            [
                (
                    row["experiment_id"],
                    row["attempt"],
                    row["retry_of"],
                    row["retryable"],
                    row["status"],
                )
                for row in after_replay
            ],
        )
        with self.assertRaisesRegex(ConfigurationError, "most recent"):
            service.run_once(
                project / "candidates" / "improve.json",
                retry_of=first["experiment_id"],
            )

    def test_nonretryable_adapter_failure_cannot_be_retried(self):
        temporary, project = self.copy_example()
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        service.baseline()
        original_call = service._call_sealed
        failed = False

        def fail_first_run(report, operation, **kwargs):
            nonlocal failed
            if operation is Operation.RUN and not failed:
                failed = True
                return self.adapter_failure(retryable=False)
            return original_call(report, operation, **kwargs)

        with patch.object(service, "_call_sealed", side_effect=fail_first_run):
            first = service.run_once(project / "candidates" / "improve.json")

        self.assertEqual(first["status"], TerminalStatus.INFRA_FAILED.value)
        self.assertFalse(first["retryable"])
        with self.assertRaisesRegex(ConfigurationError, "retryable terminal"):
            service.run_once(
                project / "candidates" / "improve.json",
                retry_of=first["experiment_id"],
            )

    def test_retryable_insufficient_evidence_adapter_failure_can_be_retried(self):
        temporary, project = self.copy_example()
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        service.baseline()
        original_call = service._call_sealed
        failed = False

        def fail_first_evaluate(report, operation, **kwargs):
            nonlocal failed
            if operation is Operation.EVALUATE and not failed:
                failed = True
                return ProtocolResponse.failure(
                    request_id="req_injected_evidence_failure",
                    error={
                        "category": "INSUFFICIENT_EVIDENCE",
                        "code": "EVIDENCE_TEMPORARILY_UNAVAILABLE",
                        "message": "injected evidence failure",
                    },
                    retryable=True,
                )
            return original_call(report, operation, **kwargs)

        with patch.object(service, "_call_sealed", side_effect=fail_first_evaluate):
            first = service.run_once(project / "candidates" / "improve.json")

        self.assertEqual(
            first["status"], TerminalStatus.INSUFFICIENT_EVIDENCE.value
        )
        self.assertTrue(first["retryable"])
        retry = service.run_once(
            project / "candidates" / "improve.json",
            retry_of=first["experiment_id"],
        )
        self.assertEqual(retry["status"], TerminalStatus.VALIDATED.value)
        self.assertEqual(retry["attempt"], 2)

    def test_retry_decision_rebuilds_a_tampered_projection(self):
        temporary, project = self.copy_example()
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        service.baseline()
        original_call = service._call_sealed
        failed = False

        def fail_first_run(report, operation, **kwargs):
            nonlocal failed
            if operation is Operation.RUN and not failed:
                failed = True
                return self.adapter_failure(retryable=False)
            return original_call(report, operation, **kwargs)

        with patch.object(service, "_call_sealed", side_effect=fail_first_run):
            first = service.run_once(project / "candidates" / "improve.json")

        with sqlite3.connect(service.projection.path) as connection:
            connection.execute(
                "UPDATE experiments SET retryable = 1 WHERE experiment_id = ?",
                (first["experiment_id"],),
            )

        with self.assertRaisesRegex(ConfigurationError, "retryable terminal"):
            service.run_once(
                project / "candidates" / "improve.json",
                retry_of=first["experiment_id"],
            )
        projected = service.projection.experiment(
            service.config.project_id, first["experiment_id"]
        )
        self.assertFalse(projected["retryable"])
        self.assertEqual(len(service.lineage()), 1)

    def test_timeout_and_cancelled_attempts_are_retryable(self):
        for failure, expected in (
            (TimeoutError("injected timeout"), TerminalStatus.TIMED_OUT),
            (KeyboardInterrupt(), TerminalStatus.CANCELLED),
        ):
            with self.subTest(status=expected.value):
                temporary, project = self.copy_example()
                self.addCleanup(temporary.cleanup)
                service = ResearchService(project)
                service.baseline()
                with patch.object(WorkspaceManager, "create", side_effect=failure):
                    if expected is TerminalStatus.CANCELLED:
                        with self.assertRaises(KeyboardInterrupt):
                            service.run_once(
                                project / "candidates" / "improve.json"
                            )
                    else:
                        outcome = service.run_once(
                            project / "candidates" / "improve.json"
                        )
                        self.assertEqual(outcome["status"], expected.value)

                first = service.lineage()[0]
                self.assertEqual(first["status"], expected.value)
                self.assertTrue(first["retryable"])
                retry = service.run_once(
                    project / "candidates" / "improve.json",
                    retry_of=first["experiment_id"],
                )
                self.assertEqual(retry["attempt"], 2)
                self.assertEqual(retry["status"], TerminalStatus.VALIDATED.value)
                service.replay()
                self.assertEqual(
                    [row["attempt"] for row in service.lineage()], [1, 2]
                )

    def test_recovered_interruption_is_an_explicit_retry_source(self):
        temporary, project = self.copy_example()
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        baseline = service.baseline()
        compatibility = str(baseline["compatibility_digest"])
        candidate_digest = sha256_json({"x": 2.0})
        abandoned_id = new_experiment_id(
            service.config.project_id,
            candidate_digest,
            compatibility_digest=compatibility,
            attempt=1,
        )
        service.event_log.append(
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": abandoned_id,
                "parent_id": None,
                "candidate_digest": candidate_digest,
                "candidate": {"x": 2.0},
                "compatibility_digest": compatibility,
                "baseline_id": baseline["baseline_id"],
                "attempt": 1,
                "retry_of": None,
                "status": "registered",
            },
        )

        retry = service.run_once(
            project / "candidates" / "improve.json", retry_of=abandoned_id
        )
        attempts = service.projection.candidate_attempts(
            service.config.project_id,
            candidate_digest,
            None,
            compatibility,
        )
        self.assertEqual([row["attempt"] for row in attempts], [1, 2])
        self.assertEqual(
            attempts[0]["payload"]["outcome"]["reason_code"],
            "RECOVERED_INTERRUPTED_RUN",
        )
        self.assertTrue(attempts[0]["retryable"])
        self.assertEqual(retry["retry_of"], abandoned_id)
        self.assertEqual(retry["status"], TerminalStatus.VALIDATED.value)
        service.replay()
        self.assertEqual(
            [row["attempt"] for row in service.lineage()], [1, 2]
        )


class RetryProjectionTests(unittest.TestCase):
    def projection(self) -> tuple[tempfile.TemporaryDirectory[str], ProjectionStore]:
        temporary = tempfile.TemporaryDirectory()
        return temporary, ProjectionStore(Path(temporary.name) / "state.db")

    def test_projection_refuses_prohibited_and_nonretryable_outcomes(self):
        for index, status in enumerate(
            (
                "INVALID_EXPERIMENT",
                "REJECTED",
                "VALIDATED",
                "UNTRUSTED",
                "INFRA_FAILED",
            )
        ):
            with self.subTest(status=status):
                temporary, projection = self.projection()
                self.addCleanup(temporary.cleanup)
                initialized = _chained_event(
                    None,
                    "PROJECT_INITIALIZED",
                    {},
                    event_id=f"evt_init_{index}",
                )
                registered = _chained_event(
                    initialized,
                    "EXPERIMENT_REGISTERED",
                    {
                        "experiment_id": "exp_attempt_1",
                        "candidate_digest": "candidate-digest",
                        "compatibility_digest": "compatibility-digest",
                        "attempt": 1,
                        "retry_of": None,
                    },
                    event_id=f"evt_registered_{index}",
                )
                terminated = _chained_event(
                    registered,
                    "EXPERIMENT_TERMINATED",
                    {
                        "experiment_id": "exp_attempt_1",
                        "status": status,
                        "attempt": 1,
                        "retry_of": None,
                        "retryable": False,
                    },
                    event_id=f"evt_terminated_{index}",
                )
                retry = _chained_event(
                    terminated,
                    "EXPERIMENT_REGISTERED",
                    {
                        "experiment_id": "exp_attempt_2",
                        "candidate_digest": "candidate-digest",
                        "compatibility_digest": "compatibility-digest",
                        "attempt": 2,
                        "retry_of": "exp_attempt_1",
                    },
                    event_id=f"evt_retry_{index}",
                )
                for event in (initialized, registered, terminated):
                    projection.apply(event)
                with self.assertRaisesRegex(IntegrityError, "terminal retryable"):
                    projection.apply(retry)

    def test_projection_validates_retry_lineage_and_most_recent_attempt(self):
        temporary, projection = self.projection()
        self.addCleanup(temporary.cleanup)
        initialized = _chained_event(
            None, "PROJECT_INITIALIZED", {}, event_id="evt_init"
        )
        registered = _chained_event(
            initialized,
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": "exp_attempt_1",
                "candidate_digest": "candidate-digest",
                "compatibility_digest": "compatibility-digest",
                "attempt": 1,
                "retry_of": None,
            },
            event_id="evt_registered_1",
        )
        terminated = _chained_event(
            registered,
            "EXPERIMENT_TERMINATED",
            {
                "experiment_id": "exp_attempt_1",
                "status": "TIMED_OUT",
                "attempt": 1,
                "retry_of": None,
                "retryable": True,
            },
            event_id="evt_terminated_1",
        )
        wrong_identity = _chained_event(
            terminated,
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": "exp_wrong_identity",
                "candidate_digest": "different-candidate",
                "compatibility_digest": "compatibility-digest",
                "attempt": 2,
                "retry_of": "exp_attempt_1",
            },
            event_id="evt_wrong_identity",
        )
        for event in (initialized, registered, terminated):
            projection.apply(event)
        with self.assertRaisesRegex(IntegrityError, "same candidate"):
            projection.apply(wrong_identity)

        retry = _chained_event(
            terminated,
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": "exp_attempt_2",
                "candidate_digest": "candidate-digest",
                "compatibility_digest": "compatibility-digest",
                "attempt": 2,
                "retry_of": "exp_attempt_1",
            },
            event_id="evt_registered_2",
        )
        projection.apply(retry)
        terminated_retry = _chained_event(
            retry,
            "EXPERIMENT_TERMINATED",
            {
                "experiment_id": "exp_attempt_2",
                "status": "TIMED_OUT",
                "attempt": 2,
                "retry_of": "exp_attempt_1",
                "retryable": True,
            },
            event_id="evt_terminated_2",
        )
        projection.apply(terminated_retry)
        stale_retry = _chained_event(
            terminated_retry,
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": "exp_stale_retry",
                "candidate_digest": "candidate-digest",
                "compatibility_digest": "compatibility-digest",
                "attempt": 2,
                "retry_of": "exp_attempt_1",
            },
            event_id="evt_stale_retry",
        )
        with self.assertRaisesRegex(IntegrityError, "most recent"):
            projection.apply(stale_retry)

        third = _chained_event(
            terminated_retry,
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": "exp_attempt_3",
                "candidate_digest": "candidate-digest",
                "compatibility_digest": "compatibility-digest",
                "attempt": 3,
                "retry_of": "exp_attempt_2",
            },
            event_id="evt_registered_3",
        )
        projection.apply(third)
        self.assertEqual(
            [
                row["attempt"]
                for row in projection.candidate_attempts(
                    "retry-test",
                    "candidate-digest",
                    None,
                    "compatibility-digest",
                )
            ],
            [1, 2, 3],
        )

    def test_projection_rejects_forged_retryable_metadata(self):
        temporary, projection = self.projection()
        self.addCleanup(temporary.cleanup)
        initialized = _chained_event(
            None, "PROJECT_INITIALIZED", {}, event_id="evt_init_forged"
        )
        registered = _chained_event(
            initialized,
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": "exp_forged",
                "candidate_digest": "candidate-digest",
                "compatibility_digest": "compatibility-digest",
            },
            event_id="evt_registered_forged",
        )
        forged = _chained_event(
            registered,
            "EXPERIMENT_TERMINATED",
            {
                "experiment_id": "exp_forged",
                "status": "INFRA_FAILED",
                "retryable": True,
            },
            event_id="evt_terminated_forged",
        )
        projection.apply(initialized)
        projection.apply(registered)
        with self.assertRaisesRegex(IntegrityError, "conflicts"):
            projection.apply(forged)

    def test_projection_requires_failed_stage_for_adapter_retry_evidence(self):
        temporary, projection = self.projection()
        self.addCleanup(temporary.cleanup)
        initialized = _chained_event(
            None, "PROJECT_INITIALIZED", {}, event_id="evt_init_nested"
        )
        registered = _chained_event(
            initialized,
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": "exp_nested",
                "candidate_digest": "candidate-digest",
                "compatibility_digest": "compatibility-digest",
            },
            event_id="evt_registered_nested",
        )
        forged = _chained_event(
            registered,
            "EXPERIMENT_TERMINATED",
            {
                "experiment_id": "exp_nested",
                "status": "INFRA_FAILED",
                "reason_code": "TRANSIENT_FAILURE",
                "retryable": True,
                "error": {
                    "type": "AdapterOperationError",
                    "category": "INFRASTRUCTURE",
                    "code": "TRANSIENT_FAILURE",
                    "retryable": True,
                },
            },
            event_id="evt_terminated_nested",
        )
        projection.apply(initialized)
        projection.apply(registered)
        with self.assertRaisesRegex(IntegrityError, "matching failed adapter stage"):
            projection.apply(forged)

    def test_legacy_status_transition_migration_preserves_timeout_retryability(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "state.db"
        with sqlite3.connect(path) as connection:
            connection.execute(
                """
                CREATE TABLE experiments (
                    experiment_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    parent_id TEXT,
                    candidate_digest TEXT NOT NULL,
                    compatibility_digest TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    terminated_at TEXT,
                    created_sequence INTEGER NOT NULL UNIQUE,
                    updated_sequence INTEGER NOT NULL
                )
                """
            )
            payload = canonical_bytes(
                {
                    "experiment_id": "exp_legacy_timeout",
                    "latest_transition": {"status": "TIMED_OUT"},
                }
            ).decode("utf-8")
            connection.execute(
                "INSERT INTO experiments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "exp_legacy_timeout",
                    "retry-test",
                    None,
                    "candidate-digest",
                    "compatibility-digest",
                    "TIMED_OUT",
                    payload,
                    "2026-08-04T00:00:00Z",
                    "2026-08-04T00:00:01Z",
                    1,
                    2,
                ),
            )

        projection = ProjectionStore(path)
        row = projection.experiment("retry-test", "exp_legacy_timeout")
        self.assertEqual(row["attempt"], 1)
        self.assertTrue(row["retryable"])


if __name__ == "__main__":
    unittest.main()
