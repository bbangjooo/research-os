from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any, cast

from research_os.contracts.common import (
    CANONICAL_JSON_VERSION,
    MAX_SAFE_JSON_INTEGER,
    canonical_json,
    canonical_json_bytes,
    decode_json_object,
    normalize_json_value,
)
from research_os.contracts.protocol import (
    FailureCategory,
    Operation,
    ProtocolError,
    ProtocolRequest,
    ProtocolResponse,
)
from research_os.contracts.results import ResultEnvelope

ROOT = Path(__file__).resolve().parents[1]


class RecursiveContractIsolationTests(unittest.TestCase):
    def test_protocol_request_detaches_freezes_and_deep_copies_payload(self):
        source = {"nested": {"items": [{"value": 1}]}}
        request = ProtocolRequest.create(
            request_id="req_isolated",
            operation=Operation.RUN,
            project_root=ROOT,
            workspace=ROOT,
            experiment_id="exp_isolated",
            payload=source,
        )

        source["nested"]["items"][0]["value"] = 2
        request_payload = cast(Any, request.payload)
        self.assertEqual(request_payload["nested"]["items"][0]["value"], 1)
        with self.assertRaises(TypeError):
            request_payload["nested"]["items"][0]["value"] = 3

        exported = cast(Any, request.to_dict())
        exported["payload"]["nested"]["items"][0]["value"] = 4
        self.assertEqual(request_payload["nested"]["items"][0]["value"], 1)

    def test_protocol_response_and_error_are_recursively_isolated(self):
        details = {"context": {"codes": ["original"]}}
        error = ProtocolError(
            code="PROJECT_ERROR",
            message="failed",
            category=FailureCategory.INFRASTRUCTURE,
            details=details,
        )
        details["context"]["codes"].append("mutated")
        error_details = cast(Any, error.details)
        self.assertEqual(error_details["context"]["codes"], ("original",))
        with self.assertRaises(TypeError):
            error_details["context"]["new"] = True
        error_export = cast(Any, error.to_dict())
        error_export["details"]["context"]["codes"].append("export")
        self.assertEqual(error_details["context"]["codes"], ("original",))

        payload = {"nested": {"values": [1, 2]}}
        diagnostics = [{"context": {"ids": ["d1"]}}]
        response = ProtocolResponse.success(
            request_id="req_response",
            payload=payload,
            diagnostics=diagnostics,
        )
        payload["nested"]["values"].append(3)
        diagnostics[0]["context"]["ids"].append("d2")
        response_payload = cast(Any, response.payload)
        response_diagnostics = cast(Any, response.diagnostics)
        self.assertEqual(response_payload["nested"]["values"], (1, 2))
        self.assertEqual(response_diagnostics[0]["context"]["ids"], ("d1",))
        with self.assertRaises(TypeError):
            response_payload["nested"]["values"][0] = 9

        exported = cast(Any, response.to_dict())
        exported["payload"]["nested"]["values"].append(4)
        exported["diagnostics"][0]["context"]["ids"].append("d3")
        self.assertEqual(response_payload["nested"]["values"], (1, 2))
        self.assertEqual(response_diagnostics[0]["context"]["ids"], ("d1",))

    def test_result_envelope_cannot_change_after_validation_or_export(self):
        constraints = ({"passed": False, "evidence": {"ids": ["e1"]}},)
        resource_usage = {"worker": {"cpu": [1, 2]}}
        provenance = {"inputs": {"digests": ["abc"]}}
        diagnostics = ({"context": {"notes": ["original"]}},)
        result = ResultEnvelope(
            metrics={"score": 0.5},
            constraints=constraints,
            resource_usage=resource_usage,
            provenance=provenance,
            diagnostics=diagnostics,
        )

        constraints[0]["passed"] = True
        resource_usage["worker"]["cpu"].append(3)
        provenance["inputs"]["digests"].append("changed")
        diagnostics[0]["context"]["notes"].append("changed")
        frozen_constraints = cast(Any, result.constraints)
        frozen_resources = cast(Any, result.resource_usage)
        frozen_provenance = cast(Any, result.provenance)
        frozen_diagnostics = cast(Any, result.diagnostics)
        self.assertIs(frozen_constraints[0]["passed"], False)
        self.assertEqual(frozen_resources["worker"]["cpu"], (1, 2))
        self.assertEqual(frozen_provenance["inputs"]["digests"], ("abc",))
        self.assertEqual(frozen_diagnostics[0]["context"]["notes"], ("original",))
        with self.assertRaises(TypeError):
            frozen_constraints[0]["passed"] = True

        exported = cast(Any, result.to_dict())
        exported["constraints"][0]["passed"] = True
        exported["resource_usage"]["worker"]["cpu"].append(4)
        exported["provenance"]["inputs"]["digests"].append("export")
        exported["diagnostics"][0]["context"]["notes"].append("export")
        self.assertIs(frozen_constraints[0]["passed"], False)
        self.assertEqual(frozen_resources["worker"]["cpu"], (1, 2))
        self.assertEqual(frozen_provenance["inputs"]["digests"], ("abc",))
        self.assertEqual(frozen_diagnostics[0]["context"]["notes"], ("original",))


class CanonicalJsonPolicyTests(unittest.TestCase):
    def test_policy_version_one_normalizes_portable_numbers(self):
        self.assertEqual(CANONICAL_JSON_VERSION, 1)
        value = {
            "safe": MAX_SAFE_JSON_INTEGER,
            "fraction": 0.3333333333333333,
            "integral": 1.0,
            "negative_zero": -0.0,
            "minimum_decimal": 0.0001,
        }
        self.assertEqual(
            canonical_json(value),
            '{"fraction":0.3333333333333333,"integral":1,'
            '"minimum_decimal":0.0001,"negative_zero":0,'
            '"safe":9007199254740991}',
        )

    def test_ecmascript_float_format_and_unsafe_python_integers(self):
        self.assertEqual(
            canonical_json(
                {"tiny": 1e-7, "small": 1e-5, "huge": 1e20, "exponent": 1e21}
            ),
            '{"exponent":1e+21,"huge":100000000000000000000,'
            '"small":0.00001,"tiny":1e-7}',
        )
        self.assertEqual(
            canonical_json(decode_json_object('{"value":100000000000000000000}')),
            '{"value":100000000000000000000}',
        )
        self.assertEqual(ResultEnvelope(metrics={"tiny": 1e-7}).metrics["tiny"], 1e-7)

        for value in (MAX_SAFE_JSON_INTEGER + 1, -(MAX_SAFE_JSON_INTEGER + 1)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_json({"value": value})

        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_json({"value": value})

    def test_unpaired_surrogates_are_rejected_before_utf8_encoding(self):
        for value in ("\ud800", "\udfff"):
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                normalize_json_value(value)
            with self.assertRaises(ValueError):
                canonical_json_bytes({"value": value})

        with self.assertRaises(ValueError):
            decode_json_object('{"value":"\\ud800"}')
        with self.assertRaises(ValueError):
            canonical_json({"\ud800": "bad key"})

        self.assertEqual(
            decode_json_object('{"value":"\\ud83d\\ude00"}'),
            {"value": "😀"},
        )

    def test_object_keys_use_ecmascript_utf16_order(self):
        self.assertEqual(
            canonical_json({"\ue000": 2, "\U00010000": 1, "a": 0}),
            '{"a":0,"𐀀":1,"":2}',
        )

    @unittest.skipUnless(shutil.which("node"), "Node is required for parity vectors")
    def test_supported_vectors_match_javascript_byte_for_byte(self):
        vectors = [
            {
                "safe": MAX_SAFE_JSON_INTEGER,
                "fraction": 0.3333333333333333,
                "integral": 1.0,
                "negative_zero": -0.0,
                "minimum_decimal": 0.0001,
            },
            {"\ue000": 2, "\U00010000": 1, "a": "😀"},
            {"10": "ten", "2": "two", "nested": [{"z": 1, "a": 2}]},
            {"corpus": [index / 37 for index in range(-100, 101)]},
            {
                "small": 1e-5,
                "tiny": 1e-7,
                "fixed_large": 1e20,
                "exponent_large": 1e21,
                "minimum": 5e-324,
                "maximum": 1.7976931348623157e308,
            },
        ]
        javascript = r"""
const fs = require("fs");
const values = JSON.parse(fs.readFileSync(0, "utf8"));
function canonical(value) {
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
  return "{" + Object.keys(value).sort().map(
    key => JSON.stringify(key) + ":" + canonical(value[key])
  ).join(",") + "}";
}
process.stdout.write(values.map(canonical).join("\n"));
"""
        node = shutil.which("node")
        assert node is not None
        completed = subprocess.run(
            [node, "-e", javascript],
            input=json.dumps(vectors, ensure_ascii=False),
            text=True,
            capture_output=True,
            check=True,
        )
        self.assertEqual(
            completed.stdout.splitlines(),
            [canonical_json(value) for value in vectors],
        )


if __name__ == "__main__":
    unittest.main()
