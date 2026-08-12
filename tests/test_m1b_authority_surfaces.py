from __future__ import annotations

import io
import json
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from research_os.cli import main
from research_os.service import ResearchService
from tests.test_m1b_service_cli import (
    CONTRACT_PATH,
    ROOT,
    _configure_agent_files,
    _passing_review,
)


def _cli_json(project: Path, *arguments: str) -> dict[str, Any]:
    output = io.StringIO()
    with redirect_stdout(output):
        code = main(["--project", str(project), *arguments])
    assert code == 0
    value = json.loads(output.getvalue())
    assert isinstance(value, dict)
    return value


def _authority_values(value: Any) -> list[Any]:
    observed: list[Any] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if key == "authorized_action":
                observed.append(item)
            observed.extend(_authority_values(item))
    elif isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        for item in value:
            observed.extend(_authority_values(item))
    return observed


def test_all_eight_changed_service_event_decision_and_cli_surfaces_are_null() -> None:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        project = root / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        _configure_agent_files(project)
        service = ResearchService(project)
        subject = service.evaluator_review_subject()
        service.certify_evaluator(
            _passing_review(
                root / "review.json",
                subject_digest=str(subject["digest"]),
            )
        )

        opened = service.open_generation(CONTRACT_PATH)
        opened_cli = _cli_json(project, "open-generation", str(CONTRACT_PATH))
        first_outcome = service.run_once(project / "candidates" / "improve.json")
        generation_event = next(
            event
            for event in service.event_log.read()
            if event.event_type == "research.study_generation_opened.v1"
        )
        registration_event = next(
            event
            for event in service.event_log.read()
            if event.event_type == "EXPERIMENT_REGISTERED"
        )
        second_candidate = root / "second-candidate.json"
        second_candidate.write_text('{"x":3.0}\n', encoding="utf-8")
        second_outcome_cli = _cli_json(
            project,
            "run-once",
            str(second_candidate),
        )
        study_status_cli = _cli_json(project, "study-status")
        replay_cli = _cli_json(project, "replay")

        surfaces = {
            "generation_event_payload": generation_event.payload,
            "open_generation_service_result": opened,
            "open_generation_cli_json": opened_cli,
            "experiment_registration_payload": registration_event.payload,
            "run_once_service_result": first_outcome,
            "run_once_cli_json": second_outcome_cli,
            "study_status_cli_json": study_status_cli,
            "replay_cli_json": replay_cli,
        }
        manifest = json.loads(
            (
                ROOT
                / "tests"
                / "fixtures"
                / "scientific_state"
                / "v1"
                / "manifest.json"
            ).read_text(encoding="utf-8")
        )
        authority_case = next(
            case
            for case in manifest["cases"]
            if case["id"] == "authority-null-changed-surfaces"
        )
        assert list(surfaces) == authority_case["input"]["surfaces"]
        assert len(surfaces) == authority_case["expected"]["surface_count"] == 8
        assert sum("authorized_action" in surface for surface in surfaces.values()) == 8
        assert all(surface["authorized_action"] is None for surface in surfaces.values())
        for outcome in (first_outcome, second_outcome_cli):
            decision = outcome.get("decision")
            assert isinstance(decision, Mapping)
            assert "authorized_action" in decision
            assert decision["authorized_action"] is None
        recursive_values = [
            authority
            for surface in surfaces.values()
            for authority in _authority_values(surface)
        ]
        assert recursive_values
        assert all(authority is None for authority in recursive_values)
