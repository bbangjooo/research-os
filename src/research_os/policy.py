"""Deterministic, project-configured promotion decisions."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Mapping

from research_os.config import ProjectConfig
from research_os.contracts import MetricDirection, ResultEnvelope, TerminalStatus


@dataclass(frozen=True, slots=True)
class Decision:
    status: TerminalStatus
    reason_code: str
    primary_metric: str
    candidate_value: float | None
    baseline_value: float | None
    improvement: float | None
    authorized_action: None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "primary_metric": self.primary_metric,
            "candidate_value": self.candidate_value,
            "baseline_value": self.baseline_value,
            "improvement": self.improvement,
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


def decide(
    config: ProjectConfig,
    result: ResultEnvelope,
    baseline_value: float,
    *,
    verified: bool,
) -> Decision:
    """Compare one candidate with its compatible sealed baseline."""

    metric_name = config.primary_metric
    if not verified:
        return Decision(
            TerminalStatus.INVALID_EXPERIMENT,
            "VERIFY_FAILED",
            metric_name,
            None,
            baseline_value,
            None,
        )
    if metric_name not in result.metrics:
        return Decision(
            TerminalStatus.INSUFFICIENT_EVIDENCE,
            "PRIMARY_METRIC_MISSING",
            metric_name,
            None,
            baseline_value,
            None,
        )
    candidate = float(result.metrics[metric_name])
    if not math.isfinite(candidate) or not math.isfinite(float(baseline_value)):
        return Decision(
            TerminalStatus.INVALID_EXPERIMENT,
            "NON_FINITE_METRIC",
            metric_name,
            candidate,
            baseline_value,
            None,
        )
    if not _constraints_pass(result.constraints):
        return Decision(
            TerminalStatus.REJECTED,
            "HARD_CONSTRAINT_FAILED",
            metric_name,
            candidate,
            baseline_value,
            None,
        )

    if config.direction is MetricDirection.MAXIMIZE:
        improvement = candidate - baseline_value
    else:
        improvement = baseline_value - candidate
    if improvement > config.minimum_improvement:
        return Decision(
            TerminalStatus.VALIDATED,
            "PRIMARY_METRIC_IMPROVED",
            metric_name,
            candidate,
            baseline_value,
            improvement,
        )
    return Decision(
        TerminalStatus.REJECTED,
        "NO_MEANINGFUL_IMPROVEMENT",
        metric_name,
        candidate,
        baseline_value,
        improvement,
    )


DESIGN_PROVENANCE = {
    "decide": ("Immutable evaluation", "Reversible ratchet", "Typed provenance"),
}
