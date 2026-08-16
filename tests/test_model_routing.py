from __future__ import annotations

import json
import runpy
import subprocess
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "research-agent"


class ModelRoutingTests(unittest.TestCase):
    def test_checked_in_defaults_preserve_research_quality(self):
        codex = tomllib.loads((ROOT / ".codex/config.toml").read_text(encoding="utf-8"))
        claude = json.loads((ROOT / ".claude/settings.json").read_text(encoding="utf-8"))

        self.assertEqual(codex["model"], "gpt-5.6-sol")
        self.assertEqual(codex["model_reasoning_effort"], "high")
        self.assertEqual(claude, {"model": "opus", "effortLevel": "high"})

    def test_every_provider_exposes_control_research_and_audit_routes(self):
        namespace = runpy.run_path(str(LAUNCHER))
        routes = namespace["ROUTES"]

        self.assertEqual(
            set(routes),
            {
                ("codex", "control"),
                ("codex", "research"),
                ("codex", "audit"),
                ("claude", "control"),
                ("claude", "research"),
                ("claude", "audit"),
            },
        )
        self.assertIn("gpt-5.6-terra", routes[("codex", "control")])
        self.assertIn("gpt-5.6-sol", routes[("codex", "research")])
        self.assertIn("sonnet", routes[("claude", "control")])
        self.assertIn("opus", routes[("claude", "research")])

    def test_dry_run_forwards_prompt_without_starting_provider(self):
        result = subprocess.run(
            [str(LAUNCHER), "codex", "research", "--dry-run", "--", "bounded research"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        command = json.loads(result.stdout)
        self.assertEqual(command[0], "codex")
        self.assertEqual(command[-1], "bounded research")
        self.assertIn('model_reasoning_effort="high"', command)

    def test_skill_keeps_model_routing_outside_scientific_evidence(self):
        skill = (
            ROOT / "src/research_os/resources/research-os/SKILL.md"
        ).read_text(encoding="utf-8")
        self.assertIn("Research OS is provider-neutral", skill)
        self.assertIn("cannot change the active root model", skill)
        self.assertIn("Control route", skill)
        self.assertIn("Research route", skill)
        self.assertIn("Audit route", skill)


if __name__ == "__main__":
    unittest.main()
