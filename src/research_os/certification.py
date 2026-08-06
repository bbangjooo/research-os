"""Local evaluator-review certifications bound to immutable project inputs.

The certification file is deliberately outside baseline compatibility and
experiment workspaces.  It is a change-control gate for agent-driven research,
not an evaluator input and not canonical experiment evidence.
"""

from __future__ import annotations

import fcntl
import os
import secrets
import stat
import threading
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Final, Iterator

from research_os.agent import load_agent_spec
from research_os.config import ProjectConfig, ensure_runtime_directory
from research_os.contracts import canonical_json_bytes, decode_json_object, sha256_json
from research_os.errors import (
    ConfigurationError,
    EvaluatorCertificationError,
    IntegrityError,
)
from research_os.provenance import project_fingerprints

EVALUATOR_CERTIFICATION_RELATIVE: Final = Path(".research-os/evaluator-certification.json")
EVALUATOR_REVIEW_KIND: Final = "research-os-evaluator-review"
EVALUATOR_REVIEW_SUBJECT_KIND: Final = "research-os-evaluator-review-subject"
EVALUATOR_CERTIFICATION_KIND: Final = "research-os-evaluator-certification"
EVALUATOR_CERTIFICATION_SCHEMA_VERSION: Final = 1

REQUIRED_EVALUATOR_CHECK_IDS: Final = frozenset(
    {
        "evidence_isolation",
        "evaluation_timing_or_causality",
        "outcome_accounting",
        "cost_and_resource_model",
        "metric_semantics",
        "constraint_semantics",
        "candidate_contract",
        "deterministic_golden_cases",
        "external_state_isolation",
    }
)
CERTIFICATION_BINDING_KEYS: Final = (
    "constitution",
    "protected",
    "evidence",
    "environment",
    "agent_spec",
    "adapter",
    "effective_compatibility",
)
_SOURCE_BINDING_KEYS: Final = CERTIFICATION_BINDING_KEYS[:5]

_CONTROL_DIR: Final = ".research-os"
_RUNTIME_DIR: Final = "runtime"
_CERTIFICATION_NAME: Final = EVALUATOR_CERTIFICATION_RELATIVE.name
_CERTIFICATION_LOCK_NAME: Final = "evaluator-certification.lock"
_GITIGNORE_NAME: Final = ".gitignore"
_GITIGNORE_ENTRY: Final = "evaluator-certification.json"
_MAX_REVIEW_BYTES: Final = 256 * 1024
_MAX_CERTIFICATION_BYTES: Final = 2 * 1024 * 1024
_CERTIFICATION_LOCK_STATE = threading.local()
_REVIEW_FIELDS: Final = frozenset(
    {
        "schema_version",
        "kind",
        "subject_digest",
        "reviewer",
        "independent_reviewer",
        "verdict",
        "summary",
        "checks",
        "blocking_findings",
    }
)
_CHECK_FIELDS: Final = frozenset({"id", "status", "evidence"})
_CERTIFICATION_FIELDS: Final = frozenset(
    {
        "schema_version",
        "kind",
        "project_id",
        "certified",
        "review",
        "review_digest",
        "bindings",
        "digest",
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


def _assert_private_single_link(
    info: os.stat_result,
    *,
    label: str,
) -> None:
    if info.st_uid != os.geteuid():
        raise IntegrityError(f"{label} must be owned by the current user")
    if info.st_nlink != 1:
        raise IntegrityError(f"{label} must have exactly one hard link")
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise IntegrityError(f"{label} must not be group- or world-writable")


def _assert_trusted_directory(info: os.stat_result, *, label: str) -> None:
    if not stat.S_ISDIR(info.st_mode):
        raise IntegrityError(f"{label} must be a directory")
    if info.st_uid != os.geteuid():
        raise IntegrityError(f"{label} must be owned by the current user")
    if stat.S_IMODE(info.st_mode) & 0o022:
        raise IntegrityError(f"{label} must not be group- or world-writable")


def _directory_flags() -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    return flags | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _file_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("short write while recording evaluator certification")
        offset += written


def _decode_object(data: bytes, *, label: str, error_type: type[Exception]) -> dict[str, Any]:
    try:
        text = data.decode("utf-8")
        return dict(decode_json_object(text))
    except (UnicodeDecodeError, TypeError, ValueError) as exc:
        raise error_type(f"{label} must be one strict UTF-8 JSON object: {exc}") from exc


def _read_bounded_regular_json(
    path: str | os.PathLike[str] | Path,
    *,
    label: str,
    max_bytes: int,
) -> dict[str, Any]:
    """Read one explicitly supplied JSON file without following its leaf."""

    supplied = Path(path).expanduser()
    absolute = Path(os.path.abspath(os.fspath(supplied)))
    descriptor = -1
    try:
        before = absolute.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise ConfigurationError(f"{label} must be a regular, non-symlink file")
        if before.st_size > max_bytes:
            raise ConfigurationError(f"{label} exceeds the {max_bytes} byte limit")
        descriptor = os.open(absolute, _file_flags())
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (before.st_dev, before.st_ino):
            raise IntegrityError(f"{label} changed while opening")
        data = bytearray()
        while block := os.read(descriptor, 64 * 1024):
            data.extend(block)
            if len(data) > max_bytes:
                raise ConfigurationError(f"{label} exceeds the {max_bytes} byte limit")
        after_descriptor = os.fstat(descriptor)
        after_path = absolute.lstat()
        if _stable_stat(after_descriptor) != _stable_stat(opened) or _stable_stat(
            after_path
        ) != _stable_stat(opened):
            raise IntegrityError(f"{label} changed while reading")
    except FileNotFoundError as exc:
        raise ConfigurationError(f"{label} is unavailable: {absolute}") from exc
    except (ConfigurationError, IntegrityError):
        raise
    except OSError as exc:
        raise IntegrityError(f"cannot safely read {label}: {absolute}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    return _decode_object(bytes(data), label=label, error_type=ConfigurationError)


def _assert_review_outside_project(
    config: ProjectConfig,
    review_path: str | os.PathLike[str] | Path,
) -> None:
    try:
        project_root = config.root.resolve(strict=True)
        review = Path(review_path).expanduser().resolve(strict=True)
    except OSError as exc:
        raise ConfigurationError(f"evaluator review is unavailable: {review_path}") from exc
    if review == project_root or project_root in review.parents:
        raise ConfigurationError(
            "evaluator review must be stored outside the project root so review I/O "
            "cannot change the project snapshot"
        )


@contextmanager
def _certification_lock(
    config: ProjectConfig,
    *,
    exclusive: bool,
) -> Iterator[None]:
    """Serialize every managed certification read/write across processes."""

    try:
        project_key = os.fspath(config.root.resolve(strict=True))
    except OSError as exc:
        raise IntegrityError(
            f"cannot resolve evaluator certification project root: {exc}"
        ) from exc
    process_id = os.getpid()
    if getattr(_CERTIFICATION_LOCK_STATE, "process_id", None) != process_id:
        _CERTIFICATION_LOCK_STATE.process_id = process_id
        _CERTIFICATION_LOCK_STATE.held = {}
    held = _CERTIFICATION_LOCK_STATE.held
    assert isinstance(held, dict)
    current = held.get(project_key)
    if current is not None:
        held_exclusive, depth = current
        if held_exclusive or exclusive:
            raise IntegrityError(
                "evaluator certification lock re-entry would deadlock; fresh doctor "
                "callbacks must not acquire certification locks"
            )
        held[project_key] = (False, depth + 1)
        try:
            yield
        finally:
            nested = held.get(project_key)
            if nested is not None:
                _, nested_depth = nested
                if nested_depth <= 1:
                    held.pop(project_key, None)
                else:
                    held[project_key] = (False, nested_depth - 1)
        return

    runtime = ensure_runtime_directory(config)
    path = runtime / _CERTIFICATION_LOCK_NAME
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    registered = False
    try:
        try:
            before = path.lstat()
        except FileNotFoundError:
            before = None
        if before is not None:
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
                raise IntegrityError("evaluator certification lock must be a regular file")
            _assert_private_single_link(before, label="evaluator certification lock")
        descriptor = os.open(path, flags, 0o600)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise IntegrityError("evaluator certification lock must be a regular file")
        _assert_private_single_link(opened, label="evaluator certification lock")
        if before is not None and (opened.st_dev, opened.st_ino) != (
            before.st_dev,
            before.st_ino,
        ):
            raise IntegrityError("evaluator certification lock changed while opening")
        fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        after_path = path.lstat()
        after_descriptor = os.fstat(descriptor)
        _assert_private_single_link(
            after_descriptor,
            label="evaluator certification lock",
        )
        if (
            (after_path.st_dev, after_path.st_ino)
            != (after_descriptor.st_dev, after_descriptor.st_ino)
            or _stable_stat(after_descriptor) != _stable_stat(opened)
        ):
            raise IntegrityError("evaluator certification lock changed while acquiring")
        held[project_key] = (exclusive, 1)
        registered = True
        yield
    except (ConfigurationError, IntegrityError):
        raise
    except OSError as exc:
        raise IntegrityError(f"cannot safely lock evaluator certification: {exc}") from exc
    finally:
        if registered:
            held.pop(project_key, None)
        if descriptor >= 0:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _ensure_certification_gitignore_unlocked(config: ProjectConfig) -> bool:
    """Migrate legacy control ignores without discarding user entries."""

    root_fd = -1
    control_fd = -1
    file_fd = -1
    temp_fd = -1
    temp_name: str | None = None
    temp_identity: tuple[int, int] | None = None
    try:
        root_fd, control_fd, root_opened, control_opened = _open_control_directory(
            config.root
        )
        try:
            before = os.stat(_GITIGNORE_NAME, dir_fd=control_fd, follow_symlinks=False)
        except FileNotFoundError:
            before = None
        data = b""
        if before is not None:
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
                raise IntegrityError("certification .gitignore must be a regular file")
            _assert_private_single_link(before, label="certification .gitignore")
            if before.st_size > _MAX_REVIEW_BYTES:
                raise IntegrityError("certification .gitignore is unreasonably large")
            file_fd = os.open(_GITIGNORE_NAME, _file_flags(), dir_fd=control_fd)
            opened = os.fstat(file_fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise IntegrityError("certification .gitignore changed while opening")
            chunks = bytearray()
            while block := os.read(file_fd, 64 * 1024):
                chunks.extend(block)
                if len(chunks) > _MAX_REVIEW_BYTES:
                    raise IntegrityError("certification .gitignore is unreasonably large")
            data = bytes(chunks)
            after_descriptor = os.fstat(file_fd)
            after_path = os.stat(
                _GITIGNORE_NAME,
                dir_fd=control_fd,
                follow_symlinks=False,
            )
            if (
                _stable_stat(after_descriptor) != _stable_stat(opened)
                or _stable_stat(after_path) != _stable_stat(opened)
            ):
                raise IntegrityError("certification .gitignore changed while reading")
            os.close(file_fd)
            file_fd = -1
        if _GITIGNORE_ENTRY.encode("utf-8") in data.splitlines():
            _verify_control_directory(
                config.root,
                root_fd,
                control_fd,
                root_opened,
                control_opened,
            )
            return False

        updated = data
        if updated and not updated.endswith(b"\n"):
            updated += b"\n"
        updated += _GITIGNORE_ENTRY.encode("utf-8") + b"\n"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        for _ in range(16):
            candidate = f".{_GITIGNORE_NAME}.{secrets.token_hex(12)}.tmp"
            try:
                temp_fd = os.open(candidate, flags, 0o600, dir_fd=control_fd)
            except FileExistsError:
                continue
            temp_name = candidate
            break
        if temp_fd < 0 or temp_name is None:
            raise IntegrityError("could not reserve a certification .gitignore temp file")
        temp_info = os.fstat(temp_fd)
        temp_identity = (temp_info.st_dev, temp_info.st_ino)
        os.fchmod(temp_fd, 0o600)
        _assert_private_single_link(temp_info, label="certification .gitignore temp file")
        _write_all(temp_fd, updated)
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = -1

        _verify_control_directory(
            config.root,
            root_fd,
            control_fd,
            root_opened,
            control_opened,
        )
        try:
            current = os.stat(_GITIGNORE_NAME, dir_fd=control_fd, follow_symlinks=False)
        except FileNotFoundError:
            current = None
        if before is None:
            if current is not None:
                raise IntegrityError("certification .gitignore appeared while migrating")
        elif current is None or _stable_stat(current) != _stable_stat(before):
            raise IntegrityError("certification .gitignore changed while migrating")
        os.replace(
            temp_name,
            _GITIGNORE_NAME,
            src_dir_fd=control_fd,
            dst_dir_fd=control_fd,
        )
        temp_name = None
        os.fsync(control_fd)
        return True
    except (ConfigurationError, IntegrityError):
        raise
    except OSError as exc:
        raise IntegrityError(f"cannot safely migrate certification .gitignore: {exc}") from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_name is not None and temp_identity is not None and control_fd >= 0:
            try:
                current = os.stat(temp_name, dir_fd=control_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == temp_identity:
                    os.unlink(temp_name, dir_fd=control_fd)
            except OSError:
                pass
        if control_fd >= 0:
            os.close(control_fd)
        if root_fd >= 0:
            os.close(root_fd)


def ensure_certification_gitignore(config: ProjectConfig) -> bool:
    """Idempotently reserve the managed certificate path in legacy projects."""

    with _certification_lock(config, exclusive=True):
        return _ensure_certification_gitignore_unlocked(config)


@contextmanager
def evaluator_certification_read_lock(config: ProjectConfig) -> Iterator[None]:
    """Keep the managed certification stable across a guarded event append."""

    with _certification_lock(config, exclusive=False):
        yield


def _open_control_directory(root: Path) -> tuple[int, int, os.stat_result, os.stat_result]:
    root_fd = -1
    control_fd = -1
    try:
        canonical_root = root.resolve(strict=True)
        root_before = canonical_root.lstat()
        if stat.S_ISLNK(root_before.st_mode) or not stat.S_ISDIR(root_before.st_mode):
            raise IntegrityError("certification project root must be a non-symlink directory")
        root_fd = os.open(canonical_root, _directory_flags())
        root_opened = os.fstat(root_fd)
        if not stat.S_ISDIR(root_opened.st_mode) or (
            root_opened.st_dev,
            root_opened.st_ino,
        ) != (root_before.st_dev, root_before.st_ino):
            raise IntegrityError("certification project root changed while opening")
        _assert_trusted_directory(
            root_opened,
            label="certification project root",
        )

        control_before = os.stat(_CONTROL_DIR, dir_fd=root_fd, follow_symlinks=False)
        if stat.S_ISLNK(control_before.st_mode) or not stat.S_ISDIR(control_before.st_mode):
            raise IntegrityError("certification control path must be a non-symlink directory")
        control_fd = os.open(_CONTROL_DIR, _directory_flags(), dir_fd=root_fd)
        control_opened = os.fstat(control_fd)
        if not stat.S_ISDIR(control_opened.st_mode) or (
            control_opened.st_dev,
            control_opened.st_ino,
        ) != (control_before.st_dev, control_before.st_ino):
            raise IntegrityError("certification control path changed while opening")
        _assert_trusted_directory(
            control_opened,
            label="certification control directory",
        )
        return root_fd, control_fd, root_opened, control_opened
    except BaseException:
        if control_fd >= 0:
            os.close(control_fd)
        if root_fd >= 0:
            os.close(root_fd)
        raise


def _verify_control_directory(
    root: Path,
    root_fd: int,
    control_fd: int,
    root_opened: os.stat_result,
    control_opened: os.stat_result,
) -> None:
    control_after = os.stat(_CONTROL_DIR, dir_fd=root_fd, follow_symlinks=False)
    root_after = root.lstat()
    control_descriptor = os.fstat(control_fd)
    _assert_trusted_directory(
        control_descriptor,
        label="certification control directory",
    )
    if (
        not stat.S_ISDIR(control_after.st_mode)
        or (control_after.st_dev, control_after.st_ino)
        != (control_opened.st_dev, control_opened.st_ino)
        or (control_descriptor.st_dev, control_descriptor.st_ino)
        != (control_opened.st_dev, control_opened.st_ino)
    ):
        raise IntegrityError("certification control path changed while in use")
    root_descriptor = os.fstat(root_fd)
    _assert_trusted_directory(
        root_descriptor,
        label="certification project root",
    )
    if (
        not stat.S_ISDIR(root_after.st_mode)
        or (root_after.st_dev, root_after.st_ino) != (root_opened.st_dev, root_opened.st_ino)
        or (root_descriptor.st_dev, root_descriptor.st_ino)
        != (root_opened.st_dev, root_opened.st_ino)
    ):
        raise IntegrityError("certification project root changed while in use")


def _open_runtime_directory(control_fd: int) -> tuple[int, os.stat_result]:
    """Open the excluded runtime directory for transaction-private files."""

    before = os.stat(_RUNTIME_DIR, dir_fd=control_fd, follow_symlinks=False)
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise IntegrityError("certification runtime path must be a non-symlink directory")
    _assert_trusted_directory(before, label="certification runtime directory")
    descriptor = os.open(_RUNTIME_DIR, _directory_flags(), dir_fd=control_fd)
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(opened.st_mode)
            or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise IntegrityError("certification runtime path changed while opening")
        _assert_trusted_directory(opened, label="certification runtime directory")
        return descriptor, opened
    except BaseException:
        os.close(descriptor)
        raise


def _verify_runtime_directory(
    control_fd: int,
    runtime_fd: int,
    opened: os.stat_result,
) -> None:
    after = os.stat(_RUNTIME_DIR, dir_fd=control_fd, follow_symlinks=False)
    descriptor = os.fstat(runtime_fd)
    _assert_trusted_directory(descriptor, label="certification runtime directory")
    if (
        not stat.S_ISDIR(after.st_mode)
        or (after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
        or (descriptor.st_dev, descriptor.st_ino) != (opened.st_dev, opened.st_ino)
    ):
        raise IntegrityError("certification runtime path changed while in use")


def _fsync_certification_directories(control_fd: int, runtime_fd: int) -> None:
    """Persist a cross-directory publication or rollback."""

    os.fsync(control_fd)
    os.fsync(runtime_fd)


def _read_certification_bytes(root: Path) -> bytes | None:
    root_fd = -1
    control_fd = -1
    file_fd = -1
    try:
        root_fd, control_fd, root_opened, control_opened = _open_control_directory(root)
        try:
            before = os.stat(
                _CERTIFICATION_NAME,
                dir_fd=control_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            _verify_control_directory(root, root_fd, control_fd, root_opened, control_opened)
            return None
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise IntegrityError("evaluator certification must be a regular file")
        _assert_private_single_link(before, label="evaluator certification")
        if before.st_size > _MAX_CERTIFICATION_BYTES:
            raise IntegrityError(
                f"evaluator certification exceeds the {_MAX_CERTIFICATION_BYTES} byte limit"
            )
        file_fd = os.open(_CERTIFICATION_NAME, _file_flags(), dir_fd=control_fd)
        opened = os.fstat(file_fd)
        if not stat.S_ISREG(opened.st_mode) or (
            opened.st_dev,
            opened.st_ino,
        ) != (before.st_dev, before.st_ino):
            raise IntegrityError("evaluator certification changed while opening")
        _assert_private_single_link(opened, label="evaluator certification")
        data = bytearray()
        while block := os.read(file_fd, 64 * 1024):
            data.extend(block)
            if len(data) > _MAX_CERTIFICATION_BYTES:
                raise IntegrityError(
                    f"evaluator certification exceeds the {_MAX_CERTIFICATION_BYTES} byte limit"
                )
        after_descriptor = os.fstat(file_fd)
        after_path = os.stat(
            _CERTIFICATION_NAME,
            dir_fd=control_fd,
            follow_symlinks=False,
        )
        _assert_private_single_link(after_descriptor, label="evaluator certification")
        _assert_private_single_link(after_path, label="evaluator certification")
        if _stable_stat(after_descriptor) != _stable_stat(opened) or _stable_stat(
            after_path
        ) != _stable_stat(opened):
            raise IntegrityError("evaluator certification changed while reading")
        _verify_control_directory(root, root_fd, control_fd, root_opened, control_opened)
        return bytes(data)
    except IntegrityError:
        raise
    except OSError as exc:
        raise IntegrityError(f"cannot safely read evaluator certification: {exc}") from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if control_fd >= 0:
            os.close(control_fd)
        if root_fd >= 0:
            os.close(root_fd)


def _write_certification_bytes(
    root: Path,
    data: bytes,
    *,
    replace: bool,
    before_publish: Callable[[], None] | None = None,
    after_publish: Callable[[], None] | None = None,
) -> None:
    root_fd = -1
    control_fd = -1
    runtime_fd = -1
    temp_fd = -1
    temp_name: str | None = None
    temp_identity: tuple[int, int] | None = None
    recovery_name: str | None = None
    recovery_identity: tuple[int, int] | None = None
    publication_attempted = False
    try:
        root_fd, control_fd, root_opened, control_opened = _open_control_directory(root)
        runtime_fd, runtime_opened = _open_runtime_directory(control_fd)
        try:
            current = os.stat(
                _CERTIFICATION_NAME,
                dir_fd=control_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            current = None
        if current is not None and (
            stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode)
        ):
            raise IntegrityError("refusing to replace an unsafe evaluator certification")
        if current is not None:
            _assert_private_single_link(current, label="existing evaluator certification")
            if not replace:
                raise ConfigurationError(
                    "evaluator certification already exists; pass replace=True to replace it"
                )

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        for _ in range(16):
            candidate = f".{_CERTIFICATION_NAME}.{secrets.token_hex(12)}.tmp"
            try:
                temp_fd = os.open(candidate, flags, 0o600, dir_fd=runtime_fd)
            except FileExistsError:
                continue
            temp_name = candidate
            break
        if temp_fd < 0 or temp_name is None:
            raise IntegrityError("could not reserve an evaluator certification temp file")
        temp_info = os.fstat(temp_fd)
        temp_identity = (temp_info.st_dev, temp_info.st_ino)
        os.fchmod(temp_fd, 0o600)
        _assert_private_single_link(os.fstat(temp_fd), label="evaluator certification temp file")
        _write_all(temp_fd, data)
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = -1

        _verify_control_directory(root, root_fd, control_fd, root_opened, control_opened)
        _verify_runtime_directory(control_fd, runtime_fd, runtime_opened)
        before_replace = os.stat(temp_name, dir_fd=runtime_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(before_replace.st_mode)
            or (before_replace.st_dev, before_replace.st_ino) != temp_identity
        ):
            raise IntegrityError("evaluator certification temp file was replaced")
        _assert_private_single_link(before_replace, label="evaluator certification temp file")
        try:
            destination = os.stat(
                _CERTIFICATION_NAME,
                dir_fd=control_fd,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            destination = None
        if destination is not None and (
            stat.S_ISLNK(destination.st_mode) or not stat.S_ISREG(destination.st_mode)
        ):
            raise IntegrityError("refusing to replace an unsafe evaluator certification")
        if destination is not None:
            _assert_private_single_link(destination, label="existing evaluator certification")
        if current is None:
            if destination is not None:
                raise IntegrityError("evaluator certification appeared while preparing publication")
        elif destination is None or _stable_stat(destination) != _stable_stat(current):
            raise IntegrityError("evaluator certification changed while preparing publication")
        if before_publish is not None:
            # The candidate remains private and unpublished until every live
            # binding has passed its final freshness check.  A failure here
            # therefore preserves the prior certification inode verbatim.
            before_publish()
            _verify_control_directory(
                root,
                root_fd,
                control_fd,
                root_opened,
                control_opened,
            )
            _verify_runtime_directory(control_fd, runtime_fd, runtime_opened)
        replacing_existing = replace and current is not None
        if replacing_existing:
            # Keep the exact prior inode recoverable until the post-publication
            # live-binding check succeeds.  The certification lock excludes
            # managed readers while the prior file temporarily has two links.
            assert current is not None
            current_identity = (current.st_dev, current.st_ino)
            for _ in range(16):
                candidate = f".{_CERTIFICATION_NAME}.{secrets.token_hex(12)}.rollback"
                # Assign before the syscall so a success followed by an
                # asynchronous exception is still cleaned up by ``finally``.
                recovery_name = candidate
                recovery_identity = current_identity
                try:
                    os.link(
                        _CERTIFICATION_NAME,
                        candidate,
                        src_dir_fd=control_fd,
                        dst_dir_fd=runtime_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError:
                    recovery_name = None
                    recovery_identity = None
                    continue
                break
            if recovery_name is None:
                raise IntegrityError(
                    "could not reserve evaluator certification rollback link"
                )
            recovery = os.stat(
                recovery_name,
                dir_fd=runtime_fd,
                follow_symlinks=False,
            )
            destination = os.stat(
                _CERTIFICATION_NAME,
                dir_fd=control_fd,
                follow_symlinks=False,
            )
            if (
                (recovery.st_dev, recovery.st_ino) != current_identity
                or (destination.st_dev, destination.st_ino) != current_identity
                or recovery.st_nlink != 2
                or destination.st_nlink != 2
            ):
                raise IntegrityError(
                    "existing evaluator certification changed while reserving rollback"
                )
            if recovery.st_uid != os.geteuid() or stat.S_IMODE(recovery.st_mode) & 0o022:
                raise IntegrityError("evaluator certification rollback link is unsafe")
            os.fsync(runtime_fd)
        publication_attempted = True
        try:
            if replacing_existing:
                os.replace(
                    temp_name,
                    _CERTIFICATION_NAME,
                    src_dir_fd=runtime_fd,
                    dst_dir_fd=control_fd,
                )
                temp_name = None
            else:
                try:
                    os.link(
                        temp_name,
                        _CERTIFICATION_NAME,
                        src_dir_fd=runtime_fd,
                        dst_dir_fd=control_fd,
                        follow_symlinks=False,
                    )
                except FileExistsError as exc:
                    raise ConfigurationError(
                        "evaluator certification appeared while recording; "
                        "pass replace=True to replace it"
                    ) from exc
                os.unlink(temp_name, dir_fd=runtime_fd)
                temp_name = None
            _fsync_certification_directories(control_fd, runtime_fd)
            recorded = os.stat(
                _CERTIFICATION_NAME,
                dir_fd=control_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(recorded.st_mode)
                or (recorded.st_dev, recorded.st_ino) != temp_identity
                or stat.S_IMODE(recorded.st_mode) != 0o600
            ):
                raise IntegrityError("recorded evaluator certification is not the written file")
            _assert_private_single_link(recorded, label="recorded evaluator certification")
            _verify_control_directory(root, root_fd, control_fd, root_opened, control_opened)
            if after_publish is not None:
                after_publish()
            committed = os.stat(
                _CERTIFICATION_NAME,
                dir_fd=control_fd,
                follow_symlinks=False,
            )
            if (
                not stat.S_ISREG(committed.st_mode)
                or (committed.st_dev, committed.st_ino) != temp_identity
                or stat.S_IMODE(committed.st_mode) != 0o600
            ):
                raise IntegrityError(
                    "evaluator certification changed during post-publication validation"
                )
            _assert_private_single_link(
                committed,
                label="post-validated evaluator certification",
            )
            _verify_control_directory(
                root,
                root_fd,
                control_fd,
                root_opened,
                control_opened,
            )
            _verify_runtime_directory(control_fd, runtime_fd, runtime_opened)
        except BaseException as publication_error:
            # Publication is provisional until the complete live binding has
            # been recomputed.  Restore the exact prior inode on replacement,
            # or remove a first publication, before exposing the failure.
            try:
                try:
                    recorded = os.stat(
                        _CERTIFICATION_NAME,
                        dir_fd=control_fd,
                        follow_symlinks=False,
                    )
                except FileNotFoundError:
                    recorded = None
                if replacing_existing:
                    if recovery_name is None or recovery_identity is None:
                        raise IntegrityError(
                            "evaluator certification rollback link is unavailable"
                        )
                    recovery = os.stat(
                        recovery_name,
                        dir_fd=runtime_fd,
                        follow_symlinks=False,
                    )
                    if (recovery.st_dev, recovery.st_ino) != recovery_identity:
                        raise IntegrityError(
                            "evaluator certification rollback link changed"
                        )
                    recorded_identity = (
                        (recorded.st_dev, recorded.st_ino)
                        if recorded is not None
                        else None
                    )
                    if recorded_identity == temp_identity:
                        os.replace(
                            recovery_name,
                            _CERTIFICATION_NAME,
                            src_dir_fd=runtime_fd,
                            dst_dir_fd=control_fd,
                        )
                        recovery_name = None
                    elif recorded_identity == recovery_identity:
                        # The publication syscall failed before changing the
                        # destination.  Drop only our rollback hard link.
                        os.unlink(recovery_name, dir_fd=runtime_fd)
                        recovery_name = None
                    else:
                        raise IntegrityError(
                            "cannot restore a certification path changed during publication"
                        )
                    restored = os.stat(
                        _CERTIFICATION_NAME,
                        dir_fd=control_fd,
                        follow_symlinks=False,
                    )
                    if (restored.st_dev, restored.st_ino) != recovery_identity:
                        raise IntegrityError("prior evaluator certification was not restored")
                    _assert_private_single_link(
                        restored,
                        label="restored evaluator certification",
                    )
                else:
                    recorded_identity = (
                        (recorded.st_dev, recorded.st_ino)
                        if recorded is not None
                        else None
                    )
                    if recorded_identity == temp_identity:
                        os.unlink(_CERTIFICATION_NAME, dir_fd=control_fd)
                    elif recorded_identity is not None:
                        raise IntegrityError(
                            "cannot roll back a certification path changed during publication"
                        )
                publication_attempted = False
                _fsync_certification_directories(control_fd, runtime_fd)
                _verify_control_directory(
                    root,
                    root_fd,
                    control_fd,
                    root_opened,
                    control_opened,
                )
            except BaseException as rollback_error:
                raise IntegrityError(
                    "evaluator certification publication failed and rollback could not "
                    f"be verified: {rollback_error}"
                ) from publication_error
            raise

        # The post-validated, directory-synced new certificate is the commit
        # point.  Cleanup of an excluded recovery link is best effort: every
        # cleanup fault must either leave the prior inode recoverable or occur
        # after its unlink, and must never report that the committed write
        # failed.
        publication_attempted = False
        if recovery_name is not None:
            try:
                recovery = os.stat(
                    recovery_name,
                    dir_fd=runtime_fd,
                    follow_symlinks=False,
                )
                if recovery_identity is not None and (
                    recovery.st_dev,
                    recovery.st_ino,
                ) == recovery_identity:
                    os.unlink(recovery_name, dir_fd=runtime_fd)
                    recovery_name = None
                    os.fsync(runtime_fd)
            except BaseException:
                pass
    except IntegrityError:
        raise
    except OSError as exc:
        raise IntegrityError(f"cannot safely write evaluator certification: {exc}") from exc
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        if temp_name is not None and temp_identity is not None and runtime_fd >= 0:
            try:
                current = os.stat(temp_name, dir_fd=runtime_fd, follow_symlinks=False)
                if (current.st_dev, current.st_ino) == temp_identity:
                    os.unlink(temp_name, dir_fd=runtime_fd)
                    os.fsync(runtime_fd)
            except BaseException:
                pass
        if recovery_name is not None and recovery_identity is not None and runtime_fd >= 0:
            try:
                recovery = os.stat(
                    recovery_name,
                    dir_fd=runtime_fd,
                    follow_symlinks=False,
                )
                # Never discard the only surviving copy of the prior
                # certification after a failed rollback.
                if (
                    (recovery.st_dev, recovery.st_ino) == recovery_identity
                    and not publication_attempted
                ):
                    os.unlink(recovery_name, dir_fd=runtime_fd)
                    os.fsync(runtime_fd)
            except BaseException:
                pass
        if runtime_fd >= 0:
            os.close(runtime_fd)
        if control_fd >= 0:
            os.close(control_fd)
        if root_fd >= 0:
            os.close(root_fd)


def _require_exact_fields(
    value: Mapping[str, Any], expected: frozenset[str], *, label: str
) -> None:
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise ConfigurationError(f"{label} has invalid fields: {'; '.join(details)}")


def _nonempty_text(value: Any, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field} must be a non-empty string")
    if "\x00" in value:
        raise ConfigurationError(f"{field} contains a NUL byte")
    return value


def _require_sha256(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ConfigurationError(f"{field} must be a lowercase SHA-256 digest")
    return value


def validate_evaluator_review(review: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize the independent evaluator-review contract."""

    value = dict(review)
    _require_exact_fields(value, _REVIEW_FIELDS, label="evaluator review")
    if value["schema_version"] != EVALUATOR_CERTIFICATION_SCHEMA_VERSION or isinstance(
        value["schema_version"], bool
    ):
        raise ConfigurationError("evaluator review schema_version must be 1")
    if value["kind"] != EVALUATOR_REVIEW_KIND:
        raise ConfigurationError(f"evaluator review kind must be {EVALUATOR_REVIEW_KIND!r}")
    _require_sha256(
        value["subject_digest"],
        field="evaluator review subject_digest",
    )
    _nonempty_text(value["reviewer"], field="evaluator review reviewer")
    if not isinstance(value["independent_reviewer"], bool):
        raise ConfigurationError("evaluator review independent_reviewer must be a boolean")
    if value["verdict"] not in {"PASS", "FAIL"}:
        raise ConfigurationError("evaluator review verdict must be 'PASS' or 'FAIL'")
    _nonempty_text(value["summary"], field="evaluator review summary")

    checks_value = value["checks"]
    if not isinstance(checks_value, Sequence) or isinstance(checks_value, (str, bytes, bytearray)):
        raise ConfigurationError("evaluator review checks must be an array")
    checks: list[dict[str, Any]] = []
    observed_ids: set[str] = set()
    for index, raw_check in enumerate(checks_value):
        if not isinstance(raw_check, Mapping):
            raise ConfigurationError(f"evaluator review checks[{index}] must be an object")
        check = dict(raw_check)
        _require_exact_fields(check, _CHECK_FIELDS, label=f"evaluator review checks[{index}]")
        check_id = _nonempty_text(check["id"], field=f"evaluator review checks[{index}].id")
        if check_id in observed_ids:
            raise ConfigurationError(f"evaluator review contains duplicate check {check_id!r}")
        observed_ids.add(check_id)
        if check["status"] not in {"PASS", "FAIL"}:
            raise ConfigurationError(
                f"evaluator review checks[{index}].status must be 'PASS' or 'FAIL'"
            )
        _nonempty_text(check["evidence"], field=f"evaluator review checks[{index}].evidence")
        checks.append(check)
    if observed_ids != REQUIRED_EVALUATOR_CHECK_IDS:
        missing = sorted(REQUIRED_EVALUATOR_CHECK_IDS - observed_ids)
        extra = sorted(observed_ids - REQUIRED_EVALUATOR_CHECK_IDS)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("unexpected " + ", ".join(extra))
        raise ConfigurationError(
            "evaluator review must contain the exact required checks: " + "; ".join(details)
        )

    blockers_value = value["blocking_findings"]
    if not isinstance(blockers_value, Sequence) or isinstance(
        blockers_value, (str, bytes, bytearray)
    ):
        raise ConfigurationError("evaluator review blocking_findings must be an array")
    blockers: list[str] = []
    for index, blocker in enumerate(blockers_value):
        blockers.append(
            _nonempty_text(
                blocker,
                field=f"evaluator review blocking_findings[{index}]",
            )
        )
    if len(set(blockers)) != len(blockers):
        raise ConfigurationError("evaluator review blocking_findings must be unique")

    # Check order is not semantically meaningful.  Normalizing it makes the
    # review and certification digests deterministic across reviewers/tools.
    value["checks"] = sorted(checks, key=lambda item: str(item["id"]))
    value["blocking_findings"] = blockers
    return value


def _review_certified(review: Mapping[str, Any]) -> bool:
    checks = review["checks"]
    assert isinstance(checks, Sequence)
    return bool(
        review["independent_reviewer"] is True
        and review["verdict"] == "PASS"
        and not review["blocking_findings"]
        and all(isinstance(check, Mapping) and check.get("status") == "PASS" for check in checks)
    )


def _source_binding_snapshot(
    config: ProjectConfig, fingerprints: Mapping[str, Any]
) -> dict[str, Any]:
    bindings: dict[str, Any] = {}
    for key in _SOURCE_BINDING_KEYS[:-1]:
        value = fingerprints.get(key)
        if not isinstance(value, Mapping):
            raise IntegrityError(f"project fingerprint omitted certification binding {key!r}")
        bindings[key] = dict(value)
    agent_spec = load_agent_spec(config.root)
    bound_agent_spec = {
        "brief_path": agent_spec["brief_path"],
        "candidate_schema_path": agent_spec["candidate_schema_path"],
        "brief": agent_spec["brief"],
        "candidate_schema": agent_spec["candidate_schema"],
    }
    bindings["agent_spec"] = {
        "digest": sha256_json(bound_agent_spec),
        "brief_path": agent_spec["brief_path"],
        "candidate_schema_path": agent_spec["candidate_schema_path"],
    }
    return bindings


def _doctor_binding_snapshot(
    config: ProjectConfig,
    fingerprints: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate and bind a complete fingerprint returned by ``doctor``."""

    bindings = _source_binding_snapshot(config, fingerprints)
    adapter = fingerprints.get("adapter")
    if not isinstance(adapter, Mapping):
        raise ConfigurationError(
            "recording evaluator certification requires doctor fingerprints with an adapter binding"
        )
    if frozenset(adapter) != frozenset({"digest", "value"}):
        raise IntegrityError("doctor adapter fingerprint has invalid fields")
    adapter_digest = adapter.get("digest")
    adapter_value = adapter.get("value")
    if (
        not isinstance(adapter_digest, str)
        or not isinstance(adapter_value, Mapping)
        or adapter_digest != sha256_json(adapter_value)
    ):
        raise IntegrityError("doctor adapter fingerprint seal is invalid")

    project_digest = fingerprints.get("project_compatibility_digest")
    effective_digest = fingerprints.get("compatibility_digest")
    if not isinstance(project_digest, str) or not isinstance(effective_digest, str):
        raise IntegrityError("doctor compatibility fingerprint is incomplete")
    expected_effective = sha256_json({"project": project_digest, "adapter": adapter_digest})
    if effective_digest != expected_effective:
        raise IntegrityError("doctor effective compatibility fingerprint is invalid")
    bindings["adapter"] = dict(adapter)
    bindings["effective_compatibility"] = {
        "digest": effective_digest,
        "project_digest": project_digest,
        "adapter_digest": adapter_digest,
    }
    return bindings


def _review_subject_from_bindings(
    config: ProjectConfig,
    bindings: Mapping[str, Any],
) -> dict[str, Any]:
    unsigned = {
        "schema_version": EVALUATOR_CERTIFICATION_SCHEMA_VERSION,
        "kind": EVALUATOR_REVIEW_SUBJECT_KIND,
        "project_id": config.project_id,
        "bindings": dict(bindings),
    }
    return {**unsigned, "digest": sha256_json(unsigned)}


def _assert_source_snapshot_matches_live(
    config: ProjectConfig,
    supplied: Mapping[str, Any],
    live: Mapping[str, Any],
) -> None:
    if _source_binding_snapshot(config, supplied) != _source_binding_snapshot(
        config,
        live,
    ) or supplied.get("compatibility_digest") != live.get("compatibility_digest"):
        raise IntegrityError("supplied project fingerprints disagree with current project inputs")


def build_evaluator_review_subject(
    config: ProjectConfig,
    *,
    fingerprints: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the exact immutable subject an independent critic must review."""

    with _certification_lock(config, exclusive=True):
        _ensure_certification_gitignore_unlocked(config)
        live = project_fingerprints(config)
        _assert_doctor_matches_source(config, fingerprints, live)
        return _review_subject_from_bindings(
            config,
            _doctor_binding_snapshot(config, fingerprints),
        )


def _source_only_binding_snapshot(
    config: ProjectConfig,
    fingerprints: Mapping[str, Any],
    stored_bindings: Mapping[str, Any],
) -> dict[str, Any]:
    """Refresh source bindings while retaining the last doctor adapter seal."""

    bindings = _source_binding_snapshot(config, fingerprints)
    adapter = stored_bindings.get("adapter")
    if not isinstance(adapter, Mapping):
        raise IntegrityError("stored evaluator certification omitted its adapter binding")
    adapter_digest = adapter.get("digest")
    project_digest = fingerprints.get("compatibility_digest")
    if not isinstance(adapter_digest, str) or not isinstance(project_digest, str):
        raise IntegrityError("source-only certification comparison is incomplete")
    bindings["adapter"] = dict(adapter)
    bindings["effective_compatibility"] = {
        "digest": sha256_json({"project": project_digest, "adapter": adapter_digest}),
        "project_digest": project_digest,
        "adapter_digest": adapter_digest,
    }
    return bindings


def _assert_doctor_matches_source(
    config: ProjectConfig,
    doctor_fingerprints: Mapping[str, Any],
    source_fingerprints: Mapping[str, Any],
) -> None:
    if _source_binding_snapshot(config, doctor_fingerprints) != _source_binding_snapshot(
        config, source_fingerprints
    ):
        raise IntegrityError("doctor fingerprints disagree with current project inputs")
    if doctor_fingerprints.get("project_compatibility_digest") != source_fingerprints.get(
        "compatibility_digest"
    ):
        raise IntegrityError("doctor project compatibility disagrees with current project inputs")


def _build_artifact(
    config: ProjectConfig,
    review: Mapping[str, Any],
    bindings: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_review = validate_evaluator_review(review)
    unsigned: dict[str, Any] = {
        "schema_version": EVALUATOR_CERTIFICATION_SCHEMA_VERSION,
        "kind": EVALUATOR_CERTIFICATION_KIND,
        "project_id": config.project_id,
        "certified": _review_certified(normalized_review),
        "review": normalized_review,
        "review_digest": sha256_json(normalized_review),
        "bindings": dict(bindings),
    }
    return {**unsigned, "digest": sha256_json(unsigned)}


def _parse_artifact(data: bytes, config: ProjectConfig) -> dict[str, Any]:
    artifact = _decode_object(
        data,
        label="evaluator certification",
        error_type=IntegrityError,
    )
    try:
        _require_exact_fields(artifact, _CERTIFICATION_FIELDS, label="evaluator certification")
    except ConfigurationError as exc:
        raise IntegrityError(str(exc)) from exc
    if artifact["schema_version"] != EVALUATOR_CERTIFICATION_SCHEMA_VERSION or isinstance(
        artifact["schema_version"], bool
    ):
        raise IntegrityError("evaluator certification schema_version must be 1")
    if artifact["kind"] != EVALUATOR_CERTIFICATION_KIND:
        raise IntegrityError(
            f"evaluator certification kind must be {EVALUATOR_CERTIFICATION_KIND!r}"
        )
    if artifact["project_id"] != config.project_id:
        raise IntegrityError("evaluator certification belongs to another project")
    if not isinstance(artifact["certified"], bool):
        raise IntegrityError("evaluator certification certified must be a boolean")
    review = artifact["review"]
    if not isinstance(review, Mapping):
        raise IntegrityError("evaluator certification review must be an object")
    try:
        normalized_review = validate_evaluator_review(review)
    except ConfigurationError as exc:
        raise IntegrityError(f"evaluator certification contains an invalid review: {exc}") from exc
    if dict(review) != normalized_review:
        raise IntegrityError("evaluator certification review is not canonically normalized")
    if artifact["review_digest"] != sha256_json(normalized_review):
        raise IntegrityError("evaluator certification review digest is invalid")
    if artifact["certified"] is not _review_certified(normalized_review):
        raise IntegrityError("evaluator certification decision disagrees with its review")
    bindings = artifact["bindings"]
    if not isinstance(bindings, Mapping) or frozenset(bindings) != frozenset(
        CERTIFICATION_BINDING_KEYS
    ):
        raise IntegrityError("evaluator certification bindings are invalid")
    expected_binding_fields = {
        "constitution": frozenset({"digest", "files"}),
        "protected": frozenset({"digest", "files"}),
        "evidence": frozenset({"digest", "files"}),
        "environment": frozenset({"digest", "value"}),
        "agent_spec": frozenset({"digest", "brief_path", "candidate_schema_path"}),
        "adapter": frozenset({"digest", "value"}),
        "effective_compatibility": frozenset({"digest", "project_digest", "adapter_digest"}),
    }
    for key in CERTIFICATION_BINDING_KEYS:
        binding = bindings[key]
        if not isinstance(binding, Mapping):
            raise IntegrityError(f"evaluator certification binding {key!r} is invalid")
        if frozenset(binding) != expected_binding_fields[key]:
            raise IntegrityError(f"evaluator certification binding {key!r} has invalid fields")
        digest = binding.get("digest")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise IntegrityError(f"evaluator certification binding {key!r} has an invalid digest")
    for key in ("constitution", "protected", "evidence"):
        if not isinstance(bindings[key].get("files"), list):
            raise IntegrityError(
                f"evaluator certification binding {key!r} has invalid file evidence"
            )
    if not isinstance(bindings["environment"].get("value"), Mapping):
        raise IntegrityError("evaluator certification binding 'environment' has an invalid value")
    adapter_value = bindings["adapter"].get("value")
    if not isinstance(adapter_value, Mapping) or bindings["adapter"]["digest"] != sha256_json(
        adapter_value
    ):
        raise IntegrityError("evaluator certification adapter binding seal is invalid")
    effective = bindings["effective_compatibility"]
    for field in ("project_digest", "adapter_digest"):
        value = effective.get(field)
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in "0123456789abcdef" for character in value)
        ):
            raise IntegrityError(
                f"evaluator certification effective compatibility {field} is invalid"
            )
    if effective.get("adapter_digest") != bindings["adapter"]["digest"] or effective.get(
        "digest"
    ) != sha256_json(
        {
            "project": effective.get("project_digest"),
            "adapter": effective.get("adapter_digest"),
        }
    ):
        raise IntegrityError("evaluator certification effective compatibility seal is invalid")
    for field in ("brief_path", "candidate_schema_path"):
        value = bindings["agent_spec"].get(field)
        if not isinstance(value, str) or not value:
            raise IntegrityError(
                f"evaluator certification binding 'agent_spec' has invalid {field}"
            )
    expected_subject = _review_subject_from_bindings(config, bindings)
    if review.get("subject_digest") != expected_subject["digest"]:
        raise IntegrityError(
            "evaluator certification review subject does not match its bindings"
        )
    claimed_digest = artifact["digest"]
    unsigned = dict(artifact)
    unsigned.pop("digest")
    if not isinstance(claimed_digest, str) or claimed_digest != sha256_json(unsigned):
        raise IntegrityError("evaluator certification digest is invalid")
    return artifact


def _load_evaluator_certification_unlocked(
    config: ProjectConfig,
) -> dict[str, Any] | None:
    data = _read_certification_bytes(config.root)
    if data is None:
        return None
    return _parse_artifact(data, config)


def load_evaluator_certification(config: ProjectConfig) -> dict[str, Any] | None:
    """Load and self-verify the recorded artifact without checking freshness."""

    with _certification_lock(config, exclusive=False):
        return _load_evaluator_certification_unlocked(config)


def _empty_summary() -> dict[str, Any]:
    return {
        "path": EVALUATOR_CERTIFICATION_RELATIVE.as_posix(),
        "present": False,
        "certified": False,
        "current": False,
        "status": "MISSING",
        "reason": "missing",
        "blockers": ["EVALUATOR_CERTIFICATION_MISSING"],
        "digest": None,
        "certification_digest": None,
        "review_digest": None,
        "review_subject_digest": None,
        "reviewer": None,
        "independent_reviewer": None,
        "bindings": {key: None for key in CERTIFICATION_BINDING_KEYS},
    }


def _inspect_evaluator_certification_unlocked(
    config: ProjectConfig,
    *,
    fingerprints: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a stable readiness summary; only malformed artifacts raise."""

    artifact = _load_evaluator_certification_unlocked(config)
    if artifact is None:
        return _empty_summary()
    bindings = artifact["bindings"]
    assert isinstance(bindings, Mapping)
    if fingerprints is None:
        current_source = project_fingerprints(config)
        current_bindings = _source_only_binding_snapshot(config, current_source, bindings)
    elif "adapter" in fingerprints or "project_compatibility_digest" in fingerprints:
        current_source = project_fingerprints(config)
        _assert_doctor_matches_source(config, fingerprints, current_source)
        current_bindings = _doctor_binding_snapshot(config, fingerprints)
    else:
        current_source = project_fingerprints(config)
        _assert_source_snapshot_matches_live(config, fingerprints, current_source)
        current_bindings = _source_only_binding_snapshot(config, current_source, bindings)
    stale_keys = [
        key for key in CERTIFICATION_BINDING_KEYS if bindings.get(key) != current_bindings.get(key)
    ]
    blockers: list[str] = []
    if stale_keys:
        status = "STALE"
        blockers.append("EVALUATOR_CERTIFICATION_STALE")
    elif artifact["certified"] is not True:
        status = "REJECTED"
        blockers.append("EVALUATOR_REVIEW_REJECTED")
    else:
        status = "CERTIFIED"
    review = artifact["review"]
    assert isinstance(review, Mapping)
    binding_digests = {
        key: (bindings[key].get("digest") if isinstance(bindings[key], Mapping) else None)
        for key in CERTIFICATION_BINDING_KEYS
    }
    return {
        "path": EVALUATOR_CERTIFICATION_RELATIVE.as_posix(),
        "present": True,
        "certified": status == "CERTIFIED",
        "current": not stale_keys,
        "status": status,
        "reason": None if status == "CERTIFIED" else status.lower(),
        "blockers": blockers,
        "digest": artifact["digest"],
        "certification_digest": artifact["digest"],
        "review_digest": artifact["review_digest"],
        "review_subject_digest": review["subject_digest"],
        "reviewer": review["reviewer"],
        "independent_reviewer": review["independent_reviewer"],
        "bindings": binding_digests,
    }


def inspect_evaluator_certification(
    config: ProjectConfig,
    *,
    fingerprints: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a stable readiness summary; only malformed artifacts raise."""

    with _certification_lock(config, exclusive=False):
        return _inspect_evaluator_certification_unlocked(
            config,
            fingerprints=fingerprints,
        )


def require_evaluator_certification(
    config: ProjectConfig,
    *,
    fingerprints: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the current passing artifact or fail closed before agent research."""

    with _certification_lock(config, exclusive=False):
        summary = _inspect_evaluator_certification_unlocked(
            config,
            fingerprints=fingerprints,
        )
        if summary["certified"] is not True:
            error = EvaluatorCertificationError(
                "a current passing evaluator certification is required for agent research",
                reason=str(summary["status"]).lower(),
            )
            error.details.update(
                {
                    "status": summary["status"],
                    "blockers": list(summary["blockers"]),
                }
            )
            raise error
        artifact = _load_evaluator_certification_unlocked(config)
        if artifact is None:  # pragma: no cover - guarded by the shared lock
            raise IntegrityError("evaluator certification disappeared after verification")
        if artifact["digest"] != summary["digest"]:
            raise IntegrityError("evaluator certification changed after verification")
        return artifact


def record_evaluator_certification(
    config: ProjectConfig,
    review_path: str | os.PathLike[str] | Path,
    *,
    fingerprints: Mapping[str, Any],
    fresh_fingerprints: Callable[[], Mapping[str, Any]],
    replace: bool = False,
) -> dict[str, Any]:
    """Record a review only while a fresh full ``doctor`` binding still agrees.

    ``fresh_fingerprints`` runs under the certification lock and must be a
    lock-free doctor snapshot callback; calling ``doctor()`` or another API
    that acquires a certification lock fails fast instead of self-deadlocking.
    """

    if not isinstance(replace, bool):
        raise TypeError("replace must be a boolean")
    if not callable(fresh_fingerprints):
        raise TypeError("fresh_fingerprints must be callable")
    with _certification_lock(config, exclusive=True):
        _ensure_certification_gitignore_unlocked(config)
        _assert_review_outside_project(config, review_path)
        review = validate_evaluator_review(
            _read_bounded_regular_json(
                review_path,
                label="evaluator review",
                max_bytes=_MAX_REVIEW_BYTES,
            )
        )
        before = project_fingerprints(config)
        doctor_bindings = _doctor_binding_snapshot(config, fingerprints)
        _assert_doctor_matches_source(config, fingerprints, before)
        before_bindings = _source_binding_snapshot(config, before)
        if any(
            doctor_bindings[key] != before_bindings[key]
            for key in _SOURCE_BINDING_KEYS
        ):
            raise IntegrityError("doctor bindings changed while certification was prepared")
        subject = _review_subject_from_bindings(config, doctor_bindings)
        if review["subject_digest"] != subject["digest"]:
            raise ConfigurationError(
                "evaluator review subject_digest does not match the current review subject"
            )
        artifact = _build_artifact(config, review, doctor_bindings)
        encoded = canonical_json_bytes(artifact) + b"\n"
        if len(encoded) > _MAX_CERTIFICATION_BYTES:
            raise ConfigurationError(
                f"evaluator certification exceeds the {_MAX_CERTIFICATION_BYTES} byte limit"
            )

        def validate_final_bindings() -> None:
            refreshed = fresh_fingerprints()
            if not isinstance(refreshed, Mapping):
                raise IntegrityError(
                    "fresh doctor callback must return a fingerprint mapping"
                )
            current = project_fingerprints(config)
            _assert_doctor_matches_source(config, refreshed, current)
            refreshed_bindings = _doctor_binding_snapshot(config, refreshed)
            if refreshed_bindings != doctor_bindings:
                raise IntegrityError(
                    "certification-bound doctor inputs changed during publication"
                )

        def validate_published_artifact() -> None:
            recorded_bytes = _read_certification_bytes(config.root)
            if recorded_bytes is None or recorded_bytes != encoded:
                raise IntegrityError(
                    "recorded evaluator certification bytes changed before commit"
                )
            recorded = _parse_artifact(recorded_bytes, config)
            if recorded != artifact:
                raise IntegrityError(
                    "recorded evaluator certification failed provisional read-back"
                )
            validate_final_bindings()

        _write_certification_bytes(
            config.root,
            encoded,
            replace=replace,
            before_publish=validate_final_bindings,
            after_publish=validate_published_artifact,
        )
        return artifact


__all__ = [
    "CERTIFICATION_BINDING_KEYS",
    "EVALUATOR_CERTIFICATION_KIND",
    "EVALUATOR_CERTIFICATION_RELATIVE",
    "EVALUATOR_CERTIFICATION_SCHEMA_VERSION",
    "EVALUATOR_REVIEW_KIND",
    "EVALUATOR_REVIEW_SUBJECT_KIND",
    "REQUIRED_EVALUATOR_CHECK_IDS",
    "build_evaluator_review_subject",
    "ensure_certification_gitignore",
    "evaluator_certification_read_lock",
    "inspect_evaluator_certification",
    "load_evaluator_certification",
    "record_evaluator_certification",
    "require_evaluator_certification",
    "validate_evaluator_review",
]
