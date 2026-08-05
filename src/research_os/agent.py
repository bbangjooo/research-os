"""Agent-facing project context and local skill installation helpers."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from research_os.contracts import canonical_json_bytes, decode_json_object, sha256_json
from research_os.errors import ConfigurationError, IntegrityError

AGENT_BRIEF_RELATIVE: Final = Path(".research-os/research-brief.md")
CANDIDATE_SCHEMA_RELATIVE: Final = Path(".research-os/candidate.schema.json")
CANDIDATE_INBOX_RELATIVE: Final = Path(".research-os/candidate.inbox.json")
AGENT_JOURNAL_RELATIVE: Final = Path(".research-os/agent-journal.jsonl")

_CONTROL_DIR: Final = ".research-os"
_MAX_AGENT_FILE_BYTES: Final = 256 * 1024
_MAX_CONTEXT_VALUE_BYTES: Final = 32 * 1024
MAX_AGENT_CONTEXT_BYTES: Final = 2 * 1024 * 1024


def _stable_stat(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _directory_flags() -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    return flags | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _file_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _read_optional_control_file(root: Path, name: str) -> str | None:
    """Read one bounded regular control file without following path replacements."""

    root_fd = -1
    control_fd = -1
    file_fd = -1
    root = root.resolve(strict=True)
    try:
        root_before = root.lstat()
        if stat.S_ISLNK(root_before.st_mode) or not stat.S_ISDIR(root_before.st_mode):
            raise IntegrityError("agent project root must be a non-symlink directory")
        root_fd = os.open(root, _directory_flags())
        root_opened = os.fstat(root_fd)
        if (root_opened.st_dev, root_opened.st_ino) != (
            root_before.st_dev,
            root_before.st_ino,
        ):
            raise IntegrityError("agent project root changed while opening")

        control_before = os.stat(
            _CONTROL_DIR, dir_fd=root_fd, follow_symlinks=False
        )
        if stat.S_ISLNK(control_before.st_mode) or not stat.S_ISDIR(
            control_before.st_mode
        ):
            raise IntegrityError("agent control path must be a non-symlink directory")
        control_fd = os.open(_CONTROL_DIR, _directory_flags(), dir_fd=root_fd)
        control_opened = os.fstat(control_fd)
        if (control_opened.st_dev, control_opened.st_ino) != (
            control_before.st_dev,
            control_before.st_ino,
        ):
            raise IntegrityError("agent control path changed while opening")

        try:
            before = os.stat(name, dir_fd=control_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise IntegrityError(f"agent control file must be regular: {name}")
        if before.st_size > _MAX_AGENT_FILE_BYTES:
            raise ConfigurationError(
                f"agent control file exceeds {_MAX_AGENT_FILE_BYTES} bytes: {name}"
            )
        file_fd = os.open(name, _file_flags(), dir_fd=control_fd)
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (before.st_dev, before.st_ino):
            raise IntegrityError(f"agent control file changed while opening: {name}")

        data = bytearray()
        while block := os.read(file_fd, 64 * 1024):
            data.extend(block)
            if len(data) > _MAX_AGENT_FILE_BYTES:
                raise ConfigurationError(
                    f"agent control file exceeds {_MAX_AGENT_FILE_BYTES} bytes: {name}"
                )
        after_descriptor = os.fstat(file_fd)
        after_path = os.stat(name, dir_fd=control_fd, follow_symlinks=False)
        if (
            _stable_stat(after_descriptor) != _stable_stat(opened)
            or _stable_stat(after_path) != _stable_stat(opened)
        ):
            raise IntegrityError(f"agent control file changed while reading: {name}")

        control_after = os.stat(
            _CONTROL_DIR, dir_fd=root_fd, follow_symlinks=False
        )
        root_after = root.lstat()
        if (control_after.st_dev, control_after.st_ino) != (
            control_opened.st_dev,
            control_opened.st_ino,
        ):
            raise IntegrityError("agent control path changed while reading")
        if (root_after.st_dev, root_after.st_ino) != (
            root_opened.st_dev,
            root_opened.st_ino,
        ):
            raise IntegrityError("agent project root changed while reading")
        try:
            return bytes(data).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ConfigurationError(
                f"agent control file must be UTF-8 text: {name}"
            ) from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if control_fd >= 0:
            os.close(control_fd)
        if root_fd >= 0:
            os.close(root_fd)


def load_agent_spec(root: Path) -> dict[str, Any]:
    """Load the project-owned research brief and candidate schema, if present."""

    brief = _read_optional_control_file(root, AGENT_BRIEF_RELATIVE.name)
    schema_text = _read_optional_control_file(root, CANDIDATE_SCHEMA_RELATIVE.name)
    schema: Mapping[str, Any] | None = None
    if schema_text is not None:
        try:
            schema = decode_json_object(schema_text)
        except (TypeError, ValueError) as exc:
            raise ConfigurationError(
                f"invalid agent candidate schema: {CANDIDATE_SCHEMA_RELATIVE}"
            ) from exc

    configured = bool(
        brief
        and "REPLACE_ME" not in brief
        and schema is not None
        and schema.get("x-research-os-configured") is True
    )
    return {
        "configured": configured,
        "brief_path": AGENT_BRIEF_RELATIVE.as_posix(),
        "candidate_schema_path": CANDIDATE_SCHEMA_RELATIVE.as_posix(),
        "candidate_inbox_path": CANDIDATE_INBOX_RELATIVE.as_posix(),
        "journal_path": AGENT_JOURNAL_RELATIVE.as_posix(),
        "brief": brief,
        "candidate_schema": schema,
        "journal_is_authoritative": False,
    }


def _bounded_value(value: Any) -> Any:
    """Keep agent context finite while retaining a deterministic evidence handle."""

    encoded = canonical_json_bytes(value)
    if len(encoded) <= _MAX_CONTEXT_VALUE_BYTES:
        return value
    return {
        "omitted_from_context": True,
        "digest": sha256_json(value),
        "size_bytes": len(encoded),
    }


def _compact_experiment(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    payload = payload if isinstance(payload, Mapping) else {}
    outcome = payload.get("outcome")
    outcome = outcome if isinstance(outcome, Mapping) else {}
    outcome_summary = {
        key: outcome[key]
        for key in (
            "status",
            "reason_code",
            "retryable",
            "decision",
            "result",
            "error",
            "secondary_errors",
            "verified",
        )
        if key in outcome
    }
    return {
        "experiment_id": row.get("experiment_id"),
        "parent_id": row.get("parent_id"),
        "status": row.get("status"),
        "attempt": row.get("attempt"),
        "retry_of": row.get("retry_of"),
        "retryable": bool(row.get("retryable", False)),
        "candidate_digest": row.get("candidate_digest"),
        "compatibility_digest": row.get("compatibility_digest"),
        "candidate": _bounded_value(payload.get("candidate")),
        "outcome": _bounded_value(outcome_summary),
        "registered_at": row.get("registered_at"),
        "terminated_at": row.get("terminated_at"),
        "created_sequence": row.get("created_sequence"),
    }


def _compact_finding(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "finding_id": row.get("finding_id"),
        "experiment_id": row.get("experiment_id"),
        "finding_key": row.get("finding_key"),
        "scope": row.get("scope"),
        "content": _bounded_value(row.get("content")),
        "evidence": _bounded_value(row.get("evidence")),
        "created_at": row.get("created_at"),
        "event_sequence": row.get("event_sequence"),
    }


def _compact_artifact(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": row.get("artifact_id"),
        "experiment_id": row.get("experiment_id"),
        "relative_path": row.get("relative_path"),
        "digest": row.get("digest"),
        "size": row.get("size"),
        "role": row.get("role"),
        "media_type": row.get("media_type"),
        "metadata": _bounded_value(row.get("metadata")),
        "recorded_at": row.get("recorded_at"),
        "event_sequence": row.get("event_sequence"),
    }


def build_agent_context(
    *,
    project: Mapping[str, Any],
    status: Mapping[str, Any],
    lineage: Sequence[Mapping[str, Any]],
    findings: Sequence[Mapping[str, Any]],
    artifacts: Sequence[Mapping[str, Any]],
    agent_spec: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    limit: int,
) -> dict[str, Any]:
    """Build one compact, provider-neutral context packet for coding agents."""

    parent_ids = {
        row.get("parent_id")
        for row in lineage
        if isinstance(row.get("parent_id"), str)
    }
    superseded_attempt_ids = {
        row.get("retry_of")
        for row in lineage
        if isinstance(row.get("retry_of"), str)
    }
    referenced_ids = parent_ids | superseded_attempt_ids
    frontier = [
        row for row in lineage if row.get("experiment_id") not in referenced_ids
    ]
    retryable = [
        row
        for row in lineage
        if row.get("retryable") is True
        and row.get("experiment_id") not in superseded_attempt_ids
    ]
    context = {
        "schema_version": 1,
        "kind": "research-os-agent-context",
        "snapshot": dict(snapshot),
        "project": dict(project),
        "agent": {**dict(agent_spec), "spec_digest": sha256_json(agent_spec)},
        "state": dict(status),
        "graph": {
            "recent": [_compact_experiment(row) for row in lineage[-limit:]],
            "frontier": [_compact_experiment(row) for row in frontier[-limit:]],
            "retryable": [_compact_experiment(row) for row in retryable[-limit:]],
            "total_experiments": len(lineage),
            "recent_returned": min(limit, len(lineage)),
            "recent_truncated": len(lineage) > limit,
            "frontier_total": len(frontier),
            "frontier_returned": min(limit, len(frontier)),
            "frontier_truncated": len(frontier) > limit,
            "retryable_total": len(retryable),
            "retryable_returned": min(limit, len(retryable)),
            "retryable_truncated": len(retryable) > limit,
        },
        "evidence": {
            "recent_findings": [
                _compact_finding(row) for row in findings[-limit:]
            ],
            "recent_artifacts": [
                _compact_artifact(row) for row in artifacts[-limit:]
            ],
            "findings_total": len(findings),
            "findings_returned": min(limit, len(findings)),
            "findings_truncated": len(findings) > limit,
            "artifacts_total": len(artifacts),
            "artifacts_returned": min(limit, len(artifacts)),
            "artifacts_truncated": len(artifacts) > limit,
        },
        "allowed_agent_actions": [
            "CONFIGURE_PROJECT",
            "RUN_DOCTOR",
            "SEAL_BASELINE",
            "PROPOSE_ONE_CANDIDATE",
            "RUN_ONE_CANDIDATE",
            "RETRY_ELIGIBLE_ATTEMPT",
            "INSPECT_EVIDENCE",
            "STOP_AND_REPORT",
        ],
        "authority": {
            "authorized_action": None,
            "deployment": False,
            "live_trading": False,
        },
    }
    context["packet_size_bytes"] = 0
    for _ in range(4):
        size = len(canonical_json_bytes(context))
        if context["packet_size_bytes"] == size:
            break
        context["packet_size_bytes"] = size
    size = len(canonical_json_bytes(context))
    context["packet_size_bytes"] = size
    if size > MAX_AGENT_CONTEXT_BYTES:
        raise ConfigurationError(
            "agent context exceeds the 2 MiB packet limit; reduce --limit or "
            "shorten the research brief/schema"
        )
    return context


__all__ = [
    "AGENT_BRIEF_RELATIVE",
    "AGENT_JOURNAL_RELATIVE",
    "CANDIDATE_INBOX_RELATIVE",
    "CANDIDATE_SCHEMA_RELATIVE",
    "MAX_AGENT_CONTEXT_BYTES",
    "build_agent_context",
    "load_agent_spec",
]
