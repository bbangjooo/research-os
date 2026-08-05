from __future__ import annotations

import io
import json
import shutil
import stat
import subprocess
import tempfile
import tomllib
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

import research_os.scaffold as scaffold_module
from research_os.cli import main
from research_os.errors import ConfigurationError
from research_os.scaffold import initialize_project

ROOT = Path(__file__).resolve().parents[1]


class ScaffoldSafetyTests(unittest.TestCase):
    def test_scaffold_is_exclusive_and_non_overwriting(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            created = initialize_project(project, "safe-project", "Safe project")
            self.assertEqual(len(created), 9)
            self.assertEqual(
                json.loads((project / "experiment.json").read_text(encoding="utf-8")),
                {},
            )
            self.assertEqual(
                stat.S_IMODE(
                    (project / ".research-os" / "project.toml").stat().st_mode
                ),
                0o600,
            )
            self.assertEqual(
                stat.S_IMODE((project / ".research-os" / "adapter.py").stat().st_mode),
                0o700,
            )
            self.assertTrue(
                (project / ".research-os" / "research-brief.md").is_file()
            )
            schema = json.loads(
                (project / ".research-os" / "candidate.schema.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertIs(schema["x-research-os-configured"], False)
            self.assertEqual(
                json.loads(
                    (project / ".research-os" / "candidate.inbox.json").read_text(
                        encoding="utf-8"
                    )
                ),
                {},
            )
            before = {path: path.read_bytes() for path in created}
            with self.assertRaises(ConfigurationError):
                initialize_project(project, "safe-project", "Replacement")
            self.assertEqual(before, {path: path.read_bytes() for path in created})
            self.assertFalse((project / ".research-os.init.lock").exists())

    def test_control_directory_symlink_cannot_escape_project(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            outside = base / "outside"
            project.mkdir()
            outside.mkdir()
            (project / ".research-os").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ConfigurationError):
                initialize_project(project, "safe-project", "Safe project")
            self.assertEqual(list(outside.iterdir()), [])
            self.assertFalse((project / "experiment.json").exists())
            self.assertFalse((project / "evaluator.py").exists())
            self.assertFalse((project / ".research-os.init.lock").exists())

    def test_root_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            project.mkdir()
            alias = base / "project-alias"
            alias.symlink_to(project, target_is_directory=True)
            with self.assertRaises(ConfigurationError):
                initialize_project(alias, "safe-project", "Safe project")
            self.assertEqual(list(project.iterdir()), [])

    def test_broken_leaf_symlink_is_a_collision_not_an_escape(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            project = base / "project"
            outside = base / "outside"
            project.mkdir()
            outside.mkdir()
            escaped_target = outside / "experiment.json"
            (project / "experiment.json").symlink_to(escaped_target)
            with self.assertRaises(ConfigurationError):
                initialize_project(project, "safe-project", "Safe project")
            self.assertFalse(escaped_target.exists())
            self.assertTrue((project / "experiment.json").is_symlink())
            self.assertFalse((project / ".research-os").exists())

    def test_write_failure_rolls_back_only_transaction_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()
            original_write = scaffold_module._write_all
            calls = 0

            def fail_second_write(descriptor: int, data: bytes) -> None:
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("injected scaffold write failure")
                original_write(descriptor, data)

            with mock.patch.object(scaffold_module, "_write_all", fail_second_write):
                with self.assertRaises(ConfigurationError):
                    initialize_project(project, "safe-project", "Safe project")

            self.assertEqual(list(project.iterdir()), [])

    def test_concurrent_initializers_have_one_winner(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "project"
            project.mkdir()

            def attempt(index: int) -> str:
                try:
                    initialize_project(project, "safe-project", f"Name {index}")
                except ConfigurationError:
                    return "rejected"
                return "created"

            with ThreadPoolExecutor(max_workers=2) as executor:
                outcomes = list(executor.map(attempt, (1, 2)))
            self.assertEqual(outcomes.count("created"), 1)
            self.assertEqual(outcomes.count("rejected"), 1)
            self.assertTrue((project / ".research-os" / "project.toml").is_file())
            self.assertFalse((project / ".research-os.init.lock").exists())


class CLISyntaxContractTests(unittest.TestCase):
    def assert_usage_error(self, arguments: list[str]) -> dict[str, object]:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            return_code = main(arguments)
        self.assertEqual(return_code, 2)
        value = json.loads(stderr.getvalue())
        self.assertEqual(value["ok"], False)
        self.assertEqual(value["error"]["type"], "CLIUsageError")
        self.assertEqual(value["error"]["code"], "CLI_USAGE")
        return value

    def test_unknown_command_is_structured_json(self):
        value = self.assert_usage_error(["not-a-command"])
        self.assertIn("invalid choice", value["error"]["message"])

    def test_missing_required_option_is_structured_json(self):
        value = self.assert_usage_error(["init", "/tmp/example", "--name", "Example"])
        self.assertIn("--id", value["error"]["message"])

    def test_invalid_option_value_is_structured_json(self):
        value = self.assert_usage_error(["baseline", "--repeats", "not-an-integer"])
        self.assertIn("invalid int value", value["error"]["message"])


class PortabilityTests(unittest.TestCase):
    @unittest.skipUnless(
        shutil.which("node"), "Node is required for the JavaScript fixture"
    )
    def test_javascript_evaluator_resolves_percent_encoded_module_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / "retrieval project %25"
            shutil.copytree(ROOT / "examples" / "toy_retrieval", project)
            completed = subprocess.run(
                ["node", str(project / "evaluator.mjs"), str(project)],
                cwd=project,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(
                (project / "outputs" / "result.json").read_text(encoding="utf-8")
            )
            self.assertIn("recall_at_1", result["metrics"])

    def test_package_declares_posix_only_support(self):
        metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        self.assertIn("Operating System :: POSIX", metadata["project"]["classifiers"])
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("supports POSIX operating systems only", readme)


if __name__ == "__main__":
    unittest.main()
