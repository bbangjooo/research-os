from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from research_os.errors import ScientificStateError
from research_os.kernel.ids import new_experiment_id
from research_os.science import (
    EvaluationSeal,
    Proposal,
    StudyContract,
    canonical_json_diff_pointers,
    generation_id,
    proposal_id,
)

FIXTURES = Path(__file__).parent / "fixtures" / "scientific_state" / "v2"
V1_FIXTURES = Path(__file__).parent / "fixtures" / "scientific_state" / "v1"


def _load(root: Path, name: str) -> dict[str, Any]:
    value = json.loads((root / name).read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _tokens(pointer: str) -> list[str]:
    assert pointer.startswith("/")
    return [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]


def _pointer_parent(document: Any, pointer: str) -> tuple[Any, str]:
    tokens = _tokens(pointer)
    parent = document
    for token in tokens[:-1]:
        parent = parent[int(token)] if isinstance(parent, list) else parent[token]
    return parent, tokens[-1]


def _replace(document: Any, pointer: str, value: Any) -> None:
    parent, token = _pointer_parent(document, pointer)
    if isinstance(parent, list):
        parent[int(token)] = value
    else:
        parent[token] = value


def _remove(document: Any, pointer: str) -> None:
    parent, token = _pointer_parent(document, pointer)
    if isinstance(parent, list):
        del parent[int(token)]
    else:
        del parent[token]


def _negative_proposal(
    base: dict[str, Any],
    matrix: dict[str, Any],
    case: dict[str, Any],
) -> Any:
    value: Any = copy.deepcopy(base)
    for pointer in case.get("remove", []):
        _remove(value, pointer)
    for pointer, replacement in case.get("replace", {}).items():
        _replace(value, pointer, replacement)
    for pointer, addition in case.get("add", {}).items():
        _replace(value, pointer, addition)
    transform_name = case.get("transform")
    if transform_name is None:
        return value
    transform = matrix["transforms"][transform_name]
    if transform["operation"] == "replace_root":
        return copy.deepcopy(transform["value"])
    generator = transform["generator"]
    if generator["kind"] == "repeat_text":
        generated = generator["text"] * generator["count"]
    elif generator["kind"] == "unicode_code_point":
        generated = chr(generator["value"])
    else:  # pragma: no cover - immutable fixture vocabulary
        raise AssertionError(generator)
    _replace(value, transform["pointer"], generated)
    return value


def test_v2_contract_round_trip_digest_generation_and_order() -> None:
    manifest = _load(FIXTURES, "manifest.json")
    fixtures = manifest["fixtures"]
    raw = _load(FIXTURES, "m1c-contract.json")
    contract = StudyContract.from_mapping(raw)

    assert contract.schema_version == 2
    assert contract.to_dict() == raw
    assert contract.digest == fixtures["contract_digest"]
    seal = EvaluationSeal.from_mapping(fixtures["evaluation_seal"])
    assert (
        generation_id(
            fixtures["project_id"],
            None,
            contract.digest,
            seal.digest,
        )
        == fixtures["generation_id"]
    )

    shuffled = copy.deepcopy(raw)
    shuffled["hypothesis_classes"].reverse()
    shuffled["evaluation_scopes"].reverse()
    shuffled["intervention_surface"]["allowed_json_pointers"].reverse()
    assert StudyContract.from_mapping(shuffled).to_dict() == raw


def test_scope_manifest_uniqueness_is_v2_only() -> None:
    raw = _load(FIXTURES, "m1c-contract.json")
    first_manifest = raw["evaluation_scopes"][0]["manifest_digest"]
    raw["evaluation_scopes"][1]["manifest_digest"] = first_manifest
    with pytest.raises(ScientificStateError) as caught:
        StudyContract.from_mapping(raw)
    assert caught.value.code == "STUDY_CONTRACT_INVALID"
    assert caught.value.details["path"] == "$.evaluation_scopes"

    raw["schema_version"] = 1
    assert StudyContract.from_mapping(raw).schema_version == 1


@pytest.mark.parametrize(
    ("fixture_name", "digest_key", "id_key"),
    (
        ("m1c-proposal-explore.json", "proposal_explore_digest", "proposal_explore_id"),
        (
            "m1c-proposal-replicate.json",
            "proposal_replicate_digest",
            "proposal_replicate_id",
        ),
    ),
)
def test_proposal_exact_round_trip_digest_and_id(
    fixture_name: str,
    digest_key: str,
    id_key: str,
) -> None:
    fixtures = _load(FIXTURES, "manifest.json")["fixtures"]
    raw = _load(FIXTURES, fixture_name)
    proposal = Proposal.from_mapping(raw)

    assert proposal.to_dict() == raw
    assert proposal.digest == fixtures[digest_key]
    assert proposal_id(fixtures["project_id"], proposal.digest) == fixtures[id_key]


def test_proposal_pointer_order_is_canonical() -> None:
    raw = _load(FIXTURES, "m1c-proposal-explore.json")
    raw["intervention_json_pointers"] = ["/y", "/x"]

    proposal = Proposal.from_mapping(raw)

    assert proposal.intervention_json_pointers == ("/x", "/y")
    assert proposal.to_dict()["intervention_json_pointers"] == ["/x", "/y"]


def test_all_25_proposal_negative_cases_have_one_stable_code() -> None:
    matrix = _load(FIXTURES, "m1c-proposal-negative-matrix.json")
    base = _load(FIXTURES, str(matrix["base_fixture"]))
    cases = matrix["cases"]
    assert len(cases) == 25

    for case in cases:
        with pytest.raises(ScientificStateError) as caught:
            Proposal.from_mapping(_negative_proposal(base, matrix, case))
        assert caught.value.code == "PROPOSAL_INVALID", case["id"]
        assert set(caught.value.details) == {"path", "reason"}, case["id"]


def test_narrative_limit_counts_utf8_bytes() -> None:
    raw = _load(FIXTURES, "m1c-proposal-explore.json")
    raw["mechanism"] = "가" * 5_461 + "x"
    assert len(raw["mechanism"].encode("utf-8")) == 16_384
    Proposal.from_mapping(raw)

    raw["mechanism"] += "x"
    assert len(raw["mechanism"].encode("utf-8")) == 16_385
    with pytest.raises(ScientificStateError) as caught:
        Proposal.from_mapping(raw)
    assert caught.value.code == "PROPOSAL_INVALID"
    assert caught.value.details["path"] == "$.mechanism"


def test_canonical_json_diff_is_recursive_escaped_sorted_and_array_atomic() -> None:
    parent = {
        "nested": {"same": 1, "changed": 1},
        "removed": True,
        "array": [1, 2],
        "a/b~c": 1,
    }
    candidate = {
        "nested": {"same": 1, "changed": 2},
        "added": True,
        "array": [1, 3],
        "a/b~c": 2,
    }

    assert canonical_json_diff_pointers(parent, candidate) == (
        "/added",
        "/array",
        "/a~1b~0c",
        "/nested/changed",
        "/removed",
    )
    assert canonical_json_diff_pointers(parent, parent) == ()
    assert canonical_json_diff_pointers([1], [2]) == ("",)
    assert canonical_json_diff_pointers({"x": {}}, {"x": 1}) == ("/x",)


def test_scoped_experiment_ids_and_null_scope_legacy_identity_are_exact() -> None:
    fixtures = _load(FIXTURES, "manifest.json")["fixtures"]
    common = {
        "project_id": fixtures["project_id"],
        "candidate_digest": fixtures["candidate_digest"],
        "compatibility_digest": fixtures["evaluation_seal"]["compatibility_digest"],
        "generation_id": fixtures["generation_id"],
    }
    parent = fixtures["explore_experiment_id"]
    observed = (
        new_experiment_id(
            **common,
            evaluation_scope_id="development",
            attempt=1,
        ),
        new_experiment_id(
            **common,
            evaluation_scope_id="development",
            attempt=2,
        ),
        new_experiment_id(
            **common,
            parent_id=parent,
            evaluation_scope_id="replication-1",
            attempt=1,
        ),
        new_experiment_id(
            **common,
            parent_id=parent,
            evaluation_scope_id="replication-1",
            attempt=2,
        ),
        new_experiment_id(
            **common,
            parent_id=parent,
            evaluation_scope_id="replication-2",
            attempt=1,
        ),
    )
    assert observed == (
        fixtures["explore_experiment_id"],
        fixtures["explore_retry_experiment_id"],
        fixtures["replication_1_experiment_id"],
        fixtures["replication_1_retry_experiment_id"],
        fixtures["replication_2_experiment_id"],
    )

    v1 = _load(V1_FIXTURES, "manifest.json")["fixtures"]
    legacy = new_experiment_id(
        "fixture-legacy-v1",
        "a" * 64,
        compatibility_digest="b" * 64,
    )
    assert legacy == v1["legacy_v1_experiment_id"]
    assert (
        new_experiment_id(
            "fixture-legacy-v1",
            "a" * 64,
            compatibility_digest="b" * 64,
            evaluation_scope_id=None,
        )
        == legacy
    )

    with pytest.raises(ValueError):
        new_experiment_id(
            fixtures["project_id"],
            fixtures["candidate_digest"],
            compatibility_digest=fixtures["evaluation_seal"]["compatibility_digest"],
            evaluation_scope_id="development",
        )
