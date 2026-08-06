from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "src" / "research_os" / "resources" / "research-os"
SKILL = SKILL_ROOT / "SKILL.md"
SCIENTIFIC_PROTOCOL = SKILL_ROOT / "references" / "scientific-protocol.md"
STATUS_ACTIONS = SKILL_ROOT / "references" / "status-actions.md"


class SkillPolicyResourceTests(unittest.TestCase):
    def test_stable_scientific_policy_markers_are_present_once(self):
        text = SKILL.read_text(encoding="utf-8")
        markers = (
            "EVALUATOR_CERTIFICATION_GATE",
            "GOLDEN_SETUP_GATE",
            "UNIVERSE_PREREGISTRATION_GATE",
            "LOCKED_HOLDOUT_GATE",
            "GRAPH_PHASE_GATE",
            "SINGLE_INTERVENTION_GATE",
            "CLASS_FAILURE_GATE",
            "CHANGE_CONTROL_GATE",
        )
        for marker in markers:
            with self.subTest(marker=marker):
                self.assertEqual(text.count(marker), 1)

    def test_skill_uses_top_level_graph_metadata_not_candidate_duplication(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("--graph-action explore", text)
        self.assertIn("--scientific-change", text)
        self.assertIn("top-level experiment metadata", text)
        self.assertIn("Do not require `graph_action`", text)
        self.assertIn("inside candidate JSON", text)

    def test_phase_machine_and_failure_closure_are_normative(self):
        text = SKILL.read_text(encoding="utf-8")
        positions = [
            text.index("**Explore:**"),
            text.index("**Diagnose:**"),
            text.index("**Ablate or exploit:**"),
            text.index("**Replicate:**"),
        ]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("after every terminal result, run no experiment", text)
        self.assertIn("default three", text)
        self.assertIn("close that class", text)
        self.assertIn("independent certification", text)
        self.assertIn("new compatible baseline", text)

    def test_packaged_markdown_reference_links_resolve(self):
        markdown_files = (SKILL, SCIENTIFIC_PROTOCOL, STATUS_ACTIONS)
        link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+\.md)(?:#[^)]+)?\)")
        for markdown in markdown_files:
            text = markdown.read_text(encoding="utf-8")
            for target in link_pattern.findall(text):
                with self.subTest(source=markdown.name, target=target):
                    self.assertTrue((markdown.parent / target).resolve().is_file())

    def test_scientific_protocol_preserves_terminal_status_guidance(self):
        protocol = SCIENTIFIC_PROTOCOL.read_text(encoding="utf-8")
        statuses = STATUS_ACTIONS.read_text(encoding="utf-8")
        self.assertIn("hand-derived", protocol)
        self.assertIn("separate read-only critic", protocol)
        self.assertIn("A locked holdout is not merely a date filter", protocol)
        self.assertIn("[status-actions.md](status-actions.md)", protocol)
        for status in (
            "VALIDATED",
            "REJECTED",
            "INVALID_EXPERIMENT",
            "INSUFFICIENT_EVIDENCE",
            "INFRA_FAILED",
            "TIMED_OUT",
            "CANCELLED",
            "UNTRUSTED",
        ):
            with self.subTest(status=status):
                self.assertIn(f"`{status}`", statuses)

    def test_certification_review_contract_matches_managed_gate(self):
        protocol = SCIENTIFIC_PROTOCOL.read_text(encoding="utf-8")
        self.assertLess(
            protocol.index("mark the fully implemented candidate contract configured"),
            protocol.index("emit `evaluator-review-subject`"),
        )
        self.assertLess(
            protocol.index("emit `evaluator-review-subject`"),
            protocol.index("digest-bound review with `certify-evaluator`"),
        )
        match = re.search(
            r"## Independent evaluator certification.*?```json\n(.*?)\n```",
            protocol,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        assert match is not None
        review = json.loads(match.group(1))
        self.assertEqual(
            set(review),
            {
                "schema_version",
                "kind",
                "subject_digest",
                "reviewer",
                "independent_reviewer",
                "verdict",
                "summary",
                "checks",
                "blocking_findings",
            },
        )
        expected_checks = {
            "evidence_isolation",
            "evaluation_timing_or_causality",
            "outcome_accounting",
            "cost_and_resource_model",
            "metric_semantics",
            "constraint_semantics",
            "candidate_contract",
            "deterministic_golden_cases",
            "external_state_isolation",
        }
        observed_checks = {check["id"] for check in review["checks"]}
        self.assertEqual(observed_checks, expected_checks)
        self.assertIn("research-os-evaluator-review", protocol)
        self.assertIn("evaluator-review-subject", protocol)
        self.assertIn("certify-evaluator /ABS/OUTSIDE/REVIEW.json", protocol)
        self.assertIn(".research-os/evaluator-certification.json", protocol)
        self.assertIn("never hand-edit it or declare", protocol)

    def test_branch_conclusion_contract_and_command_are_documented(self):
        protocol = SCIENTIFIC_PROTOCOL.read_text(encoding="utf-8")
        match = re.search(
            r"## Durable branch conclusions.*?```json\n(.*?)\n```",
            protocol,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        assert match is not None
        conclusion = json.loads(match.group(1))
        self.assertEqual(
            set(conclusion),
            {
                "branch_experiment_ids",
                "hypothesis_class",
                "failure_signature",
                "conclusion",
                "confidence",
                "next_step",
            },
        )
        self.assertIn("conclude-branch", protocol)
        self.assertIn("candidate.inbox.json --context-token TOKEN", protocol)

    def test_public_docs_explain_the_new_scientific_boundary(self):
        documents = (
            ROOT / "README.md",
            ROOT / "docs" / "agent-usage.md",
            ROOT / "docs" / "new-project.md",
            ROOT / "docs" / "architecture.md",
            ROOT / "docs" / "adapter-protocol.md",
        )
        combined = "\n".join(path.read_text(encoding="utf-8") for path in documents)
        self.assertIn("graph_action", combined)
        self.assertIn("scientific_change", combined)
        self.assertIn("independent evaluator certification", combined)
        self.assertIn("not an operating-system sandbox", combined)
        self.assertIn("default is three", combined)


if __name__ == "__main__":
    unittest.main()
