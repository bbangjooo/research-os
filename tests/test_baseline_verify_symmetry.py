from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from research_os.contracts import canonical_json, sha256_json
from research_os.errors import IntegrityError, ProtocolError
from research_os.service import ResearchService

ROOT = Path(__file__).resolve().parents[1]

ADAPTER_SOURCE = r"""#!/usr/bin/env python3
import json
import subprocess
import sys
from pathlib import Path

VERSION = 1
OPERATIONS = {
    "describe",
    "fingerprint",
    "baseline",
    "materialize",
    "run",
    "evaluate",
    "verify",
    "cleanup",
}


def respond(request, *, ok=True, payload=None, error=None, retryable=False):
    value = {
        "protocol_version": VERSION,
        "request_id": request.get("request_id"),
        "ok": ok,
        "retryable": retryable,
        "payload": payload or {},
        "diagnostics": [],
    }
    if error is not None:
        value["error"] = error
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


def load_result(workspace):
    return json.loads((workspace / "outputs" / "result.json").read_text())


def append_trace(project, request):
    runtime = project / ".research-os" / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    entry = {
        "operation": request.get("operation"),
        "experiment_id": request.get("experiment_id"),
        "workspace": request.get("workspace"),
        "payload": request.get("payload") or {},
    }
    with (runtime / "adapter-trace.jsonl").open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(entry, sort_keys=True, separators=(",", ":")) + "\n")


def main():
    try:
        request = json.loads(sys.stdin.read())
        operation = request["operation"]
        if request.get("protocol_version") != VERSION or operation not in OPERATIONS:
            raise ValueError("unsupported protocol or operation")
        project = Path(request["project_root"]).resolve()
        workspace_value = request.get("workspace")
        workspace = Path(workspace_value).resolve() if workspace_value else project
        payload = request.get("payload") or {}
        mode_path = project / ".research-os" / "runtime" / "adapter-mode"
        mode = mode_path.read_text(encoding="utf-8").strip() if mode_path.exists() else "ok"
        append_trace(project, request)

        if operation == "describe":
            respond(
                request,
                payload={"capabilities": sorted(OPERATIONS), "side_effects": []},
            )
        elif operation == "fingerprint":
            respond(
                request,
                payload={"dataset": "target-v1", "evaluator": "squared-error-v1"},
            )
        elif operation == "materialize":
            candidate = payload.get("candidate") or {}
            x = candidate.get("x")
            if not isinstance(x, (int, float)) or isinstance(x, bool):
                respond(
                    request,
                    ok=False,
                    error={
                        "category": "INVALID_EXPERIMENT",
                        "code": "INVALID_CANDIDATE",
                        "message": "x must be numeric",
                    },
                )
                return
            (workspace / "parameter.json").write_text(
                json.dumps({"x": float(x)}, sort_keys=True) + "\n"
            )
            respond(request)
        elif operation in {"baseline", "run"}:
            completed = subprocess.run(
                [sys.executable, str(project / "evaluator.py"), str(workspace)],
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode:
                respond(
                    request,
                    ok=False,
                    error={
                        "category": "INFRASTRUCTURE",
                        "code": "EVALUATOR_FAILED",
                        "message": completed.stderr[-1000:],
                    },
                )
                return
            if operation == "baseline":
                if mode == "baseline_workspace_mutation":
                    protected = workspace / ".research-os" / "adapter.py"
                    protected.write_text(
                        protected.read_text(encoding="utf-8") + "\n# mutated\n",
                        encoding="utf-8",
                    )
                result = load_result(workspace)
                result["artifacts"] = [
                    {
                        "path": "outputs/result.json",
                        "media_type": "application/json",
                        "retention": "run",
                        "sensitivity": "public",
                    }
                ]
                respond(request, payload=result)
            else:
                respond(request)
        elif operation == "evaluate":
            result = load_result(workspace)
            result["artifacts"] = [
                {
                    "path": "outputs/result.json",
                    "media_type": "application/json",
                    "retention": "project",
                    "sensitivity": "public",
                }
            ]
            respond(request, payload=result)
        elif operation == "verify":
            if mode == "negative" and str(request.get("experiment_id", "")).startswith("base_"):
                respond(
                    request,
                    payload={
                        "valid": False,
                        "category": "INSUFFICIENT_EVIDENCE",
                        "reason_code": "BASELINE_EVIDENCE_MISSING",
                    },
                )
            elif mode in {"malformed", "malformed_artifact_mutation"} and str(request.get("experiment_id", "")).startswith("base_"):
                if mode == "malformed_artifact_mutation":
                    (workspace / "outputs" / "result.json").write_text(
                        '{"tampered":true}\n', encoding="utf-8"
                    )
                respond(request, payload={"valid": "yes", "reason_code": "OK"})
            elif mode == "failed_workspace_mutation" and str(request.get("experiment_id", "")).startswith("base_"):
                (workspace / "rogue-after-verify.txt").write_text(
                    "undeclared mutation\n", encoding="utf-8"
                )
                respond(
                    request,
                    ok=False,
                    error={
                        "category": "INFRASTRUCTURE",
                        "code": "VERIFY_PROCESS_FAILED",
                        "message": "fixture verifier failed after mutation",
                    },
                )
            else:
                if mode == "verifier_source_mutation":
                    readme = project / "README.md"
                    readme.write_text(
                        readme.read_text(encoding="utf-8") + "\nverifier mutation\n",
                        encoding="utf-8",
                    )
                elif mode == "verifier_artifact_mutation":
                    (workspace / "outputs" / "result.json").write_text(
                        '{"tampered":true}\n', encoding="utf-8"
                    )
                respond(request, payload={"valid": True, "reason_code": "OK"})
        else:
            respond(request)
    except Exception as exc:
        fallback = locals().get("request", {})
        respond(
            fallback,
            ok=False,
            error={
                "category": "INFRASTRUCTURE",
                "code": "ADAPTER_EXCEPTION",
                "message": str(exc),
            },
        )


if __name__ == "__main__":
    main()
"""


class BaselineVerifySymmetryTests(unittest.TestCase):
    def copy_project(self, *, mode: str = "ok") -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        project = Path(temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        (project / ".research-os" / "adapter.py").write_text(ADAPTER_SOURCE, encoding="utf-8")
        runtime.mkdir(parents=True)
        (runtime / "adapter-mode").write_text(mode + "\n", encoding="utf-8")
        return project

    @staticmethod
    def trace(project: Path) -> list[dict[str, object]]:
        path = project / ".research-os" / "runtime" / "adapter-trace.jsonl"
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    @staticmethod
    def baseline_events(service: ResearchService):
        return [
            event for event in service.event_log.read() if event.event_type == "BASELINE_RECORDED"
        ]

    def test_two_repeats_bind_verify_to_exact_results_and_workspace_artifacts(self):
        project = self.copy_project()
        service = ResearchService(project)

        baseline = service.baseline()

        operations = [
            entry for entry in self.trace(project) if entry["operation"] in {"baseline", "verify"}
        ]
        self.assertEqual(
            [entry["operation"] for entry in operations],
            ["baseline", "verify", "baseline", "verify"],
        )
        self.assertEqual(len(baseline["verifications"]), 2)
        self.assertEqual(len(baseline["artifacts"]), 2)
        for repetition in range(2):
            baseline_call = operations[repetition * 2]
            verify_call = operations[repetition * 2 + 1]
            verification = baseline["verifications"][repetition]
            result_digest = sha256_json(baseline["observations"][repetition])
            self.assertEqual(
                baseline_call["payload"],
                {"repetition": repetition, "repetitions": 2},
            )
            self.assertTrue(str(baseline_call["experiment_id"]).startswith("base_"))
            self.assertEqual(verify_call["experiment_id"], baseline_call["experiment_id"])
            self.assertEqual(verify_call["workspace"], baseline_call["workspace"])
            self.assertEqual(verify_call["payload"], {"result_digest": result_digest})
            self.assertEqual(
                verification,
                {
                    "repetition": repetition,
                    "result_digest": result_digest,
                    "verdict": {"valid": True, "reason_code": "OK"},
                },
            )

            artifact = next(
                value
                for value in baseline["artifacts"]
                if value["baseline_repetition"] == repetition
            )
            stored = service.catalog.get(artifact["artifact_id"]).to_dict()
            published = dict(artifact)
            published.pop("baseline_repetition")
            self.assertEqual(stored, published)

        event_types = [event.event_type for event in service.event_log.read()]
        self.assertNotIn("STAGE_COMPLETED", event_types)
        self.assertEqual(event_types.count("BASELINE_RECORDED"), 1)

    def test_pre_verify_immutable_check_blocks_workspace_mutation(self):
        project = self.copy_project(mode="baseline_workspace_mutation")
        service = ResearchService(project)

        with self.assertRaisesRegex(IntegrityError, "protected workspace surfaces"):
            service.baseline()

        operations = [entry["operation"] for entry in self.trace(project)]
        self.assertEqual(
            [value for value in operations if value in {"baseline", "verify", "cleanup"}],
            ["baseline"],
        )
        self.assertEqual(len(self.baseline_events(service)), 0)

    def test_negative_and_malformed_verdicts_record_no_baseline(self):
        cases = (
            ("negative", "baseline verification rejected"),
            ("malformed", "invalid verdict"),
        )
        for mode, message in cases:
            with self.subTest(mode=mode):
                project = self.copy_project(mode=mode)
                service = ResearchService(project)

                with self.assertRaisesRegex(ProtocolError, message):
                    service.baseline()

                operations = [entry["operation"] for entry in self.trace(project)]
                self.assertEqual(
                    [value for value in operations if value in {"baseline", "verify", "cleanup"}],
                    ["baseline", "verify", "cleanup"],
                )
                self.assertEqual(len(self.baseline_events(service)), 0)

    def test_verifier_source_mutation_fails_post_verify_immutable_check(self):
        project = self.copy_project(mode="verifier_source_mutation")
        service = ResearchService(project)

        with self.assertRaisesRegex(IntegrityError, "source checkout changed"):
            service.baseline()

        operations = [entry["operation"] for entry in self.trace(project)]
        self.assertEqual(
            [value for value in operations if value in {"baseline", "verify", "cleanup"}],
            ["baseline", "verify"],
        )
        self.assertEqual(len(self.baseline_events(service)), 0)

    def test_verifier_artifact_mutation_fails_content_bound_recapture(self):
        project = self.copy_project(mode="verifier_artifact_mutation")
        service = ResearchService(project)

        with self.assertRaisesRegex(IntegrityError, "declared sha256"):
            service.baseline()

        operations = [entry["operation"] for entry in self.trace(project)]
        self.assertEqual(
            [value for value in operations if value in {"baseline", "verify", "cleanup"}],
            ["baseline", "verify", "cleanup"],
        )
        self.assertEqual(len(self.baseline_events(service)), 0)

    def test_malformed_or_failed_verify_cannot_hide_workspace_mutation(self):
        cases = (
            ("malformed_artifact_mutation", "declared sha256"),
            (
                "failed_workspace_mutation",
                "outside authorized mutable/output surfaces",
            ),
        )
        for mode, message in cases:
            with self.subTest(mode=mode):
                project = self.copy_project(mode=mode)
                service = ResearchService(project)

                with self.assertRaisesRegex(IntegrityError, message):
                    service.baseline()

                operations = [entry["operation"] for entry in self.trace(project)]
                self.assertEqual(
                    [
                        value
                        for value in operations
                        if value in {"baseline", "verify", "cleanup"}
                    ],
                    ["baseline", "verify", "cleanup"],
                )
                self.assertEqual(len(self.baseline_events(service)), 0)

    def test_verification_evidence_shape_digest_and_positive_verdict_are_validated(self):
        project = self.copy_project()
        service = ResearchService(project)
        recorded = service.baseline()
        compatibility = recorded["compatibility_digest"]

        cases = {
            "count": lambda payload: payload["verifications"].pop(),
            "alignment": lambda payload: payload["verifications"][0].update({"repetition": 1}),
            "digest": lambda payload: payload["verifications"][0].update(
                {"result_digest": "0" * 64}
            ),
            "negative": lambda payload: payload["verifications"][0].update(
                {
                    "verdict": {
                        "valid": False,
                        "category": "INSUFFICIENT_EVIDENCE",
                        "reason_code": "NO",
                    }
                }
            ),
            "unknown-field": lambda payload: payload["verifications"][0].update({"extra": True}),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                payload = json.loads(canonical_json(recorded))
                payload.pop("event_sequence")
                mutate(payload)
                payload.pop("digest")
                payload["digest"] = sha256_json(payload)
                with self.assertRaises(IntegrityError):
                    service._validate_baseline_payload(payload, compatibility)

    def test_replay_accepts_legacy_baseline_but_current_lookup_reseals_it(self):
        project = self.copy_project()
        service = ResearchService(project)
        recorded = service.baseline()
        legacy = json.loads(canonical_json(recorded))
        legacy.pop("event_sequence")
        legacy.pop("verifications")
        legacy["baseline_id"] = "base_legacy_without_verifications"
        legacy.pop("digest")
        legacy["digest"] = sha256_json(legacy)

        event_path = service.event_log.path
        projection_path = service.projection.path
        event_path.unlink()
        for path in (
            projection_path,
            Path(f"{projection_path}-wal"),
            Path(f"{projection_path}-shm"),
        ):
            if path.exists():
                path.unlink()

        current = ResearchService(project)
        current.doctor()
        current.event_log.append("BASELINE_RECORDED", legacy)
        exact_legacy_bytes = event_path.read_bytes()

        replay = current.replay()

        self.assertEqual(replay["status"]["baselines"], 1)
        self.assertEqual(event_path.read_bytes(), exact_legacy_bytes)

        outcome = current.run_once(project / "candidates" / "improve.json")

        events = current.event_log.read()
        baselines = [event for event in events if event.event_type == "BASELINE_RECORDED"]
        self.assertEqual(len(baselines), 2)
        self.assertNotIn("verifications", baselines[0].payload)
        self.assertEqual(len(baselines[1].payload["verifications"]), 2)
        registration = next(
            event for event in events if event.event_type == "EXPERIMENT_REGISTERED"
        )
        self.assertEqual(
            registration.payload["baseline_id"],
            baselines[1].payload["baseline_id"],
        )
        self.assertNotEqual(registration.payload["baseline_id"], legacy["baseline_id"])
        self.assertEqual(outcome["status"], "VALIDATED")

    def test_current_lookup_rejects_malformed_legacy_before_reseal_or_reuse(self):
        project = self.copy_project()
        service = ResearchService(project)
        recorded = service.baseline()
        malformed = json.loads(canonical_json(recorded))
        malformed.pop("event_sequence")
        malformed.pop("verifications")
        malformed["baseline_id"] = "base_malformed_legacy"
        malformed["digest"] = "0" * 64
        service.event_log.append("BASELINE_RECORDED", malformed)

        with self.assertRaisesRegex(IntegrityError, "baseline digest is invalid"):
            service.run_once(project / "candidates" / "improve.json")

        events = service.event_log.read()
        self.assertEqual(
            sum(event.event_type == "BASELINE_RECORDED" for event in events),
            2,
        )
        self.assertNotIn(
            "EXPERIMENT_REGISTERED",
            {event.event_type for event in events},
        )

    def test_replay_rejects_present_null_verification_extension(self):
        project = self.copy_project()
        service = ResearchService(project)
        recorded = service.baseline()
        malformed = json.loads(canonical_json(recorded))
        malformed.pop("event_sequence")
        malformed["baseline_id"] = "base_null_verifications"
        malformed["verifications"] = None
        malformed.pop("digest")
        malformed["digest"] = sha256_json(malformed)
        service.event_log.append("BASELINE_RECORDED", malformed)

        with self.assertRaisesRegex(IntegrityError, "verifications must be an array"):
            service.replay()


if __name__ == "__main__":
    unittest.main()
