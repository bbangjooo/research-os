"""Stable error types used across the Research OS boundary."""

from __future__ import annotations

from collections.abc import Mapping


class ResearchOSError(Exception):
    """Base error for expected Research OS failures."""


class ConfigurationError(ResearchOSError):
    """The project contract is missing, invalid, or unsafe."""


class EvaluatorCertificationError(ConfigurationError):
    """The project has no current, passing evaluator certification."""

    code = "EVALUATOR_CERTIFICATION_REQUIRED"

    def __init__(
        self,
        message: str,
        *,
        reason: str | None = None,
        details: dict[str, object] | None = None,
    ):
        super().__init__(message)
        self.details = dict(details or {})
        if reason is not None:
            self.details.setdefault("reason", reason)


class AgentResearchNotReadyError(ConfigurationError):
    """An agent attempted research before completing project setup gates."""

    code = "AGENT_RESEARCH_NOT_READY"

    def __init__(self, message: str, *, blockers: list[str] | None = None):
        super().__init__(message)
        self.details = {"blockers": list(blockers or [])}


class GraphPolicyError(ConfigurationError):
    """A proposed experiment violates the scientific graph contract."""

    code = "GRAPH_POLICY_VIOLATION"


class ScientificStateError(ConfigurationError):
    """A versioned study contract or scientific-state transition was rejected."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ):
        if not isinstance(code, str) or not code:
            raise ValueError("scientific-state error code must be a non-empty string")
        self.code = code
        self.details = dict(details or {})
        super().__init__(message)


class StaleAgentContextError(ConfigurationError):
    """An agent tried to act on a superseded canonical context snapshot."""

    code = "STALE_AGENT_CONTEXT"


class ProtocolError(ResearchOSError):
    """An adapter violated the process protocol."""


class IntegrityError(ResearchOSError):
    """Canonical evidence or a protected surface failed verification."""


class LifecycleError(ResearchOSError):
    """A requested lifecycle transition is invalid."""
