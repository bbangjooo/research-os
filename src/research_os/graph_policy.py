"""Domain-neutral policy for scientific experiment-graph metadata.

The candidate body remains project-owned.  This module only validates the
small, kernel-owned declaration that says how one candidate relates to the
experiment graph.  Legacy registrations deliberately carry no such
declaration and remain valid.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from research_os.errors import GraphPolicyError

GRAPH_METADATA_VERSION: Final = 1
MAX_SCIENTIFIC_CHANGE_BYTES: Final = 16 * 1024

_GRAPH_METADATA_KEYS: Final = frozenset(
    {"graph_metadata_version", "graph_action", "scientific_change"}
)


class GraphAction(StrEnum):
    """The four scientific relationships supported by Research OS."""

    EXPLORE = "explore"
    EXPLOIT = "exploit"
    ABLATE = "ablate"
    REPLICATE = "replicate"

    @classmethod
    def parse(cls, value: GraphAction | str) -> GraphAction:
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise GraphPolicyError("graph_action must be a string")
        try:
            return cls(value)
        except ValueError as exc:
            allowed = ", ".join(action.value for action in cls)
            raise GraphPolicyError(
                f"unknown graph_action {value!r}; expected one of: {allowed}"
            ) from exc


@dataclass(frozen=True, slots=True)
class GraphMetadata:
    """One versioned scientific change declaration."""

    graph_action: GraphAction
    scientific_change: str
    version: int = GRAPH_METADATA_VERSION

    def to_payload(self) -> dict[str, Any]:
        return {
            "graph_metadata_version": self.version,
            "graph_action": self.graph_action.value,
            "scientific_change": self.scientific_change,
        }


def _scientific_change(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GraphPolicyError("scientific_change must be a non-empty string")
    if len(value.encode("utf-8")) > MAX_SCIENTIFIC_CHANGE_BYTES:
        raise GraphPolicyError(
            "scientific_change exceeds the "
            f"{MAX_SCIENTIFIC_CHANGE_BYTES}-byte limit"
        )
    # Preserve the declaration byte-for-byte after validation.  Retry equality
    # is deliberately exact; whitespace is not silently normalized into a
    # different canonical claim.
    return value


def graph_metadata_from_values(
    graph_action: GraphAction | str | None,
    scientific_change: str | None,
    *,
    required: bool = False,
) -> GraphMetadata | None:
    """Validate service/CLI values and return their canonical payload model.

    The arguments form an inseparable pair.  They remain optional only for
    backwards-compatible non-agent calls; callers set ``required=True`` for a
    context-token-backed new proposal.
    """

    if graph_action is None and scientific_change is None:
        if required:
            raise GraphPolicyError("graph_action and scientific_change are required")
        return None
    if graph_action is None or scientific_change is None:
        raise GraphPolicyError("graph_action and scientific_change must be provided together")
    return GraphMetadata(
        graph_action=GraphAction.parse(graph_action),
        scientific_change=_scientific_change(scientific_change),
    )


def graph_metadata_from_payload(
    payload: Mapping[str, Any],
) -> GraphMetadata | None:
    """Decode graph metadata from one registration payload.

    Absence of all three fields is the legacy representation.  Presence of any
    field opts the event into the complete version-1 contract, preventing a
    partially declared or unversioned graph relationship from replaying.
    """

    if not isinstance(payload, Mapping):
        raise GraphPolicyError("experiment registration payload must be an object")
    present = _GRAPH_METADATA_KEYS.intersection(payload)
    if not present:
        return None
    if present != _GRAPH_METADATA_KEYS:
        missing = ", ".join(sorted(_GRAPH_METADATA_KEYS - present))
        raise GraphPolicyError(f"graph metadata is incomplete; missing: {missing}")

    version = payload["graph_metadata_version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != GRAPH_METADATA_VERSION
    ):
        raise GraphPolicyError(f"graph_metadata_version must equal {GRAPH_METADATA_VERSION}")
    return GraphMetadata(
        version=version,
        graph_action=GraphAction.parse(payload["graph_action"]),
        scientific_change=_scientific_change(payload["scientific_change"]),
    )


def inherit_retry_graph_metadata(
    prior_payload: Mapping[str, Any],
    *,
    graph_action: GraphAction | str | None = None,
    scientific_change: str | None = None,
) -> GraphMetadata | None:
    """Return prior attempt metadata while refusing to relabel a retry."""

    if graph_action is not None or scientific_change is not None:
        raise GraphPolicyError(
            "retry graph metadata is inherited; do not provide graph_action or scientific_change"
        )
    return graph_metadata_from_payload(prior_payload)


def validate_retry_graph_metadata(
    metadata: GraphMetadata | None,
    prior_metadata: GraphMetadata | None,
) -> None:
    """Require exact graph-metadata inheritance between adjacent attempts."""

    if metadata != prior_metadata:
        raise GraphPolicyError(
            "retry graph metadata must exactly match the immediately prior attempt"
        )


def validate_graph_relationship(
    metadata: GraphMetadata | None,
    parent_id: str | None,
    *,
    parent_is_terminal: bool | None = None,
    compatibility_digest: str | None = None,
    parent_compatibility_digest: str | None = None,
) -> None:
    """Validate action/parent shape and any supplied parent evidence.

    The optional evidence arguments let both the service and the rebuildable
    projection apply the same policy without making this domain-neutral module
    depend on the lifecycle or storage layers.
    """

    if metadata is None:
        return
    if metadata.graph_action is GraphAction.EXPLORE:
        if parent_id is not None:
            raise GraphPolicyError("explore requires parent_id to be null")
        return

    if not isinstance(parent_id, str) or not parent_id.strip():
        raise GraphPolicyError(f"{metadata.graph_action.value} requires a parent experiment")
    if parent_is_terminal is False:
        raise GraphPolicyError(
            f"{metadata.graph_action.value} requires a terminal parent experiment"
        )
    if (
        compatibility_digest is not None
        and parent_compatibility_digest is not None
        and compatibility_digest != parent_compatibility_digest
    ):
        raise GraphPolicyError(
            f"{metadata.graph_action.value} requires a compatibility-matching parent"
        )


def validate_graph_candidate_change(
    metadata: GraphMetadata | None,
    *,
    candidate_digest: str,
    parent_candidate_digest: str | None,
) -> None:
    """Require a versioned child proposal to differ from its scientific parent."""

    if metadata is None or metadata.graph_action is GraphAction.EXPLORE:
        return
    if not isinstance(candidate_digest, str) or not candidate_digest:
        raise GraphPolicyError("candidate_digest must be a non-empty string")
    if not isinstance(parent_candidate_digest, str) or not parent_candidate_digest:
        raise GraphPolicyError(
            f"{metadata.graph_action.value} requires a parent candidate digest"
        )
    if candidate_digest == parent_candidate_digest:
        raise GraphPolicyError(
            f"{metadata.graph_action.value} candidate must differ from its parent"
        )


__all__ = [
    "GRAPH_METADATA_VERSION",
    "MAX_SCIENTIFIC_CHANGE_BYTES",
    "GraphAction",
    "GraphMetadata",
    "GraphPolicyError",
    "graph_metadata_from_payload",
    "graph_metadata_from_values",
    "inherit_retry_graph_metadata",
    "validate_graph_candidate_change",
    "validate_graph_relationship",
    "validate_retry_graph_metadata",
]
