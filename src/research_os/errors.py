"""Stable error types used across the Research OS boundary."""


class ResearchOSError(Exception):
    """Base error for expected Research OS failures."""


class ConfigurationError(ResearchOSError):
    """The project contract is missing, invalid, or unsafe."""


class StaleAgentContextError(ConfigurationError):
    """An agent tried to act on a superseded canonical context snapshot."""

    code = "STALE_AGENT_CONTEXT"


class ProtocolError(ResearchOSError):
    """An adapter violated the process protocol."""


class IntegrityError(ResearchOSError):
    """Canonical evidence or a protected surface failed verification."""


class LifecycleError(ResearchOSError):
    """A requested lifecycle transition is invalid."""
