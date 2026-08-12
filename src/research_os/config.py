"""Load and validate a Research OS project constitution.

Projects opt in with two explicit TOML files beneath ``.research-os``.  Paths
declared in the project file remain relative so they can be applied to a
disposable workspace without leaking outside it.
"""

from __future__ import annotations

import math
import os
import re
import stat
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, cast

from .contracts.results import GateDefinition, MetricDirection
from .errors import ConfigurationError

SCHEMA_VERSION = 1
PROJECT_CONFIG_RELATIVE = Path(".research-os/project.toml")
CONSTITUTION_RELATIVE = Path(".research-os/constitution.toml")
PROJECT_FILE = PROJECT_CONFIG_RELATIVE
CONSTITUTION_FILE = CONSTITUTION_RELATIVE

_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MISSING = object()
_SNAPSHOT_EXCLUDED_PARTS = frozenset(
    {
        ".git",
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
_SNAPSHOT_EXCLUDED_PATHS = frozenset(
    {
        Path(".research-os/candidate.inbox.json"),
        Path(".research-os/agent-journal.jsonl"),
        Path(".research-os/evaluator-certification.json"),
    }
)


@dataclass(frozen=True, slots=True)
class ProjectConfig:
    """Fully validated, authority-safe project configuration."""

    root: Path
    project_id: str
    name: str
    adapter_command: tuple[str, ...]
    mutable_paths: tuple[Path, ...]
    protected_paths: tuple[Path, ...]
    evidence_paths: tuple[Path, ...]
    runtime_dir: Path
    timeout_seconds: float
    max_output_bytes: int
    max_artifact_bytes: int
    primary_metric: str
    direction: MetricDirection
    baseline_repeats: int
    baseline_tolerance: float
    minimum_improvement: float
    gates: tuple[GateDefinition, ...] = ()
    authorized_action: None = field(default=None, init=False, repr=False)

    @property
    def promotion_gates(self) -> tuple[GateDefinition, ...]:
        """Explicit alias for the gates declared beneath ``[promotion]``."""

        return self.gates

    @property
    def adapter_argv(self) -> tuple[str, ...]:
        """Alias emphasizing that the command is executed without a shell."""

        return self.adapter_command

    def resolve_path(self, relative_path: str | os.PathLike[str] | Path) -> Path:
        """Resolve a safe relative path beneath this project's root."""

        relative = validate_relative_path(self.root, relative_path, field_name="path")
        return self.root / relative

    @property
    def resolved_mutable_paths(self) -> tuple[Path, ...]:
        return tuple(self.root / path for path in self.mutable_paths)

    @property
    def resolved_protected_paths(self) -> tuple[Path, ...]:
        return tuple(self.root / path for path in self.protected_paths)

    @property
    def resolved_evidence_paths(self) -> tuple[Path, ...]:
        return tuple(self.root / path for path in self.evidence_paths)

    @property
    def resolved_runtime_dir(self) -> Path:
        return self.root / self.runtime_dir


def ensure_runtime_directory(config: ProjectConfig) -> Path:
    """Create/open the fixed runtime directory without following symlinks.

    Creation and permission changes are performed relative to verified root and
    control-directory descriptors.  The final link and descriptor identities
    are checked before returning so ``mkdir``/``chmod`` cannot be redirected
    through a concurrent symlink replacement.
    """

    root = config.root
    runtime = config.resolved_runtime_dir
    root_fd = -1
    control_fd = -1
    runtime_fd = -1
    try:
        root_before = root.lstat()
        if stat.S_ISLNK(root_before.st_mode) or not stat.S_ISDIR(root_before.st_mode):
            raise OSError("project root is not a non-symlink directory")
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        root_fd = os.open(root, directory_flags)
        root_opened = os.fstat(root_fd)
        if not stat.S_ISDIR(root_opened.st_mode) or (
            root_opened.st_dev,
            root_opened.st_ino,
        ) != (root_before.st_dev, root_before.st_ino):
            raise OSError("project root changed while opening runtime")

        control_before = os.stat(".research-os", dir_fd=root_fd, follow_symlinks=False)
        if stat.S_ISLNK(control_before.st_mode) or not stat.S_ISDIR(
            control_before.st_mode
        ):
            raise OSError(".research-os must be a non-symlink directory")
        control_fd = os.open(".research-os", directory_flags, dir_fd=root_fd)
        control_opened = os.fstat(control_fd)
        if not stat.S_ISDIR(control_opened.st_mode) or (
            control_opened.st_dev,
            control_opened.st_ino,
        ) != (control_before.st_dev, control_before.st_ino):
            raise OSError(".research-os changed while opening runtime")

        try:
            runtime_before = os.stat(
                "runtime", dir_fd=control_fd, follow_symlinks=False
            )
        except FileNotFoundError:
            try:
                os.mkdir("runtime", mode=0o700, dir_fd=control_fd)
            except FileExistsError:
                # A racing creator won.  Inspect its exact directory entry
                # below instead of trusting the collision.
                pass
            runtime_before = os.stat(
                "runtime", dir_fd=control_fd, follow_symlinks=False
            )
        if stat.S_ISLNK(runtime_before.st_mode) or not stat.S_ISDIR(
            runtime_before.st_mode
        ):
            raise OSError("runtime must be a non-symlink directory")

        runtime_fd = os.open("runtime", directory_flags, dir_fd=control_fd)
        runtime_opened = os.fstat(runtime_fd)
        if not stat.S_ISDIR(runtime_opened.st_mode) or (
            runtime_opened.st_dev,
            runtime_opened.st_ino,
        ) != (runtime_before.st_dev, runtime_before.st_ino):
            raise OSError("runtime changed while opening")
        os.fchmod(runtime_fd, 0o700)

        runtime_after = os.stat("runtime", dir_fd=control_fd, follow_symlinks=False)
        control_after = os.stat(".research-os", dir_fd=root_fd, follow_symlinks=False)
        root_after = root.lstat()
        if not stat.S_ISDIR(runtime_after.st_mode) or (
            runtime_after.st_dev,
            runtime_after.st_ino,
        ) != (runtime_opened.st_dev, runtime_opened.st_ino):
            raise OSError("runtime was replaced while securing it")
        if not stat.S_ISDIR(control_after.st_mode) or (
            control_after.st_dev,
            control_after.st_ino,
        ) != (control_opened.st_dev, control_opened.st_ino):
            raise OSError(".research-os was replaced while securing runtime")
        if (root_after.st_dev, root_after.st_ino) != (
            root_opened.st_dev,
            root_opened.st_ino,
        ):
            raise OSError("project root was replaced while securing runtime")
    except OSError as exc:
        raise _configuration_error(
            f"cannot securely initialize runtime directory: {exc}", source=runtime
        ) from exc
    finally:
        if runtime_fd >= 0:
            os.close(runtime_fd)
        if control_fd >= 0:
            os.close(control_fd)
        if root_fd >= 0:
            os.close(root_fd)
    return runtime


def _configuration_error(
    message: str, *, source: Path | None = None
) -> ConfigurationError:
    prefix = f"{source}: " if source is not None else ""
    return ConfigurationError(prefix + message)


def _stable_stat(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _load_toml(root: Path, relative: Path, label: str) -> dict[str, Any]:
    """Load TOML through a descriptor-anchored, non-following path walk."""

    path = root / relative
    root_fd = -1
    current_fd = -1
    file_fd = -1
    opened_directories: list[int] = []
    directory_links: list[tuple[int, str, int, os.stat_result]] = []
    try:
        root_before = root.lstat()
        if stat.S_ISLNK(root_before.st_mode) or not stat.S_ISDIR(root_before.st_mode):
            raise OSError("project root is not a non-symlink directory")
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        root_fd = os.open(root, directory_flags)
        root_opened = os.fstat(root_fd)
        if not stat.S_ISDIR(root_opened.st_mode) or (
            root_opened.st_dev,
            root_opened.st_ino,
        ) != (root_before.st_dev, root_before.st_ino):
            raise OSError("project root changed while opening configuration")
        current_fd = root_fd
        for component in relative.parts[:-1]:
            before = os.stat(component, dir_fd=current_fd, follow_symlinks=False)
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                raise OSError(
                    f"configuration path component is not a safe directory: {component}"
                )
            next_fd = os.open(component, directory_flags, dir_fd=current_fd)
            opened = os.fstat(next_fd)
            if not stat.S_ISDIR(opened.st_mode) or (opened.st_dev, opened.st_ino) != (
                before.st_dev,
                before.st_ino,
            ):
                os.close(next_fd)
                raise OSError(
                    f"configuration directory changed while opening: {component}"
                )
            directory_links.append((current_fd, component, next_fd, opened))
            opened_directories.append(next_fd)
            current_fd = next_fd

        filename = relative.parts[-1]
        before_file = os.stat(filename, dir_fd=current_fd, follow_symlinks=False)
        if stat.S_ISLNK(before_file.st_mode):
            raise OSError(f"{label} cannot be a symlink")
        if not stat.S_ISREG(before_file.st_mode):
            raise OSError(f"{label} must be a regular file")
        file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        file_flags |= getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(filename, file_flags, dir_fd=current_fd)
        opened_file = os.fstat(file_fd)
        if not stat.S_ISREG(opened_file.st_mode) or (
            opened_file.st_dev,
            opened_file.st_ino,
        ) != (before_file.st_dev, before_file.st_ino):
            raise OSError(f"{label} changed while opening")
        with os.fdopen(os.dup(file_fd), "rb") as handle:
            document = tomllib.load(handle)
        after_file = os.fstat(file_fd)
        after_path = os.stat(filename, dir_fd=current_fd, follow_symlinks=False)
        if _stable_stat(opened_file) != _stable_stat(after_file):
            raise OSError(f"{label} changed while being read")
        if _stable_stat(opened_file) != _stable_stat(after_path):
            raise OSError(f"{label} was replaced while being read")
        for parent_fd, component, child_fd, expected in reversed(directory_links):
            after_descriptor = os.fstat(child_fd)
            after_link = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
            expected_identity = (expected.st_dev, expected.st_ino)
            if (
                not stat.S_ISDIR(after_descriptor.st_mode)
                or not stat.S_ISDIR(after_link.st_mode)
                or (after_descriptor.st_dev, after_descriptor.st_ino)
                != expected_identity
                or (after_link.st_dev, after_link.st_ino) != expected_identity
            ):
                raise OSError(
                    f"configuration directory was replaced while reading: {component}"
                )
        root_after = root.lstat()
        if (root_after.st_dev, root_after.st_ino) != (
            root_opened.st_dev,
            root_opened.st_ino,
        ):
            raise OSError("project root was replaced while reading configuration")
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise _configuration_error(f"cannot load {label}: {exc}", source=path) from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        for descriptor in reversed(opened_directories):
            os.close(descriptor)
        if root_fd >= 0:
            os.close(root_fd)
    if not isinstance(document, dict):
        raise _configuration_error(f"{label} must contain a TOML table", source=path)
    return document


def _schema_version(document: Mapping[str, Any], source: Path) -> None:
    if "schema_version" not in document:
        raise _configuration_error(
            "missing required field 'schema_version'", source=source
        )
    version = document["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise _configuration_error("schema_version must be an integer", source=source)
    if version != SCHEMA_VERSION:
        raise _configuration_error(
            f"unsupported schema_version {version!r}; expected {SCHEMA_VERSION}",
            source=source,
        )


def _section(document: Mapping[str, Any], name: str, source: Path) -> Mapping[str, Any]:
    if name not in document:
        raise _configuration_error(f"missing required table [{name}]", source=source)
    value = document[name]
    if not isinstance(value, Mapping):
        raise _configuration_error(f"[{name}] must be a TOML table", source=source)
    return value


def _required(
    table: Mapping[str, Any], name: str, table_name: str, source: Path
) -> Any:
    if name not in table:
        raise _configuration_error(
            f"missing required field '{table_name}.{name}'",
            source=source,
        )
    return table[name]


def _nonempty_string(value: Any, field_name: str, source: Path) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _configuration_error(
            f"{field_name} must be a non-empty string", source=source
        )
    if "\x00" in value:
        raise _configuration_error(f"{field_name} contains a NUL byte", source=source)
    return value.strip()


def _project_id(value: Any, source: Path) -> str:
    project_id = _nonempty_string(value, "project.id", source)
    if not _PROJECT_ID_RE.fullmatch(project_id):
        raise _configuration_error(
            "project.id may contain only letters, digits, '.', '_' and '-'",
            source=source,
        )
    return project_id


def _adapter_command(
    document: Mapping[str, Any], project: Mapping[str, Any], source: Path
) -> tuple[str, ...]:
    top_level = document.get("adapter_command", _MISSING)
    nested = project.get("adapter_command", _MISSING)
    if top_level is _MISSING and nested is _MISSING:
        raise _configuration_error(
            "missing required field 'adapter_command' (top-level or project.adapter_command)",
            source=source,
        )
    if top_level is not _MISSING and nested is not _MISSING and top_level != nested:
        raise _configuration_error(
            "conflicting top-level and project.adapter_command values",
            source=source,
        )
    raw = nested if top_level is _MISSING else top_level
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
        raise _configuration_error(
            "adapter_command must be an array of strings", source=source
        )
    command: list[str] = []
    for index, item in enumerate(raw):
        if not isinstance(item, str) or not item.strip():
            raise _configuration_error(
                f"adapter_command[{index}] must be a non-empty string", source=source
            )
        if "\x00" in item:
            raise _configuration_error(
                f"adapter_command[{index}] contains a NUL byte", source=source
            )
        parsed = Path(item)
        if not parsed.is_absolute() and ".." in parsed.parts:
            raise _configuration_error(
                f"adapter_command[{index}] cannot contain parent traversal",
                source=source,
            )
        # Whitespace is meaningful in an argv vector.  Validate with strip(),
        # but retain the exact TOML value passed to execve and provenance.
        command.append(item)
    if not command:
        raise _configuration_error("adapter_command cannot be empty", source=source)
    return tuple(command)


def _coerce_relative_path(value: Any, field_name: str) -> Path:
    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise ValueError(f"{field_name} must be a path string") from exc
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{field_name} must be a non-empty path string")
    if "\x00" in raw:
        raise ValueError(f"{field_name} contains a NUL byte")

    windows = PureWindowsPath(raw)
    portable = PurePosixPath(raw.replace("\\", "/"))
    if portable.is_absolute() or windows.is_absolute() or windows.drive:
        raise ValueError(f"{field_name} must be relative")
    if any(part == ".." for part in portable.parts):
        raise ValueError(f"{field_name} cannot contain '..'")
    parts = tuple(part for part in portable.parts if part not in ("", "."))
    if not parts:
        raise ValueError(f"{field_name} must name a path beneath the project root")
    return Path(*parts)


def validate_relative_path(
    root: str | os.PathLike[str] | Path,
    value: str | os.PathLike[str] | Path,
    *,
    field_name: str = "path",
) -> Path:
    """Validate a lexical relative path and reject every existing symlink hop.

    The returned path remains relative.  Non-existent suffix components are
    allowed, which is necessary for output and runtime directories, while any
    existing prefix must be made exclusively of real directory entries.
    """

    root_path = Path(root).resolve(strict=True)
    relative = _coerce_relative_path(value, field_name)
    current = root_path
    for part in relative.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            # Once a component is absent, deeper entries cannot currently be
            # symlinks.  Callers must validate again at use time to close races.
            break
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(f"{field_name} traverses symlink {current}")

    resolved = (root_path / relative).resolve(strict=False)
    try:
        resolved.relative_to(root_path)
    except ValueError as exc:
        raise ValueError(f"{field_name} escapes the project root") from exc
    return relative


def _path_list(
    root: Path,
    value: Any,
    field_name: str,
    source: Path,
    *,
    must_exist: bool = False,
) -> tuple[Path, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _configuration_error(
            f"{field_name} must be an array of relative paths", source=source
        )
    paths: list[Path] = []
    seen: set[Path] = set()
    for index, item in enumerate(value):
        if not isinstance(item, (str, os.PathLike)):
            raise _configuration_error(
                f"{field_name}[{index}] must be a path string",
                source=source,
            )
        safe_item = cast(str | os.PathLike[str], item)
        try:
            path = validate_relative_path(
                root, safe_item, field_name=f"{field_name}[{index}]"
            )
        except (OSError, TypeError, ValueError) as exc:
            raise _configuration_error(str(exc), source=source) from exc
        if must_exist and not (root / path).exists():
            raise _configuration_error(
                f"{field_name}[{index}] does not exist: {path}",
                source=source,
            )
        if path in seen:
            raise _configuration_error(
                f"{field_name} contains duplicate path {path}", source=source
            )
        seen.add(path)
        paths.append(path)
    return tuple(paths)


def _paths_overlap(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def _assert_snapshot_paths(
    paths: Sequence[tuple[str, tuple[Path, ...]]], source: Path
) -> None:
    for group_name, group_paths in paths:
        for path in group_paths:
            excluded = next(
                (part for part in path.parts if part in _SNAPSHOT_EXCLUDED_PARTS),
                None,
            )
            if excluded is not None:
                raise _configuration_error(
                    f"{group_name} targets snapshot-excluded directory {excluded!r}: "
                    f"{path.as_posix()}",
                    source=source,
                )
            transient = next(
                (
                    candidate
                    for candidate in _SNAPSHOT_EXCLUDED_PATHS
                    if _paths_overlap(path, candidate)
                ),
                None,
            )
            if transient is not None:
                raise _configuration_error(
                    f"{group_name} targets agent-transient path "
                    f"{transient.as_posix()!r}: {path.as_posix()}",
                    source=source,
                )


def _assert_unambiguous_surfaces(
    groups: Sequence[tuple[str, tuple[Path, ...]]],
    source: Path,
) -> None:
    flattened = [(group_name, path) for group_name, paths in groups for path in paths]
    for index, (left_group, left) in enumerate(flattened):
        for right_group, right in flattened[index + 1 :]:
            if left_group == right_group:
                continue
            immutable_pair = {left_group, right_group} == {
                "paths.protected",
                "paths.evidence",
            }
            if immutable_pair:
                # Evidence is commonly a sealed subset of a larger protected
                # evaluator/data surface.  Neither side is writable.
                continue
            if _paths_overlap(left, right):
                raise _configuration_error(
                    "declared surfaces overlap: "
                    f"{left_group}={left.as_posix()} and "
                    f"{right_group}={right.as_posix()}",
                    source=source,
                )


def _local_adapter_paths(
    root: Path, command: Sequence[str], source: Path
) -> tuple[Path, ...]:
    """Return existing project-local regular files referenced by adapter argv."""

    local: list[Path] = []
    for index, argument in enumerate(command):
        # Adapter argv is passed directly without shell expansion.  Treat '~'
        # and whitespace literally here as execve/subprocess will.
        raw = Path(argument)
        if raw.is_absolute():
            normalized = Path(os.path.abspath(raw))
            try:
                candidate_relative = normalized.relative_to(root)
            except ValueError:
                continue
        else:
            # Relative parent traversal was rejected while parsing the command.
            try:
                candidate_relative = _coerce_relative_path(
                    argument, f"adapter_command[{index}]"
                )
            except ValueError:
                continue
        candidate = root / candidate_relative
        try:
            info = candidate.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise _configuration_error(
                f"project-local adapter path cannot be a symlink: {candidate_relative}",
                source=source,
            )
        if not stat.S_ISREG(info.st_mode):
            continue
        try:
            safe = validate_relative_path(
                root,
                candidate_relative,
                field_name=f"adapter_command[{index}]",
            )
        except (OSError, TypeError, ValueError) as exc:
            raise _configuration_error(str(exc), source=source) from exc
        if safe not in local:
            local.append(safe)
    return tuple(local)


def _add_effective_protected_paths(
    declared: tuple[Path, ...],
    implicit: Sequence[Path],
) -> tuple[Path, ...]:
    result = list(declared)
    for path in implicit:
        # A declared protected ancestor already seals the file.  Avoid adding a
        # redundant nested surface, which would itself look ambiguous.
        if any(existing == path or existing in path.parents for existing in result):
            continue
        result.append(path)
    return tuple(result)


def _positive_number(value: Any, field_name: str, source: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _configuration_error(f"{field_name} must be a number", source=source)
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise _configuration_error(
            f"{field_name} must be finite and greater than zero", source=source
        )
    return result


def _positive_integer(value: Any, field_name: str, source: Path) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise _configuration_error(f"{field_name} must be an integer", source=source)
    if value <= 0:
        raise _configuration_error(
            f"{field_name} must be greater than zero", source=source
        )
    return value


def _nonnegative_number(value: Any, field_name: str, source: Path) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _configuration_error(f"{field_name} must be a number", source=source)
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise _configuration_error(
            f"{field_name} must be finite and non-negative", source=source
        )
    return result


def _gate_definitions(
    value: Any,
    source: Path,
) -> tuple[GateDefinition, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _configuration_error(
            "promotion.gates must be an array of tables", source=source
        )

    gates: list[GateDefinition] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
        try:
            gate = GateDefinition.from_dict(item)
        except (TypeError, ValueError) as exc:
            raise _configuration_error(
                f"promotion.gates[{index}] is invalid: {exc}", source=source
            ) from exc
        if gate.id in seen_ids:
            raise _configuration_error(
                f"promotion.gates contains duplicate id {gate.id!r}", source=source
            )
        seen_ids.add(gate.id)
        gates.append(gate)
    return tuple(gates)


def _canonical_root(root: str | os.PathLike[str] | Path) -> Path:
    path = Path(root).expanduser()
    if (
        path.name == PROJECT_CONFIG_RELATIVE.name
        and path.parent.name == PROJECT_CONFIG_RELATIVE.parent.name
    ):
        path = path.parent.parent
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise _configuration_error(f"project root does not exist: {path}") from exc
    if not resolved.is_dir():
        raise _configuration_error(f"project root must be a directory: {resolved}")
    return resolved


def find_project_root(start: str | os.PathLike[str] | Path | None = None) -> Path:
    """Walk from ``start`` to the nearest ``.research-os/project.toml``."""

    candidate = Path.cwd() if start is None else Path(start).expanduser()
    if candidate.exists() and candidate.is_file():
        candidate = candidate.parent
    candidate = candidate.resolve(strict=False)
    for directory in (candidate, *candidate.parents):
        marker = directory / PROJECT_CONFIG_RELATIVE
        try:
            info = marker.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            raise _configuration_error(
                "project config cannot be a symlink", source=marker
            )
        if not stat.S_ISREG(info.st_mode):
            raise _configuration_error(
                "project config must be a regular file", source=marker
            )
        return directory.resolve(strict=True)
    raise _configuration_error(
        f"no {PROJECT_CONFIG_RELATIVE.as_posix()} found at or above {candidate}"
    )


def load_project_config(root: str | os.PathLike[str] | Path) -> ProjectConfig:
    """Load both project TOML documents and return a validated configuration."""

    project_root = _canonical_root(root)
    project_path = project_root / PROJECT_CONFIG_RELATIVE
    constitution_path = project_root / CONSTITUTION_RELATIVE
    project_doc = _load_toml(project_root, PROJECT_CONFIG_RELATIVE, "project config")
    constitution_doc = _load_toml(project_root, CONSTITUTION_RELATIVE, "constitution")
    _schema_version(project_doc, project_path)
    _schema_version(constitution_doc, constitution_path)

    project = _section(project_doc, "project", project_path)
    paths = _section(project_doc, "paths", project_path)
    budget = _section(project_doc, "budget", project_path)
    objective = _section(constitution_doc, "objective", constitution_path)
    baseline = _section(constitution_doc, "baseline", constitution_path)
    promotion = _section(constitution_doc, "promotion", constitution_path)
    authority = _section(constitution_doc, "authority", constitution_path)
    adapter_command = _adapter_command(project_doc, project, project_path)

    raw_authorized_action = _required(
        authority, "authorized_action", "authority", constitution_path
    )
    if not isinstance(raw_authorized_action, str):
        raise _configuration_error(
            "authority.authorized_action must be an empty string",
            source=constitution_path,
        )
    if raw_authorized_action.strip():
        raise _configuration_error(
            "authority.authorized_action must remain empty; research results never authorize actions",
            source=constitution_path,
        )

    try:
        direction = MetricDirection.parse(
            _required(objective, "direction", "objective", constitution_path)
        )
    except (TypeError, ValueError) as exc:
        raise _configuration_error(str(exc), source=constitution_path) from exc

    mutable_paths = _path_list(
        project_root,
        _required(paths, "mutable", "paths", project_path),
        "paths.mutable",
        project_path,
    )
    if any(path.parts and path.parts[0] == ".research-os" for path in mutable_paths):
        raise _configuration_error(
            "paths.mutable cannot target Research OS control data",
            source=project_path,
        )
    protected_paths = _path_list(
        project_root,
        _required(paths, "protected", "paths", project_path),
        "paths.protected",
        project_path,
        must_exist=True,
    )
    evidence_paths = _path_list(
        project_root,
        _required(paths, "evidence", "paths", project_path),
        "paths.evidence",
        project_path,
        must_exist=True,
    )
    try:
        runtime_dir = validate_relative_path(
            project_root,
            _required(paths, "runtime", "paths", project_path),
            field_name="paths.runtime",
        )
    except (OSError, TypeError, ValueError) as exc:
        raise _configuration_error(str(exc), source=project_path) from exc
    if runtime_dir != Path(".research-os/runtime"):
        raise _configuration_error(
            "paths.runtime must be '.research-os/runtime' in schema version 1",
            source=project_path,
        )

    protected_paths = _add_effective_protected_paths(
        protected_paths,
        (
            PROJECT_CONFIG_RELATIVE,
            CONSTITUTION_RELATIVE,
            *_local_adapter_paths(project_root, adapter_command, project_path),
        ),
    )
    _assert_snapshot_paths(
        (
            ("paths.mutable", mutable_paths),
            ("paths.protected", protected_paths),
            ("paths.evidence", evidence_paths),
        ),
        project_path,
    )
    _assert_unambiguous_surfaces(
        (
            ("paths.mutable", mutable_paths),
            ("paths.protected", protected_paths),
            ("paths.evidence", evidence_paths),
            ("paths.runtime", (runtime_dir,)),
        ),
        project_path,
    )

    return ProjectConfig(
        root=project_root,
        project_id=_project_id(
            _required(project, "id", "project", project_path), project_path
        ),
        name=_nonempty_string(
            _required(project, "name", "project", project_path),
            "project.name",
            project_path,
        ),
        adapter_command=adapter_command,
        mutable_paths=mutable_paths,
        protected_paths=protected_paths,
        evidence_paths=evidence_paths,
        runtime_dir=runtime_dir,
        timeout_seconds=_positive_number(
            _required(budget, "timeout_seconds", "budget", project_path),
            "budget.timeout_seconds",
            project_path,
        ),
        max_output_bytes=_positive_integer(
            _required(budget, "max_output_bytes", "budget", project_path),
            "budget.max_output_bytes",
            project_path,
        ),
        max_artifact_bytes=_positive_integer(
            _required(budget, "max_artifact_bytes", "budget", project_path),
            "budget.max_artifact_bytes",
            project_path,
        ),
        primary_metric=_nonempty_string(
            _required(objective, "primary_metric", "objective", constitution_path),
            "objective.primary_metric",
            constitution_path,
        ),
        direction=direction,
        baseline_repeats=_positive_integer(
            _required(baseline, "repeats", "baseline", constitution_path),
            "baseline.repeats",
            constitution_path,
        ),
        baseline_tolerance=_nonnegative_number(
            _required(baseline, "tolerance", "baseline", constitution_path),
            "baseline.tolerance",
            constitution_path,
        ),
        minimum_improvement=_nonnegative_number(
            _required(promotion, "minimum_improvement", "promotion", constitution_path),
            "promotion.minimum_improvement",
            constitution_path,
        ),
        gates=_gate_definitions(promotion.get("gates", ()), constitution_path),
    )


def discover_and_load_project_config(
    start: str | os.PathLike[str] | Path | None = None,
) -> ProjectConfig:
    """Convenience wrapper combining walk-up discovery and loading."""

    return load_project_config(find_project_root(start))


DESIGN_PROVENANCE: dict[str, tuple[str, ...]] = {
    "ProjectConfig": (
        "Bounded mutable surface",
        "Immutable evaluation",
        "Fixed experiment budget",
    ),
    "ensure_runtime_directory": ("Bounded mutable surface", "Durable graph memory"),
    "find_project_root": ("Bounded mutable surface",),
    "validate_relative_path": ("Bounded mutable surface",),
    "authorized_action": ("Reversible ratchet",),
}
