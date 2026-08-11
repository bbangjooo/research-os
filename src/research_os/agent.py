"""Agent-facing project context and local skill installation helpers."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Final, Mapping, Sequence

from research_os.contracts import canonical_json_bytes, decode_json_object, sha256_json
from research_os.errors import (
    ConfigurationError,
    IntegrityError,
    ProgramMemoryError,
    StaleAgentContextError,
)
from research_os.kernel.events import EventLog
from research_os.memory.claims import ClaimSnapshot
from research_os.memory.knowledge import (
    ProposalKnowledgeDisposition,
    validate_proposal_knowledge_disposition,
)
from research_os.memory.program import ProgramEvent, ProgramHead, ProgramStore
from research_os.memory.retrieval import RetrievalQuery, RetrievalResult, retrieve_claims
from research_os.science.proposals import Proposal

AGENT_BRIEF_RELATIVE: Final = Path(".research-os/research-brief.md")
CANDIDATE_SCHEMA_RELATIVE: Final = Path(".research-os/candidate.schema.json")
CANDIDATE_INBOX_RELATIVE: Final = Path(".research-os/candidate.inbox.json")
AGENT_JOURNAL_RELATIVE: Final = Path(".research-os/agent-journal.jsonl")

_CONTROL_DIR: Final = ".research-os"
_MAX_AGENT_FILE_BYTES: Final = 256 * 1024
_MAX_CONTEXT_VALUE_BYTES: Final = 32 * 1024
MAX_AGENT_CONTEXT_BYTES: Final = 2 * 1024 * 1024
_CANDIDATE_SCHEMA_URI: Final = "https://json-schema.org/draft/2020-12/schema"
_REQUIRED_BRIEF_HEADINGS: Final = frozenset(
    {
        "# Research brief",
        "## Authority",
        "## Candidate semantics",
        "## Evaluation certification",
        "## Evidence and constraints",
        "## Golden controls",
        "## Graph proposal policy",
        "## Holdout boundary",
        "## Hypothesis classes and failure threshold",
        "## Objective",
        "## Search budget",
        "## Stop conditions",
        "## Universe preregistration",
    }
)


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

        control_before = os.stat(_CONTROL_DIR, dir_fd=root_fd, follow_symlinks=False)
        if stat.S_ISLNK(control_before.st_mode) or not stat.S_ISDIR(control_before.st_mode):
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
        if _stable_stat(after_descriptor) != _stable_stat(opened) or _stable_stat(
            after_path
        ) != _stable_stat(opened):
            raise IntegrityError(f"agent control file changed while reading: {name}")

        control_after = os.stat(_CONTROL_DIR, dir_fd=root_fd, follow_symlinks=False)
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
            raise ConfigurationError(f"agent control file must be UTF-8 text: {name}") from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if control_fd >= 0:
            os.close(control_fd)
        if root_fd >= 0:
            os.close(root_fd)


def _brief_is_configured(brief: str | None) -> bool:
    if brief is None or not brief.strip() or "REPLACE_ME" in brief:
        return False
    headings = {line.strip() for line in brief.splitlines() if line.startswith("#")}
    return _REQUIRED_BRIEF_HEADINGS.issubset(headings)


def _candidate_schema_is_configured(schema: Mapping[str, Any] | None) -> bool:
    if schema is None or schema.get("x-research-os-configured") is not True:
        return False
    if (
        schema.get("$schema") != _CANDIDATE_SCHEMA_URI
        or schema.get("type") != "object"
        or schema.get("additionalProperties") is not False
        or b"REPLACE_ME" in canonical_json_bytes(schema)
    ):
        return False
    properties = schema.get("properties")
    if isinstance(properties, Mapping) and properties:
        return True
    return any(
        isinstance(schema.get(keyword), Sequence)
        and not isinstance(schema.get(keyword), (str, bytes, bytearray))
        and bool(schema.get(keyword))
        for keyword in ("allOf", "anyOf", "oneOf")
    )


def load_agent_spec(
    root: Path,
    *,
    evaluator_certification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Load project research controls and derive fail-closed agent readiness."""

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

    brief_configured = _brief_is_configured(brief)
    candidate_schema_configured = _candidate_schema_is_configured(schema)
    setup_configured = brief_configured and candidate_schema_configured
    certification = (
        dict(evaluator_certification)
        if evaluator_certification is not None
        else {
            "certified": False,
            "current": False,
            "reason": "missing",
        }
    )
    evaluator_certified = bool(
        certification.get("certified") is True and certification.get("current") is True
    )
    blockers: list[str] = []
    if not setup_configured:
        blockers.append("research_brief_or_candidate_schema_not_configured")
    if not evaluator_certified:
        reason = certification.get("reason")
        if not isinstance(reason, str) or not reason:
            status = certification.get("status")
            reason = status.lower() if isinstance(status, str) else "required"
        blockers.append("evaluator_certification_" + reason)
    return {
        "configured": setup_configured and evaluator_certified,
        "setup_configured": setup_configured,
        "brief_configured": brief_configured,
        "candidate_schema_configured": candidate_schema_configured,
        "research_ready": setup_configured and evaluator_certified,
        "setup_blockers": blockers,
        "brief_path": AGENT_BRIEF_RELATIVE.as_posix(),
        "candidate_schema_path": CANDIDATE_SCHEMA_RELATIVE.as_posix(),
        "candidate_inbox_path": CANDIDATE_INBOX_RELATIVE.as_posix(),
        "journal_path": AGENT_JOURNAL_RELATIVE.as_posix(),
        "brief": brief,
        "candidate_schema": schema,
        "evaluator_certification": certification,
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


def _finalize_context_size(context: dict[str, Any]) -> dict[str, Any]:
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


def _attach_retrieval(context: Mapping[str, Any], retrieval: RetrievalResult) -> dict[str, Any]:
    if context.get("schema_version") != 3:
        raise ValueError("retrieval can only bind to agent context schema version 3")
    raw_snapshot = context.get("snapshot")
    if not isinstance(raw_snapshot, Mapping):
        raise ValueError("agent context snapshot must be an object")
    project_snapshot = dict(raw_snapshot)
    project_token = project_snapshot.get("context_token")
    if not isinstance(project_token, str) or not project_token:
        raise ValueError("project context snapshot must have a non-empty context_token")
    memory = {
        "memory_schema_version": 1,
        "query": retrieval.query.to_dict(),
        "query_digest": retrieval.query.digest,
        "retrieval_result": retrieval.to_dict(),
        "retrieval_result_digest": retrieval.digest,
        "authorized_action": None,
    }
    bound_snapshot = {
        "schema_version": 3,
        "project_snapshot": project_snapshot,
        "program": {
            "program_id": retrieval.program_id,
            "program_head": {
                "sequence": retrieval.program_head[0],
                "hash": retrieval.program_head[1],
            },
            "query_digest": retrieval.query.digest,
            "retrieval_result_digest": retrieval.digest,
        },
        "authorized_action": None,
    }
    bound_snapshot["context_token"] = sha256_json(bound_snapshot)
    attached = dict(context)
    attached["snapshot"] = bound_snapshot
    attached["memory"] = memory
    return attached


def bind_agent_context_v3_retrieval(
    context: Mapping[str, Any], retrieval: RetrievalResult
) -> dict[str, Any]:
    """Attach a read-only retrieval manifest and bind it into a Context v3 token."""

    if not isinstance(retrieval, RetrievalResult):
        raise TypeError("retrieval must be a RetrievalResult")
    return _finalize_context_size(_attach_retrieval(context, retrieval))


def _non_null_authority(value: object) -> int:
    if isinstance(value, Mapping):
        return int("authorized_action" in value and value["authorized_action"] is not None) + sum(
            _non_null_authority(item) for item in value.values()
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray, memoryview)):
        return sum(_non_null_authority(item) for item in value)
    return 0


def validate_agent_context_v3_retrieval(
    context: Mapping[str, Any],
    *,
    current_project_context_token: str,
    current_claim_snapshot: ClaimSnapshot,
) -> RetrievalResult:
    """Recompute the complete retrieval read set and reject any stale binding."""

    if not isinstance(current_project_context_token, str) or not current_project_context_token:
        raise TypeError("current_project_context_token must be non-empty text")
    if not isinstance(current_claim_snapshot, ClaimSnapshot):
        raise TypeError("current_claim_snapshot must be a ClaimSnapshot")
    try:
        if context.get("schema_version") != 3 or _non_null_authority(context):
            raise ValueError("invalid Context v3 authority or schema")
        snapshot = context.get("snapshot")
        memory = context.get("memory")
        if not isinstance(snapshot, Mapping) or set(snapshot) != {
            "schema_version",
            "project_snapshot",
            "program",
            "authorized_action",
            "context_token",
        }:
            raise ValueError("invalid bound context snapshot")
        snapshot_version = snapshot.get("schema_version")
        if (
            isinstance(snapshot_version, bool)
            or not isinstance(snapshot_version, int)
            or snapshot_version != 3
            or snapshot.get("authorized_action") is not None
        ):
            raise ValueError("invalid bound context snapshot schema or authority")
        project_snapshot = snapshot.get("project_snapshot")
        program = snapshot.get("program")
        if not isinstance(project_snapshot, Mapping) or not isinstance(program, Mapping):
            raise ValueError("invalid bound context read set")
        if project_snapshot.get("context_token") != current_project_context_token:
            raise ValueError("project context token changed")
        if not isinstance(memory, Mapping) or set(memory) != {
            "memory_schema_version",
            "query",
            "query_digest",
            "retrieval_result",
            "retrieval_result_digest",
            "authorized_action",
        }:
            raise ValueError("invalid retrieval memory manifest")
        memory_version = memory.get("memory_schema_version")
        if (
            isinstance(memory_version, bool)
            or not isinstance(memory_version, int)
            or memory_version != 1
            or memory.get("authorized_action") is not None
        ):
            raise ValueError("invalid retrieval memory schema or authority")
        query_raw = memory.get("query")
        result_raw = memory.get("retrieval_result")
        if not isinstance(query_raw, Mapping) or not isinstance(result_raw, Mapping):
            raise ValueError("invalid retrieval query or result")
        query = RetrievalQuery.from_mapping(query_raw)
        if memory.get("query_digest") != query.digest:
            raise ValueError("retrieval query digest changed")
        expected = retrieve_claims(current_claim_snapshot, query)
        if (
            canonical_json_bytes(result_raw) != canonical_json_bytes(expected.to_dict())
            or memory.get("retrieval_result_digest") != expected.digest
        ):
            raise ValueError("retrieval result changed")
        expected_program = {
            "program_id": expected.program_id,
            "program_head": {
                "sequence": expected.program_head[0],
                "hash": expected.program_head[1],
            },
            "query_digest": expected.query.digest,
            "retrieval_result_digest": expected.digest,
        }
        if canonical_json_bytes(program) != canonical_json_bytes(expected_program):
            raise ValueError("bound Program read set changed")
        supplied_token = snapshot.get("context_token")
        unsigned = dict(snapshot)
        unsigned.pop("context_token", None)
        if supplied_token != sha256_json(unsigned):
            raise ValueError("bound context token changed")
        return expected
    except (ProgramMemoryError, TypeError, ValueError) as exc:
        raise StaleAgentContextError(
            "agent retrieval context is stale; refresh Context v3 from canonical memory"
        ) from exc


def record_agent_context_v3_knowledge_disposition(
    context: Mapping[str, Any],
    *,
    current_project_context_token: str,
    current_claim_snapshot: ClaimSnapshot,
    proposal: Proposal,
    disposition: ProposalKnowledgeDisposition | Mapping[str, Any],
    program_store: ProgramStore,
    project_log: EventLog,
    expected_program_head: ProgramHead,
    event_id: str | None = None,
    occurred_at: str | None = None,
) -> ProgramEvent:
    """Validate one complete Context read set and durably record its disposition."""

    retrieval = validate_agent_context_v3_retrieval(
        context,
        current_project_context_token=current_project_context_token,
        current_claim_snapshot=current_claim_snapshot,
    )
    snapshot = context.get("snapshot")
    if not isinstance(snapshot, Mapping):  # pragma: no cover - validator authority
        raise StaleAgentContextError("agent retrieval context is stale")
    project_snapshot = snapshot.get("project_snapshot")
    combined_token = snapshot.get("context_token")
    if (
        not isinstance(project_snapshot, Mapping)
        or project_snapshot.get("project_id") != project_log.project_id
        or not isinstance(combined_token, str)
    ):
        raise StaleAgentContextError("agent retrieval context project identity is stale")
    parsed = validate_proposal_knowledge_disposition(
        disposition,
        project_id=project_log.project_id,
        proposal=proposal,
        retrieval=retrieval,
        context_token=combined_token,
    )
    return program_store.append_knowledge_disposition(
        parsed,
        proposal,
        retrieval,
        project_log,
        context_token=combined_token,
        expected_program_head=expected_program_head,
        event_id=event_id,
        occurred_at=occurred_at,
    )


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
        "graph_metadata_version": payload.get("graph_metadata_version"),
        "graph_action": payload.get("graph_action"),
        "scientific_change": _bounded_value(payload.get("scientific_change")),
        "candidate": _bounded_value(payload.get("candidate")),
        "outcome": _bounded_value(outcome_summary),
        "registered_at": row.get("registered_at"),
        "terminated_at": row.get("terminated_at"),
        "created_sequence": row.get("created_sequence"),
    }


def _compact_finding(row: Mapping[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    metadata = payload.get("metadata") if isinstance(payload, Mapping) else None
    branch_conclusion_version = row.get("branch_conclusion_version")
    if branch_conclusion_version is None and isinstance(payload, Mapping):
        branch_conclusion_version = payload.get("branch_conclusion_version")
    return {
        "finding_id": row.get("finding_id"),
        "experiment_id": row.get("experiment_id"),
        "finding_key": row.get("finding_key"),
        "scope": row.get("scope"),
        "content": _bounded_value(row.get("content")),
        "evidence": _bounded_value(row.get("evidence")),
        "metadata": _bounded_value(metadata),
        "branch_conclusion_version": branch_conclusion_version,
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
    current_compatibility_digest: str | None = None,
    compatible_baseline_ready: bool | None = None,
) -> dict[str, Any]:
    """Build one compact, provider-neutral context packet for coding agents."""

    research_ready = agent_spec.get("research_ready") is True
    if current_compatibility_digest is not None:
        if not isinstance(current_compatibility_digest, str) or not current_compatibility_digest:
            raise ValueError("current compatibility digest must be a non-empty string")
        lineage = [
            row
            for row in lineage
            if row.get("compatibility_digest") == current_compatibility_digest
        ]
    if compatible_baseline_ready is None:
        baseline_ready = (
            isinstance(status.get("baselines"), int)
            and not isinstance(status.get("baselines"), bool)
            and status.get("baselines", 0) > 0
        )
    elif isinstance(compatible_baseline_ready, bool):
        baseline_ready = compatible_baseline_ready
    else:
        raise TypeError("compatible_baseline_ready must be a boolean")

    parent_ids = {row.get("parent_id") for row in lineage if isinstance(row.get("parent_id"), str)}
    superseded_attempt_ids = {
        row.get("retry_of") for row in lineage if isinstance(row.get("retry_of"), str)
    }
    referenced_ids = parent_ids | superseded_attempt_ids
    frontier = [row for row in lineage if row.get("experiment_id") not in referenced_ids]
    retryable = [
        row
        for row in lineage
        if row.get("retryable") is True and row.get("experiment_id") not in superseded_attempt_ids
    ]
    context = {
        "schema_version": 2,
        "kind": "research-os-agent-context",
        "snapshot": dict(snapshot),
        "project": dict(project),
        "agent": {**dict(agent_spec), "spec_digest": sha256_json(agent_spec)},
        "state": dict(status),
        "graph": {
            "compatibility_digest": current_compatibility_digest,
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
        "proposal_contract": {
            "graph_metadata_version": 1,
            "graph_actions": ["explore", "exploit", "ablate", "replicate"],
            "scientific_change": "one non-empty conceptual intervention",
            "parent_rules": {
                "explore": "parent_id must be null",
                "exploit": "a compatible terminal parent is required",
                "ablate": "a compatible terminal parent is required",
                "replicate": "a compatible terminal parent is required",
            },
            "retry_rule": ("omit graph metadata; the prior attempt metadata is inherited"),
        },
        "evidence": {
            "recent_findings": [_compact_finding(row) for row in findings[-limit:]],
            "recent_artifacts": [_compact_artifact(row) for row in artifacts[-limit:]],
            "findings_total": len(findings),
            "findings_returned": min(limit, len(findings)),
            "findings_truncated": len(findings) > limit,
            "artifacts_total": len(artifacts),
            "artifacts_returned": min(limit, len(artifacts)),
            "artifacts_truncated": len(artifacts) > limit,
        },
        "allowed_agent_actions": (
            [
                "RUN_DOCTOR",
                "PROPOSE_ONE_CANDIDATE",
                "RUN_ONE_CANDIDATE",
                "RETRY_ELIGIBLE_ATTEMPT",
                "INSPECT_EVIDENCE",
                "CONCLUDE_BRANCH",
                "STOP_AND_REPORT",
            ]
            if research_ready and baseline_ready
            else [
                "RUN_DOCTOR",
                "SEAL_BASELINE",
                "INSPECT_EVIDENCE",
                "STOP_AND_REPORT",
            ]
            if research_ready
            else [
                "CONFIGURE_PROJECT",
                "RUN_DOCTOR",
                "CERTIFY_EVALUATOR",
                "INSPECT_EVIDENCE",
                "STOP_AND_REPORT",
            ]
        ),
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


def build_agent_context_v3(
    *,
    project: Mapping[str, Any],
    status: Mapping[str, Any],
    lineage: Sequence[Mapping[str, Any]],
    findings: Sequence[Mapping[str, Any]],
    artifacts: Sequence[Mapping[str, Any]],
    agent_spec: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    scientific_state: Mapping[str, Any],
    limit: int,
    current_compatibility_digest: str | None = None,
    compatible_baseline_ready: bool | None = None,
    retrieval: RetrievalResult | None = None,
) -> dict[str, Any]:
    """Add replay-derived scientific state without changing context v2."""

    context = build_agent_context(
        project=project,
        status=status,
        lineage=lineage,
        findings=findings,
        artifacts=artifacts,
        agent_spec=agent_spec,
        snapshot=snapshot,
        limit=limit,
        current_compatibility_digest=current_compatibility_digest,
        compatible_baseline_ready=compatible_baseline_ready,
    )
    science = dict(scientific_state)
    raw_pending = science.get("pending_diagnosis_experiment_ids", [])
    pending = (
        [str(value) for value in raw_pending]
        if isinstance(raw_pending, Sequence)
        and not isinstance(raw_pending, (str, bytes, bytearray))
        else []
    )
    context["schema_version"] = 3
    context["science"] = science
    context["diagnosis_authoring"] = {
        "command": "diagnosis-template",
        "pending_total": len(pending),
        "selection_required": len(pending) > 1,
        "agent_fields": [
            "interpretation",
            "failure_type",
            "falsifier",
            "recommendation",
        ],
        "failure_types": [
            "mechanism",
            "implementation",
            "evidence",
            "constraint",
            "operational",
            "supported",
        ],
        "recommendations": [
            "stop",
            "change_control",
            "explore",
            "ablate",
            "exploit",
            "replicate",
            "retry",
        ],
        "authorized_action": None,
    }
    study_stop = science.get("study_stop")
    stopped = isinstance(study_stop, Mapping) and study_stop.get("stopped") is True
    if pending:
        context["allowed_agent_actions"] = [
            "RUN_DOCTOR",
            "AUTHOR_PENDING_DIAGNOSIS",
            "INSPECT_EVIDENCE",
            "STOP_AND_REPORT",
        ]
    elif stopped:
        context["allowed_agent_actions"] = [
            "RUN_DOCTOR",
            "INSPECT_EVIDENCE",
            "STOP_AND_REPORT",
        ]
    if retrieval is not None:
        context = _attach_retrieval(context, retrieval)
    return _finalize_context_size(context)


__all__ = [
    "AGENT_BRIEF_RELATIVE",
    "AGENT_JOURNAL_RELATIVE",
    "CANDIDATE_INBOX_RELATIVE",
    "CANDIDATE_SCHEMA_RELATIVE",
    "MAX_AGENT_CONTEXT_BYTES",
    "bind_agent_context_v3_retrieval",
    "build_agent_context",
    "build_agent_context_v3",
    "load_agent_spec",
    "validate_agent_context_v3_retrieval",
]
