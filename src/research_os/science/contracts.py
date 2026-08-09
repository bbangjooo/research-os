"""Strict immutable contracts for versioned scientific study state."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from research_os.contracts.common import MAX_SAFE_JSON_INTEGER, sha256_json
from research_os.errors import ScientificStateError
from research_os.kernel.ids import stable_id, validate_namespaced_id

SCIENCE_STATE_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SCOPE_ROLES = frozenset({"development", "diagnostic", "replication", "holdout"})


def _fail(code: str, reason: str, *, path: str) -> ScientificStateError:
    return ScientificStateError(
        code,
        reason,
        details={"path": path, "reason": reason},
    )


def _object(value: Any, keys: set[str], *, path: str, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise _fail(code, f"{path} must be an object", path=path)
    if any(not isinstance(key, str) for key in value):
        raise _fail(code, f"{path} object keys must be strings", path=path)
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise _fail(
            code,
            f"{path} must have exact keys (missing={missing}, unknown={unknown})",
            path=path,
        )
    return value


def _array(value: Any, *, path: str, code: str, nonempty: bool = True) -> Sequence[Any]:
    if not isinstance(value, Sequence) or isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        raise _fail(code, f"{path} must be an array", path=path)
    if nonempty and not value:
        raise _fail(code, f"{path} must not be empty", path=path)
    return value


def _text(value: Any, *, path: str, code: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise _fail(code, f"{path} must be a non-empty trimmed string", path=path)
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise _fail(code, f"{path} must contain Unicode scalar values", path=path)
    return value


def _digest(value: Any, *, path: str, code: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise _fail(code, f"{path} must be a lowercase SHA-256 digest", path=path)
    return value


def _integer(
    value: Any,
    *,
    path: str,
    code: str,
    minimum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or abs(value) > MAX_SAFE_JSON_INTEGER
        or value < minimum
    ):
        raise _fail(
            code,
            f"{path} must be a safe integer greater than or equal to {minimum}",
            path=path,
        )
    return value


def _json_pointer(value: Any, *, path: str, code: str) -> str:
    if not isinstance(value, str):
        raise _fail(code, f"{path} must be an RFC-6901 JSON pointer", path=path)
    if value == "":
        return value
    if not value.startswith("/"):
        raise _fail(code, f"{path} must be an RFC-6901 JSON pointer", path=path)
    index = 0
    while index < len(value):
        if value[index] != "~":
            index += 1
            continue
        if index + 1 >= len(value) or value[index + 1] not in "01":
            raise _fail(code, f"{path} has an invalid RFC-6901 escape", path=path)
        index += 2
    return value


@dataclass(frozen=True, slots=True)
class HypothesisClass:
    id: str
    description: str
    conclusive_rejection_limit: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "conclusive_rejection_limit": self.conclusive_rejection_limit,
        }


@dataclass(frozen=True, slots=True)
class InterventionSurface:
    candidate_schema_digest: str
    allowed_json_pointers: tuple[str, ...]
    max_changes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_schema_digest": self.candidate_schema_digest,
            "allowed_json_pointers": list(self.allowed_json_pointers),
            "max_changes": self.max_changes,
        }


@dataclass(frozen=True, slots=True)
class EvaluationScope:
    id: str
    role: str
    manifest_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "role": self.role, "manifest_digest": self.manifest_digest}


@dataclass(frozen=True, slots=True)
class FrontierPolicy:
    max_active_branches: int

    def to_dict(self) -> dict[str, Any]:
        return {"max_active_branches": self.max_active_branches}


@dataclass(frozen=True, slots=True)
class StopPolicy:
    on_untrusted: str = "stop"
    on_budget_exhausted: str = "stop"
    when_all_classes_closed: str = "stop"

    def to_dict(self) -> dict[str, Any]:
        return {
            "on_untrusted": self.on_untrusted,
            "on_budget_exhausted": self.on_budget_exhausted,
            "when_all_classes_closed": self.when_all_classes_closed,
        }


@dataclass(frozen=True, slots=True)
class ChangeControl:
    require_new_generation: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"require_new_generation": self.require_new_generation}


@dataclass(frozen=True, slots=True)
class StudyBudget:
    max_attempts: int
    max_retries: int
    max_elapsed_milliseconds: int
    elapsed_reservation_per_attempt_milliseconds: int
    cost_unit: str | None
    max_cost_microunits: int | None
    cost_reservation_per_attempt_microunits: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_attempts": self.max_attempts,
            "max_retries": self.max_retries,
            "max_elapsed_milliseconds": self.max_elapsed_milliseconds,
            "elapsed_reservation_per_attempt_milliseconds": (
                self.elapsed_reservation_per_attempt_milliseconds
            ),
            "cost_unit": self.cost_unit,
            "max_cost_microunits": self.max_cost_microunits,
            "cost_reservation_per_attempt_microunits": (
                self.cost_reservation_per_attempt_microunits
            ),
        }


@dataclass(frozen=True, slots=True)
class StudyContract:
    schema_version: int
    study_id: str
    hypothesis_classes: tuple[HypothesisClass, ...]
    intervention_surface: InterventionSurface
    evaluation_scopes: tuple[EvaluationScope, ...]
    frontier: FrontierPolicy
    stop_policy: StopPolicy
    change_control: ChangeControl
    budget: StudyBudget

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "StudyContract":
        code = "STUDY_CONTRACT_INVALID"
        root = _object(
            raw,
            {
                "schema_version",
                "study_id",
                "hypothesis_classes",
                "intervention_surface",
                "evaluation_scopes",
                "frontier",
                "stop_policy",
                "change_control",
                "budget",
            },
            path="$",
            code=code,
        )
        if (
            isinstance(root["schema_version"], bool)
            or not isinstance(root["schema_version"], int)
            or root["schema_version"] != SCIENCE_STATE_VERSION
        ):
            raise _fail(code, "$.schema_version must equal 1", path="$.schema_version")
        study_id = _text(root["study_id"], path="$.study_id", code=code)

        hypotheses: list[HypothesisClass] = []
        for index, item in enumerate(
            _array(root["hypothesis_classes"], path="$.hypothesis_classes", code=code)
        ):
            path = f"$.hypothesis_classes[{index}]"
            value = _object(
                item,
                {"id", "description", "conclusive_rejection_limit"},
                path=path,
                code=code,
            )
            hypotheses.append(
                HypothesisClass(
                    id=_text(value["id"], path=f"{path}.id", code=code),
                    description=_text(
                        value["description"], path=f"{path}.description", code=code
                    ),
                    conclusive_rejection_limit=_integer(
                        value["conclusive_rejection_limit"],
                        path=f"{path}.conclusive_rejection_limit",
                        code=code,
                        minimum=1,
                    ),
                )
            )
        if len({item.id for item in hypotheses}) != len(hypotheses):
            raise _fail(code, "hypothesis class IDs must be unique", path="$.hypothesis_classes")
        hypotheses.sort(key=lambda item: item.id)

        surface_raw = _object(
            root["intervention_surface"],
            {"candidate_schema_digest", "allowed_json_pointers", "max_changes"},
            path="$.intervention_surface",
            code=code,
        )
        pointers = tuple(
            sorted(
                _json_pointer(item, path=f"$.intervention_surface.allowed_json_pointers[{i}]", code=code)
                for i, item in enumerate(
                    _array(
                        surface_raw["allowed_json_pointers"],
                        path="$.intervention_surface.allowed_json_pointers",
                        code=code,
                    )
                )
            )
        )
        if len(set(pointers)) != len(pointers):
            raise _fail(
                code,
                "allowed JSON pointers must be unique",
                path="$.intervention_surface.allowed_json_pointers",
            )
        max_changes = _integer(
            surface_raw["max_changes"],
            path="$.intervention_surface.max_changes",
            code=code,
            minimum=1,
        )
        if max_changes > len(pointers):
            raise _fail(
                code,
                "max_changes must not exceed the allowed pointer count",
                path="$.intervention_surface.max_changes",
            )
        intervention_surface = InterventionSurface(
            candidate_schema_digest=_digest(
                surface_raw["candidate_schema_digest"],
                path="$.intervention_surface.candidate_schema_digest",
                code=code,
            ),
            allowed_json_pointers=pointers,
            max_changes=max_changes,
        )

        scopes: list[EvaluationScope] = []
        for index, item in enumerate(
            _array(root["evaluation_scopes"], path="$.evaluation_scopes", code=code)
        ):
            path = f"$.evaluation_scopes[{index}]"
            value = _object(item, {"id", "role", "manifest_digest"}, path=path, code=code)
            role = _text(value["role"], path=f"{path}.role", code=code)
            if role not in _SCOPE_ROLES:
                raise _fail(code, f"{path}.role is unsupported", path=f"{path}.role")
            scopes.append(
                EvaluationScope(
                    id=_text(value["id"], path=f"{path}.id", code=code),
                    role=role,
                    manifest_digest=_digest(
                        value["manifest_digest"], path=f"{path}.manifest_digest", code=code
                    ),
                )
            )
        if len({item.id for item in scopes}) != len(scopes):
            raise _fail(code, "evaluation scope IDs must be unique", path="$.evaluation_scopes")
        if not any(item.role == "development" for item in scopes):
            raise _fail(
                code,
                "at least one development evaluation scope is required",
                path="$.evaluation_scopes",
            )
        scopes.sort(key=lambda item: item.id)

        frontier_raw = _object(
            root["frontier"], {"max_active_branches"}, path="$.frontier", code=code
        )
        frontier = FrontierPolicy(
            max_active_branches=_integer(
                frontier_raw["max_active_branches"],
                path="$.frontier.max_active_branches",
                code=code,
                minimum=1,
            )
        )

        stop_raw = _object(
            root["stop_policy"],
            {"on_untrusted", "on_budget_exhausted", "when_all_classes_closed"},
            path="$.stop_policy",
            code=code,
        )
        if any(stop_raw[key] != "stop" for key in stop_raw):
            raise _fail(code, "all stop_policy values must equal 'stop'", path="$.stop_policy")
        stop_policy = StopPolicy()

        change_raw = _object(
            root["change_control"],
            {"require_new_generation"},
            path="$.change_control",
            code=code,
        )
        if change_raw["require_new_generation"] is not True:
            raise _fail(
                code,
                "require_new_generation must be literal true",
                path="$.change_control.require_new_generation",
            )
        change_control = ChangeControl()

        budget_raw = _object(
            root["budget"],
            {
                "max_attempts",
                "max_retries",
                "max_elapsed_milliseconds",
                "elapsed_reservation_per_attempt_milliseconds",
                "cost_unit",
                "max_cost_microunits",
                "cost_reservation_per_attempt_microunits",
            },
            path="$.budget",
            code=code,
        )
        max_attempts = _integer(
            budget_raw["max_attempts"], path="$.budget.max_attempts", code=code, minimum=1
        )
        max_retries = _integer(
            budget_raw["max_retries"], path="$.budget.max_retries", code=code, minimum=0
        )
        if max_retries >= max_attempts:
            raise _fail(
                code,
                "max_retries must be less than max_attempts",
                path="$.budget.max_retries",
            )
        max_elapsed = _integer(
            budget_raw["max_elapsed_milliseconds"],
            path="$.budget.max_elapsed_milliseconds",
            code=code,
            minimum=1,
        )
        elapsed_reservation = _integer(
            budget_raw["elapsed_reservation_per_attempt_milliseconds"],
            path="$.budget.elapsed_reservation_per_attempt_milliseconds",
            code=code,
            minimum=1,
        )
        cost_values = (
            budget_raw["cost_unit"],
            budget_raw["max_cost_microunits"],
            budget_raw["cost_reservation_per_attempt_microunits"],
        )
        if all(value is None for value in cost_values):
            cost_unit = None
            max_cost = None
            cost_reservation = None
        elif any(value is None for value in cost_values):
            raise _fail(code, "cost budget fields must be all null or all configured", path="$.budget")
        else:
            cost_unit = _text(cost_values[0], path="$.budget.cost_unit", code=code)
            max_cost = _integer(
                cost_values[1], path="$.budget.max_cost_microunits", code=code, minimum=1
            )
            cost_reservation = _integer(
                cost_values[2],
                path="$.budget.cost_reservation_per_attempt_microunits",
                code=code,
                minimum=1,
            )
        budget = StudyBudget(
            max_attempts=max_attempts,
            max_retries=max_retries,
            max_elapsed_milliseconds=max_elapsed,
            elapsed_reservation_per_attempt_milliseconds=elapsed_reservation,
            cost_unit=cost_unit,
            max_cost_microunits=max_cost,
            cost_reservation_per_attempt_microunits=cost_reservation,
        )
        contract = cls(
            schema_version=SCIENCE_STATE_VERSION,
            study_id=study_id,
            hypothesis_classes=tuple(hypotheses),
            intervention_surface=intervention_surface,
            evaluation_scopes=tuple(scopes),
            frontier=frontier,
            stop_policy=stop_policy,
            change_control=change_control,
            budget=budget,
        )
        try:
            sha256_json(contract.to_dict())
        except (TypeError, ValueError) as exc:
            raise _fail(code, f"contract is not canonical JSON: {exc}", path="$") from exc
        return contract

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "study_id": self.study_id,
            "hypothesis_classes": [item.to_dict() for item in self.hypothesis_classes],
            "intervention_surface": self.intervention_surface.to_dict(),
            "evaluation_scopes": [item.to_dict() for item in self.evaluation_scopes],
            "frontier": self.frontier.to_dict(),
            "stop_policy": self.stop_policy.to_dict(),
            "change_control": self.change_control.to_dict(),
            "budget": self.budget.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class EvaluationSeal:
    compatibility_digest: str
    evaluator_certification_digest: str
    evaluator_review_subject_digest: str

    def __post_init__(self) -> None:
        code = "STUDY_EVALUATION_SEAL_INVALID"
        for field_name in (
            "compatibility_digest",
            "evaluator_certification_digest",
            "evaluator_review_subject_digest",
        ):
            _digest(getattr(self, field_name), path=f"$.{field_name}", code=code)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "EvaluationSeal":
        code = "STUDY_EVALUATION_SEAL_INVALID"
        value = _object(
            raw,
            {
                "compatibility_digest",
                "evaluator_certification_digest",
                "evaluator_review_subject_digest",
            },
            path="$",
            code=code,
        )
        return cls(
            compatibility_digest=_digest(
                value["compatibility_digest"], path="$.compatibility_digest", code=code
            ),
            evaluator_certification_digest=_digest(
                value["evaluator_certification_digest"],
                path="$.evaluator_certification_digest",
                code=code,
            ),
            evaluator_review_subject_digest=_digest(
                value["evaluator_review_subject_digest"],
                path="$.evaluator_review_subject_digest",
                code=code,
            ),
        )

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, str]:
        return {
            "compatibility_digest": self.compatibility_digest,
            "evaluator_certification_digest": self.evaluator_certification_digest,
            "evaluator_review_subject_digest": self.evaluator_review_subject_digest,
        }


def generation_id(
    project_id: str,
    predecessor_generation_id: str | None,
    study_contract_digest: str,
    evaluation_seal_digest: str,
) -> str:
    """Derive the exact version-one generation identity."""

    code = "STUDY_GENERATION_INVALID"
    project_id = _text(project_id, path="$.project_id", code=code)
    if predecessor_generation_id is not None:
        try:
            predecessor_generation_id = validate_namespaced_id(
                predecessor_generation_id, "generation"
            )
        except (TypeError, ValueError) as exc:
            raise _fail(
                code,
                "predecessor_generation_id must be a generation ID",
                path="$.predecessor_generation_id",
            ) from exc
    study_contract_digest = _digest(
        study_contract_digest, path="$.study_contract_digest", code=code
    )
    evaluation_seal_digest = _digest(
        evaluation_seal_digest, path="$.evaluation_seal_digest", code=code
    )
    return stable_id(
        "generation",
        project_id,
        predecessor_generation_id,
        study_contract_digest,
        evaluation_seal_digest,
    )


def new_generation_id(
    project_id: str,
    study_contract_digest: str,
    evaluation_seal_digest: str,
    *,
    predecessor_generation_id: str | None = None,
) -> str:
    """Keyword-friendly alias for :func:`generation_id`."""

    return generation_id(
        project_id,
        predecessor_generation_id,
        study_contract_digest,
        evaluation_seal_digest,
    )


def is_safe_integer(value: Any, *, minimum: int = 0) -> bool:
    """Return whether ``value`` is an interoperable integer at least ``minimum``."""

    return (
        not isinstance(value, bool)
        and isinstance(value, int)
        and minimum <= value <= MAX_SAFE_JSON_INTEGER
        and math.isfinite(value)
    )
