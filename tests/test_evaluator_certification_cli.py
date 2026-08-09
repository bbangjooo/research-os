from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from research_os.certification import (
    EVALUATOR_CERTIFICATION_KIND,
    EVALUATOR_CERTIFICATION_RELATIVE,
    EVALUATOR_CERTIFICATION_SCHEMA_VERSION,
    EVALUATOR_REVIEW_KIND,
    REQUIRED_EVALUATOR_CHECK_IDS,
)
from research_os.cli import main
from research_os.contracts import canonical_json_bytes, sha256_json
from research_os.scaffold import initialize_project

_ADAPTER_TEMPLATE = '''#!/usr/bin/env python3
import json
import sys

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
FINGERPRINT = json.loads(__FINGERPRINT_JSON__)

request = json.loads(sys.stdin.read())
operation = request["operation"]
if operation == "describe":
    payload = {"capabilities": sorted(OPERATIONS), "side_effects": []}
elif operation == "fingerprint":
    payload = FINGERPRINT
else:
    raise SystemExit(f"unexpected fixture operation: {operation}")
response = {
    "protocol_version": 1,
    "request_id": request["request_id"],
    "ok": True,
    "retryable": False,
    "payload": payload,
    "diagnostics": [],
}
sys.stdout.write(json.dumps(response, sort_keys=True) + "\\n")
'''


def _passing_review(subject_digest: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": EVALUATOR_REVIEW_KIND,
        "subject_digest": subject_digest,
        "reviewer": "independent-cli-fixture",
        "independent_reviewer": True,
        "verdict": "PASS",
        "summary": "Independent fixture review passed every required check.",
        "checks": [
            {
                "id": check_id,
                "status": "PASS",
                "evidence": f"fixture evidence for {check_id}",
            }
            for check_id in sorted(REQUIRED_EVALUATOR_CHECK_IDS)
        ],
        "blocking_findings": [],
    }


class _WriteSpy(io.StringIO):
    def __init__(self) -> None:
        super().__init__()
        self.writes: list[str] = []

    def write(self, value: str) -> int:
        self.writes.append(value)
        return super().write(value)


class EvaluatorCertificationCLITests(unittest.TestCase):
    def make_project(
        self,
        adapter_fingerprint: dict[str, object],
    ) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        project = Path(temporary.name) / "project"
        project.mkdir()
        initialize_project(project, "cert-cli", "Certification CLI fixture")
        fingerprint_json = json.dumps(
            adapter_fingerprint,
            sort_keys=True,
            separators=(",", ":"),
        )
        adapter = project / ".research-os" / "adapter.py"
        adapter.write_text(
            _ADAPTER_TEMPLATE.replace(
                "__FINGERPRINT_JSON__",
                repr(fingerprint_json),
            ),
            encoding="utf-8",
        )
        adapter.chmod(0o700)
        return temporary, project

    def run_success(self, project: Path, *arguments: str) -> dict[str, object]:
        stdout = _WriteSpy()
        stderr = _WriteSpy()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(["--project", str(project), *arguments])
        self.assertEqual(exit_code, 0, stderr.getvalue())
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(stderr.writes, [])
        self.assertEqual(len(stdout.writes), 1)
        rendered = stdout.getvalue()
        self.assertTrue(rendered.endswith("\n"))
        value = json.loads(rendered)
        self.assertIsInstance(value, dict)
        return value

    def test_nested_fingerprint_real_cli_certification_lifecycle(self):
        nested_fingerprint = {
            "fixture_adapter_revision": "nested-v1",
            "models": [
                {
                    "name": "alpha",
                    "features": ["price", "volume"],
                }
            ],
        }
        temporary, project = self.make_project(nested_fingerprint)
        self.addCleanup(temporary.cleanup)

        doctor = self.run_success(project, "doctor")
        self.assertEqual(doctor["adapter_fingerprint"], nested_fingerprint)
        self.assertEqual(
            doctor["fingerprints"]["adapter"]["value"],
            nested_fingerprint,
        )

        subject = self.run_success(project, "evaluator-review-subject")
        self.assertEqual(
            subject["bindings"]["adapter"]["value"],
            nested_fingerprint,
        )
        self.assertEqual(json.loads(json.dumps(subject, allow_nan=False)), subject)

        review_path = Path(temporary.name) / "evaluator-review.json"
        review_path.write_text(
            json.dumps(
                _passing_review(str(subject["digest"])),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        certification = self.run_success(
            project,
            "certify-evaluator",
            str(review_path),
        )
        self.assertTrue(certification["certified"])
        self.assertTrue(certification["current"])
        self.assertEqual(certification["status"], "CERTIFIED")
        self.assertEqual(
            certification["review_subject_digest"],
            subject["digest"],
        )

        inspected = self.run_success(project, "inspect")
        self.assertEqual(inspected["project_id"], "cert-cli")
        context = self.run_success(project, "agent-context")
        inspected_certification = context["agent"]["evaluator_certification"]
        self.assertTrue(inspected_certification["certified"])
        self.assertTrue(inspected_certification["current"])
        self.assertEqual(inspected_certification["status"], "CERTIFIED")

    def test_flat_legacy_certificate_digest_and_cli_replay_remain_valid(self):
        flat_fingerprint = {
            "dataset": "fixture-data-v1",
            "evaluator": "fixture-evaluator-v1",
        }
        temporary, project = self.make_project(flat_fingerprint)
        self.addCleanup(temporary.cleanup)

        self.run_success(project, "doctor")
        subject = self.run_success(project, "evaluator-review-subject")
        review = _passing_review(str(subject["digest"]))
        unsigned = {
            "schema_version": EVALUATOR_CERTIFICATION_SCHEMA_VERSION,
            "kind": EVALUATOR_CERTIFICATION_KIND,
            "project_id": "cert-cli",
            "certified": True,
            "review": review,
            "review_digest": sha256_json(review),
            # This is the pre-normalization flat artifact construction: the
            # bindings are shallow-copied and the digest is taken immediately.
            "bindings": dict(subject["bindings"]),
        }
        legacy_artifact = {**unsigned, "digest": sha256_json(unsigned)}
        certificate_path = project / EVALUATOR_CERTIFICATION_RELATIVE
        certificate_path.write_bytes(canonical_json_bytes(legacy_artifact) + b"\n")
        certificate_path.chmod(0o600)

        context = self.run_success(project, "agent-context")
        certification = context["agent"]["evaluator_certification"]
        self.assertTrue(certification["certified"])
        self.assertTrue(certification["current"])
        self.assertEqual(
            certification["certification_digest"],
            legacy_artifact["digest"],
        )

        review_path = Path(temporary.name) / "flat-evaluator-review.json"
        review_path.write_text(
            json.dumps(review, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        replaced = self.run_success(
            project,
            "certify-evaluator",
            str(review_path),
            "--replace",
        )
        self.assertEqual(
            replaced["certification_digest"],
            legacy_artifact["digest"],
        )

        replayed = self.run_success(project, "replay")
        self.assertEqual(replayed["events_replayed"], 1)
        self.assertEqual(replayed["status"]["last_sequence"], 1)

    def test_nonserializable_command_result_keeps_stdout_atomic(self):
        stdout = _WriteSpy()
        stderr = _WriteSpy()
        with (
            mock.patch(
                "research_os.cli._dispatch",
                return_value={"not_json": object()},
            ),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = main(["inspect"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stdout.getvalue(), "")
        self.assertEqual(stdout.writes, [])
        self.assertEqual(len(stderr.writes), 1)
        self.assertEqual(stderr.getvalue(), stderr.writes[0])
        error = json.loads(stderr.getvalue())
        self.assertEqual(error["ok"], False)
        self.assertEqual(error["error"]["type"], "TypeError")
        self.assertIn("not JSON serializable", error["error"]["message"])


if __name__ == "__main__":
    unittest.main()
