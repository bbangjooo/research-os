"""Sealed synthetic meta-evaluation for the v0.5 release gate.

The generator and comparator are deterministic.  Acceptance custody is owned by
the release script: this module never creates a nonce and never writes a result.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, Literal, cast

from research_os.agent import build_agent_context, build_agent_context_v3
from research_os.contracts.common import canonical_json_bytes, sha256_json

GENERATOR_SCHEMA_VERSION: Final = 1
SUITE_SCHEMA_VERSION: Final = 1
RECEIPT_SCHEMA_VERSION: Final = 1
ARM_NAMES: Final = ("v0.2", "v0.5")
FORBIDDEN_SELECTOR_KEYS: Final = frozenset(
    {
        "hidden_world",
        "oracle_choices",
        "oracle_terminal",
        "minimum_attempts",
        "oracle_rank",
        "oracle_rank_if_visible",
    }
)
ACTION_PRIORITY: Final = {
    action: index
    for index, action in enumerate(
        (
            "test_mechanism",
            "replicate",
            "falsify",
            "resolve_gate",
            "repair_packet",
            "use_memory",
            "refresh_context",
            "resume",
            "stop_success",
            "stop_failure",
        )
    )
}
RACE_BOUNDARIES: Final = (
    {
        "boundary": "experiment_lookup_to_service",
        "pytest_node": "tests/test_m3c_crash_resume.py::test_m3c_lookup_to_append_race_fails_closed_without_controller_write[started-experiment-experiment_started_before_service-experiment_lookup_before_service-project]",
        "stable_code": "AUTONOMY_RECOVERY_STALE",
    },
    {
        "boundary": "disposition_lookup_to_append",
        "pytest_node": "tests/test_m3c_crash_resume.py::test_m3c_lookup_to_append_race_fails_closed_without_controller_write[terminal-disposition-project_terminal_before_disposition-disposition_lookup_before_append-program]",
        "stable_code": "AUTONOMY_RECOVERY_STALE",
    },
    {
        "boundary": "claim_lookup_to_append",
        "pytest_node": "tests/test_m3c_crash_resume.py::test_m3c_lookup_to_append_race_fails_closed_without_controller_write[captured-synthesis-synthesis_output_captured-claim_lookup_before_append-program]",
        "stable_code": "AUTONOMY_RECOVERY_STALE",
    },
)


class MetaEvaluationError(RuntimeError):
    """A benchmark contract, custody, or metric invariant failed."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MetaEvaluationError(message)


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MetaEvaluationError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_object(raw: bytes | str) -> dict[str, Any]:
    """Decode one finite JSON object with duplicate/non-finite rejection."""

    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda item: (_ for _ in ()).throw(
                MetaEvaluationError(f"non-finite number: {item}")
            ),
        )
    except (TypeError, ValueError) as exc:
        raise MetaEvaluationError(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise MetaEvaluationError("expected a JSON object")
    return cast(dict[str, Any], value)


def load_generator_manifest(path: Path) -> dict[str, Any]:
    value = strict_json_object(path.read_bytes())
    _require(value.get("schema_version") == GENERATOR_SCHEMA_VERSION, "wrong generator schema")
    suite = value.get("suite")
    families = value.get("families")
    if not isinstance(suite, Mapping):
        raise MetaEvaluationError("generator suite must be an object")
    if not isinstance(families, list):
        raise MetaEvaluationError("generator families must be an array")
    _require(suite.get("episode_count") == 36, "generator must fix 36 episodes")
    _require(suite.get("family_count") == 6, "generator must fix six families")
    _require(len(families) == 6, "generator must define six family rules")
    _require(
        all(isinstance(item, Mapping) and item.get("count") == 6 for item in families),
        "each generator family must fix six episodes",
    )
    return value


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _derive(nonce: str, manifest_sha: str, family: str, index: int, label: str) -> bytes:
    body = f"{nonce}|{manifest_sha}|{family}|{index}|{label}".encode()
    return hashlib.sha256(body).digest()


def _permutation(values: Sequence[str], seed: bytes) -> list[str]:
    decorated = []
    for index, value in enumerate(values):
        key = hashlib.sha256(seed + index.to_bytes(4, "big") + value.encode()).digest()
        decorated.append((key, value))
    return [value for _, value in sorted(decorated)]


def _candidate_id(seed: bytes, point: int, slot: int) -> str:
    digest = hashlib.sha256(seed + b"candidate" + bytes((point, slot))).hexdigest()[:24]
    return "candidate_" + digest


def _class_ids(seed: bytes) -> list[str]:
    return [
        "class_" + hashlib.sha256(seed + b"class" + bytes((slot,))).hexdigest()[:20]
        for slot in range(3)
    ]


def _candidate(
    seed: bytes,
    *,
    point: int,
    slot: int,
    class_id: str,
    action: str,
) -> dict[str, Any]:
    return {
        "candidate_id": _candidate_id(seed, point, slot),
        "hypothesis_class": class_id,
        "action": action,
        "experiment_cost": int(action in {"test_mechanism", "replicate", "falsify"}),
        "prerequisite_tags": [],
    }


def _point(
    seed: bytes,
    *,
    point: int,
    classes: Sequence[str],
    oracle_slot: int,
    action: str,
    distractor_actions: tuple[str, str],
    signal: Mapping[str, Any],
    terminal: bool = False,
) -> dict[str, Any]:
    candidates = []
    for slot in range(3):
        selected_action = action if slot == oracle_slot else distractor_actions[(slot + point) % 2]
        candidates.append(
            _candidate(
                seed,
                point=point,
                slot=slot,
                class_id=classes[slot],
                action=selected_action,
            )
        )
    order = _permutation([item["candidate_id"] for item in candidates], seed + bytes((point,)))
    candidates_by_id = {item["candidate_id"]: item for item in candidates}
    ordered = [candidates_by_id[item] for item in order]
    oracle = candidates[oracle_slot]
    return {
        "state_id": "state_" + hashlib.sha256(seed + b"state" + bytes((point,))).hexdigest()[:20],
        "candidates": ordered,
        "public_signal": dict(signal),
        "oracle_choices": [
            {
                "hypothesis_class": oracle["hypothesis_class"],
                "action": oracle["action"],
            }
        ],
        "terminal_decision": terminal,
    }


def _family_points(family: str, seed: bytes, classes: Sequence[str]) -> tuple[list[dict[str, Any]], int]:
    slot = seed[0] % 3
    next_slot = (slot + 1) % 3
    evidence = "evidence_" + hashlib.sha256(seed + b"evidence").hexdigest()[:20]
    claim = "claim_" + hashlib.sha256(seed + b"claim").hexdigest()[:20]
    base = {"target_class": classes[slot], "evidence_id": evidence, "claim_id": claim}

    if family == "mechanism-replication":
        return (
            [
                _point(seed, point=0, classes=classes, oracle_slot=slot, action="test_mechanism", distractor_actions=("test_mechanism", "falsify"), signal={**base, "active_claim": True}),
                _point(seed, point=1, classes=classes, oracle_slot=slot, action="replicate", distractor_actions=("test_mechanism", "replicate"), signal={**base, "support": "provisional", "replication_required": True}),
                _point(seed, point=2, classes=classes, oracle_slot=slot, action="stop_success", distractor_actions=("stop_failure", "test_mechanism"), signal={**base, "support": "replicated", "study_stop": "success"}, terminal=True),
            ],
            2,
        )
    if family == "falsification-closure":
        return (
            [
                _point(seed, point=0, classes=classes, oracle_slot=slot, action="falsify", distractor_actions=("test_mechanism", "replicate"), signal={**base, "contradiction": True}),
                _point(seed, point=1, classes=classes, oracle_slot=slot, action="stop_failure", distractor_actions=("stop_success", "test_mechanism"), signal={**base, "class_closed": True, "study_stop": "failure"}, terminal=True),
            ],
            1,
        )
    if family == "gate-conflict":
        return (
            [
                _point(seed, point=0, classes=classes, oracle_slot=slot, action="resolve_gate", distractor_actions=("test_mechanism", "falsify"), signal={**base, "hard_gate_failed": True}),
                _point(seed, point=1, classes=classes, oracle_slot=slot, action="test_mechanism", distractor_actions=("replicate", "falsify"), signal={**base, "hard_gate_failed": False, "active_claim": True}),
                _point(seed, point=2, classes=classes, oracle_slot=slot, action="stop_success", distractor_actions=("stop_failure", "test_mechanism"), signal={**base, "support": "replicated", "study_stop": "success"}, terminal=True),
            ],
            1,
        )
    if family == "invalid-retry-budget":
        return (
            [
                _point(seed, point=0, classes=classes, oracle_slot=slot, action="repair_packet", distractor_actions=("test_mechanism", "replicate"), signal={**base, "retryable_rejection": True, "invalid_budget_remaining": 1}),
                _point(seed, point=1, classes=classes, oracle_slot=slot, action="test_mechanism", distractor_actions=("repair_packet", "falsify"), signal={**base, "active_claim": True, "invalid_budget_remaining": 0}),
                _point(seed, point=2, classes=classes, oracle_slot=slot, action="stop_success", distractor_actions=("stop_failure", "repair_packet"), signal={**base, "support": "replicated", "study_stop": "success"}, terminal=True),
            ],
            1,
        )
    if family == "memory-relation-contamination":
        return (
            [
                _point(seed, point=0, classes=classes, oracle_slot=slot, action="use_memory", distractor_actions=("test_mechanism", "use_memory"), signal={**base, "active_claim": True, "irrelevant_claim_class": classes[next_slot]}),
                _point(seed, point=1, classes=classes, oracle_slot=slot, action="test_mechanism", distractor_actions=("falsify", "replicate"), signal={**base, "active_claim": True}),
                _point(seed, point=2, classes=classes, oracle_slot=slot, action="stop_success", distractor_actions=("stop_failure", "test_mechanism"), signal={**base, "support": "replicated", "study_stop": "success"}, terminal=True),
            ],
            1,
        )
    if family == "crash-drift-exhaustion":
        stale = bool(seed[1] & 1)
        action = "refresh_context" if stale else "resume"
        terminal_kind = "failure" if bool(seed[2] & 1) else "success"
        terminal_action = "stop_failure" if terminal_kind == "failure" else "stop_success"
        return (
            [
                _point(seed, point=0, classes=classes, oracle_slot=slot, action=action, distractor_actions=(("resume" if stale else "refresh_context"), "test_mechanism"), signal={**base, "pending_recovery": True, "head_stale": stale}),
                _point(seed, point=1, classes=classes, oracle_slot=slot, action=terminal_action, distractor_actions=(("stop_success" if terminal_action == "stop_failure" else "stop_failure"), "resume"), signal={**base, "study_stop": terminal_kind, "budget_exhausted": terminal_kind == "failure"}, terminal=True),
            ],
            0,
        )
    raise MetaEvaluationError(f"unsupported family: {family}")


def generate_suite(manifest: Mapping[str, Any], nonce: str) -> dict[str, Any]:
    """Generate the exact 36-body suite from one externally-created nonce."""

    _require(len(nonce) == 64 and nonce == nonce.lower(), "nonce must be 256-bit lowercase hex")
    try:
        bytes.fromhex(nonce)
    except ValueError as exc:
        raise MetaEvaluationError("nonce must be hexadecimal") from exc
    manifest_sha = sha256_bytes(canonical_json_bytes(manifest))
    families = manifest.get("families")
    if not isinstance(families, Sequence):
        raise MetaEvaluationError("generator families are missing")
    episodes: list[dict[str, Any]] = []
    for raw_family in families:
        _require(isinstance(raw_family, Mapping), "family must be an object")
        family = raw_family.get("id")
        _require(isinstance(family, str), "family id must be text")
        for index in range(6):
            seed = _derive(nonce, manifest_sha, family, index, "episode-v1")
            classes = _class_ids(seed)
            points, minimum = _family_points(family, seed, classes)
            episodes.append(
                {
                    "episode_schema_version": 1,
                    "episode_id": f"{family}-{index + 1:02d}",
                    "family": family,
                    "experiment_budget": 4,
                    "candidate_language_version": 1,
                    "decision_points": points,
                    "hidden_world": {
                        "transition_seed_commitment": sha256_bytes(seed),
                        "terminal_evidence_ids": [
                            cast(str, points[-1]["public_signal"]["evidence_id"])
                        ],
                    },
                    "oracle_terminal": {
                        "action": points[-1]["oracle_choices"][0]["action"],
                        "evidence_ids": [points[-1]["public_signal"]["evidence_id"]],
                    },
                    "minimum_attempts": minimum,
                    "authorized_action": None,
                }
            )
    _require(len(episodes) == 36, "generated suite must contain 36 episodes")
    return {
        "suite_schema_version": SUITE_SCHEMA_VERSION,
        "generator_manifest_sha256": manifest_sha,
        "nonce_commitment_sha256": sha256_bytes(bytes.fromhex(nonce)),
        "episode_count": len(episodes),
        "episodes": episodes,
        "authorized_action": None,
    }


def suite_digest(suite: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(suite))


def generate_race_suite(manifest: Mapping[str, Any], nonce: str) -> dict[str, Any]:
    """Derive twelve domain-separated confirmations for the three M3-C races."""

    _require(
        len(nonce) == 64 and all(item in "0123456789abcdef" for item in nonce),
        "nonce must be 256-bit lowercase hexadecimal",
    )
    contract = manifest.get("race_confirmation_v1")
    if not isinstance(contract, Mapping):
        raise MetaEvaluationError("race confirmation contract is missing")
    _require(contract.get("count") == 12, "race confirmation count must be twelve")
    _require(contract.get("schedules_per_boundary") == 4, "race repetitions must be four")
    boundaries = contract.get("boundaries")
    _require(
        boundaries == [item["boundary"] for item in RACE_BOUNDARIES],
        "race boundary order drifted",
    )
    manifest_sha = sha256_json(manifest)
    rows: list[dict[str, Any]] = []
    for definition in RACE_BOUNDARIES:
        boundary = definition["boundary"]
        for repetition in range(4):
            seed = _derive(
                nonce,
                manifest_sha,
                str(boundary),
                repetition,
                "race-confirmation-v1",
            )
            rows.append(
                {
                    "schedule_id": "race_" + hashlib.sha256(seed + b"id").hexdigest()[:24],
                    "boundary": boundary,
                    "repetition": repetition + 1,
                    "pytest_node": definition["pytest_node"],
                    "stable_code": definition["stable_code"],
                    "order_key": hashlib.sha256(seed + b"order").hexdigest(),
                    "expected": {
                        "passed": 1,
                        "restarted_call_count": 0,
                        "controller_project_delta": 0,
                        "controller_program_delta": 0,
                        "truth_count_delta": 0,
                    },
                }
            )
    rows.sort(key=lambda row: row["order_key"])
    _require(len(rows) == 12, "race generator did not create twelve rows")
    return {
        "race_suite_schema_version": 1,
        "generator_manifest_digest": manifest_sha,
        "schedules": rows,
        "authorized_action": None,
    }


def _lineage(point: Mapping[str, Any]) -> list[dict[str, Any]]:
    signal = cast(Mapping[str, Any], point["public_signal"])
    return [
        {
            "experiment_id": "experiment_" + cast(str, point["state_id"])[6:],
            "parent_id": None,
            "status": "TERMINAL",
            "attempt": 1,
            "retry_of": None,
            "retryable": bool(signal.get("retryable_rejection")),
            "candidate_digest": sha256_json({"state": point["state_id"]}),
            "compatibility_digest": "c" * 64,
            "payload": {
                "graph_metadata_version": 1,
                "graph_action": "explore",
                "scientific_change": "opaque historical terminal summary",
                "candidate": {"opaque": True},
                "outcome": {
                    "status": "TERMINAL",
                    "reason_code": "SYNTHETIC_TERMINAL",
                    "retryable": bool(signal.get("retryable_rejection")),
                },
            },
            "registered_at": "2026-01-01T00:00:00Z",
            "terminated_at": "2026-01-01T00:00:01Z",
            "created_sequence": 1,
        }
    ]


def _base_context(point: Mapping[str, Any]) -> dict[str, Any]:
    token = sha256_json({"state_id": point["state_id"], "surface": "project-v2"})
    return build_agent_context(
        project={"project_id": "project_benchmark", "name": "M3-D synthetic"},
        status={"phase": "research", "baselines": 1},
        lineage=_lineage(point),
        findings=[],
        artifacts=[],
        agent_spec={"research_ready": True, "configured": True},
        snapshot={"context_token": token, "project_id": "project_benchmark"},
        limit=10,
        current_compatibility_digest="c" * 64,
        compatible_baseline_ready=True,
    )


def _class_states(
    signal: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]
) -> list[dict[str, Any]]:
    target = signal["target_class"]
    class_ids = sorted({cast(str, item["hypothesis_class"]) for item in candidates})
    result = []
    for class_id in class_ids:
        is_target = class_id == target
        lifecycle = "closed" if is_target and signal.get("class_closed") else "open"
        support = signal.get("support", "unsupported") if is_target else "unsupported"
        body = {
            "hypothesis_class_id": class_id,
            "lifecycle": lifecycle,
            "support": support,
            "replication_required": bool(is_target and signal.get("replication_required")),
            "authorized_action": None,
        }
        result.append(
            {
                "class_state_id": "classstate_" + sha256_json({"class": class_id})[:20],
                "class_state_digest": sha256_json(body),
                "class_state": body,
            }
        )
    return result


def _v05_context(point: Mapping[str, Any]) -> dict[str, Any]:
    signal = cast(Mapping[str, Any], point["public_signal"])
    candidates = cast(Sequence[Mapping[str, Any]], point["candidates"])
    base = _base_context(point)
    science = {
        "science_state_version": 1,
        "active_generation_id": "generation_benchmark",
        "budget": {
            "attempts": {"limit": 4, "used": 0, "remaining": 4},
            "retries": {"limit": 1, "used": 0, "remaining": 1},
        },
        "pending_diagnosis_experiment_ids": [],
        "class_states": _class_states(signal, candidates),
        "semantic_frontier": {
            "entries": (
                [
                    {
                        "hypothesis_class_id": signal["target_class"],
                        "maturity": signal["support"],
                        "eligible_actions": ["ablate", "exploit", "replicate"],
                        "authorized_action": None,
                    }
                ]
                if signal.get("support") in {"provisional", "replicated"}
                else []
            ),
            "authorized_action": None,
        },
        "retry_frontier": {
            "entries": (
                [{"hypothesis_class_id": signal["target_class"], "retryable": True}]
                if signal.get("retryable_rejection")
                else []
            ),
            "authorized_action": None,
        },
        "study_stop": {
            "stopped": bool(signal.get("study_stop")),
            "reasons": [] if not signal.get("study_stop") else [signal["study_stop"]],
            "authorized_action": None,
        },
        "diagnoses": (
            [
                {
                    "diagnosis": {
                        "hypothesis_class_id": signal["target_class"],
                        "failure_type": "constraint",
                        "recommendation": "change_control",
                        "hard_gate_failed": True,
                        "authorized_action": None,
                    }
                }
            ]
            if signal.get("hard_gate_failed")
            else []
        ),
        "authorized_action": None,
    }
    context = build_agent_context_v3(
        project=cast(Mapping[str, Any], base["project"]),
        status=cast(Mapping[str, Any], base["state"]),
        lineage=_lineage(point),
        findings=[],
        artifacts=[],
        agent_spec={"research_ready": True, "configured": True},
        snapshot=cast(Mapping[str, Any], base["snapshot"]),
        scientific_state=science,
        limit=10,
        current_compatibility_digest="c" * 64,
        compatible_baseline_ready=True,
    )
    if signal.get("active_claim") or signal.get("contradiction"):
        role = "contradiction" if signal.get("contradiction") else "active"
        context["memory"] = {
            "memory_schema_version": 1,
            "retrieval_result": {
                role: [
                    {
                        "claim_id": signal["claim_id"],
                        "hypothesis_class_id": signal["target_class"],
                        "retrieval_role": role,
                        "reasons": ["program:exact", "class:exact", f"relation:{role}"],
                        "status": "active",
                        "authorized_action": None,
                    }
                ],
                "excluded_superseded_claim_ids": [
                    "claim_" + sha256_json({"irrelevant": signal.get("irrelevant_claim_class")})[:20]
                ],
                "authorized_action": None,
            },
            "authorized_action": None,
        }
    context["autonomy"] = {
        "autonomy_episode_state_schema_version": 1,
        "phase": "proposal",
        "current_query": {"hypothesis_class_id": signal["target_class"]},
        "pending_call_kind": "proposal" if signal.get("pending_recovery") else None,
        "recovery": {
            "head_stale": bool(signal.get("head_stale")),
            "stored_generation": "generation_benchmark",
            "stored_program_head": {"sequence": 1, "hash": "a" * 64},
        },
        "budget": {
            "experiments": {"used": 0, "limit": 4},
            "invalid_packets": {
                "used": 0,
                "limit": int(signal.get("invalid_budget_remaining", 1)),
            },
            "authorized_action": None,
        },
        "authorized_action": None,
    }
    return context


def context_for(point: Mapping[str, Any], arm: Literal["v0.2", "v0.5"]) -> dict[str, Any]:
    if arm == "v0.2":
        return _base_context(point)
    if arm == "v0.5":
        return _v05_context(point)
    raise MetaEvaluationError(f"unsupported arm: {arm}")


def _find_forbidden_key(value: object, *, path: str = "$") -> list[str]:
    hits: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key in FORBIDDEN_SELECTOR_KEYS:
                hits.append(child)
            hits.extend(_find_forbidden_key(item, path=child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for index, item in enumerate(value):
            hits.extend(_find_forbidden_key(item, path=f"{path}[{index}]") )
    return hits


def selector_input(point: Mapping[str, Any], arm: Literal["v0.2", "v0.5"]) -> dict[str, Any]:
    value = {
        "arm": arm,
        "context": context_for(point, arm),
        "candidates": deepcopy(point["candidates"]),
        "authorized_action": None,
    }
    hits = _find_forbidden_key(value)
    if hits:
        raise MetaEvaluationError(f"selector input leaks hidden/oracle keys: {hits}")
    return value


def _typed_target(context: Mapping[str, Any]) -> tuple[str | None, str | None]:
    science = context.get("science")
    memory = context.get("memory")
    autonomy = context.get("autonomy")
    if isinstance(autonomy, Mapping):
        recovery = autonomy.get("recovery")
        if autonomy.get("pending_call_kind") and isinstance(recovery, Mapping):
            current_query = autonomy.get("current_query")
            target = (
                current_query.get("hypothesis_class_id")
                if isinstance(current_query, Mapping)
                else None
            )
            return cast(str | None, target), "refresh_context" if recovery.get("head_stale") else "resume"
    if isinstance(science, Mapping):
        states = science.get("class_states")
        parsed_states = []
        if isinstance(states, Sequence):
            for state in states:
                raw_body = state.get("class_state") if isinstance(state, Mapping) else None
                if isinstance(raw_body, Mapping):
                    parsed_states.append(raw_body)
        informative = next(
            (
                item
                for item in parsed_states
                if item.get("lifecycle") == "closed"
                or item.get("support") in {"provisional", "replicated"}
            ),
            None,
        )
        target = (
            cast(str | None, informative.get("hypothesis_class_id"))
            if informative is not None
            else None
        )
        stop = science.get("study_stop")
        if isinstance(stop, Mapping) and stop.get("stopped"):
            reasons = stop.get("reasons")
            reason = reasons[0] if isinstance(reasons, Sequence) and reasons else "failure"
            return target, "stop_success" if reason == "success" else "stop_failure"
        diagnoses = science.get("diagnoses")
        if isinstance(diagnoses, Sequence) and diagnoses:
            diagnosis = diagnoses[0].get("diagnosis") if isinstance(diagnoses[0], Mapping) else None
            if isinstance(diagnosis, Mapping) and diagnosis.get("hard_gate_failed"):
                return cast(str, diagnosis.get("hypothesis_class_id")), "resolve_gate"
        retry = science.get("retry_frontier")
        if isinstance(retry, Mapping) and retry.get("entries"):
            entry = retry["entries"][0]
            return (
                cast(str | None, entry.get("hypothesis_class_id"))
                if isinstance(entry, Mapping)
                else None,
                "repair_packet",
            )
        if informative is not None:
            if informative.get("support") == "provisional" and informative.get("replication_required"):
                return target, "replicate"
            if informative.get("lifecycle") == "closed":
                return target, "stop_failure"
            if informative.get("support") == "replicated":
                return target, "stop_success"
    if isinstance(memory, Mapping):
        result = memory.get("retrieval_result")
        if isinstance(result, Mapping):
            contradictions = result.get("contradiction")
            if isinstance(contradictions, Sequence) and contradictions:
                item = contradictions[0]
                if isinstance(item, Mapping):
                    return cast(str, item.get("hypothesis_class_id")), "falsify"
            active = result.get("active")
            if isinstance(active, Sequence) and active:
                item = active[0]
                if isinstance(item, Mapping):
                    target = cast(str, item.get("hypothesis_class_id"))
                    return target, "use_memory"
    return None, None


def select_candidate(value: Mapping[str, Any]) -> dict[str, Any]:
    """Run one common deterministic selector over an arm-specific context."""

    context = value.get("context")
    candidates = value.get("candidates")
    if not isinstance(context, Mapping):
        raise MetaEvaluationError("selector context must be an object")
    if not isinstance(candidates, Sequence) or not candidates:
        raise MetaEvaluationError("selector candidates are missing")
    parsed = [cast(Mapping[str, Any], item) for item in candidates if isinstance(item, Mapping)]
    _require(len(parsed) == len(candidates), "every selector candidate must be an object")
    target_class, target_action = _typed_target(context)

    def key(candidate: Mapping[str, Any]) -> tuple[int, int, str, str]:
        score = int(candidate.get("hypothesis_class") == target_class) + int(
            candidate.get("action") == target_action
        )
        return (
            -score,
            ACTION_PRIORITY.get(cast(str, candidate.get("action")), 999),
            cast(str, candidate.get("hypothesis_class")),
            cast(str, candidate.get("candidate_id")),
        )

    return dict(min(parsed, key=key))


@dataclass(frozen=True, slots=True)
class ArmResult:
    arm: str
    correct_choices: int
    total_required_choices: int
    correct_terminals: int
    episodes: int
    evidence_bound_terminals: int
    closed_class_retries: int
    wasted_attempts: int
    per_episode_waste: tuple[int, ...]
    traces: tuple[dict[str, Any], ...]

    @property
    def choice_accuracy(self) -> float:
        return self.correct_choices / self.total_required_choices

    @property
    def terminal_rate(self) -> float:
        return self.correct_terminals / self.episodes

    def to_dict(self) -> dict[str, Any]:
        return {
            "arm": self.arm,
            "correct_choices": self.correct_choices,
            "total_required_choices": self.total_required_choices,
            "choice_accuracy": self.choice_accuracy,
            "correct_terminals": self.correct_terminals,
            "episodes": self.episodes,
            "terminal_rate": self.terminal_rate,
            "evidence_bound_terminals": self.evidence_bound_terminals,
            "closed_class_retries": self.closed_class_retries,
            "wasted_attempts": self.wasted_attempts,
            "per_episode_waste": list(self.per_episode_waste),
            "traces": list(self.traces),
        }


def run_arm(suite: Mapping[str, Any], arm: Literal["v0.2", "v0.5"]) -> ArmResult:
    episodes = suite.get("episodes")
    if not isinstance(episodes, Sequence) or len(episodes) != 36:
        raise MetaEvaluationError("suite must have 36 episodes")
    correct_choices = 0
    total = 0
    terminal_correct = 0
    evidence_bound = 0
    closed_retries = 0
    total_waste = 0
    per_episode_waste: list[int] = []
    traces: list[dict[str, Any]] = []
    for raw_episode in episodes:
        _require(isinstance(raw_episode, Mapping), "episode must be an object")
        points = raw_episode.get("decision_points")
        _require(isinstance(points, Sequence) and points, "episode decision points are missing")
        episode_correct = True
        executed_attempts = 0
        selected_rows = []
        for point in points:
            _require(isinstance(point, Mapping), "decision point must be an object")
            input_value = selector_input(point, arm)
            selected = select_candidate(input_value)
            oracle = point.get("oracle_choices")
            _require(isinstance(oracle, Sequence) and oracle, "oracle choice set is empty")
            pair = {
                "hypothesis_class": selected["hypothesis_class"],
                "action": selected["action"],
            }
            matched = pair in oracle
            correct_choices += int(matched)
            total += 1
            episode_correct &= matched
            executed_attempts += int(selected.get("experiment_cost") == 1)
            context = cast(Mapping[str, Any], input_value["context"])
            science = context.get("science")
            if selected.get("experiment_cost") == 1 and isinstance(science, Mapping):
                states = science.get("class_states")
                if isinstance(states, Sequence):
                    for state in states:
                        body = state.get("class_state") if isinstance(state, Mapping) else None
                        if (
                            isinstance(body, Mapping)
                            and body.get("hypothesis_class_id") == selected["hypothesis_class"]
                            and body.get("lifecycle") == "closed"
                        ):
                            closed_retries += 1
            selected_rows.append(
                {
                    "state_id": point["state_id"],
                    "selector_input_digest": sha256_json(input_value),
                    "candidate_list_digest": sha256_json(point["candidates"]),
                    "selected": pair,
                    "correct": matched,
                }
            )
        terminal = points[-1]
        terminal_pair = terminal["oracle_choices"][0]
        selected_terminal = selected_rows[-1]["selected"]
        terminal_match = selected_terminal == terminal_pair and episode_correct
        terminal_correct += int(terminal_match)
        evidence_ids = raw_episode.get("oracle_terminal", {}).get("evidence_ids", [])
        bound = terminal_match and bool(evidence_ids) and all(isinstance(item, str) for item in evidence_ids)
        evidence_bound += int(bound)
        minimum = raw_episode.get("minimum_attempts")
        _require(isinstance(minimum, int) and not isinstance(minimum, bool), "minimum attempts invalid")
        waste = max(0, executed_attempts - minimum)
        total_waste += waste
        per_episode_waste.append(waste)
        traces.append(
            {
                "episode_id": raw_episode["episode_id"],
                "family": raw_episode["family"],
                "candidate_bytes_digest": sha256_json(
                    [point["candidates"] for point in cast(Sequence[Mapping[str, Any]], points)]
                ),
                "budget": raw_episode["experiment_budget"],
                "required_decisions": len(points),
                "selected": selected_rows,
                "terminal_correct": terminal_match,
                "evidence_bound": bound,
                "wasted_attempts": waste,
            }
        )
    return ArmResult(
        arm,
        correct_choices,
        total,
        terminal_correct,
        len(episodes),
        evidence_bound,
        closed_retries,
        total_waste,
        tuple(per_episode_waste),
        tuple(traces),
    )


def compare_arms(v02: ArmResult, v05: ArmResult) -> dict[str, Any]:
    _require(v02.arm == "v0.2" and v05.arm == "v0.5", "arm order is invalid")
    _require(v02.total_required_choices == v05.total_required_choices, "choice denominators differ")
    _require(v02.episodes == v05.episodes == 36, "terminal denominators differ")
    positive_indices = [index for index, waste in enumerate(v02.per_episode_waste) if waste > 0]
    positive_v02 = sum(v02.per_episode_waste[index] for index in positive_indices)
    _require(positive_v02 > 0, "v0.2 positive waste is zero; REQUIREMENT-WRONG review required")
    positive_v05 = sum(v05.per_episode_waste[index] for index in positive_indices)
    zero_rule = all(v05.per_episode_waste[index] == 0 for index, waste in enumerate(v02.per_episode_waste) if waste == 0)
    choice_threshold = min(0.90, v02.choice_accuracy + 0.20)
    terminal_threshold = min(0.90, v02.terminal_rate + 0.20)
    waste_ratio = positive_v05 / positive_v02
    gates = {
        "evidence_bound_conclusion": v05.evidence_bound_terminals == 36,
        "closed_class_retry": v05.closed_class_retries == 0,
        "next_choice_accuracy": v05.choice_accuracy >= choice_threshold,
        "terminal_accuracy": v05.terminal_rate >= terminal_threshold,
        "positive_waste": waste_ratio <= 0.70 and zero_rule,
    }
    return {
        "comparison_schema_version": 1,
        "v0.2": v02.to_dict(),
        "v0.5": v05.to_dict(),
        "thresholds": {
            "choice_accuracy": choice_threshold,
            "terminal_accuracy": terminal_threshold,
            "positive_waste_ratio": 0.70,
        },
        "observed": {
            "positive_waste_v0.2": positive_v02,
            "positive_waste_v0.5": positive_v05,
            "positive_waste_ratio": waste_ratio,
            "baseline_zero_rule": zero_rule,
        },
        "gates": gates,
        "passed": all(gates.values()),
        "authorized_action": None,
    }


def arm_symmetry(v02: ArmResult, v05: ArmResult) -> dict[str, Any]:
    rows = []
    for left, right in zip(v02.traces, v05.traces, strict=True):
        rows.append(
            {
                "episode_id": left["episode_id"],
                "candidate_bytes_equal": left["candidate_bytes_digest"] == right["candidate_bytes_digest"],
                "budget_equal": left["budget"] == right["budget"],
                "denominator_equal": left["required_decisions"] == right["required_decisions"],
            }
        )
    return {
        "episodes": rows,
        "all_equal": all(
            row["candidate_bytes_equal"] and row["budget_equal"] and row["denominator_equal"]
            for row in rows
        ),
        "authorized_action": None,
    }


def prearm_seal(
    *,
    code_commit: str,
    generator_manifest_sha256: str,
    generator_source_sha256: str,
    v02_agent_sha256: str,
    v02_skill_sha256: str,
    nonce_commitment_sha256: str,
    suite_sha256: str,
    race_suite_sha256: str,
    arm_order: Sequence[str],
    environment: Mapping[str, Any],
) -> dict[str, Any]:
    _require(len(code_commit) == 40, "code commit must be a full git hash")
    digests = (
        generator_manifest_sha256,
        generator_source_sha256,
        v02_agent_sha256,
        v02_skill_sha256,
        nonce_commitment_sha256,
        suite_sha256,
        race_suite_sha256,
    )
    _require(all(len(item) == 64 for item in digests), "seal digests must be SHA-256")
    _require(tuple(arm_order) in (ARM_NAMES, tuple(reversed(ARM_NAMES))), "arm order must contain both arms once")
    body = {
        "prearm_seal_schema_version": RECEIPT_SCHEMA_VERSION,
        "code_commit": code_commit,
        "generator_manifest_sha256": generator_manifest_sha256,
        "generator_source_sha256": generator_source_sha256,
        "v0.2_agent_source_sha256": v02_agent_sha256,
        "v0.2_skill_sha256": v02_skill_sha256,
        "nonce_commitment_sha256": nonce_commitment_sha256,
        "suite_sha256": suite_sha256,
        "race_suite_sha256": race_suite_sha256,
        "arm_order": list(arm_order),
        "environment": dict(environment),
        "authorized_action": None,
    }
    body["seal_sha256"] = sha256_json(body)
    return body


__all__ = [
    "ARM_NAMES",
    "ArmResult",
    "MetaEvaluationError",
    "arm_symmetry",
    "compare_arms",
    "context_for",
    "generate_race_suite",
    "generate_suite",
    "load_generator_manifest",
    "prearm_seal",
    "run_arm",
    "select_candidate",
    "selector_input",
    "sha256_bytes",
    "strict_json_object",
    "suite_digest",
]
