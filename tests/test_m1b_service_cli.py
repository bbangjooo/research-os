from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path
from threading import Barrier
from unittest import mock

from research_os.certification import REQUIRED_EVALUATOR_CHECK_IDS
from research_os.cli import main
from research_os.errors import EvaluatorCertificationError, ScientificStateError
from research_os.kernel.events import EventLog
from research_os.scaffold import RESEARCH_BRIEF_TEMPLATE
from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "tests" / "fixtures" / "scientific_state" / "v1" / "m1b-contract.json"


def _configure_agent_files(project: Path) -> None:
    control = project / ".research-os"
    (control / "research-brief.md").write_text(
        RESEARCH_BRIEF_TEMPLATE.replace(
            "REPLACE_ME",
            "Configured M1-B service integration research",
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
                "reviewer": "m1b-service-integration-critic",
                "independent_reviewer": True,
                "verdict": "PASS",
                "summary": "All bounded evaluator controls passed.",
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


class M1BServiceCLITests(unittest.TestCase):
    def copy_project(
        self,
        *,
        certify: bool,
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, ResearchService]:
        temporary = tempfile.TemporaryDirectory()
        project = Path(temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        _configure_agent_files(project)
        service = ResearchService(project)
        subject = service.evaluator_review_subject()
        if certify:
            service.certify_evaluator(
                _passing_review(
                    Path(temporary.name) / "review.json",
                    subject_digest=str(subject["digest"]),
                )
            )
        return temporary, project, service

    def test_generation_commands_forward_exact_service_arguments(self) -> None:
        service = mock.Mock()
        service.open_generation.return_value = {
            "generation_id": "generation_fixture",
            "authorized_action": None,
        }
        service.study_status.return_value = {
            "active_generation_id": "generation_fixture",
            "authorized_action": None,
        }

        open_stdout = io.StringIO()
        status_stdout = io.StringIO()
        with mock.patch(
            "research_os.cli.ResearchService", return_value=service
        ), redirect_stdout(open_stdout):
            open_code = main(
                [
                    "--project",
                    "/tmp/project",
                    "open-generation",
                    "contract.json",
                    "--predecessor-generation-id",
                    "generation_prior",
                    "--change-reason",
                    "change the finite generation budget",
                ]
            )
        with mock.patch(
            "research_os.cli.ResearchService", return_value=service
        ), redirect_stdout(status_stdout):
            status_code = main(
                ["--project", "/tmp/project", "study-status"]
            )

        self.assertEqual(open_code, 0)
        self.assertEqual(status_code, 0)
        service.open_generation.assert_called_once_with(
            Path("contract.json"),
            predecessor_generation_id="generation_prior",
            change_reason="change the finite generation budget",
        )
        service.study_status.assert_called_once_with()
        self.assertIsNone(json.loads(open_stdout.getvalue())["authorized_action"])
        self.assertIsNone(json.loads(status_stdout.getvalue())["authorized_action"])

    def test_generation_open_is_idempotent_and_replay_visible(self) -> None:
        temporary, _, service = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)

        first = service.open_generation(CONTRACT_PATH)
        second = service.open_generation(CONTRACT_PATH)
        status = service.study_status()
        replay = service.replay()
        generation_events = [
            event
            for event in service.event_log.read()
            if event.event_type == "research.study_generation_opened.v1"
        ]

        self.assertTrue(first["appended"])
        self.assertEqual(first["appended_events"], 1)
        self.assertFalse(second["appended"])
        self.assertEqual(second["appended_events"], 0)
        self.assertEqual(first["generation_id"], second["generation_id"])
        self.assertEqual(status["active_generation_id"], first["generation_id"])
        self.assertEqual(
            replay["science"]["active_generation_id"],
            first["generation_id"],
        )
        self.assertEqual(len(generation_events), 1)
        self.assertIn("authorized_action", generation_events[0].payload)
        self.assertIsNone(generation_events[0].payload["authorized_action"])
        self.assertIsNone(first["authorized_action"])
        self.assertIsNone(second["authorized_action"])
        self.assertIsNone(status["authorized_action"])
        self.assertIsNone(replay["authorized_action"])

    def test_generation_open_requires_current_certification(self) -> None:
        temporary, _, service = self.copy_project(certify=False)
        self.addCleanup(temporary.cleanup)

        with self.assertRaises(EvaluatorCertificationError) as caught:
            service.open_generation(CONTRACT_PATH)

        self.assertEqual(caught.exception.code, "EVALUATOR_CERTIFICATION_REQUIRED")
        self.assertFalse(
            any(
                event.event_type == "research.study_generation_opened.v1"
                for event in service.event_log.read()
            )
        )

    def test_mapping_successor_requires_explicit_change_control(self) -> None:
        temporary, _, service = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        first = service.open_generation(contract)

        with self.assertRaises(ScientificStateError) as unchanged:
            service.open_generation(
                contract,
                predecessor_generation_id=str(first["generation_id"]),
                change_reason="attempt an unchanged budget reset",
            )
        self.assertEqual(unchanged.exception.code, "STUDY_GENERATION_UNCHANGED")

        contract["budget"]["max_attempts"] = 5
        successor = service.open_generation(
            contract,
            predecessor_generation_id=str(first["generation_id"]),
            change_reason="increase the preregistered generation budget",
        )
        self.assertNotEqual(first["generation_id"], successor["generation_id"])
        self.assertEqual(
            service.study_status()["active_generation_id"],
            successor["generation_id"],
        )
        self.assertEqual(
            len(
                [
                    event
                    for event in service.event_log.read()
                    if event.event_type == "research.study_generation_opened.v1"
                ]
            ),
            2,
        )

    def test_concurrent_identical_generation_open_commits_one_event(self) -> None:
        temporary, project, _ = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        append_barrier = Barrier(2)
        original_append = EventLog.append

        def append_after_barrier(event_log, event_type, *args, **kwargs):
            if event_type == "research.study_generation_opened.v1":
                append_barrier.wait(timeout=15)
            return original_append(event_log, event_type, *args, **kwargs)

        def open_one(_: int) -> dict[str, object]:
            return ResearchService(project).open_generation(CONTRACT_PATH)

        with mock.patch.object(EventLog, "append", new=append_after_barrier):
            with ThreadPoolExecutor(max_workers=2) as executor:
                results = list(executor.map(open_one, range(2)))

        events = ResearchService(project).event_log.read()
        generation_events = [
            event
            for event in events
            if event.event_type == "research.study_generation_opened.v1"
        ]
        self.assertEqual(
            {str(result["generation_id"]) for result in results},
            {str(generation_events[0].payload["generation_id"])},
        )
        self.assertEqual(sum(int(result["appended_events"]) for result in results), 1)
        self.assertEqual(len(generation_events), 1)

    def test_concurrent_divergent_successors_commit_one_child(self) -> None:
        temporary, project, service = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        first = service.open_generation(CONTRACT_PATH)
        append_barrier = Barrier(2)
        original_append = EventLog.append

        def append_after_barrier(event_log, event_type, *args, **kwargs):
            if event_type == "research.study_generation_opened.v1":
                append_barrier.wait(timeout=15)
            return original_append(event_log, event_type, *args, **kwargs)

        def open_successor(max_attempts: int) -> tuple[str, object]:
            contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
            contract["budget"]["max_attempts"] = max_attempts
            candidate_service = ResearchService(project)
            try:
                return (
                    "ok",
                    candidate_service.open_generation(
                        contract,
                        predecessor_generation_id=str(first["generation_id"]),
                        change_reason=f"set successor attempt budget to {max_attempts}",
                    ),
                )
            except ScientificStateError as exc:
                return ("error", exc)

        with mock.patch.object(EventLog, "append", new=append_after_barrier):
            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(open_successor, (5, 6)))

        successes = [value for kind, value in outcomes if kind == "ok"]
        failures = [value for kind, value in outcomes if kind == "error"]
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 1)
        self.assertIsInstance(failures[0], ScientificStateError)
        self.assertEqual(failures[0].code, "STUDY_GENERATION_MISMATCH")
        generation_events = [
            event
            for event in service.event_log.read()
            if event.event_type == "research.study_generation_opened.v1"
        ]
        self.assertEqual(len(generation_events), 2)
        self.assertEqual(
            service.study_status()["active_generation_id"],
            successes[0]["generation_id"],
        )

    def test_run_once_reserves_active_generation_budget_and_replay_matches(self) -> None:
        temporary, project, service = self.copy_project(certify=True)
        self.addCleanup(temporary.cleanup)
        contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
        contract["budget"].update(
            {
                "max_attempts": 1,
                "max_retries": 0,
                "max_elapsed_milliseconds": 1000,
                "max_cost_microunits": 2500,
            }
        )
        opened = service.open_generation(contract)
        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text('{"x":2.0}\n', encoding="utf-8")

        outcome = service.run_once(inbox)
        registration_events = [
            event
            for event in service.event_log.read()
            if event.event_type == "EXPERIMENT_REGISTERED"
        ]
        self.assertEqual(len(registration_events), 1)
        registration = registration_events[0].payload
        self.assertEqual(registration["generation_id"], opened["generation_id"])
        self.assertEqual(
            set(registration["budget_debit"]),
            {
                "attempts",
                "retries",
                "reserved_elapsed_milliseconds",
                "reserved_cost_microunits",
            },
        )
        self.assertEqual(
            registration["budget_debit"],
            {
                "attempts": 1,
                "retries": 0,
                "reserved_elapsed_milliseconds": 1000,
                "reserved_cost_microunits": 2500,
            },
        )
        self.assertIn("authorized_action", registration)
        self.assertIsNone(registration["authorized_action"])
        self.assertIsNone(outcome["authorized_action"])

        status = service.study_status()
        self.assertEqual(status["budget"]["attempts"]["used"], 1)
        self.assertEqual(status["budget"]["elapsed_milliseconds"]["reserved"], 1000)
        self.assertEqual(status["budget"]["cost_microunits"]["reserved"], 2500)
        self.assertEqual(
            service.lineage()[0]["generation_id"],
            opened["generation_id"],
        )

        inbox.write_text('{"x":3.0}\n', encoding="utf-8")
        with self.assertRaises(ScientificStateError) as exhausted:
            service.run_once(inbox)
        self.assertEqual(exhausted.exception.code, "BUDGET_ATTEMPTS_EXCEEDED")
        self.assertEqual(
            len(
                [
                    event
                    for event in service.event_log.read()
                    if event.event_type == "EXPERIMENT_REGISTERED"
                ]
            ),
            1,
        )
        replay = service.replay()
        replay_status = service.study_status()
        expected_science = {
            key: value
            for key, value in replay_status.items()
            if key not in {"project_id", "authorized_action"}
        }
        self.assertEqual(replay["science"], expected_science)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
