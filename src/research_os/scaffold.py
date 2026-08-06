"""Safe, non-overwriting project onboarding scaffold."""

from __future__ import annotations

import json
import os
import re
import stat
from pathlib import Path
from typing import Final

from research_os.errors import ConfigurationError

_PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_CONTROL_DIR: Final = ".research-os"
_INIT_LOCK: Final = ".research-os.init.lock"


PROJECT_TEMPLATE = """schema_version = 1
adapter_command = ["python3", ".research-os/adapter.py"]

[project]
id = {project_id}
name = {name}

[paths]
mutable = ["experiment.json"]
protected = [".research-os/adapter.py", ".research-os/project.toml", ".research-os/constitution.toml", ".research-os/research-brief.md", ".research-os/candidate.schema.json", "evaluator.py"]
evidence = ["evaluator.py"]
runtime = ".research-os/runtime"

[budget]
timeout_seconds = 60
max_output_bytes = 1048576
max_artifact_bytes = 10485760
"""

CONSTITUTION_TEMPLATE = """schema_version = 1

[objective]
primary_metric = "replace_me"
direction = "maximize"

[baseline]
repeats = 2
tolerance = 0.0

[promotion]
minimum_improvement = 0.0

[authority]
authorized_action = ""
"""

ADAPTER_TEMPLATE = '''#!/usr/bin/env python3
"""Replace this fail-closed adapter with project-owned deterministic operations."""

import json
import sys

request = json.loads(sys.stdin.read())
response = {
    "protocol_version": 1,
    "request_id": request.get("request_id"),
    "ok": False,
    "retryable": False,
    "payload": {},
    "diagnostics": [],
    "error": {
        "category": "INFRASTRUCTURE",
        "code": "NOT_CONFIGURED",
        "message": "project adapter has not been implemented",
    },
}
print(json.dumps(response, sort_keys=True, separators=(",", ":")))
'''

EVALUATOR_TEMPLATE = """#!/usr/bin/env python3
raise SystemExit("replace evaluator.py with a deterministic project evaluator")
"""

RESEARCH_BRIEF_TEMPLATE = """# Research brief

Status: REPLACE_ME

## Objective

REPLACE_ME: state the bounded research question and what a useful result means.

## Candidate semantics

REPLACE_ME: describe one falsifiable candidate and the allowed search surface.

## Evaluation certification

REPLACE_ME: identify the independent reviewer and the evidence needed for every
required evaluator-certification check before agent-driven research may begin.

## Universe preregistration

REPLACE_ME: define the eligible population, inclusion/exclusion rules, selection
timestamp, and the evidence that freezes the universe before evaluation.

## Holdout boundary

REPLACE_ME: define the physically or logically isolated holdout, who may access
it, when it may be opened, and the one-way rule after disclosure.

## Golden controls

REPLACE_ME: list deterministic positive, negative, edge, and failure cases that
the evaluator must reproduce before certification.

## Hypothesis classes and failure threshold

REPLACE_ME: enumerate materially distinct mechanism classes and state when
repeated negative evidence closes a branch or triggers versioned change-control.

## Graph proposal policy

REPLACE_ME: require explore/exploit/ablate/replicate action, scientific parent,
one bounded change set, predicted metric effect, constraint risks, and falsifier.

## Evidence and constraints

REPLACE_ME: identify fixed data/splits, leakage checks, costs, and hard constraints.

## Search budget

- Maximum experiments per session: REPLACE_ME
- Maximum retries per session: REPLACE_ME
- Time or cost ceiling: REPLACE_ME

## Stop conditions

REPLACE_ME: list scientific, safety, and budget conditions that stop research.

## Authority

Validated research is evidence only. It cannot authorize deployment, model release,
capital allocation, or a live order.
"""

CANDIDATE_SCHEMA_TEMPLATE = """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "title": "REPLACE_ME candidate schema",
  "description": "REPLACE_ME with the project-owned bounded candidate contract",
  "type": "object",
  "properties": {},
  "additionalProperties": false,
  "x-research-os-configured": false
}
"""


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _entry(fd: int, name: str) -> os.stat_result | None:
    try:
        return os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return None


def _write_all(fd: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(fd, data[offset:])
        if written <= 0:
            raise OSError("short write while creating project scaffold")
        offset += written


def _unlink_owned(fd: int, name: str, identity: tuple[int, int]) -> bool:
    """Unlink *name* only while it is still the inode this transaction made."""

    try:
        current = os.stat(name, dir_fd=fd, follow_symlinks=False)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    if (current.st_dev, current.st_ino) != identity:
        return False
    try:
        os.unlink(name, dir_fd=fd)
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


def _fsync_directory(fd: int) -> None:
    os.fsync(fd)


def initialize_project(root: Path, project_id: str, name: str) -> list[Path]:
    """Create a project scaffold without following or overwriting path entries.

    An exclusive root-level reservation serializes cooperating initializers.
    Every leaf is created relative to an already-open directory descriptor with
    ``O_EXCL`` and ``O_NOFOLLOW``.  A failure rolls back only inodes created by
    this transaction, leaving all pre-existing project content untouched.
    """

    if not isinstance(project_id, str) or not _PROJECT_ID.fullmatch(project_id):
        raise ConfigurationError(
            "project id may contain only letters, digits, '.', '_' and '-'"
        )
    if not isinstance(name, str) or not name.strip():
        raise ConfigurationError("project name cannot be empty")

    supplied_root = Path(root).expanduser()
    root_path = Path(os.path.abspath(os.fspath(supplied_root)))
    try:
        supplied_info = root_path.lstat()
    except OSError as exc:
        raise ConfigurationError(
            f"project directory does not exist: {root_path}"
        ) from exc
    if stat.S_ISLNK(supplied_info.st_mode) or not stat.S_ISDIR(supplied_info.st_mode):
        raise ConfigurationError(
            f"project root must be a non-symlink directory: {root_path}"
        )

    try:
        root_fd = os.open(root_path, _directory_flags())
    except OSError as exc:
        raise ConfigurationError(
            f"cannot safely open project directory: {root_path}"
        ) from exc
    control_fd = -1
    canonical_root = root_path
    lock_identity: tuple[int, int] | None = None
    control_identity: tuple[int, int] | None = None
    control_created = False
    # Each tuple is (directory fd, leaf name, inode identity).
    created_entries: list[tuple[int, str, tuple[int, int]]] = []
    created_paths: list[Path] = []

    try:
        opened_root = os.fstat(root_fd)
        if not stat.S_ISDIR(opened_root.st_mode) or (
            opened_root.st_dev,
            opened_root.st_ino,
        ) != (supplied_info.st_dev, supplied_info.st_ino):
            raise ConfigurationError("project root changed while it was being opened")
        canonical_root = root_path.resolve(strict=True)
        canonical_info = canonical_root.stat()
        if (canonical_info.st_dev, canonical_info.st_ino) != (
            opened_root.st_dev,
            opened_root.st_ino,
        ):
            raise ConfigurationError("project root resolution changed while opening it")

        lock_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        lock_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            lock_fd = os.open(_INIT_LOCK, lock_flags, 0o600, dir_fd=root_fd)
        except FileExistsError as exc:
            raise ConfigurationError(
                "project initialization is already running or has a stale reservation: "
                f"{root_path / _INIT_LOCK}"
            ) from exc
        try:
            lock_info = os.fstat(lock_fd)
            lock_identity = (lock_info.st_dev, lock_info.st_ino)
            os.fchmod(lock_fd, 0o600)
            os.fsync(lock_fd)
        finally:
            os.close(lock_fd)

        control_entry = _entry(root_fd, _CONTROL_DIR)
        if control_entry is None:
            try:
                os.mkdir(_CONTROL_DIR, 0o700, dir_fd=root_fd)
                control_created = True
            except FileExistsError:
                # A concurrent non-cooperating creator won the race.  Validate
                # the resulting entry below instead of following it.
                pass
        try:
            control_fd = os.open(_CONTROL_DIR, _directory_flags(), dir_fd=root_fd)
        except OSError as exc:
            raise ConfigurationError(
                f"project control path must be a non-symlink directory: "
                f"{root_path / _CONTROL_DIR}"
            ) from exc
        control_info = os.fstat(control_fd)
        if not stat.S_ISDIR(control_info.st_mode):
            raise ConfigurationError("project control path is not a directory")
        control_identity = (control_info.st_dev, control_info.st_ino)
        if control_created:
            os.fchmod(control_fd, 0o700)

        project_toml = PROJECT_TEMPLATE.format(
            project_id=json.dumps(project_id), name=json.dumps(name)
        )
        specifications = (
            (
                control_fd,
                "project.toml",
                project_toml,
                canonical_root / _CONTROL_DIR / "project.toml",
                0o600,
            ),
            (
                control_fd,
                "constitution.toml",
                CONSTITUTION_TEMPLATE,
                canonical_root / _CONTROL_DIR / "constitution.toml",
                0o600,
            ),
            (
                control_fd,
                "adapter.py",
                ADAPTER_TEMPLATE,
                canonical_root / _CONTROL_DIR / "adapter.py",
                0o700,
            ),
            (
                control_fd,
                ".gitignore",
                "runtime/\ncandidate.inbox.json\nagent-journal.jsonl\nevaluator-certification.json\n",
                canonical_root / _CONTROL_DIR / ".gitignore",
                0o600,
            ),
            (
                control_fd,
                "research-brief.md",
                RESEARCH_BRIEF_TEMPLATE,
                canonical_root / _CONTROL_DIR / "research-brief.md",
                0o600,
            ),
            (
                control_fd,
                "candidate.schema.json",
                CANDIDATE_SCHEMA_TEMPLATE,
                canonical_root / _CONTROL_DIR / "candidate.schema.json",
                0o600,
            ),
            (
                control_fd,
                "candidate.inbox.json",
                "{}\n",
                canonical_root / _CONTROL_DIR / "candidate.inbox.json",
                0o600,
            ),
            (
                root_fd,
                "experiment.json",
                "{}\n",
                canonical_root / "experiment.json",
                0o600,
            ),
            (
                root_fd,
                "evaluator.py",
                EVALUATOR_TEMPLATE,
                canonical_root / "evaluator.py",
                0o700,
            ),
        )

        collisions = [
            str(path)
            for directory_fd, leaf, _, path, _ in specifications
            if _entry(directory_fd, leaf) is not None
        ]
        if collisions:
            raise ConfigurationError(
                "refusing to overwrite existing files: " + ", ".join(collisions)
            )

        create_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        create_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        for directory_fd, leaf, content, path, mode in specifications:
            try:
                descriptor = os.open(leaf, create_flags, mode, dir_fd=directory_fd)
            except FileExistsError as exc:
                raise ConfigurationError(
                    f"refusing to overwrite existing file: {path}"
                ) from exc
            info = os.fstat(descriptor)
            identity = (info.st_dev, info.st_ino)
            created_entries.append((directory_fd, leaf, identity))
            created_paths.append(path)
            try:
                os.fchmod(descriptor, mode)
                _write_all(descriptor, content.encode("utf-8"))
                os.fsync(descriptor)
            finally:
                os.close(descriptor)

        final_root = root_path.lstat()
        if (final_root.st_dev, final_root.st_ino) != (
            opened_root.st_dev,
            opened_root.st_ino,
        ):
            raise ConfigurationError("project root changed during initialization")
        final_control = _entry(root_fd, _CONTROL_DIR)
        if (
            final_control is None
            or (final_control.st_dev, final_control.st_ino) != control_identity
        ):
            raise ConfigurationError(
                "project control directory changed during initialization"
            )
        for directory_fd, leaf, identity in created_entries:
            final_entry = _entry(directory_fd, leaf)
            if (
                final_entry is None
                or (final_entry.st_dev, final_entry.st_ino) != identity
            ):
                raise ConfigurationError(
                    f"scaffold path changed during initialization: {leaf}"
                )
        final_lock = _entry(root_fd, _INIT_LOCK)
        if (
            final_lock is None
            or (final_lock.st_dev, final_lock.st_ino) != lock_identity
        ):
            raise ConfigurationError(
                "project initialization reservation changed unexpectedly"
            )

        # Make directory entries durable before releasing the reservation.
        _fsync_directory(control_fd)
        _fsync_directory(root_fd)
        return created_paths
    except BaseException as exc:
        for directory_fd, leaf, identity in reversed(created_entries):
            _unlink_owned(directory_fd, leaf, identity)
        if control_created and control_identity is not None:
            current = _entry(root_fd, _CONTROL_DIR)
            if (
                current is not None
                and (current.st_dev, current.st_ino) == control_identity
            ):
                try:
                    os.rmdir(_CONTROL_DIR, dir_fd=root_fd)
                except OSError:
                    pass
        for directory_fd in (control_fd, root_fd):
            if directory_fd >= 0:
                try:
                    _fsync_directory(directory_fd)
                except OSError:
                    pass
        if isinstance(exc, ConfigurationError):
            raise
        if isinstance(exc, OSError):
            raise ConfigurationError(
                f"could not create project scaffold: {exc}"
            ) from exc
        raise
    finally:
        if lock_identity is not None:
            _unlink_owned(root_fd, _INIT_LOCK, lock_identity)
            try:
                _fsync_directory(root_fd)
            except OSError:
                pass
        if control_fd >= 0:
            os.close(control_fd)
        os.close(root_fd)


DESIGN_PROVENANCE = {
    "initialize_project": ("Bounded mutable surface", "Immutable evaluation"),
}
