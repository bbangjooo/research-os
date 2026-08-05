"""Terminal experiment outcomes."""

from __future__ import annotations

from enum import Enum


class TerminalStatus(str, Enum):
    """Durable terminal state for every attempted experiment."""

    INVALID_EXPERIMENT = "INVALID_EXPERIMENT"
    INFRA_FAILED = "INFRA_FAILED"
    TIMED_OUT = "TIMED_OUT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REJECTED = "REJECTED"
    VALIDATED = "VALIDATED"
    UNTRUSTED = "UNTRUSTED"
    CANCELLED = "CANCELLED"

    @property
    def is_validated(self) -> bool:
        return self is TerminalStatus.VALIDATED

    @classmethod
    def parse(cls, value: "TerminalStatus | str") -> "TerminalStatus":
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise TypeError("terminal status must be a string")
        try:
            return cls(value)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ValueError(
                f"unknown terminal status {value!r}; expected one of: {allowed}"
            ) from exc


DESIGN_PROVENANCE: dict[str, tuple[str, ...]] = {
    "TerminalStatus": ("Experiment DAG", "Reversible ratchet"),
}
