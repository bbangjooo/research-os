from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from research_os.contracts import (
    Operation,
    ProtocolResponse,
    ResultEnvelope,
    VerifyResult,
    sha256_json,
)

ROOT = Path(__file__).resolve().parents[1]
OPERATIONS = frozenset(operation.value for operation in Operation)
DISCOVERY_OPERATIONS = frozenset({Operation.DESCRIBE, Operation.FINGERPRINT})


class ExampleAdapterTests(unittest.TestCase):
    def invoke(
        self,
        project: Path,
        command: list[str],
        operation: Operation,
        *,
        payload: dict[str, Any],
        workspace: Path | None = None,
        experiment_id: str | None = None,
    ) -> tuple[dict[str, Any], ProtocolResponse]:
        request: dict[str, Any] = {
            "protocol_version": 1,
            "request_id": uuid.uuid4().hex,
            "operation": operation.value,
            "project_root": str(project.resolve()),
            "workspace": None if workspace is None else str(workspace.resolve()),
            "payload": payload,
        }
        if operation in DISCOVERY_OPERATIONS:
            self.assertIsNone(workspace)
            self.assertIsNone(experiment_id)
            self.assertNotIn("experiment_id", request)
        else:
            self.assertIsNotNone(workspace)
            self.assertIsNotNone(experiment_id)
            request["experiment_id"] = experiment_id

        completed = subprocess.run(
            command,
            cwd=workspace or project,
            input=json.dumps(request, allow_nan=False),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        wire_response = json.loads(completed.stdout)
        self.assertEqual(
            set(wire_response),
            {
                "protocol_version",
                "request_id",
                "ok",
                "retryable",
                "payload",
                "diagnostics",
            },
        )
        response = ProtocolResponse.from_dict(wire_response)
        self.assertEqual(response.protocol_version, 1)
        self.assertEqual(response.request_id, request["request_id"])
        self.assertTrue(response.ok)
        self.assertFalse(response.retryable)
        self.assertEqual(response.diagnostics, ())
        return request, response

    def assert_adapter_conforms(
        self,
        *,
        project_name: str,
        command_for: Callable[[Path], list[str]],
        candidate: dict[str, Any],
        primary_metric: str,
        baseline_value: float,
        candidate_value: float,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            shutil.copytree(ROOT / "examples" / project_name, project)
            command = command_for(project)

            describe_request, describe = self.invoke(
                project,
                command,
                Operation.DESCRIBE,
                payload={},
            )
            self.assertIsNone(describe_request["workspace"])
            describe_payload = describe.to_dict()["payload"]
            self.assertEqual(set(describe_payload["capabilities"]), OPERATIONS)
            self.assertEqual(describe_payload["side_effects"], [])

            _, first_fingerprint = self.invoke(
                project,
                command,
                Operation.FINGERPRINT,
                payload={},
            )
            _, second_fingerprint = self.invoke(
                project,
                command,
                Operation.FINGERPRINT,
                payload={},
            )
            self.assertEqual(
                first_fingerprint.to_dict()["payload"],
                second_fingerprint.to_dict()["payload"],
            )

            baseline_workspace = root / "baseline-workspace"
            shutil.copytree(project, baseline_workspace)
            baseline_request, baseline = self.invoke(
                project,
                command,
                Operation.BASELINE,
                payload={"repetition": 0, "repetitions": 1},
                workspace=baseline_workspace,
                experiment_id="base_reference",
            )
            self.assertEqual(
                baseline_request["payload"],
                {"repetition": 0, "repetitions": 1},
            )
            baseline_result = baseline.result_envelope()
            self.assertIsInstance(baseline_result, ResultEnvelope)
            self.assertEqual(
                baseline_result.metrics[primary_metric], baseline_value
            )
            baseline_result_digest = sha256_json(baseline_result.to_dict())
            baseline_verify_request, baseline_verification = self.invoke(
                project,
                command,
                Operation.VERIFY,
                payload={"result_digest": baseline_result_digest},
                workspace=baseline_workspace,
                experiment_id="base_reference",
            )
            self.assertEqual(
                baseline_verify_request["payload"],
                {"result_digest": baseline_result_digest},
            )
            baseline_verdict = baseline_verification.verify_result()
            self.assertIsInstance(baseline_verdict, VerifyResult)
            self.assertTrue(baseline_verdict.valid)
            self.assertIsNone(baseline_verdict.category)
            _, baseline_cleanup = self.invoke(
                project,
                command,
                Operation.CLEANUP,
                payload={},
                workspace=baseline_workspace,
                experiment_id="base_reference",
            )
            self.assertEqual(baseline_cleanup.to_dict()["payload"], {})

            workspace = root / "experiment-workspace"
            shutil.copytree(project, workspace)
            candidate_digest = sha256_json(candidate)
            materialize_request, materialized = self.invoke(
                project,
                command,
                Operation.MATERIALIZE,
                payload={
                    "candidate": candidate,
                    "candidate_digest": candidate_digest,
                },
                workspace=workspace,
                experiment_id="exp_reference",
            )
            self.assertEqual(
                materialize_request["payload"]["candidate"], candidate
            )
            self.assertEqual(
                materialize_request["payload"]["candidate_digest"],
                candidate_digest,
            )
            self.assertEqual(materialized.to_dict()["payload"], {})

            run_request, run = self.invoke(
                project,
                command,
                Operation.RUN,
                payload={
                    "candidate_digest": candidate_digest,
                    "baseline_id": "base_reference",
                },
                workspace=workspace,
                experiment_id="exp_reference",
            )
            self.assertEqual(
                run_request["payload"],
                {
                    "candidate_digest": candidate_digest,
                    "baseline_id": "base_reference",
                },
            )
            self.assertEqual(run.to_dict()["payload"], {})

            evaluate_request, evaluation = self.invoke(
                project,
                command,
                Operation.EVALUATE,
                payload={"candidate_digest": candidate_digest},
                workspace=workspace,
                experiment_id="exp_reference",
            )
            self.assertEqual(
                evaluate_request["payload"],
                {"candidate_digest": candidate_digest},
            )
            result = evaluation.result_envelope()
            self.assertIsInstance(result, ResultEnvelope)
            self.assertEqual(result.metrics[primary_metric], candidate_value)

            result_digest = sha256_json(result.to_dict())
            verify_request, verification = self.invoke(
                project,
                command,
                Operation.VERIFY,
                payload={"result_digest": result_digest},
                workspace=workspace,
                experiment_id="exp_reference",
            )
            self.assertEqual(
                verify_request["payload"], {"result_digest": result_digest}
            )
            verdict = verification.verify_result()
            self.assertIsInstance(verdict, VerifyResult)
            self.assertTrue(verdict.valid)
            self.assertIsNone(verdict.category)

            cleanup_request, cleanup = self.invoke(
                project,
                command,
                Operation.CLEANUP,
                payload={},
                workspace=workspace,
                experiment_id="exp_reference",
            )
            self.assertEqual(cleanup_request["payload"], {})
            self.assertEqual(cleanup.to_dict()["payload"], {})

    def test_python_optimization_adapter_conforms_to_all_operations(self):
        self.assert_adapter_conforms(
            project_name="toy_optimization",
            command_for=lambda project: [
                sys.executable,
                str(project / ".research-os" / "adapter.py"),
            ],
            candidate={"x": 2.0},
            primary_metric="loss",
            baseline_value=9.0,
            candidate_value=1.0,
        )

    @unittest.skipUnless(
        shutil.which("node"), "Node is required for the language-neutral fixture"
    )
    def test_javascript_retrieval_adapter_conforms_to_all_operations(self):
        self.assert_adapter_conforms(
            project_name="toy_retrieval",
            command_for=lambda project: [
                "node",
                str(project / ".research-os" / "adapter.mjs"),
            ],
            candidate={"title_weight": 2.0},
            primary_metric="recall_at_1",
            baseline_value=1 / 3,
            candidate_value=1.0,
        )


if __name__ == "__main__":
    unittest.main()
