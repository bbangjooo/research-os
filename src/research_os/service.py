"""Domain-neutral orchestration for one bounded research project.

The service deliberately contains no model, market, or business-domain logic.
Projects own candidate semantics and evaluation through their adapter; the OS
owns isolation, budgets, provenance, lifecycle, and durable evidence.
"""

from __future__ import annotations

import fcntl
import math
import os
import stat
import tempfile
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from statistics import fmean
from typing import Any, cast

from .agent import build_agent_context, build_agent_context_v3, load_agent_spec
from .artifacts.catalog import ArtifactCatalog, ArtifactRecord
from .certification import (
    build_evaluator_review_subject,
    ensure_certification_gitignore,
    evaluator_certification_read_lock,
    inspect_evaluator_certification,
    record_evaluator_certification,
)
from .config import ProjectConfig, ensure_runtime_directory, load_project_config
from .contracts import (
    FailureCategory,
    Operation,
    ProtocolResponse,
    ResultEnvelope,
    TerminalStatus,
    VerifyResult,
    decode_json_object,
    normalize_json_object,
    sha256_json,
    validate_failure_category,
)
from .errors import (
    AgentResearchNotReadyError,
    ConfigurationError,
    EvaluatorCertificationError,
    IntegrityError,
    LifecycleError,
    ProtocolError,
    ScientificStateError,
    StaleAgentContextError,
)
from .execution.adapter import AdapterClient
from .execution.workspace import WorkspaceManager, hash_tree
from .graph_policy import (
    GraphMetadata,
    graph_metadata_from_values,
    inherit_retry_graph_metadata,
    validate_graph_candidate_change,
    validate_graph_relationship,
)
from .kernel.events import Event, EventHeadMismatchError, EventLog
from .kernel.ids import new_experiment_id, new_id, stable_id
from .kernel.lifecycle import coerce_state, is_terminal
from .kernel.projection import ProjectionStore
from .memory.findings import make_finding_event
from .policy import Decision, decide
from .provenance import environment_fingerprint, project_fingerprints
from .science import (
    DIAGNOSIS_EVENT_TYPE,
    GENERATION_EVENT_TYPE,
    Diagnosis,
    DiagnosisEventPayload,
    EvaluationSeal,
    Proposal,
    StudyContract,
    build_diagnosis_template,
    plan_diagnosis_append,
    plan_generation_open,
    proposal_id,
    reduce_scientific_state,
    registration_payload_fields,
    reserve_registration,
    validate_registration,
    validate_registration_preflight,
    validate_successor_preflight,
)

REQUIRED_OPERATIONS = frozenset(operation.value for operation in Operation)
EVALUATION_SCOPE_CAPABILITY = "evaluation_scope_v1"
_TERMINAL_EVENT_TYPES = frozenset(
    {"EXPERIMENT_TERMINATED", "EXPERIMENT_STATUS_CHANGED"}
)
_ARTIFACT_EVENT_TYPES = frozenset(
    {"ARTIFACT_RECORDED", "ARTIFACT_CAPTURED", "ARTIFACT_CATALOGUED"}
)
_PRESERVED_RECOVERY_REASON = "INTERRUPTED_EVIDENCE_UNTRUSTED"
_USE_CURRENT_PRIMARY_METRIC = object()


class _GenerationAlreadyOpen(RuntimeError):
    """Internal control flow for an identical generation-open race loser."""

    def __init__(self, generation_id: str):
        super().__init__(generation_id)
        self.generation_id = generation_id


class _ProjectAlreadyInitialized(RuntimeError):
    """Internal control flow for an initialization race loser."""


class _DiagnosisAlreadyRecorded(RuntimeError):
    """Internal control flow for an identical Diagnosis append race loser."""

    def __init__(self, event_id: str):
        super().__init__(event_id)
        self.event_id = event_id


def _normalized_event_type(value: str) -> str:
    return value.strip().upper().replace(".", "_").replace("-", "_")


class AdapterOperationError(ProtocolError):
    """A well-formed adapter response reported a failed operation."""

    def __init__(self, operation: Operation, response: ProtocolResponse):
        error = response.error
        self.operation = operation
        self.response = response
        self.code = error.code if error is not None else "ADAPTER_FAILED"
        if error is None:
            raise ProtocolError(f"{operation.value}: failed response omitted error")
        category = error.category
        if category is None:
            raise ProtocolError(
                f"{operation.value}: failed response omitted error.category"
            )
        try:
            self.category = validate_failure_category(operation, category)
        except (TypeError, ValueError) as exc:
            raise ProtocolError(
                f"{operation.value}: invalid failure category for {self.code}: {exc}"
            ) from exc
        self.retryable = response.retryable
        self.details = error.details
        message = error.message
        super().__init__(f"{operation.value}: {self.code}: {message}")


@dataclass(frozen=True, slots=True)
class DoctorReport:
    project_id: str
    project_root: str
    capabilities: tuple[str, ...]
    side_effects: tuple[Any, ...]
    adapter_fingerprint: Mapping[str, Any]
    fingerprints: Mapping[str, Any]
    event_count: int

    def to_dict(self) -> dict[str, Any]:
        result = {
            "project_id": self.project_id,
            "project_root": self.project_root,
            "healthy": True,
            "capabilities": list(self.capabilities),
            "side_effects": list(self.side_effects),
            "adapter_fingerprint": dict(self.adapter_fingerprint),
            "fingerprints": dict(self.fingerprints),
            "event_count": self.event_count,
            "authorized_action": None,
        }
        return normalize_json_object(result, field_name="doctor report")


def _response_payload(
    response: ProtocolResponse, operation: Operation
) -> dict[str, Any]:
    if not response.ok:
        raise AdapterOperationError(operation, response)
    return dict(response.payload)


def _result(response: ProtocolResponse, operation: Operation) -> ResultEnvelope:
    _response_payload(response, operation)
    try:
        envelope = response.result_envelope()
    except (TypeError, ValueError, KeyError) as exc:
        raise ProtocolError(
            f"{operation.value} returned an invalid result envelope: {exc}"
        ) from exc
    if envelope.status is not None:
        raise ProtocolError(
            f"{operation.value} returned status; terminal status is owned by the kernel"
        )
    return envelope


def _bind_captured_result(
    result: ResultEnvelope, records: Sequence[ArtifactRecord]
) -> ResultEnvelope:
    """Return the terminal envelope with OS-captured digest and size evidence."""

    by_path = {record.relative_path: record for record in records}
    if len(by_path) != len(records) or set(by_path) != {
        reference.path for reference in result.artifacts
    }:
        raise IntegrityError("captured artifacts do not match the result envelope")
    bound = []
    for reference in result.artifacts:
        record = by_path[reference.path]
        if (
            record.media_type != reference.media_type
            or record.metadata
            != {
                "retention": reference.retention,
                "sensitivity": reference.sensitivity,
            }
        ):
            raise IntegrityError("captured artifact metadata changed before termination")
        bound.append(reference.with_capture(sha256=record.digest, size_bytes=record.size))
    return replace(result, artifacts=tuple(bound))


def _legacy_public_run_summary(summary: Mapping[str, Any]) -> dict[str, Any]:
    """Keep run_once's v0.1-v0.4 shape while canonical terminals retain capture evidence."""

    raw_result = summary.get("result")
    if not isinstance(raw_result, Mapping):
        return dict(summary)
    raw_artifacts = raw_result.get("artifacts")
    if not isinstance(raw_artifacts, Sequence) or isinstance(
        raw_artifacts, (str, bytes, bytearray)
    ):
        return dict(summary)
    artifacts = []
    for raw in raw_artifacts:
        if not isinstance(raw, Mapping):
            return dict(summary)
        artifacts.append(
            {
                key: value
                for key, value in raw.items()
                if key not in {"sha256", "size_bytes"}
            }
        )
    return {
        **summary,
        "result": {**raw_result, "artifacts": artifacts},
    }


def _verify_result(response: ProtocolResponse) -> VerifyResult:
    """Parse one successful adapter VERIFY response under the shared contract."""

    _response_payload(response, Operation.VERIFY)
    try:
        return response.verify_result()
    except (TypeError, ValueError, KeyError) as exc:
        raise ProtocolError(f"verify returned an invalid verdict: {exc}") from exc


def _safe_error(exc: BaseException) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": type(exc).__name__,
        "message": str(exc),
    }
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code:
        result["code"] = code
    retryable = getattr(exc, "retryable", None)
    if isinstance(retryable, bool):
        result["retryable"] = retryable
    category = getattr(exc, "category", None)
    if isinstance(category, FailureCategory):
        result["category"] = category.value
    details = getattr(exc, "details", None)
    if isinstance(details, Mapping):
        try:
            result["details"] = dict(
                normalize_json_object(details, field_name="error.details")
            )
        except (TypeError, ValueError):
            result["details"] = {"normalization_error": "details were not JSON-safe"}
    notes = getattr(exc, "__notes__", None)
    if isinstance(notes, list) and all(isinstance(note, str) for note in notes):
        result["notes"] = list(notes)
    return result


def _classify_failure(exc: BaseException) -> tuple[TerminalStatus, str]:
    if isinstance(exc, AdapterOperationError):
        return exc.category.terminal_status, exc.code
    if isinstance(exc, TimeoutError):
        return TerminalStatus.TIMED_OUT, "ADAPTER_TIMEOUT"
    if isinstance(exc, IntegrityError):
        return TerminalStatus.UNTRUSTED, "INTEGRITY_CHECK_FAILED"
    if isinstance(exc, (ProtocolError, OSError)):
        return TerminalStatus.INFRA_FAILED, "INFRASTRUCTURE_FAILURE"
    return TerminalStatus.INFRA_FAILED, "UNEXPECTED_FAILURE"


def _terminal_retryable(
    status: TerminalStatus,
    reason_code: str,
    error: Mapping[str, Any] | None,
) -> bool:
    """Derive explicit retry eligibility from the terminal evidence."""

    if status in {
        TerminalStatus.INVALID_EXPERIMENT,
        TerminalStatus.REJECTED,
        TerminalStatus.VALIDATED,
        TerminalStatus.UNTRUSTED,
    }:
        return False
    if status in {TerminalStatus.TIMED_OUT, TerminalStatus.CANCELLED}:
        return True
    if (
        status is TerminalStatus.INFRA_FAILED
        and reason_code == "RECOVERED_INTERRUPTED_RUN"
    ):
        return True
    retryable_adapter_categories = {
        TerminalStatus.INFRA_FAILED: FailureCategory.INFRASTRUCTURE.value,
        TerminalStatus.INSUFFICIENT_EVIDENCE: (
            FailureCategory.INSUFFICIENT_EVIDENCE.value
        ),
    }
    expected_category = retryable_adapter_categories.get(status)
    return (
        expected_category is not None
        and isinstance(error, Mapping)
        and error.get("type") == "AdapterOperationError"
        and error.get("category") == expected_category
        and error.get("code") == reason_code
        and error.get("retryable") is True
    )


class ResearchService:
    """Coordinate one local project without interpreting its domain."""

    def __init__(self, root: str | Path):
        self.config: ProjectConfig = load_project_config(root)
        runtime = ensure_runtime_directory(self.config)
        self.event_log = EventLog(runtime / "events.jsonl", self.config.project_id)
        # A crash may leave only an uncommitted, non-newline tail. Recovery is
        # deterministic: EventLog first verifies the complete committed prefix
        # under its exclusive lock, then truncates only that final fragment.
        self.event_log.recover_tail()
        self.projection = ProjectionStore(runtime / "state.db")
        self.catalog = ArtifactCatalog(
            runtime / "artifacts", self.config.max_artifact_bytes
        )
        self.adapter = AdapterClient(self.config)

    def _assert_config_unchanged(self) -> None:
        """Fail closed when a cached service no longer matches project policy."""

        current = load_project_config(self.config.root)
        if current != self.config:
            raise IntegrityError(
                "project configuration changed after service construction; "
                "create a new ResearchService instance"
            )

    def inspect(self) -> dict[str, Any]:
        """Return the resolved local contract without invoking project code."""

        self._assert_config_unchanged()
        config = self.config
        return {
            "schema_version": 1,
            "project_id": config.project_id,
            "name": config.name,
            "root": str(config.root),
            "adapter_command": list(config.adapter_command),
            "paths": {
                "mutable": [path.as_posix() for path in config.mutable_paths],
                "protected": [path.as_posix() for path in config.protected_paths],
                "evidence": [path.as_posix() for path in config.evidence_paths],
                "runtime": config.runtime_dir.as_posix(),
            },
            "budget": {
                "timeout_seconds": config.timeout_seconds,
                "max_output_bytes": config.max_output_bytes,
                "max_artifact_bytes": config.max_artifact_bytes,
            },
            "objective": {
                "primary_metric": config.primary_metric,
                "direction": config.direction.value,
                "baseline_repeats": config.baseline_repeats,
                "baseline_tolerance": config.baseline_tolerance,
                "minimum_improvement": config.minimum_improvement,
            },
            "promotion": {
                "minimum_improvement": config.minimum_improvement,
                "gates": [gate.to_dict() for gate in config.gates],
            },
            "authorized_action": None,
        }

    def _call(
        self,
        operation: Operation,
        *,
        payload: Mapping[str, Any] | None = None,
        workspace: Path | None = None,
        experiment_id: str | None = None,
    ) -> ProtocolResponse:
        return self.adapter.call(
            operation,
            payload={} if payload is None else payload,
            workspace=workspace,
            experiment_id=experiment_id,
        )

    def _assert_static_compatibility(self, report: DoctorReport) -> None:
        """Verify every compatibility-bearing input against the doctor seal."""

        current_project = project_fingerprints(self.config)
        current_environment = current_project.get("environment")
        expected_environment = report.fingerprints.get("environment")
        if not isinstance(current_environment, Mapping) or current_environment.get(
            "digest"
        ) != (
            expected_environment.get("digest")
            if isinstance(expected_environment, Mapping)
            else None
        ):
            raise IntegrityError("adapter executable environment changed after doctor")
        expected_project_digest = report.fingerprints.get(
            "project_compatibility_digest"
        )
        if current_project.get("compatibility_digest") != expected_project_digest:
            raise IntegrityError(
                "project compatibility inputs changed after doctor"
            )

    def _assert_environment_compatibility(self, report: DoctorReport) -> None:
        """Check executable provenance without pre-empting stage recording."""

        current = environment_fingerprint(self.config)
        expected = report.fingerprints.get("environment")
        if current.get("digest") != (
            expected.get("digest") if isinstance(expected, Mapping) else None
        ):
            raise IntegrityError("adapter executable environment changed after doctor")

    def _call_sealed(
        self,
        report: DoctorReport,
        operation: Operation,
        *,
        payload: Mapping[str, Any] | None = None,
        workspace: Path | None = None,
        experiment_id: str | None = None,
    ) -> ProtocolResponse:
        self._assert_static_compatibility(report)
        response = self._call(
            operation,
            payload=payload,
            workspace=workspace,
            experiment_id=experiment_id,
        )
        # Project-local drift is checked by the caller's WorkspaceManager after
        # it has durably recorded this response. Checking only external argv
        # here keeps a valid failed adapter response available as evidence.
        self._assert_environment_compatibility(report)
        return response

    def _sync(self) -> int:
        return self.projection.sync(self.event_log)

    def _verify_projected_artifact(
        self, projected: Mapping[str, Any]
    ) -> ArtifactRecord:
        payload = projected.get("payload")
        if not isinstance(payload, Mapping):
            raise IntegrityError("projected artifact is missing canonical payload")
        expected = ArtifactRecord.from_mapping(payload)
        if expected.project_id != self.config.project_id:
            raise IntegrityError("projected artifact belongs to another project")
        if projected.get("artifact_id") != expected.artifact_id:
            raise IntegrityError("projected artifact ID disagrees with canonical payload")
        stored = self.catalog.get(expected.artifact_id)
        if stored.to_dict() != expected.to_dict():
            raise IntegrityError(
                "artifact manifest disagrees with canonical ARTIFACT_RECORDED evidence"
            )
        return stored

    def _verify_terminal_artifact_bindings(
        self,
        projected_records: Sequence[tuple[Mapping[str, Any], ArtifactRecord]],
        *,
        events: Sequence[Event] | None = None,
    ) -> None:
        """Bind every terminal result declaration to earlier canonical artifacts."""

        by_experiment: dict[
            str, list[tuple[Mapping[str, Any], ArtifactRecord]]
        ] = {}
        for projected, record in projected_records:
            by_experiment.setdefault(record.experiment_id, []).append(
                (projected, record)
            )

        canonical_events = self.event_log.read() if events is None else events
        for event in canonical_events:
            event_type = _normalized_event_type(event.event_type)
            if event_type not in _TERMINAL_EVENT_TYPES:
                continue
            if event_type == "EXPERIMENT_STATUS_CHANGED":
                status = event.payload.get("status", event.payload.get("state"))
                try:
                    if not isinstance(status, str) or not is_terminal(status):
                        continue
                except (LifecycleError, TypeError, ValueError) as exc:
                    raise IntegrityError("terminal status event is invalid") from exc
            if "result" not in event.payload:
                # Recovery/legacy terminals may carry no result.  Artifact
                # records can still precede a recovery terminal, but there is
                # no declaration here to bind in that case.
                continue
            result_value = event.payload["result"]
            if not isinstance(result_value, Mapping):
                raise IntegrityError("terminal result must be an object")
            try:
                result = ResultEnvelope.from_mapping(
                    cast(Mapping[str, Any], result_value)
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise IntegrityError(f"terminal result is invalid: {exc}") from exc
            if result.status is not None:
                raise IntegrityError("terminal result cannot declare kernel status")
            experiment_id = event.payload.get(
                "experiment_id", event.payload.get("id")
            )
            if not isinstance(experiment_id, str) or not experiment_id:
                raise IntegrityError("terminal result has an invalid experiment ID")
            actual_records: dict[
                str, tuple[Mapping[str, Any], ArtifactRecord]
            ] = {}
            for projected, record in by_experiment.get(experiment_id, []):
                if record.relative_path in actual_records:
                    raise IntegrityError(
                        "terminal result has duplicate artifact paths in history"
                    )
                actual_records[record.relative_path] = (projected, record)
            expected = {reference.path: reference for reference in result.artifacts}
            if set(actual_records) != set(expected):
                missing = sorted(set(expected) - set(actual_records))
                extra = sorted(set(actual_records) - set(expected))
                detail = []
                if missing:
                    detail.append("missing=" + ",".join(missing))
                if extra:
                    detail.append("extra=" + ",".join(extra))
                raise IntegrityError(
                    "terminal artifact declarations do not match canonical records"
                    + (": " + "; ".join(detail) if detail else "")
                )
            for path, reference in expected.items():
                projected, record = actual_records[path]
                sequence = projected.get("event_sequence")
                if (
                    isinstance(sequence, bool)
                    or not isinstance(sequence, int)
                    or sequence >= event.sequence
                ):
                    raise IntegrityError(
                        f"terminal artifact was not recorded before termination: {path}"
                    )
                if (
                    record.project_id != self.config.project_id
                    or record.experiment_id != experiment_id
                    or record.role is not None
                    or record.media_type != reference.media_type
                    or dict(record.metadata)
                    != {
                        "retention": reference.retention,
                        "sensitivity": reference.sensitivity,
                    }
                    or (
                        reference.sha256 is not None
                        and record.digest != reference.sha256
                    )
                    or (
                        reference.size_bytes is not None
                        and record.size != reference.size_bytes
                    )
                ):
                    raise IntegrityError(
                        f"terminal artifact metadata is inconsistent: {path}"
                    )

    def _publish_artifact_records(
        self, experiment_id: str, records: Sequence[ArtifactRecord]
    ) -> None:
        """Idempotently bind captured manifests into canonical history."""

        existing: dict[str, ArtifactRecord] = {}
        for event in self.event_log.read():
            if _normalized_event_type(event.event_type) not in _ARTIFACT_EVENT_TYPES:
                continue
            record = ArtifactRecord.from_mapping(event.payload)
            if record.artifact_id in existing:
                raise IntegrityError(
                    f"duplicate artifact event for {record.artifact_id}"
                )
            existing[record.artifact_id] = record
        for record in records:
            if record.project_id != self.config.project_id or (
                record.experiment_id != experiment_id
            ):
                raise IntegrityError("captured artifact identity is inconsistent")
            prior = existing.get(record.artifact_id)
            if prior is not None:
                if prior.to_dict() != record.to_dict():
                    raise IntegrityError(
                        "canonical artifact event disagrees with captured manifest"
                    )
                continue
            self.event_log.append(
                "ARTIFACT_RECORDED",
                {**record.to_dict(), "authorized_action": None},
            )
            existing[record.artifact_id] = record

    def _artifact_records_are_published(
        self, experiment_id: str, records: Sequence[ArtifactRecord]
    ) -> bool:
        """Prove that every captured record already has exact canonical evidence."""

        expected = {record.artifact_id: record for record in records}
        if len(expected) != len(records):
            raise IntegrityError("captured artifact records contain duplicate IDs")
        observed: dict[str, ArtifactRecord] = {}
        for event in self.event_log.read():
            if _normalized_event_type(event.event_type) not in _ARTIFACT_EVENT_TYPES:
                continue
            record = ArtifactRecord.from_mapping(event.payload)
            if record.experiment_id != experiment_id:
                continue
            if record.artifact_id in observed:
                raise IntegrityError(
                    f"duplicate artifact event for {record.artifact_id}"
                )
            observed[record.artifact_id] = record
        for artifact_id, record in expected.items():
            published = observed.get(artifact_id)
            if published is not None and published.to_dict() != record.to_dict():
                raise IntegrityError(
                    "canonical artifact event disagrees with captured manifest"
                )
        return all(artifact_id in observed for artifact_id in expected)

    @contextmanager
    def _workflow_lock(self):
        """Enforce the v1 single-local-worker execution model."""

        path = self.config.resolved_runtime_dir / "workflow.lock"
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise IntegrityError(f"cannot open workflow lock: {path}") from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise IntegrityError("workflow lock is not a regular file")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ConfigurationError(
                    "another baseline or experiment is already running for this project"
                ) from exc
            yield
        finally:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)

    def _ensure_initialized(self, fingerprints: Mapping[str, Any]) -> None:
        events = self.event_log.read()
        if events:
            if _normalized_event_type(events[0].event_type) != "PROJECT_INITIALIZED":
                raise IntegrityError(
                    "the first canonical event must initialize the project"
                )
            self._sync()
            return
        self.event_log.append(
            "PROJECT_INITIALIZED",
            {
                "project_id": self.config.project_id,
                "status": "active",
                "metadata": {
                    "name": self.config.name,
                    "schema_version": 1,
                    "initial_compatibility_digest": fingerprints[
                        "compatibility_digest"
                    ],
                    "authorized_action": None,
                },
            },
        )
        self._sync()

    def _ensure_initialized_for_generation(
        self,
        fingerprints: Mapping[str, Any],
        *,
        events: Sequence[Event],
    ) -> tuple[Event, ...]:
        """Initialize an empty stream without serializing generation races."""

        if events:
            if _normalized_event_type(events[0].event_type) != "PROJECT_INITIALIZED":
                raise IntegrityError(
                    "the first canonical event must initialize the project"
                )
            return tuple(events)

        payload = {
            "project_id": self.config.project_id,
            "status": "active",
            "metadata": {
                "name": self.config.name,
                "schema_version": 1,
                "initial_compatibility_digest": fingerprints[
                    "compatibility_digest"
                ],
                "authorized_action": None,
            },
        }

        def require_empty(locked_events: tuple[Event, ...]) -> None:
            if not locked_events:
                return
            if _normalized_event_type(
                locked_events[0].event_type
            ) != "PROJECT_INITIALIZED":
                raise IntegrityError(
                    "the first canonical event must initialize the project"
                )
            raise _ProjectAlreadyInitialized()

        try:
            self.event_log.append(
                "PROJECT_INITIALIZED",
                payload,
                precondition=require_empty,
                postcondition=require_empty,
            )
        except _ProjectAlreadyInitialized:
            pass
        initialized = tuple(self.event_log.read())
        if (
            not initialized
            or _normalized_event_type(initialized[0].event_type)
            != "PROJECT_INITIALIZED"
        ):
            raise IntegrityError("project initialization did not become canonical")
        return initialized

    def doctor(self) -> DoctorReport:
        """Validate configuration and initialize canonical state atomically."""

        with self._workflow_lock():
            report = self._doctor()
            self._recover_incomplete_experiments()
            return replace(report, event_count=len(self.event_log.read()))

    def certify_evaluator(
        self,
        review_path: str | Path,
        *,
        replace: bool = False,
    ) -> dict[str, Any]:
        """Record an independent review bound to current scientific inputs."""

        with self._workflow_lock():
            report = self._doctor()
            self._recover_incomplete_experiments()
            record_evaluator_certification(
                self.config,
                review_path,
                fingerprints=report.fingerprints,
                fresh_fingerprints=lambda: self._doctor_snapshot().fingerprints,
                replace=replace,
            )
            current = self._doctor_snapshot()
            return inspect_evaluator_certification(
                self.config,
                fingerprints=current.fingerprints,
            )

    def evaluator_review_subject(self) -> dict[str, Any]:
        """Return the exact current subject digest for independent review."""

        with self._workflow_lock():
            report = self._doctor()
            self._recover_incomplete_experiments()
            return build_evaluator_review_subject(
                self.config,
                fingerprints=report.fingerprints,
            )

    def open_generation(
        self,
        contract: str | Path | Mapping[str, Any],
        *,
        predecessor_generation_id: str | None = None,
        change_reason: str | None = None,
    ) -> dict[str, Any]:
        """Open one evaluation-sealed study generation atomically.

        Generation change control is canonical-event authority, so this path
        deliberately does not use the process-local workflow lock.  The
        authoritative plan is recalculated while EventLog holds its exclusive
        append lock, with the evaluator certification held stable across the
        complete write.
        """

        explicit_successor = (
            predecessor_generation_id is not None or change_reason is not None
        )
        if explicit_successor:
            with self.event_log.locked_read() as preflight_events:
                preflight_state = reduce_scientific_state(
                    tuple(preflight_events),
                    project_id=self.config.project_id,
                )
                validate_successor_preflight(preflight_state)

        raw_contract = (
            dict(contract)
            if isinstance(contract, Mapping)
            else self._load_json_object(contract, label="study contract")
        )
        study_contract = StudyContract.from_mapping(raw_contract)
        self._assert_config_unchanged()
        self.event_log.verify()
        events = tuple(self.event_log.read())
        current_state = reduce_scientific_state(
            events,
            project_id=self.config.project_id,
        )
        if (
            current_state.active_generation_id is not None
            and study_contract.digest != current_state.study_contract_digest
        ):
            validate_successor_preflight(current_state)

        event: Event | None = None
        appended_events = 0
        try:
            with evaluator_certification_read_lock(self.config):
                report = self._doctor_snapshot(event_count=len(events))
                evaluation_seal = self._evaluation_seal_from_report(report)
                self._validate_typed_generation_environment(
                    study_contract,
                    report,
                )
                events = self._ensure_initialized_for_generation(
                    report.fingerprints,
                    events=events,
                )
                # Planning failures and idempotent confirmations are also
                # scientific-state decisions. Keep the verified snapshot
                # locked while deriving them; append-required plans are then
                # rerun under the exclusive append lock below.
                with self.event_log.locked_read() as planning_events:
                    plan = plan_generation_open(
                        tuple(planning_events),
                        project_id=self.config.project_id,
                        contract=study_contract,
                        evaluation_seal=evaluation_seal,
                        predecessor_generation_id=predecessor_generation_id,
                        change_reason=change_reason,
                    )
                    if not plan.append_required:
                        fresh_report = self._doctor_snapshot(
                            event_count=len(planning_events)
                        )
                        fresh_seal = self._evaluation_seal_from_report(fresh_report)
                        self._validate_typed_generation_environment(
                            study_contract,
                            fresh_report,
                        )
                        if (
                            fresh_report.capabilities != report.capabilities
                            or fresh_report.side_effects != report.side_effects
                            or fresh_report.adapter_fingerprint
                            != report.adapter_fingerprint
                            or fresh_report.fingerprints != report.fingerprints
                            or fresh_seal.digest != evaluation_seal.digest
                        ):
                            raise IntegrityError(
                                "evaluation seal changed before generation confirmation"
                            )
                        locked_plan = plan_generation_open(
                            tuple(planning_events),
                            project_id=self.config.project_id,
                            contract=study_contract,
                            evaluation_seal=fresh_seal,
                            predecessor_generation_id=predecessor_generation_id,
                            change_reason=change_reason,
                        )
                        if locked_plan.append_required:
                            raise IntegrityError(
                                "study generation plan changed before idempotent confirmation"
                            )
                        generation_id = locked_plan.generation_id
                if plan.append_required:
                    proposed_payload = dict(plan.payload)

                    def validate_locked_plan(locked_events: tuple[Event, ...]) -> None:
                        fresh_report = self._doctor_snapshot(
                            event_count=len(locked_events)
                        )
                        fresh_seal = self._evaluation_seal_from_report(fresh_report)
                        self._validate_typed_generation_environment(
                            study_contract,
                            fresh_report,
                        )
                        if (
                            fresh_report.capabilities != report.capabilities
                            or fresh_report.side_effects != report.side_effects
                            or fresh_report.adapter_fingerprint
                            != report.adapter_fingerprint
                            or fresh_report.fingerprints != report.fingerprints
                            or fresh_seal.digest != evaluation_seal.digest
                        ):
                            raise IntegrityError(
                                "evaluation seal changed before generation commit"
                            )
                        locked_plan = plan_generation_open(
                            locked_events,
                            project_id=self.config.project_id,
                            contract=study_contract,
                            evaluation_seal=fresh_seal,
                            predecessor_generation_id=predecessor_generation_id,
                            change_reason=change_reason,
                        )
                        if not locked_plan.append_required:
                            raise _GenerationAlreadyOpen(locked_plan.generation_id)
                        if (
                            locked_plan.generation_id != plan.generation_id
                            or locked_plan.event_type != plan.event_type
                            or dict(locked_plan.payload) != proposed_payload
                        ):
                            raise IntegrityError(
                                "study generation plan changed before canonical append"
                            )

                    event = self.event_log.append(
                        plan.event_type,
                        proposed_payload,
                        precondition=validate_locked_plan,
                        postcondition=validate_locked_plan,
                    )
                    generation_id = plan.generation_id
                    appended_events = 1
        except _GenerationAlreadyOpen as raced:
            generation_id = raced.generation_id

        self._sync()
        result: dict[str, Any] = {
            "project_id": self.config.project_id,
            "event_type": GENERATION_EVENT_TYPE,
            "generation_id": generation_id,
            "study_contract_digest": study_contract.digest,
            "evaluation_seal_digest": evaluation_seal.digest,
            "predecessor_generation_id": predecessor_generation_id,
            "change_reason": change_reason,
            "appended": appended_events == 1,
            "appended_events": appended_events,
            "authorized_action": None,
        }
        if event is not None:
            result["event_sequence"] = event.sequence
        return normalize_json_object(result, field_name="generation open result")

    def record_diagnosis(
        self,
        diagnosis: str | Path | Mapping[str, Any],
    ) -> dict[str, Any]:
        """Append one exact terminal Diagnosis or reuse its canonical event.

        Diagnosis is scientific-state authority rather than adapter work, so it
        serializes directly on EventLog's exclusive append lock.  The pure plan
        is rerun against the verified locked history immediately before and
        after the provisional write.  This keeps Diagnosis, registration, and
        generation races on one canonical ordering without a process-local
        workflow-lock decision seam.
        """

        raw_diagnosis = (
            diagnosis
            if isinstance(diagnosis, Mapping)
            else self._load_json_object(diagnosis, label="diagnosis")
        )
        typed_diagnosis = Diagnosis.from_mapping(raw_diagnosis)
        self._assert_config_unchanged()

        with self.event_log.locked_read() as planning_events:
            initial_plan = plan_diagnosis_append(
                tuple(planning_events),
                project_id=self.config.project_id,
                diagnosis=typed_diagnosis,
            )
        appended = False
        canonical_event_id = initial_plan.existing_event_id
        if initial_plan.append_required:
            proposed_payload = dict(initial_plan.payload)

            def validate_locked_plan(locked_events: tuple[Event, ...]) -> None:
                locked_plan = plan_diagnosis_append(
                    locked_events,
                    project_id=self.config.project_id,
                    diagnosis=typed_diagnosis,
                )
                if not locked_plan.append_required:
                    existing_event_id = locked_plan.existing_event_id
                    if not isinstance(existing_event_id, str):  # pragma: no cover
                        raise IntegrityError(
                            "idempotent Diagnosis plan omitted its canonical event ID"
                        )
                    raise _DiagnosisAlreadyRecorded(existing_event_id)
                if (
                    locked_plan.event_type != initial_plan.event_type
                    or locked_plan.diagnosis_id != initial_plan.diagnosis_id
                    or locked_plan.diagnosis_digest
                    != initial_plan.diagnosis_digest
                    or dict(locked_plan.payload) != proposed_payload
                ):
                    raise IntegrityError(
                        "Diagnosis append plan changed before canonical commit"
                    )

            try:
                event = self.event_log.append(
                    initial_plan.event_type,
                    proposed_payload,
                    precondition=validate_locked_plan,
                    postcondition=validate_locked_plan,
                )
            except _DiagnosisAlreadyRecorded as raced:
                canonical_event_id = raced.event_id
            else:
                appended = True
                canonical_event_id = event.event_id

        if not isinstance(canonical_event_id, str):  # pragma: no cover - plan invariant
            raise IntegrityError("Diagnosis plan omitted its canonical event identity")

        # Replay a fresh, fully verified stream before returning.  This rejects
        # persisted duplicate Diagnosis corruption while still allowing a
        # legitimate successor generation to commit after this operation's
        # linearization point.
        canonical_events = tuple(self.event_log.read())
        reduce_scientific_state(
            canonical_events,
            project_id=self.config.project_id,
        )
        matches = tuple(
            event
            for event in canonical_events
            if event.event_id == canonical_event_id
        )
        if len(matches) != 1:
            raise IntegrityError("canonical Diagnosis event identity is not unique")
        canonical_event = matches[0]
        if canonical_event.event_type != DIAGNOSIS_EVENT_TYPE:
            raise IntegrityError("canonical Diagnosis event has the wrong event type")
        parsed_payload = DiagnosisEventPayload.from_mapping(
            canonical_event.payload,
            project_id=self.config.project_id,
        ).to_dict()
        if parsed_payload["diagnosis"] != typed_diagnosis.to_dict():
            raise IntegrityError("canonical Diagnosis body changed after append")
        if (
            parsed_payload["diagnosis_id"] != initial_plan.diagnosis_id
            or parsed_payload["diagnosis_digest"]
            != initial_plan.diagnosis_digest
        ):
            raise IntegrityError("canonical Diagnosis identity changed after append")

        self._sync()
        result = {
            "project_id": self.config.project_id,
            "event_type": DIAGNOSIS_EVENT_TYPE,
            "event_id": canonical_event.event_id,
            "event_hash": canonical_event.hash,
            "event_sequence": canonical_event.sequence,
            "experiment_id": typed_diagnosis.experiment_id,
            "diagnosis_id": initial_plan.diagnosis_id,
            "diagnosis_digest": initial_plan.diagnosis_digest,
            "appended": appended,
            "appended_events": int(appended),
            "idempotent_reuse": not appended,
            "authorized_action": None,
        }
        return normalize_json_object(result, field_name="Diagnosis record result")

    def diagnosis_template(
        self,
        experiment_id: str | None = None,
    ) -> dict[str, Any]:
        """Return one no-write Diagnosis body with agent judgment sentinels."""

        if experiment_id is not None and (
            not isinstance(experiment_id, str) or not experiment_id
        ):
            raise ValueError("experiment_id must be a non-empty string or null")
        self._assert_config_unchanged()
        self.event_log.verify()
        with self.event_log.locked_read() as events:
            state = reduce_scientific_state(
                tuple(events),
                project_id=self.config.project_id,
            )
            template = build_diagnosis_template(
                state,
                experiment_id=experiment_id,
            )
        return normalize_json_object(template, field_name="Diagnosis template")

    def _require_evaluation_scope_capability(
        self,
        report: DoctorReport,
    ) -> None:
        """Require the explicit adapter promise used by scoped studies."""

        if EVALUATION_SCOPE_CAPABILITY in report.capabilities:
            return
        raise ScientificStateError(
            "STUDY_SCOPE_CAPABILITY_REQUIRED",
            "StudyContract v2 requires adapter evaluation-scope support",
            details={"required_capability": EVALUATION_SCOPE_CAPABILITY},
        )

    def _validate_typed_generation_environment(
        self,
        contract: StudyContract,
        report: DoctorReport,
    ) -> None:
        """Bind a v2 generation to the advertised scope and candidate schema."""

        if contract.schema_version != 2:
            return
        self._require_evaluation_scope_capability(report)
        agent_spec = load_agent_spec(self.config.root)
        candidate_schema = agent_spec.get("candidate_schema")
        observed_digest = (
            sha256_json(candidate_schema)
            if isinstance(candidate_schema, Mapping)
            else None
        )
        expected_digest = contract.intervention_surface.candidate_schema_digest
        if observed_digest == expected_digest:
            return
        raise ScientificStateError(
            "STUDY_CANDIDATE_SCHEMA_MISMATCH",
            "StudyContract v2 candidate schema does not match the certified project schema",
            details={
                "expected_candidate_schema_digest": expected_digest,
                "observed_candidate_schema_digest": observed_digest,
            },
        )

    def _require_active_evaluation_seal(
        self,
        science_state: Any,
        report: DoctorReport,
    ) -> EvaluationSeal:
        """Require a fresh report to match the active generation seal."""

        live_seal = self._evaluation_seal_from_report(report)
        if live_seal.digest == science_state.evaluation_seal_digest:
            return live_seal
        raise ScientificStateError(
            "STUDY_EVALUATION_SEAL_MISMATCH",
            "the active generation is not bound to the current evaluator seal",
            details={
                "active_evaluation_seal_digest": (
                    science_state.evaluation_seal_digest
                ),
                "current_evaluation_seal_digest": live_seal.digest,
            },
        )

    def _resolve_baseline_evaluation_scope(
        self,
        science_state: Any,
        evaluation_scope_id: str | None,
    ) -> Any | None:
        """Resolve the full preregistered scope for a prospective baseline."""

        if science_state.active_generation_id is None:
            if evaluation_scope_id is not None:
                raise ScientificStateError(
                    "STUDY_GENERATION_REQUIRED",
                    "a scoped baseline requires an active study generation",
                )
            return None
        contract = science_state.contract
        if contract is None:  # pragma: no cover - reducer invariant
            raise IntegrityError("active generation omitted its study contract")
        if contract.schema_version != 2:
            if evaluation_scope_id is not None:
                raise ScientificStateError(
                    "STUDY_SCOPE_CONTRACT_VERSION_REQUIRED",
                    "evaluation_scope_id requires StudyContract v2",
                )
            return None
        if evaluation_scope_id is None:
            raise ScientificStateError(
                "STUDY_EVALUATION_SCOPE_REQUIRED",
                "StudyContract v2 baseline requires evaluation_scope_id",
            )
        evaluation_scope = next(
            (
                scope
                for scope in contract.evaluation_scopes
                if scope.id == evaluation_scope_id
            ),
            None,
        )
        if evaluation_scope is None:
            raise ScientificStateError(
                "STUDY_EVALUATION_SCOPE_UNKNOWN",
                "evaluation_scope_id is not declared by the active StudyContract",
                details={"evaluation_scope_id": evaluation_scope_id},
            )
        if evaluation_scope.role == "holdout":
            raise ScientificStateError(
                "STUDY_SCOPE_BASELINE_FORBIDDEN",
                "locked holdout scopes cannot be consumed by iterative baselines",
                details={"evaluation_scope_id": evaluation_scope.id},
            )
        return evaluation_scope

    def _append_scoped_baseline_event(
        self,
        payload: Mapping[str, Any],
    ) -> Event:
        """Commit a typed baseline only while its generation and seal are current."""

        scope_id = payload.get("evaluation_scope_id")
        if not isinstance(scope_id, str):  # pragma: no cover - caller invariant
            raise IntegrityError("typed baseline evaluation scope ID is invalid")

        def validate_locked_baseline(locked_events: tuple[Event, ...]) -> None:
            locked_state = reduce_scientific_state(
                locked_events,
                project_id=self.config.project_id,
            )
            scope = self._resolve_baseline_evaluation_scope(locked_state, scope_id)
            if scope is None:  # pragma: no cover - resolver invariant
                raise IntegrityError("typed baseline evaluation scope is unavailable")
            contract = locked_state.contract
            if contract is None:  # pragma: no cover - reducer invariant
                raise IntegrityError("typed baseline study contract is unavailable")
            if payload.get("generation_id") != locked_state.active_generation_id:
                raise ScientificStateError(
                    "STUDY_GENERATION_MISMATCH",
                    "baseline generation no longer matches the active generation",
                )
            if payload.get("study_contract_digest") != contract.digest:
                raise ScientificStateError(
                    "STUDY_CONTRACT_MISMATCH",
                    "baseline contract no longer matches the active generation",
                )
            if payload.get("evaluation_seal_digest") != (
                locked_state.evaluation_seal_digest
            ):
                raise ScientificStateError(
                    "STUDY_EVALUATION_SEAL_MISMATCH",
                    "baseline evaluator seal no longer matches the active generation",
                )
            if payload.get("evaluation_scope") != scope.to_dict():
                raise ScientificStateError(
                    "STUDY_EVALUATION_SCOPE_MISMATCH",
                    "baseline scope body disagrees with the active StudyContract",
                )
            fresh_report = self._doctor_snapshot(event_count=len(locked_events))
            self._validate_typed_generation_environment(contract, fresh_report)
            self._require_active_evaluation_seal(locked_state, fresh_report)
            if payload.get("compatibility_digest") != fresh_report.fingerprints.get(
                "compatibility_digest"
            ):
                raise IntegrityError(
                    "baseline compatibility changed before canonical append"
                )

        with evaluator_certification_read_lock(self.config):
            return self.event_log.append(
                "BASELINE_RECORDED",
                payload,
                precondition=validate_locked_baseline,
                postcondition=validate_locked_baseline,
            )

    def study_status(self) -> dict[str, Any]:
        """Return the replay-derived generation and reserved-budget state."""

        self._assert_config_unchanged()
        self.event_log.verify()
        state = reduce_scientific_state(
            self.event_log.read(),
            project_id=self.config.project_id,
        )
        return normalize_json_object(
            {
                **state.to_dict(),
                "project_id": self.config.project_id,
                "authorized_action": None,
            },
            field_name="study status",
        )

    def _doctor(self) -> DoctorReport:
        """Unlocked implementation for callers already holding the workflow lock."""

        ensure_certification_gitignore(self.config)
        report = self._doctor_snapshot()
        self._ensure_initialized(report.fingerprints)
        return replace(report, event_count=len(self.event_log.read()))

    def _doctor_snapshot(self, *, event_count: int | None = None) -> DoctorReport:
        """Compute a fresh doctor seal without certification or event mutation."""

        self._assert_config_unchanged()
        source_hash = hash_tree(self.config.root)
        fingerprints = project_fingerprints(self.config)
        describe = _response_payload(self._call(Operation.DESCRIBE), Operation.DESCRIBE)
        if hash_tree(self.config.root) != source_hash:
            raise IntegrityError("adapter describe modified the project checkout")
        capabilities_value = describe.get("capabilities")
        if (
            not isinstance(capabilities_value, Sequence)
            or isinstance(capabilities_value, (str, bytes, bytearray))
            or not all(isinstance(value, str) for value in capabilities_value)
        ):
            raise ProtocolError(
                "describe.capabilities must be an array of operation names"
            )
        capabilities = frozenset(str(value) for value in capabilities_value)
        missing = sorted(REQUIRED_OPERATIONS - capabilities)
        if missing:
            raise ProtocolError(
                "adapter is missing required capabilities: " + ", ".join(missing)
            )
        side_effects_value = describe.get("side_effects")
        if not isinstance(side_effects_value, Sequence) or isinstance(
            side_effects_value, (str, bytes, bytearray)
        ):
            raise ProtocolError("describe.side_effects must be an array")
        if side_effects_value:
            raise ConfigurationError(
                "v1 adapters must declare no external side effects; live actions are outside Research OS"
            )
        adapter_fingerprint = _response_payload(
            self._call(Operation.FINGERPRINT), Operation.FINGERPRINT
        )
        if hash_tree(self.config.root) != source_hash:
            raise IntegrityError("adapter fingerprint modified the project checkout")
        after_fingerprints = project_fingerprints(self.config)
        if after_fingerprints != fingerprints:
            raise IntegrityError("immutable project fingerprints drifted during doctor")
        adapter_fingerprint_digest = sha256_json(adapter_fingerprint)
        effective_fingerprints = {
            **fingerprints,
            # This is an execution-snapshot seal used to recover an orphaned
            # workspace.  Compatibility itself remains the project+adapter
            # digest below; mutable inputs are already represented there by
            # ``project_fingerprints``.
            "source_tree_digest": source_hash,
            "project_compatibility_digest": fingerprints["compatibility_digest"],
            "adapter": {
                "digest": adapter_fingerprint_digest,
                "value": adapter_fingerprint,
            },
            "compatibility_digest": sha256_json(
                {
                    "project": fingerprints["compatibility_digest"],
                    "adapter": adapter_fingerprint_digest,
                }
            ),
        }
        return DoctorReport(
            project_id=self.config.project_id,
            project_root=str(self.config.root),
            capabilities=tuple(sorted(capabilities)),
            side_effects=tuple(side_effects_value),
            adapter_fingerprint=adapter_fingerprint,
            fingerprints=effective_fingerprints,
            event_count=(
                len(self.event_log.read()) if event_count is None else event_count
            ),
        )

    def _adapter_cleanup(
        self, report: DoctorReport, workspace: Path, experiment_id: str
    ) -> None:
        response = self._call_sealed(
            report,
            Operation.CLEANUP,
            workspace=workspace,
            experiment_id=experiment_id,
        )
        _response_payload(response, Operation.CLEANUP)

    def baseline(
        self,
        *,
        evaluation_scope_id: str | None = None,
    ) -> dict[str, Any]:
        with self._workflow_lock():
            return self._baseline(evaluation_scope_id=evaluation_scope_id)

    def _baseline(
        self,
        *,
        evaluation_scope_id: str | None = None,
    ) -> dict[str, Any]:
        """Measure a stable baseline in isolated snapshots and seal it."""

        science_state = reduce_scientific_state(
            self.event_log.read(),
            project_id=self.config.project_id,
        )
        evaluation_scope = self._resolve_baseline_evaluation_scope(
            science_state,
            evaluation_scope_id,
        )
        report = self._doctor()
        if evaluation_scope is not None:
            self._validate_typed_generation_environment(
                cast(StudyContract, science_state.contract),
                report,
            )
            self._require_active_evaluation_seal(science_state, report)
        self._recover_incomplete_experiments()
        if evaluation_scope is not None:
            # Recovery can append terminal evidence, and generation change-control
            # intentionally does not share the workflow lock. Rebind the complete
            # typed baseline identity before any evaluator work begins.
            science_state = reduce_scientific_state(
                self.event_log.read(),
                project_id=self.config.project_id,
            )
            evaluation_scope = self._resolve_baseline_evaluation_scope(
                science_state,
                evaluation_scope_id,
            )
            if evaluation_scope is None:  # pragma: no cover - guarded by v2 path
                raise IntegrityError("typed baseline evaluation scope is unavailable")
            self._validate_typed_generation_environment(
                cast(StudyContract, science_state.contract),
                report,
            )
            self._require_active_evaluation_seal(science_state, report)
        count = self.config.baseline_repeats

        manager = WorkspaceManager(self.config)
        results: list[ResultEnvelope] = []
        captured_artifacts: list[dict[str, Any]] = []
        verifications: list[dict[str, Any]] = []
        try:
            for index in range(count):
                if evaluation_scope is None:
                    workspace_id = stable_id(
                        "baseline",
                        self.config.project_id,
                        report.fingerprints["compatibility_digest"],
                        index,
                    )
                else:
                    workspace_id = stable_id(
                        "baseline",
                        self.config.project_id,
                        report.fingerprints["compatibility_digest"],
                        science_state.active_generation_id,
                        evaluation_scope.id,
                        index,
                    )
                self._assert_static_compatibility(report)
                handle = manager.create(workspace_id)
                operation_error: BaseException | None = None
                try:
                    self._assert_static_compatibility(report)
                    baseline_input: dict[str, Any] = {
                        "repetition": index,
                        "repetitions": count,
                    }
                    if evaluation_scope is not None:
                        baseline_input["evaluation_scope"] = evaluation_scope.to_dict()
                    response = self._call_sealed(
                        report,
                        Operation.BASELINE,
                        payload=baseline_input,
                        workspace=handle.path,
                        experiment_id=workspace_id,
                    )
                    baseline_result = _result(response, Operation.BASELINE)
                    manager.verify(
                        handle,
                        allowed_outputs=baseline_result.artifacts,
                        allow_mutable=False,
                    )
                    captured_records = self.catalog.capture(
                        handle.path,
                        self.config.project_id,
                        workspace_id,
                        baseline_result.artifacts,
                    )

                    result_digest = sha256_json(baseline_result.to_dict())
                    verify_result: VerifyResult | None = None
                    try:
                        verify_input: dict[str, Any] = {
                            "result_digest": result_digest
                        }
                        if evaluation_scope is not None:
                            verify_input["evaluation_scope"] = (
                                evaluation_scope.to_dict()
                            )
                        verify_response = self._call_sealed(
                            report,
                            Operation.VERIFY,
                            payload=verify_input,
                            workspace=handle.path,
                            experiment_id=workspace_id,
                        )
                        verify_result = _verify_result(verify_response)
                    finally:
                        # VERIFY is project code.  Its mutation boundary must be
                        # checked even when transport fails or its verdict is
                        # malformed; otherwise cleanup could erase the stronger
                        # integrity failure and leave only a protocol error.
                        manager.verify(
                            handle,
                            allowed_outputs=baseline_result.artifacts,
                            allow_mutable=False,
                        )
                        recaptured = self.catalog.capture(
                            handle.path,
                            self.config.project_id,
                            workspace_id,
                            [
                                {
                                    "path": record.relative_path,
                                    "role": record.role,
                                    "media_type": record.media_type,
                                    "metadata": record.metadata,
                                    "sha256": record.digest,
                                    "size_bytes": record.size,
                                }
                                for record in captured_records
                            ],
                        )
                        if [record.to_dict() for record in recaptured] != [
                            record.to_dict() for record in captured_records
                        ]:
                            raise IntegrityError(
                                "verified baseline artifact records changed after evaluation"
                            )
                    if verify_result is None:  # pragma: no cover - guarded by try/finally
                        raise ProtocolError("baseline verification verdict is unavailable")
                    if not verify_result.valid:
                        raise ProtocolError(
                            "baseline verification rejected repetition "
                            f"{index}: {verify_result.reason_code}"
                        )

                    results.append(baseline_result)
                    verifications.append(
                        {
                            "repetition": index,
                            "result_digest": result_digest,
                            "verdict": verify_result.to_dict(),
                        }
                    )
                    for record in captured_records:
                        captured_artifacts.append(
                            {
                                **record.to_dict(),
                                "baseline_repetition": index,
                            }
                        )
                except BaseException as exc:
                    operation_error = exc
                    raise
                finally:
                    integrity_errors: list[BaseException] = []
                    adapter_is_sealed = False
                    try:
                        # Cleanup executes the configured project adapter, so both
                        # the workspace and the source checkout must still be sealed.
                        manager.verify_protected(handle)
                        manager.verify_source_unchanged(handle)
                        self._assert_static_compatibility(report)
                        adapter_is_sealed = True
                    except Exception as exc:
                        integrity_errors.append(exc)
                    cleanup_failure: BaseException | None = None
                    if adapter_is_sealed:
                        try:
                            self._adapter_cleanup(report, handle.path, workspace_id)
                        except IntegrityError as exc:
                            integrity_errors.append(exc)
                        except Exception as exc:
                            cleanup_failure = exc
                        try:
                            manager.verify_protected(handle)
                            manager.verify_source_unchanged(handle)
                            self._assert_static_compatibility(report)
                        except Exception as exc:
                            integrity_errors.append(exc)
                    try:
                        manager.cleanup(handle)
                    except IntegrityError as exc:
                        integrity_errors.append(exc)
                    except Exception as exc:
                        cleanup_failure = cleanup_failure or exc
                    if integrity_errors:
                        dominant = integrity_errors[0]
                        for secondary in integrity_errors[1:]:
                            dominant.add_note(
                                f"additional integrity error: {secondary}"
                            )
                        raise dominant from operation_error
                    if operation_error is None and cleanup_failure is not None:
                        raise cleanup_failure
                    if operation_error is not None and cleanup_failure is not None:
                        operation_error.add_note(f"cleanup error: {cleanup_failure}")
        except BaseException as exc:
            try:
                manager.close()
            except BaseException as close_exc:
                exc.add_note(f"workspace manager close error: {close_exc}")
            raise
        else:
            manager.close()

        primary_values: list[float] = []
        for index, result in enumerate(results):
            if self.config.primary_metric not in result.metrics:
                raise ProtocolError(
                    f"baseline repetition {index} omitted primary metric {self.config.primary_metric!r}"
                )
            value = float(result.metrics[self.config.primary_metric])
            if not math.isfinite(value):
                raise ProtocolError("baseline primary metric must be finite")
            primary_values.append(value)
        spread = max(primary_values) - min(primary_values)
        if spread > self.config.baseline_tolerance:
            raise IntegrityError(
                "baseline is not reproducible: "
                f"spread {spread} exceeds tolerance {self.config.baseline_tolerance}"
            )

        metric_names = set(results[0].metrics)
        if any(set(result.metrics) != metric_names for result in results[1:]):
            raise ProtocolError("baseline repetitions returned different metric sets")
        metrics = {
            name: fmean(float(result.metrics[name]) for result in results)
            for name in sorted(metric_names)
        }
        payload: dict[str, Any] = {
            "baseline_id": new_id("baseline"),
            "compatibility_digest": report.fingerprints["compatibility_digest"],
            "adapter_fingerprint": dict(report.adapter_fingerprint),
            "metrics": metrics,
            "primary_metric": self.config.primary_metric,
            "primary_value": metrics[self.config.primary_metric],
            "repetitions": count,
            "observations": [result.to_dict() for result in results],
            "verifications": verifications,
            "artifacts": captured_artifacts,
            "spread": spread,
            "tolerance": self.config.baseline_tolerance,
            "fingerprints": dict(report.fingerprints),
            "authorized_action": None,
        }
        if evaluation_scope is not None:
            contract = science_state.contract
            if contract is None:  # pragma: no cover - guarded by resolver
                raise IntegrityError("typed baseline study contract is unavailable")
            payload.update(
                {
                    "science_state_version": 1,
                    "generation_id": science_state.active_generation_id,
                    "study_contract_digest": contract.digest,
                    "evaluation_seal_digest": science_state.evaluation_seal_digest,
                    "evaluation_scope_id": evaluation_scope.id,
                    "evaluation_scope": evaluation_scope.to_dict(),
                }
            )
        payload["digest"] = sha256_json(payload)
        if evaluation_scope is None:
            event = self.event_log.append("BASELINE_RECORDED", payload)
        else:
            event = self._append_scoped_baseline_event(payload)
        self._sync()
        return {**payload, "event_sequence": event.sequence}

    def _validate_baseline_payload(
        self,
        payload: Mapping[str, Any],
        compatibility_digest: str,
        *,
        enforce_current_policy: bool = True,
        generation_id: str | None = None,
        study_contract_digest: str | None = None,
        evaluation_seal_digest: str | None = None,
        evaluation_scope: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Revalidate a sealed baseline before it can authorize comparison."""

        baseline = dict(payload)
        claimed_digest = baseline.get("digest")
        unsigned = dict(baseline)
        unsigned.pop("digest", None)
        if not isinstance(claimed_digest, str) or sha256_json(unsigned) != claimed_digest:
            raise IntegrityError("compatible baseline digest is invalid")
        baseline_id = baseline.get("baseline_id", baseline.get("id"))
        if not isinstance(baseline_id, str) or not baseline_id:
            raise IntegrityError("compatible baseline has an invalid baseline ID")
        # Projection accepts the legacy ``id`` spelling.  Downstream service
        # code consumes one normalized shape after the original signed payload
        # has been verified byte-for-byte above.
        baseline["baseline_id"] = baseline_id
        if baseline.get("compatibility_digest") != compatibility_digest:
            raise IntegrityError("compatible baseline fingerprint is inconsistent")

        has_scope_id = "evaluation_scope_id" in baseline
        has_scope_body = "evaluation_scope" in baseline
        if has_scope_id is not has_scope_body:
            raise IntegrityError("compatible baseline scope binding is incomplete")
        stored_scope_id: str | None = None
        if has_scope_id:
            stored_scope_id_value = baseline.get("evaluation_scope_id")
            stored_scope_value = baseline.get("evaluation_scope")
            if (
                not isinstance(stored_scope_id_value, str)
                or not stored_scope_id_value
                or not isinstance(stored_scope_value, Mapping)
                or set(stored_scope_value) != {"id", "role", "manifest_digest"}
                or stored_scope_value.get("id") != stored_scope_id_value
            ):
                raise IntegrityError("compatible baseline scope binding is invalid")
            stored_scope_id = stored_scope_id_value
            stored_generation = baseline.get("generation_id")
            if not isinstance(stored_generation, str) or not stored_generation:
                raise IntegrityError("compatible baseline generation binding is invalid")

        if evaluation_scope is not None:
            expected_scope = dict(evaluation_scope)
            expected_scope_id = expected_scope.get("id")
            expected_bindings = {
                "science_state_version": 1,
                "generation_id": generation_id,
                "study_contract_digest": study_contract_digest,
                "evaluation_seal_digest": evaluation_seal_digest,
                "evaluation_scope_id": expected_scope_id,
                "evaluation_scope": expected_scope,
            }
            if any(baseline.get(key) != value for key, value in expected_bindings.items()):
                raise IntegrityError("compatible baseline scope binding is inconsistent")
        fingerprints = baseline.get("fingerprints")
        adapter_fingerprint = baseline.get("adapter_fingerprint")
        if not isinstance(fingerprints, Mapping) or not isinstance(
            adapter_fingerprint, Mapping
        ):
            raise IntegrityError("compatible baseline provenance is invalid")
        adapter_seal = fingerprints.get("adapter")
        project_digest = fingerprints.get("project_compatibility_digest")
        if (
            not isinstance(adapter_seal, Mapping)
            or adapter_seal.get("value") != adapter_fingerprint
            or adapter_seal.get("digest") != sha256_json(adapter_fingerprint)
            or not isinstance(project_digest, str)
            or sha256_json(
                {
                    "project": project_digest,
                    "adapter": adapter_seal.get("digest"),
                }
            )
            != compatibility_digest
            or fingerprints.get("compatibility_digest") != compatibility_digest
        ):
            raise IntegrityError("compatible baseline provenance seal is inconsistent")
        primary_metric = baseline.get("primary_metric")
        if not isinstance(primary_metric, str) or not primary_metric:
            raise IntegrityError("compatible baseline primary metric is invalid")
        if enforce_current_policy and primary_metric != self.config.primary_metric:
            raise IntegrityError("compatible baseline primary metric is inconsistent")

        repetitions = baseline.get("repetitions")
        if (
            isinstance(repetitions, bool)
            or not isinstance(repetitions, int)
            or repetitions < 1
        ):
            raise IntegrityError("compatible baseline repetition count is invalid")
        if enforce_current_policy and repetitions != self.config.baseline_repeats:
            raise IntegrityError(
                "compatible baseline did not use the constitution repetition count"
            )
        tolerance = baseline.get("tolerance")
        if (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not math.isfinite(float(tolerance))
        ):
            raise IntegrityError("compatible baseline tolerance is inconsistent")
        if enforce_current_policy and float(tolerance) != self.config.baseline_tolerance:
            raise IntegrityError("compatible baseline tolerance is inconsistent")

        observations_value = baseline.get("observations")
        if not isinstance(observations_value, Sequence) or isinstance(
            observations_value, (str, bytes, bytearray)
        ):
            raise IntegrityError("compatible baseline observations must be an array")
        if len(observations_value) != repetitions:
            raise IntegrityError("compatible baseline repetition evidence is incomplete")
        observations: list[ResultEnvelope] = []
        try:
            for value in observations_value:
                result = ResultEnvelope.from_mapping(value)
                if result.status is not None:
                    raise ValueError("baseline observations cannot declare status")
                observations.append(result)
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrityError(f"compatible baseline observation is invalid: {exc}") from exc

        if "verifications" not in baseline:
            if enforce_current_policy:
                raise IntegrityError(
                    "compatible baseline verification evidence is missing"
                )
        else:
            verifications_value = baseline["verifications"]
            if not isinstance(verifications_value, Sequence) or isinstance(
                verifications_value, (str, bytes, bytearray)
            ):
                raise IntegrityError(
                    "compatible baseline verifications must be an array"
                )
            if len(verifications_value) != repetitions:
                raise IntegrityError(
                    "compatible baseline verification evidence is incomplete"
                )
            for index, value in enumerate(verifications_value):
                if not isinstance(value, Mapping):
                    raise IntegrityError(
                        "compatible baseline verification is not an object"
                    )
                expected_fields = {"repetition", "result_digest", "verdict"}
                if set(value) != expected_fields:
                    raise IntegrityError(
                        "compatible baseline verification fields are invalid"
                    )
                repetition = value.get("repetition")
                if (
                    isinstance(repetition, bool)
                    or not isinstance(repetition, int)
                    or repetition != index
                ):
                    raise IntegrityError(
                        "compatible baseline verification repetition is invalid"
                    )
                expected_digest = sha256_json(observations[index].to_dict())
                if value.get("result_digest") != expected_digest:
                    raise IntegrityError(
                        "compatible baseline verification result digest is inconsistent"
                    )
                verdict_value = value.get("verdict")
                try:
                    verdict = VerifyResult.from_dict(verdict_value)
                except (KeyError, TypeError, ValueError) as exc:
                    raise IntegrityError(
                        f"compatible baseline verification verdict is invalid: {exc}"
                    ) from exc
                if verdict_value != verdict.to_dict():
                    raise IntegrityError(
                        "compatible baseline verification verdict is not portable"
                    )
                if not verdict.valid:
                    raise IntegrityError(
                        "compatible baseline verification verdict is not positive"
                    )

        metric_names = set(observations[0].metrics)
        if any(set(result.metrics) != metric_names for result in observations[1:]):
            raise IntegrityError("compatible baseline metric sets are inconsistent")
        primary_values = [
            float(result.metrics[primary_metric])
            for result in observations
            if primary_metric in result.metrics
        ]
        if len(primary_values) != repetitions or not all(
            math.isfinite(value) for value in primary_values
        ):
            raise IntegrityError("compatible baseline primary observations are invalid")
        expected_metrics = {
            name: fmean(float(result.metrics[name]) for result in observations)
            for name in sorted(metric_names)
        }
        if baseline.get("metrics") != expected_metrics:
            raise IntegrityError("compatible baseline aggregate metrics are inconsistent")
        if baseline.get("primary_value") != expected_metrics[primary_metric]:
            raise IntegrityError("compatible baseline primary value is inconsistent")
        expected_spread = max(primary_values) - min(primary_values)
        if baseline.get("spread") != expected_spread:
            raise IntegrityError("compatible baseline spread is inconsistent")
        if expected_spread > float(tolerance):
            raise IntegrityError("compatible baseline violates the reproducibility gate")

        artifacts_value = baseline.get("artifacts", [])
        if not isinstance(artifacts_value, Sequence) or isinstance(
            artifacts_value, (str, bytes, bytearray)
        ):
            raise IntegrityError("compatible baseline artifacts must be an array")
        expected_artifacts = {
            (index, artifact.path): artifact
            for index, result in enumerate(observations)
            for artifact in result.artifacts
        }
        observed_artifacts: set[tuple[int, str]] = set()
        for value in artifacts_value:
            if not isinstance(value, Mapping):
                raise IntegrityError("compatible baseline artifact is not an object")
            repetition = value.get("baseline_repetition")
            if (
                isinstance(repetition, bool)
                or not isinstance(repetition, int)
                or repetition < 0
                or repetition >= repetitions
            ):
                raise IntegrityError("compatible baseline artifact repetition is invalid")
            record = ArtifactRecord.from_mapping(value)
            if record.project_id != self.config.project_id:
                raise IntegrityError("compatible baseline artifact belongs to another project")
            if stored_scope_id is None:
                expected_workspace = stable_id(
                    "baseline",
                    self.config.project_id,
                    compatibility_digest,
                    repetition,
                )
            else:
                expected_workspace = stable_id(
                    "baseline",
                    self.config.project_id,
                    compatibility_digest,
                    baseline["generation_id"],
                    stored_scope_id,
                    repetition,
                )
            if record.experiment_id != expected_workspace:
                raise IntegrityError("compatible baseline artifact workspace is inconsistent")
            key = (repetition, record.relative_path)
            if key in observed_artifacts:
                raise IntegrityError("compatible baseline contains a duplicate artifact")
            observed_artifacts.add(key)
            declared = expected_artifacts.get(key)
            if declared is None:
                raise IntegrityError("compatible baseline contains an undeclared artifact")
            if (
                record.role is not None
                or record.media_type != declared.media_type
                or dict(record.metadata)
                != {
                    "retention": declared.retention,
                    "sensitivity": declared.sensitivity,
                }
                or (
                    declared.sha256 is not None
                    and record.digest != declared.sha256
                )
                or (
                    declared.size_bytes is not None
                    and record.size != declared.size_bytes
                )
            ):
                raise IntegrityError("compatible baseline artifact metadata is inconsistent")
            stored = self.catalog.get(record.artifact_id)
            if stored.to_dict() != record.to_dict():
                raise IntegrityError("compatible baseline artifact manifest is inconsistent")
        if observed_artifacts != set(expected_artifacts):
            raise IntegrityError("compatible baseline artifact evidence is incomplete")
        return baseline

    def _compatible_baseline_from_events(
        self,
        events: Sequence[Event],
        compatibility_digest: str,
        *,
        generation_id: str | None = None,
        study_contract_digest: str | None = None,
        evaluation_seal_digest: str | None = None,
        evaluation_scope: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        for event in reversed(events):
            if _normalized_event_type(event.event_type) != "BASELINE_RECORDED":
                continue
            payload = event.payload
            if payload.get("compatibility_digest") != compatibility_digest:
                continue
            if payload.get("primary_metric") != self.config.primary_metric:
                continue
            if evaluation_scope is None:
                if "evaluation_scope_id" in payload or "evaluation_scope" in payload:
                    continue
            else:
                expected_scope = dict(evaluation_scope)
                expected_bindings = {
                    "science_state_version": 1,
                    "generation_id": generation_id,
                    "study_contract_digest": study_contract_digest,
                    "evaluation_seal_digest": evaluation_seal_digest,
                    "evaluation_scope_id": expected_scope.get("id"),
                    "evaluation_scope": expected_scope,
                }
                if any(
                    payload.get(key) != value
                    for key, value in expected_bindings.items()
                ):
                    continue
            # Verification-less baselines remain valid historical replay input,
            # but they cannot authorize a current-policy candidate comparison.
            if "verifications" not in payload:
                self._validate_baseline_payload(
                    payload,
                    compatibility_digest,
                    enforce_current_policy=False,
                    generation_id=generation_id,
                    study_contract_digest=study_contract_digest,
                    evaluation_seal_digest=evaluation_seal_digest,
                    evaluation_scope=evaluation_scope,
                )
                continue
            value = payload.get("primary_value")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise IntegrityError("compatible baseline has an invalid primary value")
            return self._validate_baseline_payload(
                payload,
                compatibility_digest,
                generation_id=generation_id,
                study_contract_digest=study_contract_digest,
                evaluation_seal_digest=evaluation_seal_digest,
                evaluation_scope=evaluation_scope,
            )
        return None

    def _compatible_baseline(
        self,
        compatibility_digest: str,
        *,
        generation_id: str | None = None,
        study_contract_digest: str | None = None,
        evaluation_seal_digest: str | None = None,
        evaluation_scope: Mapping[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self._compatible_baseline_from_events(
            self.event_log.read(),
            compatibility_digest,
            generation_id=generation_id,
            study_contract_digest=study_contract_digest,
            evaluation_seal_digest=evaluation_seal_digest,
            evaluation_scope=evaluation_scope,
        )

    def _select_attempt(
        self,
        candidate_digest: str,
        parent_id: str | None,
        compatibility_digest: str,
        retry_of: str | None,
        *,
        generation_id: str | None = None,
    ) -> tuple[str | None, int, str | None]:
        """Select and validate one explicit attempt without mutating history."""

        if retry_of is None:
            attempts = self.projection.candidate_attempts(
                self.config.project_id,
                candidate_digest,
                parent_id,
                compatibility_digest,
                generation_id=generation_id,
            )
            if attempts:
                raise ConfigurationError(
                    "this candidate already exists under the selected parent; "
                    "duplicate evidence is refused"
                )
            return parent_id, 1, None

        try:
            prior = self.projection.experiment(self.config.project_id, retry_of)
        except (IntegrityError, TypeError, ValueError) as exc:
            raise ConfigurationError(f"unknown retry attempt: {retry_of}") from exc
        prior_parent = prior.get("parent_id")
        if prior_parent is not None and not isinstance(prior_parent, str):
            raise IntegrityError("projected retry parent is invalid")
        if parent_id is not None and parent_id != prior_parent:
            raise ConfigurationError(
                "a retry must use the same parent as the prior attempt"
            )
        effective_parent = prior_parent
        if (
            prior.get("candidate_digest") != candidate_digest
            or prior.get("compatibility_digest") != compatibility_digest
            or prior.get("generation_id") != generation_id
        ):
            raise ConfigurationError(
                "retry_of does not match this candidate, compatibility, and generation"
            )
        attempts = self.projection.candidate_attempts(
            self.config.project_id,
            candidate_digest,
            effective_parent,
            compatibility_digest,
            generation_id=generation_id,
        )
        if not attempts or attempts[-1].get("experiment_id") != retry_of:
            raise ConfigurationError(
                "retry_of must reference the most recent candidate attempt"
            )
        if not prior.get("retryable", False):
            raise ConfigurationError(
                "retry_of did not end with retryable terminal evidence"
            )
        prior_attempt = prior.get("attempt")
        if (
            isinstance(prior_attempt, bool)
            or not isinstance(prior_attempt, int)
            or prior_attempt < 1
        ):
            raise IntegrityError("projected retry attempt number is invalid")
        return effective_parent, prior_attempt + 1, retry_of

    def _evaluation_result_for_recovery(
        self, experiment_id: str
    ) -> ResultEnvelope | None:
        """Read the durable evaluator response for an interrupted attempt."""

        evaluate_events: list[Event] = []
        for event in self.event_log.read():
            if _normalized_event_type(event.event_type) not in {
                "STAGE_COMPLETED",
                "ADAPTER_STAGE_RECORDED",
            }:
                continue
            if event.payload.get("experiment_id") != experiment_id:
                continue
            stage = event.payload.get(
                "stage",
                event.payload.get("stage_name", event.payload.get("name")),
            )
            if not isinstance(stage, str) or (
                stage.strip().lower().replace("-", "_")
                != Operation.EVALUATE.value
            ):
                continue
            evaluate_events.append(event)
        if not evaluate_events:
            return None
        if len(evaluate_events) != 1:
            raise IntegrityError(
                "interrupted experiment has duplicate evaluate stage evidence"
            )
        response_value = evaluate_events[0].payload.get("response")
        if not isinstance(response_value, Mapping):
            raise IntegrityError(
                "interrupted evaluate stage has no canonical response"
            )
        try:
            response = ProtocolResponse.from_mapping(
                cast(Mapping[str, Any], response_value)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrityError(
                f"interrupted evaluate response is invalid: {exc}"
            ) from exc
        if not response.ok:
            return None
        try:
            return _result(response, Operation.EVALUATE)
        except (AdapterOperationError, ProtocolError) as exc:
            raise IntegrityError(
                f"interrupted evaluate result is invalid: {exc}"
            ) from exc

    def _validate_recovered_artifact_records(
        self,
        experiment_id: str,
        result: ResultEnvelope,
        records: Sequence[ArtifactRecord],
        *,
        require_complete: bool,
    ) -> bool:
        """Match catalog records exactly to the evaluator's declared outputs."""

        expected = {reference.path: reference for reference in result.artifacts}
        actual: dict[str, ArtifactRecord] = {}
        for record in records:
            if record.project_id != self.config.project_id or (
                record.experiment_id != experiment_id
            ):
                raise IntegrityError(
                    "recovered artifact belongs to another project or experiment"
                )
            if record.relative_path in actual:
                raise IntegrityError(
                    "interrupted experiment has duplicate artifact manifests"
                )
            actual[record.relative_path] = record
        extra = sorted(set(actual) - set(expected))
        if extra:
            raise IntegrityError(
                "interrupted experiment has undeclared artifact manifests: "
                + ", ".join(extra)
            )
        for path, record in actual.items():
            reference = expected[path]
            expected_metadata = {
                "retention": reference.retention,
                "sensitivity": reference.sensitivity,
            }
            if (
                record.role is not None
                or record.media_type != reference.media_type
                or dict(record.metadata) != expected_metadata
            ):
                raise IntegrityError(
                    f"recovered artifact metadata disagrees with evaluation: {path}"
                )
            if reference.sha256 is not None and (
                record.digest != reference.sha256
                or record.size != reference.size_bytes
            ):
                raise IntegrityError(
                    f"recovered artifact content disagrees with evaluation: {path}"
                )
        complete = set(actual) == set(expected)
        if require_complete and not complete:
            missing = sorted(set(expected) - set(actual))
            raise IntegrityError(
                "interrupted experiment is missing artifact manifests: "
                + ", ".join(missing)
            )
        return complete

    def _recover_interrupted_artifacts(
        self, row: Mapping[str, Any], manager: WorkspaceManager
    ) -> None:
        """Seal evaluated outputs before an interrupted workspace can be removed."""

        experiment_id_value = row.get("experiment_id")
        if not isinstance(experiment_id_value, str) or not experiment_id_value:
            raise IntegrityError("interrupted experiment identity is invalid")
        experiment_id = experiment_id_value
        result = self._evaluation_result_for_recovery(experiment_id)
        existing = self.catalog.records_for_experiment(
            self.config.project_id, experiment_id
        )
        if result is None:
            if existing:
                raise IntegrityError(
                    "interrupted experiment has artifacts without successful evaluation"
                )
            return
        complete = self._validate_recovered_artifact_records(
            experiment_id,
            result,
            existing,
            require_complete=False,
        )
        if complete:
            self._publish_artifact_records(experiment_id, existing)
            return
        if not result.artifacts:  # pragma: no cover - complete when both sets are empty
            return

        registration = row.get("payload")
        if not isinstance(registration, Mapping):
            raise IntegrityError("interrupted experiment registration is invalid")
        source_tree_digest = registration.get("source_tree_digest")
        if not isinstance(source_tree_digest, str) or not source_tree_digest:
            raise IntegrityError(
                "cannot recover evaluated artifacts without a source tree seal"
            )

        handle = manager.adopt_orphan(experiment_id, source_tree_digest)
        try:
            manager.verify(handle, allowed_outputs=result.artifacts)
            self.catalog.capture(
                handle.path,
                self.config.project_id,
                experiment_id,
                result.artifacts,
            )
            recovered = self.catalog.records_for_experiment(
                self.config.project_id, experiment_id
            )
            self._validate_recovered_artifact_records(
                experiment_id,
                result,
                recovered,
                require_complete=True,
            )
            self._publish_artifact_records(experiment_id, recovered)
            manager.cleanup(handle)
        except BaseException as primary:
            # Evidence that could not be proven remains available for a human or
            # a later compatible recovery; generic orphan cleanup must not erase it.
            try:
                manager.detach(handle)
            except BaseException as detach_error:
                primary.add_note(
                    "failed to detach preserved recovery workspace: "
                    f"{type(detach_error).__name__}: {detach_error}"
                )
                try:
                    manager.preserve(handle)
                except BaseException as preserve_error:
                    primary.add_note(
                        "failed to relinquish recovery workspace ownership: "
                        f"{type(preserve_error).__name__}: {preserve_error}"
                    )
            raise

    def _recover_incomplete_experiments(self) -> list[str]:
        """Close attempts abandoned by a previously interrupted local worker."""

        # Projection rows are disposable cache state. Rebuild from the verified
        # event stream before using them for recovery or any caller-visible
        # query so out-of-band SQLite drift never becomes research truth.
        self.projection.rebuild(self.event_log)
        workspace_manager = WorkspaceManager(self.config)
        recovered: list[str] = []
        preserved_experiment_ids = {
            experiment_id
            for event in self.event_log.read()
            if _normalized_event_type(event.event_type) in _TERMINAL_EVENT_TYPES
            and event.payload.get("reason_code") == _PRESERVED_RECOVERY_REASON
            and event.payload.get("preserve_workspace") is True
            and isinstance(
                experiment_id := event.payload.get(
                    "experiment_id", event.payload.get("id")
                ),
                str,
            )
        }
        try:
            for row in self.projection.lineage(self.config.project_id):
                if str(row.get("status", "")).lower() not in {
                    "registered",
                    "queued",
                    "running",
                }:
                    continue
                experiment_id = str(row["experiment_id"])
                primary_metric = self._historical_primary_metric(row)
                try:
                    self._recover_interrupted_artifacts(row, workspace_manager)
                    # No terminal is committed until the matching residue has
                    # either been safely removed or explicitly retained below.
                    workspace_manager.cleanup_orphan(experiment_id)
                except (IntegrityError, ConfigurationError, LifecycleError) as exc:
                    recovery_error = (
                        exc
                        if isinstance(exc, IntegrityError)
                        else IntegrityError(f"interrupted evidence is unsafe: {exc}")
                    )
                    self._terminate(
                        experiment_id,
                        TerminalStatus.UNTRUSTED,
                        _PRESERVED_RECOVERY_REASON,
                        attempt=int(row.get("attempt", 1)),
                        retry_of=row.get("retry_of")
                        if isinstance(row.get("retry_of"), str)
                        else None,
                        error=recovery_error,
                        preserve_workspace=True,
                        primary_metric=primary_metric,
                    )
                    preserved_experiment_ids.add(experiment_id)
                    recovered.append(experiment_id)
                    continue
                self._terminate(
                    experiment_id,
                    TerminalStatus.INFRA_FAILED,
                    "RECOVERED_INTERRUPTED_RUN",
                    attempt=int(row.get("attempt", 1)),
                    retry_of=row.get("retry_of")
                    if isinstance(row.get("retry_of"), str)
                    else None,
                    error=ProtocolError(
                        "a previous worker stopped before recording a terminal result"
                    ),
                    primary_metric=primary_metric,
                )
                recovered.append(experiment_id)
            self._reconcile_outcome_findings()
            workspace_manager.cleanup_orphans(preserved_experiment_ids)
        finally:
            workspace_manager.close()
        return recovered

    def _historical_primary_metric(self, row: Mapping[str, Any]) -> str | None:
        """Resolve recovery metadata from registration-time evidence only."""

        registration = row.get("payload")
        if not isinstance(registration, Mapping):
            raise IntegrityError("interrupted experiment registration is invalid")
        if "primary_metric" in registration:
            value = registration["primary_metric"]
            if not isinstance(value, str) or not value:
                return None
            return value

        baseline_id = registration.get("baseline_id", registration.get("id"))
        if not isinstance(baseline_id, str) or not baseline_id:
            return None
        created_sequence = row.get("created_sequence")
        for event in reversed(self.event_log.read()):
            if isinstance(created_sequence, int) and event.sequence >= created_sequence:
                continue
            if _normalized_event_type(event.event_type) != "BASELINE_RECORDED":
                continue
            if event.payload.get("baseline_id", event.payload.get("id")) != baseline_id:
                continue
            value = event.payload.get("primary_metric")
            if not isinstance(value, str) or not value:
                return None
            return value
        return None

    def _outcome_finding_payload(self, event: Event) -> dict[str, Any]:
        """Derive the idempotent project finding for one terminal event."""

        experiment_id = event.payload.get("experiment_id", event.payload.get("id"))
        raw_status = event.payload.get(
            "status", event.payload.get("state", event.payload.get("outcome"))
        )
        reason_code = event.payload.get("reason_code")
        if not isinstance(experiment_id, str) or not experiment_id:
            raise IntegrityError("terminal event has an invalid experiment_id")
        if not isinstance(raw_status, str) or not raw_status:
            raise IntegrityError("terminal event has an invalid status")
        try:
            status = coerce_state(raw_status).value
        except LifecycleError as exc:
            raise IntegrityError("terminal event has an invalid status") from exc
        if not isinstance(reason_code, str) or not reason_code:
            if _normalized_event_type(event.event_type) == "EXPERIMENT_STATUS_CHANGED":
                reason_code = "STATUS_CHANGED"
            else:
                reason_code = "TERMINATED"

        registration: Mapping[str, Any] | None = None
        for prior in reversed(self.event_log.read()):
            if prior.sequence >= event.sequence:
                continue
            if _normalized_event_type(prior.event_type) != "EXPERIMENT_REGISTERED":
                continue
            prior_experiment_id = prior.payload.get(
                "experiment_id", prior.payload.get("id")
            )
            if prior_experiment_id == experiment_id:
                registration = prior.payload
                break
        if registration is None:
            raise IntegrityError("terminal event has no canonical registration")

        attempt = event.payload.get("attempt", registration.get("attempt", 1))
        if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
            raise IntegrityError("terminal event has an invalid attempt")
        retry_of = (
            event.payload.get("retry_of")
            if "retry_of" in event.payload
            else registration.get("retry_of")
        )
        if retry_of is not None and not isinstance(retry_of, str):
            raise IntegrityError("terminal event has an invalid retry_of")

        error = event.payload.get("error")
        error_mapping = (
            cast(Mapping[str, Any], error) if isinstance(error, Mapping) else None
        )
        try:
            public_status = TerminalStatus.parse(status)
        except ValueError:
            retryable = False
        else:
            retryable = _terminal_retryable(
                public_status,
                reason_code,
                error_mapping,
            )
        declared_retryable = event.payload.get("retryable")
        if declared_retryable is not None and (
            not isinstance(declared_retryable, bool)
            or declared_retryable is not retryable
        ):
            raise IntegrityError("terminal retryable metadata is inconsistent")

        decision = event.payload.get("decision")
        primary_metric = event.payload.get("primary_metric")
        if not isinstance(primary_metric, str) or not primary_metric:
            primary_metric = (
                decision.get("primary_metric")
                if isinstance(decision, Mapping)
                else None
            )
        if not isinstance(primary_metric, str) or not primary_metric:
            primary_metric = self._historical_primary_metric(
                {
                    "payload": registration,
                    "created_sequence": event.sequence,
                }
            )
        return make_finding_event(
            self.config.project_id,
            {
                "status": status,
                "reason_code": reason_code,
                "primary_metric": primary_metric,
                "decision": decision,
                "attempt": attempt,
                "retry_of": retry_of,
                "retryable": retryable,
            },
            experiment_id=experiment_id,
            key="experiment_outcome",
            evidence=[{"event_id": event.event_id, "event_hash": event.hash}],
            metadata={"authorized_action": None},
            finding_id=stable_id("finding", event.event_id, "experiment_outcome"),
        )

    def _validate_outcome_finding(
        self, finding: Event, terminal: Event, expected: Mapping[str, Any]
    ) -> None:
        payload = finding.payload
        if finding.sequence <= terminal.sequence:
            raise IntegrityError("experiment outcome finding precedes its terminal event")
        if payload.get("experiment_id") != expected.get("experiment_id"):
            raise IntegrityError("experiment outcome finding targets the wrong experiment")
        if payload.get("scope", "project") != "project" or payload.get(
            "project_id", self.config.project_id
        ) != self.config.project_id:
            raise IntegrityError("experiment outcome finding has an invalid scope")
        evidence = payload.get("evidence")
        if (
            not isinstance(evidence, Sequence)
            or isinstance(evidence, (str, bytes, bytearray))
            or len(evidence) != 1
            or not isinstance(evidence[0], Mapping)
            or evidence[0].get("event_id") != terminal.event_id
            or evidence[0].get("event_hash") != terminal.hash
        ):
            raise IntegrityError("experiment outcome finding has invalid terminal evidence")
        content = payload.get("content")
        expected_content = expected.get("content")
        if not isinstance(content, Mapping) or not isinstance(
            expected_content, Mapping
        ):
            raise IntegrityError("experiment outcome finding content is invalid")
        content_map = cast(Mapping[str, Any], content)
        expected_content_map = cast(Mapping[str, Any], expected_content)
        unexpected_content = sorted(set(content_map) - set(expected_content_map))
        if unexpected_content:
            raise IntegrityError(
                "experiment outcome finding has unexpected content: "
                + ", ".join(unexpected_content)
            )
        for key in ("status", "reason_code", "primary_metric"):
            if content_map.get(key) != expected_content_map.get(key):
                raise IntegrityError(
                    f"experiment outcome finding has inconsistent {key}"
                )
        for key in ("decision", "attempt", "retry_of", "retryable"):
            if key in content_map and content_map[key] != expected_content_map.get(key):
                raise IntegrityError(
                    f"experiment outcome finding has inconsistent {key}"
                )
        metadata = payload.get("metadata", {})
        if not isinstance(metadata, Mapping) or metadata.get(
            "authorized_action"
        ) is not None:
            raise IntegrityError("experiment outcome finding metadata is invalid")

    def _reconcile_outcome_findings(self) -> int:
        """Repair a terminal/finding split caused by an interrupted append."""

        events = self.event_log.read()
        terminals: dict[str, Event] = {}
        expected_by_id: dict[str, tuple[Event, dict[str, Any]]] = {}
        for event in events:
            event_type = _normalized_event_type(event.event_type)
            if event_type not in _TERMINAL_EVENT_TYPES:
                continue
            if event_type == "EXPERIMENT_STATUS_CHANGED":
                status = event.payload.get("status", event.payload.get("state"))
                if not isinstance(status, str):
                    raise IntegrityError("terminal status event is invalid")
                try:
                    if not is_terminal(status):
                        continue
                except (LifecycleError, TypeError, ValueError) as exc:
                    raise IntegrityError("terminal status event is invalid") from exc
            expected = self._outcome_finding_payload(event)
            finding_id = expected.get("finding_id")
            if not isinstance(finding_id, str):  # pragma: no cover - builder invariant
                raise IntegrityError("expected outcome finding ID is invalid")
            terminals[event.event_id] = event
            expected_by_id[finding_id] = (event, expected)

        covered_terminal_ids: set[str] = set()
        seen_finding_ids: set[str] = set()
        for event in events:
            if _normalized_event_type(event.event_type) != "FINDING_RECORDED":
                continue
            finding_id = event.payload.get(
                "finding_id", event.payload.get("id")
            )
            if not isinstance(finding_id, str) or not finding_id:
                finding_id = stable_id(
                    "finding", self.config.project_id, event.event_id
                )
            if finding_id in seen_finding_ids:
                raise IntegrityError(f"duplicate finding ID in canonical history: {finding_id}")
            seen_finding_ids.add(finding_id)

            reserved_identity = expected_by_id.get(finding_id)
            finding_key = event.payload.get(
                "key", event.payload.get("finding_key")
            )
            if finding_key != "experiment_outcome":
                if reserved_identity is not None:
                    raise IntegrityError(
                        "kernel outcome finding ID is occupied by another finding"
                    )
                continue
            evidence = event.payload.get("evidence")
            if (
                not isinstance(evidence, Sequence)
                or isinstance(evidence, (str, bytes, bytearray))
                or len(evidence) != 1
                or not isinstance(evidence[0], Mapping)
            ):
                raise IntegrityError("kernel outcome finding has invalid evidence")
            terminal_event_id = evidence[0].get("event_id")
            terminal = (
                terminals.get(terminal_event_id)
                if isinstance(terminal_event_id, str)
                else None
            )
            if terminal is None:
                raise IntegrityError("kernel outcome finding references no terminal event")
            if terminal.event_id in covered_terminal_ids:
                raise IntegrityError(
                    "terminal event has more than one experiment outcome finding"
                )
            expected = self._outcome_finding_payload(terminal)
            if reserved_identity is not None and reserved_identity[0] != terminal:
                raise IntegrityError("kernel outcome finding ID targets the wrong terminal")
            self._validate_outcome_finding(event, terminal, expected)
            covered_terminal_ids.add(terminal.event_id)

        repaired = 0
        for event in terminals.values():
            if event.event_id in covered_terminal_ids:
                continue
            payload = self._outcome_finding_payload(event)
            finding_id = payload.get("finding_id")
            if not isinstance(finding_id, str):  # pragma: no cover
                raise IntegrityError("expected outcome finding ID is invalid")
            if finding_id in seen_finding_ids:
                raise IntegrityError("kernel outcome finding ID collision")
            self.event_log.append("FINDING_RECORDED", payload)
            seen_finding_ids.add(finding_id)
            covered_terminal_ids.add(event.event_id)
            repaired += 1
        if repaired:
            self._sync()
        return repaired

    def _load_json_object(
        self,
        path: str | Path,
        *,
        label: str,
    ) -> dict[str, Any]:
        candidate_path = Path(path).expanduser()
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(candidate_path, flags)
        except OSError as exc:
            raise ConfigurationError(
                f"{label} file is unavailable: {candidate_path}"
            ) from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ConfigurationError(
                    f"{label} must be a regular, non-symlink JSON file"
                )
            if info.st_size > self.config.max_output_bytes:
                raise ConfigurationError(
                    f"{label} exceeds {self.config.max_output_bytes} byte input limit"
                )
            chunks: list[bytes] = []
            remaining = self.config.max_output_bytes + 1
            while remaining:
                chunk = os.read(descriptor, min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            encoded = b"".join(chunks)
            if len(encoded) > self.config.max_output_bytes:
                raise ConfigurationError(
                    f"{label} exceeds {self.config.max_output_bytes} byte input limit"
                )
            value = decode_json_object(encoded)
            after = os.fstat(descriptor)
            if (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ) != (
                info.st_dev,
                info.st_ino,
                info.st_size,
                info.st_mtime_ns,
                info.st_ctime_ns,
            ):
                raise IntegrityError(f"{label} changed while being read")
        except (OSError, TypeError, ValueError) as exc:
            if isinstance(exc, ConfigurationError):
                raise
            raise ConfigurationError(
                f"{label} must be one strict JSON object: {exc}"
            ) from exc
        finally:
            os.close(descriptor)
        return value

    def _load_candidate(self, path: str | Path) -> tuple[dict[str, Any], str]:
        value = self._load_json_object(path, label="candidate")
        return value, sha256_json(value)

    def _load_proposal(
        self,
        value: str | Path | Mapping[str, Any],
    ) -> Proposal:
        raw = (
            value
            if isinstance(value, Mapping)
            else self._load_json_object(value, label="proposal")
        )
        return Proposal.from_mapping(raw)

    def _record_stage(
        self,
        experiment_id: str,
        operation: Operation,
        *,
        input_value: Mapping[str, Any],
        response: ProtocolResponse,
    ) -> Event:
        payload: dict[str, Any] = {
            "experiment_id": experiment_id,
            "stage": operation.value,
            "status": "completed" if response.ok else "failed",
            "input_digest": sha256_json(input_value),
            "output_digest": sha256_json(response.to_dict()),
            "response": response.to_dict(),
        }
        return self.event_log.append("STAGE_COMPLETED", payload)

    def _terminal_event_for(self, experiment_id: str) -> Event | None:
        """Return the single durable terminal event for an experiment, if any."""

        matches: list[Event] = []
        for event in self.event_log.read():
            event_type = _normalized_event_type(event.event_type)
            if event_type not in _TERMINAL_EVENT_TYPES:
                continue
            if event.payload.get("experiment_id", event.payload.get("id")) != (
                experiment_id
            ):
                continue
            if event_type == "EXPERIMENT_STATUS_CHANGED":
                status = event.payload.get("status", event.payload.get("state"))
                try:
                    if not isinstance(status, str) or not is_terminal(status):
                        continue
                except (LifecycleError, TypeError, ValueError) as exc:
                    raise IntegrityError("terminal status event is invalid") from exc
            matches.append(event)
        if len(matches) > 1:
            raise IntegrityError("experiment has duplicate terminal events")
        return matches[0] if matches else None

    def _terminate(
        self,
        experiment_id: str,
        status: TerminalStatus,
        reason_code: str,
        *,
        attempt: int,
        retry_of: str | None,
        decision: Decision | None = None,
        result: ResultEnvelope | None = None,
        error: BaseException | None = None,
        secondary_errors: Sequence[BaseException] = (),
        verified: bool = False,
        preserve_workspace: bool = False,
        primary_metric: str | None | object = _USE_CURRENT_PRIMARY_METRIC,
    ) -> dict[str, Any]:
        error_payload = _safe_error(error) if error is not None else None
        selected_primary_metric: str | None
        if primary_metric is _USE_CURRENT_PRIMARY_METRIC:
            selected_primary_metric = self.config.primary_metric
        elif primary_metric is None or isinstance(primary_metric, str):
            selected_primary_metric = primary_metric
        else:  # pragma: no cover - internal call contract
            raise TypeError("primary_metric must be a string or null")
        payload: dict[str, Any] = {
            "experiment_id": experiment_id,
            "status": status.value,
            "reason_code": reason_code,
            "attempt": attempt,
            "retry_of": retry_of,
            "retryable": _terminal_retryable(
                status, reason_code, error_payload
            ),
            "verified": verified,
            "primary_metric": selected_primary_metric,
            "authorized_action": None,
        }
        if preserve_workspace:
            payload["preserve_workspace"] = True
        if decision is not None:
            payload["decision"] = decision.to_dict()
        if result is not None:
            payload["result"] = result.to_dict()
        if error_payload is not None:
            payload["error"] = error_payload
        if secondary_errors:
            payload["secondary_errors"] = [
                _safe_error(secondary) for secondary in secondary_errors
            ]
        event = self.event_log.append("EXPERIMENT_TERMINATED", payload)
        self._reconcile_outcome_findings()
        self._sync()
        return {
            **payload,
            "project_id": self.config.project_id,
            "event_sequence": event.sequence,
        }

    def _validate_proposal_mode(
        self,
        science_state: Any,
        *,
        proposal: str | Path | Mapping[str, Any] | None,
        parent_id: str | None,
        retry_of: str | None,
        graph_action: str | None,
        scientific_change: str | None,
    ) -> bool:
        """Select the v1 or v2 registration contract without mutating state."""

        contract = science_state.contract
        typed_path = contract is not None and contract.schema_version == 2
        if not typed_path:
            if proposal is not None:
                raise ScientificStateError(
                    "PROPOSAL_CONTRACT_VERSION_REQUIRED",
                    "typed Proposal input requires an active StudyContract v2 generation",
                )
            return False

        if retry_of is not None and proposal is not None:
            raise ScientificStateError(
                "PROPOSAL_RETRY_FORBIDDEN",
                "a retry must inherit its persisted Proposal and evaluation scope",
                details={"retry_of": retry_of},
            )
        if retry_of is None and proposal is None:
            raise ScientificStateError(
                "PROPOSAL_REQUIRED",
                "StudyContract v2 registrations require a typed Proposal",
            )
        legacy_options = [
            option
            for option, value in (
                ("parent_id", parent_id if proposal is not None else None),
                ("graph_action", graph_action),
                ("scientific_change", scientific_change),
            )
            if value is not None
        ]
        if legacy_options:
            raise ConfigurationError(
                "typed Proposal registration cannot use legacy graph options: "
                + ", ".join(legacy_options)
            )
        return True

    def run_once(
        self,
        candidate_path: str | Path,
        *,
        parent_id: str | None = None,
        retry_of: str | None = None,
        context_token: str | None = None,
        graph_action: str | None = None,
        scientific_change: str | None = None,
        proposal: str | Path | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._workflow_lock():
            return self._run_once(
                candidate_path,
                parent_id=parent_id,
                retry_of=retry_of,
                context_token=context_token,
                graph_action=graph_action,
                scientific_change=scientific_change,
                proposal=proposal,
            )

    def _run_once(
        self,
        candidate_path: str | Path,
        *,
        parent_id: str | None = None,
        retry_of: str | None = None,
        context_token: str | None = None,
        graph_action: str | None = None,
        scientific_change: str | None = None,
        proposal: str | Path | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Run one candidate as a durable node in the experiment DAG."""

        preview_state = reduce_scientific_state(
            self.event_log.read(),
            project_id=self.config.project_id,
        )
        # State-derived stop and pending obligations outrank request parsing
        # and must reject without touching the evaluator or projection.  A
        # second intent-aware pass below adds class and replication-parent
        # gates once the Proposal lineage is known.
        validate_registration_preflight(preview_state, {})
        typed_path = (
            preview_state.contract is not None
            and preview_state.contract.schema_version == 2
        )
        preview_proposal_raw: Mapping[str, Any] | None = None
        preview_typed_proposal: Proposal | None = None
        if typed_path:
            preflight_payload: dict[str, Any] = {"retry_of": retry_of}
            if retry_of is None:
                if proposal is not None:
                    preview_proposal_raw = (
                        dict(proposal)
                        if isinstance(proposal, Mapping)
                        else self._load_json_object(proposal, label="proposal")
                    )
                    preflight_payload.update(
                        {
                            "proposal": preview_proposal_raw,
                            "parent_id": preview_proposal_raw.get(
                                "parent_experiment_id"
                            ),
                        }
                    )
            else:
                prior_registration = preview_state.registration(retry_of)
                if prior_registration is not None:
                    preflight_payload.update(
                        {
                            "proposal": prior_registration.proposal.to_dict(),
                            "parent_id": prior_registration.parent_id,
                        }
                    )
            validate_registration_preflight(preview_state, preflight_payload)
        typed_path = self._validate_proposal_mode(
            preview_state,
            proposal=proposal,
            parent_id=parent_id,
            retry_of=retry_of,
            graph_action=graph_action,
            scientific_change=scientific_change,
        )
        if typed_path:
            if preview_proposal_raw is not None:
                preview_typed_proposal = Proposal.from_mapping(preview_proposal_raw)

        agent_context_snapshot: dict[str, Any] | None = None
        if context_token is not None:
            if not isinstance(context_token, str) or not context_token:
                raise ValueError("context_token must be a non-empty string")
            agent_context_snapshot, _ = self._validate_agent_context_token(
                context_token,
                require_ready=True,
            )

        graph_metadata: GraphMetadata | None = None
        if not typed_path and retry_of is None:
            graph_metadata = graph_metadata_from_values(
                graph_action,
                scientific_change,
                required=context_token is not None,
            )
            if graph_metadata is not None:
                validate_graph_relationship(graph_metadata, parent_id)
        elif not typed_path and (
            graph_action is not None or scientific_change is not None
        ):
            # A retry is an execution continuation, never a newly labelled
            # scientific node. Its metadata is inherited below from history.
            inherit_retry_graph_metadata(
                {},
                graph_action=graph_action,
                scientific_change=scientific_change,
            )
        report = self._doctor()
        self._recover_incomplete_experiments()
        science_state = reduce_scientific_state(
            self.event_log.read(),
            project_id=self.config.project_id,
        )
        validate_registration_preflight(science_state, {})
        typed_path = (
            science_state.contract is not None
            and science_state.contract.schema_version == 2
        )
        if typed_path:
            post_recovery_payload: dict[str, Any] = {"retry_of": retry_of}
            if retry_of is None:
                if preview_proposal_raw is not None:
                    post_recovery_payload.update(
                        {
                            "proposal": preview_proposal_raw,
                            "parent_id": preview_proposal_raw.get(
                                "parent_experiment_id"
                            ),
                        }
                    )
            else:
                prior_registration = science_state.registration(retry_of)
                if prior_registration is not None:
                    post_recovery_payload.update(
                        {
                            "proposal": prior_registration.proposal.to_dict(),
                            "parent_id": prior_registration.parent_id,
                        }
                    )
            validate_registration_preflight(science_state, post_recovery_payload)
        typed_path = self._validate_proposal_mode(
            science_state,
            proposal=proposal,
            parent_id=parent_id,
            retry_of=retry_of,
            graph_action=graph_action,
            scientific_change=scientific_change,
        )
        generation_id = science_state.active_generation_id
        if generation_id is not None:
            live_seal = self._evaluation_seal_from_report(report)
            if live_seal.digest != science_state.evaluation_seal_digest:
                raise ScientificStateError(
                    "STUDY_EVALUATION_SEAL_MISMATCH",
                    "the active generation is not bound to the current evaluator seal",
                    details={
                        "active_evaluation_seal_digest": (
                            science_state.evaluation_seal_digest
                        ),
                        "current_evaluation_seal_digest": live_seal.digest,
                    },
                )
        if context_token is not None:
            agent_context_snapshot, _ = self._validate_agent_context_after_doctor(
                context_token,
                report,
            )
        compatibility = str(report.fingerprints["compatibility_digest"])
        candidate, candidate_digest = self._load_candidate(candidate_path)
        typed_proposal: Proposal | None = None
        evaluation_scope: Any | None = None
        registration: dict[str, Any] | None = None
        if typed_path:
            contract = science_state.contract
            if contract is None or generation_id is None:  # pragma: no cover
                raise IntegrityError("typed registration generation is unavailable")
            self._validate_typed_generation_environment(contract, report)
            if retry_of is None:
                if preview_typed_proposal is None:  # pragma: no cover - mode gate above
                    raise IntegrityError("typed Proposal input is unavailable")
                typed_proposal = preview_typed_proposal
                parent_id = typed_proposal.parent_experiment_id
                attempt = 1
            else:
                prior_registration = science_state.registration(retry_of)
                if prior_registration is None:
                    raise ScientificStateError(
                        "PROPOSAL_RETRY_MISMATCH",
                        "retry_of does not identify a typed registration in the active generation",
                        details={"retry_of": retry_of},
                    )
                if parent_id is not None and parent_id != prior_registration.parent_id:
                    raise ScientificStateError(
                        "PROPOSAL_RETRY_MISMATCH",
                        "a retry must inherit the persisted Proposal parent",
                        details={"retry_of": retry_of},
                    )
                typed_proposal = prior_registration.proposal
                parent_id = prior_registration.parent_id
                attempt = prior_registration.attempt + 1

            evaluation_scope_id = typed_proposal.evaluation_scope_id
            experiment_id = new_experiment_id(
                self.config.project_id,
                candidate_digest,
                compatibility_digest=compatibility,
                parent_id=parent_id,
                generation_id=generation_id,
                evaluation_scope_id=evaluation_scope_id,
                attempt=attempt,
            )
            scope_baseline = science_state.baseline_for_scope(evaluation_scope_id)
            prospective_baseline_id = (
                scope_baseline.baseline_id
                if scope_baseline is not None
                else stable_id(
                    "baseline",
                    self.config.project_id,
                    generation_id,
                    evaluation_scope_id,
                    "missing",
                )
            )
            registration = {
                "experiment_id": experiment_id,
                "parent_id": parent_id,
                "candidate_digest": candidate_digest,
                "candidate": candidate,
                "compatibility_digest": compatibility,
                "source_tree_digest": report.fingerprints["source_tree_digest"],
                "baseline_id": prospective_baseline_id,
                "primary_metric": self.config.primary_metric,
                "attempt": attempt,
                "retry_of": retry_of,
                "status": "registered",
                "authorized_action": None,
                **registration_payload_fields(
                    science_state,
                    retry_of=retry_of,
                ),
                "proposal": typed_proposal.to_dict(),
                "proposal_digest": typed_proposal.digest,
                "proposal_id": proposal_id(
                    self.config.project_id,
                    typed_proposal.digest,
                ),
                "evaluation_scope_id": evaluation_scope_id,
            }
            # Derive even an early zero-delta rejection from a verified locked
            # snapshot. The same pure authority runs again under EventLog's
            # exclusive append lock at the canonical registration boundary.
            with self.event_log.locked_read() as locked_events:
                locked_state = reduce_scientific_state(
                    tuple(locked_events),
                    project_id=self.config.project_id,
                )
                reserve_registration(locked_state, registration)
            science_state = locked_state
            evaluation_scope = next(
                (
                    scope
                    for scope in contract.evaluation_scopes
                    if scope.id == evaluation_scope_id
                ),
                None,
            )
            if evaluation_scope is None:  # pragma: no cover - validator authority
                raise IntegrityError("typed Proposal scope is unavailable")
            baseline = self._compatible_baseline(
                compatibility,
                generation_id=generation_id,
                study_contract_digest=contract.digest,
                evaluation_seal_digest=science_state.evaluation_seal_digest,
                evaluation_scope=evaluation_scope.to_dict(),
            )
            if (
                baseline is None
                or baseline.get("baseline_id") != prospective_baseline_id
            ):
                raise ScientificStateError(
                    "STUDY_SCOPE_BASELINE_REQUIRED",
                    "typed registration requires a trusted baseline for its exact evaluation scope",
                    details={"evaluation_scope_id": evaluation_scope_id},
                )
        else:
            # SQLite is a disposable query accelerator, never decision authority.
            # Rebuild it from the verified canonical stream before consulting
            # attempt/retry lineage so local projection drift cannot authorize a
            # retry or parent that history does not contain.
            self.projection.rebuild(self.event_log)
            parent_id, attempt, retry_of = self._select_attempt(
                candidate_digest,
                parent_id,
                compatibility,
                retry_of,
                generation_id=generation_id,
            )
            if retry_of is not None:
                prior_attempt = self.projection.experiment(
                    self.config.project_id,
                    retry_of,
                )
                prior_payload = prior_attempt.get("payload")
                if not isinstance(prior_payload, Mapping):
                    raise IntegrityError("projected retry registration is invalid")
                graph_metadata = inherit_retry_graph_metadata(prior_payload)

            parent_row: Mapping[str, Any] | None = None
            if parent_id is not None:
                try:
                    parent_row = self.projection.experiment(
                        self.config.project_id,
                        parent_id,
                    )
                except IntegrityError as exc:
                    raise ConfigurationError(
                        f"unknown parent experiment: {parent_id}"
                    ) from exc
                if parent_row.get("generation_id") != generation_id:
                    raise ConfigurationError(
                        "parent_id must reference an experiment in the active generation"
                    )
            if graph_metadata is not None:
                validate_graph_relationship(
                    graph_metadata,
                    parent_id,
                    parent_is_terminal=(
                        None
                        if parent_row is None
                        else is_terminal(str(parent_row.get("status", "")))
                    ),
                    compatibility_digest=compatibility,
                    parent_compatibility_digest=(
                        None
                        if parent_row is None
                        else str(parent_row.get("compatibility_digest", ""))
                    ),
                )
                validate_graph_candidate_change(
                    graph_metadata,
                    candidate_digest=candidate_digest,
                    parent_candidate_digest=(
                        None
                        if parent_row is None
                        else str(parent_row.get("candidate_digest", ""))
                    ),
                )
            self._assert_static_compatibility(report)

            baseline = self._compatible_baseline(compatibility)
            if baseline is None:
                created_baseline = self._baseline()
                # _baseline() runs doctor again; the original candidate request is
                # valid only if the complete immutable compatibility seal survived.
                if created_baseline["compatibility_digest"] != compatibility:
                    raise IntegrityError(
                        "project compatibility changed while establishing baseline"
                    )
                self._assert_static_compatibility(report)
                baseline = self._compatible_baseline(compatibility)
                if baseline is None:  # pragma: no cover - defensive invariant
                    raise IntegrityError("newly recorded baseline cannot be reloaded")
                if context_token is not None:
                    agent_context_snapshot, _ = (
                        self._validate_agent_context_after_doctor(
                            context_token,
                            report,
                        )
                    )

            experiment_id = new_experiment_id(
                self.config.project_id,
                candidate_digest,
                compatibility_digest=compatibility,
                parent_id=parent_id,
                generation_id=generation_id,
                attempt=attempt,
            )
        manager: WorkspaceManager | None = None
        handle: Any = None
        result: ResultEnvelope | None = None
        captured_records: list[ArtifactRecord] = []
        decision: Decision | None = None
        verified = False
        terminal: tuple[TerminalStatus, str] | None = None
        failure: BaseException | None = None
        secondary_errors: list[BaseException] = []
        cleanup_errors: list[BaseException] = []
        cancelled = False
        interrupt_error: KeyboardInterrupt | None = None
        evidence_pending: BaseException | None = None
        workspace_detached = False
        recorded_notes: set[tuple[int, str]] = set()
        registered = False
        registration_event_id: str | None = None

        def record_exception_notes(exc: BaseException) -> None:
            notes = getattr(exc, "__notes__", None)
            if not isinstance(notes, list):
                return
            for note in notes:
                if not isinstance(note, str):
                    continue
                identity = (id(exc), note)
                if identity in recorded_notes:
                    continue
                recorded_notes.add(identity)
                secondary_errors.append(ProtocolError(note))

        def record_interrupt(exc: KeyboardInterrupt) -> None:
            nonlocal cancelled, failure, interrupt_error, terminal
            cancelled = True
            interrupt_error = exc
            record_exception_notes(exc)
            if terminal is not None and terminal[0] is TerminalStatus.UNTRUSTED:
                secondary_errors.append(exc)
                return
            if failure is not None and failure is not exc:
                secondary_errors.append(failure)
            failure = exc
            terminal = (TerminalStatus.CANCELLED, "USER_CANCELLED")

        def publication_is_complete(exc: BaseException) -> bool:
            try:
                return self._artifact_records_are_published(
                    experiment_id, captured_records
                )
            except IntegrityError as binding_error:
                exc.add_note(
                    "artifact publication could not be proven complete: "
                    f"{binding_error}"
                )
                return False

        def registration_commit_is_owned() -> bool:
            """Prove that this invocation, not an ID-identical rival, committed."""

            if registration_event_id is None:
                return False
            return any(
                event.event_id == registration_event_id
                and _normalized_event_type(event.event_type)
                == "EXPERIMENT_REGISTERED"
                and event.payload.get("experiment_id") == experiment_id
                for event in self.event_log.read()
            )

        try:
            self._assert_static_compatibility(report)
            if context_token is not None:
                agent_context_snapshot, _ = self._validate_agent_context_after_doctor(
                    context_token,
                    report,
                )
            if registration is None:
                registration = {
                    "experiment_id": experiment_id,
                    "parent_id": parent_id,
                    "candidate_digest": candidate_digest,
                    "candidate": candidate,
                    "compatibility_digest": compatibility,
                    "source_tree_digest": report.fingerprints[
                        "source_tree_digest"
                    ],
                    "baseline_id": baseline["baseline_id"],
                    "primary_metric": baseline["primary_metric"],
                    "attempt": attempt,
                    "retry_of": retry_of,
                    "status": "registered",
                    "authorized_action": None,
                }
                if generation_id is not None:
                    registration.update(
                        registration_payload_fields(
                            science_state,
                            retry_of=retry_of,
                        )
                    )
                if graph_metadata is not None:
                    registration.update(graph_metadata.to_payload())
            if context_token is not None:
                registration["agent_context_token"] = context_token
                registration["agent_context_snapshot"] = agent_context_snapshot
                if agent_context_snapshot is None:  # pragma: no cover - guarded above
                    raise IntegrityError("agent context snapshot is unavailable")
            if generation_id is not None and not typed_path:
                reserve_registration(science_state, registration)
            registration_event_id = new_id("event")
            self._append_registration_event(
                registration,
                report=report,
                context_token=context_token,
                snapshot=agent_context_snapshot,
                event_id=registration_event_id,
            )
            registered = True
            self._sync()
            self._assert_static_compatibility(report)
            manager = WorkspaceManager(self.config)
            self._assert_static_compatibility(report)
            handle = manager.create(experiment_id)
            if handle.source_hash != report.fingerprints["source_tree_digest"]:
                raise IntegrityError(
                    "workspace source tree differs from the registration seal"
                )
            self._assert_static_compatibility(report)

            materialize_input = {
                "candidate": candidate,
                "candidate_digest": candidate_digest,
            }
            if evaluation_scope is not None:
                materialize_input["evaluation_scope"] = (
                    evaluation_scope.to_dict()
                )
            response = self._call_sealed(
                report,
                Operation.MATERIALIZE,
                payload=materialize_input,
                workspace=handle.path,
                experiment_id=experiment_id,
            )
            self._record_stage(
                experiment_id,
                Operation.MATERIALIZE,
                input_value=materialize_input,
                response=response,
            )
            _response_payload(response, Operation.MATERIALIZE)
            manager.verify(handle)

            run_input = {
                "candidate_digest": candidate_digest,
                "baseline_id": baseline["baseline_id"],
            }
            if evaluation_scope is not None:
                run_input["evaluation_scope"] = evaluation_scope.to_dict()
            response = self._call_sealed(
                report,
                Operation.RUN,
                payload=run_input,
                workspace=handle.path,
                experiment_id=experiment_id,
            )
            self._record_stage(
                experiment_id,
                Operation.RUN,
                input_value=run_input,
                response=response,
            )
            _response_payload(response, Operation.RUN)
            manager.verify_protected(handle)
            manager.verify_source_unchanged(handle)

            evaluate_input = {"candidate_digest": candidate_digest}
            if evaluation_scope is not None:
                evaluate_input["evaluation_scope"] = (
                    evaluation_scope.to_dict()
                )
            response = self._call_sealed(
                report,
                Operation.EVALUATE,
                payload=evaluate_input,
                workspace=handle.path,
                experiment_id=experiment_id,
            )
            self._record_stage(
                experiment_id,
                Operation.EVALUATE,
                input_value=evaluate_input,
                response=response,
            )
            result = _result(response, Operation.EVALUATE)
            manager.verify(handle, allowed_outputs=result.artifacts)

            # Capture evaluation evidence before invoking project verify code.
            # Even a failed verifier must not leave terminal result references
            # pointing only at a workspace that cleanup will delete.
            captured_records = self.catalog.capture(
                handle.path,
                self.config.project_id,
                experiment_id,
                result.artifacts,
            )
            self._publish_artifact_records(experiment_id, captured_records)

            verify_input = {"result_digest": sha256_json(result.to_dict())}
            if evaluation_scope is not None:
                verify_input["evaluation_scope"] = evaluation_scope.to_dict()
            response = self._call_sealed(
                report,
                Operation.VERIFY,
                payload=verify_input,
                workspace=handle.path,
                experiment_id=experiment_id,
            )
            self._record_stage(
                experiment_id,
                Operation.VERIFY,
                input_value=verify_input,
                response=response,
            )
            verify_result = _verify_result(response)
            manager.verify(handle, allowed_outputs=result.artifacts)
            verified = verify_result.valid

            recaptured = self.catalog.capture(
                handle.path,
                self.config.project_id,
                experiment_id,
                [
                    {
                        "path": record.relative_path,
                        "role": record.role,
                        "media_type": record.media_type,
                        "metadata": record.metadata,
                        "sha256": record.digest,
                        "size_bytes": record.size,
                    }
                    for record in captured_records
                ],
            )
            if [record.to_dict() for record in recaptured] != [
                record.to_dict() for record in captured_records
            ]:
                raise IntegrityError("verified artifact records changed after evaluation")

            if verified:
                baseline_value = float(baseline["primary_value"])
                decision = decide(self.config, result, baseline_value, verified=True)
                terminal = (decision.status, decision.reason_code)
            else:
                category = verify_result.category
                assert isinstance(category, FailureCategory)
                terminal = (category.terminal_status, verify_result.reason_code)
        except KeyboardInterrupt as exc:
            if not registered:
                # An interrupt may land after the durable append returns but
                # before the local assignment above.  A caller-owned event ID
                # proves that exact commit without mistaking an identical
                # contender's deterministic experiment ID for our own work.
                registered = registration_commit_is_owned()
                if not registered:
                    raise
            record_interrupt(exc)
        except Exception as exc:
            if not registered:
                registered = registration_commit_is_owned()
                if not registered:
                    # A raised append did not publish this caller's exact
                    # registration event.  In particular, do not terminalize
                    # an ID-identical concurrent winner.
                    raise
            record_exception_notes(exc)
            failure = exc
            terminal = _classify_failure(exc)
        finally:
            if result is None and handle is not None and manager is not None:
                try:
                    # An event append can commit the successful evaluator
                    # response and then deliver an interrupt/error before the
                    # local assignment below it executes.  Canonical history,
                    # not the Python stack position, decides whether output now
                    # needs sealing.
                    result = self._evaluation_result_for_recovery(experiment_id)
                except IntegrityError as exc:
                    # A protocol-invalid evaluator response is already the
                    # current run's infrastructure failure.  Recovery wraps
                    # the same invalid canonical response as integrity drift;
                    # do not reclassify that one known failure merely because
                    # result assignment never completed.
                    if not isinstance(failure, ProtocolError):
                        if failure is not None and failure is not exc:
                            secondary_errors.append(failure)
                        failure = exc
                        terminal = _classify_failure(exc)
            if (
                result is not None
                and result.artifacts
                and not captured_records
                and handle is not None
                and manager is not None
            ):
                try:
                    # A cancellation or capture failure after EVALUATE must not
                    # leave dangling artifact references in a terminal event.
                    # Finish the first local evidence finalization before any
                    # adapter or workspace cleanup is allowed to run.
                    manager.verify(handle, allowed_outputs=result.artifacts)
                    captured_records = self.catalog.capture(
                        handle.path,
                        self.config.project_id,
                        experiment_id,
                        result.artifacts,
                    )
                except KeyboardInterrupt as exc:
                    record_interrupt(exc)
                    evidence_pending = exc
                except Exception as exc:
                    record_exception_notes(exc)
                    if failure is not None and failure is not exc:
                        secondary_errors.append(failure)
                    failure = exc
                    terminal = _classify_failure(exc)
                    evidence_pending = exc
            if captured_records:
                try:
                    self._publish_artifact_records(
                        experiment_id, captured_records
                    )
                except KeyboardInterrupt as exc:
                    record_interrupt(exc)
                    if not publication_is_complete(exc):
                        evidence_pending = exc
                except IntegrityError as exc:
                    if not publication_is_complete(exc):
                        evidence_pending = exc
                    if terminal is not None and (
                        terminal[0] is TerminalStatus.UNTRUSTED
                    ):
                        secondary_errors.append(exc)
                    else:
                        if failure is not None and failure is not exc:
                            secondary_errors.append(failure)
                        failure = exc
                        terminal = _classify_failure(exc)
                except Exception as exc:
                    if not publication_is_complete(exc):
                        evidence_pending = exc
                    if terminal is not None and terminal[0] in {
                        TerminalStatus.CANCELLED,
                        TerminalStatus.UNTRUSTED,
                    }:
                        secondary_errors.append(exc)
                    else:
                        if failure is not None and failure is not exc:
                            secondary_errors.append(failure)
                        failure = exc
                        terminal = _classify_failure(exc)
            if (
                evidence_pending is not None
                and handle is not None
                and manager is not None
            ):
                try:
                    manager.detach(handle)
                    workspace_detached = True
                except BaseException as detach_error:
                    evidence_pending.add_note(
                        "failed to preserve pending evidence workspace: "
                        f"{type(detach_error).__name__}: {detach_error}"
                    )
            if (
                handle is not None
                and manager is not None
                and evidence_pending is None
            ):
                adapter_is_sealed = False
                try:
                    manager.verify_protected(handle)
                    manager.verify_source_unchanged(handle)
                    self._assert_static_compatibility(report)
                    adapter_is_sealed = True
                except KeyboardInterrupt as exc:
                    record_interrupt(exc)
                except Exception as exc:
                    if failure is not None:
                        secondary_errors.append(failure)
                    failure = exc
                    terminal = _classify_failure(exc)
                if adapter_is_sealed:
                    try:
                        self._adapter_cleanup(report, handle.path, experiment_id)
                    except KeyboardInterrupt as exc:
                        record_interrupt(exc)
                    except IntegrityError as exc:
                        if failure is not None:
                            secondary_errors.append(failure)
                        failure = exc
                        terminal = _classify_failure(exc)
                    except Exception as exc:
                        cleanup_errors.append(exc)
                    try:
                        manager.verify_protected(handle)
                        manager.verify_source_unchanged(handle)
                        self._assert_static_compatibility(report)
                    except KeyboardInterrupt as exc:
                        record_interrupt(exc)
                    except Exception as exc:
                        if failure is not None:
                            secondary_errors.append(failure)
                        failure = exc
                        terminal = _classify_failure(exc)
                try:
                    manager.cleanup(handle)
                except KeyboardInterrupt as exc:
                    record_interrupt(exc)
                except IntegrityError as exc:
                    if failure is not None:
                        secondary_errors.append(failure)
                    failure = exc
                    terminal = _classify_failure(exc)
                except Exception as exc:
                    cleanup_errors.append(exc)
            if manager is not None and (
                evidence_pending is None or workspace_detached
            ):
                try:
                    manager.close()
                except KeyboardInterrupt as exc:
                    record_interrupt(exc)
                except Exception as exc:
                    cleanup_errors.append(exc)

        if evidence_pending is not None:
            if isinstance(failure, IntegrityError):
                raise failure
            if interrupt_error is not None:
                raise interrupt_error
            if failure is not None:
                raise failure
            raise evidence_pending

        if result is not None:
            result = _bind_captured_result(result, captured_records)

        assert terminal is not None
        status, reason_code = terminal
        secondary_errors.extend(cleanup_errors)
        try:
            summary = self._terminate(
                experiment_id,
                status,
                reason_code,
                attempt=attempt,
                retry_of=retry_of,
                decision=decision if failure is None else None,
                result=result,
                error=failure,
                secondary_errors=secondary_errors,
                verified=verified,
            )
        except KeyboardInterrupt as exc:
            # The append boundary may have committed before an interrupt was
            # delivered.  Inspect canonical history before deciding whether a
            # cancellation terminal still needs to be written.
            record_interrupt(exc)
            if self._terminal_event_for(experiment_id) is None:
                assert terminal is not None
                status, reason_code = terminal
                self._terminate(
                    experiment_id,
                    status,
                    reason_code,
                    attempt=attempt,
                    retry_of=retry_of,
                    decision=decision if failure is None else None,
                    result=result,
                    error=failure,
                    secondary_errors=secondary_errors,
                    verified=verified,
                )
            else:
                self._reconcile_outcome_findings()
                self._sync()
            raise
        if cancelled:
            if interrupt_error is not None:
                raise interrupt_error
            raise KeyboardInterrupt  # pragma: no cover - defensive invariant
        return _legacy_public_run_summary(summary)

    def _agent_context_snapshot(
        self,
        *,
        agent_spec: Mapping[str, Any] | None = None,
        fingerprints: Mapping[str, Any] | None = None,
        evaluator_certification: Mapping[str, Any] | None = None,
        events: Sequence[Event] | None = None,
    ) -> dict[str, Any]:
        resolved_events = self.event_log.read() if events is None else list(events)
        resolved_certification = (
            self._evaluator_certification_summary()
            if evaluator_certification is None
            else evaluator_certification
        )
        resolved_spec = (
            load_agent_spec(
                self.config.root,
                evaluator_certification=resolved_certification,
            )
            if agent_spec is None
            else agent_spec
        )
        resolved_fingerprints = (
            project_fingerprints(self.config)
            if fingerprints is None
            else fingerprints
        )
        last_event = resolved_events[-1] if resolved_events else None
        payload = {
            "schema_version": 2,
            "project_id": self.config.project_id,
            "project_compatibility_digest": resolved_fingerprints[
                "compatibility_digest"
            ],
            "agent_spec_digest": sha256_json(resolved_spec),
            "evaluator_certification_digest": resolved_certification.get(
                "digest",
                resolved_certification.get("certification_digest"),
            ),
            "evaluator_certification_state_digest": sha256_json(
                resolved_certification
            ),
            "last_sequence": last_event.sequence if last_event is not None else 0,
            "last_hash": last_event.hash if last_event is not None else None,
        }
        return {**payload, "context_token": sha256_json(payload)}

    def _evaluator_certification_summary(
        self,
        *,
        fingerprints: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        return inspect_evaluator_certification(
            self.config,
            fingerprints=fingerprints,
        )

    def _evaluation_seal_from_report(
        self,
        report: DoctorReport,
    ) -> EvaluationSeal:
        """Derive the exact active-evaluator seal from a fresh doctor report."""

        certification = self._evaluator_certification_summary(
            fingerprints=report.fingerprints,
        )
        if (
            certification.get("certified") is not True
            or certification.get("current") is not True
        ):
            status = str(certification.get("status", "MISSING"))
            raise EvaluatorCertificationError(
                "a current passing evaluator certification is required to bind "
                "a study generation",
                reason=status.lower(),
                details={
                    "status": status,
                    "blockers": list(certification.get("blockers", [])),
                },
            )
        return EvaluationSeal.from_mapping(
            {
                "compatibility_digest": report.fingerprints[
                    "compatibility_digest"
                ],
                "evaluator_certification_digest": certification[
                    "certification_digest"
                ],
                "evaluator_review_subject_digest": certification[
                    "review_subject_digest"
                ],
            }
        )

    def _agent_research_state(
        self,
        *,
        events: Sequence[Event] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        fingerprints = project_fingerprints(self.config)
        certification = self._evaluator_certification_summary(
            fingerprints=fingerprints
        )
        agent_spec = load_agent_spec(
            self.config.root,
            evaluator_certification=certification,
        )
        snapshot = self._agent_context_snapshot(
            agent_spec=agent_spec,
            fingerprints=fingerprints,
            evaluator_certification=certification,
            events=events,
        )
        return snapshot, agent_spec, certification

    def _validate_agent_context_token(
        self,
        context_token: str,
        *,
        require_ready: bool,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        self._assert_config_unchanged()
        self.event_log.verify()
        snapshot, agent_spec, _ = self._agent_research_state()
        if snapshot["context_token"] != context_token:
            raise StaleAgentContextError(
                "agent context is stale; refresh agent-context before proposing"
            )
        if require_ready and agent_spec.get("research_ready") is not True:
            raw_blockers = agent_spec.get("setup_blockers", [])
            blockers = (
                [str(value) for value in raw_blockers]
                if isinstance(raw_blockers, Sequence)
                and not isinstance(raw_blockers, (str, bytes, bytearray))
                else []
            )
            raise AgentResearchNotReadyError(
                "agent research gates are incomplete; configure the project and "
                "record a current passing evaluator certification",
                blockers=blockers,
            )
        return snapshot, agent_spec

    def _validate_agent_context_after_doctor(
        self,
        context_token: str,
        report: DoctorReport,
        *,
        events: Sequence[Event] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Recheck a proposal against canonical state and the adapter doctor seal."""

        locked_events = tuple(events) if events is not None else tuple(self.event_log.read())
        fresh_report = self._doctor_snapshot(event_count=len(locked_events))
        if (
            fresh_report.capabilities != report.capabilities
            or fresh_report.side_effects != report.side_effects
            or fresh_report.adapter_fingerprint != report.adapter_fingerprint
            or fresh_report.fingerprints != report.fingerprints
        ):
            raise StaleAgentContextError(
                "agent context is stale; adapter doctor seal changed before commit"
            )
        certification = self._evaluator_certification_summary(
            fingerprints=fresh_report.fingerprints,
        )
        agent_spec = load_agent_spec(
            self.config.root,
            evaluator_certification=certification,
        )
        context_fingerprints = {
            **fresh_report.fingerprints,
            # Agent-context schema v2 historically seals the project component
            # here; the certification state separately seals the effective
            # project+adapter compatibility digest.
            "compatibility_digest": fresh_report.fingerprints[
                "project_compatibility_digest"
            ],
        }
        snapshot = self._agent_context_snapshot(
            agent_spec=agent_spec,
            fingerprints=context_fingerprints,
            evaluator_certification=certification,
            events=locked_events,
        )
        if snapshot["context_token"] != context_token:
            raise StaleAgentContextError(
                "agent context is stale; refresh agent-context before proposing"
            )
        if agent_spec.get("research_ready") is not True:
            raw_blockers = agent_spec.get("setup_blockers", [])
            blockers = (
                [str(value) for value in raw_blockers]
                if isinstance(raw_blockers, Sequence)
                and not isinstance(raw_blockers, (str, bytes, bytearray))
                else []
            )
            raise AgentResearchNotReadyError(
                "agent research gates are incomplete under the current adapter seal",
                blockers=blockers,
            )
        self._assert_static_compatibility(fresh_report)
        return snapshot, agent_spec

    @staticmethod
    def _snapshot_head(snapshot: Mapping[str, Any]) -> tuple[int, str | None]:
        sequence = snapshot.get("last_sequence")
        digest = snapshot.get("last_hash")
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 0
            or (sequence == 0 and digest is not None)
            or (
                sequence > 0
                and (
                    not isinstance(digest, str)
                    or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                )
            )
        ):
            raise IntegrityError("agent context snapshot has an invalid canonical head")
        return sequence, digest

    def _append_registration_event(
        self,
        payload: Mapping[str, Any],
        *,
        report: DoctorReport,
        context_token: str | None,
        snapshot: Mapping[str, Any] | None,
        event_id: str | None = None,
    ) -> Event:
        """Commit one registration through the common locked science gate."""

        if context_token is None:
            expected_head = None
        else:
            if snapshot is None:  # pragma: no cover - guarded by caller
                raise IntegrityError("agent context snapshot is unavailable")
            expected_head = self._snapshot_head(snapshot)

        def validate_locked_registration(locked_events: tuple[Event, ...]) -> None:
            if context_token is not None:
                self._validate_agent_context_after_doctor(
                    context_token,
                    report,
                    events=locked_events,
                )
            locked_state = reduce_scientific_state(
                locked_events,
                project_id=self.config.project_id,
            )
            if locked_state.active_generation_id is not None:
                # Keep malformed or incorrectly bound registration evidence
                # ahead of live environment checks in the stable science error
                # ordering. Pre-generation registrations intentionally retain
                # their exact legacy semantics.
                validate_registration(locked_state, payload)
                fresh_report = self._doctor_snapshot(
                    event_count=len(locked_events)
                )
                locked_contract = locked_state.contract
                if locked_contract is None:  # pragma: no cover - reducer invariant
                    raise IntegrityError(
                        "active generation omitted its study contract"
                    )
                self._validate_typed_generation_environment(
                    locked_contract,
                    fresh_report,
                )
                live_seal = self._evaluation_seal_from_report(fresh_report)
                if live_seal.digest != locked_state.evaluation_seal_digest:
                    raise ScientificStateError(
                        "STUDY_EVALUATION_SEAL_MISMATCH",
                        "the active generation is not bound to the current evaluator seal",
                        details={
                            "active_evaluation_seal_digest": (
                                locked_state.evaluation_seal_digest
                            ),
                            "current_evaluation_seal_digest": live_seal.digest,
                        },
                    )
                reserve_registration(locked_state, payload)

        try:
            with evaluator_certification_read_lock(self.config):
                return self.event_log.append(
                    "EXPERIMENT_REGISTERED",
                    payload,
                    event_id=event_id,
                    expected_head=expected_head,
                    precondition=validate_locked_registration,
                    postcondition=validate_locked_registration,
                )
        except EventHeadMismatchError as exc:
            raise StaleAgentContextError(
                "agent context is stale; refresh agent-context before proposing"
            ) from exc

    def _append_agent_authorized_event(
        self,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        context_token: str,
        snapshot: Mapping[str, Any],
        report: DoctorReport,
    ) -> Event:
        """Commit only while both the proposal head and certification stay current."""

        expected_head = self._snapshot_head(snapshot)

        def validate_before_append(locked_events: tuple[Event, ...]) -> None:
            self._validate_agent_context_after_doctor(
                context_token,
                report,
                events=locked_events,
            )

        def validate_after_durability(locked_events: tuple[Event, ...]) -> None:
            self._validate_agent_context_after_doctor(
                context_token,
                report,
                events=locked_events,
            )

        try:
            # The shared certification lock spans the actual event write, so a
            # managed replacement cannot enter between the final review check
            # and the canonical commit.
            with evaluator_certification_read_lock(self.config):
                return self.event_log.append(
                    event_type,
                    payload,
                    expected_head=expected_head,
                    precondition=validate_before_append,
                    postcondition=validate_after_durability,
                )
        except EventHeadMismatchError as exc:
            raise StaleAgentContextError(
                "agent context is stale; refresh agent-context before proposing"
            ) from exc

    def agent_context(
        self,
        *,
        limit: int = 20,
        schema_version: int = 3,
    ) -> dict[str, Any]:
        """Return one bounded evidence packet for Codex or Claude Code."""

        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise ValueError("agent context limit must be an integer from 1 to 100")
        if (
            isinstance(schema_version, bool)
            or not isinstance(schema_version, int)
            or schema_version not in {2, 3}
        ):
            raise ValueError("agent context schema version must be 2 or 3")
        with self._workflow_lock():
            self._assert_config_unchanged()
            self.event_log.verify()
            if schema_version == 3:
                return self._agent_context_v3_read_only(limit=limit)
            self._recover_incomplete_experiments()
            for _ in range(3):
                events_before = self.event_log.read()
                head_before = (
                    (events_before[-1].sequence, events_before[-1].hash)
                    if events_before
                    else (0, None)
                )
                status = self.projection.project_status(self.config.project_id)
                lineage = self.projection.lineage(self.config.project_id)
                findings = self.projection.findings(project_id=self.config.project_id)
                artifacts = self.projection.artifacts(self.config.project_id)
                for record in artifacts:
                    self._verify_projected_artifact(record)
                events_after = self.event_log.read()
                head_after = (
                    (events_after[-1].sequence, events_after[-1].hash)
                    if events_after
                    else (0, None)
                )
                projected_head = (status.get("last_sequence"), status.get("last_hash"))
                if head_before != head_after or projected_head != head_after:
                    self.projection.rebuild(self.event_log)
                    continue
                snapshot, agent_spec, certification = self._agent_research_state(
                    events=events_after
                )
                binding_digests = certification.get("bindings")
                effective_compatibility = (
                    binding_digests.get("effective_compatibility")
                    if isinstance(binding_digests, Mapping)
                    else None
                )
                baseline_ready = bool(
                    isinstance(effective_compatibility, str)
                    and effective_compatibility
                    and self._compatible_baseline_from_events(
                        events_after,
                        effective_compatibility,
                    )
                    is not None
                )
                return build_agent_context(
                    project=self.inspect(),
                    status=status,
                    lineage=lineage,
                    findings=findings,
                    artifacts=artifacts,
                    agent_spec=agent_spec,
                    snapshot=snapshot,
                    limit=limit,
                    current_compatibility_digest=(
                        effective_compatibility
                        if isinstance(effective_compatibility, str)
                        and effective_compatibility
                        else None
                    ),
                    compatible_baseline_ready=baseline_ready,
                )
            raise IntegrityError(
                "canonical history changed repeatedly while building agent context"
            )

    def _agent_context_v3_read_only(self, *, limit: int) -> dict[str, Any]:
        """Build Context v3 without recovery or writes to the project cache."""

        for _ in range(3):
            events_before = tuple(self.event_log.read())
            head_before = (
                (events_before[-1].sequence, events_before[-1].hash)
                if events_before
                else (0, None)
            )
            science = reduce_scientific_state(
                events_before,
                project_id=self.config.project_id,
            )
            with tempfile.TemporaryDirectory(
                prefix="research-os-context-v3-"
            ) as temporary:
                temporary_root = Path(temporary)
                temporary_log = EventLog(
                    temporary_root / "events.jsonl",
                    self.config.project_id,
                )
                for event in events_before:
                    copied = temporary_log.append(
                        event.event_type,
                        event.payload,
                        event_id=event.event_id,
                        occurred_at=event.occurred_at,
                    )
                    if copied.to_dict() != event.to_dict():
                        raise IntegrityError(
                            "Context v3 temporary replay changed a canonical event"
                        )
                projection = ProjectionStore(temporary_root / "state.db")
                projection.rebuild(temporary_log)
                status = projection.project_status(self.config.project_id)
                lineage = projection.lineage(self.config.project_id)
                findings = projection.findings(project_id=self.config.project_id)
                artifacts = projection.artifacts(self.config.project_id)
            for record in artifacts:
                self._verify_projected_artifact(record)
            events_after = tuple(self.event_log.read())
            head_after = (
                (events_after[-1].sequence, events_after[-1].hash)
                if events_after
                else (0, None)
            )
            if head_before != head_after:
                continue
            snapshot, agent_spec, certification = self._agent_research_state(
                events=events_after
            )
            bindings = certification.get("bindings")
            effective_compatibility = (
                bindings.get("effective_compatibility")
                if isinstance(bindings, Mapping)
                else None
            )
            baseline_ready = bool(
                isinstance(effective_compatibility, str)
                and effective_compatibility
                and self._compatible_baseline_from_events(
                    events_after,
                    effective_compatibility,
                )
                is not None
            )
            return build_agent_context_v3(
                project=self.inspect(),
                status=status,
                lineage=lineage,
                findings=findings,
                artifacts=artifacts,
                agent_spec=agent_spec,
                snapshot=snapshot,
                scientific_state=science.to_dict(),
                limit=limit,
                current_compatibility_digest=(
                    effective_compatibility
                    if isinstance(effective_compatibility, str)
                    and effective_compatibility
                    else None
                ),
                compatible_baseline_ready=baseline_ready,
            )
        raise IntegrityError(
            "canonical history changed repeatedly while building agent context"
        )

    def conclude_branch(
        self,
        conclusion_path: str | Path,
        *,
        context_token: str,
    ) -> dict[str, Any]:
        """Durably record an agent interpretation bound to terminal evidence."""

        if not isinstance(context_token, str) or not context_token:
            raise ValueError("context_token must be a non-empty string")
        with self._workflow_lock():
            snapshot, _ = self._validate_agent_context_token(
                context_token,
                require_ready=True,
            )
            report = self._doctor()
            self._recover_incomplete_experiments()
            snapshot, _ = self._validate_agent_context_after_doctor(
                context_token,
                report,
            )
            value = self._load_json_object(
                conclusion_path,
                label="branch conclusion",
            )
            required = {
                "branch_experiment_ids",
                "hypothesis_class",
                "failure_signature",
                "conclusion",
                "confidence",
                "next_step",
            }
            if set(value) != required:
                missing = sorted(required - set(value))
                extra = sorted(set(value) - required)
                raise ConfigurationError(
                    "branch conclusion must contain exactly the documented fields; "
                    f"missing={missing}, extra={extra}"
                )
            raw_ids = value["branch_experiment_ids"]
            if (
                not isinstance(raw_ids, Sequence)
                or isinstance(raw_ids, (str, bytes, bytearray))
                or not raw_ids
                or not all(isinstance(item, str) and item for item in raw_ids)
            ):
                raise ConfigurationError(
                    "branch_experiment_ids must be a non-empty string array"
                )
            experiment_ids = [str(item) for item in raw_ids]
            if len(set(experiment_ids)) != len(experiment_ids):
                raise ConfigurationError(
                    "branch_experiment_ids cannot contain duplicates"
                )
            for key in ("hypothesis_class", "failure_signature", "conclusion"):
                item = value[key]
                if not isinstance(item, str) or not item.strip():
                    raise ConfigurationError(f"{key} must be a non-empty string")
                value[key] = item.strip()
            if value["confidence"] not in {
                "supported",
                "falsified",
                "inconclusive",
            }:
                raise ConfigurationError(
                    "confidence must be supported, falsified, or inconclusive"
                )
            if value["next_step"] not in {
                "stop",
                "change_control",
                "explore",
                "ablate",
                "exploit",
                "replicate",
            }:
                raise ConfigurationError("branch conclusion next_step is invalid")

            self.projection.rebuild(self.event_log)
            rows: list[Mapping[str, Any]] = []
            for experiment_id in experiment_ids:
                try:
                    row = self.projection.experiment(
                        self.config.project_id,
                        experiment_id,
                    )
                except IntegrityError as exc:
                    raise ConfigurationError(
                        f"unknown branch experiment: {experiment_id}"
                    ) from exc
                try:
                    terminal = is_terminal(str(row.get("status", "")))
                except LifecycleError as exc:
                    raise IntegrityError(
                        f"projected branch status is invalid: {experiment_id}"
                    ) from exc
                if not terminal:
                    raise ConfigurationError(
                        f"branch experiment is not terminal: {experiment_id}"
                    )
                rows.append(row)
            compatibility_digests = {
                str(row.get("compatibility_digest", "")) for row in rows
            }
            if len(compatibility_digests) != 1 or "" in compatibility_digests:
                raise ConfigurationError(
                    "a branch conclusion requires one compatibility digest"
                )

            terminal_events: dict[str, Event] = {}
            for event in self.event_log.read():
                event_type = _normalized_event_type(event.event_type)
                if event_type not in _TERMINAL_EVENT_TYPES:
                    continue
                if event_type == "EXPERIMENT_STATUS_CHANGED":
                    raw_status = event.payload.get(
                        "status",
                        event.payload.get("state"),
                    )
                    if not isinstance(raw_status, str):
                        raise IntegrityError(
                            "branch evidence contains a non-string status"
                        )
                    try:
                        if not is_terminal(raw_status):
                            continue
                    except (LifecycleError, TypeError, ValueError) as exc:
                        raise IntegrityError(
                            "branch evidence contains an invalid status event"
                        ) from exc
                experiment_id = event.payload.get(
                    "experiment_id",
                    event.payload.get("id"),
                )
                if experiment_id in experiment_ids:
                    if str(experiment_id) in terminal_events:
                        raise IntegrityError(
                            "branch experiment has duplicate terminal events"
                        )
                    terminal_events[str(experiment_id)] = event
            if set(terminal_events) != set(experiment_ids):
                raise IntegrityError(
                    "branch conclusion is missing canonical terminal evidence"
                )
            evidence = [
                {
                    "experiment_id": experiment_id,
                    "event_id": terminal_events[experiment_id].event_id,
                    "event_hash": terminal_events[experiment_id].hash,
                }
                for experiment_id in experiment_ids
            ]
            content = {
                **value,
                "branch_experiment_ids": experiment_ids,
                "compatibility_digest": next(iter(compatibility_digests)),
            }
            finding_id = stable_id(
                "finding",
                self.config.project_id,
                "branch_conclusion",
                1,
                content,
                evidence,
            )
            if any(
                event.event_type == "FINDING_RECORDED"
                and event.payload.get("finding_id") == finding_id
                for event in self.event_log.read()
            ):
                raise ConfigurationError(
                    "this branch conclusion is already recorded"
                )
            payload = make_finding_event(
                self.config.project_id,
                content,
                key="branch_conclusion",
                evidence=evidence,
                metadata={
                    "claim_authority": "agent_interpretation",
                    "authorized_action": None,
                    "agent_context_token": context_token,
                    "agent_context_schema_version": snapshot["schema_version"],
                },
                finding_id=finding_id,
            )
            payload["branch_conclusion_version"] = 1
            event = self._append_agent_authorized_event(
                "FINDING_RECORDED",
                payload,
                context_token=context_token,
                snapshot=snapshot,
                report=report,
            )
            self._sync()
            return {**payload, "event_sequence": event.sequence}

    def status(self) -> dict[str, Any]:
        with self._workflow_lock():
            self._assert_config_unchanged()
            self.event_log.verify()
            self._recover_incomplete_experiments()
            return self.projection.project_status(self.config.project_id)

    def lineage(self, experiment_id: str | None = None) -> list[dict[str, Any]]:
        with self._workflow_lock():
            self._assert_config_unchanged()
            self.event_log.verify()
            self._recover_incomplete_experiments()
            return self.projection.lineage(self.config.project_id, experiment_id)

    def artifacts(self, experiment_id: str | None = None) -> list[dict[str, Any]]:
        with self._workflow_lock():
            self._assert_config_unchanged()
            self.event_log.verify()
            self._recover_incomplete_experiments()
            records = self.projection.artifacts(self.config.project_id, experiment_id)
            for record in records:
                self._verify_projected_artifact(record)
            return records

    def findings(self, experiment_id: str | None = None) -> list[dict[str, Any]]:
        with self._workflow_lock():
            self._assert_config_unchanged()
            self.event_log.verify()
            self._recover_incomplete_experiments()
            return self.projection.findings(
                project_id=self.config.project_id,
                experiment_id=experiment_id,
            )

    def replay(self) -> dict[str, Any]:
        """Strictly verify canonical history and rebuild every SQLite view."""

        with self._workflow_lock():
            self._assert_config_unchanged()
            self.event_log.verify()
            reduce_scientific_state(
                self.event_log.read(),
                project_id=self.config.project_id,
            )
            self.projection.rebuild(self.event_log)
            self._recover_incomplete_experiments()
            # A Diagnosis or generation append does not take the workflow lock.
            # Rebuild first, then retain one verified shared log snapshot while
            # every returned projection/science/evidence surface is read.  If
            # an append linearized between rebuild and the shared snapshot,
            # retry the rebuild rather than combining two canonical heads.
            for _ in range(8):
                count = self.projection.rebuild(self.event_log)
                with self.event_log.locked_read() as replay_events:
                    if count != len(replay_events):
                        continue
                    science_state = reduce_scientific_state(
                        replay_events,
                        project_id=self.config.project_id,
                    )
                    status = self.projection.project_status(
                        self.config.project_id
                    )
                    expected_hash = replay_events[-1].hash if replay_events else None
                    if (
                        status["last_sequence"] != count
                        or status["last_hash"] != expected_hash
                    ):
                        continue
                    artifact_ids: set[str] = set()
                    projected_records: list[
                        tuple[Mapping[str, Any], ArtifactRecord]
                    ] = []
                    for record in self.projection.artifacts(
                        self.config.project_id
                    ):
                        stored = self._verify_projected_artifact(record)
                        artifact_ids.add(stored.artifact_id)
                        projected_records.append((record, stored))
                    self._verify_terminal_artifact_bindings(
                        projected_records,
                        events=replay_events,
                    )
                    for event in replay_events:
                        if (
                            _normalized_event_type(event.event_type)
                            != "BASELINE_RECORDED"
                        ):
                            continue
                        compatibility = event.payload.get("compatibility_digest")
                        if not isinstance(compatibility, str) or not compatibility:
                            raise IntegrityError(
                                "historical baseline compatibility digest is invalid"
                            )
                        baseline = self._validate_baseline_payload(
                            event.payload,
                            compatibility,
                            enforce_current_policy=False,
                        )
                        baseline_artifacts = cast(
                            Sequence[Mapping[str, Any]], baseline["artifacts"]
                        )
                        for record in baseline_artifacts:
                            expected = ArtifactRecord.from_mapping(record)
                            artifact_ids.add(expected.artifact_id)
                    for artifact_id in sorted(artifact_ids):
                        self.catalog.get(artifact_id)
                    # Direct ProjectionStore.apply() writers do not acquire the
                    # canonical EventLog lock retained above.  Recheck the full
                    # projection observation after every independent query so
                    # this result linearizes before such a writer or retries
                    # after rebuilding its non-canonical cache mutation away.
                    if self.projection.project_status(
                        self.config.project_id
                    ) != status:
                        continue
                    return {
                        "project_id": self.config.project_id,
                        "events_replayed": count,
                        "artifacts_verified": len(artifact_ids),
                        "status": status,
                        "science": science_state.to_dict(),
                        "authorized_action": None,
                    }
            raise IntegrityError(
                "canonical history changed too frequently for a coherent replay"
            )


DESIGN_PROVENANCE = {
    "ResearchService.doctor": ("Immutable evaluation", "Typed provenance"),
    "ResearchService.baseline": ("Immutable evaluation", "Fixed experiment budget"),
    "ResearchService.run_once": (
        "Bounded mutable surface",
        "Reversible ratchet",
        "Experiment DAG",
        "Typed provenance",
    ),
    "ResearchService.record_diagnosis": (
        "Durable graph memory",
        "Typed provenance",
    ),
    "ResearchService.replay": ("Durable graph memory",),
}


__all__ = ["AdapterOperationError", "DoctorReport", "ResearchService"]
