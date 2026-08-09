"""Canonical typed proposals and candidate intervention diffs."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from research_os.contracts.common import normalize_json_value, sha256_json
from research_os.kernel.ids import stable_id, validate_namespaced_id

from .contracts import _array, _digest, _fail, _integer, _json_pointer, _object, _text

PROPOSAL_SCHEMA_VERSION = 1
PROPOSAL_ACTIONS = frozenset({"explore", "exploit", "ablate", "replicate"})
_MAX_NARRATIVE_UTF8_BYTES = 16_384
_PROPOSAL_KEYS = {
    "proposal_schema_version",
    "generation_id",
    "candidate_digest",
    "hypothesis_class_id",
    "action",
    "mechanism",
    "predicted_effect",
    "falsifier",
    "parent_experiment_id",
    "evaluation_scope_id",
    "intervention_json_pointers",
    "authorized_action",
}


def _namespaced_id(value: Any, namespace: str, *, path: str) -> str:
    code = "PROPOSAL_INVALID"
    text = _text(value, path=path, code=code)
    try:
        identifier = validate_namespaced_id(text, namespace)
    except (TypeError, ValueError) as exc:
        raise _fail(code, f"{path} must be a {namespace} ID", path=path) from exc
    if identifier != text:  # pragma: no cover - _text already rejects whitespace
        raise _fail(code, f"{path} must be a canonical {namespace} ID", path=path)
    return identifier


def _narrative(value: Any, *, path: str) -> str:
    code = "PROPOSAL_INVALID"
    text = _text(value, path=path, code=code)
    if len(text.encode("utf-8")) > _MAX_NARRATIVE_UTF8_BYTES:
        raise _fail(
            code,
            f"{path} must not exceed {_MAX_NARRATIVE_UTF8_BYTES} UTF-8 bytes",
            path=path,
        )
    return text


@dataclass(frozen=True, slots=True)
class Proposal:
    """One immutable, falsifiable experiment proposal body."""

    proposal_schema_version: int
    generation_id: str
    candidate_digest: str
    hypothesis_class_id: str
    action: str
    mechanism: str
    predicted_effect: str
    falsifier: str
    parent_experiment_id: str | None
    evaluation_scope_id: str
    intervention_json_pointers: tuple[str, ...]
    authorized_action: None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "Proposal":
        code = "PROPOSAL_INVALID"
        root = _object(raw, _PROPOSAL_KEYS, path="$", code=code)
        schema_version = _integer(
            root["proposal_schema_version"],
            path="$.proposal_schema_version",
            code=code,
            minimum=1,
        )
        if schema_version != PROPOSAL_SCHEMA_VERSION:
            raise _fail(
                code,
                "$.proposal_schema_version must equal 1",
                path="$.proposal_schema_version",
            )

        action = _text(root["action"], path="$.action", code=code)
        if action not in PROPOSAL_ACTIONS:
            raise _fail(code, "$.action is unsupported", path="$.action")

        parent_raw = root["parent_experiment_id"]
        parent_experiment_id = (
            None
            if parent_raw is None
            else _namespaced_id(
                parent_raw,
                "experiment",
                path="$.parent_experiment_id",
            )
        )

        pointers = tuple(
            sorted(
                _json_pointer(
                    item,
                    path=f"$.intervention_json_pointers[{index}]",
                    code=code,
                )
                for index, item in enumerate(
                    _array(
                        root["intervention_json_pointers"],
                        path="$.intervention_json_pointers",
                        code=code,
                        nonempty=False,
                    )
                )
            )
        )
        if len(set(pointers)) != len(pointers):
            raise _fail(
                code,
                "intervention JSON pointers must be unique",
                path="$.intervention_json_pointers",
            )
        if root["authorized_action"] is not None:
            raise _fail(
                code,
                "$.authorized_action must be literal null",
                path="$.authorized_action",
            )

        proposal = cls(
            proposal_schema_version=PROPOSAL_SCHEMA_VERSION,
            generation_id=_namespaced_id(
                root["generation_id"],
                "generation",
                path="$.generation_id",
            ),
            candidate_digest=_digest(
                root["candidate_digest"],
                path="$.candidate_digest",
                code=code,
            ),
            hypothesis_class_id=_text(
                root["hypothesis_class_id"],
                path="$.hypothesis_class_id",
                code=code,
            ),
            action=action,
            mechanism=_narrative(root["mechanism"], path="$.mechanism"),
            predicted_effect=_narrative(
                root["predicted_effect"],
                path="$.predicted_effect",
            ),
            falsifier=_narrative(root["falsifier"], path="$.falsifier"),
            parent_experiment_id=parent_experiment_id,
            evaluation_scope_id=_text(
                root["evaluation_scope_id"],
                path="$.evaluation_scope_id",
                code=code,
            ),
            intervention_json_pointers=pointers,
        )
        try:
            sha256_json(proposal.to_dict())
        except (TypeError, ValueError) as exc:
            raise _fail(code, f"proposal is not canonical JSON: {exc}", path="$") from exc
        return proposal

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposal_schema_version": self.proposal_schema_version,
            "generation_id": self.generation_id,
            "candidate_digest": self.candidate_digest,
            "hypothesis_class_id": self.hypothesis_class_id,
            "action": self.action,
            "mechanism": self.mechanism,
            "predicted_effect": self.predicted_effect,
            "falsifier": self.falsifier,
            "parent_experiment_id": self.parent_experiment_id,
            "evaluation_scope_id": self.evaluation_scope_id,
            "intervention_json_pointers": list(self.intervention_json_pointers),
            "authorized_action": None,
        }


def proposal_id(project_id: str, proposal_digest: str) -> str:
    """Derive the project-scoped identity of one canonical Proposal body."""

    code = "PROPOSAL_INVALID"
    project_id = _text(project_id, path="$.project_id", code=code)
    proposal_digest = _digest(
        proposal_digest,
        path="$.proposal_digest",
        code=code,
    )
    return stable_id("proposal", project_id, proposal_digest)


def _pointer_child(pointer: str, key: str) -> str:
    token = key.replace("~", "~0").replace("/", "~1")
    return f"{pointer}/{token}"


def _json_kind(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    raise TypeError(f"unsupported normalized JSON value: {type(value).__name__}")


def canonical_json_diff_pointers(parent: Any, candidate: Any) -> tuple[str, ...]:
    """Return canonical RFC-6901 pointers changed from ``parent`` to ``candidate``.

    Objects recurse over their key union. Added or removed object members emit
    the member pointer, while arrays and scalar/type changes are atomic at the
    current pointer. Both inputs are normalized under canonical JSON policy v1.
    """

    parent_value = normalize_json_value(parent)
    candidate_value = normalize_json_value(candidate)
    changed: list[str] = []

    def visit(left: Any, right: Any, pointer: str) -> None:
        left_kind = _json_kind(left)
        right_kind = _json_kind(right)
        if left_kind != right_kind:
            changed.append(pointer)
            return
        if left_kind == "object":
            assert isinstance(left, dict) and isinstance(right, dict)
            for key in set(left) | set(right):
                child = _pointer_child(pointer, key)
                if key not in left or key not in right:
                    changed.append(child)
                else:
                    visit(left[key], right[key], child)
            return
        if left_kind == "array":
            if sha256_json(left) != sha256_json(right):
                changed.append(pointer)
            return
        if sha256_json(left) != sha256_json(right):
            changed.append(pointer)

    visit(parent_value, candidate_value, "")
    return tuple(sorted(changed))


__all__ = [
    "PROPOSAL_ACTIONS",
    "PROPOSAL_SCHEMA_VERSION",
    "Proposal",
    "canonical_json_diff_pointers",
    "proposal_id",
]
