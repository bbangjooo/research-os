"""DiscoveryService appends advisory notes without touching canonical state."""

from __future__ import annotations

import contextlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from research_os.cli import main
from research_os.contracts import sha256_json
from research_os.discovery import DISCOVERY_NOTE_EVENT_TYPE
from research_os.discovery_service import DiscoveryService
from research_os.errors import ScientificStateError
from research_os.science.state import reduce_scientific_state
from research_os.service import ResearchService
from tests.test_m1b_service_cli import (
    RESEARCH_BRIEF_TEMPLATE,
    ROOT,
    _configure_agent_files,
    _passing_review,
)


def _anomaly(summary: str = "Residual drift persists after the sweep.") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "anomaly",
        "body": {
            "summary": summary,
            "evidence_refs": ["experiment_0001"],
            "open_question": "Is the drift an artifact of the holdout split?",
        },
        "refs": ["diagnosis_0001"],
        "analogy_query_digest": None,
        "authorized_action": None,
    }


def _draft(mechanism: str = "Replace the stationary prior with a two-regime mixture") -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "rival_draft",
        "body": {
            "rival_id": "rival_alpha",
            "label": "Latent regime switch",
            "assumptions": ["The generating process is stationary"],
            "mechanism": mechanism,
            "predictions": ["Residual drift disappears inside each regime"],
            "falsifiers": ["Drift persists after conditioning on the regime label"],
            "uncertainty": "Regime boundaries are not directly observed.",
        },
        "refs": ["experiment_0001"],
        "analogy_query_digest": None,
        "authorized_action": None,
    }


class DiscoveryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", self.project)
        runtime = self.project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        _configure_agent_files(self.project)
        # doctor() writes PROJECT_INITIALIZED; the advisory lane deliberately does
        # not bootstrap canonical project state on its own.
        ResearchService(self.project).doctor()
        self.service = DiscoveryService(self.project)

    def _write(self, name: str, body: dict[str, Any]) -> Path:
        path = Path(self.temporary.name) / name
        path.write_text(json.dumps(body, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def test_note_appends_one_advisory_event(self) -> None:
        result = self.service.note(_anomaly())

        self.assertTrue(result["appended"])
        self.assertEqual(result["appended_events"], 1)
        self.assertEqual(result["event_type"], DISCOVERY_NOTE_EVENT_TYPE)
        self.assertEqual(result["lane"], "advisory")
        self.assertIsNone(result["authorized_action"])
        self.assertIsNone(result["note"]["analogy_query_digest"])

    def test_identical_bodies_append_twice(self) -> None:
        first = self.service.note(_anomaly())
        second = self.service.note(_anomaly())

        self.assertNotEqual(first["note_id"], second["note_id"])
        self.assertNotEqual(first["event_id"], second["event_id"])
        self.assertEqual(self.service.status()["note_count"], 2)

    def test_status_matches_cold_replay(self) -> None:
        self.service.note(_anomaly())
        self.service.note(_draft())
        live = self.service.status()

        cold = DiscoveryService(self.project).status()
        self.assertEqual(live, cold)

    def test_status_filters_by_kind_and_limit(self) -> None:
        self.service.note(_anomaly("first"))
        self.service.note(_anomaly("second"))
        self.service.note(_draft())

        drafts = self.service.status(kind="rival_draft")
        self.assertEqual(drafts["returned_count"], 1)
        self.assertEqual(drafts["note_count"], 3)

        recent = self.service.status(limit=1)
        self.assertEqual(recent["returned_count"], 1)
        self.assertEqual(recent["notes"][0]["kind"], "rival_draft")

    def test_duplicate_draft_is_refused_by_the_service(self) -> None:
        self.service.note(_draft())
        with self.assertRaises(ScientificStateError) as caught:
            self.service.note(_draft("REPLACE   the stationary prior with a two-regime mixture"))
        self.assertEqual(caught.exception.code, "DISCOVERY_DRAFT_NOT_DISTINCT")

    def test_discovery_events_do_not_change_scientific_state(self) -> None:
        research = ResearchService(self.project)
        before = reduce_scientific_state(
            tuple(research.event_log.read()),
            project_id=research.config.project_id,
        ).to_dict()

        self.service.note(_anomaly())
        self.service.note(_draft())

        after = reduce_scientific_state(
            tuple(research.event_log.read()),
            project_id=research.config.project_id,
        ).to_dict()
        self.assertEqual(before, after)

    def test_projections_are_read_only(self) -> None:
        self.service.note(_anomaly())
        research = ResearchService(self.project)
        before = [event.hash for event in research.event_log.read()]

        self.service.exhaustion()
        self.service.residual()
        self.service.yield_curve()

        after = [event.hash for event in research.event_log.read()]
        self.assertEqual(before, after)

    def test_exhaustion_projection_refuses_advisory_only_conditions(self) -> None:
        self.service.note(_anomaly())
        self.service.note({**_anomaly(), "kind": "assumption_conflict"})

        projection = self.service.exhaustion()
        self.assertEqual(projection["canonical_signal_kinds"], [])
        self.assertFalse(projection["inquiry_signal_conditions_met"])

    def test_yield_curve_reports_the_draft_measurement(self) -> None:
        self.service.note(_draft())
        curve = self.service.yield_curve()

        self.assertEqual(curve["rival_draft_count"], 1)
        self.assertEqual(curve["distinct_rival_fingerprints"], 1)
        self.assertIsNone(curve["authorized_action"])

    def test_there_is_no_edit_or_delete_path(self) -> None:
        self.assertFalse(hasattr(self.service, "edit"))
        self.assertFalse(hasattr(self.service, "delete"))
        self.assertFalse(hasattr(self.service, "amend"))


class DiscoveryCLITests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", self.project)
        runtime = self.project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        _configure_agent_files(self.project)
        ResearchService(self.project).doctor()

    def _write(self, name: str, body: dict[str, Any]) -> Path:
        path = Path(self.temporary.name) / name
        path.write_text(json.dumps(body, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _run(self, *args: str) -> dict[str, Any]:
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(["--project", str(self.project), *args])
        self.assertEqual(code, 0, stream.getvalue())
        payload = json.loads(stream.getvalue())
        assert isinstance(payload, dict)
        return payload

    def _usage_error(self, *args: str) -> None:
        """Assert the CLI refuses these arguments with its usage exit code."""

        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(["--project", str(self.project), *args])
        self.assertEqual(code, 2, stream.getvalue())

    def test_note_and_status_round_trip(self) -> None:
        note_path = self._write("note.json", _anomaly())
        appended = self._run("discovery-note", str(note_path))
        self.assertTrue(appended["appended"])

        status = self._run("discovery-status")
        self.assertEqual(status["note_count"], 1)
        self.assertEqual(status["lane"], "advisory")

    def test_status_views_are_mutually_exclusive_and_dispatch(self) -> None:
        note_path = self._write("note.json", _anomaly())
        self._run("discovery-note", str(note_path))

        exhaustion = self._run("discovery-status", "--exhaustion")
        self.assertIn("canonical_signal_kinds", exhaustion)

        residual = self._run("discovery-status", "--residual")
        self.assertIn("residual_tasks", residual)

        curve = self._run("discovery-status", "--yield")
        self.assertIn("distinct_rival_fingerprints", curve)

        self._usage_error("discovery-status", "--exhaustion", "--yield")

    def test_kind_filter_rejects_an_unknown_kind(self) -> None:
        self._usage_error("discovery-status", "--kind", "speculation")

    def test_analogies_requires_an_explicit_program_store(self) -> None:
        query_path = self._write("query.json", {"unused": True})
        self._usage_error("discovery-analogies", str(query_path))


if __name__ == "__main__":  # pragma: no cover - convenience runner
    unittest.main()


class ClosedClassResidualTests(unittest.TestCase):
    """Drive a real hypothesis class to closure, then read the residual task.

    ``test_residual_task_is_empty_without_a_closed_class`` covers the empty
    path.  Nothing else exercises the populated one, so the instruction could
    stop naming the evidence it is derived from without a test noticing.  This
    runs the real adapter, the real decision, and real Diagnoses; the only
    fixture concession is advertising the v2 evaluation-scope capability on the
    example adapter, exactly as the M1-C manifest oracle does.
    """

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", self.project)
        control = self.project / ".research-os"
        shutil.rmtree(control / "runtime", ignore_errors=True)

        adapter = control / "adapter.py"
        source = adapter.read_text(encoding="utf-8")
        legacy = 'payload={"capabilities": sorted(OPERATIONS), "side_effects": []},'
        scoped = (
            'payload={"capabilities": sorted(OPERATIONS | {"evaluation_scope_v1"}), '
            '"side_effects": []},'
        )
        self.assertEqual(source.count(legacy), 1)
        adapter.write_text(source.replace(legacy, scoped), encoding="utf-8")

        fixtures = ROOT / "tests" / "fixtures" / "scientific_state"
        (control / "candidate.schema.json").write_bytes(
            (fixtures / "v2" / "m1c-candidate-schema.json").read_bytes()
        )
        (control / "research-brief.md").write_text(
            RESEARCH_BRIEF_TEMPLATE.replace("REPLACE_ME", "Closed-class residual task"),
            encoding="utf-8",
        )
        (self.project / "parameter.json").write_text('{"x": 0.0, "y": 0.0}\n', encoding="utf-8")

        self.service = ResearchService(self.project)
        subject = self.service.evaluator_review_subject()
        self.service.certify_evaluator(
            _passing_review(
                Path(self.temporary.name) / "review.json",
                subject_digest=str(subject["digest"]),
            ),
            replace=True,
        )
        self.service.open_generation(fixtures / "v3" / "m1d-contract.json")
        self.service.baseline(evaluation_scope_id="development")

    def _write(self, name: str, body: dict[str, Any]) -> Path:
        path = Path(self.temporary.name) / name
        path.write_text(json.dumps(body, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def _reject(self, tag: str, x: float, mechanism: str) -> None:
        candidate = {"x": x, "y": 0.0}
        proposal = {
            "proposal_schema_version": 1,
            "generation_id": self.service.study_status()["active_generation_id"],
            "candidate_digest": sha256_json(candidate),
            "hypothesis_class_id": "class-a",
            "action": "explore",
            "mechanism": mechanism,
            "predicted_effect": "The primary metric improves against the same-scope baseline.",
            "falsifier": "The sealed evaluation shows no positive primary-metric improvement.",
            "parent_experiment_id": None,
            "evaluation_scope_id": "development",
            "intervention_json_pointers": ["/x"],
            "authorized_action": None,
        }
        result = self.service.run_once(
            self._write(f"candidate-{tag}.json", candidate),
            proposal=self._write(f"proposal-{tag}.json", proposal),
        )
        self.assertEqual(result["decision"]["reason_code"], "NO_MEANINGFUL_IMPROVEMENT")

        body = dict(self.service.diagnosis_template())
        body["interpretation"] = (
            "The sealed evaluation moved the primary metric away from the same-scope "
            "baseline, so this class-a direction is refuted."
        )
        body["failure_type"] = "mechanism"
        body["falsifier"] = (
            "A repeat at the same scope shows a positive primary-metric margin for "
            "this same /x direction."
        )
        body["recommendation"] = "stop"
        self.service.record_diagnosis(self._write(f"diagnosis-{tag}.json", body))

    def test_residual_task_names_the_failed_mechanisms_of_a_closed_class(self) -> None:
        self._reject("1", -0.05, "Shift /x negatively to test the class-a direction.")
        self._reject("2", -0.4, "Shift /x further negative at larger scale.")

        closed = [
            row["class_state"]
            for row in self.service.study_status()["class_states"]
            if row["class_state"]["lifecycle"] == "closed"
        ]
        self.assertEqual([row["hypothesis_class_id"] for row in closed], ["class-a"])
        self.assertEqual(closed[0]["closure_reason"], "CONCLUSIVE_REJECTION_LIMIT_REACHED")

        projection = DiscoveryService(self.project).residual()
        tasks = projection["residual_tasks"]
        self.assertEqual(len(tasks), 1)
        task = tasks[0]
        self.assertEqual(task["hypothesis_class_id"], "class-a")
        self.assertEqual(task["closure_reason"], "CONCLUSIVE_REJECTION_LIMIT_REACHED")
        self.assertEqual(task["failed_attempt_count"], 2)
        mechanisms = [row["mechanism"] for row in task["failed_attempts"]]
        self.assertIn("Shift /x negatively to test the class-a direction.", mechanisms)
        self.assertIn("commitment", task["instruction"])
        self.assertIsNone(projection["authorized_action"])

    def test_exhaustion_reports_canonical_kinds_once_a_class_closes(self) -> None:
        self._reject("1", -0.05, "Shift /x negatively to test the class-a direction.")
        self._reject("2", -0.4, "Shift /x further negative at larger scale.")

        projection = DiscoveryService(self.project).exhaustion()
        self.assertEqual(
            projection["canonical_signal_kinds"], ["class_closure", "repeated_failure"]
        )
        self.assertEqual(projection["closed_hypothesis_class_ids"], ["class-a"])
        # Two canonical kinds satisfy the gate without any advisory note.
        self.assertTrue(projection["inquiry_signal_conditions_met"])
