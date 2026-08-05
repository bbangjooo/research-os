from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research_os.config import ensure_runtime_directory, load_project_config
from research_os.contracts import TerminalStatus
from research_os.errors import ConfigurationError, IntegrityError
from research_os.provenance import fingerprint_paths, project_fingerprints
from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]


class ProvenanceHardeningTests(unittest.TestCase):
    def copy_optimization(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        project = Path(temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        return temporary, project

    def test_adapter_argv_preserves_meaningful_whitespace(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        project_file = project / ".research-os" / "project.toml"
        project_file.write_text(
            project_file.read_text(encoding="utf-8").replace(
                '["python3", ".research-os/adapter.py"]',
                '["python3", "  literal argument  "]',
            ),
            encoding="utf-8",
        )

        config = load_project_config(project)

        self.assertEqual(config.adapter_command[1], "  literal argument  ")

    def test_dynamic_python_module_entry_point_fails_closed(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        project_file = project / ".research-os" / "project.toml"
        project_file.write_text(
            project_file.read_text(encoding="utf-8").replace(
                '["python3", ".research-os/adapter.py"]',
                '["python3", "-m", "research_os"]',
            ),
            encoding="utf-8",
        )

        with self.assertRaises(IntegrityError):
            project_fingerprints(load_project_config(project))

    def test_relative_adapter_file_cannot_escape_project_execution_semantics(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        outside = Path(temporary.name) / "outside-adapter.py"
        shutil.copy2(project / ".research-os" / "adapter.py", outside)
        project_file = project / ".research-os" / "project.toml"
        project_file.write_text(
            project_file.read_text(encoding="utf-8").replace(
                '["python3", ".research-os/adapter.py"]',
                '["python3", "../outside-adapter.py"]',
            ),
            encoding="utf-8",
        )

        with self.assertRaisesRegex(ConfigurationError, "parent traversal"):
            load_project_config(project)

    def test_external_adapter_file_change_rotates_compatibility(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        external = Path(temporary.name) / "external-adapter.py"
        shutil.copy2(project / ".research-os" / "adapter.py", external)
        project_file = project / ".research-os" / "project.toml"
        project_file.write_text(
            project_file.read_text(encoding="utf-8").replace(
                '["python3", ".research-os/adapter.py"]',
                f'["python3", {json.dumps(str(external))}]',
            ),
            encoding="utf-8",
        )
        config = load_project_config(project)

        before = project_fingerprints(config)
        adapter_files = before["environment"]["value"]["adapter_files"]
        external_record = next(item for item in adapter_files if item["index"] == 1)
        self.assertEqual(external_record["resolved"], str(external.resolve()))

        external.write_text(
            external.read_text(encoding="utf-8") + "\n# compatibility v2\n",
            encoding="utf-8",
        )
        after = project_fingerprints(config)

        self.assertNotEqual(
            before["environment"]["digest"], after["environment"]["digest"]
        )
        self.assertNotEqual(
            before["compatibility_digest"], after["compatibility_digest"]
        )

    def test_same_candidate_can_run_after_external_adapter_revision(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        external = Path(temporary.name) / "external-adapter.py"
        shutil.copy2(project / ".research-os" / "adapter.py", external)
        project_file = project / ".research-os" / "project.toml"
        project_file.write_text(
            project_file.read_text(encoding="utf-8").replace(
                '["python3", ".research-os/adapter.py"]',
                f'["python3", {json.dumps(str(external))}]',
            ),
            encoding="utf-8",
        )
        service = ResearchService(project)
        candidate = project / "candidates" / "improve.json"

        first = service.run_once(candidate)
        external.write_text(
            external.read_text(encoding="utf-8") + "\n# compatibility v2\n",
            encoding="utf-8",
        )
        second = service.run_once(candidate)

        self.assertEqual(first["status"], TerminalStatus.VALIDATED.value)
        self.assertEqual(second["status"], TerminalStatus.VALIDATED.value)
        self.assertNotEqual(first["experiment_id"], second["experiment_id"])
        self.assertEqual(
            service.status()["experiments_by_status"],
            {TerminalStatus.VALIDATED.value: 2},
        )

    def test_external_adapter_drift_during_execution_is_untrusted(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        external = Path(temporary.name) / "external-adapter.py"
        shutil.copy2(project / ".research-os" / "adapter.py", external)
        source = external.read_text(encoding="utf-8").replace(
            '            (workspace / "parameter.json").write_text(\n',
            "            adapter_file = Path(__file__)\n"
            "            adapter_file.write_text(\n"
            '                adapter_file.read_text() + "\\n# drift during run\\n"\n'
            "            )\n"
            '            (workspace / "parameter.json").write_text(\n',
        )
        external.write_text(source, encoding="utf-8")
        project_file = project / ".research-os" / "project.toml"
        project_file.write_text(
            project_file.read_text(encoding="utf-8").replace(
                '["python3", ".research-os/adapter.py"]',
                f'["python3", {json.dumps(str(external))}]',
            ),
            encoding="utf-8",
        )

        outcome = ResearchService(project).run_once(
            project / "candidates" / "improve.json"
        )

        self.assertEqual(outcome["status"], TerminalStatus.UNTRUSTED.value)
        self.assertEqual(outcome["reason_code"], "INTEGRITY_CHECK_FAILED")

    def test_toml_replacement_between_stat_and_open_is_rejected(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        project_file = project / ".research-os" / "project.toml"
        original = project_file.read_text(encoding="utf-8")
        real_open = os.open
        replaced = False

        def racing_open(path, flags, mode=0o777, *, dir_fd=None):
            nonlocal replaced
            if path == "project.toml" and dir_fd is not None and not replaced:
                replacement = project_file.with_name("project.next.toml")
                replacement.write_text(original, encoding="utf-8")
                os.replace(replacement, project_file)
                replaced = True
            if dir_fd is None:
                return real_open(path, flags, mode)
            return real_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch("research_os.config.os.open", side_effect=racing_open):
            with self.assertRaises(ConfigurationError):
                load_project_config(project)

    def test_toml_parent_replacement_during_read_is_rejected(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        control = project / ".research-os"
        detached = project / ".research-os.detached"
        replacement = Path(temporary.name) / "replacement-control"
        shutil.copytree(control, replacement)
        real_open = os.open
        replaced = False

        def racing_open(path, flags, mode=0o777, *, dir_fd=None):
            nonlocal replaced
            if path == "project.toml" and dir_fd is not None and not replaced:
                os.rename(control, detached)
                os.rename(replacement, control)
                replaced = True
            if dir_fd is None:
                return real_open(path, flags, mode)
            return real_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch("research_os.config.os.open", side_effect=racing_open):
            with self.assertRaises(ConfigurationError):
                load_project_config(project)

    def test_runtime_symlink_created_after_config_load_is_rejected(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        external = Path(temporary.name) / "external-runtime"
        external.mkdir()
        config.resolved_runtime_dir.symlink_to(external, target_is_directory=True)

        with self.assertRaises(ConfigurationError):
            ensure_runtime_directory(config)
        self.assertEqual(list(external.iterdir()), [])

    def test_runtime_creation_race_cannot_redirect_permissions(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        runtime = config.resolved_runtime_dir
        detached = runtime.with_name("runtime.detached")
        external = Path(temporary.name) / "external-runtime"
        external.mkdir(mode=0o755)
        original_mode = external.stat().st_mode & 0o777
        real_mkdir = os.mkdir

        def racing_mkdir(path, mode=0o777, *, dir_fd=None):
            if dir_fd is None:
                result = real_mkdir(path, mode)
            else:
                result = real_mkdir(path, mode, dir_fd=dir_fd)
            if path == "runtime" and dir_fd is not None:
                os.rename(runtime, detached)
                runtime.symlink_to(external, target_is_directory=True)
            return result

        with mock.patch("research_os.config.os.mkdir", side_effect=racing_mkdir):
            with self.assertRaises(ConfigurationError):
                ensure_runtime_directory(config)
        self.assertEqual(external.stat().st_mode & 0o777, original_mode)

    def test_protected_file_replacement_between_stat_and_open_is_rejected(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        target = project / "data" / "target.json"
        real_open = os.open
        replaced = False

        def racing_open(path, flags, mode=0o777, *, dir_fd=None):
            nonlocal replaced
            if path == "target.json" and dir_fd is not None and not replaced:
                replacement = target.with_name("target.next.json")
                replacement.write_text('{"target": 99}\n', encoding="utf-8")
                os.replace(replacement, target)
                replaced = True
            if dir_fd is None:
                return real_open(path, flags, mode)
            return real_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch("research_os.provenance.os.open", side_effect=racing_open):
            with self.assertRaises(IntegrityError):
                fingerprint_paths(config.root, [Path("data/target.json")])

    def test_protected_parent_replacement_during_hashing_is_rejected(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        data = project / "data"
        detached = project / "data.detached"
        replacement = Path(temporary.name) / "replacement-data"
        shutil.copytree(data, replacement)
        real_open = os.open
        replaced = False

        def racing_open(path, flags, mode=0o777, *, dir_fd=None):
            nonlocal replaced
            if path == "target.json" and dir_fd is not None and not replaced:
                os.rename(data, detached)
                os.rename(replacement, data)
                replaced = True
            if dir_fd is None:
                return real_open(path, flags, mode)
            return real_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch("research_os.provenance.os.open", side_effect=racing_open):
            with self.assertRaises(IntegrityError):
                fingerprint_paths(config.root, [Path("data/target.json")])


if __name__ == "__main__":
    unittest.main()
