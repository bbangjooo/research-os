"""Append-only, explicitly scoped research findings."""

from __future__ import annotations

import builtins
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from research_os.kernel._canonical import JSONValue, json_value, require_text
from research_os.kernel.events import Event, EventLog
from research_os.kernel.ids import new_id, validate_namespaced_id

if TYPE_CHECKING:
    from research_os.kernel.projection import ProjectionStore


FINDING_RECORDED = "FINDING_RECORDED"
KERNEL_RESERVED_FINDING_KEYS = frozenset({"experiment_outcome"})


class FindingScope(StrEnum):
    SESSION = "session"
    PROJECT = "project"
    GLOBAL = "global"


def coerce_scope(value: FindingScope | str) -> FindingScope:
    if isinstance(value, FindingScope):
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError("finding scope must be session, project, or global")
    try:
        return FindingScope(value.strip().lower())
    except ValueError as exc:
        raise ValueError(f"invalid finding scope: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class Finding(Mapping[str, Any]):
    finding_id: str
    scope: FindingScope
    project_id: str | None
    session_id: str | None
    experiment_id: str | None
    key: str | None
    content: JSONValue
    evidence: JSONValue
    metadata: dict[str, JSONValue]

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "finding_id",
        "scope",
        "project_id",
        "session_id",
        "experiment_id",
        "key",
        "content",
        "evidence",
        "metadata",
    )

    def to_dict(self) -> dict[str, Any]:
        return {key: self[key] for key in self._FIELDS}

    def __getitem__(self, key: str) -> Any:
        if key not in self._FIELDS:
            raise KeyError(key)
        value = getattr(self, key)
        if key == "scope":
            return value.value
        if key in {"content", "evidence", "metadata"}:
            return json_value(value)
        return value

    def __iter__(self) -> Iterator[str]:
        return iter(self._FIELDS)

    def __len__(self) -> int:
        return len(self._FIELDS)

    @classmethod
    def from_event(cls, event: Event) -> "Finding":
        if (
            event.event_type.strip().upper().replace(".", "_").replace("-", "_")
            != FINDING_RECORDED
        ):
            raise ValueError(f"event is not a finding: {event.event_type}")
        return cls.from_payload(event.payload, origin_project_id=event.project_id)

    @classmethod
    def from_payload(
        cls, payload: Mapping[str, Any], *, origin_project_id: str
    ) -> "Finding":
        if "content" not in payload:
            raise ValueError("finding event has no content")
        origin_project_id = require_text(origin_project_id, "origin_project_id")
        scope = coerce_scope(payload.get("scope", FindingScope.PROJECT.value))
        raw_project = payload.get("project_id")
        if scope is FindingScope.GLOBAL:
            if raw_project is not None:
                raise ValueError("global finding must not select a project_id")
            project_id = None
        else:
            project_id = (
                origin_project_id
                if raw_project is None
                else require_text(raw_project, "project_id")
            )
            if scope in {FindingScope.PROJECT, FindingScope.SESSION} and (
                project_id != origin_project_id
            ):
                raise ValueError(
                    f"{scope.value}-scoped finding must match the event's project_id"
                )
        raw_session = payload.get("session_id")
        session_id = (
            None if raw_session is None else require_text(raw_session, "session_id")
        )
        if scope is FindingScope.SESSION and session_id is None:
            raise ValueError("session-scoped finding requires session_id")
        raw_experiment = payload.get("experiment_id")
        experiment_id = (
            None
            if raw_experiment is None
            else require_text(raw_experiment, "experiment_id")
        )
        raw_key = payload.get("key")
        key = None if raw_key is None else require_text(raw_key, "key")
        metadata = json_value(payload.get("metadata", {}))
        if not isinstance(metadata, dict):
            raise ValueError("finding metadata must be a mapping")
        finding_id = validate_namespaced_id(payload["finding_id"], "finding")
        return cls(
            finding_id=finding_id,
            scope=scope,
            project_id=project_id,
            session_id=session_id,
            experiment_id=experiment_id,
            key=key,
            content=json_value(payload["content"]),
            evidence=json_value(payload.get("evidence", [])),
            metadata=metadata,
        )


def make_finding_event(
    project_id: str,
    content: Any,
    *,
    scope: FindingScope | str = FindingScope.PROJECT,
    session_id: str | None = None,
    experiment_id: str | None = None,
    key: str | None = None,
    evidence: Any = None,
    metadata: Mapping[str, Any] | None = None,
    finding_id: str | None = None,
) -> dict[str, Any]:
    """Build the generic payload for a ``FINDING_RECORDED`` event.

    Project scope is deliberately the default.  Global findings retain no
    project selector in their payload; the event envelope still identifies the
    project log that supplied the evidence.
    """

    project_id = require_text(project_id, "project_id")
    normalized_scope = coerce_scope(scope)
    if normalized_scope is FindingScope.SESSION:
        session_id = require_text(session_id, "session_id")
    elif session_id is not None:
        session_id = require_text(session_id, "session_id")
    if experiment_id is not None:
        experiment_id = require_text(experiment_id, "experiment_id")
    if key is not None:
        key = require_text(key, "key")
    clean_content = json_value(content, path="$.content")
    clean_evidence = json_value([] if evidence is None else evidence, path="$.evidence")
    clean_metadata = json_value({} if metadata is None else metadata, path="$.metadata")
    if not isinstance(clean_metadata, dict):
        raise TypeError("finding metadata must be a mapping")
    payload: dict[str, Any] = {
        "finding_id": new_id("finding")
        if finding_id is None
        else require_text(finding_id, "finding_id"),
        "scope": normalized_scope.value,
        "project_id": project_id
        if normalized_scope is not FindingScope.GLOBAL
        else None,
        "session_id": session_id,
        "experiment_id": experiment_id,
        "key": key,
        "content": clean_content,
        "evidence": clean_evidence,
        "metadata": clean_metadata,
    }
    return payload


# A short spelling for service code that is constructing an event payload.
finding_event = make_finding_event
finding_payload = make_finding_event


def record_finding(
    event_log: EventLog,
    content: Any,
    *,
    scope: FindingScope | str = FindingScope.PROJECT,
    project_id: str | None = None,
    session_id: str | None = None,
    experiment_id: str | None = None,
    key: str | None = None,
    evidence: Any = None,
    metadata: Mapping[str, Any] | None = None,
    finding_id: str | None = None,
) -> Event:
    if key in KERNEL_RESERVED_FINDING_KEYS:
        raise ValueError(f"finding key {key!r} is reserved for Research OS")
    selected_project = (
        event_log.project_id
        if project_id is None
        else require_text(project_id, "project_id")
    )
    if selected_project != event_log.project_id:
        raise ValueError("finding project_id must match the bound EventLog project_id")
    payload = make_finding_event(
        selected_project,
        content,
        scope=scope,
        session_id=session_id,
        experiment_id=experiment_id,
        key=key,
        evidence=evidence,
        metadata=metadata,
        finding_id=finding_id,
    )
    return event_log.append(FINDING_RECORDED, payload)


append_finding = record_finding


class FindingStore:
    """Convenience facade that records findings and optionally syncs a projection."""

    def __init__(
        self, event_log: EventLog, projection: "ProjectionStore | None" = None
    ):
        self.event_log = event_log
        self.projection = projection

    def record(self, content: Any, **kwargs: Any) -> Finding:
        event = record_finding(self.event_log, content, **kwargs)
        if self.projection is not None:
            self.projection.sync(self.event_log)
        return Finding.from_event(event)

    append = record

    def list(
        self,
        *,
        scope: FindingScope | str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        experiment_id: str | None = None,
    ) -> builtins.list[dict[str, Any]]:
        if self.projection is None:
            findings: list[dict[str, Any]] = []
            for event in self.event_log.read():
                if (
                    event.event_type.strip().upper().replace(".", "_").replace("-", "_")
                    != FINDING_RECORDED
                ):
                    continue
                finding = Finding.from_event(event)
                if scope is not None and finding.scope is not coerce_scope(scope):
                    continue
                if project_id is not None and finding.scope is not FindingScope.GLOBAL:
                    if finding.project_id != project_id:
                        continue
                if session_id is not None and finding.session_id != session_id:
                    continue
                if experiment_id is not None and finding.experiment_id != experiment_id:
                    continue
                findings.append(finding.to_dict())
            return findings
        rows = self.projection.findings(
            scope=coerce_scope(scope).value if scope is not None else None,
            project_id=project_id,
            session_id=session_id,
            experiment_id=experiment_id,
        )
        return [
            Finding.from_payload(
                row["payload"], origin_project_id=row["origin_project_id"]
            ).to_dict()
            for row in rows
        ]
