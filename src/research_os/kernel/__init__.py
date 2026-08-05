"""Event-sourced lifecycle and lineage kernel."""

from .events import EVENT_VERSION, Event, EventLog, JSONLEventLog, verify_events
from .ids import (
    namespace_prefix,
    new_experiment_id,
    new_id,
    stable_id,
    validate_namespaced_id,
)
from .lifecycle import (
    TERMINAL_STATES,
    LifecycleState,
    coerce_state,
    is_terminal,
    validate_transition,
)
from .projection import ProjectionStore, SQLiteProjection

__all__ = [
    "EVENT_VERSION",
    "Event",
    "EventLog",
    "JSONLEventLog",
    "LifecycleState",
    "ProjectionStore",
    "SQLiteProjection",
    "TERMINAL_STATES",
    "coerce_state",
    "is_terminal",
    "namespace_prefix",
    "new_experiment_id",
    "new_id",
    "stable_id",
    "validate_namespaced_id",
    "validate_transition",
    "verify_events",
]
