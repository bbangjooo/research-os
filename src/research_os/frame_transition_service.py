"""Opt-in orchestration for controlled frame-transition receipts.

The domain contract and replay rules live in :mod:`research_os.frame_transition`.
This module is intentionally small: it loads caller-owned JSON, serializes one
planned receipt through the canonical :class:`~research_os.kernel.events.EventLog`,
and delegates the final successor write to :class:`~research_os.service.ResearchService`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Callable, Protocol

from research_os.contracts import normalize_json_object
from research_os.errors import IntegrityError, ScientificStateError
from research_os.frame_transition import (
    FrameTransitionPlan,
    FrameTransitionState,
    controlled_change_reason,
    plan_adoption_review,
    plan_authority_revocation,
    plan_gate_a,
    plan_inquiry_decision,
    plan_inquiry_open,
    plan_pilot_authorization,
    plan_pilot_result,
    plan_policy_adoption,
    reduce_frame_transition_state,
    validate_controlled_activation,
    validate_frame_transition_commit_time,
)
from research_os.kernel._canonical import utc_now
from research_os.kernel.events import Event
from research_os.science import GENERATION_EVENT_TYPE, StudyContract
from research_os.service import ResearchService


class _ReceiptPlanner(Protocol):
    def __call__(
        self,
        events: Sequence[Event | Mapping[str, Any]],
        *,
        project_id: str,
        raw: Mapping[str, Any],
        recorded_at: str,
    ) -> FrameTransitionPlan: ...


class _FrameReceiptAlreadyRecorded(RuntimeError):
    """Internal control flow for an exact receipt-append race loser."""

    def __init__(self, plan: FrameTransitionPlan):
        super().__init__(plan.existing_event_id)
        self.plan = plan


def _same_append_plan(
    left: FrameTransitionPlan,
    right: FrameTransitionPlan,
) -> bool:
    return (
        left.event_type == right.event_type
        and left.receipt_id == right.receipt_id
        and left.receipt_digest == right.receipt_digest
        and dict(left.payload) == dict(right.payload)
    )


def _same_receipt_identity(
    left: FrameTransitionPlan,
    right: FrameTransitionPlan,
) -> bool:
    """Compare retry identity while allowing the winner's recorded timestamp."""

    return left.event_type == right.event_type and left.receipt_id == right.receipt_id


class FrameTransitionService:
    """Record and replay the optional outer frame-transition control plane."""

    def __init__(self, root: str | Path):
        self.research = ResearchService(root)
        self.config = self.research.config
        self.event_log = self.research.event_log

    def _raw_input(
        self,
        value: str | Path | Mapping[str, Any],
        *,
        label: str,
    ) -> dict[str, Any]:
        if isinstance(value, Mapping):
            return normalize_json_object(value, field_name=label)
        return self.research._load_json_object(value, label=label)

    def _state(
        self,
        events: Sequence[Event],
        *,
        as_of: str | None = None,
    ) -> FrameTransitionState:
        return reduce_frame_transition_state(
            tuple(events),
            project_id=self.config.project_id,
            as_of=as_of,
        )

    def _commit(
        self,
        planner: _ReceiptPlanner,
        value: str | Path | Mapping[str, Any],
        *,
        label: str,
        commit_guard: Callable[[tuple[Event, ...]], None] | None = None,
    ) -> dict[str, Any]:
        raw = self._raw_input(value, label=label)
        recorded_at = utc_now()
        self.research._assert_config_unchanged()

        with self.event_log.locked_read() as planning_events:
            initial_plan = planner(
                tuple(planning_events),
                project_id=self.config.project_id,
                raw=raw,
                recorded_at=recorded_at,
            )
            if initial_plan.append_required and commit_guard is not None:
                commit_guard(tuple(planning_events))

        appended = False
        canonical_event_id = initial_plan.existing_event_id
        canonical_plan = initial_plan
        if initial_plan.append_required:
            proposed_payload = dict(initial_plan.payload)

            def validate_locked_plan(locked_events: tuple[Event, ...]) -> None:
                locked_plan = planner(
                    locked_events,
                    project_id=self.config.project_id,
                    raw=raw,
                    recorded_at=recorded_at,
                )
                if not locked_plan.append_required:
                    if locked_plan.existing_event_id is None or not _same_receipt_identity(
                        initial_plan, locked_plan
                    ):
                        raise IntegrityError(
                            "idempotent frame-transition plan changed identity "
                            "before canonical append"
                        )
                    raise _FrameReceiptAlreadyRecorded(locked_plan)
                if commit_guard is not None:
                    commit_guard(locked_events)
                if not _same_append_plan(initial_plan, locked_plan):
                    raise IntegrityError(
                        "frame-transition append plan changed before canonical commit"
                    )
                validate_frame_transition_commit_time(
                    locked_events,
                    project_id=self.config.project_id,
                    plan=locked_plan,
                    as_of=utc_now(),
                )

            try:
                event = self.event_log.append(
                    initial_plan.event_type,
                    proposed_payload,
                    occurred_at=recorded_at,
                    precondition=validate_locked_plan,
                    postcondition=validate_locked_plan,
                )
            except _FrameReceiptAlreadyRecorded as raced:
                canonical_plan = raced.plan
                canonical_event_id = raced.plan.existing_event_id
            else:
                appended = True
                canonical_event_id = event.event_id

        if not isinstance(canonical_event_id, str):  # pragma: no cover - planner invariant
            raise IntegrityError("frame-transition plan omitted its canonical event identity")

        # Read the fully verified canonical stream again. Besides producing the
        # return state, this rejects duplicate/corrupt receipts and proves that
        # the race winner is the exact event planned by this request.
        canonical_events = tuple(self.event_log.read())
        state = self._state(canonical_events, as_of=recorded_at)
        matches = tuple(event for event in canonical_events if event.event_id == canonical_event_id)
        if len(matches) != 1:
            raise IntegrityError("canonical frame-transition event identity is not unique")
        canonical_event = matches[0]
        if canonical_event.event_type != canonical_plan.event_type or dict(
            canonical_event.payload
        ) != dict(canonical_plan.payload):
            raise IntegrityError("canonical frame-transition event changed after append")

        self.research._sync()
        result = {
            "schema_version": 1,
            "project_id": self.config.project_id,
            "event_type": canonical_event.event_type,
            "event_id": canonical_event.event_id,
            "event_hash": canonical_event.hash,
            "event_sequence": canonical_event.sequence,
            "receipt_id": canonical_plan.receipt_id,
            "receipt_digest": canonical_plan.receipt_digest,
            "receipt": dict(canonical_event.payload),
            "appended": appended,
            "appended_events": int(appended),
            "idempotent_reuse": not appended,
            "frame_transition": state.to_dict(),
            "authorized_action": None,
        }
        return normalize_json_object(
            result,
            field_name="frame-transition receipt result",
        )

    def gate_a(
        self,
        gate: str | Path | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Record or reuse one deterministic Gate A receipt."""

        return self._commit(plan_gate_a, gate, label="frame-transition Gate A")

    def open_inquiry(
        self,
        inquiry: str | Path | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Open one material outer inquiry against a current GO receipt."""

        return self._commit(
            plan_inquiry_open,
            inquiry,
            label="frame-transition inquiry",
        )

    def decide_inquiry(
        self,
        decision: str | Path | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Record the maker's comparative inquiry decision."""

        return self._commit(
            plan_inquiry_decision,
            decision,
            label="frame-transition inquiry decision",
        )

    def authorize_pilot(
        self,
        authorization: str | Path | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Record distinct, expiring PILOT_ONLY authority."""

        return self._commit(
            plan_pilot_authorization,
            authorization,
            label="frame-transition pilot authorization",
        )

    def record_pilot(
        self,
        result: str | Path | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Record one three-arm pilot result and its deterministic outcome."""

        return self._commit(
            plan_pilot_result,
            result,
            label="frame-transition pilot result",
        )

    def review_adoption(
        self,
        review: str | Path | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Record a fresh, independent post-pilot adoption review."""

        raw = self._raw_input(review, label="frame-transition adoption review")
        tree_digest = raw.get("tree_digest")
        if not isinstance(tree_digest, str):
            raise ScientificStateError(
                "FRAME_TRANSITION_TREE_MISMATCH",
                "adoption review requires the current source tree digest",
            )

        def require_current_tree(events: tuple[Event, ...]) -> None:
            report = self.research._doctor_snapshot(event_count=len(events))
            current = report.fingerprints.get("source_tree_digest")
            if current != tree_digest:
                raise ScientificStateError(
                    "FRAME_TRANSITION_TREE_MISMATCH",
                    "adoption review tree digest is not current",
                    details={
                        "review_tree_digest": tree_digest,
                        "current_tree_digest": current,
                    },
                )

        return self._commit(
            plan_adoption_review,
            raw,
            label="frame-transition adoption review",
            commit_guard=require_current_tree,
        )

    def adopt_policy(self, inquiry_id: str) -> dict[str, Any]:
        """Record deterministic POLICY_ADOPTION without opening a generation."""

        if not isinstance(inquiry_id, str) or not inquiry_id.strip():
            raise ValueError("inquiry_id must be a non-empty string")
        return self._commit(
            plan_policy_adoption,
            {
                "schema_version": 1,
                "inquiry_id": inquiry_id,
                "authorized_action": None,
            },
            label="frame-transition policy adoption",
        )

    def revoke_authority(
        self,
        revocation: str | Path | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Revoke an exact pilot authorization or adoption-review digest."""

        return self._commit(
            plan_authority_revocation,
            revocation,
            label="frame-transition authority revocation",
        )

    def status(
        self,
        inquiry_id: str | None = None,
    ) -> dict[str, Any]:
        """Replay current outer-control state without changing canonical data."""

        if inquiry_id is not None and (not isinstance(inquiry_id, str) or not inquiry_id.strip()):
            raise ValueError("inquiry_id must be a non-empty string or null")
        self.research._assert_config_unchanged()
        as_of = utc_now()
        with self.event_log.locked_read() as events:
            state = self._state(tuple(events), as_of=as_of)
        result = state.to_dict()
        if inquiry_id is not None:
            inquiry = state.inquiry(inquiry_id)
            if inquiry is None:
                raise ScientificStateError(
                    "FRAME_TRANSITION_INQUIRY_UNKNOWN",
                    "frame-transition inquiry does not exist",
                    details={"inquiry_id": inquiry_id},
                )
            result["inquiries"] = [inquiry]
        return normalize_json_object(
            result,
            field_name="frame-transition status",
        )

    def _canonical_activation_open_result(
        self,
        events: Sequence[Event],
        *,
        binding: Mapping[str, Any],
        study_contract: StudyContract,
        change_reason: str,
    ) -> dict[str, Any]:
        """Reconstruct ResearchService's idempotent result from one exact winner."""

        generation_id = binding.get("successor_generation_id")
        predecessor_generation_id = binding.get("predecessor_generation_id")
        successor_compatibility_digest = binding.get("successor_compatibility_digest")
        if not all(
            isinstance(value, str)
            for value in (
                generation_id,
                predecessor_generation_id,
                successor_compatibility_digest,
            )
        ):
            raise IntegrityError("controlled activation replay omitted its canonical binding")
        matches = tuple(
            event
            for event in events
            if event.event_type == GENERATION_EVENT_TYPE
            and event.payload.get("generation_id") == generation_id
        )
        if len(matches) != 1:
            raise IntegrityError("controlled activation successor identity is not unique")
        event = matches[0]
        payload = event.payload
        seal = payload.get("evaluation_seal")
        evaluation_seal_digest = payload.get("evaluation_seal_digest")
        if (
            payload.get("study_contract_digest") != study_contract.digest
            or payload.get("predecessor_generation_id") != predecessor_generation_id
            or payload.get("change_reason") != change_reason
            or not isinstance(seal, Mapping)
            or seal.get("compatibility_digest") != successor_compatibility_digest
            or not isinstance(evaluation_seal_digest, str)
        ):
            raise IntegrityError(
                "controlled activation winner does not match the requested binding"
            )
        return normalize_json_object(
            {
                "project_id": self.config.project_id,
                "event_type": GENERATION_EVENT_TYPE,
                "generation_id": generation_id,
                "study_contract_digest": study_contract.digest,
                "evaluation_seal_digest": evaluation_seal_digest,
                "predecessor_generation_id": predecessor_generation_id,
                "change_reason": change_reason,
                "appended": False,
                "appended_events": 0,
                "authorized_action": None,
            },
            field_name="idempotent controlled generation result",
        )

    def _activation_result(
        self,
        opened: Mapping[str, Any],
        *,
        inquiry_id: str,
        policy_adoption_digest: str,
        binding: Mapping[str, Any],
        events: Sequence[Event],
        as_of: str,
    ) -> dict[str, Any]:
        final_state = self._state(events, as_of=as_of)
        final_inquiry = final_state.inquiry(inquiry_id)
        generation_id = binding.get("successor_generation_id")
        if (
            not binding.get("already_activated")
            or not isinstance(generation_id, str)
            or opened.get("generation_id") != generation_id
            or final_inquiry is None
            or final_inquiry.get("successor_generation_id") != generation_id
            or final_inquiry.get("durable_successor_writer_count") != 1
        ):
            raise IntegrityError(
                "controlled successor was not recognized by frame-transition replay"
            )
        result = {
            **opened,
            "schema_version": 1,
            "frame_transition_inquiry_id": inquiry_id,
            "policy_adoption_digest": policy_adoption_digest,
            "frame_transition": final_inquiry,
            "authorized_action": None,
        }
        return normalize_json_object(
            result,
            field_name="controlled frame-transition activation result",
        )

    def _existing_activation_result(
        self,
        *,
        inquiry_id: str,
        policy_adoption_digest: str,
        successor_compatibility_digest: str,
        study_contract: StudyContract,
        change_reason: str,
    ) -> dict[str, Any]:
        """Return only when a fresh replay proves the exact canonical winner."""

        as_of = utc_now()
        events = tuple(self.event_log.read())
        binding = validate_controlled_activation(
            events,
            project_id=self.config.project_id,
            inquiry_id=inquiry_id,
            policy_adoption_digest=policy_adoption_digest,
            target_contract_digest=study_contract.digest,
            target_successor_compatibility_digest=successor_compatibility_digest,
            change_reason=change_reason,
            as_of=as_of,
        )
        if binding.get("already_activated") is not True:
            raise IntegrityError("concurrent controlled activation did not produce an exact winner")
        opened = self._canonical_activation_open_result(
            events,
            binding=binding,
            study_contract=study_contract,
            change_reason=change_reason,
        )
        return self._activation_result(
            opened,
            inquiry_id=inquiry_id,
            policy_adoption_digest=policy_adoption_digest,
            binding=binding,
            events=events,
            as_of=as_of,
        )

    def activate(
        self,
        inquiry_id: str,
        contract: str | Path | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Open the one compatibility-separated successor authorized by an inquiry.

        The outer reducer performs an early, read-only receipt check here.  The
        same binding is passed into ``ResearchService.open_generation`` so that
        it is recalculated against the exact event history held by the final
        generation append lock.  Consequently expiry, revocation, or another
        successor writer cannot slip between this check and the durable write.
        """

        if not isinstance(inquiry_id, str) or not inquiry_id.strip():
            raise ValueError("inquiry_id must be a non-empty string")
        raw_contract = self._raw_input(
            contract,
            label="controlled successor study contract",
        )
        study_contract = StudyContract.from_mapping(raw_contract)
        self.research._assert_config_unchanged()
        as_of = utc_now()

        with self.event_log.locked_read() as events:
            state = self._state(tuple(events), as_of=as_of)
            inquiry = state.inquiry(inquiry_id)
            if inquiry is None:
                raise ScientificStateError(
                    "FRAME_TRANSITION_INQUIRY_UNKNOWN",
                    "frame-transition inquiry does not exist",
                    details={"inquiry_id": inquiry_id},
                )
            policy_adoption = inquiry.get("policy_adoption")
            if not isinstance(policy_adoption, Mapping):
                raise ScientificStateError(
                    "FRAME_TRANSITION_ADOPTION_REQUIRED",
                    "controlled activation requires a current POLICY_ADOPTION receipt",
                    details={"inquiry_id": inquiry_id},
                )
            policy_adoption_digest = policy_adoption.get("receipt_digest")
            successor_compatibility_digest = policy_adoption.get(
                "successor_compatibility_digest"
            )
            if not isinstance(policy_adoption_digest, str) or not isinstance(
                successor_compatibility_digest, str
            ):
                raise IntegrityError(
                    "canonical POLICY_ADOPTION receipt omitted its activation binding"
                )
            change_reason = controlled_change_reason(
                inquiry_id,
                policy_adoption_digest,
            )
            binding = validate_controlled_activation(
                tuple(events),
                project_id=self.config.project_id,
                inquiry_id=inquiry_id,
                policy_adoption_digest=policy_adoption_digest,
                target_contract_digest=study_contract.digest,
                target_successor_compatibility_digest=successor_compatibility_digest,
                change_reason=change_reason,
                as_of=as_of,
            )

        predecessor_generation_id = binding.get("predecessor_generation_id")
        source_tree_digest = binding.get("source_tree_digest")
        if not isinstance(predecessor_generation_id, str) or not isinstance(
            source_tree_digest, str
        ):
            raise IntegrityError(
                "controlled activation binding omitted predecessor or source tree"
            )
        if binding.get("already_activated") is True:
            return self._existing_activation_result(
                inquiry_id=inquiry_id,
                policy_adoption_digest=policy_adoption_digest,
                successor_compatibility_digest=successor_compatibility_digest,
                study_contract=study_contract,
                change_reason=change_reason,
            )

        try:
            opened = self.research.open_generation(
                raw_contract,
                predecessor_generation_id=predecessor_generation_id,
                change_reason=change_reason,
                controlled_transition={
                    "inquiry_id": inquiry_id,
                    "policy_adoption_digest": policy_adoption_digest,
                    "source_tree_digest": source_tree_digest,
                    "successor_compatibility_digest": successor_compatibility_digest,
                },
            )
        except Exception as open_error:
            # A competing exact writer can make ResearchService's ordinary
            # predecessor preflight stale before its locked replan.  Accept
            # that race only after a fresh outer replay proves the requested
            # chain and target. Every other error remains the caller's error.
            try:
                return self._existing_activation_result(
                    inquiry_id=inquiry_id,
                    policy_adoption_digest=policy_adoption_digest,
                    successor_compatibility_digest=successor_compatibility_digest,
                    study_contract=study_contract,
                    change_reason=change_reason,
                )
            except Exception:
                raise open_error from None

        canonical_events = tuple(self.event_log.read())
        replayed_at = utc_now()
        final_binding = validate_controlled_activation(
            canonical_events,
            project_id=self.config.project_id,
            inquiry_id=inquiry_id,
            policy_adoption_digest=policy_adoption_digest,
            target_contract_digest=study_contract.digest,
            target_successor_compatibility_digest=successor_compatibility_digest,
            change_reason=change_reason,
            as_of=replayed_at,
        )
        return self._activation_result(
            opened,
            inquiry_id=inquiry_id,
            policy_adoption_digest=policy_adoption_digest,
            binding=final_binding,
            events=canonical_events,
            as_of=replayed_at,
        )


__all__ = ["FrameTransitionService"]
