from __future__ import annotations

import copy
import io
import json
import shutil
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

import pytest

from research_os.cli import main
from research_os.contracts import canonical_json_bytes
from research_os.errors import ScientificStateError
from research_os.execution.workspace import hash_tree
from research_os.science import reduce_scientific_state
from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]
V3_FIXTURES = ROOT / "tests" / "fixtures" / "scientific_state" / "v3"
AUTHOR_FIELDS = ("interpretation", "failure_type", "falsifier", "recommendation")


def _json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _history(record_id: str = "timed-out") -> list[dict[str, Any]]:
    records = _json(V3_FIXTURES / "m1d-terminal-corpus.json")["records"]
    selected = next(item for item in records if item["id"] == record_id)
    return copy.deepcopy(selected["canonical_history"])


def _multi_pending_history() -> list[dict[str, Any]]:
    cases = _json(V3_FIXTURES / "m1d-transition-matrix.json")["full_state_cases"]
    selected = next(
        item for item in cases if item["id"] == "terminal-order-pending-untrusted-budget-stop"
    )
    return copy.deepcopy(selected["input"]["event_history"])


def _valid_diagnosis(case_id: str = "retryable-timeout") -> dict[str, Any]:
    cases = _json(V3_FIXTURES / "m1d-diagnosis-valid.json")["cases"]
    selected = next(item for item in cases if item["id"] == case_id)
    return copy.deepcopy(selected["diagnosis_event"]["payload"]["diagnosis"])


def _service(tmp_path: Path, history: list[dict[str, Any]]) -> tuple[Path, ResearchService]:
    project = tmp_path / "project"
    shutil.copytree(ROOT / "examples" / "toy_optimization", project)
    runtime = project / ".research-os" / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    config = project / ".research-os" / "project.toml"
    config.write_text(
        config.read_text(encoding="utf-8").replace(
            'id = "toy-optimization"',
            'id = "fixture-m1d"',
        ),
        encoding="utf-8",
    )
    service = ResearchService(project)
    for raw in history:
        event = service.event_log.append(
            raw["event_type"],
            raw["payload"],
            event_id=raw["event_id"],
            occurred_at=raw["occurred_at"],
        )
        assert event.to_dict() == raw
    service.projection.rebuild(service.event_log)
    return project, service


def test_context_v3_exposes_exact_scientific_state_and_preserves_v2(tmp_path: Path) -> None:
    _, service = _service(tmp_path, _history())
    events_before = service.event_log.path.read_bytes()
    projection_before = service.projection.path.read_bytes()
    tree_before = hash_tree(service.config.root)
    context = service.agent_context(schema_version=3)
    assert service.event_log.path.read_bytes() == events_before
    assert service.projection.path.read_bytes() == projection_before
    assert hash_tree(service.config.root) == tree_before

    default_v2 = service.agent_context()
    explicit_v2 = service.agent_context(schema_version=2)
    scientific_state = reduce_scientific_state(
        service.event_log.read(), project_id=service.config.project_id
    ).to_dict()

    assert default_v2 == explicit_v2
    assert default_v2["schema_version"] == 2
    assert "science" not in default_v2
    assert context["schema_version"] == 3
    assert context["science"] == scientific_state
    assert context["science"]["pending_diagnosis_experiment_ids"]
    assert context["diagnosis_authoring"]["command"] == "diagnosis-template"
    assert "AUTHOR_PENDING_DIAGNOSIS" in context["allowed_agent_actions"]
    assert context["authority"]["authorized_action"] is None
    assert context["packet_size_bytes"] == len(canonical_json_bytes(context))


def test_template_fills_kernel_fields_then_diagnose_refreshes_context(tmp_path: Path) -> None:
    _, service = _service(tmp_path, _history())
    expected = _valid_diagnosis()
    events_before = service.event_log.path.read_bytes()
    projection_before = service.projection.path.read_bytes()

    template = service.diagnosis_template()

    for key, value in expected.items():
        if key not in AUTHOR_FIELDS:
            assert template[key] == value
    assert all(str(template[key]).startswith("REPLACE_ME") for key in AUTHOR_FIELDS)
    assert template["authorized_action"] is None
    assert service.event_log.path.read_bytes() == events_before
    assert service.projection.path.read_bytes() == projection_before

    for omitted in AUTHOR_FIELDS:
        incomplete = copy.deepcopy(template)
        for key in AUTHOR_FIELDS:
            if key != omitted:
                incomplete[key] = expected[key]
        with pytest.raises(ScientificStateError) as sentinel:
            service.record_diagnosis(incomplete)
        assert sentinel.value.code == "DIAGNOSIS_INVALID"
        assert service.event_log.path.read_bytes() == events_before

    diagnosis = copy.deepcopy(template)
    for key in AUTHOR_FIELDS:
        diagnosis[key] = expected[key]
    result = service.record_diagnosis(diagnosis)
    refreshed = service.agent_context(schema_version=3)

    assert result["appended"] is True
    assert refreshed["science"]["pending_diagnosis_experiment_ids"] == []
    assert "AUTHOR_PENDING_DIAGNOSIS" not in refreshed["allowed_agent_actions"]
    assert refreshed["science"]["class_states"]
    assert refreshed["science"]["retry_frontier"] == service.study_status()[
        "retry_frontier"
    ]


def test_template_selection_is_fail_closed_and_read_only(tmp_path: Path) -> None:
    _, multi = _service(tmp_path / "multi", _multi_pending_history())
    before = multi.event_log.path.read_bytes()
    with pytest.raises(ScientificStateError) as multiple:
        multi.diagnosis_template()
    assert multiple.value.code == "DIAGNOSIS_TEMPLATE_EXPERIMENT_REQUIRED"
    assert multi.event_log.path.read_bytes() == before

    _, service = _service(tmp_path / "single", _history())
    with pytest.raises(ScientificStateError) as unknown:
        service.diagnosis_template("experiment_00000000000000000000000000000000")
    assert unknown.value.code == "DIAGNOSIS_TEMPLATE_EXPERIMENT_UNKNOWN"

    service.record_diagnosis(_valid_diagnosis())
    with pytest.raises(ScientificStateError) as none_pending:
        service.diagnosis_template()
    assert none_pending.value.code == "DIAGNOSIS_TEMPLATE_NONE_PENDING"
    with pytest.raises(ScientificStateError) as already_closed:
        service.diagnosis_template(_valid_diagnosis()["experiment_id"])
    assert already_closed.value.code == "DIAGNOSIS_TEMPLATE_EXPERIMENT_NOT_PENDING"


def test_context_v3_and_template_are_available_through_cli(tmp_path: Path) -> None:
    project, service = _service(tmp_path, _history())
    expected_context = service.agent_context(schema_version=3)
    expected_template = service.diagnosis_template()

    context_stdout = io.StringIO()
    template_stdout = io.StringIO()
    stderr = io.StringIO()
    with redirect_stdout(context_stdout), redirect_stderr(stderr):
        context_code = main(
            [
                "--project",
                str(project),
                "agent-context",
                "--schema-version",
                "3",
            ]
        )
    with redirect_stdout(template_stdout), redirect_stderr(stderr):
        template_code = main(["--project", str(project), "diagnosis-template"])

    assert context_code == template_code == 0
    assert stderr.getvalue() == ""
    assert json.loads(context_stdout.getvalue()) == expected_context
    assert json.loads(template_stdout.getvalue()) == expected_template
