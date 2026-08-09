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
    "SCIENCE_STATE_VERSION",
    "EvaluationSeal",
    "GENERATION_EVENT_TYPE",
    "GenerationPlan",
    "PROPOSAL_ACTIONS",
    "PROPOSAL_SCHEMA_VERSION",
    "Proposal",
    "ScientificState",
    "ScientificStateError",
    "StudyBudget",
    "StudyContract",
    "canonical_json_diff_pointers",
    "generation_id",
    "new_generation_id",
    "plan_generation_open",
    "proposal_id",
    "reduce_scientific_state",
    "registration_payload_fields",
    "reserve_registration",
    "validate_registration",
]
