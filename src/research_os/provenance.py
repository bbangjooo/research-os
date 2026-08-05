"""Stable project, evaluator, data, adapter, and environment fingerprints."""

from __future__ import annotations

import hashlib
import os
import platform
import shutil
import stat
from pathlib import Path
from typing import Iterable

from research_os.config import ProjectConfig
from research_os.contracts import sha256_file, sha256_json
from research_os.errors import IntegrityError

DESIGN_PROVENANCE = {
    "fingerprint_paths": ("Immutable evaluation", "Typed provenance"),
    "fingerprint_mutable_paths": ("Immutable evaluation", "Typed provenance"),
    "project_fingerprints": ("Immutable evaluation", "Typed provenance"),
}

_FILE_SUFFIXES = frozenset(
    {
        ".bash",
        ".js",
        ".mjs",
        ".py",
        ".rb",
        ".sh",
        ".toml",
        ".yaml",
        ".yml",
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


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _directory_flags() -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    return flags | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _file_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


def _open_project_root(root: Path) -> tuple[int, os.stat_result]:
    before = root.lstat()
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
        raise IntegrityError(
            f"fingerprint root must be a non-symlink directory: {root}"
        )
    descriptor = os.open(root, _directory_flags())
    opened = os.fstat(descriptor)
    if not stat.S_ISDIR(opened.st_mode) or not _same_identity(before, opened):
        os.close(descriptor)
        raise IntegrityError(f"fingerprint root changed while opening: {root}")
    return descriptor, opened


def _open_parent(
    root_fd: int, relative: Path
) -> tuple[
    int,
    str,
    list[int],
    list[tuple[int, str, int, os.stat_result]],
]:
    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise IntegrityError(f"unsafe fingerprint path: {relative}")
    current_fd = root_fd
    opened_directories: list[int] = []
    directory_links: list[tuple[int, str, int, os.stat_result]] = []
    try:
        for component in relative.parts[:-1]:
            before = os.stat(component, dir_fd=current_fd, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise IntegrityError(
                    f"fingerprinted path traverses unsafe directory: {relative}"
                )
            next_fd = os.open(component, _directory_flags(), dir_fd=current_fd)
            opened = os.fstat(next_fd)
            if not stat.S_ISDIR(opened.st_mode) or not _same_identity(before, opened):
                os.close(next_fd)
                raise IntegrityError(
                    f"fingerprinted directory changed while opening: {relative}"
                )
            directory_links.append((current_fd, component, next_fd, opened))
            opened_directories.append(next_fd)
            current_fd = next_fd
        return current_fd, relative.parts[-1], opened_directories, directory_links
    except BaseException:
        for descriptor in reversed(opened_directories):
            os.close(descriptor)
        raise


def _verify_directory_links(
    links: list[tuple[int, str, int, os.stat_result]], relative: Path
) -> None:
    for parent_fd, component, child_fd, expected in reversed(links):
        after_descriptor = os.fstat(child_fd)
        after_link = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISDIR(after_descriptor.st_mode)
            or not stat.S_ISDIR(after_link.st_mode)
            or not _same_identity(expected, after_descriptor)
            or not _same_identity(expected, after_link)
        ):
            raise IntegrityError(
                f"fingerprinted path component was replaced while reading: {relative}"
            )


def _hash_open_file(
    parent_fd: int,
    name: str,
    before: os.stat_result,
    display_path: str,
) -> tuple[str, int]:
    descriptor = os.open(name, _file_flags(), dir_fd=parent_fd)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not _same_identity(before, opened):
            raise IntegrityError(
                f"fingerprinted file changed while opening: {display_path}"
            )
        digest = hashlib.sha256()
        size = 0
        while block := os.read(descriptor, 1024 * 1024):
            digest.update(block)
            size += len(block)
        after_descriptor = os.fstat(descriptor)
        if (
            _stable_stat(after_descriptor) != _stable_stat(opened)
            or size != opened.st_size
        ):
            raise IntegrityError(
                f"fingerprinted file changed while reading: {display_path}"
            )
    finally:
        os.close(descriptor)

    after_path = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if _stable_stat(after_path) != _stable_stat(opened):
        raise IntegrityError(
            f"fingerprinted file was replaced while reading: {display_path}"
        )
    return digest.hexdigest(), size


def _fingerprint_entry(
    parent_fd: int,
    name: str,
    relative: Path,
    records: list[dict[str, object]],
    *,
    expected: os.stat_result | None = None,
) -> None:
    display_path = relative.as_posix()
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if expected is not None and _stable_stat(before) != _stable_stat(expected):
        raise IntegrityError(
            f"fingerprinted entry changed during directory scan: {display_path}"
        )
    if stat.S_ISLNK(before.st_mode):
        raise IntegrityError(
            f"fingerprinted tree cannot contain a symlink: {display_path}"
        )
    if stat.S_ISREG(before.st_mode):
        digest, size = _hash_open_file(parent_fd, name, before, display_path)
        records.append({"path": display_path, "sha256": digest, "size_bytes": size})
        return
    if not stat.S_ISDIR(before.st_mode):
        raise IntegrityError(
            f"fingerprinted tree contains a special file: {display_path}"
        )

    descriptor = os.open(name, _directory_flags(), dir_fd=parent_fd)
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode) or not _same_identity(before, opened):
            raise IntegrityError(
                f"fingerprinted directory changed while opening: {display_path}"
            )
        records.append({"path": display_path, "kind": "directory"})
        with os.scandir(descriptor) as scanner:
            entries = sorted(
                ((entry.name, entry.stat(follow_symlinks=False)) for entry in scanner),
                key=lambda item: item[0],
            )
        for child_name, child_stat in entries:
            _fingerprint_entry(
                descriptor,
                child_name,
                relative / child_name,
                records,
                expected=child_stat,
            )
        after_descriptor = os.fstat(descriptor)
        if _stable_stat(after_descriptor) != _stable_stat(opened):
            raise IntegrityError(
                f"fingerprinted directory changed while reading: {display_path}"
            )
    finally:
        os.close(descriptor)

    after_path = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if _stable_stat(after_path) != _stable_stat(opened):
        raise IntegrityError(
            f"fingerprinted directory was replaced while reading: {display_path}"
        )


def fingerprint_paths(root: Path, paths: Iterable[Path]) -> dict[str, object]:
    """Hash declared files and trees without following or racing symlinks."""

    root = root.resolve(strict=True)
    root_fd = -1
    try:
        root_fd, root_opened = _open_project_root(root)
        records: list[dict[str, object]] = []
        for relative in sorted(
            set(Path(item) for item in paths), key=lambda item: item.as_posix()
        ):
            parent_fd, name, opened_directories, directory_links = _open_parent(
                root_fd, relative
            )
            try:
                _fingerprint_entry(parent_fd, name, relative, records)
                _verify_directory_links(directory_links, relative)
            finally:
                for descriptor in reversed(opened_directories):
                    os.close(descriptor)
        root_after_descriptor = os.fstat(root_fd)
        root_after_path = root.lstat()
        if not _same_identity(root_opened, root_after_descriptor) or not _same_identity(
            root_opened, root_after_path
        ):
            raise IntegrityError(f"fingerprint root was replaced while reading: {root}")
    except IntegrityError:
        raise
    except OSError as exc:
        raise IntegrityError(
            f"cannot securely fingerprint project paths: {exc}"
        ) from exc
    finally:
        if root_fd >= 0:
            os.close(root_fd)
    records.sort(key=lambda item: (str(item["path"]), str(item.get("kind", "file"))))
    return {"digest": sha256_json(records), "files": records}


def _assert_entry_remains_missing(
    parent_fd: int,
    name: str,
    relative: Path,
    parent_before: os.stat_result,
) -> None:
    """Establish a stable absence observation for an optional path component."""

    try:
        appeared = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        parent_after = os.fstat(parent_fd)
        if _stable_stat(parent_after) != _stable_stat(parent_before):
            raise IntegrityError(
                "directory changed while confirming a missing mutable path: "
                f"{relative.as_posix()}"
            ) from None
        return
    if stat.S_ISLNK(appeared.st_mode):
        raise IntegrityError(
            "missing mutable path appeared as a symlink while being fingerprinted: "
            f"{relative.as_posix()}"
        )
    raise IntegrityError(
        "missing mutable path appeared while being fingerprinted: "
        f"{relative.as_posix()}"
    )


def _fingerprint_optional_entry(
    root_fd: int,
    relative: Path,
    records: list[dict[str, object]],
) -> None:
    """Fingerprint one optional path through descriptor-anchored traversal."""

    if (
        relative.is_absolute()
        or not relative.parts
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise IntegrityError(f"unsafe fingerprint path: {relative}")

    current_fd = root_fd
    opened_directories: list[int] = []
    directory_links: list[tuple[int, str, int, os.stat_result]] = []
    try:
        for index, component in enumerate(relative.parts):
            parent_before = os.fstat(current_fd)
            try:
                before = os.stat(
                    component,
                    dir_fd=current_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                _assert_entry_remains_missing(
                    current_fd,
                    component,
                    relative,
                    parent_before,
                )
                _verify_directory_links(directory_links, relative)
                records.append(
                    {
                        "path": relative.as_posix(),
                        "kind": "missing",
                        "missing_at": Path(*relative.parts[: index + 1]).as_posix(),
                    }
                )
                return

            display_path = relative.as_posix()
            if stat.S_ISLNK(before.st_mode):
                raise IntegrityError(
                    f"fingerprinted tree cannot contain a symlink: {display_path}"
                )
            if index == len(relative.parts) - 1:
                _fingerprint_entry(
                    current_fd,
                    component,
                    relative,
                    records,
                    expected=before,
                )
                _verify_directory_links(directory_links, relative)
                return
            if not stat.S_ISDIR(before.st_mode):
                raise IntegrityError(
                    "mutable fingerprint path traverses a non-directory: "
                    f"{display_path}"
                )

            next_fd = os.open(component, _directory_flags(), dir_fd=current_fd)
            opened = os.fstat(next_fd)
            if not stat.S_ISDIR(opened.st_mode) or not _same_identity(before, opened):
                os.close(next_fd)
                raise IntegrityError(
                    "mutable fingerprint directory changed while opening: "
                    f"{display_path}"
                )
            directory_links.append((current_fd, component, next_fd, opened))
            opened_directories.append(next_fd)
            current_fd = next_fd
    finally:
        for descriptor in reversed(opened_directories):
            os.close(descriptor)


def fingerprint_mutable_paths(
    root: Path, paths: Iterable[Path]
) -> dict[str, object]:
    """Hash mutable baseline paths, preserving stable markers for missing paths."""

    root = root.resolve(strict=True)
    root_fd = -1
    try:
        root_fd, root_opened = _open_project_root(root)
        records: list[dict[str, object]] = []
        for relative in sorted(
            set(Path(item) for item in paths), key=lambda item: item.as_posix()
        ):
            _fingerprint_optional_entry(root_fd, relative, records)
        root_after_descriptor = os.fstat(root_fd)
        root_after_path = root.lstat()
        if not _same_identity(root_opened, root_after_descriptor) or not _same_identity(
            root_opened, root_after_path
        ):
            raise IntegrityError(f"fingerprint root was replaced while reading: {root}")
    except IntegrityError:
        raise
    except OSError as exc:
        raise IntegrityError(
            f"cannot securely fingerprint mutable project paths: {exc}"
        ) from exc
    finally:
        if root_fd >= 0:
            os.close(root_fd)
    records.sort(key=lambda item: (str(item["path"]), str(item.get("kind", "file"))))
    return {"digest": sha256_json(records), "files": records}


def _looks_file_valued(argument: str) -> bool:
    path = Path(argument)
    contains_separator = os.sep in argument or (
        os.altsep is not None and os.altsep in argument
    )
    return (
        path.is_absolute()
        or contains_separator
        or path.suffix.lower() in _FILE_SUFFIXES
    )


def _adapter_argument_candidate(
    config: ProjectConfig, index: int, argument: str
) -> tuple[Path | None, bool]:
    """Resolve an argv item that names a file under execve/cwd semantics."""

    requested = Path(argument)
    if not requested.is_absolute() and ".." in requested.parts:
        raise IntegrityError(
            "relative adapter file arguments cannot traverse above the project: "
            f"argv[{index}]={argument!r}"
        )
    if index == 0:
        if requested.is_absolute():
            return requested, True
        contains_separator = os.sep in argument or (
            os.altsep is not None and os.altsep in argument
        )
        if contains_separator:
            return config.root / requested, True
        found = shutil.which(argument)
        if found is None:
            raise IntegrityError(f"adapter executable cannot be resolved: {argument!r}")
        return Path(found), True

    candidate = requested if requested.is_absolute() else config.root / requested
    try:
        candidate.lstat()
    except FileNotFoundError:
        if _looks_file_valued(argument):
            raise IntegrityError(
                f"file-valued adapter argument cannot be resolved: argv[{index}]={argument!r}"
            ) from None
        return None, False
    except OSError as exc:
        raise IntegrityError(
            f"cannot inspect adapter argument argv[{index}]={argument!r}: {exc}"
        ) from exc
    return candidate, True


def _adapter_file_record(
    index: int, argument: str, candidate: Path
) -> dict[str, object] | None:
    try:
        resolved = candidate.resolve(strict=True)
        before = resolved.lstat()
    except OSError as exc:
        raise IntegrityError(
            f"cannot resolve adapter file argv[{index}]={argument!r}: {exc}"
        ) from exc
    if not stat.S_ISREG(before.st_mode):
        if index == 0 or not stat.S_ISDIR(before.st_mode):
            raise IntegrityError(
                f"adapter argv[{index}] does not resolve to a regular file: {resolved}"
            )
        return None
    try:
        digest = sha256_file(resolved)
        after = resolved.lstat()
        resolved_after = candidate.resolve(strict=True)
    except (OSError, ValueError) as exc:
        raise IntegrityError(
            f"cannot securely fingerprint adapter argv[{index}]={argument!r}: {exc}"
        ) from exc
    if _stable_stat(before) != _stable_stat(after) or resolved_after != resolved:
        raise IntegrityError(
            f"adapter argv[{index}] changed while being fingerprinted: {argument!r}"
        )
    return {
        "index": index,
        "argument": argument,
        "resolved": str(resolved),
        "sha256": digest,
        "size_bytes": after.st_size,
    }


def environment_fingerprint(config: ProjectConfig) -> dict[str, object]:
    adapter_files: list[dict[str, object]] = []
    for index, argument in enumerate(config.adapter_command):
        candidate, exists_or_required = _adapter_argument_candidate(
            config, index, argument
        )
        if candidate is None:
            continue
        record = _adapter_file_record(index, argument, candidate)
        if record is not None:
            adapter_files.append(record)
        elif exists_or_required and index == 0:
            raise IntegrityError("adapter executable is not a regular file")

    executable_record = next(
        (record for record in adapter_files if record["index"] == 0), None
    )
    if executable_record is None:
        raise IntegrityError("adapter executable provenance is unavailable")
    executable_name = Path(str(executable_record["resolved"])).name.lower()
    if (
        executable_name.startswith(("python", "pypy"))
        and "-m" in config.adapter_command[1:]
    ):
        raise IntegrityError(
            "Python '-m' adapter entry points are not file-verifiable; invoke a "
            "direct script and declare its imported source tree under paths.protected"
        )
    value = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "adapter_argv": list(config.adapter_command),
        "adapter_executable": executable_record,
        "adapter_files": adapter_files,
    }
    return {"digest": sha256_json(value), "value": value}


def project_fingerprints(config: ProjectConfig) -> dict[str, object]:
    config_paths = [
        Path(".research-os/project.toml"),
        Path(".research-os/constitution.toml"),
    ]
    constitution = fingerprint_paths(config.root, config_paths)
    protected = fingerprint_paths(config.root, config.protected_paths)
    evidence = fingerprint_paths(config.root, config.evidence_paths)
    mutable = fingerprint_mutable_paths(config.root, config.mutable_paths)
    environment = environment_fingerprint(config)
    compatibility = sha256_json(
        {
            "constitution": constitution["digest"],
            "protected": protected["digest"],
            "evidence": evidence["digest"],
            "mutable": mutable["digest"],
            "environment": environment["digest"],
        }
    )
    return {
        "constitution": constitution,
        "protected": protected,
        "evidence": evidence,
        "mutable": mutable,
        "environment": environment,
        "compatibility_digest": compatibility,
    }
