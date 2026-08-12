"""Sealed synthetic meta-evaluation for the v0.5 release gate.

The generator and comparator are deterministic.  Acceptance custody is owned by
the release script: this module never creates a nonce and never writes a result.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Literal, cast

from research_os.agent import build_agent_context, build_agent_context_v3
from research_os.autonomy.loop import AutonomyEpisodeState, AutonomyPolicy
from research_os.autonomy.protocol import ProviderDecisionRequest
from research_os.contracts.common import (
    canonical_json_bytes,
    freeze_json_object,
    sha256_json,
)
from research_os.kernel.ids import stable_id
from research_os.memory.claims import (
    Claim,
    ClaimApplicability,
    ClaimEvidenceRef,
    ClaimRelation,
    ClaimSnapshot,
    ClaimStatement,
    ClaimTerminalEvidence,
    ClaimView,
)
from research_os.memory.knowledge import (
    KnowledgeDispositionEntry,
    ProposalKnowledgeDisposition,
)
from research_os.memory.retrieval import RetrievalQuery, RetrievalResult, retrieve_claims
from research_os.science.state import ClassState

GENERATOR_SCHEMA_VERSION: Final = 1
SUITE_SCHEMA_VERSION: Final = 1
RECEIPT_SCHEMA_VERSION: Final = 1
ARM_NAMES: Final = ("v0.2", "v0.5")
V02_COMMIT: Final = "6f36a1b97cf8bc3c5925a3b35f0b189d82f6bcb6"
V02_AGENT_SHA256: Final = "743fe1b60665d512585f4115f8a6f1f4bfa55bce7fef72c55c9a6098a2cb1278"
V02_SKILL_SHA256: Final = "0cab9ff5279b7715c02688d4e26c4c745200400fb2ffad657924a6cec1a59a9f"
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


def _git_bytes(commit: str, relative: str) -> bytes:
    completed = subprocess.run(
        ["git", "show", f"{commit}:{relative}"],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise MetaEvaluationError(f"cannot read historical v0.2 path: {relative}")
    return completed.stdout


@lru_cache(maxsize=1)
def _selector_policy_digest() -> str:
    skill = _git_bytes(
        V02_COMMIT,
        "src/research_os/resources/research-os/SKILL.md",
    )
    _require(sha256_bytes(skill) == V02_SKILL_SHA256, "historical v0.2 skill drifted")
    return sha256_bytes(
        skill
        + canonical_json_bytes(
            {
                "candidate_actions": list(ACTION_PRIORITY),
                "tie_break": "typed_rule_score/action_priority/class/id",
            }
        )
    )


@lru_cache(maxsize=8)
def _historical_v02_context_batch(serialized_inputs: bytes) -> tuple[dict[str, Any], ...]:
    """Execute the byte-fixed v0.2 Context builder in an archived checkout."""

    agent = _git_bytes(V02_COMMIT, "src/research_os/agent.py")
    _require(sha256_bytes(agent) == V02_AGENT_SHA256, "historical v0.2 agent source drifted")
    archive = subprocess.run(
        ["git", "archive", "--format=tar", V02_COMMIT, "src/research_os"],
        check=False,
        capture_output=True,
    )
    if archive.returncode != 0:
        raise MetaEvaluationError("cannot archive historical v0.2 package")
    helper = (
        "import json,sys\n"
        "from research_os.agent import build_agent_context\n"
        "rows=json.load(sys.stdin)\n"
        "json.dump([build_agent_context(**row) for row in rows],sys.stdout,"
        "sort_keys=True,separators=(',',':'))\n"
    )
    with tempfile.TemporaryDirectory(prefix="research-os-v02-context-") as raw:
        root = Path(raw)
        with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as stream:
            stream.extractall(root, filter="data")
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(root / "src")
        completed = subprocess.run(
            [sys.executable, "-c", helper],
            cwd=root,
            env=environment,
            input=serialized_inputs,
            check=False,
            capture_output=True,
        )
    if completed.returncode != 0:
        raise MetaEvaluationError(
            "historical v0.2 Context builder failed: "
            + completed.stderr.decode(errors="replace")[-2000:]
        )
    value = strict_json_object(b'{"contexts":' + completed.stdout + b"}")
    contexts = value.get("contexts")
    if not isinstance(contexts, list) or not all(isinstance(item, dict) for item in contexts):
        raise MetaEvaluationError("historical v0.2 Context output is invalid")
    return tuple(cast(dict[str, Any], item) for item in contexts)


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


_PHASE_ACTIONS: Final[dict[str, tuple[str, str, str]]] = {
    "mechanism": ("test_mechanism", "replicate", "falsify"),
    "replication": ("replicate", "test_mechanism", "falsify"),
    "falsification": ("falsify", "test_mechanism", "replicate"),
    "gate_repair": ("resolve_gate", "test_mechanism", "falsify"),
    "packet_repair": ("repair_packet", "test_mechanism", "replicate"),
    "memory": ("use_memory", "test_mechanism", "falsify"),
    "refresh": ("refresh_context", "resume", "test_mechanism"),
    "resume": ("resume", "refresh_context", "test_mechanism"),
    "success": ("stop_success", "stop_failure", "test_mechanism"),
    "failure": ("stop_failure", "stop_success", "resume"),
}


def _public_observation(
    *,
    phase: str,
    classes: Sequence[str],
    focus_slot: int,
    evidence_id: str,
    stale: bool,
) -> dict[str, Any]:
    """Render observable facts without consulting the oracle-choice function."""

    focus = classes[focus_slot]
    profiles = []
    for class_id in classes:
        body = {
            "hypothesis_class_id": class_id,
            "lifecycle": "open",
            "support": "unsupported",
            "replication_required": False,
            "closure_reason": None,
            "closure_evidence": None,
        }
        if class_id == focus and phase == "replication":
            body.update(support="provisional", replication_required=True)
        elif class_id == focus and phase == "success":
            body.update(
                support="replicated",
                closure_evidence={
                    "terminal_event_id": evidence_id,
                    "support": "replicated",
                },
            )
        elif class_id == focus and phase == "failure":
            body.update(
                lifecycle="closed",
                closure_reason="conclusive_falsification",
                closure_evidence={"terminal_event_id": evidence_id},
            )
        elif class_id == focus and phase == "gate_repair":
            body.update(
                closure_evidence={
                    "terminal_event_id": evidence_id,
                    "hard_gate_failed": True,
                }
            )
        profiles.append(body)

    memory_fact: dict[str, Any] | None = None
    if phase in {"mechanism", "memory", "falsification"}:
        memory_fact = {
            "hypothesis_class_id": focus,
            "mode": (
                "contradiction"
                if phase == "falsification"
                else "replicated_active"
                if phase == "memory"
                else "observed_active"
            ),
        }

    autonomy_fact: dict[str, Any] | None = None
    if phase == "packet_repair":
        autonomy_fact = {
            "hypothesis_class_id": focus,
            "pending_call_kind": "decision",
            "pending_output": {
                "error_code": "DECISION_PACKET_INVALID",
                "retryable": True,
            },
            "invalid_packets_used": 0,
        }
    elif phase in {"refresh", "resume"}:
        autonomy_fact = {
            "hypothesis_class_id": focus,
            "pending_call_kind": "proposal",
            "pending_output": None,
            "stored_program_head_stale": stale,
            "invalid_packets_used": 0,
        }
    return {
        "class_profiles": profiles,
        "memory_fact": memory_fact,
        "autonomy_fact": autonomy_fact,
        "terminal_evidence_id": evidence_id,
        "authorized_action": None,
    }


def _oracle_choice(
    *, phase: str, classes: Sequence[str], focus_slot: int
) -> dict[str, str]:
    """Derive the answer from hidden state, isolated from public rendering."""

    return {
        "hypothesis_class": classes[focus_slot],
        "action": _PHASE_ACTIONS[phase][0],
    }


def _point(
    seed: bytes,
    *,
    point: int,
    classes: Sequence[str],
    focus_slot: int,
    phase: str,
    evidence_id: str,
    stale: bool = False,
    terminal: bool = False,
) -> dict[str, Any]:
    candidates = []
    for class_slot, class_id in enumerate(classes):
        for action_slot, action in enumerate(_PHASE_ACTIONS[phase]):
            slot = class_slot * len(_PHASE_ACTIONS[phase]) + action_slot
            candidates.append(
                {
                    "candidate_id": _candidate_id(seed, point, slot),
                    "hypothesis_class": class_id,
                    "action": action,
                    "experiment_cost": int(
                        action in {"test_mechanism", "replicate", "falsify"}
                    ),
                    "prerequisite_tags": [],
                }
            )
    order = _permutation(
        [cast(str, item["candidate_id"]) for item in candidates],
        seed + b"candidate-order" + bytes((point,)),
    )
    candidates_by_id = {item["candidate_id"]: item for item in candidates}
    return {
        "state_id": "state_"
        + hashlib.sha256(seed + b"state" + bytes((point,))).hexdigest()[:20],
        "candidates": [candidates_by_id[item] for item in order],
        "public_observation": _public_observation(
            phase=phase,
            classes=classes,
            focus_slot=focus_slot,
            evidence_id=evidence_id,
            stale=stale,
        ),
        "oracle_choices": [
            _oracle_choice(phase=phase, classes=classes, focus_slot=focus_slot)
        ],
        "terminal_decision": terminal,
    }


def _family_points(
    family: str, seed: bytes, classes: Sequence[str]
) -> tuple[list[dict[str, Any]], int, list[dict[str, Any]]]:
    focus_slot = seed[0] % 3
    evidence_id = stable_id("event", sha256_bytes(seed), "terminal-evidence")
    stale = bool(seed[1] & 1)
    terminal_kind = "failure" if bool(seed[2] & 1) else "success"
    phases_by_family = {
        "mechanism-replication": ("mechanism", "replication", "success"),
        "falsification-closure": ("falsification", "failure"),
        "gate-conflict": ("gate_repair", "mechanism", "success"),
        "invalid-retry-budget": ("packet_repair", "mechanism", "success"),
        "memory-relation-contamination": ("memory", "mechanism", "success"),
        "crash-drift-exhaustion": (
            "refresh" if stale else "resume",
            terminal_kind,
        ),
    }
    if family not in phases_by_family:
        raise MetaEvaluationError(f"unsupported family: {family}")
    phases = phases_by_family[family]
    points = [
        _point(
            seed,
            point=index,
            classes=classes,
            focus_slot=focus_slot,
            phase=phase,
            evidence_id=evidence_id,
            stale=stale,
            terminal=index == len(phases) - 1,
        )
        for index, phase in enumerate(phases)
    ]
    minimum = sum(
        int(_PHASE_ACTIONS[phase][0] in {"test_mechanism", "replicate", "falsify"})
        for phase in phases
    )
    hidden_states = [
        {
            "phase": phase,
            "focus_slot": focus_slot,
            "transition_commitment": sha256_bytes(
                seed + b"hidden-state" + bytes((index,))
            ),
        }
        for index, phase in enumerate(phases)
    ]
    return points, minimum, hidden_states


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
            points, minimum, hidden_states = _family_points(family, seed, classes)
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
                        "decision_states": hidden_states,
                        "terminal_evidence_ids": [
                            cast(
                                str,
                                points[-1]["public_observation"][
                                    "terminal_evidence_id"
                                ],
                            )
                        ],
                    },
                    "oracle_terminal": {
                        "action": points[-1]["oracle_choices"][0]["action"],
                        "evidence_ids": [
                            points[-1]["public_observation"]["terminal_evidence_id"]
                        ],
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
    observation = point.get("public_observation")
    if not isinstance(observation, Mapping):
        raise MetaEvaluationError("public observation is missing")
    autonomy = observation.get("autonomy_fact")
    pending = autonomy.get("pending_output") if isinstance(autonomy, Mapping) else None
    retryable = isinstance(pending, Mapping) and pending.get("retryable") is True
    return [
        {
            "experiment_id": "experiment_" + cast(str, point["state_id"])[6:],
            "parent_id": None,
            "status": "TERMINAL",
            "attempt": 1,
            "retry_of": None,
            "retryable": retryable,
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
                    "retryable": retryable,
                },
            },
            "registered_at": "2026-01-01T00:00:00Z",
            "terminated_at": "2026-01-01T00:00:01Z",
            "created_sequence": 1,
        }
    ]


def _base_context_inputs(point: Mapping[str, Any]) -> dict[str, Any]:
    token = sha256_json({"state_id": point["state_id"], "surface": "project-v2"})
    return {
        "project": {"project_id": "project_benchmark", "name": "M3-D synthetic"},
        "status": {"phase": "research", "baselines": 1},
        "lineage": _lineage(point),
        "findings": [],
        "artifacts": [],
        "agent_spec": {"research_ready": True, "configured": True},
        "snapshot": {"context_token": token, "project_id": "project_benchmark"},
        "limit": 10,
        "current_compatibility_digest": "c" * 64,
        "compatible_baseline_ready": True,
    }


def _base_context(point: Mapping[str, Any]) -> dict[str, Any]:
    return build_agent_context(**_base_context_inputs(point))


def _historical_contexts(points: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    payload = canonical_json_bytes([_base_context_inputs(point) for point in points])
    contexts = _historical_v02_context_batch(payload)
    _require(len(contexts) == len(points), "historical Context batch length drifted")
    return contexts


def _class_states(observation: Mapping[str, Any], point_id: str) -> list[dict[str, Any]]:
    raw_profiles = observation.get("class_profiles")
    if not isinstance(raw_profiles, Sequence):
        raise MetaEvaluationError("public class profiles are missing")
    result = []
    for raw in raw_profiles:
        if not isinstance(raw, Mapping):
            raise MetaEvaluationError("public class profile must be an object")
        class_id = cast(str, raw["hypothesis_class_id"])
        closed = raw.get("lifecycle") == "closed"
        state = ClassState(
            project_id="project_benchmark",
            generation_id=stable_id("generation", "m3d", point_id),
            hypothesis_class_id=class_id,
            lifecycle=cast(str, raw["lifecycle"]),
            support=cast(str, raw["support"]),
            replication_required=bool(raw["replication_required"]),
            conclusive_rejection_limit=1,
            conclusive_rejections=int(closed),
            conclusive_diagnosis_ids=(
                (stable_id("diagnosis", point_id, class_id),) if closed else ()
            ),
            provisional_diagnosis_ids=(),
            replicated_diagnosis_ids=(),
            inconclusive_diagnosis_ids=(),
            closure_reason=cast(str | None, raw.get("closure_reason")),
            closure_evidence=cast(Mapping[str, Any] | None, raw.get("closure_evidence")),
        )
        result.append(state.to_dict())
    return result


def _benchmark_claim(
    *, point_id: str, class_id: str, label: str, maturity: str
) -> Claim:
    generation_id = stable_id("generation", "m3d", point_id)
    scope = {
        "id": "development",
        "role": "development",
        "manifest_digest": sha256_json({"point": point_id, "scope": "development"}),
    }
    applicability = ClaimApplicability(
        1,
        "project_benchmark",
        generation_id,
        class_id,
        cast(str, scope["id"]),
        cast(str, scope["role"]),
        scope["manifest_digest"],
        sha256_json(
            {
                "evaluation_scope_schema_version": 1,
                "evaluation_scope": scope,
            }
        ),
        sha256_json({"point": point_id, "seal": 1}),
        "c" * 64,
    )
    evidence = ClaimEvidenceRef(
        1,
        stable_id("origin", point_id, label),
        sha256_json({"point": point_id, "origin": label}),
        1,
        stable_id("event", point_id, label, "diagnosis"),
        sha256_json({"point": point_id, "event": label}),
        stable_id("diagnosis", point_id, label),
        sha256_json({"point": point_id, "diagnosis": label}),
        ClaimTerminalEvidence(
            stable_id("experiment", point_id, label),
            stable_id("event", point_id, label, "terminal"),
            sha256_json({"point": point_id, "terminal": label}),
        ),
        (),
        applicability.evaluation_seal_digest,
        applicability.compatibility_digest,
    )
    statement = ClaimStatement(
        "effect",
        f"Benchmark observation {label} for {class_id}.",
        f"A bound counterexample falsifies {label}.",
    )
    limitations = ("Synthetic public-boundary evidence; no deployment authority.",)
    identity = (
        statement.to_dict(),
        applicability.to_dict(),
        evidence.to_dict(),
        "active",
        "observed",
        list(limitations),
    )
    return Claim(
        1,
        stable_id("claim", *identity),
        statement,
        applicability,
        evidence,
        "active",
        "observed",
        limitations,
    )


def _retrieval_result(
    observation: Mapping[str, Any], point_id: str
) -> RetrievalResult | None:
    memory_fact = observation.get("memory_fact")
    autonomy_fact = observation.get("autonomy_fact")
    if not isinstance(memory_fact, Mapping) and not isinstance(autonomy_fact, Mapping):
        return None
    fact = memory_fact if isinstance(memory_fact, Mapping) else autonomy_fact
    assert isinstance(fact, Mapping)
    class_id = cast(str, fact["hypothesis_class_id"])
    program_id = stable_id("program", "m3d", point_id)
    head_hash = sha256_json({"program": program_id, "head": 1})
    claims: list[ClaimView] = []
    relations: list[ClaimRelation] = []
    if isinstance(memory_fact, Mapping):
        mode = memory_fact.get("mode")
        maturity = "replicated" if mode == "replicated_active" else "observed"
        target = _benchmark_claim(
            point_id=point_id,
            class_id=class_id,
            label="target",
            maturity=maturity,
        )
        claims.append(ClaimView(target, target.digest, "active", maturity, (), (), None, ()))
        if mode == "contradiction":
            contradictor = _benchmark_claim(
                point_id=point_id,
                class_id=class_id,
                label="contradictor",
                maturity="observed",
            )
            rationale = "Independent public contradiction for the benchmark state."
            relation = ClaimRelation(
                1,
                stable_id(
                    "relation",
                    "contradicts",
                    contradictor.claim_id,
                    target.claim_id,
                    rationale,
                ),
                "contradicts",
                contradictor.claim_id,
                target.claim_id,
                rationale,
            )
            claims.append(
                ClaimView(
                    contradictor,
                    contradictor.digest,
                    "active",
                    "observed",
                    (),
                    (),
                    None,
                    (),
                )
            )
            relations.append(relation)
    snapshot = ClaimSnapshot(1, program_id, 1, head_hash, tuple(claims), tuple(relations))
    query = RetrievalQuery.from_mapping(
        {
            "retrieval_query_schema_version": 1,
            "query_id": stable_id("query", point_id),
            "program_id": program_id,
            "program_head": {"sequence": 1, "hash": head_hash},
            "hypothesis_class_id": class_id,
            "compatibility_digest": "c" * 64,
            "evaluation_scope": {
                "id": "development",
                "role": "development",
                "manifest_digest": sha256_json(
                    {"point": point_id, "scope": "development"}
                ),
            },
            "claim_kinds": ["effect"],
            "diagnosis_digest": None,
            "relation_types": ["contradicts"],
            "limit": 10,
            "authorized_action": None,
        }
    )
    return retrieve_claims(snapshot, query)


def _knowledge_disposition(
    observation: Mapping[str, Any],
    point_id: str,
    retrieval: RetrievalResult | None,
    context_token: str,
) -> dict[str, Any] | None:
    fact = observation.get("memory_fact")
    if (
        not isinstance(fact, Mapping)
        or fact.get("mode") != "replicated_active"
        or retrieval is None
        or len(retrieval.active) != 1
    ):
        return None
    hit = retrieval.active[0]
    entry = KnowledgeDispositionEntry(
        hit.claim_id,
        hit.view.claim_digest,
        "active",
        hit.relation_ids,
        "used",
        ("hypothesis_class_id",),
        None,
        "The replicated active Claim directly informs the next proposal.",
    )
    provisional = ProposalKnowledgeDisposition(
        1,
        "disposition_placeholder",
        stable_id("proposal", point_id),
        sha256_json({"point": point_id, "proposal": 1}),
        stable_id("generation", "m3d", point_id),
        retrieval.query.hypothesis_class_id,
        retrieval.query.evaluation_scope.evaluation_scope_id,
        context_token,
        retrieval.program_id,
        retrieval.program_head[0],
        retrieval.program_head[1],
        retrieval.query.digest,
        retrieval.digest,
        (entry,),
    )
    return replace(provisional, disposition_id=provisional.expected_id).to_dict()


def _autonomy_state(
    observation: Mapping[str, Any],
    point_id: str,
    retrieval: RetrievalResult | None,
) -> dict[str, Any] | None:
    fact = observation.get("autonomy_fact")
    if not isinstance(fact, Mapping) or retrieval is None:
        return None
    query = retrieval.query
    if fact.get("stored_program_head_stale") is True:
        query = replace(
            query,
            program_head_hash=sha256_json(
                {"program": query.program_id, "head": "stale"}
            ),
        )
    policy = AutonomyPolicy.from_mapping(
        {
            "autonomy_policy_schema_version": 1,
            "max_experiments": 4,
            "max_provider_calls": 8,
            "max_invalid_packets": 1,
            "max_token_units": 10000,
            "max_elapsed_milliseconds": 60000,
            "provider_token_reservation": 100,
            "provider_elapsed_reservation_milliseconds": 1000,
            "context_limit": 10,
            "authorized_action": None,
        }
    )
    request = ProviderDecisionRequest(
        1,
        stable_id("providerrequest", point_id),
        freeze_json_object({}, field_name="benchmark context"),
        freeze_json_object({}, field_name="benchmark program snapshot"),
    )
    pending_raw = fact.get("pending_output")
    pending = (
        None
        if pending_raw is None
        else freeze_json_object(pending_raw, field_name="benchmark pending output")
    )
    return AutonomyEpisodeState(
        project_id="project_benchmark",
        episode_id=stable_id("episode", point_id),
        policy=policy,
        phase="proposal",
        initial_query=query,
        context=freeze_json_object({}, field_name="benchmark context"),
        project_context_token=sha256_json({"point": point_id, "context": 1}),
        proposal_request=request,
        pending_call_kind=cast(str, fact["pending_call_kind"]),
        pending_call_id=stable_id("providercall", point_id),
        pending_output=pending,
        invalid_packets=int(fact.get("invalid_packets_used", 0)),
        last_event_sequence=1,
        last_event_hash=sha256_json({"point": point_id, "autonomy": 1}),
    ).to_dict()


def _v05_context(point: Mapping[str, Any]) -> dict[str, Any]:
    observation = point.get("public_observation")
    if not isinstance(observation, Mapping):
        raise MetaEvaluationError("public observation is missing")
    point_id = cast(str, point["state_id"])
    base = _base_context(point)
    retrieval = _retrieval_result(observation, point_id)
    science = {
        "science_state_version": 1,
        "active_generation_id": stable_id("generation", "m3d", point_id),
        "budget": {
            "attempts": {"limit": 4, "used": 0, "remaining": 4},
            "retries": {"limit": 1, "used": 0, "remaining": 1},
        },
        "pending_diagnosis_experiment_ids": [],
        "class_states": _class_states(observation, point_id),
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
        retrieval=retrieval,
    )
    autonomy = _autonomy_state(observation, point_id, retrieval)
    if autonomy is not None:
        context["autonomy"] = autonomy
    return context


def context_for(point: Mapping[str, Any], arm: Literal["v0.2", "v0.5"]) -> dict[str, Any]:
    if arm == "v0.2":
        return _historical_contexts((point,))[0]
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


def selector_input(
    point: Mapping[str, Any],
    arm: Literal["v0.2", "v0.5"],
    *,
    rendered_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    context = dict(rendered_context) if rendered_context is not None else context_for(point, arm)
    observation = point.get("public_observation")
    retrieval = _retrieval_result(observation, cast(str, point["state_id"])) if (
        arm == "v0.5" and isinstance(observation, Mapping)
    ) else None
    snapshot = context.get("snapshot")
    context_token = snapshot.get("context_token") if isinstance(snapshot, Mapping) else None
    disposition = (
        _knowledge_disposition(
            observation,
            cast(str, point["state_id"]),
            retrieval,
            context_token,
        )
        if isinstance(observation, Mapping) and isinstance(context_token, str)
        else None
    )
    value = {
        "arm": arm,
        "context": context,
        "candidates": deepcopy(point["candidates"]),
        "knowledge_disposition": disposition,
        "selector_policy_digest": _selector_policy_digest(),
        "authorized_action": None,
    }
    hits = _find_forbidden_key(value)
    if hits:
        raise MetaEvaluationError(f"selector input leaks hidden/oracle keys: {hits}")
    return value


def _typed_target(
    context: Mapping[str, Any],
    disposition: Mapping[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    science = context.get("science")
    memory = context.get("memory")
    autonomy = context.get("autonomy")
    if isinstance(autonomy, Mapping):
        current_query = autonomy.get("current_query")
        target = (
            current_query.get("hypothesis_class_id")
            if isinstance(current_query, Mapping)
            else None
        )
        pending = autonomy.get("pending_output")
        budget = autonomy.get("budget")
        invalid = budget.get("invalid_packets") if isinstance(budget, Mapping) else None
        if (
            isinstance(pending, Mapping)
            and pending.get("error_code") == "DECISION_PACKET_INVALID"
            and pending.get("retryable") is True
            and isinstance(invalid, Mapping)
            and isinstance(invalid.get("used"), int)
            and isinstance(invalid.get("limit"), int)
            and invalid["used"] < invalid["limit"]
        ):
            return cast(str | None, target), "repair_packet"
        if autonomy.get("pending_call_kind"):
            stored_head = (
                current_query.get("program_head")
                if isinstance(current_query, Mapping)
                else None
            )
            public_query = memory.get("query") if isinstance(memory, Mapping) else None
            current_head = (
                public_query.get("program_head")
                if isinstance(public_query, Mapping)
                else None
            )
            if isinstance(stored_head, Mapping) and isinstance(current_head, Mapping):
                return (
                    cast(str | None, target),
                    "refresh_context" if stored_head != current_head else "resume",
                )
    if isinstance(science, Mapping):
        states = science.get("class_states")
        parsed_states = []
        if isinstance(states, Sequence):
            for state in states:
                raw_body = state.get("class_state") if isinstance(state, Mapping) else None
                if isinstance(raw_body, Mapping):
                    parsed_states.append(raw_body)
        hard_gate = next(
            (
                item
                for item in parsed_states
                if isinstance(item.get("closure_evidence"), Mapping)
                and item["closure_evidence"].get("hard_gate_failed") is True
            ),
            None,
        )
        if hard_gate is not None:
            return cast(str, hard_gate.get("hypothesis_class_id")), "resolve_gate"
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
            contradictions = result.get("contradictions")
            if isinstance(contradictions, Sequence) and contradictions:
                item = contradictions[0]
                if isinstance(item, Mapping):
                    claim = item.get("claim")
                    applicability = (
                        claim.get("applicability") if isinstance(claim, Mapping) else None
                    )
                    if isinstance(applicability, Mapping):
                        return (
                            cast(str, applicability.get("hypothesis_class_id")),
                            "falsify",
                        )
            active = result.get("active")
            if isinstance(active, Sequence) and active:
                item = active[0]
                if isinstance(item, Mapping):
                    claim = item.get("claim")
                    applicability = (
                        claim.get("applicability") if isinstance(claim, Mapping) else None
                    )
                    if isinstance(applicability, Mapping):
                        target = cast(str, applicability.get("hypothesis_class_id"))
                        entries = (
                            disposition.get("entries")
                            if isinstance(disposition, Mapping)
                            else None
                        )
                        used = isinstance(entries, Sequence) and any(
                            isinstance(entry, Mapping)
                            and entry.get("claim_id")
                            == cast(Mapping[str, Any], claim).get("claim_id")
                            and entry.get("disposition") == "used"
                            for entry in entries
                        )
                        return target, "use_memory" if used else "test_mechanism"
    return None, None


def public_boundary_complete(
    context: Mapping[str, Any],
    family: str,
    disposition: Mapping[str, Any] | None = None,
) -> bool:
    """Check that one family still has its required typed public decision evidence."""

    target, action = _typed_target(context, disposition)
    required = {
        "mechanism-replication": frozenset({"test_mechanism"}),
        "falsification-closure": frozenset({"falsify"}),
        "gate-conflict": frozenset({"resolve_gate"}),
        "invalid-retry-budget": frozenset({"repair_packet"}),
        "memory-relation-contamination": frozenset({"use_memory"}),
        "crash-drift-exhaustion": frozenset({"refresh_context", "resume"}),
    }
    return isinstance(target, str) and action in required.get(family, frozenset())


def _public_conclusion_evidence_ids(context: Mapping[str, Any]) -> tuple[str, ...]:
    """Extract the exact terminal evidence a selector can cite from public state."""

    science = context.get("science")
    if not isinstance(science, Mapping):
        return ()
    states = science.get("class_states")
    if not isinstance(states, Sequence):
        return ()
    evidence_ids: set[str] = set()
    for state in states:
        body = state.get("class_state") if isinstance(state, Mapping) else None
        closure = body.get("closure_evidence") if isinstance(body, Mapping) else None
        terminal_event_id = (
            closure.get("terminal_event_id") if isinstance(closure, Mapping) else None
        )
        if isinstance(terminal_event_id, str):
            evidence_ids.add(terminal_event_id)
    return tuple(sorted(evidence_ids))


def select_candidate(
    value: Mapping[str, Any],
    *,
    action_priority: Mapping[str, int] = ACTION_PRIORITY,
) -> dict[str, Any]:
    """Run one common deterministic selector over an arm-specific context."""

    context = value.get("context")
    candidates = value.get("candidates")
    _require(
        value.get("selector_policy_digest") == _selector_policy_digest(),
        "byte-fixed v0.2 selector policy is not bound",
    )
    if not isinstance(context, Mapping):
        raise MetaEvaluationError("selector context must be an object")
    if not isinstance(candidates, Sequence) or not candidates:
        raise MetaEvaluationError("selector candidates are missing")
    parsed = [cast(Mapping[str, Any], item) for item in candidates if isinstance(item, Mapping)]
    _require(len(parsed) == len(candidates), "every selector candidate must be an object")
    disposition = value.get("knowledge_disposition")
    target_class, target_action = _typed_target(
        context,
        cast(Mapping[str, Any], disposition)
        if isinstance(disposition, Mapping)
        else None,
    )

    def key(candidate: Mapping[str, Any]) -> tuple[int, int, str, str]:
        score = int(candidate.get("hypothesis_class") == target_class) + int(
            candidate.get("action") == target_action
        )
        return (
            -score,
            action_priority.get(cast(str, candidate.get("action")), 999),
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
    historical_by_state: dict[str, dict[str, Any]] = {}
    if arm == "v0.2":
        all_points: list[Mapping[str, Any]] = []
        for raw_episode in episodes:
            if not isinstance(raw_episode, Mapping):
                raise MetaEvaluationError("episode must be an object")
            raw_points = raw_episode.get("decision_points")
            if not isinstance(raw_points, Sequence):
                raise MetaEvaluationError("episode decision points are missing")
            all_points.extend(
                cast(Mapping[str, Any], point)
                for point in raw_points
                if isinstance(point, Mapping)
            )
        contexts = _historical_contexts(all_points)
        historical_by_state = {
            cast(str, point["state_id"]): context
            for point, context in zip(all_points, contexts, strict=True)
        }
        _require(
            len(historical_by_state) == len(all_points),
            "historical Context state IDs are not unique",
        )
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
        wasted_experiments = 0
        trajectory_open = True
        selected_rows = []
        for point in points:
            _require(isinstance(point, Mapping), "decision point must be an object")
            oracle = point.get("oracle_choices")
            _require(isinstance(oracle, Sequence) and oracle, "oracle choice set is empty")
            total += 1
            if not trajectory_open:
                episode_correct = False
                selected_rows.append(
                    {
                        "state_id": point["state_id"],
                        "selector_input_digest": None,
                        "candidate_list_digest": sha256_json(point["candidates"]),
                        "selected": None,
                        "correct": False,
                        "omitted_after_wrong_transition": True,
                    }
                )
                continue
            input_value = selector_input(
                point,
                arm,
                rendered_context=historical_by_state.get(cast(str, point["state_id"])),
            )
            selected = select_candidate(input_value)
            pair = {
                "hypothesis_class": selected["hypothesis_class"],
                "action": selected["action"],
            }
            matched = pair in oracle
            correct_choices += int(matched)
            episode_correct &= matched
            is_experiment = selected.get("experiment_cost") == 1
            executed_attempts += int(is_experiment)
            wasted_experiments += int(is_experiment and not matched)
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
                    "conclusion_evidence_ids": list(
                        _public_conclusion_evidence_ids(context)
                        if selected.get("action") in {"stop_success", "stop_failure"}
                        else ()
                    ),
                    "correct": matched,
                    "omitted_after_wrong_transition": False,
                }
            )
            if not matched:
                trajectory_open = False
        terminal = points[-1]
        terminal_pair = terminal["oracle_choices"][0]
        selected_terminal = selected_rows[-1]["selected"]
        terminal_match = selected_terminal == terminal_pair and episode_correct
        terminal_correct += int(terminal_match)
        evidence_ids = raw_episode.get("oracle_terminal", {}).get("evidence_ids", [])
        published_evidence_ids = selected_rows[-1].get("conclusion_evidence_ids", [])
        bound = (
            terminal_match
            and bool(evidence_ids)
            and all(isinstance(item, str) for item in evidence_ids)
            and published_evidence_ids == sorted(evidence_ids)
        )
        evidence_bound += int(bound)
        minimum = raw_episode.get("minimum_attempts")
        _require(isinstance(minimum, int) and not isinstance(minimum, bool), "minimum attempts invalid")
        if episode_correct:
            _require(
                executed_attempts == minimum,
                "oracle-minimal executed attempt count differs from the body",
            )
        waste = wasted_experiments
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
    choice_threshold = max(v02.choice_accuracy, min(0.90, v02.choice_accuracy + 0.20))
    terminal_threshold = max(v02.terminal_rate, min(0.90, v02.terminal_rate + 0.20))
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
    "public_boundary_complete",
    "run_arm",
    "select_candidate",
    "selector_input",
    "sha256_bytes",
    "strict_json_object",
    "suite_digest",
]
