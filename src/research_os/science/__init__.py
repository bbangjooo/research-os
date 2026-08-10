"""Versioned scientific study contracts and pure state transitions."""

from research_os.errors import ScientificStateError

from .contracts import (
    SCIENCE_STATE_VERSION,
    EvaluationSeal,
    StudyBudget,
    StudyContract,
    generation_id,
    new_generation_id,
)
from .diagnoses import (
    DIAGNOSIS_FAILURE_TYPES,
    DIAGNOSIS_RECOMMENDATIONS,
    DIAGNOSIS_SCHEMA_VERSION,
    MAX_DIAGNOSIS_NARRATIVE_UTF8_BYTES,
    ArtifactEvidenceRef,
    Diagnosis,
    DiagnosisEventPayload,
    DiagnosisObservation,
    TerminalEvidenceRef,
    default_terminal_reason_code,
    diagnosis_id,
    normalize_terminal_status,
)
from .proposals import (
    PROPOSAL_ACTIONS,
    PROPOSAL_SCHEMA_VERSION,
    Proposal,
    canonical_json_diff_pointers,
    proposal_id,
)
from .state import (
    GENERATION_EVENT_TYPE,
    GenerationPlan,
    ScientificState,
    plan_generation_open,
    reduce_scientific_state,
    registration_payload_fields,
    reserve_registration,
    validate_registration,
)

__all__ = [
    "DIAGNOSIS_FAILURE_TYPES",
    "DIAGNOSIS_RECOMMENDATIONS",
    "DIAGNOSIS_SCHEMA_VERSION",
    "SCIENCE_STATE_VERSION",
    "ArtifactEvidenceRef",
    "Diagnosis",
    "DiagnosisEventPayload",
    "DiagnosisObservation",
    "EvaluationSeal",
    "GENERATION_EVENT_TYPE",
    "GenerationPlan",
    "MAX_DIAGNOSIS_NARRATIVE_UTF8_BYTES",
    "PROPOSAL_ACTIONS",
    "PROPOSAL_SCHEMA_VERSION",
    "Proposal",
    "ScientificState",
    "ScientificStateError",
    "StudyBudget",
    "StudyContract",
    "TerminalEvidenceRef",
    "canonical_json_diff_pointers",
    "default_terminal_reason_code",
    "diagnosis_id",
    "generation_id",
    "new_generation_id",
    "normalize_terminal_status",
    "plan_generation_open",
    "proposal_id",
    "reduce_scientific_state",
    "registration_payload_fields",
    "reserve_registration",
    "validate_registration",
]
