"""Domain-neutral metric and result-envelope contracts."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, cast

from .artifacts import ArtifactRef
from .common import (
    JSONObject,
    JSONValue,
    copy_json_object,
    copy_json_value,
    decode_json_object,
    freeze_json_object,
    freeze_json_value,
    normalize_json_value,
    require_fields,
)
from .status import TerminalStatus


class MetricDirection(str, Enum):
    """Direction in which a primary metric improves."""

    MAXIMIZE = "maximize"
    MINIMIZE = "minimize"

    @classmethod
    def parse(cls, value: "MetricDirection | str") -> "MetricDirection":
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise TypeError("metric direction must be a string")
        aliases = {
            "max": cls.MAXIMIZE,
            "higher": cls.MAXIMIZE,
            "higher_is_better": cls.MAXIMIZE,
            "min": cls.MINIMIZE,
            "lower": cls.MINIMIZE,
            "lower_is_better": cls.MINIMIZE,
        }
        normalized = value.strip().lower()
        if normalized in aliases:
            return aliases[normalized]
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError(
                "metric direction must be 'maximize' or 'minimize'"
            ) from exc


class GateRole(str, Enum):
    """A promotion gate's decision role."""

    HARD = "hard"
    SUPPORT = "support"

    @classmethod
    def parse(cls, value: "GateRole | str") -> "GateRole":
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise TypeError("gate role must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError("gate role must be a non-empty string")
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError("gate role must be 'hard' or 'support'") from exc


class GateOperator(str, Enum):
    """Comparison operator owned by a promotion gate definition."""

    GTE = "gte"
    LTE = "lte"

    @classmethod
    def parse(cls, value: "GateOperator | str") -> "GateOperator":
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise TypeError("gate operator must be a string")
        normalized = value.strip()
        if not normalized:
            raise ValueError("gate operator must be a non-empty string")
        try:
            return cls(normalized)
        except ValueError as exc:
            raise ValueError("gate operator must be 'gte' or 'lte'") from exc


def _gate_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    normalized = normalize_json_value(value)
    assert isinstance(normalized, str)
    result = normalized.strip()
    if "\x00" in result:
        raise ValueError(f"{field_name} contains a NUL byte")
    return result


def _gate_number(value: Any, field_name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be a number")
    # Preserve canonical-JSON integer semantics before converting the contract
    # to binary64.  Converting an unsafe Python integer first can silently round
    # a hard threshold (for example 2**53 + 1 -> 2**53) and fail open.
    portable = normalize_json_value(value)
    assert isinstance(portable, (int, float)) and not isinstance(portable, bool)
    try:
        result = float(portable)
    except OverflowError as exc:
        raise ValueError(f"{field_name} must be finite") from exc
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be finite")
    if positive and result <= 0:
        raise ValueError(f"{field_name} must be greater than zero")
    return result


def _exact_fields(data: Mapping[str, Any], expected: frozenset[str], name: str) -> None:
    actual = set(data)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unknown = sorted(str(key) for key in actual - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing: {', '.join(missing)}")
    if unknown:
        details.append(f"unknown: {', '.join(unknown)}")
    raise ValueError(f"{name} must contain exactly the required fields ({'; '.join(details)})")


_GATE_DEFINITION_FIELDS = frozenset(
    {"id", "metric", "role", "operator", "threshold", "unit", "scale"}
)


@dataclass(frozen=True, slots=True)
class GateDefinition:
    """One constitution-owned promotion gate definition."""

    id: str
    metric: str
    role: GateRole | str
    operator: GateOperator | str
    threshold: float
    unit: str
    scale: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _gate_string(self.id, "gate.id"))
        object.__setattr__(self, "metric", _gate_string(self.metric, "gate.metric"))
        object.__setattr__(self, "role", GateRole.parse(self.role))
        object.__setattr__(self, "operator", GateOperator.parse(self.operator))
        object.__setattr__(
            self, "threshold", _gate_number(self.threshold, "gate.threshold")
        )
        object.__setattr__(self, "unit", _gate_string(self.unit, "gate.unit"))
        object.__setattr__(
            self, "scale", _gate_number(self.scale, "gate.scale", positive=True)
        )

    def to_dict(self) -> JSONObject:
        role = GateRole.parse(self.role)
        operator = GateOperator.parse(self.operator)
        return {
            "id": self.id,
            "metric": self.metric,
            "role": role.value,
            "operator": operator.value,
            "threshold": self.threshold,
            "unit": self.unit,
            "scale": self.scale,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "GateDefinition":
        if not isinstance(data, Mapping):
            raise TypeError("gate definition must be a JSON object")
        _exact_fields(data, _GATE_DEFINITION_FIELDS, "gate definition")
        return cls(
            id=data["id"],
            metric=data["metric"],
            role=data["role"],
            operator=data["operator"],
            threshold=data["threshold"],
            unit=data["unit"],
            scale=data["scale"],
        )

    from_mapping = from_dict


_GATE_EVALUATION_FIELDS = frozenset(
    {
        "id",
        "metric",
        "role",
        "operator",
        "threshold",
        "unit",
        "scale",
        "observed",
        "signed_slack",
        "normalized_slack",
        "passed",
    }
)


@dataclass(frozen=True, slots=True)
class GateEvaluation:
    """Portable numeric evidence produced from one gate and one observation."""

    id: str
    metric: str
    role: GateRole | str
    operator: GateOperator | str
    threshold: float
    unit: str
    scale: float
    observed: float
    signed_slack: float
    normalized_slack: float
    passed: bool

    def __post_init__(self) -> None:
        object.__setattr__(self, "id", _gate_string(self.id, "gate evaluation.id"))
        object.__setattr__(
            self, "metric", _gate_string(self.metric, "gate evaluation.metric")
        )
        object.__setattr__(self, "role", GateRole.parse(self.role))
        object.__setattr__(self, "operator", GateOperator.parse(self.operator))
        object.__setattr__(
            self,
            "threshold",
            _gate_number(self.threshold, "gate evaluation.threshold"),
        )
        object.__setattr__(
            self, "unit", _gate_string(self.unit, "gate evaluation.unit")
        )
        object.__setattr__(
            self,
            "scale",
            _gate_number(self.scale, "gate evaluation.scale", positive=True),
        )
        object.__setattr__(
            self, "observed", _gate_number(self.observed, "gate evaluation.observed")
        )
        object.__setattr__(
            self,
            "signed_slack",
            _gate_number(self.signed_slack, "gate evaluation.signed_slack"),
        )
        object.__setattr__(
            self,
            "normalized_slack",
            _gate_number(
                self.normalized_slack, "gate evaluation.normalized_slack"
            ),
        )
        if not isinstance(self.passed, bool):
            raise TypeError("gate evaluation.passed must be a boolean")

        operator = GateOperator.parse(self.operator)
        if operator is GateOperator.GTE:
            expected_signed = self.observed - self.threshold
        else:
            expected_signed = self.threshold - self.observed
        if not math.isfinite(expected_signed):
            raise ValueError("gate evaluation signed slack arithmetic must be finite")
        expected_normalized = expected_signed / self.scale
        if not math.isfinite(expected_normalized):
            raise ValueError(
                "gate evaluation normalized slack arithmetic must be finite"
            )
        if self.signed_slack != expected_signed:
            raise ValueError("gate evaluation.signed_slack is inconsistent")
        if self.normalized_slack != expected_normalized:
            raise ValueError("gate evaluation.normalized_slack is inconsistent")
        if self.passed is not (expected_signed >= 0):
            raise ValueError("gate evaluation.passed is inconsistent")

    def to_dict(self) -> JSONObject:
        role = GateRole.parse(self.role)
        operator = GateOperator.parse(self.operator)
        return {
            "id": self.id,
            "metric": self.metric,
            "role": role.value,
            "operator": operator.value,
            "threshold": self.threshold,
            "unit": self.unit,
            "scale": self.scale,
            "observed": self.observed,
            "signed_slack": self.signed_slack,
            "normalized_slack": self.normalized_slack,
            "passed": self.passed,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "GateEvaluation":
        if not isinstance(data, Mapping):
            raise TypeError("gate evaluation must be a JSON object")
        _exact_fields(data, _GATE_EVALUATION_FIELDS, "gate evaluation")
        return cls(
            id=data["id"],
            metric=data["metric"],
            role=data["role"],
            operator=data["operator"],
            threshold=data["threshold"],
            unit=data["unit"],
            scale=data["scale"],
            observed=data["observed"],
            signed_slack=data["signed_slack"],
            normalized_slack=data["normalized_slack"],
            passed=data["passed"],
        )

    from_mapping = from_dict


def _metric_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError("metric name must be a non-empty string")
    normalized = normalize_json_value(value)
    assert isinstance(normalized, str)
    return normalized.strip()


def _metric_value(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("metric value must be a number")
    portable = normalize_json_value(value)
    assert isinstance(portable, (int, float)) and not isinstance(portable, bool)
    converted = float(portable)
    if not math.isfinite(converted):
        raise ValueError("metric value must be finite")
    return converted


@dataclass(frozen=True, slots=True)
class Metric:
    """One named, finite metric value."""

    name: str
    value: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _metric_name(self.name))
        object.__setattr__(self, "value", _metric_value(self.value))

    def to_dict(self) -> JSONObject:
        return {"name": self.name, "value": self.value}

    @classmethod
    def from_dict(cls, data: Any) -> "Metric":
        if not isinstance(data, Mapping):
            raise TypeError("metric must be a JSON object")
        require_fields(data, "name", "value")
        return cls(name=data["name"], value=data["value"])


def _metrics(value: Any) -> Mapping[str, float]:
    if not isinstance(value, Mapping):
        raise TypeError("metrics must be an object mapping names to numbers")

    normalized: dict[str, float] = {}
    for raw_name, raw_value in value.items():
        name = _metric_name(raw_name)
        if name in normalized:
            raise ValueError(f"duplicate metric name: {name}")
        normalized[name] = _metric_value(raw_value)
    if not normalized:
        raise ValueError("metrics must contain at least one metric")
    return MappingProxyType(normalized)


def _json_array(value: Any, name: str) -> tuple[JSONValue, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a JSON array")
    return tuple(normalize_json_value(item) for item in value)


def _diagnostics(value: Any) -> tuple[JSONValue, ...]:
    diagnostics = _json_array(value, "diagnostics")
    for item in diagnostics:
        if not isinstance(item, (str, dict)):
            raise TypeError("each diagnostic must be a string or JSON object")
    return tuple(cast(JSONValue, freeze_json_value(item)) for item in diagnostics)


def _constraints(value: Any) -> tuple[JSONValue, ...]:
    constraints = _json_array(value, "constraints")
    for item in constraints:
        if not isinstance(item, dict):
            raise TypeError("each constraint must be a JSON object")
        if "passed" in item and not isinstance(item["passed"], bool):
            raise TypeError("constraint 'passed' must be a boolean")
        passed = item.get("passed")
        status = item.get("status")
        explicit_pass = isinstance(passed, bool)
        normalized_status = status.strip().lower() if isinstance(status, str) else None
        recognized_statuses = {
            "passed",
            "ok",
            "failed",
            "rejected",
            "invalid",
        }
        if "status" in item and normalized_status not in recognized_statuses:
            raise ValueError("constraint 'status' is not recognized")
        explicit_status = normalized_status in recognized_statuses
        if not explicit_pass and not explicit_status:
            raise ValueError(
                "each constraint must declare boolean 'passed' or a recognized 'status'"
            )
        if explicit_pass and explicit_status:
            status_passed = normalized_status in {"passed", "ok"}
            if passed is not status_passed:
                raise ValueError("constraint 'passed' and 'status' conflict")
    return tuple(cast(JSONValue, freeze_json_value(item)) for item in constraints)


def _artifacts(value: Any) -> tuple[ArtifactRef, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("artifacts must be a JSON array")
    normalized = tuple(
        item if isinstance(item, ArtifactRef) else ArtifactRef.from_dict(item)
        for item in value
    )
    seen: set[str] = set()
    for artifact in normalized:
        if artifact.path in seen:
            raise ValueError(f"duplicate artifact path: {artifact.path}")
        seen.add(artifact.path)
    return normalized


@dataclass(frozen=True, slots=True)
class ResultEnvelope:
    """Normalized output of an adapter evaluation.

    The primary metric name and direction are constitution policy, not adapter
    output.  Consequently this envelope preserves the complete metric map and
    leaves primary-metric selection to the caller.
    """

    metrics: Mapping[str, float]
    status: TerminalStatus | None = None
    constraints: tuple[JSONValue, ...] = ()
    resource_usage: Mapping[str, JSONValue] = field(
        default_factory=lambda: MappingProxyType({})
    )
    artifacts: tuple[ArtifactRef, ...] = ()
    provenance: Mapping[str, JSONValue] = field(
        default_factory=lambda: MappingProxyType({})
    )
    diagnostics: tuple[JSONValue, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "metrics", _metrics(self.metrics))
        if self.status is not None:
            object.__setattr__(self, "status", TerminalStatus.parse(self.status))
        object.__setattr__(self, "constraints", _constraints(self.constraints))
        object.__setattr__(
            self,
            "resource_usage",
            freeze_json_object(self.resource_usage, field_name="resource_usage"),
        )
        object.__setattr__(
            self,
            "artifacts",
            _artifacts(self.artifacts),
        )
        object.__setattr__(
            self,
            "provenance",
            freeze_json_object(self.provenance, field_name="provenance"),
        )
        object.__setattr__(self, "diagnostics", _diagnostics(self.diagnostics))

    def metric(self, name: str) -> float:
        return self.metrics[name]

    def to_dict(self) -> JSONObject:
        result: JSONObject = {
            "metrics": dict(self.metrics),
            "constraints": [copy_json_value(item) for item in self.constraints],
            "resource_usage": copy_json_object(
                self.resource_usage, field_name="resource_usage"
            ),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "provenance": copy_json_object(self.provenance, field_name="provenance"),
            "diagnostics": [copy_json_value(item) for item in self.diagnostics],
        }
        if self.status is not None:
            result["status"] = self.status.value
        return result

    @classmethod
    def from_dict(cls, data: Any) -> "ResultEnvelope":
        if not isinstance(data, Mapping):
            raise TypeError("result envelope must be a JSON object")
        require_fields(data, "metrics")
        return cls(
            metrics=data["metrics"],
            status=data.get("status"),
            constraints=data.get("constraints", ()),
            resource_usage=data.get("resource_usage", {}),
            artifacts=data.get("artifacts", ()),
            provenance=data.get("provenance", {}),
            diagnostics=data.get("diagnostics", ()),
        )

    from_mapping = from_dict

    @classmethod
    def from_json(cls, data: str | bytes | bytearray) -> "ResultEnvelope":
        return cls.from_dict(decode_json_object(data))


DESIGN_PROVENANCE: dict[str, tuple[str, ...]] = {
    "GateDefinition": ("Immutable evaluation", "Typed provenance"),
    "GateEvaluation": ("Immutable evaluation", "Typed provenance"),
    "GateOperator": ("Immutable evaluation",),
    "GateRole": ("Immutable evaluation",),
    "Metric": ("Typed provenance",),
    "MetricDirection": ("Immutable evaluation",),
    "ResultEnvelope": ("Typed provenance", "Immutable evaluation"),
}
