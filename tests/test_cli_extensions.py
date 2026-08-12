from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from research_os.cli import main


class CLIExtensionTests(unittest.TestCase):
    def test_install_upgrade_flag_is_forwarded_and_rendered(self):
        installation = {
            "target": "codex",
            "destination": "/tmp/.agents/skills/research-os",
            "status": "upgraded",
            "from_release": "0.1.0",
            "to_release": "0.3.0",
        }
        stdout = io.StringIO()
        with (
            mock.patch(
                "research_os.cli.install_agent_skill",
                return_value=[installation],
            ) as installer,
            redirect_stdout(stdout),
        ):
            code = main(["install-agent-skill", "--target", "codex", "--upgrade"])
        self.assertEqual(code, 0)
        installer.assert_called_once_with("codex", upgrade=True)
        self.assertEqual(
            json.loads(stdout.getvalue())["installations"],
            [installation],
        )

    def test_duplicate_graph_options_are_structured_usage_errors(self):
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            code = main(
                [
                    "run-once",
                    "candidate.json",
                    "--graph-action",
                    "explore",
                    "--graph-action",
                    "ablate",
                    "--scientific-change",
                    "one change",
                ]
            )
        self.assertEqual(code, 2)
        error = json.loads(stderr.getvalue())["error"]
        self.assertEqual(error["code"], "CLI_USAGE")
        self.assertIn("may be supplied once", error["message"])

    def test_run_once_forwards_scientific_graph_contract(self):
        service = mock.Mock()
        service.run_once.return_value = {"status": "REJECTED"}
        stdout = io.StringIO()
        with (
            mock.patch("research_os.cli.ResearchService", return_value=service),
            redirect_stdout(stdout),
        ):
            code = main(
                [
                    "--project",
                    "/tmp/project",
                    "run-once",
                    "candidate.json",
                    "--parent",
                    "exp_parent",
                    "--context-token",
                    "token",
                    "--graph-action",
                    "ablate",
                    "--scientific-change",
                    "remove only the volume term",
                ]
            )
        self.assertEqual(code, 0)
        service.run_once.assert_called_once_with(
            Path("candidate.json"),
            parent_id="exp_parent",
            retry_of=None,
            context_token="token",
            graph_action="ablate",
            scientific_change="remove only the volume term",
        )

    def test_certify_and_conclude_commands_dispatch_to_service(self):
        service = mock.Mock()
        service.certify_evaluator.return_value = {"certified": True}
        service.evaluator_review_subject.return_value = {"digest": "a" * 64}
        service.conclude_branch.return_value = {"key": "branch_conclusion"}
        with mock.patch("research_os.cli.ResearchService", return_value=service):
            with redirect_stdout(io.StringIO()):
                certify_code = main(
                    [
                        "--project",
                        "/tmp/project",
                        "certify-evaluator",
                        "review.json",
                        "--replace",
                    ]
                )
                subject_code = main(
                    [
                        "--project",
                        "/tmp/project",
                        "evaluator-review-subject",
                    ]
                )
                conclude_code = main(
                    [
                        "--project",
                        "/tmp/project",
                        "conclude-branch",
                        "conclusion.json",
                        "--context-token",
                        "token",
                    ]
                )
        self.assertEqual(certify_code, 0)
        self.assertEqual(subject_code, 0)
        self.assertEqual(conclude_code, 0)
        service.certify_evaluator.assert_called_once_with(
            Path("review.json"),
            replace=True,
        )
        service.evaluator_review_subject.assert_called_once_with()
        service.conclude_branch.assert_called_once_with(
            Path("conclusion.json"),
            context_token="token",
        )

    def test_errors_emit_only_valid_absolute_recovery_paths(self):
        failure = OSError("retained recovery")
        failure.recovery_paths = ("/tmp/research-os-recovery",)
        failure.rollback_errors = ("restore failed",)
        stderr = io.StringIO()
        with (
            mock.patch("research_os.cli.install_agent_skill", side_effect=failure),
            redirect_stderr(stderr),
        ):
            code = main(["install-agent-skill", "--target", "codex"])
        self.assertEqual(code, 2)
        error = json.loads(stderr.getvalue())["error"]
        self.assertEqual(error["type"], "OSError")
        self.assertEqual(error["recovery_paths"], ["/tmp/research-os-recovery"])
        self.assertEqual(error["rollback_errors"], ["restore failed"])

        cancelled = KeyboardInterrupt()
        cancelled.recovery_paths = ("/tmp/research-os-cancelled",)
        cancelled.rollback_errors = ("cancel rollback failed",)
        stderr = io.StringIO()
        with (
            mock.patch("research_os.cli.install_agent_skill", side_effect=cancelled),
            redirect_stderr(stderr),
        ):
            code = main(["install-agent-skill", "--target", "codex"])
        self.assertEqual(code, 130)
        error = json.loads(stderr.getvalue())["error"]
        self.assertEqual(error["type"], "KeyboardInterrupt")
        self.assertEqual(error["recovery_paths"], ["/tmp/research-os-cancelled"])
        self.assertEqual(error["rollback_errors"], ["cancel rollback failed"])


if __name__ == "__main__":
    unittest.main()
