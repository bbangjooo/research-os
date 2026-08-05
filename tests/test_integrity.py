from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from research_os.config import load_project_config
from research_os.contracts import (
    Operation,
    ProtocolRequest,
    ProtocolResponse,
    ResultEnvelope,
    TerminalStatus,
)
from research_os.errors import ConfigurationError, IntegrityError
from research_os.execution.adapter import (
    ERROR_INVALID_CALL,
    AdapterClient,
    AdapterProtocolError,
)
from research_os.execution.workspace import WorkspaceManager
from research_os.kernel.events import EventLog
from research_os.policy import decide
from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]


class IntegrityTests(unittest.TestCase):
    def test_result_metrics_wire_shape_is_an_object(self):
        with self.assertRaisesRegex(TypeError, "metrics must be an object"):
            ResultEnvelope.from_dict(
                {"metrics": [{"name": "score", "value": 1.0}]}
            )

    def copy_optimization(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        project = Path(temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        return temporary, project

    def test_event_log_refuses_duplicate_explicit_id_before_corruption(self):
        with tempfile.TemporaryDirectory() as temporary:
            log = EventLog(Path(temporary) / "events.jsonl", "test-project")
            log.append("PROJECT_INITIALIZED", {}, event_id="evt_fixed")
            with self.assertRaises(IntegrityError):
                log.append("PROJECT_INITIALIZED", {}, event_id="evt_fixed")
            self.assertEqual(len(log.read()), 1)

    def test_workspace_rejects_undeclared_new_file(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        manager = WorkspaceManager(load_project_config(project))
        handle = manager.create("exp_boundary_new")
        try:
            (handle.path / "rogue.txt").write_text("not declared\n", encoding="utf-8")
            with self.assertRaises(IntegrityError):
                manager.verify(handle)
        finally:
            manager.cleanup(handle)

    def test_artifact_ref_cannot_authorize_modifying_preexisting_file(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        manager = WorkspaceManager(load_project_config(project))
        handle = manager.create("exp_boundary_existing")
        try:
            (handle.path / "README.md").write_text("rewritten\n", encoding="utf-8")
            with self.assertRaises(IntegrityError):
                manager.verify(handle, allowed_outputs=[{"path": "README.md"}])
        finally:
            manager.cleanup(handle)

    def test_cache_named_path_cannot_bypass_mutation_boundary(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        manager = WorkspaceManager(load_project_config(project))
        handle = manager.create("exp_boundary_cache")
        try:
            cache = handle.path / ".cache"
            cache.mkdir()
            (cache / "payload").write_text("hidden\n", encoding="utf-8")
            with self.assertRaises(IntegrityError):
                manager.verify(handle)
        finally:
            manager.cleanup(handle)

    def test_constraint_and_diagnostic_arrays_fail_closed(self):
        with self.assertRaises(TypeError):
            ResultEnvelope.from_dict(
                {"metrics": {"score": 1.0}, "constraints": "failed"}
            )
        with self.assertRaises(TypeError):
            ProtocolResponse.from_dict(
                {
                    "protocol_version": 1,
                    "request_id": "req_1",
                    "ok": True,
                    "retryable": False,
                    "payload": {},
                    "diagnostics": "not-an-array",
                }
            )
        with self.assertRaises(TypeError):
            ProtocolResponse.success(
                request_id="req_2",
                payload={},
                diagnostics="not-an-array",
            )
        with self.assertRaises(ValueError):
            ProtocolResponse.from_dict(
                {
                    "protocol_version": 1,
                    "request_id": "req_error_null",
                    "ok": True,
                    "retryable": False,
                    "payload": {},
                    "error": None,
                }
            )
        with self.assertRaises(ValueError):
            ResultEnvelope(
                metrics={"score": 1.0},
                constraints=({"passed": True, "status": "failed"},),
            )
        duplicate_ref = {
            "path": "outputs/result.json",
            "media_type": "application/json",
            "retention": "run",
            "sensitivity": "internal",
        }
        with self.assertRaises(ValueError):
            ResultEnvelope(
                metrics={"score": 1.0},
                artifacts=(duplicate_ref, duplicate_ref),
            )

    def test_explicit_failed_constraint_cannot_be_promoted(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        result = ResultEnvelope(
            metrics={"loss": 1.0},
            constraints=({"name": "safety", "passed": False},),
        )
        decision = decide(config, result, 9.0, verified=True)
        self.assertEqual(decision.status, TerminalStatus.REJECTED)
        self.assertEqual(decision.reason_code, "HARD_CONSTRAINT_FAILED")

    def test_execution_operations_require_isolated_context_before_process_launch(self):
        with self.assertRaises(ValueError):
            ProtocolRequest.create(
                request_id="req_missing_workspace",
                operation=Operation.RUN,
                project_root=ROOT,
                payload={},
            )

        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        client = AdapterClient(load_project_config(project))
        with self.assertRaises(AdapterProtocolError) as raised:
            client.call(Operation.RUN)
        self.assertEqual(raised.exception.code, ERROR_INVALID_CALL)
        self.assertFalse((project / "outputs").exists())

    def test_config_rejects_paths_omitted_from_disposable_snapshots(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        git_dir = project / ".git"
        git_dir.mkdir()
        (git_dir / "evidence.json").write_text("{}\n", encoding="utf-8")
        config_path = project / ".research-os" / "project.toml"
        config_text = config_path.read_text(encoding="utf-8").replace(
            'evidence = ["data/target.json"]',
            'evidence = [".git/evidence.json"]',
        )
        config_path.write_text(config_text, encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            load_project_config(project)

    def test_candidate_reader_refuses_symbolic_links(self):
        temporary, project = self.copy_optimization()
        self.addCleanup(temporary.cleanup)
        outside = Path(temporary.name) / "outside.json"
        outside.write_text('{"x":2}\n', encoding="utf-8")
        linked = Path(temporary.name) / "candidate.json"
        linked.symlink_to(outside)

        with self.assertRaises(ConfigurationError):
            ResearchService(project).run_once(linked)

    def test_adapter_client_preserves_javascript_large_float_semantics(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / ".research-os" / "runtime" / "workspaces" / "case"
            workspace.mkdir(parents=True)
            adapter = root / "adapter.py"
            adapter.write_text(
                "import json, sys\n"
                "request = json.load(sys.stdin)\n"
                "prefix = {\"protocol_version\":1,\"request_id\":request[\"request_id\"],"
                "\"ok\":True,\"retryable\":False,\"diagnostics\":[]}\n"
                "encoded = json.dumps(prefix, separators=(\",\", \":\"))[:-1]\n"
                "sys.stdout.write(encoded + "
                "',\"payload\":{\"metrics\":{\"score\":100000000000000000000}}}')\n",
                encoding="utf-8",
            )
            client = AdapterClient(
                {
                    "root": root,
                    "adapter_command": [sys.executable, str(adapter)],
                    "timeout_seconds": 2,
                    "max_output_bytes": 65536,
                }
            )

            response = client.call(
                Operation.EVALUATE,
                workspace=workspace,
                experiment_id="exp_numeric",
            )

            self.assertEqual(response.result_envelope().metrics["score"], 1e20)


if __name__ == "__main__":
    unittest.main()
