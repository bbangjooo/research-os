from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import pytest

from research_os.cli import main


@pytest.mark.parametrize(
    ("command", "argument", "method_name"),
    (
        ("frame-transition-gate-a", "gate-a.json", "gate_a"),
        ("frame-transition-open", "inquiry.json", "open_inquiry"),
        ("frame-transition-decide", "decision.json", "decide_inquiry"),
        (
            "frame-transition-authorize-pilot",
            "authorization.json",
            "authorize_pilot",
        ),
        (
            "frame-transition-record-pilot",
            "pilot-result.json",
            "record_pilot",
        ),
        ("frame-transition-review", "review.json", "review_adoption"),
        ("frame-transition-revoke", "revocation.json", "revoke_authority"),
    ),
)
def test_frame_transition_receipt_commands_dispatch_exact_paths(
    command: str,
    argument: str,
    method_name: str,
) -> None:
    service = mock.Mock()
    expected = {
        "command": command,
        "receipt": argument,
        "authorized_action": None,
    }
    getattr(service, method_name).return_value = expected
    stdout = io.StringIO()

    with (
        mock.patch(
            "research_os.cli.FrameTransitionService",
            return_value=service,
        ) as service_type,
        mock.patch("research_os.cli.ResearchService") as legacy_service_type,
        redirect_stdout(stdout),
    ):
        code = main(
            [
                "--project",
                "/tmp/frame-project",
                command,
                argument,
            ]
        )

    assert code == 0
    service_type.assert_called_once_with(Path("/tmp/frame-project"))
    getattr(service, method_name).assert_called_once_with(Path(argument))
    legacy_service_type.assert_not_called()
    assert json.loads(stdout.getvalue()) == expected


def test_frame_transition_adopt_policy_dispatches_inquiry_id() -> None:
    service = mock.Mock()
    expected = {
        "frame_transition_inquiry_id": "frame_inquiry_fixture",
        "authorized_action": None,
    }
    service.adopt_policy.return_value = expected
    stdout = io.StringIO()

    with (
        mock.patch(
            "research_os.cli.FrameTransitionService",
            return_value=service,
        ) as service_type,
        mock.patch("research_os.cli.ResearchService") as legacy_service_type,
        redirect_stdout(stdout),
    ):
        code = main(
            [
                "--project",
                "/tmp/frame-project",
                "frame-transition-adopt-policy",
                "frame_inquiry_fixture",
            ]
        )

    assert code == 0
    service_type.assert_called_once_with(Path("/tmp/frame-project"))
    service.adopt_policy.assert_called_once_with("frame_inquiry_fixture")
    legacy_service_type.assert_not_called()
    assert json.loads(stdout.getvalue()) == expected


def test_frame_transition_activate_dispatches_inquiry_and_contract() -> None:
    service = mock.Mock()
    expected = {
        "generation_id": "generation_successor",
        "frame_transition_inquiry_id": "frame_inquiry_fixture",
        "authorized_action": None,
    }
    service.activate.return_value = expected
    stdout = io.StringIO()

    with (
        mock.patch(
            "research_os.cli.FrameTransitionService",
            return_value=service,
        ) as service_type,
        mock.patch("research_os.cli.ResearchService") as legacy_service_type,
        redirect_stdout(stdout),
    ):
        code = main(
            [
                "--project",
                "/tmp/frame-project",
                "frame-transition-activate",
                "frame_inquiry_fixture",
                "successor-contract.json",
            ]
        )

    assert code == 0
    service_type.assert_called_once_with(Path("/tmp/frame-project"))
    service.activate.assert_called_once_with(
        "frame_inquiry_fixture",
        Path("successor-contract.json"),
    )
    legacy_service_type.assert_not_called()
    assert json.loads(stdout.getvalue()) == expected


@pytest.mark.parametrize(
    ("extra_arguments", "expected_inquiry"),
    (
        ((), None),
        (("--inquiry", "frame_inquiry_fixture"), "frame_inquiry_fixture"),
    ),
)
def test_frame_transition_status_supports_optional_inquiry_filter(
    extra_arguments: tuple[str, ...],
    expected_inquiry: str | None,
) -> None:
    service = mock.Mock()
    expected = {
        "project_id": "frame-project",
        "inquiries": [],
        "authorized_action": None,
    }
    service.status.return_value = expected
    stdout = io.StringIO()

    with (
        mock.patch(
            "research_os.cli.FrameTransitionService",
            return_value=service,
        ) as service_type,
        mock.patch("research_os.cli.ResearchService") as legacy_service_type,
        redirect_stdout(stdout),
    ):
        code = main(
            [
                "--project",
                "/tmp/frame-project",
                "frame-transition-status",
                *extra_arguments,
            ]
        )

    assert code == 0
    service_type.assert_called_once_with(Path("/tmp/frame-project"))
    service.status.assert_called_once_with(expected_inquiry)
    legacy_service_type.assert_not_called()
    assert json.loads(stdout.getvalue()) == expected


def test_frame_transition_required_file_is_a_structured_usage_error() -> None:
    stderr = io.StringIO()

    with (
        mock.patch("research_os.cli.FrameTransitionService") as service_type,
        redirect_stderr(stderr),
    ):
        code = main(["frame-transition-open"])

    assert code == 2
    service_type.assert_not_called()
    error = json.loads(stderr.getvalue())["error"]
    assert error["code"] == "CLI_USAGE"
    assert "required" in error["message"]


def test_frame_transition_ratify_is_no_longer_accepted() -> None:
    stderr = io.StringIO()

    with (
        mock.patch("research_os.cli.FrameTransitionService") as service_type,
        redirect_stderr(stderr),
    ):
        code = main(["frame-transition-ratify", "ratification.json"])

    assert code == 2
    service_type.assert_not_called()
    error = json.loads(stderr.getvalue())["error"]
    assert error["code"] == "CLI_USAGE"
    assert "invalid choice" in error["message"]
