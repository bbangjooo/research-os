from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

from research_os.certification import (
    EVALUATOR_CERTIFICATION_RELATIVE,
    REQUIRED_EVALUATOR_CHECK_IDS,
)
from research_os.contracts import (
    Operation,
    ProtocolResponse,
    canonical_json_bytes,
    sha256_json,
)
from research_os.errors import (
    AgentResearchNotReadyError,
    ConfigurationError,
    GraphPolicyError,
    IntegrityError,
    StaleAgentContextError,
)
from research_os.kernel import events as events_module
from research_os.memory.findings import make_finding_event, record_finding
from research_os.scaffold import RESEARCH_BRIEF_TEMPLATE
from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]


def _configure_agent_files(project: Path) -> None:
    control = project / ".research-os"
    (control / "research-brief.md").write_text(
        RESEARCH_BRIEF_TEMPLATE.replace(
            "REPLACE_ME",
            "Configured toy research with three hypothesis classes",
        ),
        encoding="utf-8",
    )
    (control / "candidate.schema.json").write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {"x": {"type": "number"}},
                "required": ["x"],
                "additionalProperties": False,
                "x-research-os-configured": True,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _passing_review(path: Path, *, subject_digest: str) -> Path:
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "research-os-evaluator-review",
                "subject_digest": subject_digest,
                "reviewer": "fresh-read-only-test-critic",
                "independent_reviewer": True,
                "verdict": "PASS",
                "summary": "All bounded golden controls passed.",
                "checks": [
                    {
                        "id": check_id,
                        "status": "PASS",
                        "evidence": f"independent evidence for {check_id}",
                    }
                    for check_id in sorted(REQUIRED_EVALUATOR_CHECK_IDS)
                ],
                "blocking_findings": [],
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return path


class AgentScientificControlTests(unittest.TestCase):
    def copy_project(self, *, certify: bool) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        project = Path(temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        _configure_agent_files(project)
        if certify:
            service = ResearchService(project)
            subject = service.evaluator_review_subject()
            service.certify_evaluator(
                _passing_review(
                    Path(temporary.name) / "review.json",
                    subject_digest=str(subject["digest"]),
                )
            )
            service.baseline()
        return temporary, project

    def _run_root(
        self,
        service: ResearchService,
        project: Path,
        *,
        x: float,
        change: str,
    ) -> dict[str, object]:
        context = service.agent_context(limit=10)
        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text(json.dumps({"x": x}) + "\n", encoding="utf-8")
        return service.run_once(
            inbox,
            context_token=context["snapshot"]["context_token"],
            graph_action="explore",
            scientific_change=change,
        )

    def test_missing_certification_is_visible_but_cannot_register(self):
        temporary, project = self.copy_project(certify=False)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)

        context = service.agent_context()
        self.assertFalse(context["agent"]["research_ready"])
        self.assertEqual(
            context["agent"]["evaluator_certification"]["status"],
            "MISSING",
        )
        self.assertNotIn("RUN_ONE_CANDIDATE", context["allowed_agent_actions"])
        self.assertNotIn("RETRY_ELIGIBLE_ATTEMPT", context["allowed_agent_actions"])
        self.assertIn("CERTIFY_EVALUATOR", context["allowed_agent_actions"])
        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text('{"x":2.0}\n', encoding="utf-8")
        with self.assertRaises(AgentResearchNotReadyError) as caught:
            service.run_once(
                inbox,
                context_token=context["snapshot"]["context_token"],
                graph_action="explore",
                scientific_change="toy-class: move to optimum",
            )
        self.assertEqual(caught.exception.code, "AGENT_RESEARCH_NOT_READY")
        self.assertEqual(service.status()["experiments"], 0)

    def test_bound_input_change_stales_certificate_and_context(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        token = service.agent_context()["snapshot"]["context_token"]

        evaluator = project / "evaluator.py"
        evaluator.write_text(
            evaluator.read_text(encoding="utf-8") + "\n# semantic drift\n",
            encoding="utf-8",
        )
        refreshed = service.agent_context()
        self.assertEqual(
            refreshed["agent"]["evaluator_certification"]["status"],
            "STALE",
        )
        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text('{"x":2.0}\n', encoding="utf-8")
        with self.assertRaises(StaleAgentContextError):
            service.run_once(
                inbox,
                context_token=token,
                graph_action="explore",
                scientific_change="toy-class: move to optimum",
            )
        self.assertEqual(service.status()["experiments"], 0)

    def test_certify_rolls_back_live_adapter_drift_after_publication(self):
        temporary, project = self.copy_project(certify=False)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        subject = service.evaluator_review_subject()
        review = _passing_review(
            Path(temporary.name) / "adapter-race-review.json",
            subject_digest=str(subject["digest"]),
        )
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        original_call = service._call
        fingerprint_calls = 0

        def drifting_call(operation, **kwargs):
            nonlocal fingerprint_calls
            response = original_call(operation, **kwargs)
            if operation is Operation.FINGERPRINT:
                fingerprint_calls += 1
                if fingerprint_calls == 3:
                    return ProtocolResponse.success(
                        request_id=response.request_id,
                        payload={
                            "dataset": "target-v2",
                            "evaluator": "squared-error-v2",
                        },
                    )
            return response

        with (
            mock.patch.object(service, "_call", side_effect=drifting_call),
            self.assertRaisesRegex(IntegrityError, "changed during publication"),
        ):
            service.certify_evaluator(review)

        self.assertEqual(fingerprint_calls, 3)
        self.assertFalse(certificate.exists())

    def test_certify_reports_post_commit_adapter_drift_as_stale(self):
        temporary, project = self.copy_project(certify=False)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        subject = service.evaluator_review_subject()
        review = _passing_review(
            Path(temporary.name) / "post-commit-adapter-race-review.json",
            subject_digest=str(subject["digest"]),
        )
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        original_call = service._call
        fingerprint_calls = 0

        def drifting_call(operation, **kwargs):
            nonlocal fingerprint_calls
            response = original_call(operation, **kwargs)
            if operation is Operation.FINGERPRINT:
                fingerprint_calls += 1
                if fingerprint_calls == 4:
                    return ProtocolResponse.success(
                        request_id=response.request_id,
                        payload={
                            "dataset": "target-v2",
                            "evaluator": "squared-error-v2",
                        },
                    )
            return response

        with mock.patch.object(service, "_call", side_effect=drifting_call):
            summary = service.certify_evaluator(review)

        self.assertEqual(fingerprint_calls, 4)
        self.assertTrue(certificate.exists())
        self.assertFalse(summary["current"])
        self.assertEqual(summary["status"], "STALE")

    def test_run_rechecks_source_after_doctor_before_registration(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        token = service.agent_context()["snapshot"]["context_token"]
        original_doctor = service._doctor

        def mutate_after_doctor():
            report = original_doctor()
            evaluator = project / "evaluator.py"
            evaluator.write_text(
                evaluator.read_text(encoding="utf-8") + "\n# post-doctor drift\n",
                encoding="utf-8",
            )
            return report

        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text('{"x":1.0}\n', encoding="utf-8")
        with (
            mock.patch.object(service, "_doctor", side_effect=mutate_after_doctor),
            self.assertRaises(StaleAgentContextError),
        ):
            service.run_once(
                inbox,
                context_token=token,
                graph_action="explore",
                scientific_change="class-a: test post-doctor source drift",
            )
        self.assertFalse(
            any(
                event.event_type == "EXPERIMENT_REGISTERED"
                for event in service.event_log.read()
            )
        )

    def test_run_rechecks_adapter_seal_before_registration(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        report = service._doctor()
        token = service.agent_context()["snapshot"]["context_token"]
        adapter_value = {"toy_adapter_revision": "externally-drifted"}
        adapter_digest = sha256_json(adapter_value)
        fingerprints = {
            **report.fingerprints,
            "adapter": {"digest": adapter_digest, "value": adapter_value},
            "compatibility_digest": sha256_json(
                {
                    "project": report.fingerprints[
                        "project_compatibility_digest"
                    ],
                    "adapter": adapter_digest,
                }
            ),
        }
        drifted_report = replace(
            report,
            adapter_fingerprint=adapter_value,
            fingerprints=fingerprints,
        )
        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text('{"x":1.0}\n', encoding="utf-8")
        with (
            mock.patch.object(service, "_doctor", return_value=drifted_report),
            self.assertRaises(StaleAgentContextError),
        ):
            service.run_once(
                inbox,
                context_token=token,
                graph_action="explore",
                scientific_change="class-a: test adapter fingerprint drift",
            )
        self.assertFalse(
            any(
                event.event_type == "EXPERIMENT_REGISTERED"
                for event in service.event_log.read()
            )
        )

    def test_graph_relationship_and_multiple_root_hypotheses(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)

        first = self._run_root(
            service,
            project,
            x=2.0,
            change="class-a: set the coordinate to the known optimum",
        )
        context = service.agent_context()
        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text('{"x":2.0}\n', encoding="utf-8")
        before = len(service.event_log.read())
        with self.assertRaisesRegex(GraphPolicyError, "must differ"):
            service.run_once(
                inbox,
                parent_id=str(first["experiment_id"]),
                context_token=context["snapshot"]["context_token"],
                graph_action="ablate",
                scientific_change="class-a: claim a change without changing the candidate",
            )
        self.assertEqual(len(service.event_log.read()), before)

        inbox.write_text('{"x":1.5}\n', encoding="utf-8")
        child = service.run_once(
            inbox,
            parent_id=str(first["experiment_id"]),
            context_token=context["snapshot"]["context_token"],
            graph_action="ablate",
            scientific_change="class-a: isolate a half-step displacement",
        )
        child_row = service.lineage(str(child["experiment_id"]))[-1]
        self.assertEqual(child_row["parent_id"], first["experiment_id"])

        context = service.agent_context()
        inbox.write_text('{"x":1.25}\n', encoding="utf-8")
        before = len(service.event_log.read())
        with self.assertRaises(GraphPolicyError):
            service.run_once(
                inbox,
                parent_id=str(first["experiment_id"]),
                context_token=context["snapshot"]["context_token"],
                graph_action="explore",
                scientific_change="class-b: invalid parented root",
            )
        self.assertEqual(len(service.event_log.read()), before)

        self._run_root(
            service,
            project,
            x=1.0,
            change="class-b: test a unit displacement",
        )
        self._run_root(
            service,
            project,
            x=0.0,
            change="class-c: test a two-unit displacement",
        )
        context = service.agent_context()
        inbox.write_text('{"x":3.0}\n', encoding="utf-8")
        fourth = service.run_once(
            inbox,
            context_token=context["snapshot"]["context_token"],
            graph_action="explore",
            scientific_change="class-d: explore after closing earlier classes",
        )
        self.assertEqual(
            service.lineage(str(fourth["experiment_id"]))[-1]["payload"][
                "graph_action"
            ],
            "explore",
        )

    def test_branch_conclusion_is_bound_to_terminal_events(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        first = self._run_root(
            service,
            project,
            x=0.0,
            change="class-a: test a two-unit displacement",
        )
        context = service.agent_context()
        conclusion_path = Path(temporary.name) / "conclusion.json"
        conclusion_path.write_text(
            json.dumps(
                {
                    "branch_experiment_ids": [first["experiment_id"]],
                    "hypothesis_class": "class-a",
                    "failure_signature": "primary metric below promotion threshold",
                    "conclusion": "This mechanism is not supported by this node.",
                    "confidence": "inconclusive",
                    "next_step": "explore",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        finding = service.conclude_branch(
            conclusion_path,
            context_token=context["snapshot"]["context_token"],
        )
        self.assertEqual(finding["key"], "branch_conclusion")
        self.assertEqual(
            finding["metadata"]["claim_authority"],
            "agent_interpretation",
        )
        self.assertEqual(len(finding["evidence"]), 1)
        finding_context = service.agent_context()
        projected_finding = finding_context["evidence"]["recent_findings"][-1]
        self.assertEqual(
            projected_finding["metadata"]["claim_authority"],
            "agent_interpretation",
        )
        self.assertEqual(projected_finding["branch_conclusion_version"], 1)
        with self.assertRaisesRegex(ConfigurationError, "already recorded"):
            refreshed = service.agent_context()
            service.conclude_branch(
                conclusion_path,
                context_token=refreshed["snapshot"]["context_token"],
            )

        with self.assertRaises(ValueError):
            record_finding(
                service.event_log,
                {"claim": "forged"},
                key="branch_conclusion",
            )
        legacy_payload = make_finding_event(
            service.config.project_id,
            {"legacy": "project-authored branch conclusion"},
            key="branch_conclusion",
            evidence=[],
        )
        service.event_log.append("FINDING_RECORDED", legacy_payload)
        service.replay()

        forged_payload = make_finding_event(
            service.config.project_id,
            finding["content"],
            key="branch_conclusion",
            evidence=[],
            metadata={
                "claim_authority": "agent_interpretation",
                "authorized_action": None,
                "agent_context_token": "forged",
                "agent_context_schema_version": 2,
            },
        )
        forged_payload["branch_conclusion_version"] = 1
        service.event_log.append(
            "FINDING_RECORDED",
            forged_payload,
        )
        with self.assertRaises(IntegrityError):
            service.replay()

    def test_registration_append_refuses_a_new_canonical_head(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        context = service.agent_context()
        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text('{"x":1.0}\n', encoding="utf-8")
        original_append = service.event_log.append
        injected = False

        def racing_append(event_type, payload=None, **kwargs):
            nonlocal injected
            if event_type == "EXPERIMENT_REGISTERED" and not injected:
                injected = True
                original_append(
                    "FINDING_RECORDED",
                    make_finding_event(
                        service.config.project_id,
                        {"note": "concurrent canonical change"},
                        key="race_marker",
                    ),
                )
            return original_append(event_type, payload, **kwargs)

        with (
            mock.patch.object(service.event_log, "append", side_effect=racing_append),
            self.assertRaises(StaleAgentContextError),
        ):
            service.run_once(
                inbox,
                context_token=context["snapshot"]["context_token"],
                graph_action="explore",
                scientific_change="class-race: one head change",
            )
        self.assertTrue(injected)
        self.assertFalse(
            any(
                event.event_type == "EXPERIMENT_REGISTERED"
                for event in service.event_log.read()
            )
        )

    def test_registration_append_rechecks_certificate_inside_append(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        context = service.agent_context()
        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text('{"x":1.0}\n', encoding="utf-8")
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        rejected = json.loads(certificate.read_text(encoding="utf-8"))
        rejected["review"]["verdict"] = "FAIL"
        rejected["review"]["checks"][0]["status"] = "FAIL"
        rejected["review"]["blocking_findings"] = ["append-boundary rejection"]
        rejected["certified"] = False
        rejected["review_digest"] = sha256_json(rejected["review"])
        unsigned = dict(rejected)
        unsigned.pop("digest")
        rejected["digest"] = sha256_json(unsigned)
        original_append = service.event_log.append
        swapped = False

        def swapping_append(event_type, payload=None, **kwargs):
            nonlocal swapped
            if event_type == "EXPERIMENT_REGISTERED" and not swapped:
                swapped = True
                certificate.write_bytes(canonical_json_bytes(rejected) + b"\n")
            return original_append(event_type, payload, **kwargs)

        with (
            mock.patch.object(service.event_log, "append", side_effect=swapping_append),
            self.assertRaises((StaleAgentContextError, AgentResearchNotReadyError)),
        ):
            service.run_once(
                inbox,
                context_token=context["snapshot"]["context_token"],
                graph_action="explore",
                scientific_change="class-race: reject certificate at append",
            )
        self.assertTrue(swapped)
        self.assertFalse(
            any(
                event.event_type == "EXPERIMENT_REGISTERED"
                for event in service.event_log.read()
            )
        )

    def test_registration_postcondition_rolls_back_source_change_before_write(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        context = service.agent_context()
        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text('{"x":1.0}\n', encoding="utf-8")
        evaluator = project / "evaluator.py"
        original_append = service.event_log.append
        real_write = os.write
        before = service.event_log.path.read_bytes()
        injected = False

        def mutate_before_write(descriptor: int, data: bytes) -> int:
            nonlocal injected
            if b'"event_type":"EXPERIMENT_REGISTERED"' in data and not injected:
                injected = True
                evaluator.write_text(
                    evaluator.read_text(encoding="utf-8")
                    + "\n# changed immediately before event write\n",
                    encoding="utf-8",
                )
            return real_write(descriptor, data)

        def append_with_source_race(event_type, payload=None, **kwargs):
            if event_type == "EXPERIMENT_REGISTERED":
                with mock.patch.object(
                    events_module.os,
                    "write",
                    side_effect=mutate_before_write,
                ):
                    return original_append(event_type, payload, **kwargs)
            return original_append(event_type, payload, **kwargs)

        with (
            mock.patch.object(
                service.event_log,
                "append",
                side_effect=append_with_source_race,
            ),
            self.assertRaises(StaleAgentContextError),
        ):
            service.run_once(
                inbox,
                context_token=context["snapshot"]["context_token"],
                graph_action="explore",
                scientific_change="class-race: source changes at durable append",
            )

        self.assertTrue(injected)
        self.assertEqual(service.event_log.path.read_bytes(), before)

    def test_registration_postcondition_rejects_fresh_adapter_seal_change(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        context = service.agent_context()
        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text('{"x":1.0}\n', encoding="utf-8")
        original_append = service.event_log.append
        original_call = service._call
        real_write = os.write
        before = service.event_log.path.read_bytes()
        adapter_drifted = False

        def drifting_call(operation, **kwargs):
            response = original_call(operation, **kwargs)
            if operation is Operation.FINGERPRINT and adapter_drifted:
                return ProtocolResponse.success(
                    request_id=response.request_id,
                    payload={
                        "dataset": "target-v2",
                        "evaluator": "squared-error-v2",
                    },
                )
            return response

        def drift_before_registration_write(descriptor: int, data: bytes) -> int:
            nonlocal adapter_drifted
            if b'"event_type":"EXPERIMENT_REGISTERED"' in data:
                adapter_drifted = True
            return real_write(descriptor, data)

        def append_with_adapter_race(event_type, payload=None, **kwargs):
            if event_type == "EXPERIMENT_REGISTERED":
                with mock.patch.object(
                    events_module.os,
                    "write",
                    side_effect=drift_before_registration_write,
                ):
                    return original_append(event_type, payload, **kwargs)
            return original_append(event_type, payload, **kwargs)

        with (
            mock.patch.object(service, "_call", side_effect=drifting_call),
            mock.patch.object(
                service.event_log,
                "append",
                side_effect=append_with_adapter_race,
            ),
            self.assertRaisesRegex(StaleAgentContextError, "doctor seal changed"),
        ):
            service.run_once(
                inbox,
                context_token=context["snapshot"]["context_token"],
                graph_action="explore",
                scientific_change="class-race: adapter changes at durable append",
            )

        self.assertTrue(adapter_drifted)
        self.assertEqual(service.event_log.path.read_bytes(), before)

    def test_agent_context_retries_rows_when_canonical_cursor_moves(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        original_findings = service.projection.findings
        injected_event = None

        def racing_findings(*args, **kwargs):
            nonlocal injected_event
            rows = original_findings(*args, **kwargs)
            if injected_event is None:
                injected_event = service.event_log.append(
                    "FINDING_RECORDED",
                    make_finding_event(
                        service.config.project_id,
                        {"note": "context cursor race"},
                        key="context_cursor_marker",
                    ),
                )
            return rows

        with mock.patch.object(
            service.projection,
            "findings",
            side_effect=racing_findings,
        ):
            context = service.agent_context(schema_version=2)
        self.assertIsNotNone(injected_event)
        assert injected_event is not None
        self.assertEqual(context["snapshot"]["last_sequence"], injected_event.sequence)
        self.assertEqual(context["snapshot"]["last_hash"], injected_event.hash)
        self.assertTrue(
            any(
                finding["finding_key"] == "context_cursor_marker"
                for finding in context["evidence"]["recent_findings"]
            )
        )

    def test_branch_conclusion_append_refuses_a_new_canonical_head(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        first = self._run_root(
            service,
            project,
            x=0.0,
            change="class-a: branch race evidence",
        )
        context = service.agent_context()
        conclusion_path = Path(temporary.name) / "race-conclusion.json"
        conclusion_path.write_text(
            json.dumps(
                {
                    "branch_experiment_ids": [first["experiment_id"]],
                    "hypothesis_class": "class-a",
                    "failure_signature": "no promotion",
                    "conclusion": "race test conclusion",
                    "confidence": "inconclusive",
                    "next_step": "stop",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        original_append = service.event_log.append
        injected = False

        def racing_append(event_type, payload=None, **kwargs):
            nonlocal injected
            if event_type == "FINDING_RECORDED" and not injected:
                injected = True
                original_append(
                    "FINDING_RECORDED",
                    make_finding_event(
                        service.config.project_id,
                        {"note": "branch append race"},
                        key="branch_race_marker",
                    ),
                )
            return original_append(event_type, payload, **kwargs)

        with (
            mock.patch.object(service.event_log, "append", side_effect=racing_append),
            self.assertRaises(StaleAgentContextError),
        ):
            service.conclude_branch(
                conclusion_path,
                context_token=context["snapshot"]["context_token"],
            )
        self.assertTrue(injected)
        self.assertFalse(
            any(
                event.event_type == "FINDING_RECORDED"
                and event.payload.get("key") == "branch_conclusion"
                for event in service.event_log.read()
            )
        )

    def test_finding_postcondition_rolls_back_certificate_change_before_write(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        first = self._run_root(
            service,
            project,
            x=0.0,
            change="class-a: certificate race evidence",
        )
        context = service.agent_context()
        conclusion_path = Path(temporary.name) / "certificate-race-conclusion.json"
        conclusion_path.write_text(
            json.dumps(
                {
                    "branch_experiment_ids": [first["experiment_id"]],
                    "hypothesis_class": "class-a",
                    "failure_signature": "no promotion",
                    "conclusion": "certificate race test conclusion",
                    "confidence": "inconclusive",
                    "next_step": "stop",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        rejected = json.loads(certificate.read_text(encoding="utf-8"))
        rejected["review"]["verdict"] = "FAIL"
        rejected["review"]["checks"][0]["status"] = "FAIL"
        rejected["review"]["blocking_findings"] = ["post-write rejection"]
        rejected["certified"] = False
        rejected["review_digest"] = sha256_json(rejected["review"])
        unsigned = dict(rejected)
        unsigned.pop("digest")
        rejected["digest"] = sha256_json(unsigned)
        original_append = service.event_log.append
        real_write = os.write
        before = service.event_log.path.read_bytes()
        injected = False

        def mutate_before_write(descriptor: int, data: bytes) -> int:
            nonlocal injected
            if b'"event_type":"FINDING_RECORDED"' in data and not injected:
                injected = True
                certificate.write_bytes(canonical_json_bytes(rejected) + b"\n")
            return real_write(descriptor, data)

        def append_with_certificate_race(event_type, payload=None, **kwargs):
            if event_type == "FINDING_RECORDED":
                with mock.patch.object(
                    events_module.os,
                    "write",
                    side_effect=mutate_before_write,
                ):
                    return original_append(event_type, payload, **kwargs)
            return original_append(event_type, payload, **kwargs)

        with (
            mock.patch.object(
                service.event_log,
                "append",
                side_effect=append_with_certificate_race,
            ),
            self.assertRaises((StaleAgentContextError, AgentResearchNotReadyError)),
        ):
            service.conclude_branch(
                conclusion_path,
                context_token=context["snapshot"]["context_token"],
            )

        self.assertTrue(injected)
        self.assertEqual(service.event_log.path.read_bytes(), before)

    def test_finding_postcondition_rejects_fresh_adapter_seal_change(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        first = self._run_root(
            service,
            project,
            x=0.0,
            change="class-a: adapter race evidence",
        )
        context = service.agent_context()
        conclusion_path = Path(temporary.name) / "adapter-race-conclusion.json"
        conclusion_path.write_text(
            json.dumps(
                {
                    "branch_experiment_ids": [first["experiment_id"]],
                    "hypothesis_class": "class-a",
                    "failure_signature": "no promotion",
                    "conclusion": "adapter race test conclusion",
                    "confidence": "inconclusive",
                    "next_step": "stop",
                }
            )
            + "\n",
            encoding="utf-8",
        )
        original_append = service.event_log.append
        original_call = service._call
        real_write = os.write
        before = service.event_log.path.read_bytes()
        adapter_drifted = False

        def drifting_call(operation, **kwargs):
            response = original_call(operation, **kwargs)
            if operation is Operation.FINGERPRINT and adapter_drifted:
                return ProtocolResponse.success(
                    request_id=response.request_id,
                    payload={
                        "dataset": "target-v2",
                        "evaluator": "squared-error-v2",
                    },
                )
            return response

        def drift_before_finding_write(descriptor: int, data: bytes) -> int:
            nonlocal adapter_drifted
            if b'"event_type":"FINDING_RECORDED"' in data:
                adapter_drifted = True
            return real_write(descriptor, data)

        def append_with_adapter_race(event_type, payload=None, **kwargs):
            if event_type == "FINDING_RECORDED":
                with mock.patch.object(
                    events_module.os,
                    "write",
                    side_effect=drift_before_finding_write,
                ):
                    return original_append(event_type, payload, **kwargs)
            return original_append(event_type, payload, **kwargs)

        with (
            mock.patch.object(service, "_call", side_effect=drifting_call),
            mock.patch.object(
                service.event_log,
                "append",
                side_effect=append_with_adapter_race,
            ),
            self.assertRaisesRegex(StaleAgentContextError, "doctor seal changed"),
        ):
            service.conclude_branch(
                conclusion_path,
                context_token=context["snapshot"]["context_token"],
            )

        self.assertTrue(adapter_drifted)
        self.assertEqual(service.event_log.path.read_bytes(), before)

    def test_new_compatibility_hides_old_graph_and_requires_its_own_baseline(self):
        temporary, project = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        compatibility_a = service.agent_context()["graph"]["compatibility_digest"]
        self._run_root(
            service,
            project,
            x=0.0,
            change="class-a: establish compatibility-a evidence",
        )
        evaluator = project / "evaluator.py"
        evaluator.write_text(
            evaluator.read_text(encoding="utf-8") + "\n# compatibility b\n",
            encoding="utf-8",
        )
        subject = service.evaluator_review_subject()
        service.certify_evaluator(
            _passing_review(
                Path(temporary.name) / "review-b.json",
                subject_digest=str(subject["digest"]),
            ),
            replace=True,
        )
        context = service.agent_context()
        self.assertNotEqual(
            context["graph"]["compatibility_digest"],
            compatibility_a,
        )
        self.assertEqual(context["state"]["baselines"], 1)
        self.assertEqual(context["graph"]["total_experiments"], 0)
        self.assertEqual(context["graph"]["recent"], [])
        self.assertEqual(context["graph"]["frontier"], [])
        self.assertEqual(context["graph"]["retryable"], [])
        self.assertIn("SEAL_BASELINE", context["allowed_agent_actions"])
        self.assertNotIn("RUN_ONE_CANDIDATE", context["allowed_agent_actions"])


if __name__ == "__main__":
    unittest.main()
