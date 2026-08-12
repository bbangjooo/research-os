from __future__ import annotations

import hashlib
import inspect
import json
import subprocess
from collections import Counter
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from research_os.contracts.common import canonical_json_bytes, sha256_json
from research_os.memory.knowledge import ProposalKnowledgeDisposition
from research_os.meta_evaluation import (
    MetaEvaluationError,
    arm_symmetry,
    compare_arms,
    context_for,
    generate_race_suite,
    generate_suite,
    load_generator_manifest,
    prearm_seal,
    public_boundary_complete,
    run_arm,
    select_candidate,
    selector_input,
    suite_digest,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "tests/fixtures/meta_evaluation/v1/generator-manifest.json"
PREARM_PATH = ROOT / "docs/research-os-status/14-m3-d-prearm-seal.json"
ACCEPTANCE_PATHS = (
    ROOT / "tests/fixtures/meta_evaluation/v1/acceptance-suite.json",
    ROOT / "tests/fixtures/meta_evaluation/v1/acceptance-race-suite.json",
)
ATTEMPT1_PREARM_PATH = ROOT / "docs/research-os-status/14-m3-d-attempt-1-prearm-seal.json"
ATTEMPT1_ACCEPTANCE_PATHS = (
    ROOT
    / "tests/fixtures/meta_evaluation/v1/failed-attempt-1-acceptance-suite.json",
    ROOT
    / "tests/fixtures/meta_evaluation/v1/failed-attempt-1-acceptance-race-suite.json",
)
ATTEMPT1_SEALED_PATHS = ACCEPTANCE_PATHS
MANIFEST_SHA = "dd767fcb787aa44cdf1c5aaad851f5556205bbd5143ccde169cbf469066e04a3"
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


def _assert_bodies_absent_at_sealed_code_commit(
    prearm_path: Path,
    artifact_paths: tuple[Path, ...],
    sealed_paths: tuple[Path, ...],
) -> None:
    assert prearm_path.is_file()
    assert len(artifact_paths) == len(sealed_paths)
    assert all(path.is_file() for path in artifact_paths)
    prearm = json.loads(prearm_path.read_text(encoding="utf-8"))
    code_commit = prearm["code_commit"]
    assert len(code_commit) == 40
    for path in sealed_paths:
        relative = path.relative_to(ROOT).as_posix()
        frozen = subprocess.run(
            ["git", "cat-file", "-e", f"{code_commit}:{relative}"],
            cwd=ROOT,
            check=False,
            capture_output=True,
        )
        assert frozen.returncode != 0


def test_generator_manifest_is_precommitted_and_has_no_acceptance_body() -> None:
    assert hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest() == MANIFEST_SHA
    manifest = _manifest()
    assert manifest["status"] == "precommitted-spec-only-no-acceptance-bodies"
    assert [item["id"] for item in manifest["families"]] == list(FAMILIES)
    assert manifest["suite"]["episode_count"] == 36
    assert manifest["custody"]["nonce_bits"] == 256
    present = tuple(path.exists() for path in ACCEPTANCE_PATHS)
    assert len(set(present)) == 1
    if present[0]:
        _assert_bodies_absent_at_sealed_code_commit(
            PREARM_PATH,
            ACCEPTANCE_PATHS,
            ACCEPTANCE_PATHS,
        )
    else:
        assert not PREARM_PATH.exists()


def test_failed_attempt_archive_proves_post_draw_chronology() -> None:
    _assert_bodies_absent_at_sealed_code_commit(
        ATTEMPT1_PREARM_PATH,
        ATTEMPT1_ACCEPTANCE_PATHS,
        ATTEMPT1_SEALED_PATHS,
    )


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


def test_v02_arm_executes_archived_builder_and_skill_digest_is_causal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import research_os.meta_evaluation as module

    module._historical_v02_context_batch.cache_clear()
    monkeypatch.setattr(
        module,
        "build_agent_context",
        lambda **_: (_ for _ in ()).throw(AssertionError("current builder executed")),
    )
    point = _suite()["episodes"][0]["decision_points"][0]
    context = context_for(point, "v0.2")
    assert context["schema_version"] == 2
    value = selector_input(point, "v0.2", rendered_context=context)
    with pytest.raises(MetaEvaluationError, match="selector policy is not bound"):
        select_candidate({**value, "selector_policy_digest": "0" * 64})


def test_common_context_intersection_and_candidate_budget_are_arm_symmetric() -> None:
    point = _suite()["episodes"][0]["decision_points"][0]
    v02 = context_for(point, "v0.2")
    v05 = context_for(point, "v0.5")
    for key in ("science", "diagnosis_authoring", "memory", "autonomy"):
        v05.pop(key, None)
    if "project_snapshot" in v05["snapshot"]:
        v05["snapshot"] = v05["snapshot"]["project_snapshot"]
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


def _material_point_mutation(
    point: dict[str, Any], family: str, mutation: str
) -> dict[str, Any]:
    changed = deepcopy(point)
    observation = changed["public_observation"]
    profiles = observation["class_profiles"]
    facts = [
        item
        for item in profiles
        if item["support"] != "unsupported"
        or item["lifecycle"] == "closed"
        or item["closure_evidence"] is not None
    ]
    memory = observation["memory_fact"]
    autonomy = observation["autonomy_fact"]
    candidate_classes = sorted(
        {item["hypothesis_class"] for item in changed["candidates"]}
    )
    if family in {
        "mechanism-replication",
        "falsification-closure",
        "memory-relation-contamination",
    }:
        assert isinstance(memory, dict)
        if mutation == "remove":
            observation["memory_fact"] = None
        elif mutation == "contradict":
            memory["mode"] = {
                "observed_active": "contradiction",
                "replicated_active": "observed_active",
                "contradiction": "observed_active",
            }[memory["mode"]]
        else:
            memory["hypothesis_class_id"] = next(
                item
                for item in candidate_classes
                if item != memory["hypothesis_class_id"]
            )
    elif family == "gate-conflict":
        assert len(facts) == 1
        if mutation in {"remove", "contradict"}:
            facts[0]["closure_evidence"] = None
        else:
            facts[0]["hypothesis_class_id"] = next(
                item
                for item in candidate_classes
                if item != facts[0]["hypothesis_class_id"]
            )
    elif family in {"invalid-retry-budget", "crash-drift-exhaustion"}:
        assert isinstance(autonomy, dict)
        if mutation == "remove":
            observation["autonomy_fact"] = None
        elif mutation == "contradict":
            if family == "invalid-retry-budget":
                autonomy["pending_output"]["retryable"] = False
            else:
                autonomy["stored_program_head_stale"] = not autonomy[
                    "stored_program_head_stale"
                ]
        else:
            autonomy["hypothesis_class_id"] = next(
                item
                for item in candidate_classes
                if item != autonomy["hypothesis_class_id"]
            )
    else:  # pragma: no cover - closed family set
        raise AssertionError(family)
    return changed


def test_material_v05_signal_ablation_is_causal_for_all_six_families() -> None:
    suite = _suite()
    changed_by_family = {
        (family, mutation): 0
        for family in FAMILIES
        for mutation in ("remove", "permute_id", "contradict")
    }
    for episode in suite["episodes"]:
        point = episode["decision_points"][0]
        value = selector_input(point, "v0.5")
        selected = select_candidate(value)
        for mutation in ("remove", "permute_id", "contradict"):
            mutated = _material_point_mutation(point, episode["family"], mutation)
            mutated_input = selector_input(mutated, "v0.5")
            changed_selection = select_candidate(mutated_input)
            changed_by_family[(episode["family"], mutation)] += int(
                selected["candidate_id"] != changed_selection["candidate_id"]
                or not public_boundary_complete(
                    mutated_input["context"],
                    episode["family"],
                    mutated_input["knowledge_disposition"],
                )
            )
        irrelevant = deepcopy(value["context"])
        irrelevant["project"]["display_only_note"] = "does not enter selector rules"
        assert select_candidate({**value, "context": irrelevant}) == selected
    assert all(count == 6 for count in changed_by_family.values())


def test_public_renderer_is_oracle_isolated_and_oracle_mutation_cannot_change_input() -> None:
    import research_os.meta_evaluation as module

    renderer_source = inspect.getsource(module._public_observation)
    assert "_oracle_choice" not in renderer_source
    assert "_oracle_choice" not in module._public_observation.__code__.co_names
    suite = _suite()
    changed = deepcopy(suite)
    for episode in changed["episodes"]:
        for point in episode["decision_points"]:
            point["oracle_choices"] = [
                {"hypothesis_class": "class_oracle_only", "action": "stop_failure"}
            ]
    for original_episode, changed_episode in zip(
        suite["episodes"], changed["episodes"], strict=True
    ):
        for original, oracle_only in zip(
            original_episode["decision_points"],
            changed_episode["decision_points"],
            strict=True,
        ):
            assert canonical_json_bytes(selector_input(original, "v0.5")) == (
                canonical_json_bytes(selector_input(oracle_only, "v0.5"))
            )


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
            observation = point["public_observation"]
            for profile in observation["class_profiles"]:
                profile["hypothesis_class_id"] = mapping[
                    profile["hypothesis_class_id"]
                ]
            for field in ("memory_fact", "autonomy_fact"):
                fact = observation[field]
                if fact is not None:
                    fact["hypothesis_class_id"] = mapping[
                        fact["hypothesis_class_id"]
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


def test_v05_exact_typed_match_is_independent_of_action_priority_and_array_order() -> None:
    reversed_priority = {
        action: index
        for index, action in enumerate(
            reversed(
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
        )
    }
    for episode in _suite()["episodes"]:
        for point in episode["decision_points"]:
            value = selector_input(point, "v0.5")
            shuffled = {**value, "candidates": list(reversed(value["candidates"]))}
            expected = select_candidate(value)
            assert select_candidate(value, action_priority=reversed_priority) == expected
            assert select_candidate(shuffled, action_priority=reversed_priority) == expected


@pytest.mark.parametrize("family", FAMILIES, ids=FAMILIES)
def test_generated_family_uses_real_public_serializers_and_external_oracle(
    family: str,
) -> None:
    episode = next(item for item in _suite()["episodes"] if item["family"] == family)
    for point in episode["decision_points"]:
        value = selector_input(point, "v0.5")
        context = value["context"]
        selected = select_candidate(value)
        assert {
            "hypothesis_class": selected["hypothesis_class"],
            "action": selected["action"],
        } in point["oracle_choices"]
        for state in context["science"]["class_states"]:
            assert state["class_state_digest"] == sha256_json(state["class_state"])
        memory = context.get("memory")
        if memory is not None:
            assert memory["query_digest"] == sha256_json(memory["query"])
            assert memory["retrieval_result_digest"] == sha256_json(
                memory["retrieval_result"]
            )
        autonomy = context.get("autonomy")
        if autonomy is not None:
            assert autonomy["autonomy_episode_state_schema_version"] == 1
            assert autonomy["current_query"]["query_id"].startswith("query_")

    first = selector_input(episode["decision_points"][0], "v0.5")
    assert public_boundary_complete(
        first["context"], family, first["knowledge_disposition"]
    )
    if family == "memory-relation-contamination":
        disposition = first["knowledge_disposition"]
        assert ProposalKnowledgeDisposition.from_mapping(disposition).to_dict() == disposition
        assert disposition["disposition_id"].startswith("disposition_")
        assert disposition["entries"][0]["disposition"] == "used"
        assert select_candidate({**first, "knowledge_disposition": None}) != (
            select_candidate(first)
        )
    terminal_point = episode["decision_points"][-1]
    terminal_context = selector_input(terminal_point, "v0.5")["context"]
    evidence_id = terminal_point["public_observation"]["terminal_evidence_id"]
    refs = [
        state["class_state"]["closure_evidence"]
        for state in terminal_context["science"]["class_states"]
        if state["class_state"]["closure_evidence"] is not None
    ]
    assert any(ref.get("terminal_event_id") == evidence_id for ref in refs)
    assert episode["hidden_world"]["terminal_evidence_ids"] == [evidence_id]
    assert episode["oracle_terminal"] == {
        "action": terminal_point["oracle_choices"][0]["action"],
        "evidence_ids": [evidence_id],
    }


def test_evidence_bound_gate_requires_exact_public_terminal_reference() -> None:
    suite = _suite()
    changed = deepcopy(suite)
    terminal = changed["episodes"][0]["decision_points"][-1]
    informative = next(
        item
        for item in terminal["public_observation"]["class_profiles"]
        if item["closure_evidence"] is not None
    )
    informative["closure_evidence"]["terminal_event_id"] = "event_public_tamper"
    baseline = run_arm(suite, "v0.2")
    candidate = run_arm(changed, "v0.5")
    assert candidate.correct_terminals == 36
    assert candidate.evidence_bound_terminals == 35
    observed = compare_arms(baseline, candidate)
    assert observed["gates"]["evidence_bound_conclusion"] is False
    assert observed["passed"] is False


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


def test_metric_never_approves_regression_when_v02_exceeds_ninety_percent() -> None:
    suite = _suite()
    baseline = run_arm(suite, "v0.2")
    candidate = run_arm(suite, "v0.5")
    denominator = baseline.total_required_choices
    strong_baseline = replace(
        baseline,
        correct_choices=denominator,
        correct_terminals=36,
    )
    regressed = replace(
        candidate,
        correct_choices=denominator - 1,
        correct_terminals=35,
    )
    observed = compare_arms(strong_baseline, regressed)
    assert observed["gates"]["next_choice_accuracy"] is False
    assert observed["gates"]["terminal_accuracy"] is False
    assert observed["passed"] is False


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
