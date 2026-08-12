"""Versioned, domain-neutral Research OS contracts."""

from .artifacts import DESIGN_PROVENANCE as _ARTIFACT_PROVENANCE
from .artifacts import ArtifactRef
from .common import (
    CANONICAL_JSON_VERSION,
    MAX_SAFE_JSON_INTEGER,
    JSONObject,
    JSONScalar,
    JSONValue,
    canonical_json,
    canonical_json_bytes,
    decode_json_object,
    normalize_json_object,
    normalize_json_value,
    sha256_bytes,
    sha256_file,
    sha256_json,
    sha256_text,
)
from .common import DESIGN_PROVENANCE as _COMMON_PROVENANCE
from .protocol import DESIGN_PROVENANCE as _PROTOCOL_PROVENANCE
from .protocol import (
    FAILURE_CATEGORIES_BY_OPERATION,
    LEGACY_FAILURE_CATEGORIES,
    PROTOCOL_VERSION,
    AdapterRequest,
    AdapterResponse,
    FailureCategory,
    Operation,
    ProtocolError,
    ProtocolOperation,
    ProtocolRequest,
    ProtocolResponse,
    VerifyResult,
    validate_failure_category,
)
from .results import DESIGN_PROVENANCE as _RESULT_PROVENANCE
from .results import (
    GateDefinition,
    GateEvaluation,
    GateOperator,
    GateRole,
    Metric,
    MetricDirection,
    ResultEnvelope,
)
from .status import DESIGN_PROVENANCE as _STATUS_PROVENANCE
from .status import TerminalStatus

DESIGN_PROVENANCE: dict[str, tuple[str, ...]] = {
    **_COMMON_PROVENANCE,
    **_ARTIFACT_PROVENANCE,
    **_STATUS_PROVENANCE,
    **_RESULT_PROVENANCE,
    **_PROTOCOL_PROVENANCE,
}


__all__ = [
    "AdapterRequest",
    "AdapterResponse",
    "ArtifactRef",
    "CANONICAL_JSON_VERSION",
    "DESIGN_PROVENANCE",
    "FAILURE_CATEGORIES_BY_OPERATION",
    "FailureCategory",
    "GateDefinition",
    "GateEvaluation",
    "GateOperator",
    "GateRole",
    "JSONObject",
    "JSONScalar",
    "JSONValue",
    "MAX_SAFE_JSON_INTEGER",
    "Metric",
    "MetricDirection",
    "LEGACY_FAILURE_CATEGORIES",
    "Operation",
    "PROTOCOL_VERSION",
    "ProtocolError",
    "ProtocolOperation",
    "ProtocolRequest",
    "ProtocolResponse",
    "ResultEnvelope",
    "TerminalStatus",
    "VerifyResult",
    "canonical_json",
    "canonical_json_bytes",
    "decode_json_object",
    "normalize_json_object",
    "normalize_json_value",
    "sha256_bytes",
    "sha256_file",
    "sha256_json",
    "sha256_text",
    "validate_failure_category",
]
