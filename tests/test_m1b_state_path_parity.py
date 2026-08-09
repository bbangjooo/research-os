from __future__ import annotations

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from research_os.contracts import Operation, ProtocolResponse, TerminalStatus
from research_os.errors import ScientificStateError
from research_os.science import reduce_scientific_state
from research_os.service import ResearchService
from tests.test_m1b_service_cli import (
    CONTRACT_PATH,
    ROOT,
    _configure_agent_files,
    _passing_review,
)


def _certified_project() -> tuple[tempfile.TemporaryDirectory[str], Path, ResearchService]:
    temporary = tempfile.TemporaryDirectory()
    project = Path(temporary.name) / "project"
    shutil.copytree(ROOT / "examples" / "toy_optimization", project)
    runtime = project / ".research-os" / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    _configure_agent_files(project)
    service = ResearchService(project)
    subject = service.evaluator_review_subject()
    service.certify_evaluator(
        _passing_review(
            Path(temporary.name) / "review.json",
            subject_digest=str(subject["digest"]),
        )
    )
    return temporary, project, service


def test_post_append_cold_replay_and_projection_rebuild_states_match_exactly() -> None:
    temporary, project, service = _certified_project()
    try:
        opened = service.open_generation(CONTRACT_PATH)
        original_call = service._call_sealed
        failed = False

        def fail_first_run(report, operation, **kwargs):
            nonlocal failed
            if operation is Operation.RUN and not failed:
                failed = True
                return ProtocolResponse.failure(
                    request_id="req_m1b_parity_failure",
                    error={
                        "category": "INFRASTRUCTURE",
                        "code": "TRANSIENT_M1B_PARITY_FAILURE",
                        "message": "injected retryable parity failure",
                    },
                    retryable=True,
                )
            return original_call(report, operation, **kwargs)

        with patch.object(service, "_call_sealed", side_effect=fail_first_run):
            first = service.run_once(project / "candidates" / "improve.json")
        assert first["status"] == TerminalStatus.INFRA_FAILED.value
        second = service.run_once(
            project / "candidates" / "improve.json",
            retry_of=str(first["experiment_id"]),
        )
        assert second["status"] == TerminalStatus.VALIDATED.value

        post_append = service.study_status()
        cold = reduce_scientific_state(
            service.event_log.read(),
            project_id=service.config.project_id,
        ).to_dict()
        assert service.projection.rebuild(service.event_log) == len(
            service.event_log.read()
        )
        after_rebuild = service.study_status()
        replay = service.replay()
        comparable_post_append = {
            key: value
            for key, value in post_append.items()
            if key not in {"project_id", "authorized_action"}
        }
        comparable_rebuild = {
            key: value
            for key, value in after_rebuild.items()
            if key not in {"project_id", "authorized_action"}
        }

        assert comparable_post_append == cold == comparable_rebuild == replay["science"]
        assert cold["active_generation_id"] == opened["generation_id"]
        assert cold["budget"]["attempts"]["used"] == 2
        assert cold["budget"]["retries"]["used"] == 1
        assert cold["budget"]["elapsed_milliseconds"]["reserved"] == 2000
        assert cold["budget"]["cost_microunits"]["reserved"] == 5000
        assert {
            row["generation_id"] for row in service.projection.candidate_attempts(
                service.config.project_id,
                str(service.lineage()[0]["candidate_digest"]),
                None,
                str(service.lineage()[0]["compatibility_digest"]),
                generation_id=str(opened["generation_id"]),
            )
        } == {opened["generation_id"]}
    finally:
        temporary.cleanup()


def test_service_replay_rejects_a_direct_unbound_append_after_generation() -> None:
    temporary, _, service = _certified_project()
    try:
        service.open_generation(CONTRACT_PATH)
        compatibility = service.doctor().fingerprints["compatibility_digest"]
        service.event_log.append(
            "EXPERIMENT_REGISTERED",
            {
                "experiment_id": "exp_direct_unbound",
                "parent_id": None,
                "candidate_digest": "a" * 64,
                "compatibility_digest": compatibility,
                "attempt": 1,
                "retry_of": None,
                "status": "registered",
                "authorized_action": None,
            },
        )

        with pytest.raises(ScientificStateError) as caught:
            service.replay()
        assert caught.value.code == "STUDY_GENERATION_REQUIRED"
    finally:
        temporary.cleanup()
