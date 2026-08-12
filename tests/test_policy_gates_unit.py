from __future__ import annotations

import itertools
import math
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

import pytest

from research_os.config import load_project_config
from research_os.contracts import (
    GateDefinition,
    GateEvaluation,
    GateOperator,
    GateRole,
    MetricDirection,
    ResultEnvelope,
    TerminalStatus,
    canonical_json,
)
from research_os.errors import ConfigurationError
from research_os.policy import decide

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "toy_optimization"


def _config(
    *,
    direction: MetricDirection = MetricDirection.MAXIMIZE,
    minimum_improvement: float = 5.0,
    gates: tuple[GateDefinition, ...] = (),
):
    return replace(
        load_project_config(EXAMPLE),
        primary_metric="score",
        direction=direction,
        minimum_improvement=minimum_improvement,
        gates=gates,
    )


def _gate(
    gate_id: str,
    metric: str,
    role: GateRole,
    operator: GateOperator,
    *,
    threshold: float = 10.0,
    scale: float = 4.0,
) -> GateDefinition:
    return GateDefinition(
        id=gate_id,
        metric=metric,
        role=role,
        operator=operator,
        threshold=threshold,
        unit="points",
        scale=scale,
    )


def _assert_hard_veto_evidence(decision) -> None:
    assert decision.status is TerminalStatus.REJECTED
    assert decision.reason_code == "HARD_CONSTRAINT_FAILED"
    assert decision.improvement == 12.0
    assert decision.promotion_margin == 7.0
    assert decision.authorized_action is None


def test_maximize_preserves_delta_and_margin_across_both_hard_veto_paths():
    legacy = decide(
        _config(),
        ResultEnvelope(
            metrics={"score": 112.0},
            constraints=({"name": "safety", "passed": False},),
        ),
        100.0,
        verified=True,
    )
    typed = decide(
        _config(
            gates=(
                _gate(
                    "typed-hard",
                    "safety_score",
                    GateRole.HARD,
                    GateOperator.GTE,
                ),
            )
        ),
        ResultEnvelope(metrics={"score": 112.0, "safety_score": 8.0}),
        100.0,
        verified=True,
    )

    _assert_hard_veto_evidence(legacy)
    _assert_hard_veto_evidence(typed)
    assert legacy.gate_evaluations == ()
    assert len(typed.gate_evaluations) == 1


def test_minimize_preserves_delta_and_margin_across_both_hard_veto_paths():
    legacy = decide(
        _config(direction=MetricDirection.MINIMIZE),
        ResultEnvelope(
            metrics={"score": 88.0},
            constraints=({"name": "safety", "status": "failed"},),
        ),
        100.0,
        verified=True,
    )
    typed = decide(
        _config(
            direction=MetricDirection.MINIMIZE,
            gates=(
                _gate(
                    "typed-hard",
                    "safety_score",
                    GateRole.HARD,
                    GateOperator.LTE,
                ),
            ),
        ),
        ResultEnvelope(metrics={"score": 88.0, "safety_score": 12.0}),
        100.0,
        verified=True,
    )

    _assert_hard_veto_evidence(legacy)
    _assert_hard_veto_evidence(typed)
    assert legacy.gate_evaluations == ()
    assert len(typed.gate_evaluations) == 1


def test_gte_and_lte_slack_exact_cases():
    cases = (
        (GateOperator.GTE, 12.0, 2.0, 0.5, True),
        (GateOperator.GTE, 8.0, -2.0, -0.5, False),
        (GateOperator.GTE, 10.0, 0.0, 0.0, True),
        (GateOperator.LTE, 8.0, 2.0, 0.5, True),
        (GateOperator.LTE, 12.0, -2.0, -0.5, False),
        (GateOperator.LTE, 10.0, 0.0, 0.0, True),
    )
    for index, (operator, observed, signed, normalized, passed) in enumerate(cases):
        gate = _gate(
            f"gate-{index}",
            "observation",
            GateRole.HARD,
            operator,
        )
        decision = decide(
            _config(gates=(gate,)),
            ResultEnvelope(metrics={"score": 112.0, "observation": observed}),
            100.0,
            verified=True,
        )
        evaluation = decision.gate_evaluations[0]
        assert evaluation.observed == observed
        assert evaluation.signed_slack == signed
        assert evaluation.normalized_slack == normalized
        assert evaluation.passed is passed


def _normalized_evidence(decision) -> dict[str, dict[str, object]]:
    return {item.id: item.to_dict() for item in decision.gate_evaluations}


def test_gate_permutations_preserve_complete_evidence_and_dominance():
    mixed_failure_gates = (
        _gate("hard-gte", "hard_gte", GateRole.HARD, GateOperator.GTE),
        _gate("hard-lte", "hard_lte", GateRole.HARD, GateOperator.LTE),
        _gate("support-gte", "support_gte", GateRole.SUPPORT, GateOperator.GTE),
        _gate("support-lte", "support_lte", GateRole.SUPPORT, GateOperator.LTE),
    )
    mixed_metrics = {
        "score": 112.0,
        "hard_gte": 8.0,
        "hard_lte": 8.0,
        "support_gte": 8.0,
        "support_lte": 8.0,
    }
    mixed_reference = None
    for permutation in itertools.permutations(mixed_failure_gates):
        decision = decide(
            _config(gates=permutation),
            ResultEnvelope(metrics=mixed_metrics),
            100.0,
            verified=True,
        )
        assert decision.status is TerminalStatus.REJECTED
        assert decision.reason_code == "HARD_CONSTRAINT_FAILED"
        assert len(decision.gate_evaluations) == len(permutation)
        evidence = _normalized_evidence(decision)
        assert set(evidence) == {gate.id for gate in mixed_failure_gates}
        mixed_reference = evidence if mixed_reference is None else mixed_reference
        assert evidence == mixed_reference

    support_only_gates = (
        _gate("hard-gte", "hard_gte", GateRole.HARD, GateOperator.GTE),
        _gate("hard-lte", "hard_lte", GateRole.HARD, GateOperator.LTE),
        _gate("support-gte", "support_gte", GateRole.SUPPORT, GateOperator.GTE),
        _gate("support-lte", "support_lte", GateRole.SUPPORT, GateOperator.LTE),
    )
    support_metrics = {
        "score": 112.0,
        "hard_gte": 12.0,
        "hard_lte": 8.0,
        "support_gte": 8.0,
        "support_lte": 12.0,
    }
    support_reference = None
    for permutation in itertools.permutations(support_only_gates):
        decision = decide(
            _config(gates=permutation),
            ResultEnvelope(metrics=support_metrics),
            100.0,
            verified=True,
        )
        assert decision.status is TerminalStatus.INSUFFICIENT_EVIDENCE
        assert decision.reason_code == "SUPPORT_GATE_FAILED"
        assert len(decision.gate_evaluations) == len(permutation)
        evidence = _normalized_evidence(decision)
        assert set(evidence) == {gate.id for gate in support_only_gates}
        support_reference = evidence if support_reference is None else support_reference
        assert evidence == support_reference


def test_gate_definition_is_strict_and_rejects_invalid_values():
    valid = {
        "id": " gate-a ",
        "metric": " quality ",
        "role": " hard ",
        "operator": " gte ",
        "threshold": 1.0,
        "unit": " score ",
        "scale": 2.0,
    }
    parsed = GateDefinition.from_dict(valid)
    assert parsed.id == "gate-a"
    assert parsed.metric == "quality"
    assert parsed.role is GateRole.HARD
    assert parsed.operator is GateOperator.GTE
    assert parsed.unit == "score"

    invalid = (
        {**valid, "unknown": "field"},
        {key: value for key, value in valid.items() if key != "unit"},
        {**valid, "id": "  "},
        {**valid, "metric": ""},
        {**valid, "unit": "\t"},
        {**valid, "role": "HARD"},
        {**valid, "operator": "gt"},
        {**valid, "threshold": True},
        {**valid, "threshold": math.inf},
        {**valid, "threshold": 2**53 + 1},
        {**valid, "threshold": 10**1000},
        {**valid, "scale": False},
        {**valid, "scale": math.nan},
        {**valid, "scale": 2**53 + 1},
        {**valid, "scale": 0.0},
        {**valid, "scale": -1.0},
    )
    for data in invalid:
        with pytest.raises((TypeError, ValueError)):
            GateDefinition.from_dict(data)


def test_gate_evaluation_rejects_contradictory_portable_evidence():
    evaluation = GateEvaluation(
        id="gate-a",
        metric="quality",
        role=GateRole.HARD,
        operator=GateOperator.GTE,
        threshold=10.0,
        unit="points",
        scale=4.0,
        observed=12.0,
        signed_slack=2.0,
        normalized_slack=0.5,
        passed=True,
    )
    assert GateEvaluation.from_dict(evaluation.to_dict()) == evaluation

    for field, contradictory in (
        ("signed_slack", -99.0),
        ("normalized_slack", -0.5),
        ("passed", False),
    ):
        forged = evaluation.to_dict()
        forged[field] = contradictory
        with pytest.raises(ValueError, match="inconsistent"):
            GateEvaluation.from_dict(forged)


def test_unsafe_integer_gate_threshold_cannot_round_into_a_fail_open_pass():
    with pytest.raises(ValueError, match="JavaScript safe range"):
        GateDefinition(
            id="unsafe-threshold",
            metric="quality",
            role=GateRole.HARD,
            operator=GateOperator.GTE,
            threshold=2**53 + 1,
            unit="points",
            scale=1.0,
        )

    portable_boundary = GateDefinition(
        id="safe-threshold",
        metric="quality",
        role=GateRole.HARD,
        operator=GateOperator.GTE,
        threshold=2**53 - 1,
        unit="points",
        scale=1.0,
    )
    decision = decide(
        _config(gates=(portable_boundary,)),
        ResultEnvelope(metrics={"score": 112.0, "quality": float(2**53 - 2)}),
        100.0,
        verified=True,
    )
    assert decision.status is TerminalStatus.REJECTED
    assert decision.reason_code == "HARD_CONSTRAINT_FAILED"
    assert decision.gate_evaluations[0].signed_slack == -1.0


def _copy_example() -> tuple[tempfile.TemporaryDirectory[str], Path]:
    temporary = tempfile.TemporaryDirectory()
    project = Path(temporary.name) / "project"
    shutil.copytree(EXAMPLE, project)
    runtime = project / ".research-os" / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    return temporary, project


def _append_constitution(project: Path, text: str) -> None:
    constitution = project / ".research-os" / "constitution.toml"
    constitution.write_text(
        constitution.read_text(encoding="utf-8") + text,
        encoding="utf-8",
    )


def test_config_loads_optional_gates_and_rejects_duplicate_trimmed_ids():
    temporary, project = _copy_example()
    try:
        _append_constitution(
            project,
            """

[[promotion.gates]]
id = " quality "
metric = " quality_score "
role = "support"
operator = "lte"
threshold = 10.0
unit = " points "
scale = 4.0
""",
        )
        config = load_project_config(project)
        assert len(config.gates) == 1
        assert config.promotion_gates is config.gates
        assert config.gates[0].to_dict() == {
            "id": "quality",
            "metric": "quality_score",
            "role": "support",
            "operator": "lte",
            "threshold": 10.0,
            "unit": "points",
            "scale": 4.0,
        }
    finally:
        temporary.cleanup()

    temporary, project = _copy_example()
    try:
        _append_constitution(
            project,
            """

[[promotion.gates]]
id = "quality"
metric = "quality_a"
role = "hard"
operator = "gte"
threshold = 10.0
unit = "points"
scale = 1.0

[[promotion.gates]]
id = " quality "
metric = "quality_b"
role = "support"
operator = "lte"
threshold = 10.0
unit = "points"
scale = 1.0
""",
        )
        with pytest.raises(ConfigurationError, match="duplicate id 'quality'"):
            load_project_config(project)
    finally:
        temporary.cleanup()


def test_config_wraps_gate_contract_errors_and_gate_less_config_is_compatible():
    assert load_project_config(EXAMPLE).gates == ()

    temporary, project = _copy_example()
    try:
        _append_constitution(
            project,
            """

[[promotion.gates]]
id = "quality"
metric = "quality_score"
role = "hard"
operator = "gte"
threshold = nan
unit = "points"
scale = 1.0
unexpected = true
""",
        )
        with pytest.raises(ConfigurationError, match=r"promotion\.gates\[0\]"):
            load_project_config(project)
    finally:
        temporary.cleanup()

    temporary, project = _copy_example()
    try:
        _append_constitution(
            project,
            """

[[promotion.gates]]
id = "unsafe-threshold"
metric = "quality_score"
role = "hard"
operator = "gte"
threshold = 9007199254740993
unit = "points"
scale = 1.0
""",
        )
        with pytest.raises(ConfigurationError, match="JavaScript safe range"):
            load_project_config(project)
    finally:
        temporary.cleanup()


def test_missing_gate_metric_preserves_other_calculable_evidence():
    gates = (
        _gate("missing", "not_observed", GateRole.HARD, GateOperator.GTE),
        _gate("observed", "quality", GateRole.SUPPORT, GateOperator.LTE),
    )
    decision = decide(
        _config(gates=gates),
        ResultEnvelope(metrics={"score": 112.0, "quality": 8.0}),
        100.0,
        verified=True,
    )
    assert decision.status is TerminalStatus.INSUFFICIENT_EVIDENCE
    assert decision.reason_code == "GATE_METRIC_MISSING"
    assert decision.improvement == 12.0
    assert decision.promotion_margin == 7.0
    assert [item.id for item in decision.gate_evaluations] == ["observed"]


def test_gate_slack_overflow_fails_closed_without_short_circuiting():
    cases = (
        _gate(
            "overflow",
            "extreme",
            GateRole.HARD,
            GateOperator.GTE,
            threshold=-1e308,
            scale=1.0,
        ),
        _gate(
            "overflow",
            "extreme",
            GateRole.HARD,
            GateOperator.GTE,
            threshold=0.0,
            scale=5e-324,
        ),
    )
    for overflow_gate in cases:
        ordinary_gate = _gate(
            "ordinary", "ordinary", GateRole.SUPPORT, GateOperator.GTE
        )
        decision = decide(
            _config(gates=(overflow_gate, ordinary_gate)),
            ResultEnvelope(
                metrics={"score": 112.0, "extreme": 1e308, "ordinary": 12.0}
            ),
            100.0,
            verified=True,
        )
        assert decision.status is TerminalStatus.INVALID_EXPERIMENT
        assert decision.reason_code == "NON_FINITE_GATE_SLACK"
        assert [item.id for item in decision.gate_evaluations] == ["ordinary"]
        canonical_json(decision.to_dict())


def test_non_finite_improvement_and_margin_arithmetic_fail_closed():
    improvement_overflow = decide(
        _config(),
        ResultEnvelope(metrics={"score": 1e308}),
        -1e308,
        verified=True,
    )
    assert improvement_overflow.status is TerminalStatus.INVALID_EXPERIMENT
    assert improvement_overflow.reason_code == "NON_FINITE_IMPROVEMENT"
    assert improvement_overflow.improvement is None
    assert improvement_overflow.promotion_margin is None

    margin_overflow = decide(
        _config(
            direction=MetricDirection.MINIMIZE,
            minimum_improvement=1e308,
        ),
        ResultEnvelope(metrics={"score": 1e308}),
        0.0,
        verified=True,
    )
    assert margin_overflow.status is TerminalStatus.INVALID_EXPERIMENT
    assert margin_overflow.reason_code == "NON_FINITE_PROMOTION_MARGIN"
    assert margin_overflow.improvement == -1e308
    assert margin_overflow.promotion_margin is None
    canonical_json(margin_overflow.to_dict())


def test_gate_equality_passes_but_improvement_equality_rejects():
    decision = decide(
        _config(
            gates=(
                _gate("equal", "quality", GateRole.HARD, GateOperator.GTE),
            )
        ),
        ResultEnvelope(metrics={"score": 105.0, "quality": 10.0}),
        100.0,
        verified=True,
    )
    assert decision.gate_evaluations[0].passed is True
    assert decision.gate_evaluations[0].signed_slack == 0.0
    assert decision.promotion_margin == 0.0
    assert decision.status is TerminalStatus.REJECTED
    assert decision.reason_code == "NO_MEANINGFUL_IMPROVEMENT"


def test_gate_less_legacy_constraints_and_success_remain_compatible():
    success = decide(
        _config(),
        ResultEnvelope(
            metrics={"score": 112.0},
            constraints=({"domain_specific": {"value": 1}, "passed": True},),
        ),
        100.0,
        verified=True,
    )
    assert success.status is TerminalStatus.VALIDATED
    assert success.reason_code == "PRIMARY_METRIC_IMPROVED"
    assert success.gate_evaluations == ()
    assert success.to_dict()["gate_evaluations"] == []
    assert success.to_dict()["authorized_action"] is None
    canonical_json(success.to_dict())
