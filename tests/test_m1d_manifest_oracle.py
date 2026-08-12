from __future__ import annotations

import ast
import copy
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from research_os.contracts import sha256_json
from tests.m1d_support import (
    DuplicateKeyError,
    M1DOracle,
    OperationRegistry,
    canonical_event_digest,
    json_canonical_equal,
    recursive_key_values,
    sha256_bytes,
    sorted_compact_digest,
    strict_load_json,
)
from tests.m1d_support import oracle as oracle_module
from tests.m1d_support.oracle import DiagnosisNegativeMaterializer
from tests.m1d_support.transition_observer import execute_history_paths

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "scientific_state" / "v3"
SUPPORT_ROOT = ROOT / "tests" / "m1d_support"
MANIFEST_RAW_SHA256 = "10e037678f49397a14b9f75bc0d8913da7a8f8ed8af8607b2c6f4751892e1718"
MANIFEST_PUBLIC_SHA256 = "c34efc9aeb5af9d83bd7325bc95cd948b4ba04de4ca7b773404a15100d28af78"
SUPPORTING_RAW_SHA256 = {
    "m1d-contract.json": "58d3c416c9ce98c336fe888bccf19859a6e5c789d85306b93492a7cabd0a30f3",
    "m1d-terminal-corpus.json": "e3623748815bdba58feb399a1dab55399917e80e11894eb981572af9a08cc20f",
    "m1d-diagnosis-valid.json": "3c9394d0ee2ccc06b6e21dbca403dfc6b4e0e3264ffc43e13cc39c5673462336",
    "m1d-diagnosis-negative-matrix.json": "112a77493182354637ece0dd405dcca8a4093aee876f75af58f1bde437ae4fb4",
    "m1d-transition-matrix.json": "92551a101bfbdbf96c92673750335a70ccd5d1bf422dc7fd80df4feeae9e3c54",
    "m1d-frontier-oracle.json": "66c34953a9f2e0259e4be3c00fe24c92e8213685fff3f00f02ba93e97fa75cc5",
    "m1d-compat-oracle.json": "680f475d7d13dfc663f4d84e1931f1a10888cf660312a6d0575d3d4a216a70fc",
}


def _object(path: Path) -> dict[str, object]:
    value = strict_load_json(path)
    if not isinstance(value, dict):
        raise TypeError(f"{path.name} must contain an object")
    return value


@dataclass(frozen=True, slots=True)
class ManifestBinding:
    display_id: str
    operation: str
    inputs: Mapping[str, object]
    comparison: Mapping[str, object]


def _binding(value: object) -> ManifestBinding:
    if not isinstance(value, Mapping):
        raise TypeError("manifest binding must be an object")
    display_id = value.get("id")
    operation = value.get("operation")
    inputs = value.get("input")
    comparison = value.get("expected")
    if not isinstance(display_id, str) or not display_id:
        raise TypeError("manifest display identity must be text")
    if not isinstance(operation, str) or not operation:
        raise TypeError("manifest operation must be text")
    if not isinstance(inputs, Mapping) or not isinstance(comparison, Mapping):
        raise TypeError("manifest input and comparison must be objects")
    return ManifestBinding(display_id, operation, inputs, comparison)


_MANIFEST = _object(FIXTURE_ROOT / "manifest.json")
_BINDINGS = tuple(_binding(value) for value in cast(list[object], _MANIFEST["cases"]))


@pytest.fixture(scope="module")
def transition_literal_observations() -> tuple[
    dict[str, object],
    dict[str, list[dict[str, object]]],
]:
    from tests.m1d_support.transition_observer import (
        observe_counting_taxonomy_rows,
        observe_full_state_rows,
        observe_literal_race_rows,
        observe_terminal_pending_rows,
        observe_transition_gate_rows,
    )

    matrix = _object(FIXTURE_ROOT / "m1d-transition-matrix.json")

    def fixture_source(name: str) -> Mapping[str, object]:
        if name != "m1d-transition-matrix.json":
            raise AssertionError(f"unexpected transition fixture: {name}")
        return matrix

    inputs = {"fixture": "m1d-transition-matrix.json"}
    return matrix, {
        "counting": observe_counting_taxonomy_rows(inputs, fixture_source),
        "terminal": observe_terminal_pending_rows(inputs, fixture_source),
        "full": observe_full_state_rows(inputs, fixture_source),
        "gate": observe_transition_gate_rows(inputs, fixture_source),
        "race": observe_literal_race_rows(inputs, fixture_source),
    }


def _row_mapping(value: object, name: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{name} must be an object")
    return value


def _row_list(value: object, name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{name} must be an array")
    return value


def _assert_expected_projection(
    observed: Mapping[str, object],
    expected: Mapping[str, object],
) -> None:
    assert set(observed) == set(expected)
    assert json_canonical_equal(dict(observed), dict(expected))


def _assert_exact_zero_deltas(
    observed: Mapping[str, object],
    expected: Mapping[str, object],
) -> None:
    assert set(observed) == set(expected)
    assert all(json_canonical_equal(value, 0) for value in expected.values())
    assert json_canonical_equal(dict(observed), dict(expected))


def _assert_counting_rows(
    matrix: Mapping[str, object], observations: list[dict[str, object]]
) -> None:
    rows = _row_list(matrix.get("counting_taxonomy"), "counting rows")
    assert len(observations) == len(rows) == 26
    for ordinal, (raw_row, observed) in enumerate(zip(rows, observations, strict=True)):
        row = _row_mapping(raw_row, "counting row")
        row_input = _row_mapping(row.get("input"), "counting input")
        assert set(observed) == {"ordinal", "input_sha256", "observation"}
        assert observed["ordinal"] == ordinal
        assert observed["input_sha256"] == sorted_compact_digest(row_input)
        _assert_expected_projection(
            _row_mapping(observed.get("observation"), "counting observation"),
            _row_mapping(row.get("expected"), "counting comparison"),
        )


def _assert_terminal_pending_rows(
    matrix: Mapping[str, object], observations: list[dict[str, object]]
) -> None:
    rows = _row_list(matrix.get("terminal_pending_cases"), "terminal-pending rows")
    assert len(observations) == len(rows) == 23
    for ordinal, (raw_row, observed) in enumerate(zip(rows, observations, strict=True)):
        row = _row_mapping(raw_row, "terminal-pending row")
        row_input = _row_mapping(row.get("input"), "terminal-pending input")
        comparison = _row_mapping(row.get("expected"), "terminal comparison")
        assert set(observed) == {"ordinal", "input_sha256", "observation"}
        assert observed["ordinal"] == ordinal
        assert observed["input_sha256"] == sorted_compact_digest(row_input)
        _assert_expected_projection(
            _row_mapping(observed.get("observation"), "terminal observation"),
            comparison,
        )


def _assert_full_state_rows(
    matrix: Mapping[str, object], observations: list[dict[str, object]]
) -> None:
    rows = _row_list(matrix.get("full_state_cases"), "full-state rows")
    assert len(observations) == len(rows) == 54
    for ordinal, (raw_row, observed) in enumerate(zip(rows, observations, strict=True)):
        row = _row_mapping(raw_row, "full-state row")
        row_input = _row_mapping(row.get("input"), "full-state input")
        assert observed["ordinal"] == ordinal
        assert observed["input_sha256"] == sorted_compact_digest(row_input)
        assert json_canonical_equal(observed["state"], row["expected_state"])
        comparison = _row_mapping(row.get("expected"), "full-state comparison")
        assert set(comparison) == {
            "history_event_count",
            "operation_deltas",
            "post_state_digest",
            "pre_state_digest",
        }
        assert set(observed) == {
            "ordinal",
            "input_sha256",
            "state",
            *comparison,
        }
        _assert_expected_projection(
            {key: observed[key] for key in comparison},
            comparison,
        )


def _assert_gate_rows(matrix: Mapping[str, object], observations: list[dict[str, object]]) -> None:
    rows = _row_list(matrix.get("gate_cases"), "gate rows")
    assert len(observations) == len(rows) == 37
    for ordinal, (raw_row, observed) in enumerate(zip(rows, observations, strict=True)):
        row = _row_mapping(raw_row, "gate row")
        row_input = _row_mapping(row.get("input"), "gate input")
        assert observed["ordinal"] == ordinal
        assert observed["input_sha256"] == sorted_compact_digest(row_input)
        public_observation = {
            key: value for key, value in observed.items() if key not in {"ordinal", "input_sha256"}
        }
        assert json_canonical_equal(public_observation, row["expected"])


def _assert_race_rows(matrix: Mapping[str, object], observations: list[dict[str, object]]) -> None:
    rows = _row_list(matrix.get("race_schedules"), "race rows")
    assert len(observations) == len(rows) == 7
    for ordinal, (raw_row, observed) in enumerate(zip(rows, observations, strict=True)):
        row = _row_mapping(raw_row, "race row")
        row_input = {
            "precondition": row.get("precondition"),
            "schedule": row.get("schedule"),
        }
        assert observed["ordinal"] == ordinal
        assert observed["input_sha256"] == sorted_compact_digest(row_input)
        public_observation = {
            key: value for key, value in observed.items() if key not in {"ordinal", "input_sha256"}
        }
        assert json_canonical_equal(public_observation, row["expected"])


@pytest.mark.parametrize(
    "binding",
    _BINDINGS,
    ids=[binding.display_id for binding in _BINDINGS],
)
def test_each_frozen_operation_has_an_executable_outer_comparison(
    binding: ManifestBinding,
    tmp_path: Path,
) -> None:
    oracle = M1DOracle(FIXTURE_ROOT, project_root=ROOT, work_root=tmp_path)
    observed = oracle.registry().observe(binding.operation, binding.inputs)
    assert json_canonical_equal(observed, binding.comparison)


def test_frozen_json_bytes_and_both_manifest_digest_domains_are_exact() -> None:
    manifest_path = FIXTURE_ROOT / "manifest.json"
    assert sha256_bytes(manifest_path.read_bytes()) == MANIFEST_RAW_SHA256
    assert sha256_json(_MANIFEST) == MANIFEST_PUBLIC_SHA256
    assert len(_BINDINGS) == 28
    assert len({binding.display_id for binding in _BINDINGS}) == 28
    assert len({binding.operation for binding in _BINDINGS}) == 28
    assert {path.name for path in FIXTURE_ROOT.glob("*.json")} == {
        "manifest.json",
        *SUPPORTING_RAW_SHA256,
    }
    for name, digest in SUPPORTING_RAW_SHA256.items():
        path = FIXTURE_ROOT / name
        strict_load_json(path)
        assert sha256_bytes(path.read_bytes()) == digest


def test_public_and_kernel_digest_encoders_are_observed_independently() -> None:
    ordering_probe = {"\U0001f600": 1, "\ue000": 2}
    assert sha256_json(ordering_probe) != sorted_compact_digest(ordering_probe)

    terminal_fixture = _object(FIXTURE_ROOT / "m1d-terminal-corpus.json")
    records = terminal_fixture["records"]
    assert isinstance(records, list) and records
    history = cast(Mapping[str, object], records[0])["canonical_history"]
    assert isinstance(history, list) and history
    envelope = dict(cast(Mapping[str, object], history[-1]))
    supplied = envelope.pop("hash")
    assert canonical_event_digest(envelope) == supplied


def test_manifest_outer_comparator_rejects_bool_number_confusion() -> None:
    expected = {"value": 1, "nested": [True, 0.0]}
    assert json_canonical_equal(copy.deepcopy(expected), expected)
    assert json_canonical_equal({"value": 1.0, "nested": [True, 0]}, expected)
    assert not json_canonical_equal({"value": True, "nested": [True, 0.0]}, expected)
    assert not json_canonical_equal({"value": 1, "nested": [1, 0.0]}, expected)


def test_expected_projection_requires_exact_keys_and_canonical_values() -> None:
    _assert_expected_projection({"count_delta": 1.0}, {"count_delta": 1})
    with pytest.raises(AssertionError):
        _assert_expected_projection(
            {"count_delta": 1, "unexpected": True},
            {"count_delta": 1},
        )
    with pytest.raises(AssertionError):
        _assert_expected_projection({"count_delta": True}, {"count_delta": 1})


def test_negative_deltas_require_exact_keys_and_canonical_numeric_zero() -> None:
    expected = {
        "events": 0,
        "budget": 0,
        "diagnoses": 0,
        "class_state": 0,
        "frontier": 0,
        "projection_cursor": 0,
    }
    _assert_exact_zero_deltas(
        {key: 0.0 for key in expected},
        expected,
    )
    with pytest.raises(AssertionError):
        _assert_exact_zero_deltas(
            {**expected, "unexpected": 0},
            expected,
        )
    with pytest.raises(AssertionError):
        _assert_exact_zero_deltas(
            {**expected, "events": False},
            expected,
        )


def test_operation_registry_receives_only_operation_and_input() -> None:
    received: list[Mapping[str, object]] = []
    registry = OperationRegistry()
    registry.register("probe", lambda inputs: received.append(inputs) or {"ok": True})

    assert registry.observe("probe", {"value": 1}) == {"ok": True}
    assert received == [{"value": 1}]
    assert M1DOracle(FIXTURE_ROOT, project_root=ROOT).registry().names == {
        binding.operation for binding in _BINDINGS
    }


def test_observer_contracts_contain_only_declarative_metadata() -> None:
    manifest_contract = _row_mapping(_MANIFEST.get("observer_contract"), "observer contract")
    assert set(manifest_contract) == {
        "dispatch_input",
        "expected_comparison",
        "forbidden_dispatch",
    }
    transition = _object(FIXTURE_ROOT / "m1d-transition-matrix.json")
    transition_contract = _row_mapping(
        transition.get("observer_contract"),
        "transition observer contract",
    )
    assert set(transition_contract) == {
        "counting_taxonomy_decision_exact_fields",
        "counting_taxonomy_derivation_sources",
        "counting_taxonomy_forbidden_input_fields",
        "counting_taxonomy_gate_evaluation_exact_fields",
        "counting_taxonomy_observation_exact_fields",
        "counting_taxonomy_observer_receives",
        "display_identity_fields_stripped_before_observer",
        "event_envelope_exact_fields",
        "event_hash_algorithm",
        "expected_state_kind",
        "forbidden_dispatch",
        "forbidden_input_expansion",
        "forbidden_observer_access",
        "full_state_observer_input_exact_fields",
        "gate_case_input_exact_fields",
        "gate_expected_state_kind",
        "gate_observer_receives",
        "input_kind",
        "production_observer",
        "race_observer_input_exact_fields",
        "race_observer_receives",
        "race_precondition_input_exact_fields",
        "race_schedule_operation_exact_fields",
        "race_setup_source",
        "strip_before_observer",
        "terminal_pending_case_input_exact_fields",
        "terminal_pending_observer_receives",
    }
    for contract in (manifest_contract, transition_contract):
        assert all(
            isinstance(value, str)
            or (isinstance(value, list) and all(isinstance(item, str) for item in value))
            for value in contract.values()
        )
    assert "expected" not in transition


def test_strict_loader_rejects_duplicate_members(tmp_path: Path) -> None:
    malformed = tmp_path / "duplicate.json"
    malformed.write_text('{"value":1,"value":2}\n', encoding="utf-8")
    with pytest.raises(DuplicateKeyError):
        strict_load_json(malformed)


def test_every_transition_literal_has_an_outer_exact_comparison(
    transition_literal_observations: tuple[
        dict[str, object],
        dict[str, list[dict[str, object]]],
    ],
) -> None:
    matrix, observations = transition_literal_observations
    _assert_counting_rows(matrix, observations["counting"])
    _assert_terminal_pending_rows(matrix, observations["terminal"])
    _assert_full_state_rows(matrix, observations["full"])
    _assert_gate_rows(matrix, observations["gate"])
    _assert_race_rows(matrix, observations["race"])


def test_transition_outer_comparators_reject_corrupted_inner_values(
    transition_literal_observations: tuple[
        dict[str, object],
        dict[str, list[dict[str, object]]],
    ],
) -> None:
    matrix, observations = transition_literal_observations

    counting = copy.deepcopy(matrix)
    counting_rows = cast(list[dict[str, object]], counting["counting_taxonomy"])
    counting_comparison = cast(dict[str, object], counting_rows[0]["expected"])
    counting_comparison["count_delta"] = 0
    with pytest.raises(AssertionError):
        _assert_counting_rows(counting, observations["counting"])

    terminal = copy.deepcopy(matrix)
    terminal_rows = cast(list[dict[str, object]], terminal["terminal_pending_cases"])
    terminal_comparison = cast(dict[str, object], terminal_rows[0]["expected"])
    terminal_comparison["pending_count"] = 2
    with pytest.raises(AssertionError):
        _assert_terminal_pending_rows(terminal, observations["terminal"])

    full = copy.deepcopy(matrix)
    full_rows = cast(list[dict[str, object]], full["full_state_cases"])
    full_state = cast(dict[str, object], full_rows[0]["expected_state"])
    full_state["diagnosis_count"] = 999
    with pytest.raises(AssertionError):
        _assert_full_state_rows(full, observations["full"])

    gates = copy.deepcopy(matrix)
    gate_rows = cast(list[dict[str, object]], gates["gate_cases"])
    gate_comparison = cast(dict[str, object], gate_rows[0]["expected"])
    gate_comparison["accepted"] = not cast(bool, gate_comparison["accepted"])
    with pytest.raises(AssertionError):
        _assert_gate_rows(gates, observations["gate"])

    races = copy.deepcopy(matrix)
    race_rows = cast(list[dict[str, object]], races["race_schedules"])
    race_comparison = cast(dict[str, object], race_rows[0]["expected"])
    race_counts = cast(dict[str, object], race_comparison["outcome_counts"])
    race_counts["successes"] = 999
    with pytest.raises(AssertionError):
        _assert_race_rows(races, observations["race"])


def test_transition_outer_comparators_reject_bool_number_confusion(
    transition_literal_observations: tuple[
        dict[str, object],
        dict[str, list[dict[str, object]]],
    ],
) -> None:
    matrix, observations = transition_literal_observations

    counting = copy.deepcopy(matrix)
    counting_rows = cast(list[dict[str, object]], counting["counting_taxonomy"])
    counting_expected = cast(dict[str, object], counting_rows[0]["expected"])
    assert type(counting_expected["count_delta"]) is int
    counting_expected["count_delta"] = bool(counting_expected["count_delta"])
    with pytest.raises(AssertionError):
        _assert_counting_rows(counting, observations["counting"])

    terminal = copy.deepcopy(matrix)
    terminal_rows = cast(list[dict[str, object]], terminal["terminal_pending_cases"])
    terminal_expected = cast(dict[str, object], terminal_rows[0]["expected"])
    assert type(terminal_expected["pending_count"]) is int
    terminal_expected["pending_count"] = bool(terminal_expected["pending_count"])
    with pytest.raises(AssertionError):
        _assert_terminal_pending_rows(terminal, observations["terminal"])

    full = copy.deepcopy(matrix)
    full_rows = cast(list[dict[str, object]], full["full_state_cases"])
    full_state = cast(dict[str, object], full_rows[0]["expected_state"])
    assert type(full_state["diagnosis_count"]) is int
    full_state["diagnosis_count"] = bool(full_state["diagnosis_count"])
    with pytest.raises(AssertionError):
        _assert_full_state_rows(full, observations["full"])

    gates = copy.deepcopy(matrix)
    gate_rows = cast(list[dict[str, object]], gates["gate_cases"])
    gate_expected = cast(dict[str, object], gate_rows[0]["expected"])
    gate_deltas = cast(dict[str, object], gate_expected["deltas"])
    assert type(gate_deltas["canonical_events"]) is int
    gate_deltas["canonical_events"] = bool(gate_deltas["canonical_events"])
    with pytest.raises(AssertionError):
        _assert_gate_rows(gates, observations["gate"])

    races = copy.deepcopy(matrix)
    race_rows = cast(list[dict[str, object]], races["race_schedules"])
    race_expected = cast(dict[str, object], race_rows[0]["expected"])
    assert type(race_expected["count_delta"]) is int
    race_expected["count_delta"] = bool(race_expected["count_delta"])
    with pytest.raises(AssertionError):
        _assert_race_rows(races, observations["race"])


def _input_keys(value: object) -> set[str]:
    if isinstance(value, Mapping):
        return {
            *(str(key) for key in value),
            *(key for item in value.values() for key in _input_keys(item)),
        }
    if isinstance(value, list):
        return {key for item in value for key in _input_keys(item)}
    return set()


def test_manifest_dispatch_inputs_contain_no_semantic_selectors() -> None:
    forbidden = {
        "$ref",
        "case_id",
        "display_id",
        "extends",
        "gate_ids",
        "id",
        "label",
        "race_ids",
        "required_operations",
        "scenario",
        "template",
    }
    for binding in _BINDINGS:
        assert not forbidden.intersection(_input_keys(binding.inputs))


def _comparison_accesses(tree: ast.AST) -> list[ast.AST]:
    accesses: list[ast.AST] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Subscript):
            if isinstance(node.slice, ast.Constant) and node.slice.value == "expected":
                accesses.append(node)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if (
                node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "expected"
            ):
                accesses.append(node)
        elif isinstance(node, ast.Attribute) and node.attr == "expected":
            accesses.append(node)
    return accesses


def test_support_observers_have_no_comparison_or_display_identity_dispatch() -> None:
    display_ids = {binding.display_id for binding in _BINDINGS}
    for path in SUPPORT_ROOT.glob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        assert _comparison_accesses(tree) == []
        assert all(display_id not in source for display_id in display_ids)


def test_all_frozen_authority_values_are_null() -> None:
    authority_values = [
        value
        for path in FIXTURE_ROOT.glob("*.json")
        for value in recursive_key_values(strict_load_json(path), "authorized_action")
    ]
    assert len(authority_values) == 3129
    assert sum(value is not None for value in authority_values) == 0


def test_ten_live_public_surfaces_keep_authority_present_and_null(
    tmp_path: Path,
) -> None:
    oracle = M1DOracle(FIXTURE_ROOT, project_root=ROOT, work_root=tmp_path)
    compatibility = _object(FIXTURE_ROOT / "m1d-compat-oracle.json")
    surfaces = oracle._authority_surfaces(compatibility)
    recursive_values = [
        value
        for surface in surfaces.values()
        for value in recursive_key_values(surface, "authorized_action")
    ]
    assert len(surfaces) == 10
    assert sum("authorized_action" in surface for surface in surfaces.values()) == 10
    assert sum(value is not None for value in recursive_values) == 0


def test_frontier_exclusion_count_is_driven_by_derived_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.m1d_support import frontier_observer

    fixture = _object(FIXTURE_ROOT / "m1d-frontier-oracle.json")
    derive = frontier_observer._derive_frontiers
    calls = 0

    def corrupt_first_exclusion(value: Mapping[str, object]) -> dict[str, object]:
        nonlocal calls
        calls += 1
        result = derive(value)
        if calls == 2:
            target = next(
                node
                for node in cast(list[Mapping[str, object]], result["nodes"])
                if node.get("experiment_id") == "exp_a1"
            )
            result["leaves"] = [
                *cast(list[Mapping[str, object]], result["leaves"]),
                target,
            ]
        return result

    monkeypatch.setattr(frontier_observer, "_derive_frontiers", corrupt_first_exclusion)
    observed = frontier_observer.execute_frontier_exclusions(
        {"fixture": "m1d-frontier-oracle.json"},
        lambda _: fixture,
    )
    assert observed["excluded"] == 20
    assert observed["unexpectedly_eligible"] == 1


def test_frontier_selector_free_count_detects_a_display_selector() -> None:
    from tests.m1d_support import frontier_observer

    fixture = copy.deepcopy(_object(FIXTURE_ROOT / "m1d-frontier-oracle.json"))
    exclusions = cast(list[dict[str, object]], fixture["exclusions"])
    first_input = cast(dict[str, object], exclusions[0]["input"])
    first_input["display_id"] = "forbidden-observer-selector"
    observed = frontier_observer.derive_semantic_frontier(
        {"fixture": "m1d-frontier-oracle.json"},
        lambda _: fixture,
    )
    assert observed["selector_free_observer_rows"] == 45


def test_counting_binding_rejects_bool_number_confusion_in_literal_input() -> None:
    from tests.m1d_support import transition_observer

    def observe(value: object) -> tuple[Mapping[str, object], Mapping[str, object]]:
        fixture = copy.deepcopy(_object(FIXTURE_ROOT / "m1d-transition-matrix.json"))
        rows = cast(list[dict[str, object]], fixture["counting_taxonomy"])
        row_input = cast(dict[str, object], rows[12]["input"])
        diagnosis = cast(dict[str, object], row_input["diagnosis"])
        observation = cast(dict[str, object], diagnosis["observation"])
        observation["improvement"] = value
        inputs = {"fixture": "m1d-transition-matrix.json"}
        row_observations = transition_observer.observe_counting_taxonomy_rows(
            inputs,
            lambda _: fixture,
        )
        aggregate = transition_observer.execute_counting_taxonomy(
            inputs,
            lambda _: fixture,
        )
        return cast(Mapping[str, object], row_observations[12]["observation"]), aggregate

    canonical_row, canonical_aggregate = observe(1.0)
    assert canonical_row["count_delta"] == 1
    assert canonical_aggregate["positive_rows"] == 7
    assert canonical_aggregate["zero_rows"] == 19

    confused_row, confused_aggregate = observe(True)
    assert confused_row["count_delta"] == 0
    assert confused_aggregate["positive_rows"] == 6
    assert confused_aggregate["zero_rows"] == 20


def test_frontier_binding_rejects_bool_number_confusion_in_literal_input() -> None:
    from tests.m1d_support import frontier_observer

    def observe(value: object) -> Mapping[str, object]:
        fixture = copy.deepcopy(_object(FIXTURE_ROOT / "m1d-frontier-oracle.json"))
        frontier_input = cast(dict[str, object], fixture["input"])
        raw_nodes = cast(list[dict[str, object]], frontier_input["raw_nodes"])
        diagnosis_fact = cast(dict[str, object], raw_nodes[2]["diagnosis_fact"])
        diagnosis = cast(dict[str, object], diagnosis_fact["diagnosis"])
        observation = cast(dict[str, object], diagnosis["observation"])
        observation["promotion_margin"] = value
        return frontier_observer.derive_semantic_frontier(
            {"fixture": "m1d-frontier-oracle.json"},
            lambda _: fixture,
        )

    assert observe(1.0)["derived_supported_nodes"] == 7
    assert observe(True)["derived_supported_nodes"] == 6


def test_race_rename_binding_uses_canonical_json_equality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.m1d_support import transition_observer

    def run(replacement: object) -> Mapping[str, object]:
        calls = 0

        def fake_rows(_: Mapping[str, object]) -> list[tuple[object, ...]]:
            nonlocal calls
            calls += 1
            rows: list[tuple[object, ...]] = []
            for ordinal in range(7):
                value = replacement if calls == 4 and ordinal == 0 else 1
                rows.append(
                    (
                        {"schedule": []},
                        [{"deltas": {"canonical_events": value}}],
                        [{"sequence": value}],
                        {
                            "precondition": {"event_history": [{"sequence": value}]},
                            "schedule": [],
                        },
                    )
                )
            return rows

        monkeypatch.setattr(transition_observer, "_race_rows", fake_rows)
        return transition_observer.verify_race_label_invariance(
            {"fixture": "probe.json"},
            lambda _: {"race_schedules": []},
        )

    assert run(1.0)["display_id_label_rename_invariance_assertions"] == 7
    assert run(True)["display_id_label_rename_invariance_assertions"] == 6


def test_closure_origin_binding_uses_canonical_json_equality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.m1d_support import transition_observer

    original_state_rows = transition_observer._state_rows
    original_first_closure = transition_observer._first_closure

    def run(replacement: object) -> Mapping[str, object]:
        def probed_state_rows(
            matrix: Mapping[str, object],
        ) -> list[tuple[list[Mapping[str, object]], dict[str, object]]]:
            rows = original_state_rows(matrix)
            for _, state in rows:
                for body in transition_observer._class_bodies(state):
                    if body.get("lifecycle") != "closed":
                        continue
                    evidence = body.get("closure_evidence")
                    if isinstance(evidence, dict):
                        evidence["canonical_equality_probe"] = replacement
            return rows

        def probed_first_closure(
            history: list[Mapping[str, object]],
            project_id: str,
        ) -> tuple[int, dict[object, Mapping[str, object]]]:
            sequence, evidence = original_first_closure(history, project_id)
            return sequence, {
                class_id: {**dict(value), "canonical_equality_probe": 1}
                for class_id, value in evidence.items()
            }

        monkeypatch.setattr(transition_observer, "_state_rows", probed_state_rows)
        monkeypatch.setattr(transition_observer, "_first_closure", probed_first_closure)
        return transition_observer.verify_class_closure_origin(
            {"fixture": "m1d-transition-matrix.json"},
            lambda _: _object(FIXTURE_ROOT / "m1d-transition-matrix.json"),
        )

    assert run(1.0)["closure_origin_changes_after_followup"] == 0
    assert run(True)["closure_origin_changes_after_followup"] == 11


def test_m1c_exact_count_rejects_a_partial_outer_run_even_in_regression_child_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def partial_run(*_: object, **__: object) -> object:
        return type(
            "Completed",
            (),
            {"returncode": 0, "stdout": "19 passed in 1.00s\n", "stderr": ""},
        )()

    monkeypatch.setenv("RESEARCH_OS_M1D_REGRESSION_CHILD", "1")
    monkeypatch.setattr(oracle_module, "_completed", partial_run)
    with pytest.raises(AssertionError, match="19/20"):
        oracle_module._m1c_exact_case_count(20)


def test_regression_floor_does_not_fail_open_in_regression_child_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_run(*_: object, **__: object) -> object:
        return type(
            "Completed",
            (),
            {"returncode": 1, "stdout": "forced nested failure\n", "stderr": ""},
        )()

    monkeypatch.setenv("RESEARCH_OS_M1D_REGRESSION_CHILD", "1")
    monkeypatch.setattr(oracle_module, "_REGRESSION_OBSERVATION", None)
    monkeypatch.setattr(oracle_module, "_completed", failed_run)
    oracle = M1DOracle(FIXTURE_ROOT, project_root=ROOT, work_root=tmp_path)
    with pytest.raises(AssertionError, match="forced nested failure"):
        oracle.verify_regression_floor(
            {
                "python": f"{oracle_module.sys.version_info.major}.{oracle_module.sys.version_info.minor}"
            }
        )


def test_regression_floor_excludes_both_meta_oracles_from_nested_pytest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[list[str], Mapping[str, str] | None]] = []

    def successful_run(
        command: list[str],
        *,
        environment: Mapping[str, str] | None = None,
    ) -> object:
        calls.append((command, environment))
        return type(
            "Completed",
            (),
            {
                "returncode": 0,
                "stdout": "9999 passed, 9999 subtests passed\n",
                "stderr": "",
            },
        )()

    monkeypatch.setenv(
        "PYTEST_ADDOPTS",
        "-k recursion_guard_probe --ignore=tests/test_m1d_manifest_oracle.py",
    )
    monkeypatch.setattr(oracle_module, "_REGRESSION_OBSERVATION", None)
    monkeypatch.setattr(oracle_module, "_completed", successful_run)
    oracle = M1DOracle(FIXTURE_ROOT, project_root=ROOT, work_root=tmp_path)
    observed = oracle.verify_regression_floor(
        {"python": f"{oracle_module.sys.version_info.major}.{oracle_module.sys.version_info.minor}"}
    )

    assert observed["ruff"] == "PASS"
    pytest_command, pytest_environment = calls[0]
    assert pytest_command[-1] == "tests"
    assert pytest_environment is not None
    nested_options = oracle_module.shlex.split(pytest_environment["PYTEST_ADDOPTS"])
    assert nested_options[:2] == ["-k", "recursion_guard_probe"]
    assert all(
        nested_options.count(option) == 1 for option in oracle_module._META_ORACLE_IGNORES
    )
    assert all(environment is None for _, environment in calls[1:])


def test_terminal_pending_row_match_count_detects_reducer_corruption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from research_os import science

    original = science.reduce_scientific_state
    calls = 0

    def corrupt_first_row(*args: object, **kwargs: object) -> object:
        nonlocal calls
        calls += 1
        state = original(*args, **kwargs)
        if calls == 1:
            return oracle_module.SimpleNamespace(
                pending_diagnosis_experiment_ids=(),
            )
        return state

    monkeypatch.setattr(science, "reduce_scientific_state", corrupt_first_row)
    oracle = M1DOracle(FIXTURE_ROOT, project_root=ROOT, work_root=tmp_path)
    observed = oracle.verify_terminal_corpus({"fixture": "m1d-terminal-corpus.json"})
    assert observed["pending_diagnosis_row_matches"] == 22


def test_compatibility_delta_counters_detect_injected_m1d_fields() -> None:
    assert (
        oracle_module._recursive_key_occurrences(
            {"state": {"diagnoses": []}},
            oracle_module._M1D_ADDITIVE_PUBLIC_KEYS,
        )
        == 1
    )
    assert (
        oracle_module._mapping_difference_count(
            {"generation_id": "generation-old"},
            {
                "generation_id": "generation-new",
                "diagnosis_id": "diagnosis-forbidden",
            },
        )
        == 2
    )
    assert oracle_module._mapping_difference_count({"limit": 1}, {"limit": 1.0}) == 0
    assert oracle_module._mapping_difference_count({"limit": 1}, {"limit": True}) == 1

    raw_budget = {
        "max_attempts": 1,
        "max_retries": 1,
        "max_elapsed_milliseconds": 1,
        "elapsed_reservation_per_attempt_milliseconds": 1,
        "cost_unit": "microunit",
        "max_cost_microunits": 1,
        "cost_reservation_per_attempt_microunits": 1,
    }
    observed_budget = {
        "attempts": {"limit": 1},
        "retries": {"limit": 1},
        "elapsed_milliseconds": {"limit": 1, "reserved": 1},
        "cost_microunits": {"unit": "microunit", "limit": 1, "reserved": 1},
    }
    assert oracle_module._v2_budget_difference_count(raw_budget, observed_budget) == 0
    canonical_float_budget = copy.deepcopy(observed_budget)
    cast(dict[str, object], canonical_float_budget["attempts"])["limit"] = 1.0
    assert oracle_module._v2_budget_difference_count(raw_budget, canonical_float_budget) == 0
    confused_budget = copy.deepcopy(observed_budget)
    cast(dict[str, object], confused_budget["attempts"])["limit"] = True
    assert oracle_module._v2_budget_difference_count(raw_budget, confused_budget) == 1


def test_diagnosis_decision_binding_rejects_bool_number_confusion() -> None:
    decision = {
        "status": "REJECTED",
        "reason_code": "NO_MEANINGFUL_IMPROVEMENT",
        "primary_metric": "score",
        "candidate_value": 1,
        "baseline_value": 0,
        "improvement": 1,
        "promotion_margin": 0,
        "gate_evaluations": [],
    }
    observation = {
        "terminal_status": "REJECTED",
        "reason_code": "NO_MEANINGFUL_IMPROVEMENT",
        "verified": True,
        "retryable": False,
        "primary_metric": "score",
        "candidate_value": 1.0,
        "baseline_value": 0.0,
        "improvement": 1.0,
        "promotion_margin": 0.0,
        "gate_evaluations": [],
    }
    assert M1DOracle._decision_matches_observation({"decision": decision}, observation)
    observation["improvement"] = True
    assert not M1DOracle._decision_matches_observation({"decision": decision}, observation)
    observation["improvement"] = 1.0
    observation["unexpected"] = "undeclared"
    assert not M1DOracle._decision_matches_observation({"decision": decision}, observation)


def test_compatibility_transition_rejections_are_not_labeled_exact_matches() -> None:
    binding = next(
        item for item in _BINDINGS if item.operation == "verify_m1d_compatibility_authority"
    )
    assert binding.comparison["m1c_transition_case_rejections"] == 53
    assert "m1c_transition_exact_matches" not in binding.comparison


def test_legacy_context_observer_detects_an_injected_m1d_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from research_os.service import ResearchService
    from tests import test_m1c_manifest_oracle as legacy_oracle

    original = ResearchService.agent_context

    def injected_context(
        service: ResearchService,
        *,
        limit: int = 20,
        schema_version: int = 3,
    ) -> dict[str, object]:
        assert schema_version == 2
        observed = original(service, limit=limit, schema_version=schema_version)
        return {**observed, "diagnoses": []}

    monkeypatch.setattr(ResearchService, "agent_context", injected_context)
    manifest = _object(ROOT / "tests" / "fixtures" / "scientific_state" / "v2" / "manifest.json")
    legacy_binding = next(
        binding
        for binding in cast(list[Mapping[str, object]], manifest["cases"])
        if binding.get("operation") == "verify_legacy_parity"
    )
    legacy_input = legacy_binding["input"]
    assert isinstance(legacy_input, Mapping)
    oracle = M1DOracle(FIXTURE_ROOT, project_root=ROOT, work_root=tmp_path)
    observed = oracle._legacy_compatibility_key_counts(
        legacy_input,
        legacy_oracle,
    )
    assert observed["context_v2_new_keys"] == 1


def test_each_negative_row_matches_its_outer_declared_error_on_all_four_paths(
    tmp_path: Path,
) -> None:
    from research_os.errors import ScientificStateError
    from research_os.science import Diagnosis

    matrix = _object(FIXTURE_ROOT / "m1d-diagnosis-negative-matrix.json")
    terminal = _object(FIXTURE_ROOT / "m1d-terminal-corpus.json")
    valid = _object(FIXTURE_ROOT / "m1d-diagnosis-valid.json")
    materializer = DiagnosisNegativeMaterializer(matrix, terminal, valid)
    execution_paths = matrix["execution_paths"]
    rows = matrix["cases"]
    assert isinstance(execution_paths, list) and len(execution_paths) == 4
    assert isinstance(rows, list) and len(rows) == 115
    exact_matches = 0
    for ordinal, raw_row in enumerate(rows):
        assert isinstance(raw_row, Mapping)
        row_input = raw_row["input"]
        declaration = raw_row["expected"]
        assert isinstance(row_input, Mapping) and isinstance(declaration, Mapping)
        materialized = materializer.materialize(raw_row.get("operation"), row_input)
        if isinstance(materialized, list):
            outcomes = execute_history_paths(
                materialized,
                materializer.project_id,
                tmp_path / str(ordinal),
            ).values()
            for outcome in outcomes:
                assert outcome["accepted"] is False
                assert outcome["error_code"] == declaration["error_code"]
                assert outcome["error_path"] == declaration["path"]
                declared_deltas = declaration["deltas"]
                observed_deltas = outcome["deltas"]
                assert isinstance(declared_deltas, Mapping)
                assert isinstance(observed_deltas, Mapping)
                _assert_exact_zero_deltas(observed_deltas, declared_deltas)
                exact_matches += 1
        else:
            for _ in execution_paths:
                with pytest.raises(ScientificStateError) as caught:
                    Diagnosis.from_mapping(materialized)
                assert caught.value.code == declaration["error_code"]
                assert caught.value.details.get("path") == declaration["path"]
                exact_matches += 1
    assert exact_matches == 460
