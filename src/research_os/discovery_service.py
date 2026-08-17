"""Opt-in orchestration for the advisory discovery lane.

The domain contract and replay rules live in :mod:`research_os.discovery`.  This
module loads caller-owned JSON, appends one note through the canonical
:class:`~research_os.kernel.events.EventLog`, and replays the projections.  It
never opens a generation, never writes to ProgramLog, and never returns
authority.
"""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from research_os.contracts import normalize_json_object
from research_os.discovery import (
    DiscoveryPlan,
    DiscoveryState,
    exhaustion_projection,
    frame_health_projection,
    jump_dossier,
    plan_discovery_note,
    reduce_discovery_state,
    residual_task,
    yield_projection,
)
from research_os.errors import IntegrityError
from research_os.kernel._canonical import utc_now
from research_os.kernel.events import Event
from research_os.memory.program import ProgramStore
from research_os.memory.retrieval import AnalogyQuery, retrieve_analogies
from research_os.service import ResearchService


class DiscoveryService:
    """Record and replay the advisory discovery journal."""

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

    def _state(self, events: Sequence[Event]) -> DiscoveryState:
        return reduce_discovery_state(tuple(events), project_id=self.config.project_id)

    def note(
        self,
        note: str | Path | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Append one screened discovery note.

        There is deliberately no idempotent reuse path.  Two identical bodies
        are two observations, so every accepted request appends.  Because a
        note's identity binds its position in the journal, the plan is recomputed
        under the append lock and rejected if another writer moved that position.
        """

        raw = self._raw_input(note, label="discovery note")
        recorded_at = utc_now()
        self.research._assert_config_unchanged()

        with self.event_log.locked_read() as planning_events:
            initial_plan = plan_discovery_note(
                tuple(planning_events),
                project_id=self.config.project_id,
                raw=raw,
                recorded_at=recorded_at,
            )

        def validate_locked_plan(locked_events: tuple[Event, ...]) -> None:
            locked_plan = plan_discovery_note(
                locked_events,
                project_id=self.config.project_id,
                raw=raw,
                recorded_at=recorded_at,
            )
            if not _same_plan(initial_plan, locked_plan):
                raise IntegrityError(
                    "discovery note plan changed before canonical commit"
                )

        event = self.event_log.append(
            initial_plan.event_type,
            dict(initial_plan.payload),
            occurred_at=recorded_at,
            precondition=validate_locked_plan,
            postcondition=validate_locked_plan,
        )

        canonical_events = tuple(self.event_log.read())
        state = self._state(canonical_events)
        matches = tuple(item for item in canonical_events if item.event_id == event.event_id)
        if len(matches) != 1:
            raise IntegrityError("canonical discovery note identity is not unique")
        canonical_event = matches[0]
        if canonical_event.event_type != initial_plan.event_type or dict(
            canonical_event.payload
        ) != dict(initial_plan.payload):
            raise IntegrityError("canonical discovery note changed after append")

        self.research._sync()
        result = {
            "schema_version": 1,
            "project_id": self.config.project_id,
            "lane": "advisory",
            "event_type": canonical_event.event_type,
            "event_id": canonical_event.event_id,
            "event_hash": canonical_event.hash,
            "event_sequence": canonical_event.sequence,
            "note_id": initial_plan.note_id,
            "receipt_digest": initial_plan.receipt_digest,
            "note": dict(canonical_event.payload),
            "appended": True,
            "appended_events": 1,
            "discovery": state.to_dict(),
            "authorized_action": None,
        }
        return normalize_json_object(result, field_name="discovery note result")

    def status(
        self,
        *,
        kind: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """Replay the journal without changing canonical data."""

        if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
            raise ValueError("limit must be a positive integer or null")
        self.research._assert_config_unchanged()
        with self.event_log.locked_read() as events:
            state = self._state(tuple(events))
        return normalize_json_object(
            state.to_dict(kind=kind, limit=limit),
            field_name="discovery status",
        )

    def exhaustion(self) -> dict[str, Any]:
        """Report which exhaustion signal kinds currently have material."""

        self.research._assert_config_unchanged()
        with self.event_log.locked_read() as events:
            projection = exhaustion_projection(
                tuple(events),
                project_id=self.config.project_id,
            )
        return normalize_json_object(projection, field_name="discovery exhaustion")

    def residual(self) -> dict[str, Any]:
        """Report the residual generation task for each closed hypothesis class."""

        self.research._assert_config_unchanged()
        with self.event_log.locked_read() as events:
            projection = residual_task(
                tuple(events),
                project_id=self.config.project_id,
            )
        return normalize_json_object(projection, field_name="discovery residual task")

    def frame_health(self) -> dict[str, Any]:
        """Emit the interpretation packet an LLM reads to judge frame health."""

        self.research._assert_config_unchanged()
        with self.event_log.locked_read() as events:
            projection = frame_health_projection(
                tuple(events),
                project_id=self.config.project_id,
            )
        return normalize_json_object(projection, field_name="discovery frame health")

    def dossier(self, note_id: str) -> dict[str, Any]:
        """Emit the authoring dossier for one recorded rival draft."""

        if not isinstance(note_id, str) or not note_id.strip():
            raise ValueError("note_id must be a non-empty string")
        self.research._assert_config_unchanged()
        with self.event_log.locked_read() as events:
            projection = jump_dossier(
                tuple(events),
                project_id=self.config.project_id,
                note_id=note_id,
            )
        return normalize_json_object(projection, field_name="discovery jump dossier")

    def yield_curve(self) -> dict[str, Any]:
        """Report the admissible-distinct draft yield used to keep or drop the lane."""

        self.research._assert_config_unchanged()
        with self.event_log.locked_read() as events:
            projection = yield_projection(
                tuple(events),
                project_id=self.config.project_id,
            )
        return normalize_json_object(projection, field_name="discovery yield")

    def analogies(
        self,
        query: str | Path | Mapping[str, Any],
        *,
        program_root: str | os.PathLike[str],
        program_id: str,
    ) -> dict[str, Any]:
        """Read cross-frame claims as advisory material.

        ProgramLog is owned outside :class:`ResearchService`, so the caller names
        the store.  The result is an ``AnalogyResult``, a type canonical
        registration cannot accept, and nothing here writes.
        """

        raw = self._raw_input(query, label="analogy query")
        parsed = AnalogyQuery.from_mapping(raw)
        store = ProgramStore(program_root, program_id)
        result = retrieve_analogies(store.claim_snapshot(), parsed)
        return normalize_json_object(
            {
                **result.to_dict(),
                "project_id": self.config.project_id,
                "result_digest": result.digest,
            },
            field_name="analogy result",
        )


def _same_plan(left: DiscoveryPlan, right: DiscoveryPlan) -> bool:
    return (
        left.event_type == right.event_type
        and left.note_id == right.note_id
        and left.receipt_digest == right.receipt_digest
        and dict(left.payload) == dict(right.payload)
    )


__all__ = ["DiscoveryService"]
