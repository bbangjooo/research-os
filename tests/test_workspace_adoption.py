from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_os.errors import ConfigurationError, IntegrityError, LifecycleError
from research_os.execution.workspace import WorkspaceManager, hash_tree


class WorkspaceAdoptionTests(unittest.TestCase):
    def make_project(
        self,
    ) -> tuple[tempfile.TemporaryDirectory[str], Path, dict[str, object]]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "project"
        project.mkdir()
        (project / "input.txt").write_text("source\n", encoding="utf-8")
        (project / "protected.txt").write_text("sealed\n", encoding="utf-8")
        config: dict[str, object] = {
            "root": project,
            "mutable_paths": ["scratch"],
            "protected_paths": ["protected.txt"],
        }
        return temporary, project, config

    def leave_orphan(
        self,
        config: dict[str, object],
        experiment_id: str,
    ) -> tuple[WorkspaceManager, Path, str]:
        original_manager = WorkspaceManager(config)
        original = original_manager.create(experiment_id)
        expected_source_hash = original.source_hash
        original_manager.detach(original)
        return original_manager, original.path, expected_source_hash

    def test_adopt_reconstructs_clean_seals_and_can_verify_crash_output(self):
        _, _, config = self.make_project()
        original_manager, orphan_path, source_hash = self.leave_orphan(
            config, "exp_crash"
        )
        artifact = orphan_path / "evidence.json"
        artifact.write_text('{"score": 1}\n', encoding="utf-8")

        recovery_manager = WorkspaceManager(config)
        adopted = recovery_manager.adopt_orphan("exp_crash", source_hash)
        try:
            self.assertEqual(adopted.path, orphan_path)
            self.assertNotIn("evidence.json", adopted.workspace_manifest)
            self.assertEqual(adopted.source_hash, source_hash)
            self.assertTrue(
                recovery_manager.verify(
                    adopted,
                    allowed_outputs=[{"path": "evidence.json"}],
                )
            )
            self.assertEqual(
                sorted(path.name for path in recovery_manager.workspaces_root.iterdir()),
                [orphan_path.name],
            )
        finally:
            recovery_manager.cleanup(adopted)
            original_manager.close()

        self.assertFalse(orphan_path.exists())

    def test_detach_preserves_workspace_from_close_and_orphan_cleanup(self):
        _, _, config = self.make_project()
        manager = WorkspaceManager(config)
        handle = manager.create("exp_preserve")

        manager.detach(handle)
        manager.detach(handle)
        self.assertEqual(manager.cleanup_orphans(), ())
        manager.close()
        self.assertTrue(handle.path.is_dir())
        with self.assertRaises(LifecycleError):
            manager.verify(handle)

        next_manager = WorkspaceManager(config)
        self.assertEqual(next_manager.cleanup_orphans(), (handle.path.name,))
        self.assertFalse(handle.path.exists())

    def test_source_mismatch_rejects_adoption_without_touching_orphan(self):
        _, project, config = self.make_project()
        original_manager, orphan_path, source_hash = self.leave_orphan(
            config, "exp_source_drift"
        )
        (project / "input.txt").write_text("changed\n", encoding="utf-8")

        recovery_manager = WorkspaceManager(config)
        with self.assertRaisesRegex(IntegrityError, "no longer matches"):
            recovery_manager.adopt_orphan("exp_source_drift", source_hash)

        self.assertTrue(orphan_path.is_dir())
        self.assertEqual(
            sorted(path.name for path in recovery_manager.workspaces_root.iterdir()),
            [orphan_path.name],
        )
        original_manager.close()

    def test_adopt_rejects_missing_ambiguous_and_unsafe_matches(self):
        _, _, config = self.make_project()
        manager = WorkspaceManager(config)
        source_hash = hash_tree(manager.project_root)

        with self.assertRaisesRegex(IntegrityError, "no orphan workspace"):
            manager.adopt_orphan("exp_missing", source_hash)
        with self.assertRaises(ConfigurationError):
            manager.adopt_orphan("../unsafe", source_hash)

        first = manager.create("exp_ambiguous")
        second = manager.create("exp_ambiguous")
        manager.detach(first)
        manager.detach(second)
        with self.assertRaisesRegex(IntegrityError, "multiple orphan workspaces"):
            WorkspaceManager(config).adopt_orphan("exp_ambiguous", source_hash)

        outside = manager.project_root.parent / "outside"
        outside.mkdir()
        unsafe = manager.workspaces_root / "exp_symlink-unsafe"
        unsafe.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(IntegrityError, "not a safe directory"):
            WorkspaceManager(config).adopt_orphan("exp_symlink", source_hash)

    def test_adopt_rechecks_orphan_identity_after_reference_is_removed(self):
        _, _, config = self.make_project()
        original_manager, orphan_path, source_hash = self.leave_orphan(
            config, "exp_replaced"
        )
        recovery_manager = WorkspaceManager(config)
        original_locator = recovery_manager._locate_orphan_workspace
        calls = 0

        def replace_before_second_lookup(
            experiment_id: str,
        ) -> tuple[Path, tuple[int, int]]:
            nonlocal calls
            calls += 1
            if calls == 2:
                saved = recovery_manager.workspaces_root / "saved-orphan"
                orphan_path.rename(saved)
                orphan_path.mkdir()
            return original_locator(experiment_id)

        with (
            patch.object(
                recovery_manager,
                "_locate_orphan_workspace",
                side_effect=replace_before_second_lookup,
            ),
            self.assertRaisesRegex(IntegrityError, "changed identity"),
        ):
            recovery_manager.adopt_orphan("exp_replaced", source_hash)

        self.assertTrue(orphan_path.is_dir())
        self.assertFalse(
            any(
                path.name.startswith("rosrecovery")
                for path in recovery_manager.workspaces_root.iterdir()
            )
        )
        original_manager.close()


if __name__ == "__main__":
    unittest.main()
