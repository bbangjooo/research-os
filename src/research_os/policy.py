"""Deterministic, project-configured promotion decisions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from research_os.config import ProjectConfig
from research_os.contracts import (
    GateEvaluation,
    GateOperator,
    GateRole,
    MetricDirection,
    ResultEnvelope,
    TerminalStatus,
)


@dataclass(frozen=True, slots=True)
class Decision:
    status: TerminalStatus
    reason_code: str
    primary_metric: str
    candidate_value: float | None
    baseline_value: float | None
    improvement: float | None
    promotion_margin: float | None = None
    gate_evaluations: tuple[GateEvaluation, ...] = ()
    authorized_action: None = None

    def __post_init__(self) -> None:
        for field_name in (
            "candidate_value",
            "baseline_value",
            "improvement",
            "promotion_margin",
        ):
            value = getattr(self, field_name)
            if value is None:
                continue
            normalized = _finite_float(value)
            if normalized is None:
                raise ValueError(f"{field_name} must be finite or null")
            object.__setattr__(self, field_name, normalized)
        evaluations = tuple(self.gate_evaluations)
        if any(not isinstance(item, GateEvaluation) for item in evaluations):
            raise TypeError("gate_evaluations must contain GateEvaluation values")
        object.__setattr__(self, "gate_evaluations", evaluations)
        if self.authorized_action is not None:
            raise ValueError("research decisions cannot authorize actions")

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "primary_metric": self.primary_metric,
            "candidate_value": self.candidate_value,
            "baseline_value": self.baseline_value,
            "improvement": self.improvement,
            "promotion_margin": self.promotion_margin,
            "gate_evaluations": [
                evaluation.to_dict() for evaluation in self.gate_evaluations
            ],
            "authorized_action": None,
        }


def _constraints_pass(constraints: tuple[Any, ...]) -> bool:
    for item in constraints:
        if not isinstance(item, Mapping):
            return False
        passed = item.get("passed")
        status_value = item.get("status")
        status = str(status_value).strip().lower() if status_value is not None else None
        if isinstance(passed, bool):
            if passed is False:
                return False
            if status is not None and status not in {"passed", "ok"}:
                return False
            continue
        if status not in {"passed", "ok"}:
            return False
    return True


def _finite_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        converted = float(value)
    except OverflowError:
        return None
    return converted if math.isfinite(converted) else None


def _evaluate_gates(
    config: ProjectConfig,
    result: ResultEnvelope,
) -> tuple[tuple[GateEvaluation, ...], bool, bool]:
    """Evaluate every calculable gate and report missing/overflow evidence."""

    evaluations: list[GateEvaluation] = []
    missing_metric = False
    non_finite_slack = False
    for gate in config.gates:
        if gate.metric not in result.metrics:
            missing_metric = True
            continue

        observed = result.metrics[gate.metric]
        if gate.operator is GateOperator.GTE:
            signed_slack = observed - gate.threshold
        else:
            signed_slack = gate.threshold - observed
        if not math.isfinite(signed_slack):
            non_finite_slack = True
            continue

        normalized_slack = signed_slack / gate.scale
        if not math.isfinite(normalized_slack):
            non_finite_slack = True
            continue

        evaluations.append(
            GateEvaluation(
                id=gate.id,
                metric=gate.metric,
                role=gate.role,
                operator=gate.operator,
                threshold=gate.threshold,
                unit=gate.unit,
                scale=gate.scale,
                observed=observed,
                signed_slack=signed_slack,
                normalized_slack=normalized_slack,
                passed=signed_slack >= 0,
            )
        )
    return tuple(evaluations), missing_metric, non_finite_slack


def decide(
    config: ProjectConfig,
    result: ResultEnvelope,
    baseline_value: float,
    *,
    verified: bool,
) -> Decision:
    """Compare one candidate with its compatible sealed baseline."""

    metric_name = config.primary_metric
    baseline = _finite_float(baseline_value)
    if not verified:
        return Decision(
            TerminalStatus.INVALID_EXPERIMENT,
            "VERIFY_FAILED",
            metric_name,
            None,
            baseline,
            None,
        )
    if metric_name not in result.metrics:
        return Decision(
            TerminalStatus.INSUFFICIENT_EVIDENCE,
            "PRIMARY_METRIC_MISSING",
            metric_name,
            None,
            baseline,
            None,
        )
    candidate = _finite_float(result.metrics[metric_name])
    if candidate is None or baseline is None:
        return Decision(
            TerminalStatus.INVALID_EXPERIMENT,
            "NON_FINITE_METRIC",
            metric_name,
            candidate,
            baseline,
            None,
        )

    if config.direction is MetricDirection.MAXIMIZE:
        improvement = candidate - baseline
    else:
        improvement = baseline - candidate
    if not math.isfinite(improvement):
        return Decision(
            TerminalStatus.INVALID_EXPERIMENT,
            "NON_FINITE_IMPROVEMENT",
            metric_name,
            candidate,
            baseline,
            None,
        )

    minimum_improvement = _finite_float(config.minimum_improvement)
    if minimum_improvement is None:
        return Decision(
            TerminalStatus.INVALID_EXPERIMENT,
            "NON_FINITE_PROMOTION_MARGIN",
            metric_name,
            candidate,
            baseline,
            improvement,
        )
    promotion_margin = improvement - minimum_improvement
    if not math.isfinite(promotion_margin):
        return Decision(
            TerminalStatus.INVALID_EXPERIMENT,
            "NON_FINITE_PROMOTION_MARGIN",
            metric_name,
            candidate,
            baseline,
            improvement,
        )

    gate_evaluations, missing_gate_metric, non_finite_gate_slack = _evaluate_gates(
        config, result
    )
    if non_finite_gate_slack:
        return Decision(
            TerminalStatus.INVALID_EXPERIMENT,
            "NON_FINITE_GATE_SLACK",
            metric_name,
            candidate,
            baseline,
            improvement,
            promotion_margin,
            gate_evaluations,
        )
    if missing_gate_metric:
        return Decision(
            TerminalStatus.INSUFFICIENT_EVIDENCE,
            "GATE_METRIC_MISSING",
            metric_name,
            candidate,
            baseline,
            improvement,
            promotion_margin,
            gate_evaluations,
        )

    legacy_hard_failed = not _constraints_pass(result.constraints)
    typed_hard_failed = any(
        evaluation.role is GateRole.HARD and not evaluation.passed
        for evaluation in gate_evaluations
    )
    if legacy_hard_failed or typed_hard_failed:
        return Decision(
            TerminalStatus.REJECTED,
            "HARD_CONSTRAINT_FAILED",
            metric_name,
            candidate,
            baseline,
            improvement,
            promotion_margin,
            gate_evaluations,
        )

    support_failed = any(
        evaluation.role is GateRole.SUPPORT and not evaluation.passed
        for evaluation in gate_evaluations
    )
    if support_failed:
        return Decision(
            TerminalStatus.INSUFFICIENT_EVIDENCE,
            "SUPPORT_GATE_FAILED",
            metric_name,
            candidate,
            baseline,
            improvement,
            promotion_margin,
            gate_evaluations,
        )

    if promotion_margin > 0:
        return Decision(
            TerminalStatus.VALIDATED,
            "PRIMARY_METRIC_IMPROVED",
            metric_name,
            candidate,
            baseline,
            improvement,
            promotion_margin,
            gate_evaluations,
        )
    return Decision(
        TerminalStatus.REJECTED,
        "NO_MEANINGFUL_IMPROVEMENT",
        metric_name,
        candidate,
        baseline,
        improvement,
        promotion_margin,
        gate_evaluations,
    )


DESIGN_PROVENANCE = {
    "decide": ("Immutable evaluation", "Reversible ratchet", "Typed provenance"),
}
