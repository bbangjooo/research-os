from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from research_os.contracts import (
    FailureCategory,
    Operation,
    ProtocolResponse,
    TerminalStatus,
    VerifyResult,
)
from research_os.contracts import (
    ProtocolError as AdapterFailure,
)
from research_os.errors import ProtocolError
from research_os.service import (
    AdapterOperationError,
    ResearchService,
    _classify_failure,
)

ROOT = Path(__file__).resolve().parents[1]


class FailureTaxonomyTests(unittest.TestCase):
    def test_categories_have_one_deterministic_terminal_status(self):
        self.assertEqual(
            {category: category.terminal_status for category in FailureCategory},
            {
                FailureCategory.INVALID_EXPERIMENT: (TerminalStatus.INVALID_EXPERIMENT),
                FailureCategory.TIMED_OUT: TerminalStatus.TIMED_OUT,
                FailureCategory.INSUFFICIENT_EVIDENCE: (
                    TerminalStatus.INSUFFICIENT_EVIDENCE
                ),
                FailureCategory.INFRASTRUCTURE: TerminalStatus.INFRA_FAILED,
            },
        )

    def test_exact_legacy_code_is_supported_but_substrings_are_not(self):
        legacy = AdapterFailure.from_dict(
            {"code": "INVALID_CANDIDATE", "message": "bad parameter"}
        )
        self.assertIs(legacy.category, FailureCategory.INVALID_EXPERIMENT)

        with self.assertRaisesRegex(ValueError, "category is required"):
            AdapterFailure.from_dict(
                {"code": "ALMOST_INVALID_CANDIDATE", "message": "unknown legacy code"}
            )

    def test_explicit_category_supports_project_specific_codes(self):
        failure = AdapterFailure.from_dict(
            {
                "category": "INVALID_EXPERIMENT",
                "code": "PARAMETER_OUTSIDE_SEARCH_SPACE",
                "message": "outside declared range",
            }
        )
        self.assertIs(failure.category, FailureCategory.INVALID_EXPERIMENT)
        self.assertEqual(failure.to_dict()["category"], "INVALID_EXPERIMENT")

    def test_category_is_validated_against_operation(self):
        response = ProtocolResponse.failure(
            request_id="req_1",
            error={
                "category": "INVALID_EXPERIMENT",
                "code": "CUSTOM_INVALID",
                "message": "candidate is invalid",
            },
        )
        failure = AdapterOperationError(Operation.MATERIALIZE, response)
        self.assertEqual(
            _classify_failure(failure),
            (TerminalStatus.INVALID_EXPERIMENT, "CUSTOM_INVALID"),
        )

        with self.assertRaisesRegex(ProtocolError, "invalid failure category"):
            AdapterOperationError(Operation.RUN, response)

        misleading_code = ProtocolResponse.failure(
            request_id="req_2",
            error={
                "category": "INFRASTRUCTURE",
                "code": "INVALID_CANDIDATE",
                "message": "the explicit category is authoritative",
            },
        )
        self.assertEqual(
            _classify_failure(
                AdapterOperationError(Operation.MATERIALIZE, misleading_code)
            ),
            (TerminalStatus.INFRA_FAILED, "INVALID_CANDIDATE"),
        )


class VerifyVerdictTests(unittest.TestCase):
    def copy_optimization_example(
        self,
    ) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        project = Path(temporary.name) / "project"
        shutil.copytree(ROOT / "examples" / "toy_optimization", project)
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        return temporary, project

    def test_explicit_adapter_failure_category_reaches_terminal_event(self):
        temporary, project = self.copy_optimization_example()
        self.addCleanup(temporary.cleanup)

        outcome = ResearchService(project).run_once(
            project / "candidates" / "invalid.json"
        )

        self.assertEqual(outcome["status"], TerminalStatus.INVALID_EXPERIMENT.value)
        self.assertEqual(outcome["reason_code"], "INVALID_CANDIDATE")
        self.assertEqual(outcome["error"]["category"], "INVALID_EXPERIMENT")

    def test_negative_verdict_requires_an_evidence_category_and_reason(self):
        verdict = VerifyResult.from_dict(
            {
                "valid": False,
                "category": "INSUFFICIENT_EVIDENCE",
                "reason_code": "OUT_OF_SAMPLE_REPORT_MISSING",
            }
        )
        self.assertIs(verdict.category, FailureCategory.INSUFFICIENT_EVIDENCE)

        with self.assertRaisesRegex(ValueError, "category is required"):
            VerifyResult.from_dict({"valid": False, "reason_code": "EVIDENCE_MISSING"})
        with self.assertRaisesRegex(ValueError, "valid verify result"):
            VerifyResult.from_dict(
                {
                    "valid": True,
                    "category": "INSUFFICIENT_EVIDENCE",
                    "reason_code": "CONTRADICTORY",
                }
            )

    def test_negative_verify_reason_reaches_terminal_event(self):
        temporary, project = self.copy_optimization_example()
        self.addCleanup(temporary.cleanup)
        adapter = project / ".research-os" / "adapter.py"
        source = adapter.read_text(encoding="utf-8")
        old = """        elif operation == "verify":
            result = load_result(workspace)
            valid = isinstance(result.get("metrics", {}).get("loss"), (int, float))
            verdict = {
                "valid": valid,
                "reason_code": "OK" if valid else "MISSING_LOSS",
            }
            if not valid:
                verdict["category"] = "INSUFFICIENT_EVIDENCE"
            respond(request, payload=verdict)
"""
        new = """        elif operation == "verify":
            respond(
                request,
                payload={
                    "valid": False,
                    "category": "INSUFFICIENT_EVIDENCE",
                    "reason_code": "OUT_OF_SAMPLE_REPORT_MISSING",
                },
            )
"""
        self.assertIn(old, source)
        adapter.write_text(source.replace(old, new), encoding="utf-8")

        outcome = ResearchService(project).run_once(
            project / "candidates" / "improve.json"
        )

        self.assertEqual(outcome["status"], TerminalStatus.INSUFFICIENT_EVIDENCE.value)
        self.assertEqual(outcome["reason_code"], "OUT_OF_SAMPLE_REPORT_MISSING")
        self.assertFalse(outcome["verified"])
        self.assertNotIn("decision", outcome)


if __name__ == "__main__":
    unittest.main()
