from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

from research_os.config import load_project_config
from research_os.errors import IntegrityError
from research_os.provenance import (
    fingerprint_mutable_paths,
    project_fingerprints,
)

ROOT = Path(__file__).resolve().parents[1]


class MutableFingerprintTests(unittest.TestCase):
    def copy_optimization(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        project = Path(temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        return temporary, project

    def configure_mutable(self, project: Path, relative: str) -> None:
        project_file = project / ".research-os" / "project.toml"
        project_file.write_text(
            project_file.read_text(encoding="utf-8").replace(
                'mutable = ["parameter.json"]',
                f'mutable = ["{relative}"]',
            ),
            encoding="utf-8",
        )

    def test_mutable_content_rotates_compatibility(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)

        before = cast(dict[str, Any], project_fingerprints(config))
        (project / "parameter.json").write_text(
            '{"value": 2.5}\n', encoding="utf-8"
        )
        after = cast(dict[str, Any], project_fingerprints(config))

        self.assertEqual(
            [record["path"] for record in before["mutable"]["files"]],
            ["parameter.json"],
        )
        self.assertNotEqual(before["mutable"]["digest"], after["mutable"]["digest"])
        self.assertNotEqual(
            before["compatibility_digest"], after["compatibility_digest"]
        )
        for surface in ("constitution", "protected", "evidence", "environment"):
            self.assertEqual(before[surface]["digest"], after[surface]["digest"])

    def test_missing_mutable_path_has_an_explicit_marker_and_can_appear(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        self.configure_mutable(project, "generated/parameter.json")
        config = load_project_config(project)

        before = cast(dict[str, Any], project_fingerprints(config))

        self.assertEqual(
            before["mutable"]["files"],
            [
                {
                    "path": "generated/parameter.json",
                    "kind": "missing",
                    "missing_at": "generated",
                }
            ],
        )
        (project / "generated").mkdir()
        (project / "generated" / "parameter.json").write_text(
            '{"value": 1.0}\n', encoding="utf-8"
        )
        after = cast(dict[str, Any], project_fingerprints(config))
        self.assertNotEqual(before["mutable"]["digest"], after["mutable"]["digest"])
        self.assertNotEqual(
            before["compatibility_digest"], after["compatibility_digest"]
        )

    def test_missing_parent_and_missing_leaf_have_distinct_fingerprints(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)

        missing_parent = fingerprint_mutable_paths(
            root, [Path("generated/parameter.json")]
        )
        (root / "generated").mkdir()
        missing_leaf = fingerprint_mutable_paths(
            root, [Path("generated/parameter.json")]
        )

        self.assertNotEqual(missing_parent["digest"], missing_leaf["digest"])
        self.assertEqual(
            missing_parent["files"][0]["missing_at"], "generated"
        )
        self.assertEqual(
            missing_leaf["files"][0]["missing_at"], "generated/parameter.json"
        )

    def test_mutable_fingerprint_is_independent_of_declaration_order(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / "z.txt").write_text("stable\n", encoding="utf-8")

        forward = cast(
            dict[str, Any],
            fingerprint_mutable_paths(
                root, [Path("z.txt"), Path("missing.txt")]
            ),
        )
        reverse = cast(
            dict[str, Any],
            fingerprint_mutable_paths(
                root, [Path("missing.txt"), Path("z.txt")]
            ),
        )

        self.assertEqual(forward, reverse)
        self.assertEqual(
            [record["path"] for record in forward["files"]],
            ["missing.txt", "z.txt"],
        )

    def test_symlink_inserted_after_config_load_is_rejected(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        self.configure_mutable(project, "optional.json")
        config = load_project_config(project)
        outside = Path(temporary.name) / "outside.json"
        outside.write_text("{}\n", encoding="utf-8")
        (project / "optional.json").symlink_to(outside)

        with self.assertRaisesRegex(IntegrityError, "symlink"):
            project_fingerprints(config)

    def test_mutable_file_replacement_between_stat_and_open_is_rejected(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        target = project / "parameter.json"
        real_open = os.open
        replaced = False

        def racing_open(path, flags, mode=0o777, *, dir_fd=None):
            nonlocal replaced
            if path == "parameter.json" and dir_fd is not None and not replaced:
                replacement = target.with_name("parameter.next.json")
                replacement.write_text('{"value": 99}\n', encoding="utf-8")
                os.replace(replacement, target)
                replaced = True
            if dir_fd is None:
                return real_open(path, flags, mode)
            return real_open(path, flags, mode, dir_fd=dir_fd)

        with mock.patch("research_os.provenance.os.open", side_effect=racing_open):
            with self.assertRaises(IntegrityError):
                project_fingerprints(config)

    def test_missing_mutable_path_creation_race_is_rejected(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        self.configure_mutable(project, "generated.json")
        config = load_project_config(project)
        target = project / "generated.json"
        real_stat = os.stat
        observed_missing = False

        def racing_stat(path, *args, dir_fd=None, follow_symlinks=True, **kwargs):
            nonlocal observed_missing
            if path == "generated.json" and dir_fd is not None and not observed_missing:
                observed_missing = True
                try:
                    return real_stat(
                        path,
                        *args,
                        dir_fd=dir_fd,
                        follow_symlinks=follow_symlinks,
                        **kwargs,
                    )
                except FileNotFoundError:
                    target.write_text("{}\n", encoding="utf-8")
                    raise
            if dir_fd is None:
                return real_stat(
                    path,
                    *args,
                    follow_symlinks=follow_symlinks,
                    **kwargs,
                )
            return real_stat(
                path,
                *args,
                dir_fd=dir_fd,
                follow_symlinks=follow_symlinks,
                **kwargs,
            )

        with mock.patch("research_os.provenance.os.stat", side_effect=racing_stat):
            with self.assertRaisesRegex(IntegrityError, "appeared"):
                project_fingerprints(config)


if __name__ == "__main__":
    unittest.main()
