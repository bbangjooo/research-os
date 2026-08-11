"""Provider-neutral, no-authority inputs for autonomous research."""

from .protocol import (
    DECISION_PACKET_SCHEMA_VERSION,
    MAX_DECISION_PACKET_BYTES,
    PROVIDER_DECISION_REQUEST_SCHEMA_VERSION,
    DecisionPacket,
    DecisionPacketError,
    ProviderDecisionRequest,
    RetrievalManifest,
    ValidatedDecision,
    build_decision_packet,
    build_provider_decision_request,
    build_retrieval_manifest,
    validate_decision_packet,
)
from .provider import (
    JSONSubprocessProvider,
    ProviderPortError,
    PythonDecisionProvider,
    PythonProviderPort,
)

__all__ = [
    "DECISION_PACKET_SCHEMA_VERSION",
    "MAX_DECISION_PACKET_BYTES",
    "PROVIDER_DECISION_REQUEST_SCHEMA_VERSION",
    "DecisionPacket",
    "DecisionPacketError",
    "JSONSubprocessProvider",
    "ProviderDecisionRequest",
    "ProviderPortError",
    "PythonDecisionProvider",
    "PythonProviderPort",
    "RetrievalManifest",
    "ValidatedDecision",
    "build_decision_packet",
    "build_provider_decision_request",
    "build_retrieval_manifest",
    "validate_decision_packet",
]
