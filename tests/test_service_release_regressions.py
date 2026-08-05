from __future__ import annotations

import hashlib
import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from research_os.cli import main as cli_main
from research_os.contracts import Operation, ProtocolResponse, canonical_json, sha256_json
from research_os.errors import ConfigurationError, IntegrityError, ProtocolError
from research_os.execution.workspace import WorkspaceManager
from research_os.kernel.ids import new_experiment_id
from research_os.memory.findings import make_finding_event, record_finding
from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]


class ServiceReleaseRegressionTests(unittest.TestCase):
    def copy_optimization(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        return project

    @staticmethod
    def event_types(service: ResearchService) -> list[str]:
        return [event.event_type for event in service.event_log.read()]

    def leave_evaluated_orphan(
        self,
        project: Path,
        *,
        stage_event_type: str = "STAGE_COMPLETED",
        stage_field: str = "stage",
    ) -> tuple[Path, str, str]:
        """Leave exact evaluated output plus only its durable pre-capture evidence."""

        service = ResearchService(project)
        baseline = service.baseline()
        report = service.doctor()
        candidate = {"x": 2.0}
        candidate_digest = sha256_json(candidate)
        compatibility = str(report.fingerprints["compatibility_digest"])
        experiment_id = new_experiment_id(
            service.config.project_id,
            candidate_digest,
            compatibility_digest=compatibility,
        )
        service.event_log.append(
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": experiment_id,
                "parent_id": None,
                "candidate_digest": candidate_digest,
                "candidate": candidate,
                "compatibility_digest": compatibility,
                "source_tree_digest": report.fingerprints["source_tree_digest"],
                "baseline_id": baseline["baseline_id"],
                "primary_metric": baseline["primary_metric"],
                "attempt": 1,
                "retry_of": None,
                "status": "registered",
                "authorized_action": None,
            },
        )

        manager = WorkspaceManager(service.config)
        handle = manager.create(experiment_id)
        materialize_input = {
            "candidate": candidate,
            "candidate_digest": candidate_digest,
        }
        materialized = service.adapter.call(
            Operation.MATERIALIZE,
            payload=materialize_input,
            workspace=handle.path,
            experiment_id=experiment_id,
        )
        self.assertTrue(materialized.ok)
        ran = service.adapter.call(
            Operation.RUN,
            payload={
                "candidate_digest": candidate_digest,
                "baseline_id": baseline["baseline_id"],
            },
            workspace=handle.path,
            experiment_id=experiment_id,
        )
        self.assertTrue(ran.ok)
        evaluate_input = {"candidate_digest": candidate_digest}
        evaluated = service.adapter.call(
            Operation.EVALUATE,
            payload=evaluate_input,
            workspace=handle.path,
            experiment_id=experiment_id,
        )
        self.assertTrue(evaluated.ok)

        # Bind recovery to the exact bytes that existed when evaluation
        # succeeded. This models an evaluator that supplies optional capture
        # metadata in its durable ArtifactRef.
        artifact_path = handle.path / "outputs" / "result.json"
        artifact_bytes = artifact_path.read_bytes()
        artifact_digest = hashlib.sha256(artifact_bytes).hexdigest()
        evaluate_wire = evaluated.to_dict()
        payload = evaluate_wire.get("payload")
        if not isinstance(payload, dict):
            self.fail("evaluate response payload is not an object")
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list) or len(artifacts) != 1:
            self.fail("evaluate response does not declare exactly one artifact")
        artifact = artifacts[0]
        if not isinstance(artifact, dict):
            self.fail("evaluate artifact reference is not an object")
        artifact["sha256"] = artifact_digest
        artifact["size_bytes"] = len(artifact_bytes)
        sealed_evaluation = ProtocolResponse.from_dict(evaluate_wire)
        service.event_log.append(
            stage_event_type,
            {
                "experiment_id": experiment_id,
                stage_field: Operation.EVALUATE.value,
                "status": "completed",
                "input_digest": sha256_json(evaluate_input),
                "output_digest": sha256_json(sealed_evaluation.to_dict()),
                "response": sealed_evaluation.to_dict(),
            },
        )
        manager.detach(handle)
        manager.close()
        self.assertTrue(handle.path.is_dir())
        return handle.path, experiment_id, artifact_digest

    def test_cached_service_rejects_semantic_constitution_change(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        service.doctor()
        event_count = len(service.event_log.read())
        constitution = project / ".research-os" / "constitution.toml"
        original = constitution.read_text(encoding="utf-8")
        changed = original.replace(
            "minimum_improvement = 0.0",
            "minimum_improvement = 0.5",
        )
        self.assertNotEqual(changed, original)
        constitution.write_text(changed, encoding="utf-8")

        with self.assertRaisesRegex(IntegrityError, "configuration changed"):
            service.status()

        self.assertEqual(len(service.event_log.read()), event_count)

    def test_mutable_source_change_rotates_compatibility_and_baseline(self):
        project = self.copy_optimization()
        service = ResearchService(project)

        first = service.baseline()
        (project / "parameter.json").write_text('{"x": 1.0}\n', encoding="utf-8")
        second = service.baseline()

        self.assertEqual(first["primary_value"], 9.0)
        self.assertEqual(second["primary_value"], 4.0)
        self.assertNotEqual(first["compatibility_digest"], second["compatibility_digest"])
        self.assertNotEqual(first["baseline_id"], second["baseline_id"])
        self.assertEqual(service.status()["baselines"], 2)

    def test_cli_repeat_mismatch_records_no_baseline(self):
        project = self.copy_optimization()
        stdout = io.StringIO()
        stderr = io.StringIO()

        with redirect_stdout(stdout), redirect_stderr(stderr):
            return_code = cli_main(
                [
                    "--project",
                    str(project),
                    "baseline",
                    "--repeats",
                    "1",
                ]
            )

        self.assertEqual(return_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        error = json.loads(stderr.getvalue())
        self.assertIn("constitution repetition count", error["error"]["message"])
        service = ResearchService(project)
        self.assertNotIn("BASELINE_RECORDED", self.event_types(service))
        self.assertEqual(service.status()["baselines"], 0)

    def test_unreadable_candidates_do_not_create_a_baseline(self):
        for case in ("missing", "malformed"):
            with self.subTest(case=case):
                project = self.copy_optimization()
                candidate = project / "candidates" / f"{case}.json"
                if case == "malformed":
                    candidate.write_text('{"x":', encoding="utf-8")
                service = ResearchService(project)

                with self.assertRaises(ConfigurationError):
                    service.run_once(candidate)

                types = self.event_types(service)
                self.assertNotIn("BASELINE_RECORDED", types)
                self.assertNotIn("EXPERIMENT_REGISTERED", types)

    def test_exact_captured_at_manifest_tampering_is_rejected(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        outcome = service.run_once(project / "candidates" / "improve.json")
        projected = service.artifacts(outcome["experiment_id"])[0]
        artifact_id = projected["artifact_id"]
        manifest = service.catalog.record_root / f"{artifact_id}.json"
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        original_timestamp = payload["captured_at"]
        payload["captured_at"] = "2000-01-01T00:00:00Z"
        self.assertNotEqual(payload["captured_at"], original_timestamp)
        manifest.write_text(canonical_json(payload) + "\n", encoding="utf-8")

        with self.assertRaisesRegex(IntegrityError, "manifest"):
            service.artifacts(outcome["experiment_id"])
        with self.assertRaisesRegex(IntegrityError, "manifest"):
            service.replay()

    def test_generic_finding_writer_rejects_reserved_outcome_key(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        service.doctor()
        event_count = len(service.event_log.read())

        with self.assertRaisesRegex(ValueError, "reserved"):
            record_finding(
                service.event_log,
                {"status": "forged"},
                key="experiment_outcome",
            )

        self.assertEqual(len(service.event_log.read()), event_count)

    def test_forged_outcome_finding_is_rejected(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        outcome = service.run_once(project / "candidates" / "improve.json")
        service.event_log.append(
            "FINDING_RECORDED",
            make_finding_event(
                service.config.project_id,
                {
                    "status": outcome["status"],
                    "reason_code": outcome["reason_code"],
                    "primary_metric": service.config.primary_metric,
                },
                experiment_id=outcome["experiment_id"],
                key="experiment_outcome",
                evidence=[
                    {
                        "event_id": "evt_nonexistent",
                        "event_hash": "0" * 64,
                    }
                ],
            ),
        )

        with self.assertRaisesRegex(IntegrityError, "references no terminal"):
            service.status()

    def test_duplicate_outcome_finding_is_rejected(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        service.run_once(project / "candidates" / "improve.json")
        outcome_finding = next(
            event
            for event in service.event_log.read()
            if event.event_type == "FINDING_RECORDED"
            and event.payload.get("key") == "experiment_outcome"
        )
        service.event_log.append("FINDING_RECORDED", outcome_finding.payload)

        with self.assertRaisesRegex(IntegrityError, "duplicate|UNIQUE"):
            service.replay()

    def test_doctor_event_count_includes_recovery_events(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        initial = service.doctor()
        candidate = {"x": 1.5}
        candidate_digest = sha256_json(candidate)
        compatibility = str(initial.fingerprints["compatibility_digest"])
        experiment_id = new_experiment_id(
            service.config.project_id,
            candidate_digest,
            compatibility_digest=compatibility,
        )
        service.event_log.append(
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": experiment_id,
                "parent_id": None,
                "candidate_digest": candidate_digest,
                "candidate": candidate,
                "compatibility_digest": compatibility,
                "baseline_id": "base_interrupted",
                "primary_metric": service.config.primary_metric,
                "attempt": 1,
                "retry_of": None,
                "status": "registered",
                "authorized_action": None,
            },
        )

        recovered_report = service.doctor()

        self.assertEqual(recovered_report.event_count, len(service.event_log.read()))
        self.assertEqual(
            recovered_report.event_count,
            service.status()["last_sequence"],
        )

    def test_recovery_captures_evaluated_artifact_before_terminal(self):
        project = self.copy_optimization()
        orphan, experiment_id, artifact_digest = self.leave_evaluated_orphan(project)

        restarted = ResearchService(project)
        status = restarted.status()

        self.assertEqual(status["experiments_by_status"], {"INFRA_FAILED": 1})
        self.assertEqual(status["artifacts"], 1)
        self.assertFalse(orphan.exists())
        records = restarted.artifacts(experiment_id)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["digest"], artifact_digest)
        events = restarted.event_log.read()
        artifact_event = next(
            event
            for event in events
            if event.event_type == "ARTIFACT_RECORDED"
            and event.payload.get("experiment_id") == experiment_id
        )
        terminal_event = next(
            event
            for event in events
            if event.event_type == "EXPERIMENT_TERMINATED"
            and event.payload.get("experiment_id") == experiment_id
        )
        self.assertLess(artifact_event.sequence, terminal_event.sequence)
        self.assertEqual(terminal_event.payload["status"], "INFRA_FAILED")
        self.assertEqual(
            terminal_event.payload["reason_code"],
            "RECOVERED_INTERRUPTED_RUN",
        )
        replayed = restarted.replay()
        self.assertEqual(replayed["events_replayed"], len(restarted.event_log.read()))

    def test_recovery_marks_tampered_artifact_untrusted_and_preserves_workspace(self):
        project = self.copy_optimization()
        orphan, experiment_id, _ = self.leave_evaluated_orphan(project)
        (orphan / "outputs" / "result.json").write_text(
            '{"tampered":true}\n',
            encoding="utf-8",
        )

        restarted = ResearchService(project)
        status = restarted.status()

        self.assertTrue(orphan.is_dir())
        self.assertEqual(status["experiments_by_status"], {"UNTRUSTED": 1})
        experiment_events = [
            event
            for event in restarted.event_log.read()
            if event.payload.get("experiment_id") == experiment_id
        ]
        self.assertFalse(
            any(event.event_type == "ARTIFACT_RECORDED" for event in experiment_events)
        )
        terminal = next(
            event
            for event in experiment_events
            if event.event_type == "EXPERIMENT_TERMINATED"
        )
        self.assertEqual(terminal.payload["status"], "UNTRUSTED")
        self.assertTrue(terminal.payload["preserve_workspace"])
        self.assertEqual(
            terminal.payload["reason_code"],
            "INTERRUPTED_EVIDENCE_UNTRUSTED",
        )
        # Preservation is durable across fresh manager instances and queries.
        self.assertEqual(restarted.status()["experiments_by_status"], {"UNTRUSTED": 1})
        self.assertTrue(orphan.is_dir())

    def test_cancellation_after_evaluate_seals_artifacts_before_cleanup(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        service.baseline()
        original_verify = WorkspaceManager.verify
        interrupted = False

        def interrupt_after_evidence_verify(manager, handle, *args, **kwargs):
            nonlocal interrupted
            result = original_verify(manager, handle, *args, **kwargs)
            allowed = kwargs.get("allowed_outputs", args[0] if args else ())
            if allowed and handle.experiment_id.startswith("exp_") and not interrupted:
                interrupted = True
                raise KeyboardInterrupt
            return result

        with patch.object(
            WorkspaceManager,
            "verify",
            new=interrupt_after_evidence_verify,
        ):
            with self.assertRaises(KeyboardInterrupt):
                service.run_once(project / "candidates" / "improve.json")

        row = service.lineage()[0]
        self.assertEqual(row["status"], "CANCELLED")
        self.assertEqual(len(service.artifacts(row["experiment_id"])), 1)
        workspaces = project / ".research-os" / "runtime" / "workspaces"
        self.assertEqual(list(workspaces.iterdir()), [])
        self.assertEqual(service.replay()["artifacts_verified"], 3)

    def test_recovery_accepts_legacy_stage_and_artifact_event_aliases(self):
        project = self.copy_optimization()
        orphan, experiment_id, _ = self.leave_evaluated_orphan(
            project,
            stage_event_type="ADAPTER_STAGE_RECORDED",
            stage_field="stage_name",
        )
        service = ResearchService(project)
        evaluate_event = next(
            event
            for event in service.event_log.read()
            if event.event_type == "ADAPTER_STAGE_RECORDED"
        )
        response = ProtocolResponse.from_mapping(evaluate_event.payload["response"])
        result = response.result_envelope()
        records = service.catalog.capture(
            orphan,
            service.config.project_id,
            experiment_id,
            result.artifacts,
        )
        service.event_log.append("ARTIFACT_CAPTURED", records[0].to_dict())

        status = service.status()

        self.assertEqual(status["artifacts"], 1)
        self.assertEqual(status["experiments_by_status"], {"INFRA_FAILED": 1})
        artifact_types = [
            event.event_type
            for event in service.event_log.read()
            if event.event_type.startswith("ARTIFACT_")
        ]
        self.assertEqual(artifact_types, ["ARTIFACT_CAPTURED"])
        self.assertEqual(service.replay()["artifacts_verified"], 3)

    def test_compatible_legacy_baseline_id_alias_is_normalized(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        recorded = service.baseline()
        payload = json.loads(canonical_json(recorded))
        payload.pop("event_sequence")
        payload.pop("baseline_id")
        payload["id"] = "base_legacy_alias"
        payload.pop("digest")
        payload["digest"] = sha256_json(payload)
        service.event_log.append("BASELINE_RECORDED", payload)

        outcome = service.run_once(project / "candidates" / "improve.json")

        registration = next(
            event
            for event in service.event_log.read()
            if event.event_type == "EXPERIMENT_REGISTERED"
        )
        self.assertEqual(registration.payload["baseline_id"], "base_legacy_alias")
        self.assertEqual(outcome["status"], "VALIDATED")

    def test_legacy_outcome_finding_id_and_key_aliases_reconcile(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        original_append = service.event_log.append
        failed = False

        def fail_first_outcome(event_type, payload, **kwargs):
            nonlocal failed
            if event_type == "FINDING_RECORDED" and not failed:
                failed = True
                raise OSError("leave terminal without finding")
            return original_append(event_type, payload, **kwargs)

        with patch.object(service.event_log, "append", side_effect=fail_first_outcome):
            with self.assertRaises(OSError):
                service.run_once(project / "candidates" / "improve.json")

        terminal = next(
            event
            for event in service.event_log.read()
            if event.event_type == "EXPERIMENT_TERMINATED"
        )
        finding = service._outcome_finding_payload(terminal)
        finding["id"] = finding.pop("finding_id")
        finding["finding_key"] = finding.pop("key")
        service.event_log.append("FINDING_RECORDED", finding)

        status = service.status()

        self.assertEqual(status["findings"], 1)
        self.assertEqual(len(service.findings()), 1)

    def test_baseline_cleanup_integrity_failure_dominates_operation_error(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        original_call = service._call_sealed

        def fail_baseline(report, operation, **kwargs):
            if operation is Operation.BASELINE:
                raise OSError("baseline operation failed")
            return original_call(report, operation, **kwargs)

        with (
            patch.object(service, "_call_sealed", side_effect=fail_baseline),
            patch.object(
                WorkspaceManager,
                "cleanup",
                side_effect=IntegrityError("workspace identity drift"),
            ),
        ):
            with self.assertRaisesRegex(IntegrityError, "identity drift"):
                service.baseline()

    def test_workspace_create_cleanup_note_is_durable_secondary_error(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        service.baseline()

        with (
            patch(
                "research_os.execution.workspace.shutil.copytree",
                side_effect=OSError("copy failed"),
            ),
            patch.object(
                WorkspaceManager,
                "_remove_workspace_path",
                side_effect=OSError("removal failed"),
            ),
        ):
            outcome = service.run_once(project / "candidates" / "improve.json")

        self.assertEqual(outcome["status"], "INFRA_FAILED")
        self.assertIn("notes", outcome["error"])
        secondary = outcome.get("secondary_errors", [])
        self.assertTrue(
            any("removal failed" in error.get("message", "") for error in secondary)
        )

    def test_recovery_detach_failure_still_preserves_untrusted_workspace(self):
        project = self.copy_optimization()
        orphan, _, _ = self.leave_evaluated_orphan(project)
        (orphan / "outputs" / "result.json").write_text(
            '{"tampered":true}\n', encoding="utf-8"
        )
        service = ResearchService(project)

        with patch.object(
            WorkspaceManager,
            "detach",
            side_effect=OSError("simulated detach failure"),
        ):
            status = service.status()

        self.assertEqual(status["experiments_by_status"], {"UNTRUSTED": 1})
        self.assertTrue(orphan.is_dir())

    def test_unsafe_interrupted_orphan_is_untrusted_before_infra_terminal(self):
        project = self.copy_optimization()
        orphan, _, _ = self.leave_evaluated_orphan(project)
        shutil.rmtree(orphan)
        orphan.symlink_to(project / "parameter.json")
        service = ResearchService(project)

        status = service.status()

        self.assertEqual(status["experiments_by_status"], {"UNTRUSTED": 1})
        terminal = next(
            event
            for event in service.event_log.read()
            if event.event_type == "EXPERIMENT_TERMINATED"
        )
        self.assertEqual(
            terminal.payload["reason_code"],
            "INTERRUPTED_EVIDENCE_UNTRUSTED",
        )
        self.assertTrue(orphan.is_symlink())

    def test_invalid_historical_metric_does_not_wedge_recovery(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        report = service.doctor()
        candidate = {"x": 5.0}
        candidate_digest = sha256_json(candidate)
        experiment_id = new_experiment_id(
            service.config.project_id,
            candidate_digest,
            compatibility_digest=str(report.fingerprints["compatibility_digest"]),
        )
        service.event_log.append(
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": experiment_id,
                "candidate_digest": candidate_digest,
                "candidate": candidate,
                "compatibility_digest": report.fingerprints["compatibility_digest"],
                "baseline_id": "base_legacy",
                "primary_metric": "",
                "attempt": 1,
                "status": "registered",
            },
        )

        status = service.status()

        self.assertEqual(status["experiments_by_status"], {"INFRA_FAILED": 1})

    def test_repeated_artifact_publish_failure_preserves_then_recovers(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        service.baseline()

        with patch.object(
            service,
            "_publish_artifact_records",
            side_effect=ProtocolError("publication unavailable"),
        ):
            with self.assertRaisesRegex(ProtocolError, "publication unavailable"):
                service.run_once(project / "candidates" / "improve.json")

        events = service.event_log.read()
        self.assertFalse(
            any(event.event_type == "EXPERIMENT_TERMINATED" for event in events)
        )
        self.assertFalse(any(event.event_type == "ARTIFACT_RECORDED" for event in events))
        workspaces = project / ".research-os" / "runtime" / "workspaces"
        self.assertEqual(len(list(workspaces.iterdir())), 1)

        status = service.status()

        self.assertEqual(status["experiments_by_status"], {"INFRA_FAILED": 1})
        self.assertEqual(status["artifacts"], 1)
        self.assertEqual(list(workspaces.iterdir()), [])

    def test_committed_evaluate_stage_interrupt_still_seals_artifacts(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        service.baseline()
        original_append = service.event_log.append
        interrupted = False

        def interrupt_after_evaluate_append(event_type, payload=None, **kwargs):
            nonlocal interrupted
            event = original_append(event_type, payload, **kwargs)
            if (
                event_type == "STAGE_COMPLETED"
                and isinstance(payload, dict)
                and payload.get("stage") == Operation.EVALUATE.value
                and not interrupted
            ):
                interrupted = True
                raise KeyboardInterrupt("evaluate stage append interrupted")
            return event

        with patch.object(
            service.event_log,
            "append",
            side_effect=interrupt_after_evaluate_append,
        ):
            with self.assertRaises(KeyboardInterrupt):
                service.run_once(project / "candidates" / "improve.json")

        status = service.status()
        self.assertEqual(status["experiments_by_status"], {"CANCELLED": 1})
        self.assertEqual(status["artifacts"], 1)
        self.assertEqual(service.replay()["artifacts_verified"], 3)

    def test_replay_rejects_terminal_result_without_artifact_evidence(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        service.doctor()
        experiment_id = "exp_legacy_missing_artifact"
        service.event_log.append(
            "EXPERIMENT_REGISTERED",
            {
                "id": experiment_id,
                "digest": "a" * 64,
                "state": "registered",
            },
        )
        service.event_log.append(
            "EXPERIMENT_STATUS_CHANGED",
            {
                "id": experiment_id,
                "state": "rejected",
                "retryable": False,
                "result": {
                    "metrics": {"loss": 5.0},
                    "artifacts": [
                        {
                            "path": "lost.json",
                            "media_type": "application/json",
                            "retention": "run",
                            "sensitivity": "internal",
                        }
                    ],
                },
            },
        )

        with self.assertRaisesRegex(
            IntegrityError, "terminal artifact declarations"
        ):
            service.replay()

    def test_replay_rejects_baseline_with_missing_declared_artifact(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        recorded = service.baseline()
        payload = json.loads(canonical_json(recorded))
        payload.pop("event_sequence")
        payload["baseline_id"] = "base_missing_evidence"
        payload["artifacts"] = []
        payload.pop("digest")
        payload["digest"] = sha256_json(payload)
        service.event_log.append("BASELINE_RECORDED", payload)

        with self.assertRaisesRegex(IntegrityError, "artifact evidence is incomplete"):
            service.replay()

    def test_interrupted_first_terminal_append_records_exactly_one_cancellation(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        original_append = service.event_log.append
        interrupt = KeyboardInterrupt("terminal append interrupted")
        interrupted = False

        def interrupt_first_terminal(event_type, payload=None, **kwargs):
            nonlocal interrupted
            if event_type == "EXPERIMENT_TERMINATED" and not interrupted:
                interrupted = True
                raise interrupt
            return original_append(event_type, payload, **kwargs)

        with (
            patch.object(
                service.event_log,
                "append",
                side_effect=interrupt_first_terminal,
            ),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            service.run_once(project / "candidates" / "improve.json")

        self.assertIs(raised.exception, interrupt)
        terminals = [
            event
            for event in service.event_log.read()
            if event.event_type == "EXPERIMENT_TERMINATED"
        ]
        self.assertEqual(len(terminals), 1)
        terminal = terminals[0]
        self.assertEqual(terminal.payload["status"], "CANCELLED")
        self.assertEqual(terminal.payload["reason_code"], "USER_CANCELLED")
        findings = [
            event
            for event in service.event_log.read()
            if event.event_type == "FINDING_RECORDED"
            and event.payload.get("key") == "experiment_outcome"
        ]
        self.assertEqual(len(findings), 1)
        self.assertEqual(
            findings[0].payload["evidence"],
            [{"event_id": terminal.event_id, "event_hash": terminal.hash}],
        )
        self.assertEqual(service.status()["experiments_by_status"], {"CANCELLED": 1})

    def test_integrity_failure_during_cancelled_artifact_republish_is_primary(self):
        project = self.copy_optimization()
        service = ResearchService(project)
        service.baseline()
        original_call = service._call_sealed
        original_publish = service._publish_artifact_records
        interrupt = KeyboardInterrupt("verify interrupted")
        publish_calls = 0

        def interrupt_verify(report, operation, **kwargs):
            if operation is Operation.VERIFY:
                raise interrupt
            return original_call(report, operation, **kwargs)

        def fail_republish(experiment_id, records):
            nonlocal publish_calls
            publish_calls += 1
            if publish_calls == 2:
                raise IntegrityError("artifact republish integrity failure")
            return original_publish(experiment_id, records)

        with (
            patch.object(service, "_call_sealed", side_effect=interrupt_verify),
            patch.object(
                service,
                "_publish_artifact_records",
                side_effect=fail_republish,
            ),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            service.run_once(project / "candidates" / "improve.json")

        self.assertIs(raised.exception, interrupt)
        self.assertEqual(publish_calls, 2)
        terminals = [
            event
            for event in service.event_log.read()
            if event.event_type == "EXPERIMENT_TERMINATED"
        ]
        self.assertEqual(len(terminals), 1)
        terminal = terminals[0]
        self.assertEqual(terminal.payload["status"], "UNTRUSTED")
        self.assertEqual(terminal.payload["reason_code"], "INTEGRITY_CHECK_FAILED")
        error_payload = terminal.payload.get("error")
        if not isinstance(error_payload, dict):
            self.fail("terminal error is not an object")
        self.assertEqual(error_payload.get("type"), "IntegrityError")
        secondary_errors = terminal.payload.get("secondary_errors")
        if not isinstance(secondary_errors, list):
            self.fail("terminal secondary_errors is not an array")
        secondary_types: list[object] = []
        for error in secondary_errors:
            if not isinstance(error, dict):
                self.fail("terminal secondary error is not an object")
            secondary_types.append(error.get("type"))
        self.assertIn(
            "KeyboardInterrupt",
            secondary_types,
        )
        self.assertEqual(service.status()["experiments_by_status"], {"UNTRUSTED": 1})


if __name__ == "__main__":
    unittest.main()
