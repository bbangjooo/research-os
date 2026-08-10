"""Run the M1-E Context v3 and Diagnosis authoring slice in a temp project."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "scientific_state" / "v3"
AUTHOR_FIELDS = ("interpretation", "failure_type", "falsifier", "recommendation")


def load_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected one JSON object: {path}")
    return value


def main() -> None:
    corpus = load_object(FIXTURES / "m1d-terminal-corpus.json")
    record = next(item for item in corpus["records"] if item["id"] == "timed-out")
    valid = load_object(FIXTURES / "m1d-diagnosis-valid.json")
    diagnosis_case = next(
        item for item in valid["cases"] if item["id"] == "retryable-timeout"
    )
    expected = diagnosis_case["diagnosis_event"]["payload"]["diagnosis"]

    with tempfile.TemporaryDirectory(prefix="research-os-m1e-demo-") as temporary:
        project = Path(temporary) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", project)
        shutil.rmtree(project / ".research-os" / "runtime", ignore_errors=True)
        config = project / ".research-os" / "project.toml"
        config.write_text(
            config.read_text(encoding="utf-8").replace(
                'id = "toy-optimization"',
                'id = "fixture-m1d"',
            ),
            encoding="utf-8",
        )
        service = ResearchService(project)
        for raw in record["canonical_history"]:
            service.event_log.append(
                raw["event_type"],
                raw["payload"],
                event_id=raw["event_id"],
                occurred_at=raw["occurred_at"],
            )
        service.projection.rebuild(service.event_log)

        before = service.agent_context(schema_version=3)
        template = service.diagnosis_template()
        diagnosis = copy.deepcopy(template)
        for field in AUTHOR_FIELDS:
            diagnosis[field] = expected[field]
        recorded = service.record_diagnosis(diagnosis)
        after = service.agent_context(schema_version=3)

        print(
            json.dumps(
                {
                    "temporary_project": str(project),
                    "before": {
                        "schema_version": before["schema_version"],
                        "pending": before["science"][
                            "pending_diagnosis_experiment_ids"
                        ],
                        "allowed_agent_actions": before["allowed_agent_actions"],
                    },
                    "template": template,
                    "diagnose_result": recorded,
                    "after": {
                        "pending": after["science"][
                            "pending_diagnosis_experiment_ids"
                        ],
                        "class_states": after["science"]["class_states"],
                        "semantic_frontier": after["science"]["semantic_frontier"],
                        "retry_frontier": after["science"]["retry_frontier"],
                    },
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    main()
