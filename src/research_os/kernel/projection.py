"""Rebuildable SQLite query projection for the canonical event stream."""

from __future__ import annotations

import fcntl
import os
import secrets
import sqlite3
import stat
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, TypeVar, cast

from research_os.errors import IntegrityError, LifecycleError
from research_os.graph_policy import (
    GraphPolicyError,
    graph_metadata_from_payload,
    validate_graph_candidate_change,
    validate_graph_relationship,
    validate_retry_graph_metadata,
)

from ._canonical import (
    canonical_bytes,
    canonical_json,
    require_text,
    sha256_hex,
    strict_json_loads,
)
from .events import Event, EventLog
from .ids import stable_id
from .lifecycle import (
    TERMINAL_STATES,
    LifecycleState,
    coerce_state,
    validate_transition,
)

_SUPPORTED_EVENT_TYPES = frozenset(
    {
        "PROJECT_INITIALIZED",
        "BASELINE_RECORDED",
        "EXPERIMENT_REGISTERED",
        "STAGE_COMPLETED",
        "ADAPTER_STAGE_RECORDED",
        "ARTIFACT_RECORDED",
        "ARTIFACT_CAPTURED",
        "ARTIFACT_CATALOGUED",
        "FINDING_RECORDED",
        "EXPERIMENT_TERMINATED",
        "EXPERIMENT_STATUS_CHANGED",
    }
)

_REQUIRED_SCHEMA_COLUMNS = {
    "projects": frozenset(
        {
            "project_id",
            "status",
            "metadata_json",
            "initialized_at",
            "updated_at",
            "last_sequence",
        }
    ),
    "experiments": frozenset(
        {
            "experiment_id",
            "project_id",
            "generation_id",
            "evaluation_scope_id",
            "parent_id",
            "candidate_digest",
            "compatibility_digest",
            "attempt",
            "retry_of",
            "retryable",
            "status",
            "payload_json",
            "registered_at",
            "terminated_at",
            "created_sequence",
            "updated_sequence",
        }
    ),
    "baselines": frozenset(
        {
            "baseline_id",
            "project_id",
            "experiment_id",
            "digest",
            "metrics_json",
            "payload_json",
            "recorded_at",
            "event_sequence",
        }
    ),
    "adapter_stages": frozenset(
        {
            "stage_id",
            "project_id",
            "experiment_id",
            "stage_name",
            "status",
            "input_digest",
            "output_digest",
            "payload_json",
            "completed_at",
            "event_sequence",
        }
    ),
    "artifacts": frozenset(
        {
            "artifact_id",
            "project_id",
            "experiment_id",
            "digest",
            "algorithm",
            "relative_path",
            "storage_path",
            "role",
            "media_type",
            "size",
            "metadata_json",
            "payload_json",
            "recorded_at",
            "event_sequence",
        }
    ),
    "findings": frozenset(
        {
            "finding_id",
            "scope",
            "project_id",
            "origin_project_id",
            "session_id",
            "experiment_id",
            "finding_key",
            "content_json",
            "evidence_json",
            "payload_json",
            "created_at",
            "event_sequence",
        }
    ),
    "event_cursor": frozenset(
        {"singleton", "project_id", "last_sequence", "last_hash"}
    ),
    "projected_events": frozenset(
        {"event_id", "project_id", "event_sequence", "event_hash"}
    ),
}

_INTEGER_SCHEMA_COLUMNS = frozenset(
    {
        ("projects", "last_sequence"),
        ("experiments", "attempt"),
        ("experiments", "retryable"),
        ("experiments", "created_sequence"),
        ("experiments", "updated_sequence"),
        ("baselines", "event_sequence"),
        ("adapter_stages", "event_sequence"),
        ("artifacts", "size"),
        ("artifacts", "event_sequence"),
        ("findings", "event_sequence"),
        ("event_cursor", "singleton"),
        ("event_cursor", "last_sequence"),
        ("projected_events", "event_sequence"),
    }
)

_REQUIRED_NOT_NULL_COLUMNS = {
    "projects": frozenset(
        {"status", "metadata_json", "initialized_at", "updated_at", "last_sequence"}
    ),
    "experiments": frozenset(
        {
            "project_id",
            "candidate_digest",
            "compatibility_digest",
            "attempt",
            "retryable",
            "status",
            "payload_json",
            "registered_at",
            "created_sequence",
            "updated_sequence",
        }
    ),
    "baselines": frozenset(
        {
            "project_id",
            "digest",
            "metrics_json",
            "payload_json",
            "recorded_at",
            "event_sequence",
        }
    ),
    "adapter_stages": frozenset(
        {
            "project_id",
            "experiment_id",
            "stage_name",
            "status",
            "payload_json",
            "completed_at",
            "event_sequence",
        }
    ),
    "artifacts": frozenset(
        {
            "project_id",
            "digest",
            "algorithm",
            "size",
            "metadata_json",
            "payload_json",
            "recorded_at",
            "event_sequence",
        }
    ),
    "findings": frozenset(
        {
            "scope",
            "origin_project_id",
            "content_json",
            "evidence_json",
            "payload_json",
            "created_at",
            "event_sequence",
        }
    ),
    "event_cursor": frozenset({"last_sequence"}),
    "projected_events": frozenset(
        {"project_id", "event_sequence", "event_hash"}
    ),
}

_PRIMARY_KEY_COLUMNS = {
    "projects": ("project_id",),
    "experiments": ("experiment_id",),
    "baselines": ("baseline_id",),
    "adapter_stages": ("stage_id",),
    "artifacts": ("artifact_id",),
    "findings": ("finding_id",),
    "event_cursor": ("singleton",),
    "projected_events": ("event_id",),
}

_REQUIRED_UNIQUE_COLUMN_KEYS = {
    "experiments": frozenset({("created_sequence",)}),
    "baselines": frozenset({("event_sequence",)}),
    "adapter_stages": frozenset({("event_sequence",)}),
    "artifacts": frozenset({("event_sequence",)}),
    "findings": frozenset({("event_sequence",)}),
    "projected_events": frozenset({("event_sequence",)}),
}

_REQUIRED_FOREIGN_KEYS = {
    "experiments": frozenset(
        {
            ("project_id", "projects", "project_id"),
            ("parent_id", "experiments", "experiment_id"),
            ("retry_of", "experiments", "experiment_id"),
        }
    ),
    "baselines": frozenset(
        {
            ("project_id", "projects", "project_id"),
            ("experiment_id", "experiments", "experiment_id"),
        }
    ),
    "adapter_stages": frozenset(
        {
            ("project_id", "projects", "project_id"),
            ("experiment_id", "experiments", "experiment_id"),
        }
    ),
    "artifacts": frozenset(
        {
            ("project_id", "projects", "project_id"),
            ("experiment_id", "experiments", "experiment_id"),
        }
    ),
    "findings": frozenset(
        {
            ("origin_project_id", "projects", "project_id"),
            ("experiment_id", "experiments", "experiment_id"),
        }
    ),
}

_REQUIRED_NAMED_INDEXES: dict[str, tuple[str, bool, tuple[str | None, ...]]] = {
    "experiments_project_status_idx": (
        "experiments",
        False,
        ("project_id", "status", "created_sequence"),
    ),
    "experiments_candidate_idx": (
        "experiments",
        False,
        (
            "project_id",
            "generation_id",
            "evaluation_scope_id",
            "candidate_digest",
            "parent_id",
        ),
    ),
    "experiments_scope_idx": (
        "experiments",
        False,
        ("project_id", "evaluation_scope_id", "created_sequence"),
    ),
    "experiments_parent_idx": (
        "experiments",
        False,
        ("project_id", "parent_id"),
    ),
    "experiments_retry_idx": (
        "experiments",
        False,
        ("project_id", "retry_of"),
    ),
    "experiments_candidate_parent_compatibility_generation_attempt_unique_idx": (
        "experiments",
        True,
        (
            "project_id",
            "candidate_digest",
            None,
            "compatibility_digest",
            None,
            None,
            "attempt",
        ),
    ),
    "baselines_project_idx": (
        "baselines",
        False,
        ("project_id", "event_sequence"),
    ),
    "adapter_stages_experiment_idx": (
        "adapter_stages",
        False,
        ("project_id", "experiment_id", "event_sequence"),
    ),
    "artifacts_experiment_idx": (
        "artifacts",
        False,
        ("project_id", "experiment_id", "event_sequence"),
    ),
    "artifacts_digest_idx": ("artifacts", False, ("digest",)),
    "findings_scope_idx": (
        "findings",
        False,
        ("scope", "project_id", "session_id", "event_sequence"),
    ),
    "findings_experiment_idx": (
        "findings",
        False,
        ("experiment_id", "event_sequence"),
    ),
    "projected_events_project_idx": (
        "projected_events",
        False,
        ("project_id", "event_sequence"),
    ),
}

_EXPECTED_AUTO_INDEX_ORIGINS = {
    "sqlite_autoindex_projects_1": "pk",
    "sqlite_autoindex_experiments_1": "pk",
    "sqlite_autoindex_experiments_2": "u",
    "sqlite_autoindex_baselines_1": "pk",
    "sqlite_autoindex_baselines_2": "u",
    "sqlite_autoindex_adapter_stages_1": "pk",
    "sqlite_autoindex_adapter_stages_2": "u",
    "sqlite_autoindex_artifacts_1": "pk",
    "sqlite_autoindex_artifacts_2": "u",
    "sqlite_autoindex_findings_1": "pk",
    "sqlite_autoindex_findings_2": "u",
    "sqlite_autoindex_projected_events_1": "pk",
    "sqlite_autoindex_projected_events_2": "u",
}

_EXPECTED_INDEX_NAMES = frozenset(_REQUIRED_NAMED_INDEXES) | frozenset(
    _EXPECTED_AUTO_INDEX_ORIGINS
)

_REQUIRED_CHECK_MARKERS = {
    "experiments": frozenset(
        {"CHECK(ATTEMPT>=1)", "CHECK(RETRYABLEIN(0,1))"}
    ),
    "findings": frozenset({"CHECK(SCOPEIN('SESSION','PROJECT','GLOBAL'))"}),
    "event_cursor": frozenset({"CHECK(SINGLETON=1)"}),
}

_RECOVERABLE_SQLITE_CODES = frozenset(
    {
        sqlite3.SQLITE_CORRUPT,
        sqlite3.SQLITE_ERROR,
        sqlite3.SQLITE_NOTADB,
        sqlite3.SQLITE_SCHEMA,
    }
)

_SCHEMA_ERROR_MARKERS = (
    "database disk image is malformed",
    "database schema has changed",
    "file is not a database",
    "has no column named",
    "malformed database schema",
    "no such column",
    "no such table",
)

_TYPED_REGISTRATION_KEYS = frozenset(
    {"proposal", "proposal_digest", "proposal_id", "evaluation_scope_id"}
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
_DIAGNOSIS_EVENT_TYPE = "research.experiment_diagnosed.v1"

_T = TypeVar("_T")


class _ProjectionCacheInvalid(IntegrityError):
    """An incompatibility confined to the rebuildable SQLite projection."""


def _normalized_event_type(value: str) -> str:
    return value.strip().upper().replace(".", "_").replace("-", "_")


def _requires_scientific_history(event: Event) -> bool:
    if event.event_type == _DIAGNOSIS_EVENT_TYPE:
        return True
    event_type = _normalized_event_type(event.event_type)
    payload_keys = set(event.payload)
    if event_type == "EXPERIMENT_REGISTERED":
        return bool(payload_keys.intersection(_TYPED_REGISTRATION_KEYS))
    if event_type == "BASELINE_RECORDED":
        return bool(payload_keys.intersection(_TYPED_BASELINE_KEYS))
    return False


def _validate_scientific_history(
    events: Sequence[Event], *, project_id: str
) -> None:
    # Lazy import keeps the lowest-level event/projection package acyclic while
    # still making the canonical reducer the authority for every history-aware
    # projection write.
    from research_os.science.state import reduce_scientific_state

    reduce_scientific_state(events, project_id=project_id)


def _pick(payload: Mapping[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def _text(payload: Mapping[str, Any], *keys: str, required: bool = False) -> str | None:
    value = _pick(payload, *keys)
    if value is None:
        if required:
            raise IntegrityError(f"event payload is missing {keys[0]!r}")
        return None
    try:
        return require_text(value, keys[0])
    except (TypeError, ValueError) as exc:
        raise IntegrityError(str(exc)) from exc


def _attempt(payload: Mapping[str, Any], *, default: int = 1) -> int:
    value = _pick(payload, "attempt", default=default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise IntegrityError("experiment attempt must be a positive integer")
    return value


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


def _terminal_retryable(
    state: LifecycleState, payload: Mapping[str, Any]
) -> bool:
    """Derive retry eligibility from terminal evidence, never from assertion alone."""

    if state in _NON_RETRYABLE_TERMINAL_STATES:
        return False
    if state in {LifecycleState.TIMED_OUT, LifecycleState.CANCELLED}:
        return True
    if (
        state is LifecycleState.INFRA_FAILED
        and payload.get("reason_code") == "RECOVERED_INTERRUPTED_RUN"
    ):
        return True
    error = payload.get("error")
    retryable_adapter_categories = {
        LifecycleState.INFRA_FAILED: "INFRASTRUCTURE",
        LifecycleState.INSUFFICIENT_EVIDENCE: "INSUFFICIENT_EVIDENCE",
    }
    expected_category = retryable_adapter_categories.get(state)
    return (
        expected_category is not None
        and isinstance(error, Mapping)
        and error.get("type") == "AdapterOperationError"
        and error.get("category") == expected_category
        and error.get("code") == payload.get("reason_code")
        and error.get("retryable") is True
    )


def _validated_retryable(
    state: LifecycleState, payload: Mapping[str, Any]
) -> bool:
    derived = _terminal_retryable(state, payload)
    if "retryable" in payload:
        declared = payload["retryable"]
        if not isinstance(declared, bool):
            raise IntegrityError("terminal retryable metadata must be a boolean")
        if declared is not derived:
            raise IntegrityError(
                "terminal retryable metadata conflicts with terminal evidence"
            )
    return derived


class ProjectionStore:
    """SQLite materialization of one project event log.

    The cursor is committed in the same transaction as every projection
    change.  Explicitly namespaced extension events (``vendor.event`` or an
    ``X_``/``EXTENSION_`` type) intentionally only advance the cursor, while an
    unknown unnamespaced core-looking type is rejected as a likely typo.
    """

    def __init__(self, db_path: str | os.PathLike[str]):
        self.path = Path(os.path.abspath(os.fspath(Path(db_path).expanduser())))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise IntegrityError(
                f"projection database must not be a symbolic link: {self.path}"
            )
        with self._cache_maintenance_lock():
            self._secure_database_file()
            try:
                self._initialize()
            except (_ProjectionCacheInvalid, sqlite3.DatabaseError) as exc:
                self._recover_after_failure(
                    "initialize", exc, maintenance_lock_held=True
                )

    @contextmanager
    def _cache_maintenance_lock(self):
        """Serialize schema migration and quarantine across processes."""

        path = self.path.with_name(f".{self.path.name}.maintenance.lock")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = -1
        try:
            descriptor = os.open(path, flags, 0o600)
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
                raise IntegrityError(
                    "projection maintenance lock must be a private regular file"
                )
            os.fchmod(descriptor, 0o600)
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            current = os.fstat(descriptor)
            linked = path.lstat()
            if (
                not stat.S_ISREG(linked.st_mode)
                or linked.st_nlink != 1
                or (linked.st_dev, linked.st_ino) != (current.st_dev, current.st_ino)
                or (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
            ):
                raise IntegrityError(
                    "projection maintenance lock changed while acquiring"
                )
            yield
        except IntegrityError:
            raise
        except OSError as exc:
            raise IntegrityError(
                f"cannot safely lock projection maintenance: {exc}"
            ) from exc
        finally:
            if descriptor >= 0:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)

    @staticmethod
    def _is_recoverable_cache_failure(exc: BaseException) -> bool:
        if isinstance(exc, _ProjectionCacheInvalid):
            return True
        if not isinstance(exc, sqlite3.DatabaseError):
            return False
        error_code = getattr(exc, "sqlite_errorcode", None)
        if isinstance(error_code, int):
            return error_code & 0xFF in _RECOVERABLE_SQLITE_CODES
        message = str(exc).casefold()
        return any(marker in message for marker in _SCHEMA_ERROR_MARKERS)

    def _recover_after_failure(
        self,
        operation: str,
        exc: _ProjectionCacheInvalid | sqlite3.DatabaseError,
        *,
        maintenance_lock_held: bool = False,
    ) -> None:
        """Replace a broken derived cache, or normalize a non-cache failure."""

        if not self._is_recoverable_cache_failure(exc):
            raise IntegrityError(
                f"cannot {operation} projection database: {exc}"
            ) from exc
        if not maintenance_lock_held:
            with self._cache_maintenance_lock():
                self._recover_after_failure(
                    operation,
                    exc,
                    maintenance_lock_held=True,
                )
            return
        self._quarantine_corrupt_database()
        try:
            self._initialize()
        except (_ProjectionCacheInvalid, sqlite3.DatabaseError) as retry_exc:
            raise IntegrityError(
                f"cannot recreate projection database during {operation}: {retry_exc}"
            ) from retry_exc

    def _run_with_recovery(
        self, operation: str, action: Callable[[], _T]
    ) -> _T:
        """Run a projection write, replacing and retrying its cache at most once."""

        with self._cache_maintenance_lock():
            try:
                return action()
            except (_ProjectionCacheInvalid, sqlite3.DatabaseError) as exc:
                self._recover_after_failure(
                    operation,
                    exc,
                    maintenance_lock_held=True,
                )
            try:
                return action()
            except _ProjectionCacheInvalid as retry_exc:
                raise IntegrityError(
                    f"cannot {operation} projection database after recovery: {retry_exc}"
                ) from retry_exc
            except sqlite3.DatabaseError as retry_exc:
                raise IntegrityError(
                    f"cannot {operation} projection database after recovery: {retry_exc}"
                ) from retry_exc

    def _quarantine_corrupt_database(self) -> tuple[Path, ...]:
        """Move corrupt derived SQLite files aside before creating a clean cache."""

        token = secrets.token_hex(8)
        sources: list[Path] = []
        for suffix in ("", "-wal", "-shm"):
            source = Path(f"{self.path}{suffix}")
            try:
                info = source.lstat()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise IntegrityError(
                    f"cannot inspect corrupt projection file: {source}"
                ) from exc
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise IntegrityError(
                    f"corrupt projection path is unsafe to quarantine: {source}"
                )
            sources.append(source)

        moved: list[tuple[Path, Path]] = []
        try:
            for source in sources:
                destination = source.with_name(f"{source.name}.corrupt-{token}")
                os.rename(source, destination)
                moved.append((source, destination))
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            for source, destination in reversed(moved):
                try:
                    os.rename(destination, source)
                except OSError:
                    pass
            raise IntegrityError("cannot quarantine corrupt projection database") from exc
        return tuple(destination for _, destination in moved)

    def _secure_database_file(self) -> tuple[int, int]:
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise IntegrityError(
                f"cannot safely open projection database {self.path}: {exc}"
            ) from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise IntegrityError(
                    f"projection database is not a regular file: {self.path}"
                )
            os.fchmod(descriptor, 0o600)
            return info.st_dev, info.st_ino
        finally:
            os.close(descriptor)

    def _connect(self) -> sqlite3.Connection:
        if self.path.is_symlink():
            raise IntegrityError(
                f"projection database must not be a symbolic link: {self.path}"
            )
        expected_identity = self._secure_database_file()
        connection = sqlite3.connect(self.path, timeout=30.0)
        try:
            # sqlite3.connect() reopens by pathname and Python does not expose
            # SQLITE_OPEN_NOFOLLOW.  Validate the directory entry again before
            # issuing any pragma or SQL that can write through the connection.
            # A swap in the open gap therefore fails closed instead of turning
            # a disposable projection into an arbitrary-path write primitive.
            after = self.path.lstat()
            if (
                stat.S_ISLNK(after.st_mode)
                or not stat.S_ISREG(after.st_mode)
                or (after.st_dev, after.st_ino) != expected_identity
            ):
                raise IntegrityError(
                    "projection database changed while opening the SQLite connection"
                )
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 30000")
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = FULL")
            return connection
        except BaseException:
            connection.close()
            raise

    def _initialize(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    initialized_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_sequence INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS experiments (
                    experiment_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    generation_id TEXT,
                    evaluation_scope_id TEXT,
                    parent_id TEXT,
                    candidate_digest TEXT NOT NULL,
                    compatibility_digest TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 1 CHECK(attempt >= 1),
                    retry_of TEXT,
                    retryable INTEGER NOT NULL DEFAULT 0 CHECK(retryable IN (0, 1)),
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    registered_at TEXT NOT NULL,
                    terminated_at TEXT,
                    created_sequence INTEGER NOT NULL UNIQUE,
                    updated_sequence INTEGER NOT NULL,
                    FOREIGN KEY(project_id) REFERENCES projects(project_id),
                    FOREIGN KEY(parent_id) REFERENCES experiments(experiment_id),
                    FOREIGN KEY(retry_of) REFERENCES experiments(experiment_id)
                );

                CREATE INDEX IF NOT EXISTS experiments_project_status_idx
                    ON experiments(project_id, status, created_sequence);
                CREATE INDEX IF NOT EXISTS experiments_parent_idx
                    ON experiments(project_id, parent_id);

                CREATE TABLE IF NOT EXISTS baselines (
                    baseline_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    experiment_id TEXT,
                    digest TEXT NOT NULL,
                    metrics_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    event_sequence INTEGER NOT NULL UNIQUE,
                    FOREIGN KEY(project_id) REFERENCES projects(project_id),
                    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
                );
                CREATE INDEX IF NOT EXISTS baselines_project_idx
                    ON baselines(project_id, event_sequence);

                CREATE TABLE IF NOT EXISTS adapter_stages (
                    stage_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    experiment_id TEXT NOT NULL,
                    stage_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    input_digest TEXT,
                    output_digest TEXT,
                    payload_json TEXT NOT NULL,
                    completed_at TEXT NOT NULL,
                    event_sequence INTEGER NOT NULL UNIQUE,
                    FOREIGN KEY(project_id) REFERENCES projects(project_id),
                    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
                );
                CREATE INDEX IF NOT EXISTS adapter_stages_experiment_idx
                    ON adapter_stages(project_id, experiment_id, event_sequence);

                CREATE TABLE IF NOT EXISTS artifacts (
                    artifact_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    experiment_id TEXT,
                    digest TEXT NOT NULL,
                    algorithm TEXT NOT NULL,
                    relative_path TEXT,
                    storage_path TEXT,
                    role TEXT,
                    media_type TEXT,
                    size INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    event_sequence INTEGER NOT NULL UNIQUE,
                    FOREIGN KEY(project_id) REFERENCES projects(project_id),
                    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
                );
                CREATE INDEX IF NOT EXISTS artifacts_experiment_idx
                    ON artifacts(project_id, experiment_id, event_sequence);
                CREATE INDEX IF NOT EXISTS artifacts_digest_idx
                    ON artifacts(digest);

                CREATE TABLE IF NOT EXISTS findings (
                    finding_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL CHECK(scope IN ('session', 'project', 'global')),
                    project_id TEXT,
                    origin_project_id TEXT NOT NULL,
                    session_id TEXT,
                    experiment_id TEXT,
                    finding_key TEXT,
                    content_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    event_sequence INTEGER NOT NULL UNIQUE,
                    FOREIGN KEY(origin_project_id) REFERENCES projects(project_id),
                    FOREIGN KEY(experiment_id) REFERENCES experiments(experiment_id)
                );
                CREATE INDEX IF NOT EXISTS findings_scope_idx
                    ON findings(scope, project_id, session_id, event_sequence);
                CREATE INDEX IF NOT EXISTS findings_experiment_idx
                    ON findings(experiment_id, event_sequence);

                CREATE TABLE IF NOT EXISTS event_cursor (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    project_id TEXT,
                    last_sequence INTEGER NOT NULL,
                    last_hash TEXT
                );
                INSERT OR IGNORE INTO event_cursor(singleton, project_id, last_sequence, last_hash)
                    VALUES (1, NULL, 0, NULL);

                CREATE TABLE IF NOT EXISTS projected_events (
                    event_id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    event_sequence INTEGER NOT NULL UNIQUE,
                    event_hash TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS projected_events_project_idx
                    ON projected_events(project_id, event_sequence);
                """
            )
            # ``executescript`` commits its bootstrap statements independently.
            # Hold one writer transaction across every additive migration and
            # index replacement so readers never observe a half-migrated cache.
            connection.execute("BEGIN IMMEDIATE")
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(experiments)"
                ).fetchall()
            }
            if "generation_id" not in columns:
                connection.execute(
                    "ALTER TABLE experiments ADD COLUMN generation_id TEXT"
                )
                rows = connection.execute(
                    "SELECT experiment_id, payload_json FROM experiments"
                ).fetchall()
                for row in rows:
                    try:
                        payload = strict_json_loads(row["payload_json"])
                    except (TypeError, ValueError) as exc:
                        raise _ProjectionCacheInvalid(
                            f"cannot migrate experiment {row['experiment_id']!r}: {exc}"
                        ) from exc
                    generation_id = (
                        payload.get("generation_id")
                        if isinstance(payload, dict)
                        else None
                    )
                    if generation_id is None:
                        continue
                    try:
                        generation_id = require_text(
                            generation_id, "generation_id"
                        )
                    except (TypeError, ValueError) as exc:
                        raise _ProjectionCacheInvalid(
                            f"cannot migrate experiment {row['experiment_id']!r}: {exc}"
                        ) from exc
                    connection.execute(
                        "UPDATE experiments SET generation_id = ? "
                        "WHERE experiment_id = ?",
                        (generation_id, row["experiment_id"]),
                    )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(experiments)"
                ).fetchall()
            }
            if "compatibility_digest" not in columns:
                connection.execute(
                    "ALTER TABLE experiments ADD COLUMN compatibility_digest "
                    "TEXT NOT NULL DEFAULT ''"
                )
                rows = connection.execute(
                    "SELECT experiment_id, payload_json FROM experiments"
                ).fetchall()
                for row in rows:
                    try:
                        payload = strict_json_loads(row["payload_json"])
                    except (TypeError, ValueError) as exc:
                        raise _ProjectionCacheInvalid(
                            f"cannot migrate experiment {row['experiment_id']!r}: {exc}"
                        ) from exc
                    compatibility = (
                        payload.get("compatibility_digest", "")
                        if isinstance(payload, dict)
                        else ""
                    )
                    if not isinstance(compatibility, str):
                        compatibility = ""
                    connection.execute(
                        "UPDATE experiments SET compatibility_digest = ? "
                        "WHERE experiment_id = ?",
                        (compatibility, row["experiment_id"]),
                    )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(experiments)"
                ).fetchall()
            }
            if "evaluation_scope_id" not in columns:
                connection.execute(
                    "ALTER TABLE experiments ADD COLUMN evaluation_scope_id TEXT"
                )
                rows = connection.execute(
                    "SELECT experiment_id, payload_json FROM experiments"
                ).fetchall()
                for row in rows:
                    try:
                        payload = strict_json_loads(row["payload_json"])
                    except (TypeError, ValueError) as exc:
                        raise _ProjectionCacheInvalid(
                            f"cannot migrate experiment {row['experiment_id']!r}: {exc}"
                        ) from exc
                    evaluation_scope_id = (
                        payload.get("evaluation_scope_id")
                        if isinstance(payload, dict)
                        else None
                    )
                    if evaluation_scope_id is None:
                        continue
                    try:
                        normalized_scope_id = require_text(
                            evaluation_scope_id, "evaluation_scope_id"
                        )
                        if normalized_scope_id != evaluation_scope_id:
                            raise ValueError(
                                "evaluation_scope_id must already be trimmed"
                            )
                    except (TypeError, ValueError) as exc:
                        raise _ProjectionCacheInvalid(
                            f"cannot migrate experiment {row['experiment_id']!r}: {exc}"
                        ) from exc
                    connection.execute(
                        "UPDATE experiments SET evaluation_scope_id = ? "
                        "WHERE experiment_id = ?",
                        (normalized_scope_id, row["experiment_id"]),
                    )
            columns = {
                row["name"]
                for row in connection.execute(
                    "PRAGMA table_info(experiments)"
                ).fetchall()
            }
            legacy_retry_schema = not {"attempt", "retry_of", "retryable"}.issubset(
                columns
            )
            if "attempt" not in columns:
                connection.execute(
                    "ALTER TABLE experiments ADD COLUMN attempt "
                    "INTEGER NOT NULL DEFAULT 1"
                )
            if "retry_of" not in columns:
                connection.execute(
                    "ALTER TABLE experiments ADD COLUMN retry_of TEXT"
                )
            if "retryable" not in columns:
                connection.execute(
                    "ALTER TABLE experiments ADD COLUMN retryable "
                    "INTEGER NOT NULL DEFAULT 0"
                )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS experiments_retry_idx "
                "ON experiments(project_id, retry_of)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS experiments_scope_idx "
                "ON experiments(project_id, evaluation_scope_id, created_sequence)"
            )
            connection.execute("DROP INDEX IF EXISTS experiments_candidate_idx")
            connection.execute(
                "CREATE INDEX experiments_candidate_idx "
                "ON experiments(project_id, generation_id, evaluation_scope_id, "
                "candidate_digest, parent_id)"
            )

            # A pre-retry projection could only contain the first attempt because
            # its candidate identity index was unique without an attempt number.
            # Preserve those rows as attempt 1 and recover retry eligibility from
            # their already-projected terminal evidence.
            if legacy_retry_schema:
                legacy_rows = connection.execute(
                    "SELECT experiment_id, status, payload_json FROM experiments"
                ).fetchall()
                for row in legacy_rows:
                    try:
                        payload = strict_json_loads(row["payload_json"])
                        state = coerce_state(row["status"])
                    except (TypeError, ValueError, LifecycleError) as exc:
                        raise _ProjectionCacheInvalid(
                            f"cannot migrate experiment {row['experiment_id']!r}: {exc}"
                        ) from exc
                    if not isinstance(payload, dict):
                        raise _ProjectionCacheInvalid(
                            f"cannot migrate experiment {row['experiment_id']!r}: "
                            "payload is not an object"
                        )
                    outcome = payload.get("outcome")
                    if not isinstance(outcome, Mapping):
                        outcome = payload.get("latest_transition")
                    if not isinstance(outcome, Mapping):
                        outcome = {}
                    retryable = (
                        _terminal_retryable(state, outcome)
                        if state in TERMINAL_STATES
                        else False
                    )
                    connection.execute(
                        "UPDATE experiments SET attempt = 1, retry_of = NULL, "
                        "retryable = ? WHERE experiment_id = ?",
                        (int(retryable), row["experiment_id"]),
                    )
            connection.execute(
                "DROP INDEX IF EXISTS experiments_candidate_parent_unique_idx"
            )
            connection.execute(
                "DROP INDEX IF EXISTS "
                "experiments_candidate_parent_compatibility_unique_idx"
            )
            connection.execute(
                "DROP INDEX IF EXISTS "
                "experiments_candidate_parent_compatibility_attempt_unique_idx"
            )
            connection.execute(
                "DROP INDEX IF EXISTS "
                "experiments_candidate_parent_compatibility_generation_attempt_unique_idx"
            )
            connection.execute(
                "CREATE UNIQUE INDEX "
                "experiments_candidate_parent_compatibility_generation_attempt_unique_idx "
                "ON experiments(project_id, candidate_digest, COALESCE(parent_id, ''), "
                "compatibility_digest, COALESCE(generation_id, ''), "
                "COALESCE(evaluation_scope_id, ''), attempt)"
            )
            self._validate_schema(
                connection,
                allow_legacy_experiments=legacy_retry_schema,
            )

    @staticmethod
    def _validate_schema(
        connection: sqlite3.Connection,
        *,
        allow_legacy_experiments: bool = False,
    ) -> None:
        """Reject a valid SQLite file that lacks projection invariants."""

        schema_objects = connection.execute(
            "SELECT type, name FROM sqlite_master "
            "WHERE type IN ('table', 'index', 'view', 'trigger')"
        ).fetchall()
        actual_tables = {
            str(row["name"])
            for row in schema_objects
            if row["type"] == "table" and not str(row["name"]).startswith("sqlite_")
        }
        if actual_tables != set(_REQUIRED_SCHEMA_COLUMNS):
            raise _ProjectionCacheInvalid(
                "projection database has an unexpected table set"
            )
        actual_indexes = {
            str(row["name"])
            for row in schema_objects
            if row["type"] == "index"
        }
        if actual_indexes != _EXPECTED_INDEX_NAMES:
            raise _ProjectionCacheInvalid(
                "projection database has an unexpected index set"
            )
        active_objects = sorted(
            (str(row["type"]), str(row["name"]))
            for row in schema_objects
            if row["type"] in {"view", "trigger"}
        )
        if active_objects:
            raise _ProjectionCacheInvalid(
                f"projection database has unexpected active schema objects: {active_objects}"
            )

        for table, required_columns in _REQUIRED_SCHEMA_COLUMNS.items():
            rows = connection.execute(f"PRAGMA table_xinfo('{table}')").fetchall()
            hidden_columns = sorted(
                str(row["name"]) for row in rows if int(row["hidden"]) != 0
            )
            if hidden_columns:
                raise _ProjectionCacheInvalid(
                    f"projection table {table!r} has hidden/generated columns: "
                    f"{hidden_columns}"
                )
            actual_columns = {str(row["name"]) for row in rows}
            missing = sorted(required_columns - actual_columns)
            unexpected = sorted(actual_columns - required_columns)
            if missing or unexpected:
                raise _ProjectionCacheInvalid(
                    f"projection table {table!r} has incompatible columns "
                    f"(missing={missing}, unexpected={unexpected})"
                )
            wrong_types = sorted(
                str(row["name"])
                for row in rows
                if str(row["type"]).upper()
                != (
                    "INTEGER"
                    if (table, str(row["name"])) in _INTEGER_SCHEMA_COLUMNS
                    else "TEXT"
                )
            )
            if wrong_types:
                raise _ProjectionCacheInvalid(
                    f"projection table {table!r} has incompatible column types: "
                    f"{wrong_types}"
                )
            actual_defaults = {
                str(row["name"]): str(row["dflt_value"])
                for row in rows
                if row["dflt_value"] is not None
            }
            expected_defaults = {"attempt": "1", "retryable": "0"}
            if table != "experiments":
                expected_defaults = {}
            if not (allow_legacy_experiments and table == "experiments") and (
                actual_defaults != expected_defaults
            ):
                raise _ProjectionCacheInvalid(
                    f"projection table {table!r} has incompatible defaults"
                )
            actual_not_null = {
                str(row["name"]) for row in rows if bool(row["notnull"])
            }
            if actual_not_null != _REQUIRED_NOT_NULL_COLUMNS[table]:
                raise _ProjectionCacheInvalid(
                    f"projection table {table!r} has incompatible NOT NULL constraints"
                )
            primary_key = tuple(
                str(row["name"])
                for row in sorted(rows, key=lambda item: int(item["pk"]))
                if int(row["pk"]) > 0
            )
            if primary_key != _PRIMARY_KEY_COLUMNS[table]:
                raise _ProjectionCacheInvalid(
                    f"projection table {table!r} has an incompatible primary key"
                )

            indexes = connection.execute(f"PRAGMA index_list('{table}')").fetchall()
            unique_keys: set[tuple[str | None, ...]] = set()
            for index in indexes:
                index_rows = connection.execute(
                    f"PRAGMA index_xinfo('{index['name']}')"
                ).fetchall()
                key_rows = [item for item in index_rows if bool(item["key"])]
                if any(
                    bool(item["desc"]) or str(item["coll"]).upper() != "BINARY"
                    for item in key_rows
                ):
                    raise _ProjectionCacheInvalid(
                        f"projection index {index['name']!r} has incompatible ordering"
                    )
                if bool(index["unique"]):
                    unique_keys.add(
                        tuple(
                            None if item["name"] is None else str(item["name"])
                            for item in key_rows
                        )
                    )
            required_unique = _REQUIRED_UNIQUE_COLUMN_KEYS.get(table, frozenset())
            expected_unique = set(required_unique)
            if table != "event_cursor":
                expected_unique.add(_PRIMARY_KEY_COLUMNS[table])
            expected_unique.update(
                columns
                for index_table, unique, columns in _REQUIRED_NAMED_INDEXES.values()
                if index_table == table and unique
            )
            if unique_keys != expected_unique:
                raise _ProjectionCacheInvalid(
                    f"projection table {table!r} has incompatible UNIQUE keys"
                )

            expected_foreign_keys = _REQUIRED_FOREIGN_KEYS.get(table, frozenset())
            actual_foreign_keys = frozenset(
                (str(row["from"]), str(row["table"]), str(row["to"]))
                for row in connection.execute(
                    f"PRAGMA foreign_key_list('{table}')"
                ).fetchall()
            )
            if not (allow_legacy_experiments and table == "experiments") and (
                actual_foreign_keys != expected_foreign_keys
            ):
                raise _ProjectionCacheInvalid(
                    f"projection table {table!r} has incompatible foreign keys"
                )

            schema_row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if schema_row is None or not isinstance(schema_row["sql"], str):
                raise _ProjectionCacheInvalid(
                    f"projection table {table!r} has no canonical schema definition"
                )
            normalized_sql = "".join(schema_row["sql"].upper().split())
            required_checks = _REQUIRED_CHECK_MARKERS.get(table, frozenset())
            if allow_legacy_experiments and table == "experiments":
                required_checks = frozenset()
            if not all(marker in normalized_sql for marker in required_checks):
                raise _ProjectionCacheInvalid(
                    f"projection table {table!r} is missing a required CHECK constraint"
                )
            if normalized_sql.count("CHECK(") != len(required_checks):
                raise _ProjectionCacheInvalid(
                    f"projection table {table!r} has an unexpected CHECK constraint"
                )
            if "ONCONFLICT" in normalized_sql or "COLLATE" in normalized_sql:
                raise _ProjectionCacheInvalid(
                    f"projection table {table!r} has unsupported constraint semantics"
                )

        for index_name, (table, unique, required_columns) in (
            _REQUIRED_NAMED_INDEXES.items()
        ):
            index = connection.execute(
                "SELECT tbl_name, sql FROM sqlite_master "
                "WHERE type = 'index' AND name = ?",
                (index_name,),
            ).fetchone()
            if index is None or index["tbl_name"] != table:
                raise _ProjectionCacheInvalid(
                    f"projection index {index_name!r} is missing or attached incorrectly"
                )
            index_list = {
                row["name"]: row
                for row in connection.execute(
                    f"PRAGMA index_list('{table}')"
                ).fetchall()
            }
            index_metadata = index_list.get(index_name)
            if (
                index_metadata is None
                or bool(index_metadata["unique"]) is not unique
                or bool(index_metadata["partial"])
            ):
                raise _ProjectionCacheInvalid(
                    f"projection index {index_name!r} has incompatible semantics"
                )
            index_columns = tuple(
                None if row["name"] is None else str(row["name"])
                for row in connection.execute(
                    f"PRAGMA index_xinfo('{index_name}')"
                ).fetchall()
                if bool(row["key"])
            )
            if index_columns != required_columns:
                raise _ProjectionCacheInvalid(
                    f"projection index {index_name!r} has incompatible columns"
                )

        for index_name, expected_origin in _EXPECTED_AUTO_INDEX_ORIGINS.items():
            table_name = index_name.removeprefix("sqlite_autoindex_").rsplit("_", 1)[0]
            index_metadata = {
                row["name"]: row
                for row in connection.execute(
                    f"PRAGMA index_list('{table_name}')"
                ).fetchall()
            }.get(index_name)
            if (
                index_metadata is None
                or index_metadata["origin"] != expected_origin
                or not bool(index_metadata["unique"])
                or bool(index_metadata["partial"])
            ):
                raise _ProjectionCacheInvalid(
                    f"projection implicit index {index_name!r} is incompatible"
                )

        candidate_index = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            (
                "experiments_candidate_parent_compatibility_generation_attempt_unique_idx",
            ),
        ).fetchone()
        candidate_sql = (
            ""
            if candidate_index is None or not isinstance(candidate_index["sql"], str)
            else "".join(candidate_index["sql"].upper().split())
        )
        expected_candidate_sql = (
            "CREATEUNIQUEINDEXEXPERIMENTS_CANDIDATE_PARENT_COMPATIBILITY_GENERATION_"
            "ATTEMPT_"
            "UNIQUE_IDXONEXPERIMENTS(PROJECT_ID,CANDIDATE_DIGEST,"
            "COALESCE(PARENT_ID,''),COMPATIBILITY_DIGEST,"
            "COALESCE(GENERATION_ID,''),COALESCE(EVALUATION_SCOPE_ID,''),ATTEMPT)"
        )
        if candidate_sql != expected_candidate_sql:
            raise _ProjectionCacheInvalid(
                "projection candidate identity index has an incompatible expression"
            )

        cursor_rows = connection.execute(
            "SELECT singleton FROM event_cursor"
        ).fetchall()
        if len(cursor_rows) != 1 or cursor_rows[0]["singleton"] != 1:
            raise _ProjectionCacheInvalid(
                "projection event cursor singleton is logically invalid"
            )

    def _reset(self, connection: sqlite3.Connection) -> None:
        # Child tables precede their parents so this also works with FK checks on.
        for table in (
            "adapter_stages",
            "artifacts",
            "findings",
            "baselines",
            "experiments",
            "projects",
            "projected_events",
        ):
            connection.execute(f"DELETE FROM {table}")
        connection.execute(
            "UPDATE event_cursor SET project_id = NULL, last_sequence = 0, last_hash = NULL "
            "WHERE singleton = 1"
        )

    @staticmethod
    def _cursor(connection: sqlite3.Connection) -> sqlite3.Row:
        row = connection.execute(
            "SELECT project_id, last_sequence, last_hash FROM event_cursor WHERE singleton = 1"
        ).fetchone()
        if row is None:
            raise IntegrityError("projection event cursor is missing")
        return row

    def _check_cursor(self, connection: sqlite3.Connection, event: Event) -> None:
        cursor = self._cursor(connection)
        expected_sequence = int(cursor["last_sequence"]) + 1
        if event.sequence != expected_sequence:
            raise IntegrityError(
                f"projection expected event sequence {expected_sequence}, found {event.sequence}"
            )
        if event.prev_hash != cursor["last_hash"]:
            raise IntegrityError(
                f"projection cursor hash does not match event {event.sequence} prev_hash"
            )
        cursor_project = cursor["project_id"]
        if cursor_project is not None and cursor_project != event.project_id:
            raise IntegrityError(
                f"projection belongs to {cursor_project!r}, not {event.project_id!r}"
            )

    @staticmethod
    def _advance_cursor(connection: sqlite3.Connection, event: Event) -> None:
        connection.execute(
            "UPDATE event_cursor SET project_id = ?, last_sequence = ?, last_hash = ? "
            "WHERE singleton = 1",
            (event.project_id, event.sequence, event.hash),
        )

    @staticmethod
    def _verify_or_backfill_event_ids(
        connection: sqlite3.Connection, events: list[Event], position: int
    ) -> None:
        """Verify the durable event-ID index, backfilling legacy projections."""

        rows = connection.execute(
            "SELECT event_id, project_id, event_sequence, event_hash "
            "FROM projected_events ORDER BY event_sequence"
        ).fetchall()
        if not rows and position:
            # Databases created before ``projected_events`` existed have a
            # trustworthy cursor but no event identity index.  The canonical
            # stream is already fully verified by EventLog, so it is safe to
            # populate the missing prefix transactionally.
            for event in events[:position]:
                connection.execute(
                    "INSERT INTO projected_events "
                    "(event_id, project_id, event_sequence, event_hash) "
                    "VALUES (?, ?, ?, ?)",
                    (event.event_id, event.project_id, event.sequence, event.hash),
                )
            return
        if len(rows) != position:
            raise IntegrityError(
                "projection event identity index does not match its cursor"
            )
        for row, event in zip(rows, events[:position], strict=True):
            if (
                row["event_id"] != event.event_id
                or row["project_id"] != event.project_id
                or row["event_sequence"] != event.sequence
                or row["event_hash"] != event.hash
            ):
                raise IntegrityError(
                    "projection event identity index does not match the canonical log"
                )

    def rebuild(self, event_log: EventLog) -> int:
        return self._run_with_recovery(
            "rebuild", lambda: self._rebuild_once(event_log)
        )

    def _rebuild_once(self, event_log: EventLog) -> int:
        # Acquire the SQLite writer lock before taking the log snapshot.  This
        # serializes rebuild against direct apply/sync writers; retaining the
        # shared log lock through commit also blocks concurrent appenders.
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._validate_schema(connection)
                with event_log.locked_read() as events:
                    _validate_scientific_history(
                        events, project_id=event_log.project_id
                    )
                    self._reset(connection)
                    for event in events:
                        self._apply_one(connection, event)
                    connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return len(events)

    def sync(self, event_log: EventLog) -> int:
        return self._run_with_recovery("sync", lambda: self._sync_once(event_log))

    def _sync_once(self, event_log: EventLog) -> int:
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._validate_schema(connection)
                with event_log.locked_read() as events:
                    _validate_scientific_history(
                        events, project_id=event_log.project_id
                    )
                    cursor = self._cursor(connection)
                    position = int(cursor["last_sequence"])
                    if position > len(events):
                        raise IntegrityError(
                            "projection cursor is ahead of the canonical event log"
                        )
                    if position:
                        canonical_head = events[position - 1]
                        if canonical_head.hash != cursor["last_hash"]:
                            raise IntegrityError(
                                "projection cursor does not match the canonical event log"
                            )
                        if canonical_head.project_id != cursor["project_id"]:
                            raise IntegrityError(
                                "projection project does not match the canonical event log"
                            )
                    self._verify_or_backfill_event_ids(connection, events, position)
                    pending = events[position:]
                    for event in pending:
                        self._apply_one(connection, event)
                    connection.commit()
            except BaseException:
                connection.rollback()
                raise
        return len(pending)

    def apply(self, event: Event | Mapping[str, Any]) -> bool:
        normalized = event if isinstance(event, Event) else Event.from_mapping(event)
        # Re-hash Event instances too; frozen attributes are not a trust boundary for
        # mutable payload values.
        normalized = Event.from_mapping(normalized.to_dict())
        if _requires_scientific_history(normalized):
            raise IntegrityError(
                "typed scientific events require canonical history; use sync or rebuild"
            )
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = self._cursor(connection)
            indexed = connection.execute(
                "SELECT COUNT(*) FROM projected_events"
            ).fetchone()[0]
            if indexed != cursor["last_sequence"]:
                raise IntegrityError(
                    "projection event identity index is incomplete; sync or rebuild first"
                )
            self._apply_one(connection, normalized)
        return True

    def _apply_one(self, connection: sqlite3.Connection, event: Event) -> None:
        reused = connection.execute(
            "SELECT event_sequence FROM projected_events WHERE event_id = ?",
            (event.event_id,),
        ).fetchone()
        if reused is not None:
            raise IntegrityError(
                f"event ID {event.event_id!r} was already projected at sequence "
                f"{reused['event_sequence']}"
            )
        self._check_cursor(connection, event)
        event_type = _normalized_event_type(event.event_type)
        is_extension = (
            "." in event.event_type
            or event_type.startswith("X_")
            or event_type.startswith("EXTENSION_")
        )
        if event_type not in _SUPPORTED_EVENT_TYPES and not is_extension:
            raise IntegrityError(
                f"unknown unnamespaced event type at sequence {event.sequence}: "
                f"{event.event_type!r}"
            )
        if event.sequence == 1 and event_type != "PROJECT_INITIALIZED":
            raise IntegrityError(
                "the first projected event must initialize the project"
            )
        try:
            if event_type == "PROJECT_INITIALIZED":
                self._project_initialized(connection, event)
            elif event_type == "BASELINE_RECORDED":
                self._baseline_recorded(connection, event)
            elif event_type == "EXPERIMENT_REGISTERED":
                self._experiment_registered(connection, event)
            elif event_type in {"STAGE_COMPLETED", "ADAPTER_STAGE_RECORDED"}:
                self._stage_completed(connection, event)
            elif event_type in {
                "ARTIFACT_RECORDED",
                "ARTIFACT_CAPTURED",
                "ARTIFACT_CATALOGUED",
            }:
                self._artifact_recorded(connection, event)
            elif event_type == "FINDING_RECORDED":
                self._finding_recorded(connection, event)
            elif event_type == "EXPERIMENT_TERMINATED":
                self._experiment_terminated(connection, event)
            elif event_type == "EXPERIMENT_STATUS_CHANGED":
                self._experiment_status_changed(connection, event)
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(
                f"event {event.sequence} violates projection integrity: {exc}"
            ) from exc
        # Namespaced extension events are canonical history that this projection
        # simply does not understand yet. Advancing the cursor is intentional;
        # adding a projection for one later requires a full rebuild.
        connection.execute(
            "INSERT INTO projected_events "
            "(event_id, project_id, event_sequence, event_hash) VALUES (?, ?, ?, ?)",
            (event.event_id, event.project_id, event.sequence, event.hash),
        )
        self._advance_cursor(connection, event)

    @staticmethod
    def _ensure_project(connection: sqlite3.Connection, event: Event) -> None:
        updated = connection.execute(
            "UPDATE projects SET updated_at = ?, last_sequence = ? WHERE project_id = ?",
            (event.occurred_at, event.sequence, event.project_id),
        )
        if updated.rowcount != 1:
            raise IntegrityError(
                f"project {event.project_id!r} must be initialized before domain events"
            )

    def _project_initialized(
        self, connection: sqlite3.Connection, event: Event
    ) -> None:
        payload_project = _text(event.payload, "project_id")
        if payload_project is not None and payload_project != event.project_id:
            raise IntegrityError(
                "PROJECT_INITIALIZED payload project_id mismatches its event"
            )
        existing = connection.execute(
            "SELECT 1 FROM projects WHERE project_id = ?", (event.project_id,)
        ).fetchone()
        if existing is not None:
            raise IntegrityError(
                f"project initialized more than once: {event.project_id}"
            )
        status = _text(event.payload, "status") or "active"
        metadata = _pick(event.payload, "metadata", default=event.payload)
        connection.execute(
            "INSERT INTO projects "
            "(project_id, status, metadata_json, initialized_at, updated_at, last_sequence) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                event.project_id,
                status,
                canonical_json(metadata),
                event.occurred_at,
                event.occurred_at,
                event.sequence,
            ),
        )

    def _baseline_recorded(self, connection: sqlite3.Connection, event: Event) -> None:
        self._ensure_project(connection, event)
        experiment_id = _text(event.payload, "experiment_id")
        if experiment_id is not None:
            self._require_experiment(connection, event.project_id, experiment_id)
        digest = _text(
            event.payload, "digest", "baseline_digest", "provenance_digest"
        ) or sha256_hex(canonical_bytes(event.payload))
        baseline_id = _text(event.payload, "baseline_id", "id") or stable_id(
            "baseline", event.project_id, digest, event.sequence
        )
        metrics = _pick(event.payload, "metrics", default={})
        connection.execute(
            "INSERT INTO baselines "
            "(baseline_id, project_id, experiment_id, digest, metrics_json, payload_json, "
            "recorded_at, event_sequence) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                baseline_id,
                event.project_id,
                experiment_id,
                digest,
                canonical_json(metrics),
                canonical_json(event.payload),
                event.occurred_at,
                event.sequence,
            ),
        )

    def _experiment_registered(
        self, connection: sqlite3.Connection, event: Event
    ) -> None:
        self._ensure_project(connection, event)
        experiment_id = _text(event.payload, "experiment_id", "id", required=True)
        assert experiment_id is not None
        generation_id = _text(event.payload, "generation_id")
        evaluation_scope_id = _text(event.payload, "evaluation_scope_id")
        parent_id = _text(event.payload, "parent_id", "parent_experiment_id")
        digest = _text(event.payload, "candidate_digest", "digest", required=True)
        assert digest is not None
        compatibility_digest = _text(event.payload, "compatibility_digest") or ""
        attempt = _attempt(event.payload)
        retry_of = _text(event.payload, "retry_of")
        try:
            graph_metadata = graph_metadata_from_payload(event.payload)
            if graph_metadata is not None and not compatibility_digest:
                raise GraphPolicyError(
                    "versioned graph metadata requires compatibility_digest"
                )
            # Check the action/parent shape before resolving the parent so an
            # explore declaration cannot disguise itself behind an arbitrary
            # missing parent identifier.
            validate_graph_relationship(graph_metadata, parent_id)
        except GraphPolicyError as exc:
            raise IntegrityError(
                f"invalid experiment graph metadata: {exc}"
            ) from exc
        if parent_id == experiment_id:
            raise IntegrityError("an experiment cannot be its own parent")
        parent: sqlite3.Row | None = None
        if parent_id is not None:
            parent = self._require_experiment(
                connection, event.project_id, parent_id
            )
            if parent["generation_id"] != generation_id:
                raise IntegrityError(
                    "parent_id must reference an experiment in the same generation"
                )
            self._check_no_cycle(connection, event.project_id, experiment_id, parent_id)
        if graph_metadata is not None and parent is not None:
            try:
                parent_state = coerce_state(parent["status"])
                validate_graph_relationship(
                    graph_metadata,
                    parent_id,
                    parent_is_terminal=(
                        parent_state in TERMINAL_STATES
                        and parent["terminated_at"] is not None
                    ),
                    compatibility_digest=compatibility_digest,
                    parent_compatibility_digest=parent["compatibility_digest"],
                )
                validate_graph_candidate_change(
                    graph_metadata,
                    candidate_digest=digest,
                    parent_candidate_digest=parent["candidate_digest"],
                )
            except (GraphPolicyError, LifecycleError) as exc:
                raise IntegrityError(
                    f"invalid experiment graph parent: {exc}"
                ) from exc

        if attempt == 1:
            if retry_of is not None:
                raise IntegrityError("the first attempt cannot declare retry_of")
            if evaluation_scope_id is not None:
                reused_scope = connection.execute(
                    "SELECT experiment_id FROM experiments "
                    "WHERE project_id = ? AND candidate_digest = ? "
                    "AND ((generation_id = ?) OR "
                    "(generation_id IS NULL AND ? IS NULL)) "
                    "AND evaluation_scope_id = ? AND attempt = 1 LIMIT 1",
                    (
                        event.project_id,
                        digest,
                        generation_id,
                        generation_id,
                        evaluation_scope_id,
                    ),
                ).fetchone()
                if reused_scope is not None:
                    raise IntegrityError(
                        "candidate and evaluation scope were already used "
                        "in this generation"
                    )
        else:
            if retry_of is None:
                raise IntegrityError("a retry attempt must declare retry_of")
            if retry_of == experiment_id:
                raise IntegrityError("an experiment cannot retry itself")
            prior = self._require_experiment(
                connection, event.project_id, retry_of
            )
            if (
                prior["candidate_digest"] != digest
                or prior["parent_id"] != parent_id
                or prior["compatibility_digest"] != compatibility_digest
                or prior["generation_id"] != generation_id
                or prior["evaluation_scope_id"] != evaluation_scope_id
            ):
                raise IntegrityError(
                    "retry_of must reference the same candidate, parent, compatibility, "
                    "generation, and evaluation scope"
                )
            if int(prior["attempt"]) != attempt - 1:
                raise IntegrityError("retry attempts must be contiguous")
            latest = connection.execute(
                "SELECT experiment_id, attempt FROM experiments "
                "WHERE project_id = ? AND candidate_digest = ? "
                "AND ((parent_id = ?) OR (parent_id IS NULL AND ? IS NULL)) "
                "AND compatibility_digest = ? "
                "AND ((generation_id = ?) OR (generation_id IS NULL AND ? IS NULL)) "
                "AND ((evaluation_scope_id = ?) OR "
                "(evaluation_scope_id IS NULL AND ? IS NULL)) "
                "ORDER BY attempt DESC LIMIT 1",
                (
                    event.project_id,
                    digest,
                    parent_id,
                    parent_id,
                    compatibility_digest,
                    generation_id,
                    generation_id,
                    evaluation_scope_id,
                    evaluation_scope_id,
                ),
            ).fetchone()
            if latest is None or latest["experiment_id"] != retry_of:
                raise IntegrityError("retry_of must reference the most recent attempt")
            if prior["terminated_at"] is None or not bool(prior["retryable"]):
                raise IntegrityError(
                    "retry_of must reference a terminal retryable attempt"
                )
            try:
                prior_payload = strict_json_loads(prior["payload_json"])
            except (TypeError, ValueError) as exc:
                raise IntegrityError(
                    "retry_of registration payload is corrupt"
                ) from exc
            if not isinstance(prior_payload, Mapping):
                raise IntegrityError("retry_of registration payload is not an object")
            try:
                prior_graph_metadata = graph_metadata_from_payload(
                    cast(Mapping[str, Any], prior_payload)
                )
                validate_retry_graph_metadata(
                    graph_metadata, prior_graph_metadata
                )
            except GraphPolicyError as exc:
                raise IntegrityError(
                    f"invalid retry graph metadata: {exc}"
                ) from exc
        state_value = _pick(
            event.payload, "status", "state", default=LifecycleState.REGISTERED.value
        )
        try:
            state = coerce_state(state_value)
        except LifecycleError as exc:
            raise IntegrityError(str(exc)) from exc
        if state not in {
            LifecycleState.REGISTERED,
            LifecycleState.QUEUED,
            LifecycleState.RUNNING,
        }:
            raise IntegrityError(
                "a newly registered experiment cannot start in a terminal state"
            )
        try:
            connection.execute(
                "INSERT INTO experiments "
                "(experiment_id, project_id, generation_id, evaluation_scope_id, "
                "parent_id, candidate_digest, compatibility_digest, attempt, retry_of, "
                "retryable, status, payload_json, registered_at, terminated_at, "
                "created_sequence, updated_sequence) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, NULL, ?, ?)",
                (
                    experiment_id,
                    event.project_id,
                    generation_id,
                    evaluation_scope_id,
                    parent_id,
                    digest,
                    compatibility_digest,
                    attempt,
                    retry_of,
                    state.value,
                    canonical_json(event.payload),
                    event.occurred_at,
                    event.sequence,
                    event.sequence,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(
                f"invalid experiment registration {experiment_id}: {exc}"
            ) from exc

    def _stage_completed(self, connection: sqlite3.Connection, event: Event) -> None:
        self._ensure_project(connection, event)
        experiment_id = _text(event.payload, "experiment_id", required=True)
        assert experiment_id is not None
        experiment = self._require_experiment(
            connection, event.project_id, experiment_id
        )
        try:
            state = coerce_state(experiment["status"])
        except LifecycleError as exc:
            raise IntegrityError(str(exc)) from exc
        if state in TERMINAL_STATES:
            raise IntegrityError(
                f"cannot record stage completion after experiment {experiment_id!r} "
                f"terminated as {state.value}"
            )
        stage_name = _text(event.payload, "stage", "stage_name", "name", required=True)
        assert stage_name is not None
        stage_id = _text(event.payload, "stage_id", "id") or stable_id(
            "stage", event.project_id, experiment_id, stage_name, event.sequence
        )
        status = _text(event.payload, "status") or "completed"
        connection.execute(
            "INSERT INTO adapter_stages "
            "(stage_id, project_id, experiment_id, stage_name, status, input_digest, "
            "output_digest, payload_json, completed_at, event_sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                stage_id,
                event.project_id,
                experiment_id,
                stage_name,
                status,
                _text(event.payload, "input_digest"),
                _text(event.payload, "output_digest", "digest"),
                canonical_json(event.payload),
                event.occurred_at,
                event.sequence,
            ),
        )

    def _artifact_recorded(self, connection: sqlite3.Connection, event: Event) -> None:
        self._ensure_project(connection, event)
        # Import lazily so the low-level kernel does not create an import cycle
        # while package exports are being initialized.
        from research_os.artifacts.catalog import ArtifactRecord

        try:
            artifact = ArtifactRecord.from_mapping(event.payload)
        except IntegrityError as exc:
            raise IntegrityError(
                f"ARTIFACT_RECORDED payload is not a captured artifact: {exc}"
            ) from exc
        if artifact.project_id != event.project_id:
            raise IntegrityError("artifact project_id does not match its event project")
        self._require_experiment(connection, event.project_id, artifact.experiment_id)
        connection.execute(
            "INSERT INTO artifacts "
            "(artifact_id, project_id, experiment_id, digest, algorithm, relative_path, "
            "storage_path, role, media_type, size, metadata_json, payload_json, recorded_at, "
            "event_sequence) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                artifact.artifact_id,
                event.project_id,
                artifact.experiment_id,
                artifact.digest,
                artifact.algorithm,
                artifact.relative_path,
                artifact.storage_path,
                artifact.role,
                artifact.media_type,
                artifact.size,
                canonical_json(artifact.metadata),
                canonical_json(event.payload),
                event.occurred_at,
                event.sequence,
            ),
        )

    def _finding_recorded(self, connection: sqlite3.Connection, event: Event) -> None:
        self._ensure_project(connection, event)
        finding_id = _text(event.payload, "finding_id", "id") or stable_id(
            "finding", event.project_id, event.event_id
        )
        scope = (_text(event.payload, "scope") or "project").lower()
        if scope not in {"session", "project", "global"}:
            raise IntegrityError(f"invalid finding scope: {scope!r}")
        payload_project = _text(event.payload, "project_id")
        session_id = _text(event.payload, "session_id")
        if scope == "project":
            finding_project = payload_project or event.project_id
            if finding_project != event.project_id:
                raise IntegrityError(
                    "project-scoped finding belongs to a different event project"
                )
        elif scope == "session":
            if session_id is None:
                raise IntegrityError("session-scoped finding requires session_id")
            finding_project = payload_project or event.project_id
            if finding_project != event.project_id:
                raise IntegrityError(
                    "session-scoped finding belongs to a different event project"
                )
        else:
            finding_project = None
        experiment_id = _text(event.payload, "experiment_id")
        if experiment_id is not None:
            self._require_experiment(connection, event.project_id, experiment_id)
        if "content" not in event.payload:
            raise IntegrityError("finding event payload is missing 'content'")
        content = event.payload["content"]
        evidence = _pick(event.payload, "evidence", default=[])
        finding_key = _text(event.payload, "key", "finding_key")
        has_branch_version = "branch_conclusion_version" in event.payload
        if has_branch_version and finding_key != "branch_conclusion":
            raise IntegrityError(
                "branch_conclusion_version is reserved for branch conclusions"
            )
        if finding_key == "branch_conclusion" and has_branch_version:
            version = event.payload.get("branch_conclusion_version")
            if (
                isinstance(version, bool)
                or not isinstance(version, int)
                or version != 1
            ):
                raise IntegrityError("branch conclusion version is invalid")
            self._validate_branch_conclusion(
                connection,
                event,
                finding_id=finding_id,
                content=content,
                evidence=evidence,
            )
        normalized_payload = dict(event.payload)
        normalized_payload.update(
            {
                "finding_id": finding_id,
                "scope": scope,
                "project_id": finding_project,
                "session_id": session_id,
                "experiment_id": experiment_id,
            }
        )
        connection.execute(
            "INSERT INTO findings "
            "(finding_id, scope, project_id, origin_project_id, session_id, experiment_id, "
            "finding_key, content_json, evidence_json, payload_json, created_at, event_sequence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                finding_id,
                scope,
                finding_project,
                event.project_id,
                session_id,
                experiment_id,
                finding_key,
                canonical_json(content),
                canonical_json(evidence),
                canonical_json(normalized_payload),
                event.occurred_at,
                event.sequence,
            ),
        )

    def _validate_branch_conclusion(
        self,
        connection: sqlite3.Connection,
        event: Event,
        *,
        finding_id: str,
        content: Any,
        evidence: Any,
    ) -> None:
        """Replay the evidence binding for the managed branch finding."""

        required_envelope = {
            "finding_id",
            "scope",
            "project_id",
            "session_id",
            "experiment_id",
            "key",
            "content",
            "evidence",
            "metadata",
            "branch_conclusion_version",
        }
        if set(event.payload) != required_envelope:
            raise IntegrityError("branch conclusion envelope has invalid fields")
        if (
            event.payload.get("scope") != "project"
            or event.payload.get("project_id") != event.project_id
            or event.payload.get("session_id") is not None
            or event.payload.get("experiment_id") is not None
            or event.payload.get("key") != "branch_conclusion"
        ):
            raise IntegrityError("branch conclusion envelope is invalid")

        required_content = {
            "branch_experiment_ids",
            "hypothesis_class",
            "failure_signature",
            "conclusion",
            "confidence",
            "next_step",
            "compatibility_digest",
        }
        if not isinstance(content, Mapping) or set(content) != required_content:
            raise IntegrityError("branch conclusion content has invalid fields")
        for key in (
            "hypothesis_class",
            "failure_signature",
            "conclusion",
            "compatibility_digest",
        ):
            value = content.get(key)
            if not isinstance(value, str) or not value.strip():
                raise IntegrityError(f"branch conclusion {key} is invalid")
        if content.get("confidence") not in {
            "supported",
            "falsified",
            "inconclusive",
        }:
            raise IntegrityError("branch conclusion confidence is invalid")
        if content.get("next_step") not in {
            "stop",
            "change_control",
            "explore",
            "ablate",
            "exploit",
            "replicate",
        }:
            raise IntegrityError("branch conclusion next_step is invalid")

        experiment_ids = content.get("branch_experiment_ids")
        if (
            not isinstance(experiment_ids, Sequence)
            or isinstance(experiment_ids, (str, bytes, bytearray))
            or not experiment_ids
            or not all(isinstance(value, str) and value for value in experiment_ids)
            or len(set(experiment_ids)) != len(experiment_ids)
        ):
            raise IntegrityError("branch conclusion experiment IDs are invalid")
        if (
            not isinstance(evidence, Sequence)
            or isinstance(evidence, (str, bytes, bytearray))
            or len(evidence) != len(experiment_ids)
        ):
            raise IntegrityError("branch conclusion evidence is incomplete")

        compatibility_digest = cast(str, content["compatibility_digest"])
        for index, experiment_id in enumerate(experiment_ids):
            experiment_id = cast(str, experiment_id)
            item = evidence[index]
            if not isinstance(item, Mapping) or set(item) != {
                "experiment_id",
                "event_id",
                "event_hash",
            }:
                raise IntegrityError("branch conclusion evidence item is invalid")
            if item.get("experiment_id") != experiment_id:
                raise IntegrityError(
                    "branch conclusion evidence order does not match its experiments"
                )
            terminal_event_id = item.get("event_id")
            terminal_event_hash = item.get("event_hash")
            if (
                not isinstance(terminal_event_id, str)
                or not terminal_event_id
                or not isinstance(terminal_event_hash, str)
                or not terminal_event_hash
            ):
                raise IntegrityError("branch conclusion event evidence is invalid")
            experiment = self._require_experiment(
                connection,
                event.project_id,
                experiment_id,
            )
            try:
                state = coerce_state(experiment["status"])
            except LifecycleError as exc:
                raise IntegrityError(
                    "branch conclusion references invalid experiment state"
                ) from exc
            if (
                state not in TERMINAL_STATES
                or experiment["terminated_at"] is None
                or experiment["compatibility_digest"] != compatibility_digest
            ):
                raise IntegrityError(
                    "branch conclusion requires compatible terminal experiments"
                )
            terminal = connection.execute(
                "SELECT project_id, event_sequence, event_hash FROM projected_events "
                "WHERE event_id = ?",
                (terminal_event_id,),
            ).fetchone()
            if (
                terminal is None
                or terminal["project_id"] != event.project_id
                or terminal["event_hash"] != terminal_event_hash
                or int(terminal["event_sequence"]) != int(experiment["updated_sequence"])
                or int(terminal["event_sequence"]) >= event.sequence
            ):
                raise IntegrityError(
                    "branch conclusion does not reference the terminal event"
                )

        metadata = event.payload.get("metadata")
        required_metadata = {
            "claim_authority",
            "authorized_action",
            "agent_context_token",
            "agent_context_schema_version",
        }
        context_schema_version = (
            metadata.get("agent_context_schema_version")
            if isinstance(metadata, Mapping)
            else None
        )
        if (
            not isinstance(metadata, Mapping)
            or set(metadata) != required_metadata
            or metadata.get("claim_authority") != "agent_interpretation"
            or metadata.get("authorized_action") is not None
            or not isinstance(metadata.get("agent_context_token"), str)
            or not metadata.get("agent_context_token")
            or isinstance(context_schema_version, bool)
            or not isinstance(context_schema_version, int)
            or context_schema_version != 2
        ):
            raise IntegrityError("branch conclusion metadata is invalid")
        expected_id = stable_id(
            "finding",
            event.project_id,
            "branch_conclusion",
            1,
            content,
            evidence,
        )
        if finding_id != expected_id:
            raise IntegrityError("branch conclusion finding ID is invalid")

    def _experiment_terminated(
        self, connection: sqlite3.Connection, event: Event
    ) -> None:
        self._ensure_project(connection, event)
        experiment_id = _text(event.payload, "experiment_id", "id", required=True)
        assert experiment_id is not None
        row = self._require_experiment(connection, event.project_id, experiment_id)
        target_value = _pick(event.payload, "status", "state", "outcome")
        if target_value is None:
            raise IntegrityError(
                "EXPERIMENT_TERMINATED payload is missing terminal status"
            )
        try:
            target = coerce_state(target_value)
            if target not in TERMINAL_STATES:
                raise LifecycleError(
                    f"{target.value!r} is not a terminal lifecycle state"
                )
            validate_transition(row["status"], target)
        except LifecycleError as exc:
            raise IntegrityError(str(exc)) from exc
        if "attempt" in event.payload and _attempt(event.payload) != int(row["attempt"]):
            raise IntegrityError("terminal attempt does not match its registration")
        if "retry_of" in event.payload:
            terminal_retry_of = _text(event.payload, "retry_of")
            if terminal_retry_of != row["retry_of"]:
                raise IntegrityError("terminal retry_of does not match its registration")
        retryable = _validated_retryable(target, event.payload)
        if (
            retryable
            and target
            in {
                LifecycleState.INFRA_FAILED,
                LifecycleState.INSUFFICIENT_EVIDENCE,
            }
            and event.payload.get("reason_code") != "RECOVERED_INTERRUPTED_RUN"
        ):
            self._require_matching_retryable_stage(
                connection, event, experiment_id
            )
        try:
            registration_payload = strict_json_loads(row["payload_json"])
        except (TypeError, ValueError) as exc:
            raise IntegrityError(
                f"experiment {experiment_id!r} has corrupt projected payload JSON"
            ) from exc
        if not isinstance(registration_payload, dict):
            raise IntegrityError(
                f"experiment {experiment_id!r} projected payload is not an object"
            )
        # Keep the immutable registration/candidate context visible in lineage,
        # while retaining the complete terminal evidence under a distinct key.
        merged_payload = dict(registration_payload)
        merged_payload["status"] = target.value
        merged_payload["outcome"] = event.payload
        connection.execute(
            "UPDATE experiments SET status = ?, retryable = ?, payload_json = ?, "
            "terminated_at = ?, updated_sequence = ? "
            "WHERE experiment_id = ? AND project_id = ?",
            (
                target.value,
                int(retryable),
                canonical_json(merged_payload),
                event.occurred_at,
                event.sequence,
                experiment_id,
                event.project_id,
            ),
        )

    def _require_matching_retryable_stage(
        self,
        connection: sqlite3.Connection,
        terminal_event: Event,
        experiment_id: str,
    ) -> None:
        """Bind adapter retry eligibility to its preceding failed stage event."""

        row = connection.execute(
            "SELECT payload_json FROM adapter_stages "
            "WHERE project_id = ? AND experiment_id = ? "
            "ORDER BY event_sequence DESC LIMIT 1",
            (terminal_event.project_id, experiment_id),
        ).fetchone()
        if row is None:
            raise IntegrityError(
                "retryable adapter failure requires a matching failed adapter stage"
            )
        try:
            stage_payload = strict_json_loads(row["payload_json"])
        except (TypeError, ValueError) as exc:
            raise IntegrityError("retryable adapter stage payload is corrupt") from exc
        response = (
            stage_payload.get("response")
            if isinstance(stage_payload, Mapping)
            else None
        )
        stage_error = response.get("error") if isinstance(response, Mapping) else None
        terminal_error = terminal_event.payload.get("error")
        if not (
            isinstance(response, Mapping)
            and response.get("ok") is False
            and response.get("retryable") is True
            and isinstance(stage_error, Mapping)
            and isinstance(terminal_error, Mapping)
            and stage_error.get("category") == terminal_error.get("category")
            and stage_error.get("code") == terminal_error.get("code")
            and stage_error.get("code") == terminal_event.payload.get("reason_code")
        ):
            raise IntegrityError(
                "retryable terminal evidence does not match its failed adapter stage"
            )

    def _experiment_status_changed(
        self, connection: sqlite3.Connection, event: Event
    ) -> None:
        self._ensure_project(connection, event)
        experiment_id = _text(event.payload, "experiment_id", "id", required=True)
        assert experiment_id is not None
        row = self._require_experiment(connection, event.project_id, experiment_id)
        target_value = _pick(event.payload, "status", "state")
        if target_value is None:
            raise IntegrityError("EXPERIMENT_STATUS_CHANGED payload is missing status")
        try:
            target = validate_transition(row["status"], target_value)
        except LifecycleError as exc:
            raise IntegrityError(str(exc)) from exc
        if "attempt" in event.payload and _attempt(event.payload) != int(row["attempt"]):
            raise IntegrityError("transition attempt does not match its registration")
        if "retry_of" in event.payload:
            transition_retry_of = _text(event.payload, "retry_of")
            if transition_retry_of != row["retry_of"]:
                raise IntegrityError("transition retry_of does not match its registration")
        retryable = (
            _validated_retryable(target, event.payload)
            if target in TERMINAL_STATES
            else bool(row["retryable"])
        )
        if (
            retryable
            and target
            in {
                LifecycleState.INFRA_FAILED,
                LifecycleState.INSUFFICIENT_EVIDENCE,
            }
            and event.payload.get("reason_code") != "RECOVERED_INTERRUPTED_RUN"
        ):
            self._require_matching_retryable_stage(
                connection, event, experiment_id
            )
        try:
            original_payload = strict_json_loads(row["payload_json"])
        except (TypeError, ValueError) as exc:
            raise IntegrityError(
                f"experiment {experiment_id!r} has corrupt projected payload JSON"
            ) from exc
        if not isinstance(original_payload, dict):
            raise IntegrityError(
                f"experiment {experiment_id!r} projected payload is not an object"
            )
        merged_payload = dict(original_payload)
        merged_payload["status"] = target.value
        merged_payload["latest_transition"] = event.payload
        connection.execute(
            "UPDATE experiments SET status = ?, retryable = ?, payload_json = ?, "
            "terminated_at = ?, updated_sequence = ? "
            "WHERE experiment_id = ? AND project_id = ?",
            (
                target.value,
                int(retryable),
                canonical_json(merged_payload),
                event.occurred_at
                if target in TERMINAL_STATES
                else row["terminated_at"],
                event.sequence,
                experiment_id,
                event.project_id,
            ),
        )

    @staticmethod
    def _require_experiment(
        connection: sqlite3.Connection, project_id: str, experiment_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM experiments WHERE project_id = ? AND experiment_id = ?",
            (project_id, experiment_id),
        ).fetchone()
        if row is None:
            raise IntegrityError(
                f"experiment {experiment_id!r} does not exist in project {project_id!r}"
            )
        return row

    @staticmethod
    def _check_no_cycle(
        connection: sqlite3.Connection,
        project_id: str,
        experiment_id: str,
        parent_id: str,
    ) -> None:
        seen = {experiment_id}
        cursor: str | None = parent_id
        while cursor is not None:
            if cursor in seen:
                raise IntegrityError(
                    "experiment parent relationship would create a cycle"
                )
            seen.add(cursor)
            row = connection.execute(
                "SELECT parent_id FROM experiments WHERE project_id = ? AND experiment_id = ?",
                (project_id, cursor),
            ).fetchone()
            if row is None:
                raise IntegrityError(f"missing experiment parent: {cursor}")
            cursor = row["parent_id"]

    @staticmethod
    def _decode_row(row: sqlite3.Row) -> dict[str, Any]:
        import json

        result = dict(row)
        # ``generation_id`` did not exist in legacy query surfaces.  Keep null
        # as an internal SQLite sentinel without adding a nullable API key to
        # decoded legacy rows; versioned experiments expose the concrete axis.
        if result.get("generation_id") is None:
            result.pop("generation_id", None)
        if result.get("evaluation_scope_id") is None:
            result.pop("evaluation_scope_id", None)
        if "retryable" in result:
            result["retryable"] = bool(result["retryable"])
        for key in tuple(result):
            if key.endswith("_json"):
                decoded_key = key[:-5]
                result[decoded_key] = json.loads(result.pop(key))
        return result

    def project_status(self, project_id: str) -> dict[str, Any]:
        project_id = require_text(project_id, "project_id")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN")
            project = connection.execute(
                "SELECT * FROM projects WHERE project_id = ?", (project_id,)
            ).fetchone()
            status_rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM experiments WHERE project_id = ? "
                "GROUP BY status ORDER BY status",
                (project_id,),
            ).fetchall()
            baseline_count = connection.execute(
                "SELECT COUNT(*) FROM baselines WHERE project_id = ?", (project_id,)
            ).fetchone()[0]
            finding_count = connection.execute(
                "SELECT COUNT(*) FROM findings WHERE origin_project_id = ?",
                (project_id,),
            ).fetchone()[0]
            artifact_count = connection.execute(
                "SELECT COUNT(*) FROM artifacts WHERE project_id = ?", (project_id,)
            ).fetchone()[0]
            cursor = self._cursor(connection)
        counts = {row["status"]: row["count"] for row in status_rows}
        return {
            "project_id": project_id,
            "initialized": project is not None,
            "status": project["status"] if project else None,
            "experiments": sum(counts.values()),
            "experiments_by_status": counts,
            "baselines": baseline_count,
            "artifacts": artifact_count,
            "findings": finding_count,
            "last_sequence": cursor["last_sequence"]
            if cursor["project_id"] == project_id
            else 0,
            "last_hash": cursor["last_hash"]
            if cursor["project_id"] == project_id
            else None,
        }

    def lineage(
        self, project_id: str, experiment_id: str | None = None
    ) -> list[dict[str, Any]]:
        project_id = require_text(project_id, "project_id")
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN")
            if experiment_id is None:
                rows = connection.execute(
                    "SELECT * FROM experiments WHERE project_id = ? ORDER BY created_sequence",
                    (project_id,),
                ).fetchall()
                return [self._decode_row(row) for row in rows]
            experiment_id = require_text(experiment_id, "experiment_id")
            lineage: list[sqlite3.Row] = []
            seen: set[str] = set()
            cursor: str | None = experiment_id
            while cursor is not None:
                if cursor in seen:
                    raise IntegrityError("cycle found while reading experiment lineage")
                seen.add(cursor)
                row = self._require_experiment(connection, project_id, cursor)
                lineage.append(row)
                cursor = row["parent_id"]
            lineage.reverse()
            return [self._decode_row(row) for row in lineage]

    def artifacts(
        self, project_id: str, experiment_id: str | None = None
    ) -> list[dict[str, Any]]:
        project_id = require_text(project_id, "project_id")
        parameters: list[Any] = [project_id]
        query = "SELECT * FROM artifacts WHERE project_id = ?"
        if experiment_id is not None:
            query += " AND experiment_id = ?"
            parameters.append(require_text(experiment_id, "experiment_id"))
        query += " ORDER BY event_sequence"
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._decode_row(row) for row in rows]

    def candidate_exists(
        self,
        project_id: str,
        digest: str,
        parent_id: str | None,
        compatibility_digest: str | None = None,
        generation_id: str | None = None,
        evaluation_scope_id: str | None = None,
    ) -> bool:
        project_id = require_text(project_id, "project_id")
        digest = require_text(digest, "digest")
        clauses = ["project_id = ?", "candidate_digest = ?"]
        parameters: list[Any] = [project_id, digest]
        if parent_id is None:
            clauses.append("parent_id IS NULL")
        else:
            clauses.append("parent_id = ?")
            parameters.append(require_text(parent_id, "parent_id"))
        if compatibility_digest is not None:
            clauses.append("compatibility_digest = ?")
            parameters.append(
                require_text(compatibility_digest, "compatibility_digest")
            )
        if generation_id is None:
            clauses.append("generation_id IS NULL")
        else:
            clauses.append("generation_id = ?")
            parameters.append(require_text(generation_id, "generation_id"))
        if evaluation_scope_id is None:
            clauses.append("evaluation_scope_id IS NULL")
        else:
            clauses.append("evaluation_scope_id = ?")
            parameters.append(
                require_text(evaluation_scope_id, "evaluation_scope_id")
            )
        query = "SELECT 1 FROM experiments WHERE " + " AND ".join(clauses) + " LIMIT 1"
        with closing(self._connect()) as connection, connection:
            row = connection.execute(query, parameters).fetchone()
        return row is not None

    def experiment(self, project_id: str, experiment_id: str) -> dict[str, Any]:
        """Return one projected experiment, including retry-attempt metadata."""

        project_id = require_text(project_id, "project_id")
        experiment_id = require_text(experiment_id, "experiment_id")
        with closing(self._connect()) as connection, connection:
            row = self._require_experiment(connection, project_id, experiment_id)
        return self._decode_row(row)

    def candidate_attempts(
        self,
        project_id: str,
        digest: str,
        parent_id: str | None,
        compatibility_digest: str,
        generation_id: str | None = None,
        evaluation_scope_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return every attempt for one candidate identity in attempt order."""

        project_id = require_text(project_id, "project_id")
        digest = require_text(digest, "digest")
        compatibility_digest = require_text(
            compatibility_digest, "compatibility_digest"
        )
        clauses = [
            "project_id = ?",
            "candidate_digest = ?",
            "compatibility_digest = ?",
        ]
        parameters: list[Any] = [project_id, digest, compatibility_digest]
        if parent_id is None:
            clauses.append("parent_id IS NULL")
        else:
            clauses.append("parent_id = ?")
            parameters.append(require_text(parent_id, "parent_id"))
        if generation_id is None:
            clauses.append("generation_id IS NULL")
        else:
            clauses.append("generation_id = ?")
            parameters.append(require_text(generation_id, "generation_id"))
        if evaluation_scope_id is None:
            clauses.append("evaluation_scope_id IS NULL")
        else:
            clauses.append("evaluation_scope_id = ?")
            parameters.append(
                require_text(evaluation_scope_id, "evaluation_scope_id")
            )
        query = (
            "SELECT * FROM experiments WHERE "
            + " AND ".join(clauses)
            + " ORDER BY attempt, created_sequence"
        )
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._decode_row(row) for row in rows]

    def findings(
        self,
        *,
        scope: str | None = None,
        project_id: str | None = None,
        session_id: str | None = None,
        experiment_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        parameters: list[Any] = []
        if scope is not None:
            normalized_scope = require_text(scope, "scope").lower()
            if normalized_scope not in {"session", "project", "global"}:
                raise ValueError(f"invalid finding scope: {scope!r}")
            clauses.append("scope = ?")
            parameters.append(normalized_scope)
        if project_id is not None:
            clauses.append("(project_id = ? OR scope = 'global')")
            parameters.append(require_text(project_id, "project_id"))
        if session_id is not None:
            clauses.append("session_id = ?")
            parameters.append(require_text(session_id, "session_id"))
        if experiment_id is not None:
            clauses.append("experiment_id = ?")
            parameters.append(require_text(experiment_id, "experiment_id"))
        query = "SELECT * FROM findings"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY event_sequence"
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(query, parameters).fetchall()
        return [self._decode_row(row) for row in rows]

    # More explicit aliases useful at API boundaries.
    artifacts_for_experiment = artifacts
    get_experiment = experiment
    get_lineage = lineage
    has_candidate = candidate_exists


SQLiteProjection = ProjectionStore
