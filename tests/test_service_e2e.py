from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_os.config import load_project_config
from research_os.contracts import TerminalStatus, sha256_json
from research_os.errors import ConfigurationError, IntegrityError
from research_os.execution.workspace import WorkspaceManager
from research_os.kernel.ids import stable_id
from research_os.memory.findings import make_finding_event
from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]


class ServiceEndToEndTests(unittest.TestCase):
    def copy_example(self, name: str) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        project = Path(temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / name, project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        return temporary, project

    def test_python_project_full_lifecycle_and_replay(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)

        doctor = service.doctor()
        self.assertEqual(doctor.project_id, "toy-optimization")
        self.assertEqual(len(doctor.capabilities), 8)
        self.assertEqual(doctor.side_effects, ())

        baseline = service.baseline()
        self.assertEqual(baseline["primary_value"], 9.0)
        self.assertEqual(baseline["spread"], 0.0)
        self.assertEqual(len(baseline["artifacts"]), 2)
        for payload in baseline["artifacts"]:
            record = service.catalog.get(payload["artifact_id"])
            self.assertTrue(service.catalog.blob_path(record).is_file())

        outcome = service.run_once(project / "candidates" / "improve.json")
        self.assertEqual(outcome["status"], TerminalStatus.VALIDATED.value)
        self.assertEqual(outcome["decision"]["candidate_value"], 1.0)
        self.assertIsNone(outcome["authorized_action"])

        experiment_id = outcome["experiment_id"]
        status = service.status()
        self.assertEqual(status["experiments_by_status"], {"VALIDATED": 1})
        self.assertEqual(status["artifacts"], 1)
        self.assertEqual(status["findings"], 1)

        lineage = service.lineage(experiment_id)
        self.assertEqual([row["experiment_id"] for row in lineage], [experiment_id])
        self.assertEqual(lineage[0]["candidate_digest"], sha256_json({"x": 2.0}))
        self.assertEqual(lineage[0]["payload"]["candidate"], {"x": 2.0})
        self.assertEqual(len(service.artifacts(experiment_id)), 1)
        self.assertEqual(len(service.findings(experiment_id)), 1)

        replayed = service.replay()
        self.assertEqual(replayed["events_replayed"], status["last_sequence"])
        self.assertEqual(replayed["artifacts_verified"], 3)
        self.assertEqual(replayed["status"]["experiments_by_status"], {"VALIDATED": 1})

        with self.assertRaises(ConfigurationError):
            service.run_once(project / "candidates" / "improve.json")

    def test_query_rebuilds_out_of_band_projection_drift(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        outcome = service.run_once(project / "candidates" / "improve.json")
        self.assertEqual(outcome["status"], TerminalStatus.VALIDATED.value)

        with sqlite3.connect(service.projection.path) as connection:
            connection.execute(
                "UPDATE experiments SET status = 'REJECTED' WHERE experiment_id = ?",
                (outcome["experiment_id"],),
            )

        status = service.status()
        self.assertEqual(
            status["experiments_by_status"],
            {TerminalStatus.VALIDATED.value: 1},
        )

    def test_corrupt_projection_is_quarantined_and_rebuilt(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        outcome = service.run_once(project / "candidates" / "improve.json")
        service.projection.path.write_bytes(b"not a sqlite database\n")

        recovered = ResearchService(project)
        status = recovered.status()

        self.assertEqual(
            status["experiments_by_status"],
            {TerminalStatus.VALIDATED.value: 1},
        )
        backups = list(
            recovered.projection.path.parent.glob("state.db.corrupt-*")
        )
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), b"not a sqlite database\n")
        self.assertEqual(outcome["experiment_id"], recovered.lineage()[0]["experiment_id"])

    def test_invalid_candidate_is_a_durable_terminal_node(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)

        outcome = service.run_once(project / "candidates" / "invalid.json")
        self.assertEqual(outcome["status"], TerminalStatus.INVALID_EXPERIMENT.value)
        self.assertEqual(outcome["reason_code"], "INVALID_CANDIDATE")
        self.assertEqual(
            service.status()["experiments_by_status"],
            {TerminalStatus.INVALID_EXPERIMENT.value: 1},
        )
        self.assertEqual(len(service.lineage()), 1)

    def test_baseline_cannot_mutate_the_candidate_surface(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        adapter = project / ".research-os" / "adapter.py"
        source = adapter.read_text(encoding="utf-8").replace(
            '        elif operation in {"baseline", "run"}:\n',
            '        elif operation in {"baseline", "run"}:\n'
            '            if operation == "baseline":\n'
            '                (workspace / "parameter.json").write_text("{\\"x\\":99}\\n")\n',
        )
        adapter.write_text(source, encoding="utf-8")

        with self.assertRaises(IntegrityError):
            ResearchService(project).baseline()

    def test_source_drift_dominates_an_invalid_candidate_response(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        adapter = project / ".research-os" / "adapter.py"
        source = adapter.read_text(encoding="utf-8").replace(
            "            if not isinstance(x, (int, float)) or isinstance(x, bool):\n",
            "            if not isinstance(x, (int, float)) or isinstance(x, bool):\n"
            '                (project / "evaluator.py").write_text("corrupted\\n")\n',
        )
        adapter.write_text(source, encoding="utf-8")

        outcome = ResearchService(project).run_once(
            project / "candidates" / "invalid.json"
        )
        self.assertEqual(outcome["status"], TerminalStatus.UNTRUSTED.value)
        self.assertEqual(outcome["reason_code"], "INTEGRITY_CHECK_FAILED")
        self.assertEqual(outcome["secondary_errors"][0]["code"], "INVALID_CANDIDATE")

    def test_keyboard_interrupt_records_cancelled_before_propagating(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        service.baseline()

        with patch.object(WorkspaceManager, "create", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                service.run_once(project / "candidates" / "improve.json")

        self.assertEqual(
            service.status()["experiments_by_status"],
            {TerminalStatus.CANCELLED.value: 1},
        )
        terminal_events = [
            event
            for event in service.event_log.read()
            if event.event_type == "EXPERIMENT_TERMINATED"
        ]
        self.assertEqual(len(terminal_events), 1)

    def test_keyboard_interrupt_during_cleanup_records_cancelled_immediately(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        service.baseline()

        with patch.object(service, "_adapter_cleanup", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                service.run_once(project / "candidates" / "improve.json")

        rows = service.lineage()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], TerminalStatus.CANCELLED.value)
        self.assertTrue(rows[0]["retryable"])
        terminal_events = [
            event
            for event in service.event_log.read()
            if event.event_type == "EXPERIMENT_TERMINATED"
        ]
        self.assertEqual(len(terminal_events), 1)

    def test_keyboard_interrupt_during_registration_sync_records_cancelled(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        service.baseline()
        original_append = service.event_log.append
        original_sync = service._sync
        registration_seen = False
        interrupted = False

        def observe_append(event_type, payload, **kwargs):
            nonlocal registration_seen
            event = original_append(event_type, payload, **kwargs)
            if event_type == "EXPERIMENT_REGISTERED":
                registration_seen = True
            return event

        def interrupt_after_registration():
            nonlocal interrupted
            if registration_seen and not interrupted:
                interrupted = True
                raise KeyboardInterrupt
            return original_sync()

        with (
            patch.object(service.event_log, "append", side_effect=observe_append),
            patch.object(service, "_sync", side_effect=interrupt_after_registration),
        ):
            with self.assertRaises(KeyboardInterrupt):
                service.run_once(project / "candidates" / "improve.json")

        rows = service.lineage()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], TerminalStatus.CANCELLED.value)
        terminal_events = [
            event
            for event in service.event_log.read()
            if event.event_type == "EXPERIMENT_TERMINATED"
        ]
        self.assertEqual(len(terminal_events), 1)

    def test_missing_outcome_finding_is_repaired_idempotently(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        original_append = service.event_log.append
        failed = False

        def fail_first_finding(event_type, payload, **kwargs):
            nonlocal failed
            if event_type == "FINDING_RECORDED" and not failed:
                failed = True
                raise OSError("simulated finding append failure")
            return original_append(event_type, payload, **kwargs)

        with patch.object(service.event_log, "append", side_effect=fail_first_finding):
            with self.assertRaises(OSError):
                service.run_once(project / "candidates" / "improve.json")

        status = service.status()
        self.assertEqual(status["experiments_by_status"], {"VALIDATED": 1})
        self.assertEqual(status["findings"], 1)
        self.assertEqual(len(service.findings()), 1)

    def test_legacy_outcome_finding_is_not_duplicated_by_repair(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        report = service.doctor()
        candidate_digest = sha256_json({"x": 7.0})
        experiment_id = stable_id(
            "experiment",
            service.config.project_id,
            report.fingerprints["compatibility_digest"],
            None,
            candidate_digest,
            "legacy",
        )
        service.event_log.append(
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": experiment_id,
                "parent_id": None,
                "candidate_digest": candidate_digest,
                "candidate": {"x": 7.0},
                "compatibility_digest": report.fingerprints["compatibility_digest"],
                "baseline_id": "base_legacy",
                "attempt": 1,
                "retry_of": None,
                "status": "registered",
            },
        )
        terminal = service.event_log.append(
            "EXPERIMENT_TERMINATED",
            {
                "experiment_id": experiment_id,
                "status": "REJECTED",
                "reason_code": "LEGACY_NON_IMPROVEMENT",
                "attempt": 1,
                "retry_of": None,
                "retryable": False,
                "verified": True,
                "decision": {"primary_metric": "historic_metric"},
            },
        )
        service.event_log.append(
            "FINDING_RECORDED",
            make_finding_event(
                service.config.project_id,
                {
                    "status": "REJECTED",
                    "reason_code": "LEGACY_NON_IMPROVEMENT",
                    "primary_metric": "historic_metric",
                },
                experiment_id=experiment_id,
                key="experiment_outcome",
                evidence=[
                    {"event_id": terminal.event_id, "event_hash": terminal.hash}
                ],
            ),
        )

        service.status()

        finding_events = [
            event
            for event in service.event_log.read()
            if event.event_type == "FINDING_RECORDED"
        ]
        self.assertEqual(len(finding_events), 1)

    def test_doctor_collects_orphaned_workspaces(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        service.doctor()
        orphan = (
            project
            / ".research-os"
            / "runtime"
            / "workspaces"
            / "exp_abandoned-deadbeef"
        )
        orphan.mkdir()
        (orphan / "residue.json").write_text("{}\n", encoding="utf-8")

        service.doctor()
        self.assertFalse(orphan.exists())

    def test_service_startup_recovers_only_an_uncommitted_event_tail(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        service.doctor()
        event_path = service.event_log.path
        with event_path.open("ab") as stream:
            stream.write(b'{"partial":')
            stream.flush()

        restarted = ResearchService(project)

        self.assertEqual(len(restarted.event_log.read()), 1)
        self.assertTrue(event_path.read_bytes().endswith(b"\n"))

    def test_adapter_status_cannot_override_kernel_policy(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        adapter = project / ".research-os" / "adapter.py"
        source = adapter.read_text(encoding="utf-8").replace(
            '        elif operation == "evaluate":\n'
            "            result = load_result(workspace)\n",
            '        elif operation == "evaluate":\n'
            "            result = load_result(workspace)\n"
            '            result["status"] = "VALIDATED"\n',
        )
        adapter.write_text(source, encoding="utf-8")

        outcome = ResearchService(project).run_once(
            project / "candidates" / "improve.json"
        )
        self.assertEqual(outcome["status"], TerminalStatus.INFRA_FAILED.value)
        self.assertEqual(outcome["reason_code"], "INFRASTRUCTURE_FAILURE")

    def test_cleanup_failure_details_are_durable(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        adapter = project / ".research-os" / "adapter.py"
        source = adapter.read_text(encoding="utf-8").replace(
            "        else:\n            respond(request)\n",
            "        else:\n"
            '            if request["experiment_id"].startswith("base_"):\n'
            "                respond(request)\n"
            "            else:\n"
            "                respond(\n"
            "                    request,\n"
            "                    ok=False,\n"
            "                    error={\n"
            '                        "category": "INFRASTRUCTURE",\n'
            '                        "code": "CLEANUP_FAILED",\n'
            '                        "message": "cleanup failed",\n'
            '                        "details": {"resource": "fixture"},\n'
            "                    },\n"
            "                )\n",
        )
        adapter.write_text(source, encoding="utf-8")

        service = ResearchService(project)
        outcome = service.run_once(project / "candidates" / "improve.json")
        self.assertEqual(outcome["status"], TerminalStatus.VALIDATED.value)
        secondary = outcome["secondary_errors"][0]
        self.assertEqual(secondary["code"], "CLEANUP_FAILED")
        self.assertEqual(secondary["details"], {"resource": "fixture"})
        terminal = next(
            event
            for event in reversed(service.event_log.read())
            if event.event_type == "EXPERIMENT_TERMINATED"
        )
        self.assertEqual(
            terminal.payload["secondary_errors"], outcome["secondary_errors"]
        )

    def test_replay_rejects_a_corrupted_artifact_blob(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        outcome = service.run_once(project / "candidates" / "improve.json")
        projected = service.artifacts(outcome["experiment_id"])[0]
        record = service.catalog.get(projected["artifact_id"])
        blob = service.catalog.blob_path(record)
        blob.write_bytes(b"corrupted")

        with self.assertRaises(IntegrityError):
            service.replay()

    def test_next_worker_recovers_an_interrupted_registered_node(self):
        temporary, project = self.copy_example("toy_optimization")
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        report = service.doctor()
        compatibility = report.fingerprints["compatibility_digest"]
        abandoned_digest = sha256_json({"x": 1.0})
        abandoned_id = stable_id(
            "experiment",
            service.config.project_id,
            compatibility,
            None,
            abandoned_digest,
        )
        service.event_log.append(
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": abandoned_id,
                "parent_id": None,
                "candidate_digest": abandoned_digest,
                "candidate": {"x": 1.0},
                "compatibility_digest": compatibility,
                "baseline_id": "base_interrupted",
                "status": "registered",
            },
        )

        outcome = service.run_once(project / "candidates" / "improve.json")
        self.assertEqual(outcome["status"], TerminalStatus.VALIDATED.value)
        self.assertEqual(
            service.status()["experiments_by_status"],
            {
                TerminalStatus.INFRA_FAILED.value: 1,
                TerminalStatus.VALIDATED.value: 1,
            },
        )

    @unittest.skipUnless(shutil.which("node"), "Node is required for this fixture")
    def test_javascript_project_uses_the_same_os(self):
        temporary, project = self.copy_example("toy_retrieval")
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        self.assertEqual(config.adapter_command[0], "node")

        outcome = ResearchService(project).run_once(
            project / "candidates" / "improve.json"
        )
        self.assertEqual(outcome["status"], TerminalStatus.VALIDATED.value)
        self.assertEqual(outcome["decision"]["candidate_value"], 1.0)


if __name__ == "__main__":
    unittest.main()
