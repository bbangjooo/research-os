"""Experiment lifecycle states and transition validation."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from research_os.errors import LifecycleError


class LifecycleState(StrEnum):
    REGISTERED = "REGISTERED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"

    # Stable terminal statuses from the public result contract.
    INVALID_EXPERIMENT = "INVALID_EXPERIMENT"
    INFRA_FAILED = "INFRA_FAILED"
    TIMED_OUT = "TIMED_OUT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED = "REJECTED"
    VALIDATED = "VALIDATED"
    UNTRUSTED = "UNTRUSTED"
    CANCELLED = "CANCELLED"

    # Additional generic outcomes accepted at the storage boundary.
    ACCEPTED = "ACCEPTED"
    SUCCEEDED = "SUCCEEDED"
    COMPLETED = "COMPLETED"
    INVALID = "INVALID"
    FAILED = "FAILED"
    CRASHED = "CRASHED"


TERMINAL_STATES = frozenset(
    {
        LifecycleState.ACCEPTED,
        LifecycleState.SUCCEEDED,
        LifecycleState.COMPLETED,
        LifecycleState.INVALID_EXPERIMENT,
        LifecycleState.INFRA_FAILED,
        LifecycleState.INSUFFICIENT_EVIDENCE,
        LifecycleState.REJECTED,
        LifecycleState.VALIDATED,
        LifecycleState.UNTRUSTED,
        LifecycleState.INVALID,
        LifecycleState.FAILED,
        LifecycleState.CRASHED,
        LifecycleState.TIMED_OUT,
        LifecycleState.CANCELLED,
    }
)

_ALIASES = {
    "PENDING": LifecycleState.REGISTERED,
    "CREATED": LifecycleState.REGISTERED,
    "SUCCESS": LifecycleState.SUCCEEDED,
    "PASSED": LifecycleState.SUCCEEDED,
    "COMPLETE": LifecycleState.COMPLETED,
    "TIMEOUT": LifecycleState.TIMED_OUT,
    "TIMEDOUT": LifecycleState.TIMED_OUT,
    "CANCELED": LifecycleState.CANCELLED,
    "ERROR": LifecycleState.FAILED,
}

_TRANSITIONS: dict[LifecycleState, frozenset[LifecycleState]] = {
    LifecycleState.REGISTERED: frozenset(
        {LifecycleState.QUEUED, LifecycleState.RUNNING, *TERMINAL_STATES}
    ),
    LifecycleState.QUEUED: frozenset({LifecycleState.RUNNING, *TERMINAL_STATES}),
    LifecycleState.RUNNING: TERMINAL_STATES,
    **{state: frozenset() for state in TERMINAL_STATES},
}


def coerce_state(value: Any) -> LifecycleState:
    if isinstance(value, LifecycleState):
        return value
    if isinstance(value, StrEnum):
        value = value.value
    if not isinstance(value, str) or not value.strip():
        raise LifecycleError("lifecycle state must be a non-empty string")
    normalized = value.strip().upper().replace("-", "_").replace(" ", "_")
    if normalized in _ALIASES:
        return _ALIASES[normalized]
    try:
        return LifecycleState(normalized)
    except ValueError as exc:
        raise LifecycleError(f"unknown lifecycle state: {value!r}") from exc


def validate_transition(
    current: LifecycleState | str,
    target: LifecycleState | str,
    *,
    allow_same: bool = False,
) -> LifecycleState:
    """Validate and return the normalized target lifecycle state."""

    source = coerce_state(current)
    destination = coerce_state(target)
    if source == destination:
        if allow_same:
            return destination
        raise LifecycleError(f"experiment is already {source.value!r}")
    if destination not in _TRANSITIONS[source]:
        raise LifecycleError(
            f"invalid experiment lifecycle transition: {source.value} -> {destination.value}"
        )
    return destination


def is_terminal(state: LifecycleState | str) -> bool:
    return coerce_state(state) in TERMINAL_STATES
