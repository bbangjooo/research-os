from __future__ import annotations

import copy
import json
import math
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

from research_os.errors import ScientificStateError
from research_os.science import (
    EvaluationSeal,
    StudyContract,
    generation_id,
    new_generation_id,
)

FIXTURES = Path(__file__).parent / "fixtures" / "scientific_state" / "v1"


def _load(name: str) -> dict[str, Any]:
    value = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _tokens(pointer: str) -> list[str]:
    if not pointer.startswith("/"):
        raise AssertionError(pointer)
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _parent(document: Any, pointer: str) -> tuple[Any, str]:
    tokens = _tokens(pointer)
    parent = document
    for token in tokens[:-1]:
        parent = parent[int(token)] if isinstance(parent, list) else parent[token]
    return parent, tokens[-1]


def _replace(document: Any, pointer: str, value: Any) -> None:
    parent, token = _parent(document, pointer)
    if isinstance(parent, list):
        parent[int(token)] = value
    else:
        parent[token] = value


def _remove(document: Any, pointer: str) -> None:
    parent, token = _parent(document, pointer)
    if isinstance(parent, list):
        del parent[int(token)]
    else:
        del parent[token]


def _add(document: Any, pointer: str, value: Any) -> None:
    _replace(document, pointer, value)


def _negative_contract(base: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(base)
    for pointer in case.get("remove", []):
        _remove(value, pointer)
    for pointer, replacement in case.get("replace", {}).items():
        _replace(value, pointer, replacement)
    for pointer, addition in case.get("add", {}).items():
        _add(value, pointer, addition)
    transform = case.get("transform")
    if transform == "duplicate_first_hypothesis_id":
        value["hypothesis_classes"][1]["id"] = value["hypothesis_classes"][0]["id"]
    elif transform == "duplicate_first_scope_id":
        value["evaluation_scopes"][1]["id"] = value["evaluation_scopes"][0]["id"]
    elif transform == "duplicate_first_allowed_pointer":
        value["intervention_surface"]["allowed_json_pointers"][1] = value[
            "intervention_surface"
        ]["allowed_json_pointers"][0]
    elif transform == "replace_max_elapsed_with_nan":
        value["budget"]["max_elapsed_milliseconds"] = math.nan
    elif transform is not None:
        raise AssertionError(f"unknown fixture transform: {transform}")
    return value


class StudyContractV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = _load("manifest.json")
        self.raw_contract = _load("m1b-contract.json")

    def test_exact_round_trip_digest_and_recursive_immutability(self) -> None:
        contract = StudyContract.from_mapping(self.raw_contract)

        self.assertEqual(contract.to_dict(), self.raw_contract)
        self.assertEqual(contract.digest, self.manifest["fixtures"]["contract_digest"])
        with self.assertRaises(FrozenInstanceError):
            contract.study_id = "mutated"  # type: ignore[misc]
        exported = contract.to_dict()
        exported["budget"]["max_attempts"] = 999
        self.assertEqual(contract.budget.max_attempts, 4)

    def test_semantically_unordered_arrays_are_canonicalized(self) -> None:
        shuffled = copy.deepcopy(self.raw_contract)
        shuffled["hypothesis_classes"].reverse()
        shuffled["evaluation_scopes"].reverse()
        shuffled["intervention_surface"]["allowed_json_pointers"].reverse()

        contract = StudyContract.from_mapping(shuffled)

        self.assertEqual(contract.digest, self.manifest["fixtures"]["contract_digest"])
        self.assertEqual(contract.to_dict(), self.raw_contract)

    def test_null_cost_triple_remains_null(self) -> None:
        value = copy.deepcopy(self.raw_contract)
        value["budget"].update(
            {
                "cost_unit": None,
                "max_cost_microunits": None,
                "cost_reservation_per_attempt_microunits": None,
            }
        )

        budget = StudyContract.from_mapping(value).budget

        self.assertIsNone(budget.cost_unit)
        self.assertIsNone(budget.max_cost_microunits)
        self.assertIsNone(budget.cost_reservation_per_attempt_microunits)

    def test_all_24_versioned_negative_cases_have_one_stable_code(self) -> None:
        matrix = _load("m1b-contract-negative-matrix.json")
        cases = matrix["cases"]
        self.assertEqual(len(cases), 24)
        rejected: list[str] = []

        for case in cases:
            with self.subTest(case=case["id"]):
                with self.assertRaises(ScientificStateError) as caught:
                    StudyContract.from_mapping(_negative_contract(self.raw_contract, case))
                self.assertEqual(caught.exception.code, "STUDY_CONTRACT_INVALID")
                self.assertEqual(set(caught.exception.details), {"path", "reason"})
                rejected.append(caught.exception.code)

        self.assertEqual(rejected, ["STUDY_CONTRACT_INVALID"] * 24)

    def test_schema_version_must_be_integer_literal_and_keys_must_be_strings(self) -> None:
        float_version = copy.deepcopy(self.raw_contract)
        float_version["schema_version"] = 1.0
        with self.assertRaises(ScientificStateError) as version_error:
            StudyContract.from_mapping(float_version)
        self.assertEqual(version_error.exception.code, "STUDY_CONTRACT_INVALID")

        non_string_key = copy.deepcopy(self.raw_contract)
        non_string_key["budget"][1] = "invalid"
        with self.assertRaises(ScientificStateError) as key_error:
            StudyContract.from_mapping(non_string_key)
        self.assertEqual(key_error.exception.code, "STUDY_CONTRACT_INVALID")

    def test_rfc6901_escape_validation_and_safe_integer_types(self) -> None:
        for invalid_pointer in ("not/a/pointer", "/bad~", "/bad~2escape"):
            with self.subTest(pointer=invalid_pointer):
                value = copy.deepcopy(self.raw_contract)
                value["intervention_surface"]["allowed_json_pointers"][0] = invalid_pointer
                with self.assertRaises(ScientificStateError):
                    StudyContract.from_mapping(value)

        for invalid_number in (True, 1.0, math.inf, math.nan, 2**53):
            with self.subTest(number=invalid_number):
                value = copy.deepcopy(self.raw_contract)
                value["budget"]["max_attempts"] = invalid_number
                with self.assertRaises(ScientificStateError):
                    StudyContract.from_mapping(value)


class EvaluationSealAndGenerationIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = _load("manifest.json")
        self.fixtures = self.manifest["fixtures"]

    def test_evaluation_seal_is_exact_immutable_and_digest_stable(self) -> None:
        seal = EvaluationSeal.from_mapping(self.fixtures["evaluation_seal"])

        self.assertEqual(seal.to_dict(), self.fixtures["evaluation_seal"])
        self.assertEqual(seal.digest, self.fixtures["evaluation_seal_digest"])
        with self.assertRaises(FrozenInstanceError):
            seal.compatibility_digest = "0" * 64  # type: ignore[misc]

        for mutation in (
            {**self.fixtures["evaluation_seal"], "unknown": "0" * 64},
            {"compatibility_digest": "0" * 64},
            {**self.fixtures["evaluation_seal"], "compatibility_digest": "invalid"},
        ):
            with self.subTest(mutation=mutation):
                with self.assertRaises(ScientificStateError) as caught:
                    EvaluationSeal.from_mapping(mutation)
                self.assertEqual(caught.exception.code, "STUDY_EVALUATION_SEAL_INVALID")

    def test_generation_id_matches_first_and_successor_oracles(self) -> None:
        first = generation_id(
            self.fixtures["project_id"],
            None,
            self.fixtures["contract_digest"],
            self.fixtures["evaluation_seal_digest"],
        )
        successor = new_generation_id(
            self.fixtures["project_id"],
            self.fixtures["successor_contract_digest"],
            self.fixtures["evaluation_seal_digest"],
            predecessor_generation_id=first,
        )

        self.assertEqual(first, self.fixtures["first_generation_id"])
        self.assertEqual(successor, self.fixtures["successor_generation_id"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
