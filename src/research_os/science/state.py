"""Pure replay and prospective validation for versioned scientific state."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from research_os.errors import ScientificStateError
from research_os.kernel.events import Event
from research_os.kernel.ids import validate_namespaced_id

from .contracts import (
    SCIENCE_STATE_VERSION,
    EvaluationSeal,
    StudyContract,
    is_safe_integer,
)
from .contracts import generation_id as derive_generation_id

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
_BUDGET_DEBIT_KEYS = frozenset(
    {
        "attempts",
        "retries",
        "reserved_elapsed_milliseconds",
        "reserved_cost_microunits",
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

    @property
    def study_contract_digest(self) -> str | None:
        return None if self.contract is None else self.contract.digest

    @property
    def evaluation_seal_digest(self) -> str | None:
        return None if self.evaluation_seal is None else self.evaluation_seal.digest

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
                        declared.max_elapsed_milliseconds
                        - self.elapsed_reserved_milliseconds
                    ),
                },
                "cost_microunits": cost,
            }
        return {
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
            "legacy_unstructured_registrations": (
                self.legacy_unstructured_registrations
            ),
        }


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
            "reserved_elapsed_milliseconds": (
                budget.elapsed_reservation_per_attempt_milliseconds
            ),
            "reserved_cost_microunits": (
                budget.cost_reservation_per_attempt_microunits
            ),
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
    if retry_of is not None and (
        not isinstance(retry_of, str) or not retry_of.strip()
    ):
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
            registration_evaluation_seal_digest=payload[
                "evaluation_seal_digest"
            ],
        )
    return int(attempts), int(retries), int(elapsed), None if cost is None else int(cost)


def validate_registration(
    state: ScientificState,
    payload: Mapping[str, Any],
) -> None:
    """Validate binding and contract-fixed debit without consuming it."""

    _registration_debit(state, payload)


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

    attempts, retries, elapsed, cost = _registration_debit(state, payload)
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
    return replace(
        state,
        attempts_used=next_attempts,
        retries_used=next_retries,
        elapsed_reserved_milliseconds=next_elapsed,
        cost_reserved_microunits=next_cost,
    )


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
    observed_id = _generation_identifier(
        payload["generation_id"], code=code, field="generation_id"
    )
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
        cost_reserved_microunits=(
            None
            if contract.budget.max_cost_microunits is None
            else 0
        ),
        legacy_unstructured_registrations=(
            state.legacy_unstructured_registrations
        ),
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
        if _normalized_event_type(event_type) != _REGISTRATION_EVENT_TYPE:
            continue
        present = _REGISTRATION_SCIENCE_KEYS.intersection(payload)
        if state.active_generation_id is None:
            if present:
                raise _error(
                    "STUDY_REGISTRATION_INVALID",
                    "pre-generation registration has a partial versioned bundle",
                    present_fields=sorted(present),
                )
            state = replace(
                state,
                legacy_unstructured_registrations=(
                    state.legacy_unstructured_registrations + 1
                ),
            )
            continue
        state = reserve_registration(state, payload)
    return state
