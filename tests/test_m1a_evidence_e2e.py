from __future__ import annotations

import io
import json
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from research_os.certification import (
    EVALUATOR_REVIEW_KIND,
    REQUIRED_EVALUATOR_CHECK_IDS,
)
from research_os.cli import main
from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]


def _passing_review(subject_digest: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": EVALUATOR_REVIEW_KIND,
        "subject_digest": subject_digest,
        "reviewer": "independent-m1a-e2e-fixture",
        "independent_reviewer": True,
        "verdict": "PASS",
        "summary": "Fixture review passed every required evaluator check.",
        "checks": [
            {
                "id": check_id,
                "status": "PASS",
                "evidence": f"fixture evidence for {check_id}",
            }
            for check_id in sorted(REQUIRED_EVALUATOR_CHECK_IDS)
        ],
        "blocking_findings": [],
    }


def _run_cli(project: Path, *arguments: str) -> dict[str, object]:
    stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        exit_code = main(["--project", str(project), *arguments])
    assert exit_code == 0, stderr.getvalue()
    assert stderr.getvalue() == ""
    value = json.loads(stdout.getvalue())
    assert isinstance(value, dict)
    return value


def _authority_values(value: object) -> list[object]:
    found: list[object] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "authorized_action":
                found.append(item)
            found.extend(_authority_values(item))
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for item in value:
            found.extend(_authority_values(item))
    return found


def _copy_project() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary = tempfile.TemporaryDirectory()
    project = Path(temporary.name) / "project"
    shutil.copytree(ROOT / "examples" / "toy_optimization", project)
    runtime = project / ".research-os" / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    constitution = project / ".research-os" / "constitution.toml"
    original = constitution.read_text(encoding="utf-8")
    gate = '''

[[promotion.gates]]
id = "minimum-distance"
metric = "distance"
role = "hard"
operator = "gte"
threshold = 2.0
unit = "distance"
scale = 2.0
'''
    constitution.write_text(original + gate, encoding="utf-8")
    return temporary, project


def test_m1a_changed_surfaces_keep_authority_null():
    temporary, project = _copy_project()
    try:
        inspected = _run_cli(project, "inspect")
        assert inspected["promotion"] == {
            "minimum_improvement": 0.0,
            "gates": [
                {
                    "id": "minimum-distance",
                    "metric": "distance",
                    "role": "hard",
                    "operator": "gte",
                    "threshold": 2.0,
                    "unit": "distance",
                    "scale": 2.0,
                }
            ],
        }
        doctor = _run_cli(project, "doctor")
        subject = _run_cli(project, "evaluator-review-subject")

        review_path = Path(temporary.name) / "review.json"
        review_path.write_text(
            json.dumps(_passing_review(str(subject["digest"])), sort_keys=True) + "\n",
            encoding="utf-8",
        )
        certification = _run_cli(
            project,
            "certify-evaluator",
            str(review_path),
        )
        assert certification["certified"] is True
        assert certification["current"] is True

        baseline = _run_cli(project, "baseline")
        assert len(baseline["verifications"]) == 2
        outcome = _run_cli(
            project,
            "run-once",
            str(project / "candidates" / "improve.json"),
        )

        decision = outcome["decision"]
        assert decision["status"] == "REJECTED"
        assert decision["reason_code"] == "HARD_CONSTRAINT_FAILED"
        assert decision["improvement"] == 8.0
        assert decision["promotion_margin"] == 8.0
        assert decision["gate_evaluations"] == [
            {
                "id": "minimum-distance",
                "metric": "distance",
                "role": "hard",
                "operator": "gte",
                "threshold": 2.0,
                "unit": "distance",
                "scale": 2.0,
                "observed": 1.0,
                "signed_slack": -1.0,
                "normalized_slack": -0.5,
                "passed": False,
            }
        ]

        service = ResearchService(project)
        event_payloads = [event.payload for event in service.event_log.read()]
        changed_cli_surfaces = (
            inspected,
            doctor,
            subject,
            certification,
            baseline,
            outcome,
        )
        authority_values = _authority_values(
            {"cli": changed_cli_surfaces, "events": event_payloads}
        )
        assert len(authority_values) >= 6
        assert all(value is None for value in authority_values)

        # These certification surfaces intentionally carry no action field at
        # all; their complete enumeration above prevents a zero-denominator
        # authority claim from being mistaken for a scan omission.
        assert _authority_values(subject) == []
        assert _authority_values(certification) == []
    finally:
        temporary.cleanup()
