"""Install the packaged Research OS skill for supported coding agents."""

from __future__ import annotations

import os
import stat
from importlib import resources
from pathlib import Path
from typing import Final, Iterable

from research_os.errors import ConfigurationError

_DESTINATIONS: Final = {
    "codex": Path(".agents/skills/research-os"),
    "claude": Path(".claude/skills/research-os"),
}
_RESOURCE_FILES: Final = (
    Path("SKILL.md"),
    Path("agents/openai.yaml"),
    Path("references/status-actions.md"),
)


def _resource_bytes(relative: Path) -> bytes:
    item = resources.files("research_os").joinpath(
        "resources", "research-os", *relative.parts
    )
    if not item.is_file():
        raise ConfigurationError(
            f"packaged Research OS agent skill is incomplete: {relative.as_posix()}"
        )
    return item.read_bytes()


def _safe_directory(path: Path, *, create: bool) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not create:
            raise ConfigurationError(
                f"agent skill directory does not exist: {path}"
            ) from None
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ConfigurationError(
            f"agent skill path must be a non-symlink directory: {path}"
        )


def _ensure_parent(home: Path, relative: Path) -> Path:
    home = home.resolve(strict=True)
    _safe_directory(home, create=False)
    current = home
    for part in relative.parts:
        current = current / part
        _safe_directory(current, create=True)
    return current


def _expected_files() -> dict[Path, bytes]:
    return {relative: _resource_bytes(relative) for relative in _RESOURCE_FILES}


def _installed_files(destination: Path) -> dict[Path, bytes]:
    observed: dict[Path, bytes] = {}
    for entry in destination.rglob("*"):
        relative = entry.relative_to(destination)
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ConfigurationError(
                f"installed agent skill contains a symbolic link: {entry}"
            )
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise ConfigurationError(
                f"installed agent skill contains a special file: {entry}"
            )
        observed[relative] = entry.read_bytes()
    return observed


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("short write while installing agent skill")
        offset += written


def _remove_owned_tree(destination: Path, identity: tuple[int, int]) -> None:
    try:
        current = destination.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(current.st_mode) or (current.st_dev, current.st_ino) != identity:
        return
    for entry in sorted(
        destination.rglob("*"), key=lambda item: len(item.parts), reverse=True
    ):
        info = entry.lstat()
        if stat.S_ISLNK(info.st_mode) or stat.S_ISREG(info.st_mode):
            entry.unlink()
        elif stat.S_ISDIR(info.st_mode):
            entry.rmdir()
    destination.rmdir()


def _preflight_one(
    target: str, home: Path, expected: dict[Path, bytes]
) -> None:
    relative = _DESTINATIONS[target]
    home = home.resolve(strict=True)
    _safe_directory(home, create=False)
    current = home
    for part in relative.parent.parts:
        current = current / part
        try:
            _safe_directory(current, create=False)
        except ConfigurationError as exc:
            if not current.exists() and not current.is_symlink():
                return
            raise exc
    destination = current / relative.name
    try:
        existing = destination.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(existing.st_mode) or not stat.S_ISDIR(existing.st_mode):
        raise ConfigurationError(
            f"refusing to replace existing agent skill path: {destination}"
        )
    if _installed_files(destination) != expected:
        raise ConfigurationError(
            "refusing to overwrite a different Research OS agent skill: "
            f"{destination}"
        )


def _install_one(
    target: str, home: Path, expected: dict[Path, bytes]
) -> dict[str, str]:
    relative = _DESTINATIONS[target]
    parent = _ensure_parent(home, relative.parent)
    destination = parent / relative.name
    try:
        existing = destination.lstat()
    except FileNotFoundError:
        existing = None
    if existing is not None:
        if stat.S_ISLNK(existing.st_mode) or not stat.S_ISDIR(existing.st_mode):
            raise ConfigurationError(
                f"refusing to replace existing agent skill path: {destination}"
            )
        if _installed_files(destination) != expected:
            raise ConfigurationError(
                "refusing to overwrite a different Research OS agent skill: "
                f"{destination}"
            )
        return {
            "target": target,
            "destination": str(destination),
            "status": "already_current",
        }

    try:
        destination.mkdir(mode=0o700)
    except FileExistsError:
        _preflight_one(target, home, expected)
        return {
            "target": target,
            "destination": str(destination),
            "status": "already_current",
        }
    installed = destination.lstat()
    identity = (installed.st_dev, installed.st_ino)
    try:
        for relative_path, content in expected.items():
            output = destination / relative_path
            output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(output, flags, 0o600)
            try:
                _write_all(descriptor, content)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        if _installed_files(destination) != expected:
            raise OSError("installed agent skill failed its byte-for-byte check")
    except BaseException:
        _remove_owned_tree(destination, identity)
        raise
    return {
        "target": target,
        "destination": str(destination),
        "status": "installed",
    }


def _rollback_installed(destination: Path, expected: dict[Path, bytes]) -> None:
    try:
        info = destination.lstat()
    except FileNotFoundError:
        return
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or _installed_files(destination) != expected
    ):
        return
    _remove_owned_tree(destination, (info.st_dev, info.st_ino))


def install_agent_skill(
    target: str = "all", *, home: Path | None = None
) -> list[dict[str, str]]:
    """Install one packaged skill for Codex, Claude Code, or both.

    Existing byte-identical installations are accepted. Any collision or drift
    is rejected rather than overwritten.
    """

    if target not in {"all", *_DESTINATIONS}:
        raise ValueError("target must be one of: all, codex, claude")
    selected_value: Iterable[str] = _DESTINATIONS if target == "all" else (target,)
    selected = tuple(selected_value)
    resolved_home = Path.home() if home is None else Path(home)
    expected = _expected_files()
    for name in selected:
        _preflight_one(name, resolved_home, expected)

    installed: list[dict[str, str]] = []
    created: list[Path] = []
    try:
        for name in selected:
            record = _install_one(name, resolved_home, expected)
            installed.append(record)
            if record["status"] == "installed":
                created.append(Path(record["destination"]))
    except BaseException:
        for destination in reversed(created):
            _rollback_installed(destination, expected)
        raise
    return installed


__all__ = ["install_agent_skill"]
