from __future__ import annotations

import io
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from threading import Barrier
from unittest import mock

import pytest

from research_os.certification import REQUIRED_EVALUATOR_CHECK_IDS
from research_os.cli import main
from research_os.contracts import Operation, ProtocolResponse, TerminalStatus
from research_os.errors import ScientificStateError
from research_os.scaffold import RESEARCH_BRIEF_TEMPLATE
from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]
V2_FIXTURES = ROOT / "tests" / "fixtures" / "scientific_state" / "v2"


def _scoped_project(tmp_path: Path) -> tuple[Path, ResearchService, dict[str, object]]:
    project = tmp_path / "project"
    shutil.copytree(ROOT / "examples" / "toy_optimization", project)
    runtime = project / ".research-os" / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    control = project / ".research-os"
    (control / "research-brief.md").write_text(
        RESEARCH_BRIEF_TEMPLATE.replace(
            "REPLACE_ME",
            "Configured M1-C typed Proposal service integration research",
        ),
        encoding="utf-8",
    )
    shutil.copy2(
        V2_FIXTURES / "m1c-candidate-schema.json",
        control / "candidate.schema.json",
    )
    adapter = control / "adapter.py"
    adapter_source = adapter.read_text(encoding="utf-8")
    adapter.write_text(
        adapter_source.replace(
            '    "fingerprint",\n',
            '    "fingerprint",\n    "evaluation_scope_v1",\n',
            1,
        ),
        encoding="utf-8",
    )
    service = ResearchService(project)
    subject = service.evaluator_review_subject()
    review = tmp_path / "review.json"
    review.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "research-os-evaluator-review",
                "subject_digest": subject["digest"],
                "reviewer": "m1c-service-integration-critic",
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
    service.certify_evaluator(review)
    opened = service.open_generation(V2_FIXTURES / "m1c-contract.json")
    proposal = json.loads(
        (V2_FIXTURES / "m1c-proposal-explore.json").read_text(encoding="utf-8")
    )
    proposal["generation_id"] = opened["generation_id"]
    return project, service, proposal


def test_baseline_scope_option_is_forwarded_without_changing_legacy_call_shape() -> None:
    service = mock.Mock()
    service.baseline.return_value = {"authorized_action": None}

    with mock.patch("research_os.cli.ResearchService", return_value=service):
        with redirect_stdout(io.StringIO()):
            legacy_code = main(["--project", "/tmp/project", "baseline"])
            scoped_code = main(
                [
                    "--project",
                    "/tmp/project",
                    "baseline",
                    "--evaluation-scope-id",
                    "development",
                ]
            )

    assert legacy_code == 0
    assert scoped_code == 0
    assert service.baseline.call_args_list == [
        mock.call(),
        mock.call(evaluation_scope_id="development"),
    ]


def test_proposal_option_is_forwarded_without_changing_legacy_call_shape() -> None:
    service = mock.Mock()
    service.run_once.return_value = {"authorized_action": None}

    with mock.patch("research_os.cli.ResearchService", return_value=service):
        with redirect_stdout(io.StringIO()):
            legacy_code = main(
                [
                    "--project",
                    "/tmp/project",
                    "run-once",
                    "candidate.json",
                    "--graph-action",
                    "explore",
                    "--scientific-change",
                    "class-a: change x",
                ]
            )
            typed_code = main(
                [
                    "--project",
                    "/tmp/project",
                    "run-once",
                    "candidate.json",
                    "--proposal",
                    "proposal.json",
                    "--context-token",
                    "token",
                ]
            )

    assert legacy_code == 0
    assert typed_code == 0
    assert service.run_once.call_args_list == [
        mock.call(
            Path("candidate.json"),
            parent_id=None,
            retry_of=None,
            context_token=None,
            graph_action="explore",
            scientific_change="class-a: change x",
        ),
        mock.call(
            Path("candidate.json"),
            parent_id=None,
            retry_of=None,
            context_token="token",
            graph_action=None,
            scientific_change=None,
            proposal=Path("proposal.json"),
        ),
    ]


@pytest.mark.parametrize(
    "legacy_arguments",
    [
        ["--parent", "exp_parent"],
        ["--graph-action", "explore"],
        ["--scientific-change", "class-a: change x"],
    ],
)
def test_proposal_rejects_legacy_graph_options_before_service_creation(
    legacy_arguments: list[str],
) -> None:
    stderr = io.StringIO()
    with (
        mock.patch("research_os.cli.ResearchService") as service_type,
        redirect_stderr(stderr),
    ):
        code = main(
            [
                "run-once",
                "candidate.json",
                "--proposal",
                "proposal.json",
                *legacy_arguments,
            ]
        )

    assert code == 2
    service_type.assert_not_called()
    error = json.loads(stderr.getvalue())["error"]
    assert error["code"] == "CLI_USAGE"
    assert "--proposal cannot be combined" in error["message"]


def test_proposal_retry_reaches_service_for_stable_science_error() -> None:
    service = mock.Mock()
    service.run_once.return_value = {"authorized_action": None}
    with (
        mock.patch("research_os.cli.ResearchService", return_value=service),
        redirect_stdout(io.StringIO()),
    ):
        code = main(
            [
                "--project",
                "/tmp/project",
                "run-once",
                "candidate.json",
                "--proposal",
                "proposal.json",
                "--retry-of",
                "exp_prior",
            ]
        )

    assert code == 0
    service.run_once.assert_called_once_with(
        Path("candidate.json"),
        parent_id=None,
        retry_of="exp_prior",
        context_token=None,
        graph_action=None,
        scientific_change=None,
        proposal=Path("proposal.json"),
    )


@pytest.mark.parametrize(
    "arguments, option",
    [
        (
            [
                "run-once",
                "candidate.json",
                "--proposal",
                "one.json",
                "--proposal",
                "two.json",
            ],
            "--proposal",
        ),
        (
            [
                "baseline",
                "--evaluation-scope-id",
                "development",
                "--evaluation-scope-id",
                "diagnostic-1",
            ],
            "--evaluation-scope-id",
        ),
    ],
)
def test_new_science_options_reject_duplicate_values(
    arguments: list[str],
    option: str,
) -> None:
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        code = main(arguments)

    assert code == 2
    error = json.loads(stderr.getvalue())["error"]
    assert error["code"] == "CLI_USAGE"
    assert option in error["message"]
    assert "may be supplied once" in error["message"]


def test_typed_service_binds_scope_to_baseline_registration_and_four_stages(
    tmp_path: Path,
) -> None:
    project, service, proposal = _scoped_project(tmp_path)
    candidate = project / "candidate-m1c.json"
    candidate.write_text('{"x":2.0,"y":1.0}\n', encoding="utf-8")
    expected_scope = {
        "id": "development",
        "role": "development",
        "manifest_digest": "b" * 64,
    }
    observed: list[tuple[Operation, dict[str, object]]] = []
    original_call = service._call_sealed

    def capture_call(report, operation, **kwargs):
        payload = kwargs.get("payload")
        if isinstance(payload, dict):
            observed.append((operation, dict(payload)))
        return original_call(report, operation, **kwargs)

    with mock.patch.object(service, "_call_sealed", side_effect=capture_call):
        baseline = service.baseline(evaluation_scope_id="development")
        result = service.run_once(candidate, proposal=proposal)

    assert baseline["evaluation_scope"] == expected_scope
    assert result["authorized_action"] is None
    scope_calls = [
        (operation, payload)
        for operation, payload in observed
        if "evaluation_scope" in payload
    ]
    candidate_scope_calls = scope_calls[-4:]
    assert [operation for operation, _ in candidate_scope_calls] == [
        Operation.MATERIALIZE,
        Operation.RUN,
        Operation.EVALUATE,
        Operation.VERIFY,
    ]
    assert [operation for operation, _ in scope_calls[:-4]] == [
        operation
        for _ in range(int(baseline["repetitions"]))
        for operation in (Operation.BASELINE, Operation.VERIFY)
    ]
    assert all(
        payload["evaluation_scope"] == expected_scope
        for _, payload in scope_calls
    )

    registrations = [
        event.payload
        for event in service.event_log.read()
        if event.event_type == "EXPERIMENT_REGISTERED"
    ]
    assert len(registrations) == 1
    registration = registrations[0]
    assert registration["candidate"] == {"x": 2.0, "y": 1.0}
    assert not {
        "proposal",
        "proposal_digest",
        "proposal_id",
        "evaluation_scope_id",
        "graph_action",
        "scientific_change",
    }.intersection(registration["candidate"])
    assert registration["proposal"] == proposal
    assert registration["evaluation_scope_id"] == "development"
    assert registration["parent_id"] is None
    assert "graph_metadata_version" not in registration
    assert "graph_action" not in registration
    assert "scientific_change" not in registration


def test_identical_scoped_run_loser_never_terminalizes_the_winner(
    tmp_path: Path,
) -> None:
    project, first_service, proposal = _scoped_project(tmp_path)
    first_service.baseline(evaluation_scope_id="development")
    second_service = ResearchService(project)
    candidate = project / "candidate-m1c-race.json"
    candidate.write_text('{"x":2.0,"y":1.0}\n', encoding="utf-8")
    barrier = Barrier(2)
    adapter_calls: dict[str, list[Operation]] = {"first": [], "second": []}

    def synchronized_append(service: ResearchService):
        original = service._append_registration_event

        def append(*args, **kwargs):
            barrier.wait(timeout=15)
            return original(*args, **kwargs)

        return append

    def observed_calls(label: str, service: ResearchService):
        original = service._call_sealed

        def call(report, operation, **kwargs):
            adapter_calls[label].append(operation)
            return original(report, operation, **kwargs)

        return call

    def run(label: str, service: ResearchService):
        try:
            result = service._run_once(candidate, proposal=proposal)
        except ScientificStateError as exc:
            return label, "rejected", exc.code
        return label, "committed", result["status"]

    with (
        mock.patch.object(
            first_service,
            "_append_registration_event",
            side_effect=synchronized_append(first_service),
        ),
        mock.patch.object(
            second_service,
            "_append_registration_event",
            side_effect=synchronized_append(second_service),
        ),
        mock.patch.object(
            first_service,
            "_call_sealed",
            side_effect=observed_calls("first", first_service),
        ),
        mock.patch.object(
            second_service,
            "_call_sealed",
            side_effect=observed_calls("second", second_service),
        ),
        ThreadPoolExecutor(max_workers=2) as executor,
    ):
        outcomes = [
            future.result(timeout=30)
            for future in (
                executor.submit(run, "first", first_service),
                executor.submit(run, "second", second_service),
            )
        ]

    committed = [outcome for outcome in outcomes if outcome[1] == "committed"]
    rejected = [outcome for outcome in outcomes if outcome[1] == "rejected"]
    assert len(committed) == 1
    assert committed[0][2] == TerminalStatus.VALIDATED.value
    assert len(rejected) == 1
    assert rejected[0][2] == "PROPOSAL_EVALUATION_SCOPE_REUSED"
    assert adapter_calls[rejected[0][0]] == []
    assert adapter_calls[committed[0][0]]

    events = first_service.event_log.read()
    registrations = [
        event
        for event in events
        if event.event_type == "EXPERIMENT_REGISTERED"
    ]
    terminals = [
        event
        for event in events
        if event.event_type == "EXPERIMENT_TERMINATED"
    ]
    assert len(registrations) == 1
    assert len(terminals) == 1
    assert terminals[0].payload["experiment_id"] == registrations[0].payload[
        "experiment_id"
    ]
    assert terminals[0].payload["status"] == TerminalStatus.VALIDATED.value
    status = first_service.study_status()
    assert status["budget"]["attempts"]["used"] == 1
    assert status["budget"]["retries"]["used"] == 0


def test_typed_service_never_auto_creates_a_missing_scope_baseline(
    tmp_path: Path,
) -> None:
    project, service, proposal = _scoped_project(tmp_path)
    candidate = project / "candidate-m1c.json"
    candidate.write_text('{"x":2.0,"y":1.0}\n', encoding="utf-8")
    before = service.event_log.path.read_bytes()

    with pytest.raises(ScientificStateError) as caught:
        service.run_once(candidate, proposal=proposal)

    assert caught.value.code == "STUDY_SCOPE_BASELINE_REQUIRED"
    assert service.event_log.path.read_bytes() == before
    assert not any(
        event.event_type in {"BASELINE_RECORDED", "EXPERIMENT_REGISTERED"}
        for event in service.event_log.read()
    )


def test_typed_retry_inherits_exact_proposal_scope_and_candidate(
    tmp_path: Path,
) -> None:
    project, service, proposal = _scoped_project(tmp_path)
    candidate = project / "candidate-m1c.json"
    candidate.write_text('{"x":2.0,"y":1.0}\n', encoding="utf-8")
    service.baseline(evaluation_scope_id="development")
    original_call = service._call_sealed
    failed = False

    def fail_first_run(report, operation, **kwargs):
        nonlocal failed
        if operation is Operation.RUN and not failed:
            failed = True
            return ProtocolResponse.failure(
                request_id="req_m1c_retry",
                error={
                    "category": "INFRASTRUCTURE",
                    "code": "TRANSIENT_M1C_TEST_FAILURE",
                    "message": "injected retryable scoped failure",
                },
                retryable=True,
            )
        return original_call(report, operation, **kwargs)

    with mock.patch.object(service, "_call_sealed", side_effect=fail_first_run):
        first = service.run_once(candidate, proposal=proposal)
    assert first["status"] == TerminalStatus.INFRA_FAILED.value

    second = service.run_once(
        candidate,
        retry_of=str(first["experiment_id"]),
    )
    assert second["status"] == TerminalStatus.VALIDATED.value
    registrations = [
        event.payload
        for event in service.event_log.read()
        if event.event_type == "EXPERIMENT_REGISTERED"
    ]
    assert len(registrations) == 2
    original, retry = registrations
    for key in (
        "candidate",
        "candidate_digest",
        "parent_id",
        "proposal",
        "proposal_digest",
        "proposal_id",
        "evaluation_scope_id",
        "baseline_id",
    ):
        assert retry[key] == original[key]
    assert original["attempt"] == 1
    assert original["retry_of"] is None
    assert retry["attempt"] == 2
    assert retry["retry_of"] == original["experiment_id"]
    status = service.study_status()
    assert status["budget"]["attempts"]["used"] == 2
    assert status["budget"]["retries"]["used"] == 1
    assert status["replication_count"] == 0
