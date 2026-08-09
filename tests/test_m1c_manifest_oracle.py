from __future__ import annotations

import copy
import io
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, redirect_stdout
from dataclasses import replace
from pathlib import Path
from threading import Barrier
from types import MethodType, SimpleNamespace
from unittest import mock

import pytest

from research_os.cli import main as cli_main
from research_os.contracts import Operation, ProtocolResponse
from research_os.contracts.common import canonical_json, sha256_json
from research_os.errors import ScientificStateError
from research_os.kernel.events import EventLog
from research_os.kernel.ids import new_experiment_id, stable_id
from research_os.kernel.projection import ProjectionStore
from research_os.scaffold import RESEARCH_BRIEF_TEMPLATE
from research_os.science import (
    EvaluationSeal,
    Proposal,
    ScientificState,
    StudyContract,
    plan_generation_open,
    proposal_id,
    reduce_scientific_state,
    registration_payload_fields,
    validate_registration,
)
from research_os.science.state import ScientificRegistration
from research_os.service import (
    EVALUATION_SCOPE_CAPABILITY,
    DoctorReport,
    ResearchService,
)
from tests.m1c_support import (
    DocumentResolver,
    DuplicateKeyError,
    OperationRegistry,
    ProposalNegativeInterpreter,
    apply_patch,
    sha256_bytes,
    sorted_compact_digest,
    strict_load_json,
    strict_load_json_lines,
)
from tests.test_m1b_manifest_oracle import _CASE_BY_ID as _M1B_CASES_BY_ID
from tests.test_m1b_manifest_oracle import _certified_project as _m1b_certified_project
from tests.test_m1b_manifest_oracle import (
    _observe_manifest_case as _observe_m1b_manifest_case,
)
from tests.test_m1b_service_cli import CONTRACT_PATH as M1B_CONTRACT_PATH

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "scientific_state" / "v2"
V1_FIXTURE_ROOT = FIXTURE_ROOT.parent / "v1"
MANIFEST_RAW_SHA256 = "4b9c216ea7a6bcbd8aec00a2224e4c41c349c038ea4b1d7c7fafcc8721e31b1d"
MANIFEST_SORTED_COMPACT_DIGEST = (
    "75d7e1e568f3d42463184544e4b396c6f68cd1ae91fc3d5026dffda8454dca67"
)


def _object(path: Path) -> dict[str, object]:
    value = strict_load_json(path)
    assert isinstance(value, dict)
    return value


_MANIFEST = _object(FIXTURE_ROOT / "manifest.json")
_MANIFEST_CASES = tuple(_MANIFEST["cases"])
assert all(isinstance(case, dict) for case in _MANIFEST_CASES)
_CASE_IDS = tuple(str(case["id"]) for case in _MANIFEST_CASES)
_CASES_BY_ID = {str(case["id"]): case for case in _MANIFEST_CASES}


def _fixtures() -> Mapping[str, object]:
    fixtures = _MANIFEST["fixtures"]
    assert isinstance(fixtures, Mapping)
    return fixtures


def _evaluation_seal() -> EvaluationSeal:
    value = _fixtures()["evaluation_seal"]
    assert isinstance(value, Mapping)
    return EvaluationSeal.from_mapping(value)


def _apply_pointer_mapping(
    document: object,
    operation: str,
    changes: Mapping[str, object],
) -> object:
    for pointer in sorted(changes):
        document = apply_patch(
            document,
            {"op": operation, "path": pointer, "value": changes[pointer]},
        )
    return document


def _observe_fixture_integrity(_: Mapping[str, object]) -> dict[str, object]:
    fixtures = _fixtures()
    linked = (
        ("candidate_schema", "candidate_schema_raw_sha256", "json"),
        ("contract", "contract_raw_sha256", "json"),
        ("proposal_explore", "proposal_explore_raw_sha256", "json"),
        ("proposal_replicate", "proposal_replicate_raw_sha256", "json"),
        ("proposal_negative_matrix", "proposal_negative_matrix_raw_sha256", "json"),
        ("transition_negative_matrix", "transition_negative_matrix_raw_sha256", "json"),
        ("m1b_v1_generation_events", "m1b_v1_generation_events_raw_sha256", "jsonl"),
        ("m1b_v1_compat_oracle", "m1b_v1_compat_oracle_raw_sha256", "json"),
    )
    matches = 0
    for path_key, digest_key, kind in linked:
        name = fixtures[path_key]
        expected = fixtures[digest_key]
        assert isinstance(name, str) and isinstance(expected, str)
        path = FIXTURE_ROOT / name
        if kind == "json":
            strict_load_json(path)
        else:
            strict_load_json_lines(path)
        matches += int(sha256_bytes(path.read_bytes()) == expected)
    proposal_matrix = _object(FIXTURE_ROOT / str(fixtures["proposal_negative_matrix"]))
    transition_matrix = _object(FIXTURE_ROOT / str(fixtures["transition_negative_matrix"]))
    return {
        "fixture_count": len(linked),
        "proposal_negative_cases": len(proposal_matrix["cases"]),
        "transition_negative_cases": len(transition_matrix["cases"]),
        "manifest_cases": len(_MANIFEST_CASES),
        "raw_digest_matches": matches,
    }


def _observe_v2_contract(inputs: Mapping[str, object]) -> dict[str, object]:
    fixture = inputs.get("fixture")
    assert isinstance(fixture, str)
    contract = StudyContract.from_mapping(_object(FIXTURE_ROOT / fixture))
    plan = plan_generation_open(
        [],
        project_id=str(_fixtures()["project_id"]),
        contract=contract,
        evaluation_seal=_evaluation_seal(),
    )
    manifests = [scope.manifest_digest for scope in contract.evaluation_scopes]
    return {
        "schema_version": contract.schema_version,
        "contract_digest": contract.digest,
        "candidate_schema_digest": contract.intervention_surface.candidate_schema_digest,
        "generation_id": plan.generation_id,
        "evaluation_scope_ids": [scope.id for scope in contract.evaluation_scopes],
        "scope_manifest_digests_unique": len(set(manifests)) == len(manifests),
        "required_adapter_capability": EVALUATION_SCOPE_CAPABILITY,
    }


def _observe_proposal(inputs: Mapping[str, object]) -> dict[str, object]:
    fixture = inputs.get("fixture")
    assert isinstance(fixture, str)
    raw = _object(FIXTURE_ROOT / fixture)
    original_pointers = copy.deepcopy(raw.get("intervention_json_pointers"))
    replacements = inputs.get("replace", {})
    assert isinstance(replacements, Mapping)
    raw = _apply_pointer_mapping(raw, "replace", replacements)  # type: ignore[assignment]
    assert isinstance(raw, Mapping)
    proposal = Proposal.from_mapping(raw)
    if replacements:
        return {
            "intervention_json_pointers": list(proposal.intervention_json_pointers),
            "input_order_preserved": (
                list(proposal.intervention_json_pointers) == original_pointers
            ),
            "authorized_action": proposal.authorized_action,
        }
    return {
        "proposal_digest": proposal.digest,
        "proposal_id": proposal_id(str(_fixtures()["project_id"]), proposal.digest),
        "action": proposal.action,
        "evaluation_scope_id": proposal.evaluation_scope_id,
        "intervention_json_pointers": list(proposal.intervention_json_pointers),
        "authorized_action": proposal.authorized_action,
    }


def _observe_generated_proposal(inputs: Mapping[str, object]) -> dict[str, object]:
    fixture = inputs.get("fixture")
    generated_spec = inputs.get("replace_generated")
    assert isinstance(fixture, str) and isinstance(generated_spec, Mapping)
    pointer = generated_spec.get("pointer")
    generator = generated_spec.get("generator")
    assert isinstance(pointer, str) and isinstance(generator, Mapping)
    matrix = _object(FIXTURE_ROOT / "m1c-proposal-negative-matrix.json")
    generated = ProposalNegativeInterpreter(matrix, FIXTURE_ROOT).generate(generator)
    raw = apply_patch(
        _object(FIXTURE_ROOT / fixture),
        {"op": "replace", "path": pointer, "value": generated},
    )
    assert isinstance(raw, Mapping)
    proposal = Proposal.from_mapping(raw)
    return {
        "accepted": True,
        "mechanism_code_points": len(proposal.mechanism),
        "mechanism_utf8_bytes": len(proposal.mechanism.encode("utf-8")),
        "authorized_action": proposal.authorized_action,
    }


def _observe_proposal_negatives(inputs: Mapping[str, object]) -> dict[str, object]:
    fixture = inputs.get("fixture")
    assert isinstance(fixture, str)
    matrix = _object(FIXTURE_ROOT / fixture)
    cases = matrix.get("cases")
    assert isinstance(cases, list)
    interpreter = ProposalNegativeInterpreter(matrix, FIXTURE_ROOT)
    codes: list[str] = []
    for case in cases:
        assert isinstance(case, Mapping)
        try:
            Proposal.from_mapping(interpreter.materialize(case))  # type: ignore[arg-type]
        except ScientificStateError as exc:
            codes.append(exc.code)
        else:
            codes.append("ACCEPTED")
    return {
        "cases": len(cases),
        "rejections": sum(code != "ACCEPTED" for code in codes),
        "error_code": codes[0] if len(set(codes)) == 1 else "MIXED",
    }


def _recursive_key_occurrences(value: object, keys: frozenset[str]) -> int:
    if isinstance(value, Mapping):
        return sum(key in keys for key in value) + sum(
            _recursive_key_occurrences(item, keys) for item in value.values()
        )
    if isinstance(value, list):
        return sum(_recursive_key_occurrences(item, keys) for item in value)
    return 0


def _canonical_shape(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _canonical_shape(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        if not value:
            return []
        shapes = [_canonical_shape(item) for item in value]
        if any(shape != shapes[0] for shape in shapes[1:]):
            raise AssertionError("public surface sequence has heterogeneous shapes")
        return [shapes[0]]
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    raise AssertionError(f"unsupported public surface value: {type(value).__name__}")


def _fixed_v1_service(
    root: Path,
    generation_bytes: bytes,
) -> ResearchService:
    project = root / "project"
    shutil.copytree(Path(__file__).resolve().parents[1] / "examples" / "toy_optimization", project)
    runtime = project / ".research-os" / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    config_path = project / ".research-os" / "project.toml"
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace(
            'id = "toy-optimization"',
            'id = "fixture-m1c-v1-compat"',
            1,
        ),
        encoding="utf-8",
    )
    runtime.mkdir(parents=True)
    (runtime / "events.jsonl").write_bytes(generation_bytes)
    return ResearchService(project)


def _observe_v1_public_surfaces(
    root: Path,
    *,
    public_keysets: Mapping[str, object],
    shape_digests: Mapping[str, object],
) -> tuple[int, int, int]:
    root.mkdir(parents=True)
    project, service = _m1b_certified_project(root)
    baseline = service.baseline()
    opened = service.open_generation(M1B_CONTRACT_PATH)
    run = service.run_once(project / "candidates" / "improve.json")
    generation_event = next(
        event
        for event in service.event_log.read()
        if event.event_type == "research.study_generation_opened.v1"
    )
    registration_event = next(
        event
        for event in service.event_log.read()
        if event.event_type == "EXPERIMENT_REGISTERED"
    )
    study_status = service.study_status()
    replay = service.replay()
    experiment_id = str(run["experiment_id"])
    surfaces: dict[str, Mapping[str, object]] = {
        "generation_event_payload": generation_event.payload,
        "open_generation": opened,
        "baseline": baseline,
        "run_once": run,
        "study_status": study_status,
        "replay": replay,
        "replay_science": replay["science"],  # type: ignore[dict-item]
        "projection_experiment": service.projection.experiment(
            service.config.project_id,
            experiment_id,
        ),
        "project_status": service.projection.project_status(
            service.config.project_id
        ),
        "registration_payload": registration_event.payload,
    }
    cli_root = root / "cli"
    cli_root.mkdir()
    cli_project, cli_service = _m1b_certified_project(cli_root)
    cli_baseline = _cli_json(
        ["--project", str(cli_project), "baseline"]
    )
    cli_opened = _cli_json(
        [
            "--project",
            str(cli_project),
            "open-generation",
            str(M1B_CONTRACT_PATH),
        ]
    )
    cli_run = _cli_json(
        [
            "--project",
            str(cli_project),
            "run-once",
            str(cli_project / "candidates" / "improve.json"),
        ]
    )
    cli_study_status = _cli_json(
        ["--project", str(cli_project), "study-status"]
    )
    cli_replay = _cli_json(["--project", str(cli_project), "replay"])
    cli_generation_event = next(
        event
        for event in cli_service.event_log.read()
        if event.event_type == "research.study_generation_opened.v1"
    )
    cli_registration_event = next(
        event
        for event in cli_service.event_log.read()
        if event.event_type == "EXPERIMENT_REGISTERED"
    )
    cli_experiment_id = str(cli_run["experiment_id"])
    cli_surfaces: dict[str, Mapping[str, object]] = {
        "generation_event_payload": cli_generation_event.payload,
        "open_generation": cli_opened,
        "baseline": cli_baseline,
        "run_once": cli_run,
        "study_status": cli_study_status,
        "replay": cli_replay,
        "replay_science": cli_replay["science"],  # type: ignore[dict-item]
        "projection_experiment": cli_service.projection.experiment(
            cli_service.config.project_id,
            cli_experiment_id,
        ),
        "project_status": cli_service.projection.project_status(
            cli_service.config.project_id
        ),
        "registration_payload": cli_registration_event.payload,
    }
    assert set(cli_surfaces) == set(surfaces)
    assert all(
        _canonical_shape(cli_surfaces[name]) == _canonical_shape(surface)
        for name, surface in surfaces.items()
    )
    keyset_matches = sum(
        sorted(surfaces[name]) == expected
        for name, expected in public_keysets.items()
    )
    shape_matches = sum(
        sha256_json(_canonical_shape(surfaces[name])) == expected
        for name, expected in shape_digests.items()
    )
    nullable_scope_keys = {"evaluation_scope", "evaluation_scope_id"}
    nullable_scope_occurrences = sum(
        key in nullable_scope_keys
        for name in public_keysets
        for key in surfaces[name]
    )
    return keyset_matches, shape_matches, nullable_scope_occurrences


def _observe_legacy_parity(inputs: Mapping[str, object], tmp_path: Path) -> dict[str, object]:
    legacy_name = inputs.get("legacy_events")
    generation_name = inputs.get("m1b_generation_events")
    oracle_name = inputs.get("compatibility_oracle")
    v1_manifest_name = inputs.get("v1_manifest")
    assert all(
        isinstance(value, str)
        for value in (legacy_name, generation_name, oracle_name, v1_manifest_name)
    )
    legacy_path = FIXTURE_ROOT / str(legacy_name)
    legacy_bytes = legacy_path.read_bytes()
    legacy_copy = tmp_path / "legacy-events.jsonl"
    legacy_copy.write_bytes(legacy_bytes)
    legacy_log = EventLog(legacy_copy, "fixture-legacy-v1")
    legacy_projection = ProjectionStore(tmp_path / "legacy-state.db")
    legacy_projection.rebuild(legacy_log)
    legacy_id = str(_fixtures()["legacy_v1_experiment_id"])
    legacy_observed = {
        "experiment": legacy_projection.experiment("fixture-legacy-v1", legacy_id),
        "status": legacy_projection.project_status("fixture-legacy-v1"),
    }

    generation_path = FIXTURE_ROOT / str(generation_name)
    generation_bytes = generation_path.read_bytes()
    generation_copy = tmp_path / "generation-events.jsonl"
    generation_copy.write_bytes(generation_bytes)
    generation_log = EventLog(generation_copy, "fixture-m1c-v1-compat")
    events = generation_log.read()
    state = reduce_scientific_state(events, project_id="fixture-m1c-v1-compat")
    projection = ProjectionStore(tmp_path / "generation-state.db")
    projection.rebuild(generation_log)
    projection_observed = {
        "status": projection.project_status("fixture-m1c-v1-compat"),
        "lineage": projection.lineage("fixture-m1c-v1-compat"),
    }
    oracle = _object(FIXTURE_ROOT / str(oracle_name))
    oracle_expected = oracle["expected"]
    assert isinstance(oracle_expected, Mapping)
    v1_manifest = _object(FIXTURE_ROOT / str(v1_manifest_name))
    v1_contract = StudyContract.from_mapping(_object(V1_FIXTURE_ROOT / "m1b-contract.json"))
    first_plan = plan_generation_open(
        [],
        project_id="fixture-m1b",
        contract=v1_contract,
        evaluation_seal=_evaluation_seal(),
    )
    registration_ids = [
        event.payload["experiment_id"]
        for event in events
        if event.event_type == "EXPERIMENT_REGISTERED"
    ]
    finding_ids = [
        event.payload["finding_id"]
        for event in events
        if event.event_type == "FINDING_RECORDED"
    ]
    forbidden = frozenset(oracle["forbidden_typed_keys"])  # type: ignore[arg-type]
    public_keysets = oracle["public_surface_keysets"]
    shape_oracle = oracle["public_surface_shape_oracle"]
    invariance = oracle["m1b_manifest_invariance"]
    assert isinstance(public_keysets, Mapping)
    assert isinstance(shape_oracle, Mapping)
    assert isinstance(invariance, Mapping)
    shape_digests = shape_oracle["shape_digests"]
    assert isinstance(shape_digests, Mapping)
    fixed_service = _fixed_v1_service(
        tmp_path / "fixed-v1-service",
        generation_bytes,
    )
    service_status = fixed_service.study_status()
    before_replay_bytes = fixed_service.event_log.path.read_bytes()
    before_replay_head = fixed_service.event_log.read()[-1].hash
    replay = fixed_service.replay()
    replay_findings = fixed_service.findings()
    after_replay_events = fixed_service.event_log.read()
    keyset_matches, shape_matches, public_scope_occurrences = (
        _observe_v1_public_surfaces(
            tmp_path / "v1-public-surfaces",
            public_keysets=public_keysets,
            shape_digests=shape_digests,
        )
    )
    expected_registration_keys = oracle["exact_v1_registration_keyset"]
    assert isinstance(expected_registration_keys, list)
    actual_registration_keysets = [
        sorted(event.payload)
        for event in events
        if event.event_type == "EXPERIMENT_REGISTERED"
    ]
    assert actual_registration_keysets
    assert all(
        keyset == expected_registration_keys
        for keyset in actual_registration_keysets
    )
    v1_manifest_path = FIXTURE_ROOT / str(v1_manifest_name)
    assert sha256_bytes(v1_manifest_path.read_bytes()) == invariance["raw_sha256"]
    assert sorted_compact_digest(v1_manifest) == invariance["sorted_compact_digest"]
    assert set(_M1B_CASES_BY_ID) == {
        str(case["id"])
        for case in v1_manifest["cases"]  # type: ignore[index]
        if isinstance(case, Mapping)
    }
    m1b_matches = 0
    for ordinal, case in enumerate(_M1B_CASES_BY_ID.values()):
        case_root = tmp_path / "m1b-manifest" / str(ordinal)
        case_root.mkdir(parents=True)
        observed = _observe_m1b_manifest_case(case, case_root)
        m1b_matches += int(observed == case["expected"])
    event_typed_occurrences = _recursive_key_occurrences(
        [event.payload for event in events],
        forbidden,
    )
    return {
        "legacy_event_bytes_sha256": sha256_bytes(legacy_bytes),
        "legacy_experiment_id": legacy_id,
        "legacy_projection_canonical_digest": sha256_json(legacy_observed),
        "m1b_contract_digest": v1_contract.digest,
        "m1b_generation_id": first_plan.generation_id,
        "m1b_generation_event_count": len(events),
        "m1b_generation_event_bytes": len(generation_bytes),
        "m1b_generation_event_bytes_sha256": sha256_bytes(generation_bytes),
        "m1b_generation_event_head": events[-1].hash,
        "m1b_fixture_generation_id": state.active_generation_id,
        "m1b_fixture_experiment_ids": registration_ids,
        "m1b_fixture_finding_ids": finding_ids,
        "m1b_science_state_digest": sha256_json(state.to_dict()),
        "m1b_projection_digest": sha256_json(projection_observed),
        "m1b_study_status_digest": sha256_json(service_status),
        "m1b_replay_digest": sha256_json(replay),
        "m1b_replay_events": replay["events_replayed"],
        "m1b_replay_findings": len(replay_findings),
        "m1b_event_bytes_preserved_after_replay": (
            fixed_service.event_log.path.read_bytes() == before_replay_bytes
        ),
        "m1b_event_head_preserved_after_replay": (
            after_replay_events[-1].hash == before_replay_head
        ),
        "m1b_manifest_exact_matches": m1b_matches,
        "m1b_exact_registration_keys": len(actual_registration_keysets[0]),
        "m1b_public_surface_keysets_exact": keyset_matches,
        "m1b_public_surface_shape_digests_exact": shape_matches,
        "nullable_scope_api_keys_added": public_scope_occurrences,
        "typed_key_occurrences": event_typed_occurrences,
    }


def _observe_scope_ids(inputs: Mapping[str, object]) -> dict[str, object]:
    scopes = inputs.get("scope_ids")
    assert isinstance(scopes, list) and all(isinstance(scope, str) for scope in scopes)
    fixtures = _fixtures()
    project_id = str(fixtures["project_id"])
    generation_id = str(fixtures["generation_id"])
    compatibility = str(fixtures["evaluation_seal"]["compatibility_digest"])  # type: ignore[index]
    candidate_digest = str(fixtures["candidate_digest"])
    root_id = new_experiment_id(
        project_id,
        candidate_digest,
        compatibility_digest=compatibility,
        generation_id=generation_id,
        evaluation_scope_id=str(scopes[0]),
        attempt=1,
    )
    experiment_ids = [root_id]
    experiment_ids.extend(
        new_experiment_id(
            project_id,
            candidate_digest,
            parent_id=root_id,
            compatibility_digest=compatibility,
            generation_id=generation_id,
            evaluation_scope_id=str(scope),
            attempt=1,
        )
        for scope in scopes[1:]
    )
    legacy_id = new_experiment_id(
        "fixture-legacy-v1",
        "a" * 64,
        compatibility_digest="b" * 64,
    )
    return {
        "experiment_ids": experiment_ids,
        "unique_experiment_ids": len(set(experiment_ids)),
        "legacy_experiment_id": legacy_id,
    }


def _event_mapping(event_type: str, payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "project_id": str(_fixtures()["project_id"]),
        "event_type": event_type,
        "payload": copy.deepcopy(dict(payload)),
    }


def _baseline_payload(
    state: ScientificState,
    evaluation_scope_id: str | None,
) -> dict[str, object]:
    compatibility = str(_fixtures()["evaluation_seal"]["compatibility_digest"])  # type: ignore[index]
    payload: dict[str, object] = {
        "baseline_id": stable_id(
            "baseline",
            state.project_id,
            state.active_generation_id,
            evaluation_scope_id,
        ),
        "compatibility_digest": compatibility,
        "metrics": {"score": 1.0},
        "primary_metric": "score",
        "primary_value": 1.0,
        "repetitions": 1,
        "observations": [],
        "verifications": [],
        "artifacts": [],
        "spread": 0.0,
        "tolerance": 0.0,
        "fingerprints": {},
        "adapter_fingerprint": {},
        "authorized_action": None,
    }
    if evaluation_scope_id is not None:
        assert state.contract is not None
        scope = next(
            item
            for item in state.contract.evaluation_scopes
            if item.id == evaluation_scope_id
        )
        payload.update(
            {
                "science_state_version": 1,
                "generation_id": state.active_generation_id,
                "study_contract_digest": state.study_contract_digest,
                "evaluation_seal_digest": state.evaluation_seal_digest,
                "evaluation_scope_id": evaluation_scope_id,
                "evaluation_scope": scope.to_dict(),
            }
        )
    payload["digest"] = sha256_json(payload)
    return payload


def _registration_payload(
    state: ScientificState,
    candidate: Mapping[str, object],
    proposal_raw: Mapping[str, object] | None,
    *,
    retry_of: str | None = None,
) -> dict[str, object]:
    candidate_body = copy.deepcopy(dict(candidate))
    candidate_digest = sha256_json(candidate_body)
    proposal = None if proposal_raw is None else Proposal.from_mapping(proposal_raw)
    prior = None if retry_of is None else state.registration(retry_of)
    attempt = 1 if prior is None else prior.attempt + 1
    parent_id = None if proposal is None else proposal.parent_experiment_id
    evaluation_scope_id = None if proposal is None else proposal.evaluation_scope_id
    compatibility = (
        str(_fixtures()["evaluation_seal"]["compatibility_digest"])  # type: ignore[index]
        if state.evaluation_seal is None
        else state.evaluation_seal.compatibility_digest
    )
    baseline = (
        None
        if evaluation_scope_id is None
        else state.baseline_for_scope(evaluation_scope_id)
    )
    if baseline is not None:
        baseline_id = baseline.baseline_id
    elif state.scope_baselines:
        baseline_id = state.scope_baselines[-1].baseline_id
    else:
        baseline_id = stable_id(
            "baseline",
            state.project_id,
            state.active_generation_id,
            evaluation_scope_id,
            "missing",
        )
    experiment_id = new_experiment_id(
        state.project_id,
        candidate_digest,
        compatibility_digest=compatibility,
        parent_id=parent_id,
        generation_id=state.active_generation_id,
        evaluation_scope_id=evaluation_scope_id,
        attempt=attempt,
    )
    payload: dict[str, object] = {
        "experiment_id": experiment_id,
        "parent_id": parent_id,
        "candidate_digest": candidate_digest,
        "candidate": candidate_body,
        "compatibility_digest": compatibility,
        "source_tree_digest": "a" * 64,
        "baseline_id": baseline_id,
        "primary_metric": "score",
        "attempt": attempt,
        "retry_of": retry_of,
        "status": "registered",
        "authorized_action": None,
        **registration_payload_fields(state, retry_of=retry_of),
    }
    if proposal is not None:
        payload.update(
            {
                "proposal": proposal.to_dict(),
                "proposal_digest": proposal.digest,
                "proposal_id": proposal_id(state.project_id, proposal.digest),
                "evaluation_scope_id": proposal.evaluation_scope_id,
            }
        )
    return payload


def _recompute_registration_field(
    payload: dict[str, object],
    field: str,
) -> None:
    if field == "candidate_digest":
        payload[field] = sha256_json(payload["candidate"])
        return
    if field == "proposal_digest":
        proposal = Proposal.from_mapping(payload["proposal"])
        payload[field] = proposal.digest
        return
    if field == "proposal_id":
        payload[field] = proposal_id(
            str(_fixtures()["project_id"]),
            str(payload["proposal_digest"]),
        )
        return
    if field == "experiment_id":
        payload[field] = new_experiment_id(
            str(_fixtures()["project_id"]),
            str(payload["candidate_digest"]),
            compatibility_digest=str(payload["compatibility_digest"]),
            parent_id=payload.get("parent_id"),  # type: ignore[arg-type]
            generation_id=payload.get("generation_id"),  # type: ignore[arg-type]
            evaluation_scope_id=payload.get("evaluation_scope_id"),  # type: ignore[arg-type]
            attempt=int(payload.get("attempt", 1)),
        )
        return
    raise KeyError(f"unsupported registration recompute field: {field!r}")


def _state_with_parent_view(
    state: ScientificState,
    view: Mapping[str, object],
) -> ScientificState:
    candidate = view.get("candidate")
    assert isinstance(candidate, Mapping)
    candidate_digest = sha256_json(candidate)
    proposal_raw = _object(FIXTURE_ROOT / "m1c-proposal-explore.json")
    proposal_raw["generation_id"] = view["generation_id"]
    proposal_raw["candidate_digest"] = candidate_digest
    proposal_raw["hypothesis_class_id"] = view["hypothesis_class_id"]
    proposal_raw["evaluation_scope_id"] = view["evaluation_scope_id"]
    proposal = Proposal.from_mapping(proposal_raw)
    registration = ScientificRegistration(
        experiment_id=str(view["experiment_id"]),
        generation_id=str(view["generation_id"]),
        candidate_digest=candidate_digest,
        candidate_json=canonical_json(candidate),
        proposal=proposal,
        proposal_digest=proposal.digest,
        proposal_id=proposal_id(state.project_id, proposal.digest),
        parent_id=None,
        evaluation_scope_id=str(view["evaluation_scope_id"]),
        compatibility_digest=str(view["compatibility_digest"]),
        baseline_id="parent-view",
        attempt=1,
        retry_of=None,
        terminal_status="VALIDATED" if view.get("terminal") is True else None,
        retryable=False,
    )
    return replace(state, registrations=(*state.registrations, registration))


class _ReplayHarness(ResearchService):
    """Run the real replay implementation with unrelated evidence stores empty."""

    def __init__(self, event_log: EventLog, projection: ProjectionStore) -> None:
        self.config = SimpleNamespace(project_id=str(_fixtures()["project_id"]))  # type: ignore[assignment]
        self.event_log = event_log
        self.projection = projection
        self.catalog = SimpleNamespace(get=lambda _: None)  # type: ignore[assignment]

    @contextmanager
    def _workflow_lock(self):  # type: ignore[no-untyped-def,override]
        yield

    def _assert_config_unchanged(self) -> None:
        return None

    def _recover_incomplete_experiments(self) -> None:
        return None

    def _verify_terminal_artifact_bindings(self, projected_records):  # type: ignore[no-untyped-def,override]
        return None

    def _validate_baseline_payload(  # type: ignore[no-untyped-def,override]
        self,
        payload,
        compatibility_digest,
        **kwargs,
    ):
        return {**payload, "artifacts": []}


class _TransitionScenario:
    """Execute the frozen scenario vocabulary without receiving a matrix case ID."""

    def __init__(
        self,
        resolver: DocumentResolver,
        scenario: Mapping[str, object],
        fixture_root: Path,
        environment_root: Path,
    ) -> None:
        self.resolver = resolver
        self.scenario = scenario
        self.fixture_root = fixture_root
        self.project_id = str(_fixtures()["project_id"])
        self.events: list[dict[str, object]] = []
        self.state = reduce_scientific_state([], project_id=self.project_id)
        self.captures: dict[str, object] = {}
        self.parent_views: list[dict[str, object]] = []
        self.baseline_scope_ids: list[str | None] = []
        self.last_registration_payload: dict[str, object] | None = None
        control = environment_root / ".research-os"
        control.mkdir(parents=True, exist_ok=True)
        (control / "candidate.schema.json").write_bytes(
            (fixture_root / "m1c-candidate-schema.json").read_bytes()
        )
        self.service = object.__new__(ResearchService)
        self.service.config = SimpleNamespace(  # type: ignore[assignment]
            root=environment_root,
            project_id=self.project_id,
        )
        profile_name = scenario.get("project_profile")
        assert isinstance(profile_name, str)
        profile = resolver.profile(profile_name)
        capabilities = profile.get("adapter_capabilities")
        assert isinstance(capabilities, list)
        self.report = DoctorReport(
            project_id=self.project_id,
            project_root=str(environment_root),
            capabilities=tuple(str(item) for item in capabilities),
            side_effects=(),
            adapter_fingerprint={},
            fingerprints={"compatibility_digest": profile["compatibility_digest"]},
            event_count=0,
        )

    def _refresh(self) -> None:
        self.state = reduce_scientific_state(
            self.events,
            project_id=self.project_id,
        )

    def _append(self, event_type: str, payload: Mapping[str, object]) -> None:
        self.events.append(_event_mapping(event_type, payload))
        self._refresh()

    def _resolve(
        self,
        value: object,
        *,
        local_documents: Mapping[str, object] | None = None,
    ) -> object:
        return self.resolver.resolve_value(
            value,
            local_documents=local_documents,
            captures=self.captures,
        )

    def build(self) -> None:
        steps = self.scenario.get("steps")
        assert isinstance(steps, list)
        for raw_step in steps:
            resolved = self._resolve(raw_step)
            assert isinstance(resolved, Mapping)
            driver = resolved.get("driver")
            if driver == "generation.open":
                contract_raw = resolved.get("contract")
                assert isinstance(contract_raw, Mapping)
                contract = StudyContract.from_mapping(contract_raw)
                self.service._validate_typed_generation_environment(
                    contract,
                    self.report,
                )
                plan = plan_generation_open(
                    self.events,
                    project_id=self.project_id,
                    contract=contract,
                    evaluation_seal=_evaluation_seal(),
                )
                self._append(plan.event_type, plan.payload)
            elif driver == "baseline.record":
                scope_id = resolved.get("evaluation_scope_id")
                assert scope_id is None or isinstance(scope_id, str)
                scope = self.service._resolve_baseline_evaluation_scope(
                    self.state,
                    scope_id,
                )
                normalized_scope_id = None if scope is None else scope.id
                self._append(
                    "BASELINE_RECORDED",
                    _baseline_payload(self.state, normalized_scope_id),
                )
                self.baseline_scope_ids.append(normalized_scope_id)
            elif driver == "registration.append":
                candidate = resolved.get("candidate")
                proposal = resolved.get("proposal")
                assert isinstance(candidate, Mapping) and isinstance(proposal, Mapping)
                payload = _registration_payload(self.state, candidate, proposal)
                self._append("EXPERIMENT_REGISTERED", payload)
                capture = resolved.get("capture")
                if isinstance(capture, str):
                    self.captures[capture] = {
                        "experiment_id": payload["experiment_id"],
                        "payload": copy.deepcopy(payload),
                    }
            elif driver == "experiment.terminate":
                experiment_id = resolved.get("experiment_id")
                status = resolved.get("status")
                retryable = resolved.get("retryable")
                assert isinstance(experiment_id, str) and isinstance(status, str)
                registration = self.state.registration(experiment_id)
                assert registration is not None and isinstance(retryable, bool)
                self._append(
                    "EXPERIMENT_TERMINATED",
                    {
                        "experiment_id": experiment_id,
                        "status": status,
                        "reason_code": (
                            "ADAPTER_TIMEOUT" if status == "TIMED_OUT" else "VERIFIED"
                        ),
                        "attempt": registration.attempt,
                        "retry_of": registration.retry_of,
                        "retryable": retryable,
                        "authorized_action": None,
                    },
                )
            elif driver == "event.append":
                event_type = resolved.get("event_type")
                payload = resolved.get("payload")
                assert isinstance(event_type, str) and isinstance(payload, Mapping)
                self._append(event_type, payload)
                if event_type == "BASELINE_RECORDED":
                    scope = payload.get("evaluation_scope_id")
                    self.baseline_scope_ids.append(
                        scope if isinstance(scope, str) else None
                    )
            elif driver == "parent_view.inject":
                capture = resolved.get("capture")
                assert isinstance(capture, str)
                view = {
                    key: copy.deepcopy(value)
                    for key, value in resolved.items()
                    if key not in {"driver", "capture"}
                }
                self.parent_views.append(view)
                self.captures[capture] = copy.deepcopy(view)
            else:
                raise KeyError(f"unsupported scenario driver: {driver!r}")
        self._assert_expected_state()

    def _assert_expected_state(self) -> None:
        expected = self.scenario.get("expected_state")
        assert isinstance(expected, Mapping)
        terminal_ids = [
            registration.experiment_id
            for registration in self.state.registrations
            if registration.is_terminal
        ]
        observed: dict[str, object] = {
            "active_generation_id": self.state.active_generation_id,
            "contract_schema_version": (
                None if self.state.contract is None else self.state.contract.schema_version
            ),
            "baseline_scope_ids": self.baseline_scope_ids,
            "attempts_used": self.state.attempts_used,
            "retries_used": self.state.retries_used,
            "registrations": [
                registration.experiment_id for registration in self.state.registrations
            ],
            "terminal_experiment_ids": terminal_ids,
            "terminal_count": len(terminal_ids),
            "replication_count": self.state.replication_count,
            "used_candidate_scope_pairs": self.state.used_candidate_scope_pairs,
            "parent_view_count": len(self.parent_views),
        }
        assert all(observed[key] == value for key, value in expected.items())

    def snapshot(self) -> dict[str, int]:
        return {
            "canonical_events": len(self.events),
            "generation_events": sum(
                event["event_type"] == "research.study_generation_opened.v1"
                for event in self.events
            ),
            "baseline_events": sum(
                event["event_type"] == "BASELINE_RECORDED" for event in self.events
            ),
            "registration_events": sum(
                event["event_type"] == "EXPERIMENT_REGISTERED"
                for event in self.events
            ),
            "budget_attempts": self.state.attempts_used,
            "budget_retries": self.state.retries_used,
        }

    def _prospective_state(self, arguments: Mapping[str, object]) -> ScientificState:
        parent_view = arguments.get("parent_view")
        if isinstance(parent_view, Mapping):
            return _state_with_parent_view(self.state, parent_view)
        return self.state

    def _mutated_registration(
        self,
        arguments: Mapping[str, object],
        *,
        retry: bool,
    ) -> dict[str, object]:
        if retry:
            retry_of = arguments.get("retry_of")
            assert isinstance(retry_of, str)
            prior = next(
                event["payload"]
                for event in reversed(self.events)
                if event["event_type"] == "EXPERIMENT_REGISTERED"
                and isinstance(event["payload"], Mapping)
                and event["payload"].get("experiment_id") == retry_of
            )
            assert isinstance(prior, Mapping)
            payload = copy.deepcopy(dict(prior))
            payload["attempt"] = int(prior["attempt"]) + 1
            payload["retry_of"] = retry_of
            payload.update(registration_payload_fields(self.state, retry_of=retry_of))
            _recompute_registration_field(payload, "experiment_id")
        else:
            base_payload = arguments.get("base_payload")
            if isinstance(base_payload, Mapping):
                payload = copy.deepcopy(dict(base_payload))
            else:
                candidate = arguments.get("candidate")
                proposal = arguments.get("proposal")
                assert isinstance(candidate, Mapping) and isinstance(proposal, Mapping)
                payload = _registration_payload(self.state, candidate, proposal)
        mutations = arguments.get("mutations", [])
        assert isinstance(mutations, list)
        document: object = payload
        for mutation in mutations:
            assert isinstance(mutation, Mapping)
            document = apply_patch(document, mutation)
        assert isinstance(document, dict)
        payload = document
        recompute = arguments.get("recompute", [])
        assert isinstance(recompute, list)
        for field in recompute:
            assert isinstance(field, str)
            _recompute_registration_field(payload, field)
        asserted = arguments.get("assert_recomputed", {})
        assert isinstance(asserted, Mapping)
        assert all(payload.get(key) == value for key, value in asserted.items())
        return payload

    def invoke(
        self,
        raw_invoke: Mapping[str, object],
        *,
        local_documents: Mapping[str, object],
    ) -> None:
        invoke = self._resolve(raw_invoke, local_documents=local_documents)
        assert isinstance(invoke, Mapping)
        driver = invoke.get("driver")
        arguments = invoke.get("arguments")
        assert isinstance(driver, str) and isinstance(arguments, Mapping)
        self.last_registration_payload = None
        if driver == "generation.open":
            contract_raw = arguments.get("contract")
            assert isinstance(contract_raw, Mapping)
            contract = StudyContract.from_mapping(contract_raw)
            self.service._validate_typed_generation_environment(contract, self.report)
            plan_generation_open(
                self.events,
                project_id=self.project_id,
                contract=contract,
                evaluation_seal=_evaluation_seal(),
            )
            return
        if driver == "service.baseline":
            scope_id = arguments.get("evaluation_scope_id")
            assert scope_id is None or isinstance(scope_id, str)
            self.service._resolve_baseline_evaluation_scope(self.state, scope_id)
            return
        if driver in {"service.run_once", "service.retry"}:
            proposal_value = arguments.get("proposal")
            proposal_input = proposal_value if isinstance(proposal_value, Mapping) else None
            retry_of = arguments.get("retry_of")
            assert retry_of is None or isinstance(retry_of, str)
            typed = self.service._validate_proposal_mode(
                self.state,
                proposal=proposal_input,
                parent_id=None,
                retry_of=retry_of,
                graph_action=None,
                scientific_change=None,
            )
            if not typed:
                return
            candidate = arguments.get("candidate")
            assert isinstance(candidate, Mapping)
            payload = _registration_payload(
                self.state,
                candidate,
                proposal_input,
                retry_of=retry_of,
            )
            self.last_registration_payload = payload
            validate_registration(self.state, payload)
            return
        if driver == "science.preflight_registration":
            candidate = arguments.get("candidate")
            proposal = arguments.get("proposal")
            assert isinstance(candidate, Mapping) and isinstance(proposal, Mapping)
            payload = _registration_payload(self.state, candidate, proposal)
            self.last_registration_payload = payload
            validate_registration(self._prospective_state(arguments), payload)
            return
        if driver in {"replay.mutated_registration", "replay.mutated_retry"}:
            payload = self._mutated_registration(
                arguments,
                retry=driver == "replay.mutated_retry",
            )
            self.last_registration_payload = payload
            reduce_scientific_state(
                [*self.events, _event_mapping("EXPERIMENT_REGISTERED", payload)],
                project_id=self.project_id,
            )
            return
        raise KeyError(f"unsupported invoke driver: {driver!r}")


def _append_valid_events(log: EventLog, events: list[dict[str, object]]) -> None:
    log.append(
        "PROJECT_INITIALIZED",
        {
            "project_id": str(_fixtures()["project_id"]),
            "status": "active",
            "authorized_action": None,
        },
    )
    for event in events:
        event_type = event["event_type"]
        payload = event["payload"]
        assert isinstance(event_type, str) and isinstance(payload, Mapping)
        log.append(event_type, payload)


def _direct_rejection_code(
    path: str,
    events: list[dict[str, object]],
    payload: Mapping[str, object],
    root: Path,
) -> str:
    log = EventLog(root / "events.jsonl", str(_fixtures()["project_id"]))
    _append_valid_events(log, events)
    proposed = _event_mapping("EXPERIMENT_REGISTERED", payload)
    try:
        if path == "locked_registration_append":
            before = len(log.read())
            log.append(
                "EXPERIMENT_REGISTERED",
                payload,
                precondition=lambda locked: reduce_scientific_state(
                    [*locked, proposed],
                    project_id=str(_fixtures()["project_id"]),
                ),
            )
            assert len(log.read()) == before + 1
        elif path == "cold_science_reduce":
            reduce_scientific_state(
                [*log.read(), proposed],
                project_id=str(_fixtures()["project_id"]),
            )
        elif path == "projection_rebuild":
            log.append("EXPERIMENT_REGISTERED", payload)
            ProjectionStore(root / "projection.db").rebuild(log)
        elif path == "research_service_replay":
            log.append("EXPERIMENT_REGISTERED", payload)
            service = _ReplayHarness(log, ProjectionStore(root / "service.db"))
            service.replay()
        else:
            raise KeyError(f"unsupported direct replay path: {path!r}")
    except ScientificStateError as exc:
        return exc.code
    raise AssertionError(f"direct replay path accepted an invalid registration: {path}")


def _observe_transition_negatives(
    inputs: Mapping[str, object],
    tmp_path: Path,
) -> dict[str, object]:
    fixture = inputs.get("fixture")
    assert isinstance(fixture, str)
    matrix = _object(FIXTURE_ROOT / fixture)
    baseline_deriver = _ServiceBaselineDeriver(tmp_path / "baseline-derive")
    resolver = DocumentResolver(
        matrix,
        FIXTURE_ROOT,
        derive_handlers={"service.baseline_event_payload": baseline_deriver},
        recompute_handlers={"digest": _recompute_digest},
        control_handlers=baseline_deriver.control_handlers,
    )
    cases = matrix.get("cases")
    assert isinstance(cases, list)
    rejected = 0
    event_delta_zero = 0
    budget_delta_zero = 0
    direct_matches = 0
    case_id_dispatches = 0
    for ordinal, case in enumerate(cases):
        assert isinstance(case, Mapping)
        case_input = {
            key: copy.deepcopy(value)
            for key, value in case.items()
            if key != "id"
        }
        case_id_dispatches += int("id" in case_input)
        scenario_name = case_input.get("scenario")
        assert isinstance(scenario_name, str)
        scenario = resolver.scenario(scenario_name)
        runner = _TransitionScenario(
            resolver,
            scenario,
            FIXTURE_ROOT,
            tmp_path / f"environment-{ordinal}",
        )
        runner.build()
        local_documents = case_input.get("documents", {})
        invoke = case_input.get("invoke")
        assert isinstance(local_documents, Mapping) and isinstance(invoke, Mapping)
        expected = resolver.resolve_value(
            case_input.get("expected"),
            captures=runner.captures,
        )
        assert isinstance(expected, Mapping)
        before = runner.snapshot()
        try:
            runner.invoke(invoke, local_documents=local_documents)
        except ScientificStateError as exc:
            assert exc.code == expected["error_code"]
            expected_details = expected.get("error_details", {})
            assert isinstance(expected_details, Mapping)
            assert all(exc.details.get(key) == value for key, value in expected_details.items())
            rejected += 1
        else:
            raise AssertionError("transition negative case was accepted")
        after = runner.snapshot()
        deltas = {
            key: after[key] - before[key]
            for key in before
        }
        expected_deltas = expected.get("deltas")
        assert isinstance(expected_deltas, Mapping)
        assert deltas == expected_deltas
        event_delta_zero += int(
            all(
                deltas[key] == 0
                for key in (
                    "canonical_events",
                    "generation_events",
                    "baseline_events",
                    "registration_events",
                )
            )
        )
        budget_delta_zero += int(
            deltas["budget_attempts"] == 0 and deltas["budget_retries"] == 0
        )
        paths = invoke.get("paths", [])
        resolved_paths = resolver.resolve_value(paths)
        assert isinstance(resolved_paths, list)
        if resolved_paths:
            payload = runner.last_registration_payload
            assert payload is not None
            for path_index, path in enumerate(resolved_paths):
                assert isinstance(path, str)
                code = _direct_rejection_code(
                    path,
                    runner.events,
                    payload,
                    tmp_path / f"direct-{ordinal}-{path_index}",
                )
                direct_matches += int(code == expected["error_code"])
    assert baseline_deriver.baseline_service_calls == 1
    assert resolver.control_observer_calls.get(
        "service.current_baseline_validation"
    )
    assert resolver.control_observer_calls.get("reduce_scientific_state")
    return {
        "cases": len(cases),
        "case_rejections": rejected,
        "direct_replay_path_matches": direct_matches,
        "event_delta_zero_cases": event_delta_zero,
        "budget_delta_zero_cases": budget_delta_zero,
        "case_id_dispatches": case_id_dispatches,
    }


def _registry(tmp_path: Path) -> OperationRegistry:
    registry = OperationRegistry()
    registry.register("verify_fixture_integrity", _observe_fixture_integrity)
    registry.register("parse_v2_contract", _observe_v2_contract)
    registry.register(
        "verify_legacy_parity",
        lambda inputs: _observe_legacy_parity(inputs, tmp_path),
    )
    registry.register("parse_proposal", _observe_proposal)
    registry.register("parse_proposal_generated_text", _observe_generated_proposal)
    registry.register("parse_proposal_negative_matrix", _observe_proposal_negatives)
    registry.register("derive_scope_bound_ids", _observe_scope_ids)
    registry.register(
        "execute_transition_negative_matrix",
        lambda inputs: _observe_transition_negatives(inputs, tmp_path),
    )
    registry.register(
        "seal_scope_baselines",
        lambda inputs: _observe_scope_baselines(inputs, tmp_path),
    )
    registry.register(
        "run_typed_proposal",
        lambda inputs: _observe_typed_proposal(inputs, tmp_path),
    )
    registry.register(
        "run_typed_replication",
        lambda inputs: _observe_typed_replication(inputs, tmp_path),
    )
    registry.register(
        "retry_typed_proposal",
        lambda inputs: _observe_typed_proposal_retry(inputs, tmp_path),
    )
    registry.register(
        "retry_typed_replication",
        lambda inputs: _observe_typed_replication_retry(inputs, tmp_path),
    )
    registry.register(
        "inspect_adapter_requests",
        lambda inputs: _observe_adapter_requests(inputs, tmp_path),
    )
    registry.register(
        "compare_proposal_state_paths",
        lambda inputs: _observe_state_path_parity(inputs, tmp_path),
    )
    registry.register(
        "race_scope_registration",
        lambda inputs: _observe_scope_registration_race(inputs, tmp_path),
    )
    registry.register(
        "inspect_authority_surfaces",
        lambda inputs: _observe_authority_surfaces(inputs, tmp_path),
    )
    registry.register("verify_regression_floor", _observe_regression_floor)
    return registry


@pytest.mark.parametrize("manifest_case_id", _CASE_IDS, ids=_CASE_IDS)
def test_every_manifest_case_has_an_operation_only_expectation_binding(
    manifest_case_id: str,
    tmp_path: Path,
) -> None:
    case = _CASES_BY_ID[manifest_case_id]
    expected = case["expected"]
    assert isinstance(expected, dict)
    observed = _registry(tmp_path).observe(case)
    assert observed == expected


def test_manifest_and_all_linked_fixture_bytes_are_strict_and_frozen() -> None:
    manifest_path = FIXTURE_ROOT / "manifest.json"
    assert sha256_bytes(manifest_path.read_bytes()) == MANIFEST_RAW_SHA256
    assert sorted_compact_digest(_MANIFEST) == MANIFEST_SORTED_COMPACT_DIGEST
    assert len(_MANIFEST_CASES) == 20
    assert len(set(_CASE_IDS)) == 20
    assert _observe_fixture_integrity({}) == _CASES_BY_ID["fixture-integrity"]["expected"]


def test_strict_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    malformed = tmp_path / "duplicate.json"
    malformed.write_text('{"case":1,"case":2}\n', encoding="utf-8")
    with pytest.raises(DuplicateKeyError):
        strict_load_json(malformed)


def test_operation_registry_never_receives_case_id() -> None:
    received: list[Mapping[str, object]] = []
    registry = OperationRegistry()
    registry.register("probe", lambda inputs: received.append(inputs) or {"ok": True})
    observed = registry.observe(
        {"id": "must-remain-display-only", "operation": "probe", "input": {"x": 1}}
    )
    assert observed == {"ok": True}
    assert received == [{"x": 1}]


class _ServiceBaselineDeriver:
    """Obtain a baseline payload from the real service in an isolated project."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._service: ResearchService | None = None
        self._payload: dict[str, object] | None = None
        self.baseline_service_calls = 0

    @property
    def control_handlers(self):  # type: ignore[no-untyped-def]
        return {
            "service.current_baseline_validation": self.validate_current_baseline,
            "reduce_scientific_state": self.validate_legacy_registration,
        }

    def _prepare_project(self) -> ResearchService:
        if self._service is not None:
            return self._service
        project = self.root / "project"
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "examples" / "toy_optimization",
            project,
        )
        runtime = project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        control = project / ".research-os"
        project_toml = control / "project.toml"
        project_text = project_toml.read_text(encoding="utf-8")
        project_text = project_text.replace(
            'id = "toy-optimization"',
            f'id = "{_fixtures()["project_id"]}"',
        )
        project_toml.write_text(project_text, encoding="utf-8")
        constitution = control / "constitution.toml"
        constitution_text = constitution.read_text(encoding="utf-8").replace(
            "repeats = 2",
            "repeats = 1",
        )
        constitution.write_text(constitution_text, encoding="utf-8")
        adapter = control / "adapter.py"
        adapter_text = adapter.read_text(encoding="utf-8")
        capability_source = 'payload={"capabilities": sorted(OPERATIONS), "side_effects": []},'
        capability_target = (
            'payload={"capabilities": sorted(OPERATIONS | {"evaluation_scope_v1"}), '
            '"side_effects": []},'
        )
        assert capability_source in adapter_text
        adapter.write_text(
            adapter_text.replace(capability_source, capability_target),
            encoding="utf-8",
        )
        (control / "research-brief.md").write_text(
            RESEARCH_BRIEF_TEMPLATE.replace(
                "REPLACE_ME",
                "Configured frozen M1-C isolated baseline derivation",
            ),
            encoding="utf-8",
        )
        (control / "candidate.schema.json").write_bytes(
            (FIXTURE_ROOT / "m1c-candidate-schema.json").read_bytes()
        )
        service = ResearchService(project)
        report = service.doctor()
        contract = StudyContract.from_mapping(
            _object(FIXTURE_ROOT / "m1c-contract.json")
        )
        plan = plan_generation_open(
            service.event_log.read(),
            project_id=str(_fixtures()["project_id"]),
            contract=contract,
            evaluation_seal=_evaluation_seal(),
        )
        service.event_log.append(plan.event_type, plan.payload)
        service.projection.sync(service.event_log)

        def frozen_seal(_: ResearchService, __: DoctorReport) -> EvaluationSeal:
            return _evaluation_seal()

        service._evaluation_seal_from_report = MethodType(  # type: ignore[method-assign]
            frozen_seal,
            service,
        )
        assert EVALUATION_SCOPE_CAPABILITY in report.capabilities
        self._service = service
        return service

    def __call__(self, arguments: Mapping[str, object]) -> dict[str, object]:
        scope_id = arguments.get("evaluation_scope_id")
        persist = arguments.get("persist")
        if not isinstance(scope_id, str) or persist is not False:
            raise ValueError(
                "service.baseline_event_payload requires a scope and persist=false"
            )
        if self._payload is not None:
            return {"payload": copy.deepcopy(self._payload)}
        service = self._prepare_project()
        captured: dict[str, object] = {}

        def capture_without_persist(
            _: ResearchService,
            payload: Mapping[str, object],
        ) -> object:
            captured.update(copy.deepcopy(dict(payload)))
            return SimpleNamespace(sequence=0)

        service._append_scoped_baseline_event = MethodType(  # type: ignore[method-assign]
            capture_without_persist,
            service,
        )
        before = tuple(service.event_log.read())
        service.baseline(evaluation_scope_id=scope_id)
        after = tuple(service.event_log.read())
        assert before == after
        assert captured
        self.baseline_service_calls += 1
        self._payload = captured
        return {"payload": copy.deepcopy(captured)}

    def validate_current_baseline(self, document: object) -> Mapping[str, object]:
        if not isinstance(document, Mapping):
            raise TypeError("baseline control document must be an object")
        service = self._prepare_project()
        state = reduce_scientific_state(
            service.event_log.read(),
            project_id=str(_fixtures()["project_id"]),
        )
        assert state.contract is not None
        scope_id = document.get("evaluation_scope_id")
        scope = next(
            item for item in state.contract.evaluation_scopes if item.id == scope_id
        )
        compatibility = document.get("compatibility_digest")
        assert isinstance(compatibility, str)
        validated = service._validate_baseline_payload(
            document,
            compatibility,
            generation_id=state.active_generation_id,
            study_contract_digest=state.study_contract_digest,
            evaluation_seal_digest=state.evaluation_seal_digest,
            evaluation_scope=scope.to_dict(),
        )
        return {
            "accepted": True,
            "trusted": validated.get("digest") == document.get("digest"),
        }

    @staticmethod
    def validate_legacy_registration(document: object) -> Mapping[str, object]:
        if not isinstance(document, Mapping):
            raise TypeError("registration control document must be an object")
        state = reduce_scientific_state(
            [_event_mapping("EXPERIMENT_REGISTERED", document)],
            project_id=str(_fixtures()["project_id"]),
        )
        return {
            "accepted": True,
            "legacy_unstructured_registrations": (
                state.legacy_unstructured_registrations
            ),
            "active_generation_id": state.active_generation_id,
        }


def _fixture_service_sha256_json(value: object) -> str:
    """Bind the synthetic compatibility fixture at the one external hash seam."""

    if isinstance(value, Mapping) and set(value) == {"project", "adapter"}:
        return str(_fixtures()["evaluation_seal"]["compatibility_digest"])  # type: ignore[index]
    return sha256_json(value)


def _fixture_evaluation_seal(
    _: ResearchService,
    __: DoctorReport,
) -> EvaluationSeal:
    return _evaluation_seal()


class _M1CServiceProject:
    """One real service/adapter project bound to the frozen synthetic seal."""

    def __init__(self, root: Path, *, open_generation: bool = True) -> None:
        self.project = root / "project"
        shutil.copytree(
            Path(__file__).resolve().parents[1] / "examples" / "toy_optimization",
            self.project,
        )
        runtime = self.project / ".research-os" / "runtime"
        if runtime.exists():
            shutil.rmtree(runtime)
        self.control = self.project / ".research-os"
        self._configure_project()
        self.capture_path = runtime / "m1c-adapter-requests.jsonl"
        self.candidate_path = self.control / "candidate.inbox.json"
        self.candidate_path.write_text('{"x":2.0,"y":1.0}\n', encoding="utf-8")
        self.proposal_explore_path = self.control / "proposal-explore.json"
        self.proposal_explore_path.write_bytes(
            (FIXTURE_ROOT / "m1c-proposal-explore.json").read_bytes()
        )
        self.proposal_replicate_path = self.control / "proposal-replicate.json"
        self.proposal_replicate_path.write_bytes(
            (FIXTURE_ROOT / "m1c-proposal-replicate.json").read_bytes()
        )
        self.service = ResearchService(self.project)
        if open_generation:
            self.open_generation()

    def open_generation(self) -> dict[str, object]:
        opened = self.service.open_generation(
            _object(FIXTURE_ROOT / "m1c-contract.json")
        )
        assert opened["generation_id"] == _fixtures()["generation_id"]
        return opened

    def _configure_project(self) -> None:
        project_toml = self.control / "project.toml"
        project_toml.write_text(
            project_toml.read_text(encoding="utf-8").replace(
                'id = "toy-optimization"',
                f'id = "{_fixtures()["project_id"]}"',
            ),
            encoding="utf-8",
        )
        constitution = self.control / "constitution.toml"
        constitution.write_text(
            constitution.read_text(encoding="utf-8").replace(
                "repeats = 2",
                "repeats = 1",
            ),
            encoding="utf-8",
        )
        adapter = self.control / "adapter.py"
        adapter_source = adapter.read_text(encoding="utf-8")
        capability_source = 'payload={"capabilities": sorted(OPERATIONS), "side_effects": []},'
        capability_target = (
            'payload={"capabilities": sorted(OPERATIONS | {"evaluation_scope_v1"}), '
            '"side_effects": []},'
        )
        capture_source = "        payload = request.get(\"payload\") or {}\n"
        capture_target = capture_source + (
            "        capture = project / \".research-os/runtime/"
            "m1c-adapter-requests.jsonl\"\n"
            "        with capture.open(\"a\", encoding=\"utf-8\") as stream:\n"
            "            stream.write(json.dumps(request, sort_keys=True, "
            "separators=(\",\", \":\")) + \"\\n\")\n"
        )
        assert capability_source in adapter_source
        assert capture_source in adapter_source
        adapter.write_text(
            adapter_source.replace(capability_source, capability_target).replace(
                capture_source,
                capture_target,
            ),
            encoding="utf-8",
        )
        (self.control / "research-brief.md").write_text(
            RESEARCH_BRIEF_TEMPLATE.replace(
                "REPLACE_ME",
                "Configured frozen M1-C positive lifecycle observer",
            ),
            encoding="utf-8",
        )
        (self.control / "candidate.schema.json").write_bytes(
            (FIXTURE_ROOT / "m1c-candidate-schema.json").read_bytes()
        )

    def new_service(self) -> ResearchService:
        return ResearchService(self.project)

    def clear_requests(self) -> None:
        self.capture_path.parent.mkdir(parents=True, exist_ok=True)
        self.capture_path.write_text("", encoding="utf-8")

    def requests(self) -> list[dict[str, object]]:
        if not self.capture_path.exists() or not self.capture_path.read_bytes():
            return []
        values = strict_load_json_lines(self.capture_path)
        assert all(isinstance(value, dict) for value in values)
        return [value for value in values if isinstance(value, dict)]

    def events(self, event_type: str) -> list[object]:
        return [
            event
            for event in self.service.event_log.read()
            if event.event_type == event_type
        ]

    def registration(self, experiment_id: str) -> Mapping[str, object]:
        for event in self.service.event_log.read():
            if (
                event.event_type == "EXPERIMENT_REGISTERED"
                and event.payload.get("experiment_id") == experiment_id
            ):
                return event.payload
        raise AssertionError(f"registration is absent: {experiment_id}")

    def science_state(self) -> ScientificState:
        return reduce_scientific_state(
            self.service.event_log.read(),
            project_id=str(_fixtures()["project_id"]),
        )


@contextmanager
def _m1c_service_project(  # type: ignore[no-untyped-def]
    root: Path,
    *,
    open_generation: bool = True,
):
    with (
        mock.patch(
            "research_os.service.sha256_json",
            side_effect=_fixture_service_sha256_json,
        ),
        mock.patch.object(
            ResearchService,
            "_evaluation_seal_from_report",
            new=_fixture_evaluation_seal,
        ),
    ):
        yield _M1CServiceProject(root, open_generation=open_generation)


def _proposal_fixture_path(inputs: Mapping[str, object]) -> Path:
    name = inputs.get("proposal")
    if not isinstance(name, str):
        raise TypeError("positive lifecycle observer requires a Proposal fixture")
    path = FIXTURE_ROOT / name
    if path.parent != FIXTURE_ROOT or not path.is_file():
        raise ValueError("Proposal fixture must be a direct frozen v2 fixture")
    return path


def _write_candidate(
    project: _M1CServiceProject,
    inputs: Mapping[str, object],
) -> Mapping[str, object]:
    candidate = inputs.get("candidate")
    if not isinstance(candidate, Mapping):
        raise TypeError("positive lifecycle observer requires a candidate object")
    project.candidate_path.write_text(
        canonical_json(candidate) + "\n",
        encoding="utf-8",
    )
    return candidate


def _registration_events(service: ResearchService) -> list[Mapping[str, object]]:
    return [
        event.payload
        for event in service.event_log.read()
        if event.event_type == "EXPERIMENT_REGISTERED"
    ]


def _terminal_events(service: ResearchService) -> list[Mapping[str, object]]:
    return [
        event.payload
        for event in service.event_log.read()
        if event.event_type == "EXPERIMENT_TERMINATED"
    ]


def _seed_explore(project: _M1CServiceProject) -> dict[str, object]:
    project.service.baseline(evaluation_scope_id="development")
    return project.service.run_once(
        project.candidate_path,
        proposal=project.proposal_explore_path,
    )


def _observe_scope_baselines(
    inputs: Mapping[str, object],
    tmp_path: Path,
) -> dict[str, object]:
    scopes = inputs.get("scope_ids")
    repetitions = inputs.get("repetitions")
    if (
        not isinstance(scopes, list)
        or not scopes
        or not all(isinstance(scope, str) for scope in scopes)
        or isinstance(repetitions, bool)
        or not isinstance(repetitions, int)
    ):
        raise TypeError("scope baseline observer requires scope IDs and repetitions")

    with _m1c_service_project(
        tmp_path / "unscoped-control",
        open_generation=False,
    ) as control:
        control.clear_requests()
        unscoped_result = control.service.baseline()
        unscoped_events = [
            event.payload
            for event in control.service.event_log.read()
            if event.event_type == "BASELINE_RECORDED"
        ]
        assert len(unscoped_events) == 1
        assert "evaluation_scope_id" not in unscoped_result
        control.open_generation()
        before_bytes = control.service.event_log.path.read_bytes()
        before_baselines = len(unscoped_events)
        typed_authorized = True
        try:
            control.service.run_once(
                control.candidate_path,
                proposal=control.proposal_explore_path,
            )
        except ScientificStateError as exc:
            assert exc.code == "STUDY_SCOPE_BASELINE_REQUIRED"
            typed_authorized = False
        after_events = control.service.event_log.read()
        after_baselines = sum(
            event.event_type == "BASELINE_RECORDED" for event in after_events
        )
        assert control.service.event_log.path.read_bytes() == before_bytes

    with _m1c_service_project(tmp_path / "scoped-baselines") as project:
        project.clear_requests()
        results = [
            project.service.baseline(evaluation_scope_id=scope)
            for scope in scopes
        ]
        assert all(result["repetitions"] == repetitions for result in results)
        baseline_events = [
            event.payload
            for event in project.service.event_log.read()
            if event.event_type == "BASELINE_RECORDED"
        ]
        requests = project.requests()
        scoped_baseline_requests = [
            request
            for request in requests
            if request.get("operation") == Operation.BASELINE.value
            and isinstance(request.get("payload"), Mapping)
            and "evaluation_scope" in request["payload"]  # type: ignore[operator]
        ]
        scoped_verify_requests = [
            request
            for request in requests
            if request.get("operation") == Operation.VERIFY.value
            and isinstance(request.get("payload"), Mapping)
            and "evaluation_scope" in request["payload"]  # type: ignore[operator]
        ]
        scope_fields = [key for key in results[0] if key not in unscoped_result]
        scope_bindings = [
            {key: copy.deepcopy(payload[key]) for key in scope_fields}
            for payload in baseline_events
        ]

    return {
        "baseline_events": len(baseline_events),
        "development_workspace_id": scoped_baseline_requests[0]["experiment_id"],
        "replication_workspace_id": scoped_baseline_requests[1]["experiment_id"],
        "scope_bound_baseline_calls": len(scoped_baseline_requests),
        "scope_bound_verify_calls": len(scoped_verify_requests),
        "unscoped_baseline_authorizes_typed_run": typed_authorized,
        "typed_run_auto_creates_baseline": after_baselines > before_baselines,
        "baseline_event_scope_fields": scope_fields,
        "baseline_event_scope_bindings": scope_bindings,
    }


def _observe_typed_proposal(
    inputs: Mapping[str, object],
    tmp_path: Path,
) -> dict[str, object]:
    with _m1c_service_project(tmp_path / "typed-proposal") as project:
        candidate = _write_candidate(project, inputs)
        proposal_path = _proposal_fixture_path(inputs)
        project.service.baseline(evaluation_scope_id="development")
        before = project.science_state()
        result = project.service.run_once(
            project.candidate_path,
            proposal=proposal_path,
        )
        after = project.science_state()
        registration = project.registration(str(result["experiment_id"]))
        typed_siblings = sorted(
            key
            for key in registration
            if key == "evaluation_scope_id" or key.startswith("proposal")
        )
        typed_candidate_keys = {
            "evaluation_scope_id",
            "proposal",
            "proposal_digest",
            "proposal_id",
        }
        proposal_only_events = sum(
            "PROPOSAL" in event.event_type.upper()
            for event in project.service.event_log.read()
        )

    return {
        "experiment_id": result["experiment_id"],
        "proposal_id": registration["proposal_id"],
        "evaluation_scope_id": registration["evaluation_scope_id"],
        "attempt": registration["attempt"],
        "retry_of": registration["retry_of"],
        "registration_events": len(_registration_events(project.service)),
        "proposal_only_events": proposal_only_events,
        "typed_sibling_keys": typed_siblings,
        "registration_payload_keys": sorted(registration),
        "typed_sibling_bundle_complete": typed_candidate_keys.issubset(registration),
        "typed_keys_in_candidate": len(typed_candidate_keys.intersection(candidate)),
        "budget_attempt_delta": after.attempts_used - before.attempts_used,
    }


def _observe_typed_replication(
    inputs: Mapping[str, object],
    tmp_path: Path,
) -> dict[str, object]:
    with _m1c_service_project(tmp_path / "typed-replication") as project:
        _write_candidate(project, inputs)
        root = _seed_explore(project)
        root_registration = project.registration(str(root["experiment_id"]))
        project.service.baseline(evaluation_scope_id="replication-1")
        result = project.service.run_once(
            project.candidate_path,
            proposal=_proposal_fixture_path(inputs),
        )
        registration = project.registration(str(result["experiment_id"]))
        state = project.science_state()

    return {
        "experiment_id": result["experiment_id"],
        "proposal_id": registration["proposal_id"],
        "candidate_digest_equal_to_parent": (
            registration["candidate_digest"] == root_registration["candidate_digest"]
        ),
        "evaluation_scope_id": registration["evaluation_scope_id"],
        "evaluation_scope_changed": (
            registration["evaluation_scope_id"]
            != root_registration["evaluation_scope_id"]
        ),
        "attempt": registration["attempt"],
        "retry_of": registration["retry_of"],
        "replication_count": state.replication_count,
    }


def _observe_typed_proposal_retry(
    inputs: Mapping[str, object],
    tmp_path: Path,
) -> dict[str, object]:
    retry_of = inputs.get("retry_of")
    if not isinstance(retry_of, str):
        raise TypeError("typed retry observer requires retry_of")
    with _m1c_service_project(tmp_path / "proposal-retry") as project:
        project.service.baseline(evaluation_scope_id="development")
        original_call = project.service._call_sealed
        failed = False

        def fail_first_run(report, operation, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal failed
            if operation is Operation.RUN and not failed:
                failed = True
                return ProtocolResponse.failure(
                    request_id="req_m1c_manifest_proposal_retry",
                    error={
                        "category": "INFRASTRUCTURE",
                        "code": "TRANSIENT_M1C_MANIFEST_FAILURE",
                        "message": "injected retryable Proposal execution failure",
                    },
                    retryable=True,
                )
            return original_call(report, operation, **kwargs)

        with mock.patch.object(
            project.service,
            "_call_sealed",
            side_effect=fail_first_run,
        ):
            first = project.service.run_once(
                project.candidate_path,
                proposal=project.proposal_explore_path,
            )
        assert first["experiment_id"] == retry_of
        assert first["retryable"] is True
        result = project.service.run_once(
            project.candidate_path,
            retry_of=retry_of,
        )
        registration = project.registration(str(result["experiment_id"]))
        state = project.science_state()

    return {
        "experiment_id": result["experiment_id"],
        "proposal_id": registration["proposal_id"],
        "evaluation_scope_id": registration["evaluation_scope_id"],
        "attempt": registration["attempt"],
        "proposal_unique_count": state.proposal_count,
        "replication_count": state.replication_count,
    }


def _observe_typed_replication_retry(
    inputs: Mapping[str, object],
    tmp_path: Path,
) -> dict[str, object]:
    retry_of = inputs.get("retry_of")
    terminal_status = inputs.get("terminal_status")
    retryable = inputs.get("retryable")
    if not isinstance(retry_of, str) or not isinstance(terminal_status, str):
        raise TypeError("replication retry observer requires retry identity and status")
    if not isinstance(retryable, bool):
        raise TypeError("replication retry observer requires retryable boolean")
    with _m1c_service_project(tmp_path / "replication-retry") as project:
        _seed_explore(project)
        project.service.baseline(evaluation_scope_id="replication-1")
        original_call = project.service._call_sealed
        failed = False

        def time_out_first_run(report, operation, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal failed
            if operation is Operation.RUN and not failed:
                failed = True
                raise TimeoutError("injected replication timeout")
            return original_call(report, operation, **kwargs)

        with mock.patch.object(
            project.service,
            "_call_sealed",
            side_effect=time_out_first_run,
        ):
            first = project.service.run_once(
                project.candidate_path,
                proposal=project.proposal_replicate_path,
            )
        assert first["experiment_id"] == retry_of
        assert first["status"] == terminal_status
        assert first["retryable"] is retryable
        before = project.science_state()
        result = project.service.run_once(
            project.candidate_path,
            retry_of=retry_of,
        )
        registration = project.registration(str(result["experiment_id"]))
        after = project.science_state()

    return {
        "experiment_id": result["experiment_id"],
        "proposal_id": registration["proposal_id"],
        "evaluation_scope_id": registration["evaluation_scope_id"],
        "attempt": registration["attempt"],
        "proposal_unique_count": after.proposal_count,
        "replication_count": after.replication_count,
        "used_candidate_scope_pairs": after.used_candidate_scope_pairs,
        "budget_attempt_delta": after.attempts_used - before.attempts_used,
        "budget_retry_delta": after.retries_used - before.retries_used,
    }


def _observe_adapter_requests(
    inputs: Mapping[str, object],
    tmp_path: Path,
) -> dict[str, object]:
    with _m1c_service_project(tmp_path / "adapter-requests") as project:
        _write_candidate(project, inputs)
        project.service.baseline(evaluation_scope_id="development")
        project.clear_requests()
        result = project.service.run_once(
            project.candidate_path,
            proposal=_proposal_fixture_path(inputs),
        )
        candidate_requests = [
            request
            for request in project.requests()
            if request.get("experiment_id") == result["experiment_id"]
            and request.get("operation")
            in {
                Operation.MATERIALIZE.value,
                Operation.RUN.value,
                Operation.EVALUATE.value,
                Operation.VERIFY.value,
            }
        ]
        assert len(candidate_requests) == 4
        materialize = candidate_requests[0]["payload"]
        assert isinstance(materialize, Mapping)
        candidate = materialize["candidate"]
        assert isinstance(candidate, Mapping)
        scopes = [
            request["payload"]["evaluation_scope"]  # type: ignore[index]
            for request in candidate_requests
        ]
        assert all(scope == scopes[0] for scope in scopes)
        orchestration_keys = {
            "proposal",
            "proposal_digest",
            "proposal_id",
            "evaluation_scope_id",
            "graph_action",
            "scientific_change",
        }

    return {
        "candidate_keys": sorted(candidate),
        "proposal_keys_in_candidate": len(orchestration_keys.intersection(candidate)),
        "scope_bound_candidate_operations": [
            request["operation"] for request in candidate_requests
        ],
        "evaluation_scope": scopes[0],
    }


def _science_signature(value: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value[key]
        for key in (
            "proposal_count",
            "replication_count",
            "used_candidate_scope_pairs",
            "active_generation_id",
        )
    }


def _observe_state_path_parity(
    inputs: Mapping[str, object],
    tmp_path: Path,
) -> dict[str, object]:
    sequence = inputs.get("sequence")
    if sequence != ["explore", "replicate"]:
        raise ValueError("state parity observer requires explore then replicate")
    with _m1c_service_project(tmp_path / "state-parity") as project:
        _seed_explore(project)
        project.service.baseline(evaluation_scope_id="replication-1")
        project.service.run_once(
            project.candidate_path,
            proposal=project.proposal_replicate_path,
        )
        live = dict(project.service.study_status())
        live.pop("project_id")
        live.pop("authorized_action")
        events = project.service.event_log.read()
        cold = reduce_scientific_state(
            events,
            project_id=str(_fixtures()["project_id"]),
        ).to_dict()
        rebuilt_states: list[dict[str, object]] = []
        real_reduce = reduce_scientific_state

        def capture_rebuild(events, *, project_id):  # type: ignore[no-untyped-def]
            state = real_reduce(events, project_id=project_id)
            rebuilt_states.append(state.to_dict())
            return state

        rebuilt_projection = ProjectionStore(tmp_path / "rebuilt-state.db")
        with mock.patch(
            "research_os.science.state.reduce_scientific_state",
            side_effect=capture_rebuild,
        ):
            rebuilt_projection.rebuild(project.service.event_log)
        assert rebuilt_states
        assert len(rebuilt_projection.lineage(str(_fixtures()["project_id"]))) == 2
        rebuilt = rebuilt_states[-1]
        replayed = project.service.replay()["science"]
        assert isinstance(replayed, Mapping)
        signatures = [
            _science_signature(value)
            for value in (live, cold, rebuilt, replayed)
        ]

    return {
        "paths_equal": sum(value == signatures[0] for value in signatures),
        **signatures[0],
    }


def _observe_scope_registration_race(
    inputs: Mapping[str, object],
    tmp_path: Path,
) -> dict[str, object]:
    workers = inputs.get("workers")
    scope_id = inputs.get("scope_id")
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 2:
        raise TypeError("race observer requires at least two workers")
    if not isinstance(scope_id, str):
        raise TypeError("race observer requires a scope ID")
    with _m1c_service_project(tmp_path / "scope-race") as project:
        _seed_explore(project)
        project.service.baseline(evaluation_scope_id=scope_id)
        before = project.science_state()
        registrations_before = len(_registration_events(project.service))
        terminals_before = len(_terminal_events(project.service))
        project.clear_requests()
        barrier = Barrier(workers)
        original_append = ResearchService._append_registration_event

        @contextmanager
        def unlocked(_: ResearchService):
            yield

        def synchronized_append(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            barrier.wait(timeout=20)
            return original_append(self, *args, **kwargs)

        contenders = [project.new_service() for _ in range(workers)]

        def run(contender: ResearchService) -> dict[str, object] | ScientificStateError:
            try:
                return contender.run_once(
                    project.candidate_path,
                    proposal=project.proposal_replicate_path,
                )
            except ScientificStateError as exc:
                return exc

        with (
            mock.patch.object(ResearchService, "_workflow_lock", new=unlocked),
            mock.patch.object(
                ResearchService,
                "_append_registration_event",
                new=synchronized_append,
            ),
            ThreadPoolExecutor(max_workers=workers) as pool,
        ):
            outcomes = list(pool.map(run, contenders))

        winners = [value for value in outcomes if isinstance(value, Mapping)]
        rejections = [
            value for value in outcomes if isinstance(value, ScientificStateError)
        ]
        after = project.science_state()
        registrations_after = len(_registration_events(project.service))
        terminals_after = len(_terminal_events(project.service))
        stage_operations = [
            request.get("operation")
            for request in project.requests()
            if request.get("operation")
            in {
                Operation.MATERIALIZE.value,
                Operation.RUN.value,
                Operation.EVALUATE.value,
                Operation.VERIFY.value,
            }
        ]
        cleanup_calls = sum(
            request.get("operation") == Operation.CLEANUP.value
            for request in project.requests()
        )
        workspace_root = project.control / "runtime" / "workspaces"
        remaining_workspaces = list(workspace_root.iterdir()) if workspace_root.exists() else []

        assert len(winners) == 1
        assert len(rejections) == workers - 1
        assert terminals_after - terminals_before == 1
        assert stage_operations == [
            Operation.MATERIALIZE.value,
            Operation.RUN.value,
            Operation.EVALUATE.value,
            Operation.VERIFY.value,
        ]
        assert cleanup_calls == 1
        assert remaining_workspaces == []

    return {
        "winner_count": len(winners),
        "rejection_count": len(rejections),
        "rejection_code": rejections[0].code,
        "registration_event_delta": registrations_after - registrations_before,
        "budget_attempt_delta": after.attempts_used - before.attempts_used,
    }


def _cli_json(arguments: list[str]) -> dict[str, object]:
    output = io.StringIO()
    with redirect_stdout(output):
        code = cli_main(arguments)
    assert code == 0
    value = json.loads(output.getvalue())
    assert isinstance(value, dict)
    return value


def _authorized_action_values(value: object) -> list[object]:
    if isinstance(value, Mapping):
        values = [value["authorized_action"]] if "authorized_action" in value else []
        for item in value.values():
            values.extend(_authorized_action_values(item))
        return values
    if isinstance(value, list):
        values = []
        for item in value:
            values.extend(_authorized_action_values(item))
        return values
    return []


def _observe_authority_surfaces(
    inputs: Mapping[str, object],
    tmp_path: Path,
) -> dict[str, object]:
    declared_surfaces = inputs.get("surfaces")
    if not isinstance(declared_surfaces, list) or not all(
        isinstance(surface, str) for surface in declared_surfaces
    ):
        raise TypeError("authority observer requires named surfaces")
    with _m1c_service_project(tmp_path / "authority-surfaces") as project:
        proposal_input = Proposal.from_mapping(
            _object(FIXTURE_ROOT / "m1c-proposal-explore.json")
        ).to_dict()
        baseline_service = project.service.baseline(
            evaluation_scope_id="development"
        )
        baseline_cli = _cli_json(
            [
                "--project",
                str(project.project),
                "baseline",
                "--evaluation-scope-id",
                "development",
            ]
        )
        run_service = project.service.run_once(
            project.candidate_path,
            proposal=project.proposal_explore_path,
        )
        registration = project.registration(str(run_service["experiment_id"]))
        project.service.baseline(evaluation_scope_id="replication-1")
        run_cli = _cli_json(
            [
                "--project",
                str(project.project),
                "run-once",
                str(project.candidate_path),
                "--proposal",
                str(project.proposal_replicate_path),
            ]
        )
        study_status_cli = _cli_json(
            ["--project", str(project.project), "study-status"]
        )
        replay_cli = _cli_json(["--project", str(project.project), "replay"])
        observed_surfaces: dict[str, Mapping[str, object]] = {
            "proposal_input": proposal_input,
            "proposal_registration": registration["proposal"],  # type: ignore[dict-item]
            "experiment_registration": registration,
            "baseline_service_result": baseline_service,
            "baseline_cli_json": baseline_cli,
            "run_once_service_result": run_service,
            "run_once_cli_json": run_cli,
            "study_status_cli_json": study_status_cli,
            "replay_cli_json": replay_cli,
        }
        assert set(observed_surfaces) == set(declared_surfaces)
        surfaces = [observed_surfaces[name] for name in declared_surfaces]
        recursive_values = [
            item
            for surface in surfaces
            for item in _authorized_action_values(surface)
        ]

    return {
        "surface_count": len(surfaces),
        "top_level_authorized_action_key_count": sum(
            "authorized_action" in surface for surface in surfaces
        ),
        "top_level_authorized_action_non_null_count": sum(
            surface.get("authorized_action") is not None for surface in surfaces
        ),
        "recursive_authorized_action_non_null_count": sum(
            value is not None for value in recursive_values
        ),
    }


_REGRESSION_OBSERVATION: dict[str, object] | None = None


def _completed(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )


def _regression_floor_from_approved_status() -> tuple[int, int]:
    status = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "research-os-status"
        / "03-2026-08-10-m1-c-typed-proposal-replication.md"
    ).read_text(encoding="utf-8")
    match = re.search(
        r"구현 전 기준선:.*?(\d+) passed, (\d+) subtests passed",
        status,
    )
    if match is None:
        raise AssertionError("approved pre-M1-C regression floor is absent")
    return int(match.group(1)), int(match.group(2))


def _observe_regression_floor(inputs: Mapping[str, object]) -> dict[str, object]:
    global _REGRESSION_OBSERVATION
    python = inputs.get("python")
    if python != f"{sys.version_info.major}.{sys.version_info.minor}":
        raise AssertionError("regression observer is running under the wrong Python")
    if _REGRESSION_OBSERVATION is not None:
        return copy.deepcopy(_REGRESSION_OBSERVATION)

    tests_floor, subtests_floor = _regression_floor_from_approved_status()
    pytest_run = _completed(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests",
            "--ignore=tests/test_m1c_manifest_oracle.py",
        ]
    )
    pytest_output = pytest_run.stdout + pytest_run.stderr
    tests_match = re.search(r"(?:^|\s)(\d+) passed", pytest_output)
    subtests_match = re.search(r"(\d+) subtests passed", pytest_output)
    assert pytest_run.returncode == 0, pytest_output
    assert tests_match is not None and subtests_match is not None, pytest_output
    assert int(tests_match.group(1)) >= tests_floor
    assert int(subtests_match.group(1)) >= subtests_floor

    ruff = _completed([sys.executable, "-m", "ruff", "check", "src", "tests"])
    ty = _completed(["uvx", "--offline", "ty", "check", "src"])
    diff = _completed(["git", "diff", "--check"])
    assert ruff.returncode == 0, ruff.stdout + ruff.stderr
    assert ty.returncode == 0, ty.stdout + ty.stderr
    assert diff.returncode == 0, diff.stdout + diff.stderr
    _REGRESSION_OBSERVATION = {
        "tests_minimum": tests_floor,
        "subtests_minimum": subtests_floor,
        "ruff": "PASS",
        "ty_src": "PASS",
        "diff_check": "PASS",
    }
    return copy.deepcopy(_REGRESSION_OBSERVATION)


def _recompute_digest(document: object, _: str) -> object:
    assert isinstance(document, dict)
    unsigned = copy.deepcopy(document)
    unsigned.pop("digest", None)
    document["digest"] = sha256_json(unsigned)
    return document


def test_transition_dsl_resolves_without_case_id_dispatch(tmp_path: Path) -> None:
    matrix = _object(FIXTURE_ROOT / "m1c-transition-negative-matrix.json")
    baseline_deriver = _ServiceBaselineDeriver(tmp_path / "baseline-derive")
    resolver = DocumentResolver(
        matrix,
        FIXTURE_ROOT,
        derive_handlers={"service.baseline_event_payload": baseline_deriver},
        recompute_handlers={"digest": _recompute_digest},
        control_handlers=baseline_deriver.control_handlers,
    )
    profiles = matrix["project_profiles"]
    scenarios = matrix["scenarios"]
    documents = matrix["documents"]
    cases = matrix["cases"]
    assert isinstance(profiles, Mapping)
    assert isinstance(scenarios, Mapping)
    assert isinstance(documents, Mapping)
    assert isinstance(cases, list)
    for name in profiles:
        resolver.profile(name)
    for name in scenarios:
        resolver.scenario(name)
    for name in documents:
        resolver.document(name)

    captures: dict[str, object] = {
        "root": {"experiment_id": str(_fixtures()["explore_experiment_id"])},
        "diagnostic-root": {"experiment_id": "exp_diagnostic_fixture"},
        "replication-1": {
            "experiment_id": str(_fixtures()["replication_1_experiment_id"])
        },
        "replication-2": {
            "experiment_id": str(_fixtures()["replication_2_experiment_id"])
        },
        "incompatible-parent": {
            "experiment_id": "exp_10ef269d91d8cd540bc2ddcb5c840672"
        },
    }
    for case in cases:
        assert isinstance(case, Mapping)
        local_documents = case.get("documents", {})
        assert isinstance(local_documents, Mapping)
        for name in local_documents:
            resolver.document(
                name,
                local_documents=local_documents,
                captures=captures,
            )
        resolver.resolve_value(
            case["invoke"],
            local_documents=local_documents,
            captures=captures,
        )
        resolver.resolve_value(case["expected"], captures=captures)

    direct = [case for case in cases if isinstance(case.get("invoke"), Mapping) and "paths" in case["invoke"]]
    assert len(cases) == 53
    assert len(direct) == 18
    assert sum(len(resolver.resolve_value(case["invoke"]["paths"])) for case in direct) == 72  # type: ignore[index,arg-type]
    assert baseline_deriver.baseline_service_calls == 1
    assert set(resolver.control_observer_calls) == {
        "reduce_scientific_state",
        "service.current_baseline_validation",
    }


def test_document_controls_run_on_unpatched_sources_and_never_enter_payloads(
    tmp_path: Path,
) -> None:
    matrix = _object(FIXTURE_ROOT / "m1c-transition-negative-matrix.json")
    baseline_deriver = _ServiceBaselineDeriver(tmp_path / "baseline-derive")
    resolver = DocumentResolver(
        matrix,
        FIXTURE_ROOT,
        derive_handlers={"service.baseline_event_payload": baseline_deriver},
        recompute_handlers={"digest": _recompute_digest},
        control_handlers=baseline_deriver.control_handlers,
    )

    unscoped = resolver.document("baseline-legacy-unscoped")
    legacy_registration = resolver.document("registration-legacy-no-generation")

    assert isinstance(unscoped, Mapping)
    assert "evaluation_scope" not in unscoped
    assert "evaluation_scope_id" not in unscoped
    assert isinstance(legacy_registration, Mapping)
    assert resolver.control_observer_calls == {
        "service.current_baseline_validation": 1,
        "reduce_scientific_state": 1,
    }
    assert baseline_deriver.baseline_service_calls == 1
    for document in (unscoped, legacy_registration):
        assert "control_assertions" not in document
        assert "observer" not in document
        assert "accepted" not in document
        assert "trusted" not in document


def test_all_manifest_binding_nodes_are_collected(request: pytest.FixtureRequest) -> None:
    expected = {
        "test_every_manifest_case_has_an_operation_only_expectation_binding"
        f"[{case_id}]"
        for case_id in _CASE_IDS
    }
    collected = {
        item.nodeid.rsplit("::", 1)[-1]
        for item in request.session.items
        if "test_every_manifest_case_has_an_operation_only_expectation_binding[" in item.nodeid
    }
    assert collected == expected


def test_no_manifest_or_matrix_case_id_is_used_as_observer_input() -> None:
    support_source = (
        Path(__file__).parent / "m1c_support" / "oracle.py"
    ).read_text(encoding="utf-8")
    module_source = Path(__file__).read_text(encoding="utf-8")
    transition_observer_source = module_source[
        module_source.index("def _observe_transition_negatives(") :
        module_source.index("\ndef _registry(")
    ]
    positive_observer_source = module_source[
        module_source.index("def _proposal_fixture_path(") :
        module_source.index("\ndef _recompute_digest(")
    ]
    source = support_source + transition_observer_source + positive_observer_source
    forbidden_patterns = (
        r"case\s*\[\s*[\"']id[\"']\s*\]",
        r"case\.get\(\s*[\"']id[\"']",
        r"startswith\(.*case",
    )
    assert not any(re.search(pattern, source) for pattern in forbidden_patterns)
    matrix = _object(FIXTURE_ROOT / "m1c-transition-negative-matrix.json")
    cases = matrix["cases"]
    assert isinstance(cases, list)
    display_ids = [case["id"] for case in cases if isinstance(case, Mapping)]
    assert len(display_ids) == len(cases)
    assert not any(str(display_id) in source for display_id in display_ids)
