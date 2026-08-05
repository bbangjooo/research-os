from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from research_os.contracts import TerminalStatus
from research_os.errors import LifecycleError
from research_os.execution import workspace as workspace_module
from research_os.execution.workspace import WorkspaceHandle, WorkspaceManager
from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]


class WorkspaceExceptionPreservationTests(unittest.TestCase):
    def make_manager(
        self,
    ) -> tuple[tempfile.TemporaryDirectory[str], WorkspaceManager]:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "project"
        project.mkdir()
        (project / "input.txt").write_text("evidence\n", encoding="utf-8")
        return temporary, WorkspaceManager({"root": project})

    def test_create_preserves_keyboard_interrupt_when_removal_fails(self):
        _, manager = self.make_manager()
        primary = KeyboardInterrupt("stop requested")
        cleanup_error = LifecycleError("cannot remove partial workspace")

        with (
            patch.object(workspace_module.shutil, "copytree", side_effect=primary),
            patch.object(
                manager,
                "_remove_workspace_path",
                side_effect=cleanup_error,
            ),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            manager.create("exp_interrupt")

        self.assertIs(raised.exception, primary)
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(any("LifecycleError" in note for note in notes))
        self.assertEqual(len(manager.cleanup_orphans()), 1)

    def test_create_preserves_primary_when_cleanup_is_interrupted(self):
        _, manager = self.make_manager()
        primary = RuntimeError("copy failed")
        cleanup_error = KeyboardInterrupt("cleanup interrupted")

        with (
            patch.object(workspace_module.shutil, "copytree", side_effect=primary),
            patch.object(
                manager,
                "_remove_workspace_path",
                side_effect=cleanup_error,
            ),
            self.assertRaises(RuntimeError) as raised,
        ):
            manager.create("exp_copy_failure")

        self.assertIs(raised.exception, primary)
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(any("KeyboardInterrupt" in note for note in notes))
        self.assertEqual(len(manager.cleanup_orphans()), 1)

    def test_context_manager_cleanup_cannot_mask_body_exception(self):
        _, manager = self.make_manager()
        primary = KeyboardInterrupt("body interrupted")
        handle: WorkspaceHandle | None = None

        with (
            patch.object(
                manager,
                "cleanup",
                side_effect=LifecycleError("cleanup failed"),
            ),
            self.assertRaises(KeyboardInterrupt) as raised,
        ):
            with manager.workspace("exp_context") as created:
                handle = created
                raise primary

        self.assertIs(raised.exception, primary)
        notes = getattr(raised.exception, "__notes__", ())
        self.assertTrue(any("LifecycleError" in note for note in notes))
        self.assertIsNotNone(handle)
        manager.cleanup(handle)

    def test_service_classifies_interrupted_copy_as_cancelled_when_removal_fails(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        service = ResearchService(project)
        service.baseline()

        with (
            patch.object(
                workspace_module.shutil,
                "copytree",
                side_effect=KeyboardInterrupt("stop requested"),
            ),
            patch.object(
                WorkspaceManager,
                "_remove_workspace_path",
                side_effect=OSError("cleanup failed"),
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            service.run_once(project / "candidates" / "improve.json")

        self.assertEqual(
            service.status()["experiments_by_status"],
            {TerminalStatus.CANCELLED.value: 1},
        )


if __name__ == "__main__":
    unittest.main()
