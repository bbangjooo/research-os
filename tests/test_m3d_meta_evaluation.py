from __future__ import annotations

import hashlib
import subprocess
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from research_os.contracts.common import canonical_json_bytes
from research_os.meta_evaluation import (
    MetaEvaluationError,
    arm_symmetry,
    compare_arms,
    context_for,
    generate_race_suite,
    generate_suite,
    load_generator_manifest,
    prearm_seal,
    run_arm,
    select_candidate,
    selector_input,
    suite_digest,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/meta_evaluation/v1/generator-manifest.json"
MANIFEST_SHA = "3f7e010a79106140fb311578300af4cda5b43e87fa8a5e813e9bc1c6959ff46c"
DEVELOPMENT_NONCE = "11" * 32
V02_COMMIT = "6f36a1b97cf8bc3c5925a3b35f0b189d82f6bcb6"
V02_AGENT_SHA = "743fe1b60665d512585f4115f8a6f1f4bfa55bce7fef72c55c9a6098a2cb1278"
V02_SKILL_SHA = "0cab9ff5279b7715c02688d4e26c4c745200400fb2ffad657924a6cec1a59a9f"
FAMILIES = (
    "mechanism-replication",
    "falsification-closure",
    "gate-conflict",
    "invalid-retry-budget",
    "memory-relation-contamination",
    "crash-drift-exhaustion",
)


def _manifest() -> dict[str, Any]:
    return load_generator_manifest(MANIFEST_PATH)


def _suite(nonce: str = DEVELOPMENT_NONCE) -> dict[str, Any]:
    return generate_suite(_manifest(), nonce)


def _git_bytes(path: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{V02_COMMIT}:{path}"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    ).stdout


def _forbidden_key_hits(value: object, path: str = "$") -> list[str]:
    forbidden = {
        "hidden_world",
        "oracle_choices",
        "oracle_terminal",
        "minimum_attempts",
        "oracle_rank",
        "oracle_rank_if_visible",
    }
    hits = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}"
            if key in forbidden:
                hits.append(child)
            hits.extend(_forbidden_key_hits(item, child))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            hits.extend(_forbidden_key_hits(item, f"{path}[{index}]"))
    return hits


def test_generator_manifest_is_precommitted_and_has_no_acceptance_body() -> None:
    assert hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest() == MANIFEST_SHA
    manifest = _manifest()
    assert manifest["status"] == "precommitted-spec-only-no-acceptance-bodies"
    assert [item["id"] for item in manifest["families"]] == list(FAMILIES)
    assert manifest["suite"]["episode_count"] == 36
    assert manifest["custody"]["nonce_bits"] == 256
    assert not list(MANIFEST_PATH.parent.glob("*acceptance*"))
    assert not list(MANIFEST_PATH.parent.glob("*nonce*"))


def test_generator_is_deterministic_complete_and_nonce_sensitive() -> None:
    first = _suite()
    second = _suite()
    other = _suite("22" * 32)
    assert canonical_json_bytes(first) == canonical_json_bytes(second)
    assert suite_digest(first) == suite_digest(second)
    assert suite_digest(first) != suite_digest(other)
    assert first["episode_count"] == 36
    assert [item["family"] for item in first["episodes"]].count(FAMILIES[0]) == 6
    assert {item["family"] for item in first["episodes"]} == set(FAMILIES)
    assert len({item["episode_id"] for item in first["episodes"]}) == 36
    assert all(item["experiment_budget"] == 4 for item in first["episodes"])
    assert all(item["decision_points"] for item in first["episodes"])


def test_v02_fixture_bytes_and_complete_historical_context_surface() -> None:
    manifest = _manifest()
    arm = manifest["arms"]["v0.2"]
    agent = _git_bytes("src/research_os/agent.py")
    skill = _git_bytes("src/research_os/resources/research-os/SKILL.md")
    assert hashlib.sha256(agent).hexdigest() == arm["agent_source_sha256"] == V02_AGENT_SHA
    assert hashlib.sha256(skill).hexdigest() == arm["packaged_skill_sha256"] == V02_SKILL_SHA

    point = _suite()["episodes"][0]["decision_points"][0]
    context = context_for(point, "v0.2")
    assert context["schema_version"] == 2
    assert set(context) == {
        "schema_version",
        "kind",
        "snapshot",
        "project",
        "agent",
        "state",
        "graph",
        "proposal_contract",
        "evidence",
        "allowed_agent_actions",
        "authority",
        "packet_size_bytes",
    }
    assert set(context["graph"]) == {
        "compatibility_digest",
        "recent",
        "frontier",
        "retryable",
        "total_experiments",
        "recent_returned",
        "recent_truncated",
        "frontier_total",
        "frontier_returned",
        "frontier_truncated",
        "retryable_total",
        "retryable_returned",
        "retryable_truncated",
    }
    assert all(key not in context for key in ("science", "memory", "autonomy"))


def test_common_context_intersection_and_candidate_budget_are_arm_symmetric() -> None:
    point = _suite()["episodes"][0]["decision_points"][0]
    v02 = context_for(point, "v0.2")
    v05 = context_for(point, "v0.5")
    for key in ("science", "diagnosis_authoring", "memory", "autonomy"):
        v05.pop(key, None)
    v02.pop("packet_size_bytes")
    v05.pop("packet_size_bytes")
    v05["schema_version"] = 2
    assert canonical_json_bytes(v02) == canonical_json_bytes(v05)

    left = run_arm(_suite(), "v0.2")
    right = run_arm(_suite(), "v0.5")
    symmetry = arm_symmetry(left, right)
    assert symmetry["all_equal"] is True
    assert len(symmetry["episodes"]) == 36


def test_selector_inputs_have_no_oracle_hidden_world_or_digest_alias() -> None:
    suite = _suite()
    for episode in suite["episodes"]:
        for point in episode["decision_points"]:
            for arm in ("v0.2", "v0.5"):
                value = selector_input(point, arm)
                assert _forbidden_key_hits(value) == []
                encoded = canonical_json_bytes(value)
                for hidden_key in (
                    b"hidden_world",
                    b"oracle_choices",
                    b"oracle_terminal",
                    b"minimum_attempts",
                ):
                    assert hidden_key not in encoded


def _ablated_context(family: str, context: dict[str, Any]) -> dict[str, Any]:
    changed = deepcopy(context)
    if family in {
        "mechanism-replication",
        "falsification-closure",
        "memory-relation-contamination",
    }:
        changed.pop("memory", None)
    elif family == "gate-conflict":
        changed["science"]["diagnoses"] = []
    elif family == "invalid-retry-budget":
        changed["science"]["retry_frontier"]["entries"] = []
    elif family == "crash-drift-exhaustion":
        changed.pop("autonomy", None)
    else:  # pragma: no cover - closed family set
        raise AssertionError(family)
    return changed


def test_material_v05_signal_ablation_is_causal_for_all_six_families() -> None:
    suite = _suite()
    changed_by_family = {family: 0 for family in FAMILIES}
    for episode in suite["episodes"]:
        point = episode["decision_points"][0]
        value = selector_input(point, "v0.5")
        selected = select_candidate(value)
        ablated = select_candidate(
            {"context": _ablated_context(episode["family"], value["context"]), "candidates": value["candidates"]}
        )
        changed_by_family[episode["family"]] += int(
            selected["candidate_id"] != ablated["candidate_id"]
        )
        irrelevant = deepcopy(value["context"])
        irrelevant["project"]["display_only_note"] = "does not enter selector rules"
        assert select_candidate({"context": irrelevant, "candidates": value["candidates"]}) == selected
    assert all(count > 0 for count in changed_by_family.values())


def _relabel_suite(suite: dict[str, Any]) -> dict[str, Any]:
    changed = deepcopy(suite)
    for episode in changed["episodes"]:
        for point_index, point in enumerate(episode["decision_points"]):
            old_classes = sorted({item["hypothesis_class"] for item in point["candidates"]})
            new_classes = [
                "class_perm_" + hashlib.sha256(f"{episode['episode_id']}:{point_index}:{index}".encode()).hexdigest()[:16]
                for index in reversed(range(len(old_classes)))
            ]
            mapping = dict(zip(old_classes, new_classes, strict=True))
            for candidate_index, candidate in enumerate(point["candidates"]):
                candidate["hypothesis_class"] = mapping[candidate["hypothesis_class"]]
                candidate["candidate_id"] = (
                    "candidate_perm_"
                    + hashlib.sha256(
                        f"{episode['episode_id']}:{point_index}:{candidate_index}".encode()
                    ).hexdigest()[:16]
                )
            point["public_signal"]["target_class"] = mapping[
                point["public_signal"]["target_class"]
            ]
            if point["public_signal"].get("irrelevant_claim_class") in mapping:
                point["public_signal"]["irrelevant_claim_class"] = mapping[
                    point["public_signal"]["irrelevant_claim_class"]
                ]
            for oracle in point["oracle_choices"]:
                oracle["hypothesis_class"] = mapping[oracle["hypothesis_class"]]
    return changed


def test_id_and_order_bijection_preserves_v05_oracle_equivalence() -> None:
    original = run_arm(_suite(), "v0.5")
    relabeled = run_arm(_relabel_suite(_suite()), "v0.5")
    assert original.correct_choices == relabeled.correct_choices
    assert original.correct_terminals == relabeled.correct_terminals
    assert original.evidence_bound_terminals == relabeled.evidence_bound_terminals
    assert original.wasted_attempts == relabeled.wasted_attempts == 0


@pytest.mark.parametrize("nonce", ("01" * 32, "02" * 32, "ff" * 32))
def test_development_suites_pass_exact_quality_gates_without_rebaselining(nonce: str) -> None:
    suite = _suite(nonce)
    v02 = run_arm(suite, "v0.2")
    v05 = run_arm(suite, "v0.5")
    observed = compare_arms(v02, v05)
    assert observed["passed"] is True
    assert observed["gates"] == {
        "evidence_bound_conclusion": True,
        "closed_class_retry": True,
        "next_choice_accuracy": True,
        "terminal_accuracy": True,
        "positive_waste": True,
    }
    assert v05.correct_choices == v05.total_required_choices
    assert v05.correct_terminals == v05.episodes == 36
    assert v05.evidence_bound_terminals == 36
    assert v05.closed_class_retries == 0
    assert v05.wasted_attempts == 0
    assert v02.wasted_attempts > 0


def test_metric_denominators_and_zero_waste_are_non_vacuous() -> None:
    suite = _suite()
    v02 = run_arm(suite, "v0.2")
    v05 = run_arm(suite, "v0.5")
    assert v02.total_required_choices == v05.total_required_choices == sum(
        len(item["decision_points"]) for item in suite["episodes"]
    )
    with pytest.raises(MetaEvaluationError, match="positive waste is zero"):
        compare_arms(
            replace(v02, wasted_attempts=0, per_episode_waste=(0,) * 36),
            v05,
        )
    with pytest.raises(MetaEvaluationError, match="choice denominators differ"):
        compare_arms(replace(v02, total_required_choices=v02.total_required_choices - 1), v05)


def test_prearm_seal_binds_every_custody_digest_and_arm_order() -> None:
    suite = _suite()
    seal = prearm_seal(
        code_commit="a" * 40,
        generator_manifest_sha256=MANIFEST_SHA,
        generator_source_sha256="b" * 64,
        v02_agent_sha256=V02_AGENT_SHA,
        v02_skill_sha256=V02_SKILL_SHA,
        nonce_commitment_sha256=suite["nonce_commitment_sha256"],
        suite_sha256=suite_digest(suite),
        race_suite_sha256="c" * 64,
        arm_order=("v0.2", "v0.5"),
        environment={"python": "3.12", "platform": "test"},
    )
    supplied = seal.pop("seal_sha256")
    from research_os.contracts.common import sha256_json

    assert supplied == sha256_json(seal)
    with pytest.raises(MetaEvaluationError, match="both arms once"):
        prearm_seal(
            code_commit="a" * 40,
            generator_manifest_sha256=MANIFEST_SHA,
            generator_source_sha256="b" * 64,
            v02_agent_sha256=V02_AGENT_SHA,
            v02_skill_sha256=V02_SKILL_SHA,
            nonce_commitment_sha256=suite["nonce_commitment_sha256"],
            suite_sha256=suite_digest(suite),
            race_suite_sha256="c" * 64,
            arm_order=("v0.5", "v0.5"),
            environment={},
        )


def test_race_suite_derives_exact_four_per_public_m3c_boundary() -> None:
    race = generate_race_suite(_manifest(), "03" * 32)
    schedules = race["schedules"]
    assert len(schedules) == len({row["schedule_id"] for row in schedules}) == 12
    assert Counter(row["boundary"] for row in schedules) == {
        "experiment_lookup_to_service": 4,
        "disposition_lookup_to_append": 4,
        "claim_lookup_to_append": 4,
    }
    expected = {
        "passed": 1,
        "restarted_call_count": 0,
        "controller_project_delta": 0,
        "controller_program_delta": 0,
        "truth_count_delta": 0,
    }
    assert all(row["stable_code"] == "AUTONOMY_RECOVERY_STALE" for row in schedules)
    assert all(row["expected"] == expected for row in schedules)
    assert generate_race_suite(_manifest(), "03" * 32) == race
    assert generate_race_suite(_manifest(), "04" * 32) != race
