"""Disposable, integrity-checked project workspaces.

The source checkout is never used as a candidate's writable working directory.
Each experiment receives a private copy below ``.research-os/runtime/workspaces``
and the copy is discarded after its integrity checks have run.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import shutil
import stat
import tempfile
import threading
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePath, PureWindowsPath
from types import MappingProxyType
from typing import Any, Iterator

from research_os.errors import ConfigurationError, IntegrityError, LifecycleError

_COPY_BUFFER_SIZE = 1024 * 1024
_EXPERIMENT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_CONTROL_DIR = ".research-os"
_RUNTIME_PARTS = (_CONTROL_DIR, "runtime")
_AGENT_TRANSIENT_PATHS = frozenset(
    {
        (_CONTROL_DIR, "candidate.inbox.json"),
        (_CONTROL_DIR, "agent-journal.jsonl"),
        (_CONTROL_DIR, "evaluator-certification.json"),
    }
)

# These directories contain derived data.  Omitting them makes a workspace a
# snapshot of the experiment inputs rather than of local tool state.
_CACHE_DIR_NAMES = frozenset(
    {
        "__pycache__",
        ".cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".hypothesis",
        "caches",
    }
)


def _config_value(config: object, name: str, default: Any = None) -> Any:
    if isinstance(config, Mapping):
        return config.get(name, default)
    return getattr(config, name, default)


def _error_with_details(
    error_type: type[ConfigurationError] | type[IntegrityError] | type[LifecycleError],
    message: str,
    *,
    code: str,
    details: Mapping[str, Any] | None = None,
) -> ConfigurationError | IntegrityError | LifecycleError:
    error = error_type(message)
    # The shared error classes intentionally have no constructor policy.  These
    # attributes keep programmatic error handling stable without changing that
    # public hierarchy.
    setattr(error, "code", code)  # noqa: B010 - typed exception metadata is dynamic.
    setattr(error, "details", dict(details or {}))  # noqa: B010
    return error


def _attach_cleanup_note(
    primary: BaseException,
    cleanup_error: BaseException,
    *,
    context: str,
) -> None:
    """Describe a secondary cleanup failure without disturbing ``primary``."""

    try:
        detail = str(cleanup_error)
    except BaseException:
        detail = "<unprintable>"
    summary = type(cleanup_error).__name__
    if detail:
        summary = f"{summary}: {detail}"
    try:
        primary.add_note(f"{context}: {summary}")
    except BaseException:
        # Notes are diagnostic only.  Even a hostile exception subclass must
        # not be able to replace the failure that triggered cleanup.
        pass


def _mode(path_stat: os.stat_result) -> str:
    return f"{stat.S_IMODE(path_stat.st_mode):04o}"


def _framed(digest: "hashlib._Hash", *parts: str | bytes) -> None:
    """Add unambiguous length-prefixed fields to a digest."""

    for part in parts:
        data = part if isinstance(part, bytes) else part.encode("utf-8")
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)


def _path_is_excluded(relative: PurePath) -> bool:
    parts = relative.parts
    if not parts:
        return False
    if ".git" in parts or any(part in _CACHE_DIR_NAMES for part in parts):
        return True
    return (len(parts) >= 2 and parts[:2] == _RUNTIME_PARTS) or tuple(
        parts
    ) in _AGENT_TRANSIENT_PATHS


def _regular_file_stat(path: Path) -> os.stat_result:
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise IntegrityError(
            f"cannot inspect file {path}: {exc.strerror or exc}"
        ) from exc
    if stat.S_ISLNK(path_stat.st_mode):
        raise IntegrityError(f"refusing to hash symbolic link: {path}")
    if not stat.S_ISREG(path_stat.st_mode):
        raise IntegrityError(f"refusing to hash non-regular file: {path}")
    return path_stat


def hash_file(
    path: str | os.PathLike[str], *, chunk_size: int = _COPY_BUFFER_SIZE
) -> str:
    """Return the SHA-256 content digest of one regular, non-symlink file."""

    if (
        isinstance(chunk_size, bool)
        or not isinstance(chunk_size, int)
        or chunk_size <= 0
    ):
        raise ValueError("chunk_size must be a positive integer")
    file_path = Path(path)
    before = _regular_file_stat(file_path)
    digest = hashlib.sha256()
    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(file_path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            os.close(descriptor)
            raise IntegrityError(f"refusing to hash non-regular file: {file_path}")
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            os.close(descriptor)
            raise IntegrityError(
                f"file was replaced while opening it for hashing: {file_path}"
            )
        with os.fdopen(descriptor, "rb") as stream:
            while block := stream.read(chunk_size):
                digest.update(block)
    except OSError as exc:
        raise IntegrityError(
            f"cannot read file for hashing {file_path}: {exc.strerror or exc}"
        ) from exc
    after = _regular_file_stat(file_path)
    # Catch common replacement/write races.  The enclosing source-tree check
    # provides a second comparison after the copy has completed.
    if (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        before.st_ctime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        after.st_ctime_ns,
    ):
        raise IntegrityError(f"file changed while it was being hashed: {file_path}")
    return digest.hexdigest()


def _tree_entries(
    root: Path, *, exclude_transient: bool
) -> Iterator[tuple[str, Path, os.stat_result]]:
    """Yield a stable, non-following walk as ``(relative, path, lstat)``."""

    root_stat = root.lstat()
    pending: list[tuple[PurePath, Path, tuple[int, int], int]] = [
        (
            PurePath(),
            root,
            (root_stat.st_dev, root_stat.st_ino),
            stat.S_IMODE(root_stat.st_mode),
        )
    ]
    while pending:
        relative_dir, directory, expected_identity, expected_mode = pending.pop()
        descriptor = -1
        try:
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(directory, flags)
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISDIR(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != expected_identity
                or stat.S_IMODE(opened.st_mode) != expected_mode
            ):
                raise IntegrityError(
                    f"project directory changed during hashing: {directory}"
                )
            with os.scandir(descriptor) as scanner:
                entries = sorted(
                    (
                        (entry.name, entry.stat(follow_symlinks=False))
                        for entry in scanner
                    ),
                    key=lambda item: item[0],
                )
        except OSError as exc:
            raise IntegrityError(
                f"cannot inspect project tree at {directory}: {exc.strerror or exc}"
            ) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)

        child_directories: list[tuple[PurePath, Path, tuple[int, int], int]] = []
        for entry_name, entry_stat in entries:
            relative = relative_dir / entry_name
            if exclude_transient and _path_is_excluded(relative):
                continue
            path = directory / entry_name
            relative_text = relative.as_posix()
            yield relative_text, path, entry_stat
            if stat.S_ISDIR(entry_stat.st_mode):
                child_directories.append(
                    (
                        relative,
                        path,
                        (entry_stat.st_dev, entry_stat.st_ino),
                        stat.S_IMODE(entry_stat.st_mode),
                    )
                )
            elif not stat.S_ISREG(entry_stat.st_mode):
                kind = (
                    "symbolic link"
                    if stat.S_ISLNK(entry_stat.st_mode)
                    else "special file"
                )
                raise IntegrityError(f"project tree contains unsafe {kind}: {path}")

        # The stack is LIFO, so reverse to retain lexical traversal order.
        pending.extend(reversed(child_directories))


def hash_tree(path: str | os.PathLike[str], *, exclude_transient: bool = True) -> str:
    """Hash a normalized project tree.

    Relative POSIX paths, entry kinds, permission bits and file content hashes
    are framed and sorted.  Timestamps, ownership and platform inode values are
    deliberately omitted.  Git metadata, Research OS runtime data, and common
    cache directories are excluded.
    """

    root = Path(path)
    try:
        root_stat = root.lstat()
    except OSError as exc:
        raise IntegrityError(
            f"cannot inspect project root {root}: {exc.strerror or exc}"
        ) from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise IntegrityError(
            f"project tree root must be a non-symlink directory: {root}"
        )

    digest = hashlib.sha256()
    _framed(digest, "research-os-tree-v1", "root", _mode(root_stat))
    for relative, entry, entry_stat in _tree_entries(
        root, exclude_transient=exclude_transient
    ):
        if stat.S_ISDIR(entry_stat.st_mode):
            _framed(digest, "directory", relative, _mode(entry_stat))
        else:
            _framed(digest, "file", relative, _mode(entry_stat), hash_file(entry))
    return digest.hexdigest()


def fingerprint_path(path: str | os.PathLike[str]) -> str:
    """Hash one protected file or directory, including its kind and mode."""

    protected_path = Path(path)
    try:
        path_stat = protected_path.lstat()
    except OSError as exc:
        raise IntegrityError(
            f"cannot fingerprint protected path {protected_path}: {exc.strerror or exc}"
        ) from exc
    digest = hashlib.sha256()
    if stat.S_ISREG(path_stat.st_mode):
        _framed(
            digest,
            "research-os-protected-v1",
            "file",
            _mode(path_stat),
            hash_file(protected_path),
        )
    elif stat.S_ISDIR(path_stat.st_mode):
        _framed(
            digest,
            "research-os-protected-v1",
            "directory",
            _mode(path_stat),
            hash_tree(protected_path, exclude_transient=False),
        )
    elif stat.S_ISLNK(path_stat.st_mode):
        raise IntegrityError(
            f"protected path must not be a symbolic link: {protected_path}"
        )
    else:
        raise IntegrityError(
            f"protected path must be a regular file or directory: {protected_path}"
        )
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class WorkspaceEntry:
    """Normalized state of one entry in a workspace manifest."""

    kind: str
    mode: int
    digest: str | None = None
    size: int | None = None


@dataclass(frozen=True, slots=True)
class WorkspaceChange:
    """One added, removed, or modified workspace entry."""

    path: str
    before: WorkspaceEntry | None
    after: WorkspaceEntry | None

    @property
    def change_type(self) -> str:
        if self.before is None:
            return "added"
        if self.after is None:
            return "removed"
        return "modified"


def _workspace_manifest(root: Path) -> dict[str, WorkspaceEntry]:
    try:
        root_stat = root.lstat()
    except OSError as exc:
        raise IntegrityError(f"cannot inspect workspace root {root}") from exc
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise IntegrityError(f"workspace root must be a non-symlink directory: {root}")
    manifest: dict[str, WorkspaceEntry] = {
        ".": WorkspaceEntry("directory", stat.S_IMODE(root_stat.st_mode))
    }
    # The copy starts without Git/runtime/cache data, but the post-run manifest
    # deliberately includes every entry.  Otherwise an adapter could hide an
    # unauthorized write merely by placing it in ``.cache`` or ``__pycache__``.
    for relative, entry, entry_stat in _tree_entries(root, exclude_transient=False):
        if stat.S_ISDIR(entry_stat.st_mode):
            manifest[relative] = WorkspaceEntry(
                "directory", stat.S_IMODE(entry_stat.st_mode)
            )
        else:
            manifest[relative] = WorkspaceEntry(
                "file",
                stat.S_IMODE(entry_stat.st_mode),
                hash_file(entry),
                entry_stat.st_size,
            )
    return manifest


def _coerce_relative_paths(value: Any, field_name: str) -> tuple[Path, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, os.PathLike)):
        values: Iterable[Any] = (value,)
    else:
        try:
            values = iter(value)
        except TypeError as exc:
            raise ConfigurationError(
                f"{field_name} must be a sequence of paths"
            ) from exc

    result: list[Path] = []
    seen: set[str] = set()
    for raw_path in values:
        try:
            relative = Path(os.fspath(raw_path))
        except TypeError as exc:
            raise ConfigurationError(f"{field_name} contains a non-path value") from exc
        text = os.fspath(relative)
        if not text or "\x00" in text:
            raise ConfigurationError(f"{field_name} contains an empty or invalid path")
        # Backslashes are separators on Windows but ordinary characters on
        # POSIX.  Refusing them keeps a contract safe if moved between hosts.
        if "\\" in text:
            raise ConfigurationError(f"{field_name} path is not portable: {text!r}")
        if relative.is_absolute() or relative.anchor:
            raise ConfigurationError(
                f"{field_name} path must be project-relative: {text!r}"
            )
        windows_path = PureWindowsPath(text)
        if windows_path.is_absolute() or windows_path.drive:
            raise ConfigurationError(
                f"{field_name} path must be project-relative: {text!r}"
            )
        parts = relative.parts
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise ConfigurationError(f"{field_name} path is unsafe: {text!r}")
        normalized = Path(*parts)
        runtime_relative = Path(*_RUNTIME_PARTS)
        if (
            _path_is_excluded(PurePath(*parts))
            or _has_path_overlap(normalized, runtime_relative)
            or (field_name == "mutable_paths" and parts[0] == _CONTROL_DIR)
        ):
            raise ConfigurationError(
                f"{field_name} path targets control or excluded data: {normalized.as_posix()!r}"
            )
        key = normalized.as_posix()
        if key in seen:
            raise ConfigurationError(f"{field_name} contains duplicate path: {key!r}")
        seen.add(key)
        result.append(normalized)
    return tuple(result)


def _has_path_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _ensure_surface_is_safe(
    root: Path, relative: Path, *, must_exist: bool, field_name: str
) -> None:
    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            if must_exist:
                raise ConfigurationError(
                    f"{field_name} path does not exist: {relative.as_posix()!r}"
                ) from None
            # A missing component makes all remaining components non-symlinks
            # at validation time.  Their eventual location is still contained
            # by the already-validated parent.
            return
        except OSError as exc:
            raise ConfigurationError(
                f"cannot inspect {field_name} path {relative.as_posix()!r}: {exc.strerror or exc}"
            ) from exc
        if stat.S_ISLNK(current_stat.st_mode):
            raise ConfigurationError(
                f"{field_name} path crosses a symbolic link: {relative.as_posix()!r}"
            )
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(current_stat.st_mode):
            raise ConfigurationError(
                f"{field_name} path crosses a non-directory: {relative.as_posix()!r}"
            )
    final_stat = current.lstat()
    if not (stat.S_ISREG(final_stat.st_mode) or stat.S_ISDIR(final_stat.st_mode)):
        raise ConfigurationError(
            f"{field_name} path is not a regular file or directory: {relative.as_posix()!r}"
        )


def _mkdir_without_symlinks(root: Path, relative_parts: tuple[str, ...]) -> Path:
    current = root
    for part in relative_parts:
        current = current / part
        try:
            current_stat = current.lstat()
        except FileNotFoundError:
            try:
                current.mkdir(mode=0o700)
            except FileExistsError:
                pass
            current_stat = current.lstat()
        if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISDIR(current_stat.st_mode):
            raise ConfigurationError(f"runtime path is not a safe directory: {current}")
    return current


def _copy_ignore(directory: str, names: list[str], *, source_root: Path) -> set[str]:
    directory_path = Path(directory)
    ignored: set[str] = set()
    for name in names:
        candidate = directory_path / name
        # copytree invokes this callback with a source directory.  Runtime is
        # also recognized explicitly to prevent copying the destination into
        # itself.
        if name == ".git" or name in _CACHE_DIR_NAMES:
            ignored.add(name)
        elif name == "runtime" and directory_path == source_root / _CONTROL_DIR:
            ignored.add(name)
        elif (
            directory_path == source_root / _CONTROL_DIR
            and (_CONTROL_DIR, name) in _AGENT_TRANSIENT_PATHS
        ):
            ignored.add(name)
        elif candidate.is_symlink():
            # Symlinks are audited and rejected before copy.  Ignore here as a
            # second line of defence against a replacement race; the post-copy
            # source fingerprint will still report drift.
            ignored.add(name)
    return ignored


@dataclass(frozen=True, slots=True)
class WorkspaceHandle:
    """Integrity seals and location of one disposable workspace."""

    experiment_id: str
    path: Path
    project_root: Path
    source_hash: str
    workspace_hash: str
    protected_hashes: Mapping[str, str]
    workspace_manifest: Mapping[str, WorkspaceEntry]
    _manager_token: str = field(repr=False, compare=False)
    _source_identity: tuple[int, int] = field(repr=False, compare=False)
    _workspace_identity: tuple[int, int] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", Path(self.path))
        object.__setattr__(self, "project_root", Path(self.project_root))
        object.__setattr__(
            self,
            "protected_hashes",
            MappingProxyType(dict(self.protected_hashes)),
        )
        object.__setattr__(
            self,
            "workspace_manifest",
            MappingProxyType(dict(self.workspace_manifest)),
        )

    @property
    def source_tree_hash(self) -> str:
        """Compatibility name for the sealed source checkout hash."""

        return self.source_hash

    @property
    def source_pre_hash(self) -> str:
        return self.source_hash

    @property
    def protected_pre_hashes(self) -> Mapping[str, str]:
        return self.protected_hashes

    @property
    def source_hash_before(self) -> str:
        return self.source_hash

    @property
    def workspace_hash_before(self) -> str:
        return self.workspace_hash

    @property
    def protected_hashes_before(self) -> Mapping[str, str]:
        return self.protected_hashes

    @property
    def source_root(self) -> Path:
        return self.project_root

    @property
    def workspace_manifest_before(self) -> Mapping[str, WorkspaceEntry]:
        return self.workspace_manifest

    @property
    def pre_hashes(self) -> Mapping[str, Any]:
        return MappingProxyType(
            {
                "source": self.source_hash,
                "workspace": self.workspace_hash,
                "protected": dict(self.protected_hashes),
            }
        )


class WorkspaceManager:
    """Create, verify, and safely remove clean-room workspaces."""

    def __init__(self, config: object):
        self.config = config
        raw_root = _config_value(config, "root", _config_value(config, "project_root"))
        if raw_root is None:
            raise ConfigurationError("workspace config requires root")
        try:
            supplied_root = Path(os.fspath(raw_root)).expanduser()
        except TypeError as exc:
            raise ConfigurationError(
                "workspace root must be a filesystem path"
            ) from exc
        if supplied_root.is_symlink():
            raise ConfigurationError("workspace root must not be a symbolic link")
        try:
            self.project_root = supplied_root.resolve(strict=True)
        except OSError as exc:
            raise ConfigurationError(
                f"workspace root does not exist: {supplied_root}"
            ) from exc
        if not self.project_root.is_dir():
            raise ConfigurationError(
                f"workspace root is not a directory: {self.project_root}"
            )

        expected_runtime = self.project_root / _RUNTIME_PARTS[0] / _RUNTIME_PARTS[1]
        configured_runtime = _config_value(config, "runtime_dir")
        if configured_runtime is not None:
            configured_path = Path(os.fspath(configured_runtime)).expanduser()
            if not configured_path.is_absolute():
                configured_path = self.project_root / configured_path
            # lexical normalization is intentional: resolving an attacker-
            # supplied symlink before rejecting it would hide the symlink.
            normalized = Path(os.path.abspath(configured_path))
            if normalized != expected_runtime:
                raise ConfigurationError(
                    "runtime_dir must be <project>/.research-os/runtime"
                )

        self.runtime_root = _mkdir_without_symlinks(self.project_root, _RUNTIME_PARTS)
        self.workspaces_root = _mkdir_without_symlinks(
            self.runtime_root,
            ("workspaces",),
        )
        os.chmod(self.runtime_root, 0o700)
        os.chmod(self.workspaces_root, 0o700)
        source_stat = self.project_root.lstat()
        runtime_stat = self.runtime_root.lstat()
        workspaces_stat = self.workspaces_root.lstat()
        self._source_identity = (source_stat.st_dev, source_stat.st_ino)
        self._runtime_identity = (runtime_stat.st_dev, runtime_stat.st_ino)
        self._workspaces_identity = (workspaces_stat.st_dev, workspaces_stat.st_ino)

        self.mutable_paths = _coerce_relative_paths(
            _config_value(config, "mutable_paths", ()), "mutable_paths"
        )
        self.protected_paths = _coerce_relative_paths(
            _config_value(config, "protected_paths", ()), "protected_paths"
        )
        for mutable in self.mutable_paths:
            _ensure_surface_is_safe(
                self.project_root,
                mutable,
                must_exist=False,
                field_name="mutable_paths",
            )
        for protected in self.protected_paths:
            _ensure_surface_is_safe(
                self.project_root,
                protected,
                must_exist=True,
                field_name="protected_paths",
            )
        overlaps = sorted(
            f"{mutable.as_posix()} <-> {protected.as_posix()}"
            for mutable in self.mutable_paths
            for protected in self.protected_paths
            if _has_path_overlap(mutable, protected)
        )
        if overlaps:
            raise ConfigurationError(
                "mutable and protected paths overlap: " + ", ".join(overlaps)
            )

        self._token = secrets.token_hex(32)
        self._lock = threading.RLock()
        self._active: dict[Path, WorkspaceHandle] = {}
        # Detached workspaces are intentionally left on disk when recovery
        # cannot safely finish consuming their evidence.  They are no longer
        # valid handles, but this manager must not subsequently mistake them
        # for disposable orphans in ``close``/``cleanup_orphans``.
        self._detached: dict[Path, WorkspaceHandle] = {}
        self._retired: dict[int, WorkspaceHandle] = {}

    def _assert_manager_roots(self) -> None:
        checks = (
            (self.project_root, self._source_identity, "source checkout"),
            (self.runtime_root, self._runtime_identity, "runtime directory"),
            (self.workspaces_root, self._workspaces_identity, "workspace directory"),
        )
        for path, expected, label in checks:
            try:
                path_stat = path.lstat()
            except OSError as exc:
                raise IntegrityError(f"{label} is unavailable: {path}") from exc
            actual = (path_stat.st_dev, path_stat.st_ino)
            if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
                raise IntegrityError(f"{label} is no longer a safe directory: {path}")
            if actual != expected:
                raise IntegrityError(
                    f"{label} was replaced after manager initialization: {path}"
                )

    def _validate_experiment_id(self, experiment_id: str) -> str:
        if not isinstance(experiment_id, str) or not _EXPERIMENT_ID.fullmatch(
            experiment_id
        ):
            raise ConfigurationError(
                "experiment_id must match [A-Za-z0-9][A-Za-z0-9._-]{0,127}"
            )
        if experiment_id in (".", ".."):
            raise ConfigurationError("experiment_id is unsafe")
        return experiment_id

    def _protected_fingerprints(self, root: Path) -> dict[str, str]:
        fingerprints: dict[str, str] = {}
        for relative in self.protected_paths:
            _ensure_surface_is_safe(
                root,
                relative,
                must_exist=True,
                field_name="protected_paths",
            )
            fingerprints[relative.as_posix()] = fingerprint_path(root / relative)
        return fingerprints

    def create(self, experiment_id: str) -> WorkspaceHandle:
        """Copy the project into a newly sealed disposable workspace."""

        safe_id = self._validate_experiment_id(experiment_id)
        # Validate again because an otherwise safe path may have been replaced
        # after manager construction.
        self._assert_manager_roots()
        for mutable in self.mutable_paths:
            _ensure_surface_is_safe(
                self.project_root,
                mutable,
                must_exist=False,
                field_name="mutable_paths",
            )
        for protected in self.protected_paths:
            _ensure_surface_is_safe(
                self.project_root,
                protected,
                must_exist=True,
                field_name="protected_paths",
            )

        source_hash = hash_tree(self.project_root)
        protected_hashes = self._protected_fingerprints(self.project_root)
        workspace = Path(
            tempfile.mkdtemp(prefix=f"{safe_id}-", dir=self.workspaces_root)
        )
        workspace_stat = workspace.lstat()
        workspace_identity = (workspace_stat.st_dev, workspace_stat.st_ino)
        try:
            shutil.copytree(
                self.project_root,
                workspace,
                symlinks=True,
                ignore=lambda directory, names: _copy_ignore(
                    directory,
                    names,
                    source_root=self.project_root,
                ),
                copy_function=shutil.copy2,
                dirs_exist_ok=True,
            )
            workspace_hash = hash_tree(workspace)
            if workspace_hash != source_hash:
                raise _error_with_details(
                    IntegrityError,
                    "workspace snapshot does not match its source checkout",
                    code="workspace_copy_mismatch",
                    details={"expected": source_hash, "actual": workspace_hash},
                )
            workspace_protected = self._protected_fingerprints(workspace)
            if workspace_protected != protected_hashes:
                changed = sorted(
                    name
                    for name in set(protected_hashes) | set(workspace_protected)
                    if protected_hashes.get(name) != workspace_protected.get(name)
                )
                raise _error_with_details(
                    IntegrityError,
                    "protected surfaces changed while creating the workspace",
                    code="protected_copy_mismatch",
                    details={"paths": changed},
                )
            # Detect source writes and copy races before giving the handle to a
            # caller.  Runtime/workspace files are excluded from this hash.
            actual_source_hash = hash_tree(self.project_root)
            if actual_source_hash != source_hash:
                raise _error_with_details(
                    IntegrityError,
                    "source checkout changed while creating the workspace",
                    code="source_changed_during_copy",
                    details={"expected": source_hash, "actual": actual_source_hash},
                )
            workspace_manifest = _workspace_manifest(workspace)
        except BaseException as primary:
            try:
                self._remove_workspace_path(
                    workspace,
                    expected_identity=workspace_identity,
                )
            except BaseException as cleanup_error:
                # The unregistered directory remains discoverable by
                # ``cleanup_orphans`` on the next run.  Preserve the operation
                # failure (including KeyboardInterrupt) as the primary signal.
                _attach_cleanup_note(
                    primary,
                    cleanup_error,
                    context=f"workspace creation cleanup failed for {workspace.name}",
                )
            raise

        handle = WorkspaceHandle(
            experiment_id=safe_id,
            path=workspace,
            project_root=self.project_root,
            source_hash=source_hash,
            workspace_hash=workspace_hash,
            protected_hashes=protected_hashes,
            workspace_manifest=workspace_manifest,
            _manager_token=self._token,
            _source_identity=self._source_identity,
            _workspace_identity=workspace_identity,
        )
        with self._lock:
            self._active[workspace] = handle
        return handle

    def _locate_orphan_workspace(
        self,
        experiment_id: str,
    ) -> tuple[Path, tuple[int, int]]:
        """Resolve exactly one safe direct workspace child for an experiment."""

        self._assert_manager_roots()
        prefix = f"{experiment_id}-"
        root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        root_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        root_fd = os.open(self.workspaces_root, root_flags)
        try:
            opened = os.fstat(root_fd)
            if (opened.st_dev, opened.st_ino) != self._workspaces_identity:
                raise IntegrityError("workspace root changed during orphan discovery")
            with os.scandir(root_fd) as scanner:
                matches = sorted(
                    (
                        entry.name,
                        entry.stat(follow_symlinks=False),
                    )
                    for entry in scanner
                    if entry.name.startswith(prefix)
                )
        except OSError as exc:
            raise IntegrityError(
                f"cannot inspect orphan workspaces for {experiment_id!r}"
            ) from exc
        finally:
            os.close(root_fd)

        if not matches:
            raise _error_with_details(
                IntegrityError,
                f"no orphan workspace exists for experiment {experiment_id!r}",
                code="orphan_workspace_not_found",
                details={"experiment_id": experiment_id},
            )
        unsafe = [
            name
            for name, entry_stat in matches
            if stat.S_ISLNK(entry_stat.st_mode)
            or not stat.S_ISDIR(entry_stat.st_mode)
        ]
        if unsafe:
            raise _error_with_details(
                IntegrityError,
                "matching orphan workspace is not a safe directory",
                code="orphan_workspace_unsafe",
                details={"entries": unsafe},
            )
        if len(matches) != 1:
            raise _error_with_details(
                IntegrityError,
                f"multiple orphan workspaces exist for experiment {experiment_id!r}",
                code="orphan_workspace_ambiguous",
                details={"entries": [name for name, _ in matches]},
            )

        name, entry_stat = matches[0]
        path = self.workspaces_root / name
        return path, (entry_stat.st_dev, entry_stat.st_ino)

    def adopt_orphan(
        self,
        experiment_id: str,
        expected_source_hash: str,
    ) -> WorkspaceHandle:
        """Adopt a crash-left workspace using newly reconstructed clean seals.

        A mutated orphan cannot describe its own pre-run state.  Recovery
        therefore makes and seals a fresh reference copy of the unchanged
        source checkout, removes that reference, and transfers only its clean
        manifest/protected seals to a handle for the identity-checked orphan.
        """

        safe_id = self._validate_experiment_id(experiment_id)
        if not isinstance(expected_source_hash, str):
            raise ConfigurationError("expected_source_hash must be a SHA-256 string")
        self._assert_manager_roots()
        actual_source_hash = hash_tree(self.project_root)
        if actual_source_hash != expected_source_hash:
            raise _error_with_details(
                IntegrityError,
                "source checkout no longer matches the interrupted experiment",
                code="recovery_source_mismatch",
                details={
                    "expected": expected_source_hash,
                    "actual": actual_source_hash,
                },
            )

        orphan_path, orphan_identity = self._locate_orphan_workspace(safe_id)
        with self._lock:
            if orphan_path in self._active or orphan_path in self._detached:
                raise LifecycleError("matching workspace is already owned by this manager")

        # This identifier contains no hyphen, so it cannot begin with
        # ``<safe_id>-`` and accidentally become a second target match.
        recovery_id = f"rosrecovery{secrets.token_hex(16)}"

        reference: WorkspaceHandle | None = None
        try:
            reference = self.create(recovery_id)
            if reference.source_hash != expected_source_hash:
                raise _error_with_details(
                    IntegrityError,
                    "source checkout changed before recovery seals were reconstructed",
                    code="recovery_source_mismatch",
                    details={
                        "expected": expected_source_hash,
                        "actual": reference.source_hash,
                    },
                )
            workspace_hash = reference.workspace_hash
            protected_hashes = reference.protected_hashes
            workspace_manifest = reference.workspace_manifest
            source_identity = reference._source_identity
        except BaseException as primary:
            if reference is not None:
                try:
                    self.cleanup(reference)
                except BaseException as cleanup_error:
                    _attach_cleanup_note(
                        primary,
                        cleanup_error,
                        context=(
                            "recovery reference cleanup failed for "
                            f"{reference.path.name}"
                        ),
                    )
            raise
        else:
            # The synthetic reference must be gone before the real orphan is
            # registered, so later orphan cleanup can never confuse the two.
            self.cleanup(reference)

        self._assert_manager_roots()
        final_source_hash = hash_tree(self.project_root)
        if final_source_hash != expected_source_hash:
            raise _error_with_details(
                IntegrityError,
                "source checkout changed while adopting the orphan workspace",
                code="recovery_source_mismatch",
                details={
                    "expected": expected_source_hash,
                    "actual": final_source_hash,
                },
            )
        final_path, final_identity = self._locate_orphan_workspace(safe_id)
        if final_path != orphan_path or final_identity != orphan_identity:
            raise IntegrityError("orphan workspace changed identity during adoption")

        handle = WorkspaceHandle(
            experiment_id=safe_id,
            path=orphan_path,
            project_root=self.project_root,
            source_hash=expected_source_hash,
            workspace_hash=workspace_hash,
            protected_hashes=protected_hashes,
            workspace_manifest=workspace_manifest,
            _manager_token=self._token,
            _source_identity=source_identity,
            _workspace_identity=orphan_identity,
        )
        with self._lock:
            if orphan_path in self._active or orphan_path in self._detached:
                raise LifecycleError("orphan workspace became owned during adoption")
            self._active[orphan_path] = handle
        return handle

    def cleanup_orphan(self, experiment_id: str) -> bool:
        """Remove the one safe unmanaged workspace for an experiment, if present."""

        safe_id = self._validate_experiment_id(experiment_id)
        try:
            path, identity = self._locate_orphan_workspace(safe_id)
        except IntegrityError as exc:
            if getattr(exc, "code", None) == "orphan_workspace_not_found":
                return False
            raise
        with self._lock:
            if path in self._active or path in self._detached:
                raise LifecycleError(
                    "cannot clean an orphan workspace owned by this manager"
                )
        self._remove_workspace_path(path, expected_identity=identity)
        return True

    def _require_active(self, handle: WorkspaceHandle) -> WorkspaceHandle:
        if not isinstance(handle, WorkspaceHandle):
            raise LifecycleError("workspace handle has the wrong type")
        with self._lock:
            active = self._active.get(handle.path)
        if (
            active is None
            or active is not handle
            or handle._manager_token != self._token
            or handle.project_root != self.project_root
        ):
            raise LifecycleError("workspace handle is not active for this manager")
        return active

    def verify_protected(self, handle: WorkspaceHandle) -> bool:
        """Fail if a declared protected surface changed in the workspace."""

        active = self._require_active(handle)
        self._assert_manager_roots()
        try:
            workspace_stat = active.path.lstat()
        except OSError as exc:
            raise IntegrityError(
                "workspace is unavailable during verification"
            ) from exc
        if (
            stat.S_ISLNK(workspace_stat.st_mode)
            or not stat.S_ISDIR(workspace_stat.st_mode)
            or (workspace_stat.st_dev, workspace_stat.st_ino)
            != active._workspace_identity
        ):
            raise IntegrityError("workspace was replaced before protected verification")
        changed: list[str] = []
        actual: dict[str, str | None] = {}
        for relative_text, expected in active.protected_hashes.items():
            relative = Path(relative_text)
            try:
                _ensure_surface_is_safe(
                    active.path,
                    relative,
                    must_exist=True,
                    field_name="protected_paths",
                )
                observed: str | None = fingerprint_path(active.path / relative)
            except (ConfigurationError, IntegrityError, OSError):
                observed = None
            actual[relative_text] = observed
            if observed != expected:
                changed.append(relative_text)
        if changed:
            raise _error_with_details(
                IntegrityError,
                "protected workspace surfaces changed: " + ", ".join(sorted(changed)),
                code="protected_surface_changed",
                details={"paths": sorted(changed), "actual": actual},
            )
        return True

    def verify_source_unchanged(self, handle: WorkspaceHandle) -> bool:
        """Fail if the original checkout drifted after workspace creation."""

        active = self._require_active(handle)
        self._assert_manager_roots()
        if active._source_identity != self._source_identity:
            raise IntegrityError("workspace handle has the wrong source identity")
        try:
            actual = hash_tree(self.project_root)
        except IntegrityError as exc:
            raise _error_with_details(
                IntegrityError,
                "source checkout is no longer a safe, hashable tree",
                code="source_checkout_unsafe",
                details={"reason": str(exc)},
            ) from exc
        if actual != active.source_hash:
            raise _error_with_details(
                IntegrityError,
                "source checkout changed after workspace creation",
                code="source_checkout_changed",
                details={"expected": active.source_hash, "actual": actual},
            )
        return True

    def diff(self, handle: WorkspaceHandle) -> tuple[WorkspaceChange, ...]:
        """Return a stable path-sorted diff from the initial workspace state."""

        active = self._require_active(handle)
        self._assert_manager_roots()
        try:
            workspace_stat = active.path.lstat()
        except OSError as exc:
            raise IntegrityError("workspace is unavailable during diff") from exc
        if (
            stat.S_ISLNK(workspace_stat.st_mode)
            or not stat.S_ISDIR(workspace_stat.st_mode)
            or (workspace_stat.st_dev, workspace_stat.st_ino)
            != active._workspace_identity
        ):
            raise IntegrityError("workspace was replaced before diff")
        current = _workspace_manifest(active.path)
        initial = active.workspace_manifest
        return tuple(
            WorkspaceChange(path, initial.get(path), current.get(path))
            for path in sorted(set(initial) | set(current))
            if initial.get(path) != current.get(path)
        )

    def _allowed_output_paths(
        self, handle: WorkspaceHandle, allowed_outputs: Any
    ) -> tuple[Path, ...]:
        if allowed_outputs is None:
            return ()
        if isinstance(allowed_outputs, Mapping) and (
            "path" in allowed_outputs or "relative_path" in allowed_outputs
        ):
            raw_values: Iterable[Any] = (allowed_outputs,)
        elif isinstance(allowed_outputs, (str, bytes, os.PathLike)) or hasattr(
            allowed_outputs, "path"
        ):
            raw_values = (allowed_outputs,)
        else:
            try:
                raw_values = iter(allowed_outputs)
            except TypeError as exc:
                raise ConfigurationError(
                    "allowed_outputs must be a sequence of artifact paths"
                ) from exc

        normalized: list[Path] = []
        seen: set[str] = set()
        for item in raw_values:
            if isinstance(item, Mapping):
                raw = item.get("path", item.get("relative_path"))
            else:
                raw = getattr(item, "path", getattr(item, "relative_path", item))
            try:
                path = Path(os.fspath(raw))
            except TypeError as exc:
                raise ConfigurationError(
                    "allowed output contains a non-path value"
                ) from exc
            if path.is_absolute():
                lexical = Path(os.path.abspath(path))
                try:
                    path = lexical.relative_to(handle.path)
                except ValueError as exc:
                    raise ConfigurationError(
                        f"allowed output escapes the workspace: {lexical}"
                    ) from exc
            parsed = _coerce_relative_paths((path,), "allowed_outputs")[0]
            if parsed.parts[0] == _CONTROL_DIR:
                raise ConfigurationError(
                    f"allowed output targets Research OS control data: {parsed.as_posix()!r}"
                )
            overlaps = [
                protected.as_posix()
                for protected in self.protected_paths
                if _has_path_overlap(parsed, protected)
            ]
            if overlaps:
                raise ConfigurationError(
                    f"allowed output overlaps protected surface {overlaps[0]!r}: "
                    f"{parsed.as_posix()!r}"
                )
            key = parsed.as_posix()
            if key not in seen:
                seen.add(key)
                normalized.append(parsed)
        return tuple(normalized)

    def verify_mutable_boundary(
        self,
        handle: WorkspaceHandle,
        allowed_outputs: Any = (),
        *,
        allow_mutable: bool = True,
    ) -> bool:
        """Fail when workspace drift escapes declared mutable/output surfaces.

        ``allowed_outputs`` should be the artifact references returned by the
        validated evaluator response.  Runtime and configured cache paths are
        absent from both manifests by policy; all other changes must fall below
        a mutable path or an explicitly allowed output.
        """

        active = self._require_active(handle)
        output_paths = self._allowed_output_paths(active, allowed_outputs)
        mutable_paths = self.mutable_paths if allow_mutable else ()
        allowed = (*mutable_paths, *output_paths)
        unauthorized: list[str] = []
        changes = self.diff(active)
        changes_by_path = {change.path: change for change in changes}
        invalid_outputs: list[str] = []
        for output in output_paths:
            # A response cannot retroactively authorize edits to pre-existing
            # project files.  Outside an already-declared mutable surface, an
            # artifact allowance is exactly one newly-created regular file.
            if any(
                output == mutable or mutable in output.parents
                for mutable in mutable_paths
            ):
                continue
            key = output.as_posix()
            change = changes_by_path.get(key)
            if (
                key in active.workspace_manifest
                or change is None
                or change.before is not None
                or change.after is None
                or change.after.kind != "file"
            ):
                invalid_outputs.append(key)
        if invalid_outputs:
            raise _error_with_details(
                IntegrityError,
                "allowed outputs must be newly-created regular files: "
                + ", ".join(sorted(invalid_outputs)),
                code="invalid_allowed_output",
                details={"paths": sorted(invalid_outputs)},
            )

        for change in changes:
            if change.path == ".":
                unauthorized.append(change.path)
                continue
            changed_path = Path(change.path)
            inside_allowed = any(
                changed_path == surface or surface in changed_path.parents
                for surface in allowed
            )
            # A newly-created directory may be an ancestor needed to reach an
            # explicitly allowed output.  Existing ancestors do not change when
            # ordinary children are created, so broader modifications remain
            # unauthorized.
            required_new_ancestor = (
                change.before is None
                and change.after is not None
                and change.after.kind == "directory"
                and any(changed_path in surface.parents for surface in output_paths)
            )
            if not inside_allowed and not required_new_ancestor:
                unauthorized.append(change.path)
        if unauthorized:
            raise _error_with_details(
                IntegrityError,
                "workspace changed outside authorized mutable/output surfaces: "
                + ", ".join(unauthorized),
                code="mutable_boundary_violated",
                details={"paths": unauthorized},
            )
        return True

    def verify(
        self,
        handle: WorkspaceHandle,
        allowed_outputs: Any = (),
        *,
        allow_mutable: bool = True,
    ) -> bool:
        """Verify protected inputs, mutation bounds, and the source checkout."""

        self.verify_protected(handle)
        self.verify_mutable_boundary(
            handle,
            allowed_outputs,
            allow_mutable=allow_mutable,
        )
        self.verify_source_unchanged(handle)
        return True

    def _remove_workspace_path(
        self, path: Path, *, expected_identity: tuple[int, int]
    ) -> None:
        """Rename then delete one direct child without following symlinks."""

        path = Path(path)
        if path.parent != self.workspaces_root or path == self.workspaces_root:
            raise LifecycleError("refusing to remove a path outside the workspace root")
        self._assert_manager_roots()
        try:
            path_stat = path.lstat()
        except FileNotFoundError as exc:
            raise IntegrityError("workspace disappeared before cleanup") from exc
        if stat.S_ISLNK(path_stat.st_mode):
            raise IntegrityError("workspace path was replaced by a symbolic link")
        if not stat.S_ISDIR(path_stat.st_mode):
            raise IntegrityError("workspace path was replaced by a non-directory")
        actual_identity = (path_stat.st_dev, path_stat.st_ino)
        if actual_identity != expected_identity:
            raise IntegrityError("workspace directory was replaced before cleanup")

        quarantine = self.workspaces_root / (
            f".deleting-{path.name}-{secrets.token_hex(8)}"
        )
        if not getattr(shutil.rmtree, "avoids_symlink_attacks", False):
            raise LifecycleError(
                "safe directory removal is unavailable on this platform"
            )
        root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        root_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        root_fd = os.open(self.workspaces_root, root_flags)
        try:
            opened_root = os.fstat(root_fd)
            if (opened_root.st_dev, opened_root.st_ino) != self._workspaces_identity:
                raise IntegrityError("workspace root changed during cleanup")
            os.rename(
                path.name,
                quarantine.name,
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
            )
        except BaseException:
            os.close(root_fd)
            raise
        try:
            quarantine_stat = os.stat(
                quarantine.name,
                dir_fd=root_fd,
                follow_symlinks=False,
            )
        except BaseException:
            os.close(root_fd)
            raise
        quarantine_identity = (quarantine_stat.st_dev, quarantine_stat.st_ino)
        if (
            stat.S_ISLNK(quarantine_stat.st_mode)
            or not stat.S_ISDIR(quarantine_stat.st_mode)
            or quarantine_identity != expected_identity
        ):
            try:
                os.rename(
                    quarantine.name,
                    path.name,
                    src_dir_fd=root_fd,
                    dst_dir_fd=root_fd,
                )
            except OSError:
                pass
            os.close(root_fd)
            raise IntegrityError("workspace changed identity during cleanup")

        def make_directories_writable(directory_fd: int) -> None:
            directory_stat = os.fstat(directory_fd)
            os.fchmod(
                directory_fd,
                stat.S_IMODE(directory_stat.st_mode)
                | stat.S_IRUSR
                | stat.S_IWUSR
                | stat.S_IXUSR,
            )
            with os.scandir(directory_fd) as scanner:
                names = [entry.name for entry in scanner]
            child_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            child_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            for name in names:
                try:
                    child_stat = os.stat(
                        name, dir_fd=directory_fd, follow_symlinks=False
                    )
                except FileNotFoundError:
                    continue
                if not stat.S_ISDIR(child_stat.st_mode) or stat.S_ISLNK(
                    child_stat.st_mode
                ):
                    continue
                if child_stat.st_dev != expected_identity[0]:
                    raise IntegrityError(
                        "workspace cleanup refuses a mounted directory"
                    )
                try:
                    child_fd = os.open(name, child_flags, dir_fd=directory_fd)
                except (FileNotFoundError, NotADirectoryError):
                    continue
                try:
                    opened = os.fstat(child_fd)
                    if (opened.st_dev, opened.st_ino) != (
                        child_stat.st_dev,
                        child_stat.st_ino,
                    ):
                        raise IntegrityError(
                            "workspace directory changed during cleanup"
                        )
                    make_directories_writable(child_fd)
                finally:
                    os.close(child_fd)

        try:
            quarantine_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            quarantine_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(
                os, "O_NOFOLLOW", 0
            )
            quarantine_fd = os.open(quarantine.name, quarantine_flags, dir_fd=root_fd)
            try:
                opened_quarantine = os.fstat(quarantine_fd)
                if (
                    opened_quarantine.st_dev,
                    opened_quarantine.st_ino,
                ) != expected_identity:
                    raise IntegrityError("workspace changed identity before removal")
                make_directories_writable(quarantine_fd)
            finally:
                os.close(quarantine_fd)
            shutil.rmtree(quarantine.name, dir_fd=root_fd)
        except BaseException:
            try:
                os.rename(
                    quarantine.name,
                    path.name,
                    src_dir_fd=root_fd,
                    dst_dir_fd=root_fd,
                )
            except OSError:
                pass
            raise
        finally:
            os.close(root_fd)

    def cleanup(self, handle: WorkspaceHandle) -> None:
        """Safely discard an active workspace.

        Cleanup deliberately does not perform integrity verification: callers
        should call :meth:`verify` first so that cleanup is still possible after
        a failed check.
        """

        with self._lock:
            if self._retired.get(id(handle)) is handle:
                return
        active = self._require_active(handle)
        self._remove_workspace_path(
            active.path,
            expected_identity=active._workspace_identity,
        )
        with self._lock:
            self._active.pop(active.path, None)
            self._retired[id(active)] = active

    def detach(self, handle: WorkspaceHandle) -> None:
        """Relinquish an active handle while preserving its directory on disk."""

        if not isinstance(handle, WorkspaceHandle):
            raise LifecycleError("workspace handle has the wrong type")
        with self._lock:
            if self._detached.get(handle.path) is handle:
                return
        active = self._require_active(handle)
        # Recheck the identity before promising that this exact evidence
        # directory, rather than a replacement, will be preserved.
        self._assert_manager_roots()
        try:
            path_stat = active.path.lstat()
        except OSError as exc:
            raise IntegrityError("workspace is unavailable during detach") from exc
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or not stat.S_ISDIR(path_stat.st_mode)
            or (path_stat.st_dev, path_stat.st_ino) != active._workspace_identity
        ):
            raise IntegrityError("workspace was replaced before detach")
        with self._lock:
            current = self._active.get(active.path)
            if current is not active:
                raise LifecycleError("workspace handle is not active for this manager")
            self._active.pop(active.path)
            self._detached[active.path] = active

    def preserve(self, handle: WorkspaceHandle) -> None:
        """Relinquish a handle without touching disk or trusting path identity.

        This is the fail-safe counterpart to :meth:`detach`: callers use it
        only after identity-checked detach itself failed while evidence must not
        be deleted by :meth:`close`.  It validates ownership in memory and makes
        no claim about the current filesystem object.
        """

        if not isinstance(handle, WorkspaceHandle):
            raise LifecycleError("workspace handle has the wrong type")
        with self._lock:
            if self._detached.get(handle.path) is handle:
                return
            active = self._active.get(handle.path)
            if (
                active is not handle
                or handle._manager_token != self._token
                or handle.project_root != self.project_root
            ):
                raise LifecycleError(
                    "workspace handle is not active for this manager"
                )
            self._active.pop(handle.path)
            self._detached[handle.path] = handle

    def cleanup_orphans(
        self, preserve_experiment_ids: Iterable[str] = ()
    ) -> tuple[str, ...]:
        """Remove every unmanaged direct child of the dedicated workspace root.

        Callers must hold the project workflow lock.  Research OS v1 permits a
        single local worker, so any directory not owned by this manager is a
        residue from an interrupted process.  Every identity is rechecked by
        ``_remove_workspace_path`` before it is quarantined and deleted.
        """

        preserve_prefixes: list[str] = []
        for experiment_id in preserve_experiment_ids:
            try:
                safe_id = self._validate_experiment_id(experiment_id)
            except ConfigurationError:
                # An unsafe legacy identity could never have been created by
                # this manager, so it has no legitimate workspace prefix.
                continue
            preserve_prefixes.append(f"{safe_id}-")
        self._assert_manager_roots()
        root_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        root_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        root_fd = os.open(self.workspaces_root, root_flags)
        try:
            opened = os.fstat(root_fd)
            if (opened.st_dev, opened.st_ino) != self._workspaces_identity:
                raise IntegrityError("workspace root changed during orphan cleanup")
            with os.scandir(root_fd) as scanner:
                entries = sorted(
                    (
                        entry.name,
                        entry.stat(follow_symlinks=False),
                    )
                    for entry in scanner
                )
        finally:
            os.close(root_fd)

        with self._lock:
            preserved = {**self._active, **self._detached}
        removed: list[str] = []
        for name, entry_stat in entries:
            path = self.workspaces_root / name
            if any(name.startswith(prefix) for prefix in preserve_prefixes):
                # A prior terminal event explicitly retained this path as
                # untrusted evidence.  Do not follow, inspect, or mutate it.
                continue
            if handle := preserved.get(path):
                if (
                    stat.S_ISLNK(entry_stat.st_mode)
                    or not stat.S_ISDIR(entry_stat.st_mode)
                    or (entry_stat.st_dev, entry_stat.st_ino)
                    != handle._workspace_identity
                ):
                    raise IntegrityError(
                        f"preserved workspace changed identity: {name}"
                    )
                continue
            if stat.S_ISLNK(entry_stat.st_mode) or not stat.S_ISDIR(entry_stat.st_mode):
                raise IntegrityError(
                    f"workspace root contains an unsafe orphan entry: {name}"
                )
            self._remove_workspace_path(
                path,
                expected_identity=(entry_stat.st_dev, entry_stat.st_ino),
            )
            removed.append(name)
        return tuple(removed)

    @contextmanager
    def workspace(self, experiment_id: str) -> Iterator[WorkspaceHandle]:
        """Context-manager convenience that always attempts safe cleanup."""

        handle = self.create(experiment_id)
        try:
            yield handle
        except BaseException as primary:
            try:
                self.cleanup(handle)
            except BaseException as cleanup_error:
                _attach_cleanup_note(
                    primary,
                    cleanup_error,
                    context=f"workspace cleanup failed for {handle.path.name}",
                )
            raise
        else:
            self.cleanup(handle)

    def close(self) -> None:
        """Best-effort removal of all workspaces owned by this manager."""

        with self._lock:
            handles = list(self._active.values())
        failures: list[str] = []
        for handle in handles:
            try:
                self.cleanup(handle)
            except (IntegrityError, LifecycleError, OSError) as exc:
                failures.append(f"{handle.path.name}: {exc}")
        if failures:
            raise LifecycleError("workspace cleanup failed: " + "; ".join(failures))


# Clear, discoverable aliases for callers that use digest terminology.
sha256_file = hash_file
hash_project_tree = hash_tree


__all__ = [
    "WorkspaceHandle",
    "WorkspaceChange",
    "WorkspaceEntry",
    "WorkspaceManager",
    "fingerprint_path",
    "hash_file",
    "hash_project_tree",
    "hash_tree",
    "sha256_file",
]
