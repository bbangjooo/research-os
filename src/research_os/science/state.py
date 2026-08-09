"""Pure replay and prospective validation for versioned scientific state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, cast

from research_os.contracts.common import canonical_json, sha256_json
from research_os.errors import LifecycleError, ScientificStateError
from research_os.kernel._canonical import strict_json_loads
from research_os.kernel.events import Event
from research_os.kernel.ids import new_experiment_id, validate_namespaced_id
from research_os.kernel.lifecycle import (
    TERMINAL_STATES,
    LifecycleState,
    coerce_state,
)

from .contracts import (
    SCIENCE_STATE_VERSION,
    EvaluationScope,
    EvaluationSeal,
    StudyContract,
    is_safe_integer,
)
from .contracts import generation_id as derive_generation_id
from .proposals import Proposal, canonical_json_diff_pointers, proposal_id

GENERATION_EVENT_TYPE = "research.study_generation_opened.v1"
_REGISTRATION_EVENT_TYPE = "EXPERIMENT_REGISTERED"
_GENERATION_PAYLOAD_KEYS = frozenset(
    {
        "science_state_version",
        "generation_id",
        "study_contract_digest",
        "evaluation_seal",
        "evaluation_seal_digest",
        "predecessor_generation_id",
        "change_reason",
        "contract",
        "authorized_action",
    }
)
_REGISTRATION_SCIENCE_KEYS = frozenset(
    {
        "science_state_version",
        "generation_id",
        "study_contract_digest",
        "evaluation_seal_digest",
        "budget_debit",
    }
)
_TYPED_REGISTRATION_KEYS = frozenset(
    {
        "proposal",
        "proposal_digest",
        "proposal_id",
        "evaluation_scope_id",
    }
)
_TYPED_BASELINE_KEYS = frozenset(
    {
        "science_state_version",
        "generation_id",
        "study_contract_digest",
        "evaluation_seal_digest",
        "evaluation_scope_id",
        "evaluation_scope",
    }
)
_LEGACY_GRAPH_KEYS = frozenset({"graph_metadata_version", "graph_action", "scientific_change"})
_BUDGET_DEBIT_KEYS = frozenset(
    {
        "attempts",
        "retries",
        "reserved_elapsed_milliseconds",
        "reserved_cost_microunits",
    }
)

_NON_RETRYABLE_TERMINAL_STATES = frozenset(
    {
        LifecycleState.ACCEPTED,
        LifecycleState.SUCCEEDED,
        LifecycleState.COMPLETED,
        LifecycleState.INVALID_EXPERIMENT,
        LifecycleState.INVALID,
        LifecycleState.REJECTED,
        LifecycleState.VALIDATED,
        LifecycleState.UNTRUSTED,
    }
)


def _error(
    code: str,
    message: str,
    **details: object,
) -> ScientificStateError:
    return ScientificStateError(code, message, details=details)


def _normalized_event_type(value: str) -> str:
    return value.strip().upper().replace(".", "_").replace("-", "_")


def _event_parts(
    event: Event | Mapping[str, Any],
    *,
    expected_project_id: str,
) -> tuple[str, Mapping[str, Any]]:
    if isinstance(event, Event):
        event_type = event.event_type
        payload: Any = event.payload
        event_project_id: Any = event.project_id
    elif isinstance(event, Mapping):
        event_type = event.get("event_type")
        payload = event.get("payload")
        event_project_id = event.get("project_id", expected_project_id)
    else:
        raise _error(
            "STUDY_EVENT_INVALID",
            "scientific state input must contain event objects",
        )
    if not isinstance(event_type, str) or not event_type.strip():
        raise _error("STUDY_EVENT_INVALID", "event_type must be non-empty text")
    if not isinstance(payload, Mapping):
        raise _error("STUDY_EVENT_INVALID", "event payload must be an object")
    if event_project_id != expected_project_id:
        raise _error(
            "STUDY_EVENT_INVALID",
            "event project does not match the scientific-state project",
            expected_project_id=expected_project_id,
            event_project_id=event_project_id,
        )
    return event_type, payload


def _literal_version(value: Any, *, code: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        raise _error(code, "science_state_version must be integer literal 1")


def _generation_identifier(value: Any, *, code: str, field: str) -> str:
    if not isinstance(value, str):
        raise _error(code, f"{field} must be a generation ID")
    try:
        identifier = validate_namespaced_id(value, "generation")
    except (TypeError, ValueError) as exc:
        raise _error(code, f"{field} must be a generation ID") from exc
    if identifier != value:
        raise _error(code, f"{field} must be a canonical generation ID")
    return identifier


@dataclass(frozen=True, slots=True)
class ScopeBaseline:
    """One active-generation baseline bound to a declared evaluation scope."""

    baseline_id: str
    generation_id: str
    compatibility_digest: str
    evaluation_scope_id: str
    evaluation_scope: EvaluationScope


@dataclass(frozen=True, slots=True)
class ScientificRegistration:
    """Canonical typed registration evidence retained for pure transitions."""

    experiment_id: str
    generation_id: str
    candidate_digest: str
    candidate_json: str
    proposal: Proposal
    proposal_digest: str
    proposal_id: str
    parent_id: str | None
    evaluation_scope_id: str
    compatibility_digest: str
    baseline_id: str
    attempt: int
    retry_of: str | None
    terminal_status: str | None = None
    retryable: bool = False

    @property
    def candidate(self) -> dict[str, Any]:
        value = strict_json_loads(self.candidate_json)
        if not isinstance(value, dict):  # pragma: no cover - constructor invariant
            raise _error(
                "STUDY_STATE_INVALID",
                "stored candidate JSON is not an object",
                experiment_id=self.experiment_id,
            )
        return cast(dict[str, Any], value)

    @property
    def is_terminal(self) -> bool:
        return self.terminal_status is not None


@dataclass(frozen=True, slots=True)
class ScientificState:
    """The replay-derived active generation and its reservation ledger."""

    project_id: str
    generation_count: int = 0
    active_generation_id: str | None = None
    contract: StudyContract | None = None
    evaluation_seal: EvaluationSeal | None = None
    attempts_used: int = 0
    retries_used: int = 0
    elapsed_reserved_milliseconds: int = 0
    cost_reserved_microunits: int | None = None
    legacy_unstructured_registrations: int = 0
    scope_baselines: tuple[ScopeBaseline, ...] = ()
    registrations: tuple[ScientificRegistration, ...] = ()
    proposal_ids: frozenset[str] = frozenset()
    used_candidate_scope_keys: frozenset[tuple[str, str, str]] = frozenset()
    replication_count: int = 0

    @property
    def study_contract_digest(self) -> str | None:
        return None if self.contract is None else self.contract.digest

    @property
    def evaluation_seal_digest(self) -> str | None:
        return None if self.evaluation_seal is None else self.evaluation_seal.digest

    @property
    def proposal_count(self) -> int:
        return len(self.proposal_ids)

    @property
    def used_candidate_scope_pairs(self) -> int:
        return len(self.used_candidate_scope_keys)

    def registration(self, experiment_id: str) -> ScientificRegistration | None:
        for registration in reversed(self.registrations):
            if registration.experiment_id == experiment_id:
                return registration
        return None

    def baseline_for_scope(
        self,
        evaluation_scope_id: str,
    ) -> ScopeBaseline | None:
        for baseline in reversed(self.scope_baselines):
            if baseline.evaluation_scope_id == evaluation_scope_id:
                return baseline
        return None

    def to_dict(self) -> dict[str, Any]:
        budget: dict[str, Any] | None
        if self.contract is None:
            budget = None
        else:
            declared = self.contract.budget
            cost: dict[str, Any] | None
            if declared.max_cost_microunits is None:
                cost = None
            else:
                reserved_cost = self.cost_reserved_microunits
                if reserved_cost is None:  # pragma: no cover - defensive invariant
                    raise _error(
                        "STUDY_STATE_INVALID",
                        "configured cost ledger cannot be null",
                    )
                cost = {
                    "unit": declared.cost_unit,
                    "limit": declared.max_cost_microunits,
                    "reserved": reserved_cost,
                    "remaining": declared.max_cost_microunits - reserved_cost,
                }
            budget = {
                "attempts": {
                    "limit": declared.max_attempts,
                    "used": self.attempts_used,
                    "remaining": declared.max_attempts - self.attempts_used,
                },
                "retries": {
                    "limit": declared.max_retries,
                    "used": self.retries_used,
                    "remaining": declared.max_retries - self.retries_used,
                },
                "elapsed_milliseconds": {
                    "limit": declared.max_elapsed_milliseconds,
                    "reserved": self.elapsed_reserved_milliseconds,
                    "remaining": (
                        declared.max_elapsed_milliseconds - self.elapsed_reserved_milliseconds
                    ),
                },
                "cost_microunits": cost,
            }
        result = {
            "science_state_version": SCIENCE_STATE_VERSION,
            "generation_count": self.generation_count,
            "active_generation_id": self.active_generation_id,
            "study_contract_digest": self.study_contract_digest,
            "evaluation_seal": (
                None if self.evaluation_seal is None else self.evaluation_seal.to_dict()
            ),
            "evaluation_seal_digest": self.evaluation_seal_digest,
            "contract": None if self.contract is None else self.contract.to_dict(),
            "budget": budget,
            "legacy_unstructured_registrations": (self.legacy_unstructured_registrations),
        }
        if self.contract is not None and self.contract.schema_version == 2:
            result.update(
                {
                    "proposal_count": self.proposal_count,
                    "replication_count": self.replication_count,
                    "used_candidate_scope_pairs": (self.used_candidate_scope_pairs),
                }
            )
        return result


@dataclass(frozen=True, slots=True)
class GenerationPlan:
    project_id: str
    generation_id: str
    append_required: bool
    contract: StudyContract
    evaluation_seal: EvaluationSeal
    predecessor_generation_id: str | None
    change_reason: str | None

    @property
    def event_type(self) -> str:
        return GENERATION_EVENT_TYPE

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "science_state_version": SCIENCE_STATE_VERSION,
            "generation_id": self.generation_id,
            "study_contract_digest": self.contract.digest,
            "evaluation_seal": self.evaluation_seal.to_dict(),
            "evaluation_seal_digest": self.evaluation_seal.digest,
            "predecessor_generation_id": self.predecessor_generation_id,
            "change_reason": self.change_reason,
            "contract": self.contract.to_dict(),
            "authorized_action": None,
        }


def plan_generation_open(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    contract: StudyContract,
    evaluation_seal: EvaluationSeal,
    predecessor_generation_id: str | None = None,
    change_reason: str | None = None,
) -> GenerationPlan:
    """Plan an idempotent first open or an explicit successor."""

    if not isinstance(contract, StudyContract):
        raise _error(
            "STUDY_CONTRACT_INVALID",
            "contract must be a validated StudyContract",
        )
    # Frozen dataclasses prevent mutation but do not make direct construction a
    # validation boundary.  Reparse here so every plan is canonical and every
    # emitted payload is accepted by the replay reducer that owns authority.
    contract = StudyContract.from_mapping(contract.to_dict())
    if not isinstance(evaluation_seal, EvaluationSeal):
        raise _error(
            "STUDY_EVALUATION_SEAL_INVALID",
            "evaluation_seal must be a validated EvaluationSeal",
        )
    evaluation_seal = EvaluationSeal.from_mapping(evaluation_seal.to_dict())
    state = reduce_scientific_state(events, project_id=project_id)
    if state.active_generation_id is None:
        if predecessor_generation_id is not None or change_reason is not None:
            raise _error(
                "STUDY_GENERATION_MISMATCH",
                "the first generation cannot declare a predecessor or change reason",
                active_generation_id=None,
                predecessor_generation_id=predecessor_generation_id,
            )
        identifier = derive_generation_id(
            project_id,
            None,
            contract.digest,
            evaluation_seal.digest,
        )
        return GenerationPlan(
            project_id,
            identifier,
            True,
            contract,
            evaluation_seal,
            None,
            None,
        )

    identical = (
        state.study_contract_digest == contract.digest
        and state.evaluation_seal_digest == evaluation_seal.digest
    )
    if identical and predecessor_generation_id is None and change_reason is None:
        return GenerationPlan(
            project_id,
            state.active_generation_id,
            False,
            contract,
            evaluation_seal,
            None,
            None,
        )
    if predecessor_generation_id != state.active_generation_id:
        raise _error(
            "STUDY_GENERATION_MISMATCH",
            "predecessor_generation_id must match the active generation",
            active_generation_id=state.active_generation_id,
            predecessor_generation_id=predecessor_generation_id,
        )
    if not isinstance(change_reason, str) or not change_reason.strip():
        raise _error(
            "STUDY_CHANGE_REASON_REQUIRED",
            "a non-empty change reason is required for a successor generation",
            active_generation_id=state.active_generation_id,
        )
    normalized_reason = change_reason.strip()
    if normalized_reason != change_reason:
        raise _error(
            "STUDY_CHANGE_REASON_REQUIRED",
            "change_reason must be trimmed",
            active_generation_id=state.active_generation_id,
        )
    if identical:
        raise _error(
            "STUDY_GENERATION_UNCHANGED",
            "an unchanged contract and evaluation seal cannot reset the budget",
            active_generation_id=state.active_generation_id,
        )
    identifier = derive_generation_id(
        project_id,
        state.active_generation_id,
        contract.digest,
        evaluation_seal.digest,
    )
    return GenerationPlan(
        project_id,
        identifier,
        True,
        contract,
        evaluation_seal,
        state.active_generation_id,
        change_reason,
    )


def registration_payload_fields(
    state: ScientificState,
    *,
    retry_of: str | None,
) -> dict[str, Any]:
    """Return the complete contract-fixed science bundle for registration."""

    if (
        state.active_generation_id is None
        or state.contract is None
        or state.evaluation_seal is None
    ):
        return {}
    budget = state.contract.budget
    return {
        "science_state_version": SCIENCE_STATE_VERSION,
        "generation_id": state.active_generation_id,
        "study_contract_digest": state.contract.digest,
        "evaluation_seal_digest": state.evaluation_seal.digest,
        "budget_debit": {
            "attempts": 1,
            "retries": int(retry_of is not None),
            "reserved_elapsed_milliseconds": (budget.elapsed_reservation_per_attempt_milliseconds),
            "reserved_cost_microunits": (budget.cost_reservation_per_attempt_microunits),
        },
    }


def _registration_debit(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> tuple[int, int, int, int | None]:
    if state.contract is None or state.active_generation_id is None:
        raise _error(
            "STUDY_GENERATION_REQUIRED",
            "a versioned registration requires an active study generation",
        )
    present = _REGISTRATION_SCIENCE_KEYS.intersection(payload)
    if not present:
        raise _error(
            "STUDY_GENERATION_REQUIRED",
            "registration must bind the active study generation",
            active_generation_id=state.active_generation_id,
        )
    if present != _REGISTRATION_SCIENCE_KEYS:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "registration has a partial scientific-state bundle",
            missing_fields=sorted(_REGISTRATION_SCIENCE_KEYS - present),
        )
    if "authorized_action" not in payload or payload["authorized_action"] is not None:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "versioned registration authorized_action must be present and null",
        )
    retry_of = payload.get("retry_of")
    if retry_of is not None and (not isinstance(retry_of, str) or not retry_of.strip()):
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "retry_of must be null or a non-empty experiment ID",
        )
    _literal_version(
        payload["science_state_version"],
        code="STUDY_REGISTRATION_INVALID",
    )
    proposed_generation_id = _generation_identifier(
        payload["generation_id"],
        code="STUDY_REGISTRATION_INVALID",
        field="generation_id",
    )
    for field in ("study_contract_digest", "evaluation_seal_digest"):
        value = payload[field]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise _error(
                "STUDY_REGISTRATION_INVALID",
                f"{field} must be a lowercase SHA-256 digest",
            )
    debit = payload["budget_debit"]
    if not isinstance(debit, Mapping) or set(debit) != _BUDGET_DEBIT_KEYS:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "budget_debit must have exact version-one fields",
        )
    attempts = debit["attempts"]
    retries = debit["retries"]
    elapsed = debit["reserved_elapsed_milliseconds"]
    cost = debit["reserved_cost_microunits"]
    if (
        not is_safe_integer(attempts, minimum=0)
        or not is_safe_integer(retries, minimum=0)
        or not is_safe_integer(elapsed, minimum=0)
        or (cost is not None and not is_safe_integer(cost, minimum=0))
    ):
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "budget_debit values must be null or nonnegative safe integers",
        )
    expected = registration_payload_fields(
        state,
        retry_of=retry_of,
    )["budget_debit"]
    if dict(debit) != expected:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "budget_debit does not match the active contract reservation",
            expected_budget_debit=expected,
            observed_budget_debit=dict(debit),
        )
    if proposed_generation_id != state.active_generation_id:
        raise _error(
            "STUDY_GENERATION_MISMATCH",
            "registration generation does not match the active generation",
            active_generation_id=state.active_generation_id,
            registration_generation_id=proposed_generation_id,
        )
    if payload["study_contract_digest"] != state.study_contract_digest:
        raise _error(
            "STUDY_CONTRACT_MISMATCH",
            "registration contract digest does not match the active generation",
            active_study_contract_digest=state.study_contract_digest,
            registration_study_contract_digest=payload["study_contract_digest"],
        )
    if payload["evaluation_seal_digest"] != state.evaluation_seal_digest:
        raise _error(
            "STUDY_EVALUATION_SEAL_MISMATCH",
            "registration evaluation seal does not match the active generation",
            active_evaluation_seal_digest=state.evaluation_seal_digest,
            registration_evaluation_seal_digest=payload["evaluation_seal_digest"],
        )
    return int(attempts), int(retries), int(elapsed), None if cost is None else int(cost)


def _evaluation_scope(
    state: ScientificState,
    evaluation_scope_id: str,
) -> EvaluationScope | None:
    if state.contract is None:
        return None
    for scope in state.contract.evaluation_scopes:
        if scope.id == evaluation_scope_id:
            return scope
    return None


def _typed_registration_evidence(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> ScientificRegistration | None:
    """Recompute one registration's canonical typed sibling evidence."""

    assert state.contract is not None
    present = _TYPED_REGISTRATION_KEYS.intersection(payload)
    if state.contract.schema_version == 1:
        if present:
            raise _error(
                "PROPOSAL_CONTRACT_VERSION_REQUIRED",
                "typed Proposal evidence requires StudyContract version 2",
            )
        return None
    if state.contract.schema_version != 2:  # pragma: no cover - contract parser guards
        raise _error(
            "STUDY_CONTRACT_INVALID",
            "active study contract has an unsupported schema version",
        )
    if not present:
        raise _error(
            "PROPOSAL_REQUIRED",
            "StudyContract version 2 registration requires a typed Proposal",
        )
    if present != _TYPED_REGISTRATION_KEYS:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "registration has a partial typed Proposal bundle",
            missing_fields=sorted(_TYPED_REGISTRATION_KEYS - present),
        )
    graph_fields = _LEGACY_GRAPH_KEYS.intersection(payload)
    if graph_fields:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "typed Proposal registration cannot contain legacy graph metadata",
            present_fields=sorted(graph_fields),
        )

    candidate_value = payload.get("candidate")
    if not isinstance(candidate_value, Mapping):
        raise _error(
            "CANDIDATE_DIGEST_MISMATCH",
            "typed registration candidate body must be an object",
        )
    try:
        candidate_digest = sha256_json(candidate_value)
        candidate_json = canonical_json(candidate_value)
    except (TypeError, ValueError) as exc:
        raise _error(
            "CANDIDATE_DIGEST_MISMATCH",
            "typed registration candidate body is not canonical JSON",
        ) from exc
    if payload.get("candidate_digest") != candidate_digest:
        raise _error(
            "CANDIDATE_DIGEST_MISMATCH",
            "registration candidate digest does not match its canonical body",
            expected_candidate_digest=candidate_digest,
            observed_candidate_digest=payload.get("candidate_digest"),
        )

    proposal_raw = payload.get("proposal")
    proposal = Proposal.from_mapping(cast(Mapping[str, Any], proposal_raw))
    expected_proposal_digest = proposal.digest
    if payload.get("proposal_digest") != expected_proposal_digest:
        raise _error(
            "PROPOSAL_DIGEST_MISMATCH",
            "registration Proposal digest does not match its canonical body",
            expected_proposal_digest=expected_proposal_digest,
            observed_proposal_digest=payload.get("proposal_digest"),
        )
    expected_proposal_id = proposal_id(
        state.project_id,
        expected_proposal_digest,
    )
    if payload.get("proposal_id") != expected_proposal_id:
        raise _error(
            "PROPOSAL_ID_MISMATCH",
            "registration Proposal ID does not match its canonical identity",
            expected_proposal_id=expected_proposal_id,
            observed_proposal_id=payload.get("proposal_id"),
        )

    if (
        proposal.generation_id != payload.get("generation_id")
        or proposal.generation_id != state.active_generation_id
    ):
        raise _error(
            "PROPOSAL_GENERATION_MISMATCH",
            "Proposal generation does not match the registration and active generation",
            active_generation_id=state.active_generation_id,
            registration_generation_id=payload.get("generation_id"),
            proposal_generation_id=proposal.generation_id,
        )
    if (
        proposal.candidate_digest != payload.get("candidate_digest")
        or proposal.candidate_digest != candidate_digest
    ):
        raise _error(
            "PROPOSAL_CANDIDATE_MISMATCH",
            "Proposal candidate digest does not match the registration candidate",
            registration_candidate_digest=payload.get("candidate_digest"),
            proposal_candidate_digest=proposal.candidate_digest,
        )
    parent_id = payload.get("parent_id")
    if parent_id != proposal.parent_experiment_id:
        raise _error(
            "PROPOSAL_PARENT_MISMATCH",
            "flat registration parent does not match the Proposal parent",
            registration_parent_id=parent_id,
            proposal_parent_experiment_id=proposal.parent_experiment_id,
        )
    evaluation_scope_id = payload.get("evaluation_scope_id")
    if evaluation_scope_id != proposal.evaluation_scope_id:
        raise _error(
            "PROPOSAL_EVALUATION_SCOPE_MISMATCH",
            "flat registration scope does not match the Proposal scope",
            registration_evaluation_scope_id=evaluation_scope_id,
            proposal_evaluation_scope_id=proposal.evaluation_scope_id,
        )

    compatibility_digest = payload.get("compatibility_digest")
    active_compatibility = (
        None if state.evaluation_seal is None else state.evaluation_seal.compatibility_digest
    )
    if compatibility_digest != active_compatibility:
        raise _error(
            "STUDY_EVALUATION_SEAL_MISMATCH",
            "registration compatibility does not match the active evaluation seal",
            active_compatibility_digest=active_compatibility,
            registration_compatibility_digest=compatibility_digest,
        )
    attempt = payload.get("attempt", 1)
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "typed registration attempt must be a positive integer",
        )
    retry_of = payload.get("retry_of")
    if retry_of is None and attempt != 1:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "a first typed registration must use attempt 1",
        )
    if retry_of is not None and attempt == 1:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "a typed retry cannot use attempt 1",
        )

    expected_experiment_id = new_experiment_id(
        state.project_id,
        candidate_digest,
        compatibility_digest=cast(str, compatibility_digest),
        parent_id=proposal.parent_experiment_id,
        generation_id=proposal.generation_id,
        evaluation_scope_id=proposal.evaluation_scope_id,
        attempt=attempt,
    )
    experiment_id = payload.get("experiment_id")
    if experiment_id != expected_experiment_id:
        raise _error(
            "EXPERIMENT_ID_MISMATCH",
            "typed experiment ID does not match its canonical scoped identity",
            expected_experiment_id=expected_experiment_id,
            observed_experiment_id=experiment_id,
        )
    baseline_id = payload.get("baseline_id")
    if not isinstance(baseline_id, str) or not baseline_id.strip():
        raise _error(
            "STUDY_SCOPE_BASELINE_REQUIRED",
            "typed registration requires a scope-bound baseline",
            evaluation_scope_id=proposal.evaluation_scope_id,
        )

    return ScientificRegistration(
        experiment_id=expected_experiment_id,
        generation_id=proposal.generation_id,
        candidate_digest=candidate_digest,
        candidate_json=candidate_json,
        proposal=proposal,
        proposal_digest=expected_proposal_digest,
        proposal_id=expected_proposal_id,
        parent_id=proposal.parent_experiment_id,
        evaluation_scope_id=proposal.evaluation_scope_id,
        compatibility_digest=cast(str, compatibility_digest),
        baseline_id=baseline_id,
        attempt=attempt,
        retry_of=cast(str | None, retry_of),
    )


def _require_scope_baseline(
    state: ScientificState,
    registration: ScientificRegistration,
) -> None:
    baseline = next(
        (
            item
            for item in reversed(state.scope_baselines)
            if item.baseline_id == registration.baseline_id
        ),
        None,
    )
    if (
        baseline is None
        or baseline.generation_id != registration.generation_id
        or baseline.compatibility_digest != registration.compatibility_digest
        or baseline.evaluation_scope_id != registration.evaluation_scope_id
    ):
        raise _error(
            "STUDY_SCOPE_BASELINE_REQUIRED",
            "typed registration requires a trusted baseline for the same generation and scope",
            baseline_id=registration.baseline_id,
            evaluation_scope_id=registration.evaluation_scope_id,
        )


def _validate_retry_registration(
    state: ScientificState,
    registration: ScientificRegistration,
) -> None:
    assert registration.retry_of is not None
    prior = state.registration(registration.retry_of)
    if prior is None:
        raise _error(
            "PROPOSAL_RETRY_MISMATCH",
            "typed retry does not reference a canonical prior registration",
        )
    related = tuple(
        item
        for item in state.registrations
        if item.proposal_id == prior.proposal_id
        and item.candidate_digest == prior.candidate_digest
        and item.evaluation_scope_id == prior.evaluation_scope_id
    )
    exact_inheritance = (
        prior.is_terminal
        and prior.retryable
        and bool(related)
        and related[-1].experiment_id == prior.experiment_id
        and registration.attempt == prior.attempt + 1
        and registration.generation_id == prior.generation_id
        and registration.candidate_digest == prior.candidate_digest
        and registration.candidate_json == prior.candidate_json
        and registration.proposal == prior.proposal
        and registration.proposal_digest == prior.proposal_digest
        and registration.proposal_id == prior.proposal_id
        and registration.parent_id == prior.parent_id
        and registration.evaluation_scope_id == prior.evaluation_scope_id
        and registration.compatibility_digest == prior.compatibility_digest
    )
    if not exact_inheritance:
        raise _error(
            "PROPOSAL_RETRY_MISMATCH",
            "typed retry must inherit the immediately prior Proposal and scope exactly",
            retry_of=registration.retry_of,
        )
    _require_scope_baseline(state, registration)


def _validate_first_typed_registration(
    state: ScientificState,
    registration: ScientificRegistration,
) -> bool:
    assert state.contract is not None
    proposal = registration.proposal
    hypothesis_ids = {item.id for item in state.contract.hypothesis_classes}
    if proposal.hypothesis_class_id not in hypothesis_ids:
        raise _error(
            "PROPOSAL_HYPOTHESIS_CLASS_UNKNOWN",
            "Proposal hypothesis class is not declared by the active contract",
            hypothesis_class_id=proposal.hypothesis_class_id,
        )
    scope = _evaluation_scope(state, proposal.evaluation_scope_id)
    if scope is None:
        raise _error(
            "PROPOSAL_EVALUATION_SCOPE_UNKNOWN",
            "Proposal evaluation scope is not declared by the active contract",
            evaluation_scope_id=proposal.evaluation_scope_id,
        )

    iterative = proposal.action in {"explore", "exploit", "ablate"}
    if iterative and scope.role not in {"development", "diagnostic"}:
        raise _error(
            "PROPOSAL_SCOPE_ROLE_MISMATCH",
            "iterative Proposal requires a development or diagnostic scope",
            action=proposal.action,
            evaluation_scope_id=scope.id,
            evaluation_scope_role=scope.role,
        )
    if proposal.action == "replicate" and scope.role != "replication":
        raise _error(
            "PROPOSAL_SCOPE_ROLE_MISMATCH",
            "replication Proposal requires a replication scope",
            evaluation_scope_id=scope.id,
            evaluation_scope_role=scope.role,
        )

    pointers = proposal.intervention_json_pointers
    surface = state.contract.intervention_surface
    if proposal.action == "replicate":
        if pointers:
            raise _error(
                "PROPOSAL_INTERVENTION_INVALID",
                "replication Proposal intervention pointers must be empty",
            )
    elif (
        not pointers
        or len(pointers) > surface.max_changes
        or not set(pointers).issubset(surface.allowed_json_pointers)
    ):
        raise _error(
            "PROPOSAL_INTERVENTION_INVALID",
            "Proposal interventions exceed or escape the declared surface",
            declared_json_pointers=list(pointers),
        )

    if proposal.action == "explore":
        if registration.parent_id is not None:
            raise _error(
                "PROPOSAL_PARENT_MISMATCH",
                "explore Proposal requires a null parent",
            )
        parent = None
    else:
        if registration.parent_id is None:
            raise _error(
                "PROPOSAL_PARENT_MISMATCH",
                f"{proposal.action} Proposal requires a parent experiment",
            )
        parent = state.registration(registration.parent_id)
        if parent is None:
            raise _error(
                "PROPOSAL_PARENT_MISMATCH",
                "Proposal parent is not registered in the active generation",
                parent_experiment_id=registration.parent_id,
            )
        if not parent.is_terminal:
            raise _error(
                "PROPOSAL_PARENT_NOT_TERMINAL",
                "Proposal parent must have terminal evidence",
                parent_experiment_id=registration.parent_id,
            )
        if parent.compatibility_digest != registration.compatibility_digest:
            raise _error(
                "PROPOSAL_PARENT_COMPATIBILITY_MISMATCH",
                "Proposal parent must share the active compatibility seal",
                parent_experiment_id=registration.parent_id,
            )

    if proposal.action in {"exploit", "ablate"}:
        assert parent is not None
        if registration.candidate_digest == parent.candidate_digest:
            raise _error(
                "PROPOSAL_CANDIDATE_CHANGE_REQUIRED",
                f"{proposal.action} Proposal must change the parent candidate",
            )
        observed = canonical_json_diff_pointers(
            parent.candidate,
            registration.candidate,
        )
        if pointers != observed:
            raise _error(
                "PROPOSAL_INTERVENTION_MISMATCH",
                "declared intervention pointers do not match the canonical candidate diff",
                declared_json_pointers=list(pointers),
                observed_json_pointers=list(observed),
            )
    elif proposal.action == "replicate":
        assert parent is not None
        if (
            registration.candidate_digest != parent.candidate_digest
            or registration.candidate_json != parent.candidate_json
        ):
            raise _error(
                "PROPOSAL_REPLICATION_CANDIDATE_MISMATCH",
                "replication requires the exact frozen parent candidate",
            )
        if proposal.hypothesis_class_id != parent.proposal.hypothesis_class_id:
            raise _error(
                "PROPOSAL_REPLICATION_CLASS_MISMATCH",
                "replication must preserve the parent hypothesis class",
            )
        parent_scope = _evaluation_scope(state, parent.evaluation_scope_id)
        if (
            parent_scope is None
            or scope.id == parent_scope.id
            or scope.manifest_digest == parent_scope.manifest_digest
        ):
            raise _error(
                "PROPOSAL_REPLICATION_SCOPE_UNCHANGED",
                "replication requires a distinct preregistered scope",
            )

    _require_scope_baseline(state, registration)
    uniqueness_key = (
        registration.generation_id,
        registration.candidate_digest,
        registration.evaluation_scope_id,
    )
    if uniqueness_key in state.used_candidate_scope_keys:
        raise _error(
            "PROPOSAL_EVALUATION_SCOPE_REUSED",
            "candidate has already used this evaluation scope in the active generation",
            generation_id=registration.generation_id,
            candidate_digest=registration.candidate_digest,
            evaluation_scope_id=registration.evaluation_scope_id,
        )
    return proposal.action == "replicate"


def _validated_registration(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> tuple[tuple[int, int, int, int | None], ScientificRegistration | None, bool]:
    debit = _registration_debit(state, payload)
    registration = _typed_registration_evidence(state, payload)
    if registration is None:
        return debit, None, False
    if registration.retry_of is not None:
        _validate_retry_registration(state, registration)
        return debit, registration, False
    is_replication = _validate_first_typed_registration(state, registration)
    return debit, registration, is_replication


def validate_registration(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> None:
    """Validate binding, Proposal semantics, and debit without consuming it."""

    _validated_registration(state, payload)


def _budget_exceeded(
    code: str,
    state: ScientificState,
    *,
    dimension: str,
    limit: int,
    reserved: int,
    requested: int,
) -> ScientificStateError:
    return _error(
        code,
        f"{dimension} reservation exceeds the active generation budget",
        generation_id=state.active_generation_id,
        dimension=dimension,
        limit=limit,
        reserved=reserved,
        requested=requested,
    )


def reserve_registration(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> ScientificState:
    """Validate and non-refundably reserve one versioned registration."""

    debit, registration, is_replication = _validated_registration(state, payload)
    attempts, retries, elapsed, cost = debit
    assert state.contract is not None  # guarded by _registration_debit
    budget = state.contract.budget
    next_attempts = state.attempts_used + attempts
    if next_attempts > budget.max_attempts:
        raise _budget_exceeded(
            "BUDGET_ATTEMPTS_EXCEEDED",
            state,
            dimension="attempts",
            limit=budget.max_attempts,
            reserved=state.attempts_used,
            requested=attempts,
        )
    next_retries = state.retries_used + retries
    if next_retries > budget.max_retries:
        raise _budget_exceeded(
            "BUDGET_RETRIES_EXCEEDED",
            state,
            dimension="retries",
            limit=budget.max_retries,
            reserved=state.retries_used,
            requested=retries,
        )
    next_elapsed = state.elapsed_reserved_milliseconds + elapsed
    if next_elapsed > budget.max_elapsed_milliseconds:
        raise _budget_exceeded(
            "BUDGET_ELAPSED_EXCEEDED",
            state,
            dimension="elapsed_milliseconds",
            limit=budget.max_elapsed_milliseconds,
            reserved=state.elapsed_reserved_milliseconds,
            requested=elapsed,
        )
    if budget.max_cost_microunits is None:
        if cost is not None or state.cost_reserved_microunits is not None:
            raise _error(
                "STUDY_REGISTRATION_INVALID",
                "an unconfigured cost ledger must remain null",
            )
        next_cost = None
    else:
        if cost is None or state.cost_reserved_microunits is None:
            raise _error(
                "STUDY_REGISTRATION_INVALID",
                "a configured cost ledger requires a fixed reservation",
            )
        next_cost = state.cost_reserved_microunits + cost
        if next_cost > budget.max_cost_microunits:
            raise _budget_exceeded(
                "BUDGET_COST_EXCEEDED",
                state,
                dimension="cost_microunits",
                limit=budget.max_cost_microunits,
                reserved=state.cost_reserved_microunits,
                requested=cost,
            )
    registrations = state.registrations
    proposal_ids = state.proposal_ids
    used_candidate_scope_keys = state.used_candidate_scope_keys
    replication_count = state.replication_count
    if registration is not None:
        registrations = (*registrations, registration)
        proposal_ids = proposal_ids | {registration.proposal_id}
        if registration.retry_of is None:
            used_candidate_scope_keys = used_candidate_scope_keys | {
                (
                    registration.generation_id,
                    registration.candidate_digest,
                    registration.evaluation_scope_id,
                )
            }
            replication_count += int(is_replication)
    return replace(
        state,
        attempts_used=next_attempts,
        retries_used=next_retries,
        elapsed_reserved_milliseconds=next_elapsed,
        cost_reserved_microunits=next_cost,
        registrations=registrations,
        proposal_ids=frozenset(proposal_ids),
        used_candidate_scope_keys=frozenset(used_candidate_scope_keys),
        replication_count=replication_count,
    )


def _apply_scope_baseline(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> ScientificState:
    present = _TYPED_BASELINE_KEYS.intersection(payload)
    if state.active_generation_id is None or state.contract is None:
        if present:
            raise _error(
                "STUDY_GENERATION_REQUIRED",
                "scope-bound baseline requires an active study generation",
            )
        return state
    if state.contract.schema_version == 1:
        if present:
            raise _error(
                "STUDY_SCOPE_CONTRACT_VERSION_REQUIRED",
                "evaluation-scoped baseline requires StudyContract version 2",
            )
        return state
    has_scope_id = "evaluation_scope_id" in payload
    has_scope_body = "evaluation_scope" in payload
    if not has_scope_id and not has_scope_body:
        # Legacy unscoped baselines remain replayable but cannot authorize a
        # typed registration because no ScopeBaseline record is created.
        return state
    if has_scope_id is not has_scope_body:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "scope-bound baseline has an incomplete evaluation-scope bundle",
        )
    if present != _TYPED_BASELINE_KEYS:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "scope-bound baseline has a partial scientific-state bundle",
            missing_fields=sorted(_TYPED_BASELINE_KEYS - present),
        )
    _literal_version(
        payload["science_state_version"],
        code="STUDY_REGISTRATION_INVALID",
    )
    if payload["generation_id"] != state.active_generation_id:
        raise _error(
            "STUDY_GENERATION_MISMATCH",
            "baseline generation does not match the active generation",
        )
    if payload["study_contract_digest"] != state.study_contract_digest:
        raise _error(
            "STUDY_CONTRACT_MISMATCH",
            "baseline contract digest does not match the active generation",
        )
    if payload["evaluation_seal_digest"] != state.evaluation_seal_digest:
        raise _error(
            "STUDY_EVALUATION_SEAL_MISMATCH",
            "baseline evaluation seal does not match the active generation",
        )
    evaluation_scope_id = payload["evaluation_scope_id"]
    if not isinstance(evaluation_scope_id, str):
        raise _error(
            "STUDY_EVALUATION_SCOPE_UNKNOWN",
            "baseline evaluation scope ID must be text",
        )
    scope = _evaluation_scope(state, evaluation_scope_id)
    if scope is None:
        raise _error(
            "STUDY_EVALUATION_SCOPE_UNKNOWN",
            "baseline evaluation scope is not declared by the active contract",
            evaluation_scope_id=evaluation_scope_id,
        )
    if scope.role == "holdout":
        raise _error(
            "STUDY_SCOPE_BASELINE_FORBIDDEN",
            "holdout scope cannot be consumed by the iterative baseline path",
            evaluation_scope_id=evaluation_scope_id,
        )
    if payload["evaluation_scope"] != scope.to_dict():
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "baseline evaluation scope body does not match the active contract",
        )
    compatibility_digest = payload.get("compatibility_digest")
    active_compatibility = (
        None if state.evaluation_seal is None else state.evaluation_seal.compatibility_digest
    )
    if compatibility_digest != active_compatibility:
        raise _error(
            "STUDY_EVALUATION_SEAL_MISMATCH",
            "baseline compatibility does not match the active evaluation seal",
        )
    if payload.get("authorized_action") is not None:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "scope-bound baseline authorized_action must be null",
        )
    baseline_id = payload.get("baseline_id")
    if not isinstance(baseline_id, str) or not baseline_id.strip():
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "scope-bound baseline requires a non-empty baseline ID",
        )
    if any(item.baseline_id == baseline_id for item in state.scope_baselines):
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "scope-bound baseline ID is already present",
            baseline_id=baseline_id,
        )
    baseline = ScopeBaseline(
        baseline_id=baseline_id,
        generation_id=state.active_generation_id,
        compatibility_digest=cast(str, compatibility_digest),
        evaluation_scope_id=evaluation_scope_id,
        evaluation_scope=scope,
    )
    return replace(state, scope_baselines=(*state.scope_baselines, baseline))


def _terminal_retryable(
    status: LifecycleState,
    payload: Mapping[str, Any],
) -> bool:
    if status in _NON_RETRYABLE_TERMINAL_STATES:
        return False
    if status in {LifecycleState.TIMED_OUT, LifecycleState.CANCELLED}:
        return True
    if (
        status is LifecycleState.INFRA_FAILED
        and payload.get("reason_code") == "RECOVERED_INTERRUPTED_RUN"
    ):
        return True
    error = payload.get("error")
    expected_category = {
        LifecycleState.INFRA_FAILED: "INFRASTRUCTURE",
        LifecycleState.INSUFFICIENT_EVIDENCE: "INSUFFICIENT_EVIDENCE",
    }.get(status)
    return (
        expected_category is not None
        and isinstance(error, Mapping)
        and error.get("type") == "AdapterOperationError"
        and error.get("category") == expected_category
        and error.get("code") == payload.get("reason_code")
        and error.get("retryable") is True
    )


def _apply_terminal_evidence(
    state: ScientificState,
    event_type: str,
    payload: Mapping[str, Any],
) -> ScientificState:
    if state.contract is None or state.contract.schema_version != 2:
        return state
    experiment_id = payload.get("experiment_id", payload.get("id"))
    if not isinstance(experiment_id, str):
        return state
    registration = state.registration(experiment_id)
    if registration is None:
        return state
    if event_type == "EXPERIMENT_TERMINATED":
        target_value = payload.get(
            "status",
            payload.get("state", payload.get("outcome")),
        )
    else:
        target_value = payload.get("status", payload.get("state"))
    try:
        target = coerce_state(target_value)
    except LifecycleError as exc:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "typed experiment terminal evidence has an invalid status",
            experiment_id=experiment_id,
        ) from exc
    if target not in TERMINAL_STATES:
        if event_type == "EXPERIMENT_STATUS_CHANGED":
            return state
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "EXPERIMENT_TERMINATED must declare a terminal status",
            experiment_id=experiment_id,
        )
    if registration.is_terminal:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "typed experiment has duplicate terminal evidence",
            experiment_id=experiment_id,
        )
    if "attempt" in payload and payload["attempt"] != registration.attempt:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "terminal attempt does not match its typed registration",
            experiment_id=experiment_id,
        )
    if "retry_of" in payload and payload["retry_of"] != registration.retry_of:
        raise _error(
            "STUDY_REGISTRATION_INVALID",
            "terminal retry_of does not match its typed registration",
            experiment_id=experiment_id,
        )
    retryable = _terminal_retryable(target, payload)
    if "retryable" in payload:
        declared = payload["retryable"]
        if not isinstance(declared, bool) or declared is not retryable:
            raise _error(
                "STUDY_REGISTRATION_INVALID",
                "terminal retryable metadata conflicts with terminal evidence",
                experiment_id=experiment_id,
            )
    updated = replace(
        registration,
        terminal_status=target.value,
        retryable=retryable,
    )
    registrations = tuple(
        updated if item.experiment_id == experiment_id else item for item in state.registrations
    )
    return replace(state, registrations=registrations)


def _apply_generation(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> ScientificState:
    code = "STUDY_GENERATION_INVALID"
    if set(payload) != _GENERATION_PAYLOAD_KEYS:
        raise _error(
            code,
            "generation payload must have exact version-one fields",
            missing_fields=sorted(_GENERATION_PAYLOAD_KEYS - set(payload)),
            unknown_fields=sorted(set(payload) - _GENERATION_PAYLOAD_KEYS),
        )
    _literal_version(payload["science_state_version"], code=code)
    if payload["authorized_action"] is not None:
        raise _error(code, "generation authorized_action must be null")
    contract_raw = payload["contract"]
    seal_raw = payload["evaluation_seal"]
    if not isinstance(contract_raw, Mapping) or not isinstance(seal_raw, Mapping):
        raise _error(code, "generation contract and evaluation_seal must be objects")
    contract = StudyContract.from_mapping(contract_raw)
    evaluation_seal = EvaluationSeal.from_mapping(seal_raw)
    if payload["study_contract_digest"] != contract.digest:
        raise _error(code, "generation contract digest does not match its contract")
    if payload["evaluation_seal_digest"] != evaluation_seal.digest:
        raise _error(code, "generation evaluation seal digest does not match its seal")
    predecessor = payload["predecessor_generation_id"]
    reason = payload["change_reason"]
    if state.active_generation_id is None:
        if predecessor is not None or reason is not None:
            raise _error(
                "STUDY_GENERATION_MISMATCH",
                "the first generation must have null predecessor and change reason",
            )
    else:
        if predecessor != state.active_generation_id:
            raise _error(
                "STUDY_GENERATION_MISMATCH",
                "generation predecessor does not match the active generation",
                active_generation_id=state.active_generation_id,
                predecessor_generation_id=predecessor,
            )
        if not isinstance(reason, str) or not reason.strip() or reason != reason.strip():
            raise _error(
                "STUDY_CHANGE_REASON_REQUIRED",
                "a trimmed non-empty change reason is required",
            )
        if (
            contract.digest == state.study_contract_digest
            and evaluation_seal.digest == state.evaluation_seal_digest
        ):
            raise _error(
                "STUDY_GENERATION_UNCHANGED",
                "an unchanged successor cannot reset the generation budget",
            )
    expected_id = derive_generation_id(
        state.project_id,
        None if state.active_generation_id is None else state.active_generation_id,
        contract.digest,
        evaluation_seal.digest,
    )
    observed_id = _generation_identifier(payload["generation_id"], code=code, field="generation_id")
    if observed_id != expected_id:
        raise _error(
            code,
            "generation_id does not match the canonical generation identity",
            expected_generation_id=expected_id,
            observed_generation_id=observed_id,
        )
    return ScientificState(
        project_id=state.project_id,
        generation_count=state.generation_count + 1,
        active_generation_id=observed_id,
        contract=contract,
        evaluation_seal=evaluation_seal,
        attempts_used=0,
        retries_used=0,
        elapsed_reserved_milliseconds=0,
        cost_reserved_microunits=(None if contract.budget.max_cost_microunits is None else 0),
        legacy_unstructured_registrations=(state.legacy_unstructured_registrations),
    )


def reduce_scientific_state(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
) -> ScientificState:
    """Replay scientific state from canonical events without I/O or clocks."""

    if not isinstance(project_id, str) or not project_id.strip():
        raise _error("STUDY_STATE_INVALID", "project_id must be non-empty text")
    state = ScientificState(project_id=project_id)
    for event in events:
        event_type, payload = _event_parts(
            event,
            expected_project_id=project_id,
        )
        if event_type == GENERATION_EVENT_TYPE:
            state = _apply_generation(state, payload)
            continue
        normalized_event_type = _normalized_event_type(event_type)
        if normalized_event_type == "BASELINE_RECORDED":
            state = _apply_scope_baseline(state, payload)
            continue
        if normalized_event_type in {
            "EXPERIMENT_TERMINATED",
            "EXPERIMENT_STATUS_CHANGED",
        }:
            state = _apply_terminal_evidence(
                state,
                normalized_event_type,
                payload,
            )
            continue
        if normalized_event_type != _REGISTRATION_EVENT_TYPE:
            continue
        present = (_REGISTRATION_SCIENCE_KEYS | _TYPED_REGISTRATION_KEYS).intersection(payload)
        if state.active_generation_id is None:
            if present:
                raise _error(
                    "STUDY_REGISTRATION_INVALID",
                    "pre-generation registration has a partial versioned bundle",
                    present_fields=sorted(present),
                )
            state = replace(
                state,
                legacy_unstructured_registrations=(state.legacy_unstructured_registrations + 1),
            )
            continue
        state = reserve_registration(state, payload)
    return state
