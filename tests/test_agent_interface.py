from __future__ import annotations

import io
import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from research_os.agent import (
    MAX_AGENT_CONTEXT_BYTES,
    build_agent_context,
    load_agent_spec,
)
from research_os.agent_install import install_agent_skill
from research_os.certification import REQUIRED_EVALUATOR_CHECK_IDS
from research_os.cli import main
from research_os.contracts import canonical_json_bytes
from research_os.errors import (
    ConfigurationError,
    IntegrityError,
    StaleAgentContextError,
)
from research_os.execution.workspace import hash_tree
from research_os.scaffold import RESEARCH_BRIEF_TEMPLATE, initialize_project
from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]


def _configured_agent_files(project: Path) -> None:
    control = project / ".research-os"
    (control / "research-brief.md").write_text(
        RESEARCH_BRIEF_TEMPLATE.replace(
            "REPLACE_ME",
            "Configured bounded optimization research",
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


def _certify_evaluator(project: Path) -> None:
    service = ResearchService(project)
    subject = service.evaluator_review_subject()
    review = project.parent / "evaluator-review.json"
    review.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "research-os-evaluator-review",
                "subject_digest": subject["digest"],
                "reviewer": "independent-test-reviewer",
                "independent_reviewer": True,
                "verdict": "PASS",
                "summary": "Independent fixture review passed.",
                "checks": [
                    {
                        "id": check_id,
                        "status": "PASS",
                        "evidence": f"golden fixture evidence for {check_id}",
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


class AgentSpecTests(unittest.TestCase):
    def test_scaffold_agent_spec_is_fail_closed_and_transient_files_are_excluded(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            initialize_project(project, "agent-project", "Agent project")

            spec = load_agent_spec(project)
            self.assertFalse(spec["configured"])
            self.assertIn("REPLACE_ME", spec["brief"])
            self.assertIs(
                spec["candidate_schema"]["x-research-os-configured"], False
            )

            before = hash_tree(project)
            (project / ".research-os" / "candidate.inbox.json").write_text(
                '{"candidate": 1}\n', encoding="utf-8"
            )
            (project / ".research-os" / "agent-journal.jsonl").write_text(
                '{"note":"non-authoritative"}\n', encoding="utf-8"
            )
            self.assertEqual(hash_tree(project), before)

    def test_agent_spec_rejects_a_symlinked_control_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            initialize_project(project, "agent-project", "Agent project")
            brief = project / ".research-os" / "research-brief.md"
            outside = Path(temporary) / "outside.md"
            outside.write_text("configured\n", encoding="utf-8")
            brief.unlink()
            brief.symlink_to(outside)

            with self.assertRaises(IntegrityError):
                load_agent_spec(project)

    def test_agent_setup_requires_complete_brief_schema_and_current_certification(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            initialize_project(project, "agent-project", "Agent project")
            control = project / ".research-os"
            (control / "research-brief.md").write_text("   \n", encoding="utf-8")
            (control / "candidate.schema.json").write_text(
                '{"x-research-os-configured":true}\n',
                encoding="utf-8",
            )
            minimal = load_agent_spec(
                project,
                evaluator_certification={"certified": True, "current": True},
            )
            self.assertFalse(minimal["setup_configured"])
            self.assertFalse(minimal["brief_configured"])
            self.assertFalse(minimal["candidate_schema_configured"])

            _configured_agent_files(project)
            missing_current = load_agent_spec(
                project,
                evaluator_certification={"certified": True},
            )
            self.assertTrue(missing_current["setup_configured"])
            self.assertFalse(missing_current["research_ready"])
            ready = load_agent_spec(
                project,
                evaluator_certification={"certified": True, "current": True},
            )
            self.assertTrue(ready["research_ready"])


class AgentInstallerTests(unittest.TestCase):
    def test_installs_both_hosts_idempotently(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            installed = install_agent_skill("all", home=home)
            self.assertEqual(
                {record["target"] for record in installed}, {"codex", "claude"}
            )
            for relative in (
                Path(".agents/skills/research-os"),
                Path(".claude/skills/research-os"),
            ):
                destination = home / relative
                self.assertTrue((destination / "SKILL.md").is_file())
                self.assertTrue(
                    (destination / "references" / "status-actions.md").is_file()
                )

            repeated = install_agent_skill("all", home=home)
            self.assertEqual(
                {record["status"] for record in repeated}, {"already_current"}
            )

    def test_refuses_to_overwrite_a_drifted_or_symlinked_skill(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            install_agent_skill("codex", home=home)
            skill = home / ".agents" / "skills" / "research-os" / "SKILL.md"
            skill.write_text("different\n", encoding="utf-8")
            with self.assertRaises(ConfigurationError):
                install_agent_skill("codex", home=home)
            self.assertEqual(skill.read_text(encoding="utf-8"), "different\n")

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            destination = home / ".claude" / "skills"
            destination.mkdir(parents=True)
            outside = home / "outside"
            outside.mkdir()
            (destination / "research-os").symlink_to(
                outside, target_is_directory=True
            )
            with self.assertRaises(ConfigurationError):
                install_agent_skill("claude", home=home)
            self.assertEqual(list(outside.iterdir()), [])

    def test_all_targets_preflight_before_installing_either(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            claude = home / ".claude" / "skills" / "research-os"
            claude.mkdir(parents=True)
            (claude / "SKILL.md").write_text("local skill\n", encoding="utf-8")

            with self.assertRaises(ConfigurationError):
                install_agent_skill("all", home=home)
            self.assertFalse((home / ".agents" / "skills" / "research-os").exists())
            self.assertEqual(
                (claude / "SKILL.md").read_text(encoding="utf-8"), "local skill\n"
            )


class AgentContextTests(unittest.TestCase):
    def copy_project(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        project = Path(temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        _configured_agent_files(project)
        _certify_evaluator(project)
        ResearchService(project).baseline()
        return temporary, project

    def test_context_token_binds_graph_and_allows_transient_candidate_write(self):
        temporary, project = self.copy_project()
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)

        context = service.agent_context(limit=5)
        self.assertEqual(context["kind"], "research-os-agent-context")
        self.assertTrue(context["agent"]["configured"])
        self.assertEqual(context["graph"]["total_experiments"], 0)
        token = context["snapshot"]["context_token"]
        self.assertEqual(len(token), 64)
        self.assertLessEqual(context["packet_size_bytes"], MAX_AGENT_CONTEXT_BYTES)
        self.assertEqual(
            context["packet_size_bytes"], len(canonical_json_bytes(context))
        )
        self.assertIn("project_compatibility_digest", context["snapshot"])
        self.assertNotIn("compatibility_digest", context["snapshot"])
        self.assertIn("RUN_ONE_CANDIDATE", context["allowed_agent_actions"])
        self.assertNotIn("SEAL_BASELINE", context["allowed_agent_actions"])

        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text('{"x":2.0}\n', encoding="utf-8")
        outcome = service.run_once(
            inbox,
            context_token=token,
            graph_action="explore",
            scientific_change="toy-objective: set x to the known optimum",
        )
        self.assertEqual(outcome["status"], "VALIDATED")
        registration = next(
            event
            for event in service.event_log.read()
            if event.event_type == "EXPERIMENT_REGISTERED"
        )
        self.assertEqual(registration.payload["agent_context_token"], token)
        self.assertEqual(
            registration.payload["agent_context_snapshot"]["context_token"], token
        )
        self.assertEqual(registration.payload["graph_action"], "explore")
        self.assertEqual(
            registration.payload["scientific_change"],
            "toy-objective: set x to the known optimum",
        )

        refreshed = service.agent_context(limit=5)
        self.assertEqual(refreshed["graph"]["total_experiments"], 1)
        self.assertEqual(refreshed["graph"]["recent_returned"], 1)
        self.assertEqual(
            refreshed["graph"]["frontier"][0]["experiment_id"],
            outcome["experiment_id"],
        )

    def test_stale_context_is_rejected_before_registration(self):
        temporary, project = self.copy_project()
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        stale = service.agent_context()["snapshot"]["context_token"]
        service.baseline()
        inbox = project / ".research-os" / "candidate.inbox.json"
        inbox.write_text('{"x":2.0}\n', encoding="utf-8")

        with self.assertRaisesRegex(
            StaleAgentContextError, "agent context is stale"
        ) as caught:
            service.run_once(
                inbox,
                context_token=stale,
                graph_action="explore",
                scientific_change="toy-objective: set x to the known optimum",
            )
        self.assertEqual(caught.exception.code, "STALE_AGENT_CONTEXT")
        self.assertEqual(service.status()["experiments"], 0)

    def test_context_limit_is_validated(self):
        temporary, project = self.copy_project()
        self.addCleanup(temporary.cleanup)
        service = ResearchService(project)
        for invalid in (True, 0, 101):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    service.agent_context(limit=invalid)

    def test_cli_emits_the_agent_context_json_contract(self):
        temporary, project = self.copy_project()
        self.addCleanup(temporary.cleanup)
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            return_code = main(
                [
                    "--project",
                    str(project),
                    "agent-context",
                    "--limit",
                    "3",
                ]
            )
        self.assertEqual(return_code, 0)
        value = json.loads(stdout.getvalue())
        self.assertEqual(value["kind"], "research-os-agent-context")
        self.assertEqual(value["graph"]["recent_returned"], 0)

    def test_builder_hides_superseded_retry_from_frontier_and_retryable(self):
        first = {
            "experiment_id": "exp_1",
            "parent_id": None,
            "retry_of": None,
            "retryable": True,
            "status": "TIMED_OUT",
            "attempt": 1,
            "payload": {"candidate": {"x": 1}},
        }
        second = {
            "experiment_id": "exp_2",
            "parent_id": None,
            "retry_of": "exp_1",
            "retryable": False,
            "status": "REJECTED",
            "attempt": 2,
            "payload": {"candidate": {"x": 1}},
        }
        context = build_agent_context(
            project={},
            status={},
            lineage=[first, second],
            findings=[],
            artifacts=[],
            agent_spec={},
            snapshot={},
            limit=10,
        )
        self.assertEqual(
            [row["experiment_id"] for row in context["graph"]["frontier"]],
            ["exp_2"],
        )
        self.assertEqual(context["graph"]["retryable"], [])

    def test_builder_enforces_a_global_packet_cap(self):
        large_candidate = {"text": "x" * 30_000}
        lineage = [
            {
                "experiment_id": f"exp_{index}",
                "parent_id": None,
                "retry_of": None,
                "retryable": False,
                "status": "REJECTED",
                "attempt": 1,
                "payload": {"candidate": large_candidate},
            }
            for index in range(100)
        ]
        with self.assertRaisesRegex(ConfigurationError, "2 MiB packet limit"):
            build_agent_context(
                project={},
                status={},
                lineage=lineage,
                findings=[],
                artifacts=[],
                agent_spec={},
                snapshot={},
                limit=100,
            )


if __name__ == "__main__":
    unittest.main()
