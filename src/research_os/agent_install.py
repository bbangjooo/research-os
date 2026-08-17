"""Install the packaged Research OS skill for supported coding agents."""

from __future__ import annotations

import ctypes
import errno
import fcntl
import hashlib
import json
import os
import stat
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Final, Iterable, Iterator, Literal, Mapping, cast

from research_os import __version__
from research_os.errors import ConfigurationError

_DESTINATIONS: Final = {
    "codex": Path(".agents/skills/research-os"),
    "claude": Path(".claude/skills/research-os"),
}
_REQUIRED_RESOURCE_FILES: Final = (
    Path("SKILL.md"),
    Path("agents/openai.yaml"),
    Path("references/status-actions.md"),
)
_MANIFEST_PATH: Final = Path(".research-os-managed.json")
_MANIFEST_OWNER: Final = "research-os-agent-skill"
_LOCK_NAME: Final = ".research-os-agent-skill.lock"
_BACKUP_ROOT_NAME: Final = ".research-os-agent-skill-backups"
_DARWIN_RENAME_EXCL: Final = 0x00000004
_LINUX_RENAME_NOREPLACE: Final = 1

# The first released installer did not write an ownership manifest.  This is
# the one deliberately supported migration exception.  Paths, sizes, hashes,
# and directories must all match; a merely similar or locally edited tree is
# never adopted.
_LEGACY_0_1_0_FILES: Final[dict[Path, tuple[int, str]]] = {
    Path("SKILL.md"): (
        7313,
        "0936a11c83495edb8c50eb012e85cf37989fb63d2248ee8a679816447e130d30",
    ),
    Path("agents/openai.yaml"): (
        218,
        "a4e0ea2cb6b7ee315c578092a09c09e961e86cb729b457fe276b056c903b359b",
    ),
    Path("references/status-actions.md"): (
        2034,
        "9ea331def5b04f071bda77d3a06711455b5c2a7b1b5b3c0b80691e2ae1165c11",
    ),
}
_LEGACY_0_1_0_DIRECTORIES: Final = frozenset({Path("agents"), Path("references")})

# Managed releases are eligible for replacement only when the complete installed
# tree is byte-identical to a published checkpoint.  The 0.2.0 signature is from
# commit 6f36a1b; the manifest itself is part of the signed tree rather than a
# source of authority supplied by the installation being inspected.
_KNOWN_MANAGED_RELEASE_FILES: Final[dict[str, dict[Path, tuple[int, str]]]] = {
    "0.2.0": {
        Path(".research-os-managed.json"): (
            595,
            "3001753fa5f0908ccdfa63f5f3e4c9e8dabe596b73c20584b26b990075e11be0",
        ),
        Path("SKILL.md"): (
            14409,
            "0cab9ff5279b7715c02688d4e26c4c745200400fb2ffad657924a6cec1a59a9f",
        ),
        Path("agents/openai.yaml"): (
            218,
            "a4e0ea2cb6b7ee315c578092a09c09e961e86cb729b457fe276b056c903b359b",
        ),
        Path("references/scientific-protocol.md"): (
            13411,
            "b05812c5bc7bf10f55c216f36a15693dcb30f89601564abf8ab93bb0850354d8",
        ),
        Path("references/status-actions.md"): (
            2686,
            "5e7654d2913dc7bde67eff937126cf25808b92b4cf87625aa6f354a7f4da429e",
        ),
    },
    "0.3.0": {
        Path(".research-os-managed.json"): (
            595,
            "c912a0fc91e87ada01a32b0c3e205b78ee309bfa438683c36f0de256814e77c4",
        ),
        Path("SKILL.md"): (
            15506,
            "0f46444cf08637ebd7c98451b6e84a34aa3e39c8859e0b257e91b0a985111278",
        ),
        Path("agents/openai.yaml"): (
            218,
            "a4e0ea2cb6b7ee315c578092a09c09e961e86cb729b457fe276b056c903b359b",
        ),
        Path("references/scientific-protocol.md"): (
            13411,
            "b05812c5bc7bf10f55c216f36a15693dcb30f89601564abf8ab93bb0850354d8",
        ),
        Path("references/status-actions.md"): (
            2686,
            "5e7654d2913dc7bde67eff937126cf25808b92b4cf87625aa6f354a7f4da429e",
        ),
    },
    "0.4.0": {
        Path(".research-os-managed.json"): (
            595,
            "64e6c2c74b6a5cb939a3b321b894d1d66c06d22cb84e8a089d3d64f00276b705",
        ),
        Path("SKILL.md"): (
            16128,
            "90df221007e489355bf85f76ca08d1afcbd8fce2165bb510a9cea5840b77969d",
        ),
        Path("agents/openai.yaml"): (
            218,
            "a4e0ea2cb6b7ee315c578092a09c09e961e86cb729b457fe276b056c903b359b",
        ),
        Path("references/scientific-protocol.md"): (
            14755,
            "ef19072bf83b896bd4038674b834b24a8004ee23044ecb4c217a6e56177b470a",
        ),
        Path("references/status-actions.md"): (
            2686,
            "5e7654d2913dc7bde67eff937126cf25808b92b4cf87625aa6f354a7f4da429e",
        ),
    },
    # The 0.5.0 signature is the tree published at commit 2bb7a88.  It was
    # omitted at release time, which is why an installation made from the
    # genuine 0.5.0 release could not be upgraded.
    "0.5.0": {
        Path(".research-os-managed.json"): (
            595,
            "6f52a50f04e88681adb05aff8b4586a410b8a9cad3572d6e4495ca9e7fcce521",
        ),
        Path("SKILL.md"): (
            16854,
            "8ee52ee54d8ccd5a60ea13d4fb425130d0fff92d6b460506cff560c570f30f40",
        ),
        Path("agents/openai.yaml"): (
            218,
            "a4e0ea2cb6b7ee315c578092a09c09e961e86cb729b457fe276b056c903b359b",
        ),
        Path("references/scientific-protocol.md"): (
            16009,
            "f8b32832b912c2ed766490e78aeadfb4ad2246e3f211112f71d4ebeb8a794e80",
        ),
        Path("references/status-actions.md"): (
            2686,
            "5e7654d2913dc7bde67eff937126cf25808b92b4cf87625aa6f354a7f4da429e",
        ),
    },
}
# The exact tree an installation writes at the current __version__.  Changing a
# shipped skill byte or the release identity must be deliberate: register the
# outgoing tree above, bump __version__, then update this digest.  v0.5.0 shipped
# and the tree then changed twice without either step, which left every
# installation made afterwards unrecognizable to the upgrade path.
_SHIPPED_SKILL_TREE_DIGEST: Final = (
    "3c2ed90e788120a27a611ae7402c47a3c43b39cb5ae013e62952e33c1d0444e5"
)

_KNOWN_MANAGED_RELEASE_DIRECTORIES: Final = frozenset(
    {Path("agents"), Path("references")}
)

_StateKind = Literal["absent", "current", "legacy"]


@dataclass(frozen=True)
class _TreeSnapshot:
    files: Mapping[Path, bytes]
    directories: frozenset[Path]
    identity: tuple[int, int]


@dataclass(frozen=True)
class _TargetState:
    target: str
    destination: Path
    kind: _StateKind
    snapshot: _TreeSnapshot | None = None
    prior_release: str | None = None


@dataclass
class _PreparedTarget:
    state: _TargetState
    transaction: Path
    transaction_identity: tuple[int, int]
    staged: Path
    staged_identity: tuple[int, int]
    backup: Path
    exposed_recovery: Path
    backup_moved: bool = False
    new_installed: bool = False
    exposure_attempted: bool = False


def _resource_root():
    return resources.files("research_os").joinpath("resources", "research-os")


def _walk_resources(node, prefix: Path = Path()) -> Iterator[tuple[Path, bytes]]:
    try:
        children = sorted(node.iterdir(), key=lambda child: child.name)
    except (FileNotFoundError, NotADirectoryError) as exc:
        raise ConfigurationError("packaged Research OS agent skill directory is missing") from exc
    for child in children:
        relative = prefix / child.name
        if child.is_dir():
            yield from _walk_resources(child, relative)
        elif child.is_file():
            yield relative, child.read_bytes()
        else:
            raise ConfigurationError(
                "packaged Research OS agent skill contains an unsupported entry: "
                f"{relative.as_posix()}"
            )


def _packaged_files() -> dict[Path, bytes]:
    root = _resource_root()
    if not root.is_dir():
        raise ConfigurationError("packaged Research OS agent skill directory is missing")
    packaged = dict(_walk_resources(root))
    if _MANIFEST_PATH in packaged:
        raise ConfigurationError(
            f"packaged agent skill uses reserved path: {_MANIFEST_PATH.as_posix()}"
        )
    for required in _REQUIRED_RESOURCE_FILES:
        if required not in packaged:
            raise ConfigurationError(
                f"packaged Research OS agent skill is incomplete: {required.as_posix()}"
            )
    return packaged


def _managed_manifest(packaged: Mapping[Path, bytes]) -> bytes:
    files = [
        {
            "path": relative.as_posix(),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        for relative, content in sorted(packaged.items(), key=lambda item: item[0].as_posix())
    ]
    value = {
        "files": files,
        "owner": _MANIFEST_OWNER,
        "release": __version__,
        "schema_version": 1,
    }
    rendered = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return (rendered + "\n").encode("utf-8")


def _expected_files() -> dict[Path, bytes]:
    packaged = _packaged_files()
    expected = dict(packaged)
    expected[_MANIFEST_PATH] = _managed_manifest(packaged)
    return expected


def shipped_skill_tree_digest() -> str:
    """Digest the exact tree an installation would write right now.

    The manifest embeds ``__version__``, so this changes when either a resource
    byte or the release identity changes.  ``_SHIPPED_SKILL_TREE_DIGEST`` pins
    it, which forces any such change to be a deliberate edit here rather than a
    silent one somewhere in the resource tree.
    """

    rows = [
        {
            "path": relative.as_posix(),
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
        }
        for relative, content in sorted(
            _expected_files().items(), key=lambda item: item[0].as_posix()
        )
    ]
    rendered = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _expected_directories(files: Iterable[Path]) -> frozenset[Path]:
    directories: set[Path] = set()
    for relative in files:
        parent = relative.parent
        while parent != Path("."):
            directories.add(parent)
            parent = parent.parent
    return frozenset(directories)


def _identity(info: os.stat_result) -> tuple[int, int]:
    return (info.st_dev, info.st_ino)


def _same_file_state(before: os.stat_result, after: os.stat_result) -> bool:
    return (
        _identity(before) == _identity(after)
        and before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and before.st_ctime_ns == after.st_ctime_ns
    )


def _read_file_at(
    directory_fd: int,
    name: str,
    expected_info: os.stat_result,
    display: Path,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(name, flags, dir_fd=directory_fd)
    except OSError as exc:
        raise ConfigurationError(
            f"installed agent skill file could not be opened safely: {display}"
        ) from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or _identity(before) != _identity(expected_info):
            raise ConfigurationError(
                f"installed agent skill file was replaced while reading: {display}"
            )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        if not _same_file_state(before, after):
            raise ConfigurationError(f"installed agent skill file changed while reading: {display}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _scan_directory_fd(
    descriptor: int,
    *,
    prefix: Path,
    display_root: Path,
    files: dict[Path, bytes],
    directories: set[Path],
) -> None:
    with os.scandir(descriptor) as iterator:
        entries = sorted(iterator, key=lambda entry: entry.name)
    for entry in entries:
        relative = prefix / entry.name
        display = display_root / relative
        try:
            info = entry.stat(follow_symlinks=False)
        except OSError as exc:
            raise ConfigurationError(
                f"installed agent skill entry changed while scanning: {display}"
            ) from exc
        if stat.S_ISLNK(info.st_mode):
            raise ConfigurationError(f"installed agent skill contains a symbolic link: {display}")
        if stat.S_ISDIR(info.st_mode):
            flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
            try:
                child_fd = os.open(entry.name, flags, dir_fd=descriptor)
            except OSError as exc:
                raise ConfigurationError(
                    f"installed agent skill directory could not be opened safely: {display}"
                ) from exc
            try:
                opened = os.fstat(child_fd)
                if not stat.S_ISDIR(opened.st_mode) or _identity(opened) != _identity(info):
                    raise ConfigurationError(
                        f"installed agent skill directory was replaced while reading: {display}"
                    )
                directories.add(relative)
                _scan_directory_fd(
                    child_fd,
                    prefix=relative,
                    display_root=display_root,
                    files=files,
                    directories=directories,
                )
                named_after = os.stat(entry.name, dir_fd=descriptor, follow_symlinks=False)
                if _identity(named_after) != _identity(opened):
                    raise ConfigurationError(
                        f"installed agent skill directory was replaced while reading: {display}"
                    )
            finally:
                os.close(child_fd)
            continue
        if stat.S_ISREG(info.st_mode):
            content = _read_file_at(descriptor, entry.name, info, display)
            try:
                named_after = os.stat(entry.name, dir_fd=descriptor, follow_symlinks=False)
            except OSError as exc:
                raise ConfigurationError(
                    f"installed agent skill file changed while reading: {display}"
                ) from exc
            if _identity(named_after) != _identity(info):
                raise ConfigurationError(
                    f"installed agent skill file was replaced while reading: {display}"
                )
            files[relative] = content
            continue
        raise ConfigurationError(f"installed agent skill contains a special file: {display}")


def _snapshot_tree(destination: Path) -> _TreeSnapshot:
    try:
        initial = destination.lstat()
    except FileNotFoundError:
        raise ConfigurationError(f"agent skill directory does not exist: {destination}") from None
    if stat.S_ISLNK(initial.st_mode) or not stat.S_ISDIR(initial.st_mode):
        raise ConfigurationError(f"refusing to replace existing agent skill path: {destination}")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(destination, flags)
    except OSError as exc:
        raise ConfigurationError(
            f"agent skill directory could not be opened safely: {destination}"
        ) from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISDIR(opened.st_mode) or _identity(opened) != _identity(initial):
            raise ConfigurationError(
                f"agent skill directory was replaced while reading: {destination}"
            )
        files: dict[Path, bytes] = {}
        directories: set[Path] = set()
        _scan_directory_fd(
            descriptor,
            prefix=Path(),
            display_root=destination,
            files=files,
            directories=directories,
        )
        after_fd = os.fstat(descriptor)
        if _identity(after_fd) != _identity(opened):
            raise ConfigurationError(
                f"agent skill directory was replaced while reading: {destination}"
            )
    finally:
        os.close(descriptor)
    try:
        named_after = destination.lstat()
    except FileNotFoundError as exc:
        raise ConfigurationError(
            f"agent skill directory was replaced while reading: {destination}"
        ) from exc
    if stat.S_ISLNK(named_after.st_mode) or _identity(named_after) != _identity(opened):
        raise ConfigurationError(f"agent skill directory was replaced while reading: {destination}")
    return _TreeSnapshot(files, frozenset(directories), _identity(opened))


def _installed_files(destination: Path) -> dict[Path, bytes]:
    """Return safely read files for compatibility with the original installer."""

    return dict(_snapshot_tree(destination).files)


def _is_current(snapshot: _TreeSnapshot, expected: Mapping[Path, bytes]) -> bool:
    return snapshot.files == expected and snapshot.directories == _expected_directories(expected)


def _is_legacy_0_1_0(snapshot: _TreeSnapshot) -> bool:
    if snapshot.directories != _LEGACY_0_1_0_DIRECTORIES:
        return False
    if set(snapshot.files) != set(_LEGACY_0_1_0_FILES):
        return False
    for relative, (expected_size, expected_digest) in _LEGACY_0_1_0_FILES.items():
        content = snapshot.files[relative]
        if len(content) != expected_size:
            return False
        if hashlib.sha256(content).hexdigest() != expected_digest:
            return False
    return True


def _known_managed_release(snapshot: _TreeSnapshot) -> str | None:
    if snapshot.directories != _KNOWN_MANAGED_RELEASE_DIRECTORIES:
        return None
    for release, signature in _KNOWN_MANAGED_RELEASE_FILES.items():
        if set(snapshot.files) != set(signature):
            continue
        if all(
            len(snapshot.files[relative]) == expected_size
            and hashlib.sha256(snapshot.files[relative]).hexdigest() == expected_digest
            for relative, (expected_size, expected_digest) in signature.items()
        ):
            return release
    return None


def _safe_directory(path: Path, *, create: bool) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not create:
            raise ConfigurationError(f"agent skill directory does not exist: {path}") from None
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ConfigurationError(f"agent skill path must be a non-symlink directory: {path}")


def _resolve_home(home: Path) -> Path:
    raw = home.expanduser()
    try:
        info = raw.lstat()
    except FileNotFoundError:
        raise ConfigurationError(f"agent home directory does not exist: {raw}") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ConfigurationError(f"agent home must be a non-symlink directory: {raw}")
    return raw.resolve(strict=True)


def _ensure_parent(home: Path, relative: Path) -> Path:
    current = home
    for part in relative.parts:
        current = current / part
        _safe_directory(current, create=True)
    return current


@contextmanager
def _installation_lock(home: Path) -> Iterator[None]:
    lock_path = home / _LOCK_NAME
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        raise ConfigurationError(f"agent skill installer lock is unsafe: {lock_path}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ConfigurationError(
                f"agent skill installer lock must be a regular file: {lock_path}"
            )
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _classify_one(
    target: str,
    home: Path,
    expected: Mapping[Path, bytes],
    *,
    upgrade: bool,
) -> _TargetState:
    relative = _DESTINATIONS[target]
    destination = home / relative
    current = home
    for part in relative.parent.parts:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return _TargetState(target, destination, "absent")
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise ConfigurationError(f"agent skill path must be a non-symlink directory: {current}")
    try:
        existing = destination.lstat()
    except FileNotFoundError:
        return _TargetState(target, destination, "absent")
    if stat.S_ISLNK(existing.st_mode) or not stat.S_ISDIR(existing.st_mode):
        raise ConfigurationError(f"refusing to replace existing agent skill path: {destination}")
    snapshot = _snapshot_tree(destination)
    if _is_current(snapshot, expected):
        return _TargetState(target, destination, "current", snapshot)
    prior_release = "0.1.0" if _is_legacy_0_1_0(snapshot) else _known_managed_release(snapshot)
    if prior_release is not None:
        if upgrade:
            return _TargetState(
                target,
                destination,
                "legacy",
                snapshot,
                prior_release,
            )
        raise ConfigurationError(
            "existing Research OS agent skill is a recognized prior release; "
            f"rerun with --upgrade to replace it: {destination}"
        )
    marker_note = ""
    if _MANIFEST_PATH in snapshot.files:
        marker_note = " managed manifest is unknown or its tree has drifted;"
    raise ConfigurationError(
        f"refusing to overwrite a different Research OS agent skill:{marker_note} {destination}"
    )


def _write_all(descriptor: int, data: bytes) -> None:
    offset = 0
    while offset < len(data):
        written = os.write(descriptor, data[offset:])
        if written <= 0:
            raise OSError("short write while installing agent skill")
        offset += written


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _open_directory_fd(path: Path, *, label: str) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ConfigurationError(f"{label} could not be opened safely: {path}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode):
            raise ConfigurationError(f"{label} is not a directory: {path}")
    except BaseException:
        os.close(descriptor)
        raise
    return descriptor


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically rename ``source`` only when ``destination`` is absent.

    A check followed by ``os.rename`` is unsafe for directories because POSIX
    permits replacing an empty directory created between those two operations.
    There is no portable stdlib no-replace primitive, so supported kernels are
    called directly and every other platform fails closed.
    """

    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin":
        symbol = "renameatx_np"
        flags = _DARWIN_RENAME_EXCL
    elif sys.platform.startswith("linux"):
        symbol = "renameat2"
        flags = _LINUX_RENAME_NOREPLACE
    else:
        raise ConfigurationError(
            f"atomic no-replace rename is unavailable on platform {sys.platform!r}"
        )
    try:
        operation = getattr(libc, symbol)
    except AttributeError as exc:
        raise ConfigurationError(
            f"atomic no-replace rename primitive {symbol} is unavailable"
        ) from exc
    operation.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    operation.restype = ctypes.c_int

    source_parent_fd = _open_directory_fd(source.parent, label="agent skill rename source parent")
    try:
        destination_parent_fd = _open_directory_fd(
            destination.parent, label="agent skill rename destination parent"
        )
    except BaseException:
        os.close(source_parent_fd)
        raise
    try:
        ctypes.set_errno(0)
        result = operation(
            source_parent_fd,
            os.fsencode(source.name),
            destination_parent_fd,
            os.fsencode(destination.name),
            flags,
        )
        if result != 0:
            error_number = ctypes.get_errno() or errno.EIO
            raise OSError(error_number, os.strerror(error_number), str(destination))
    finally:
        os.close(destination_parent_fd)
        os.close(source_parent_fd)


def _write_tree(destination: Path, expected: Mapping[Path, bytes]) -> tuple[int, int]:
    destination.mkdir(mode=0o700)
    for relative in sorted(
        _expected_directories(expected), key=lambda item: (len(item.parts), item.as_posix())
    ):
        _safe_directory(destination / relative, create=True)
    for relative, content in sorted(expected.items(), key=lambda item: item[0].as_posix()):
        output = destination / relative
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(output, flags, 0o600)
        try:
            _write_all(descriptor, content)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    for relative in sorted(
        _expected_directories(expected),
        key=lambda item: (-len(item.parts), item.as_posix()),
    ):
        _fsync_directory(destination / relative)
    _fsync_directory(destination)
    snapshot = _snapshot_tree(destination)
    if not _is_current(snapshot, expected):
        raise OSError("staged agent skill failed its byte-for-byte check")
    return snapshot.identity


def _remove_owned_tree(destination: Path, identity: tuple[int, int]) -> None:
    try:
        current = destination.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(current.st_mode) or _identity(current) != identity:
        return
    for entry in sorted(destination.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        info = entry.lstat()
        if stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode):
            entry.rmdir()
        else:
            entry.unlink()
    destination.rmdir()


def _backup_root(home: Path) -> Path:
    root = home / _BACKUP_ROOT_NAME
    try:
        root.lstat()
    except FileNotFoundError:
        created = True
    else:
        created = False
    _safe_directory(root, create=True)
    if created:
        _fsync_directory(home)
    return root


def _stage_one(state: _TargetState, home: Path, expected: Mapping[Path, bytes]) -> _PreparedTarget:
    relative = _DESTINATIONS[state.target]
    parent = _ensure_parent(home, relative.parent)
    recovery_root = _backup_root(home)
    parent_info = parent.lstat()
    recovery_info = recovery_root.lstat()
    if parent_info.st_dev != recovery_info.st_dev:
        raise ConfigurationError(
            "agent skill destination and HOME recovery root are on different "
            "filesystems; mounted skill directories cannot be installed safely: "
            f"{parent} and {recovery_root}"
        )
    prior_release = state.prior_release or "unknown"
    phase = f"upgrade-{prior_release}" if state.kind == "legacy" else f"install-{__version__}"
    transaction = Path(tempfile.mkdtemp(prefix=f"{state.target}-{phase}-", dir=recovery_root))
    transaction_info = transaction.lstat()
    transaction_identity = _identity(transaction_info)
    staged = transaction / "never-exposed-staging"
    try:
        _fsync_directory(recovery_root)
        staged_identity = _write_tree(staged, expected)
    except BaseException:
        _remove_owned_tree(transaction, transaction_identity)
        _fsync_directory(recovery_root)
        raise
    return _PreparedTarget(
        state=state,
        transaction=transaction,
        transaction_identity=transaction_identity,
        staged=staged,
        staged_identity=staged_identity,
        backup=transaction / f"prior-{prior_release}-recovery",
        exposed_recovery=transaction / "exposed-new-recovery",
    )


def _assert_unchanged(
    initial: _TargetState,
    home: Path,
    expected: Mapping[Path, bytes],
    *,
    upgrade: bool,
) -> None:
    current = _classify_one(initial.target, home, expected, upgrade=upgrade)
    if current != initial:
        raise ConfigurationError(
            f"agent skill target changed during installation: {initial.destination}"
        )


def _assert_prior_backup_unchanged(prepared: _PreparedTarget) -> None:
    if prepared.state.kind != "legacy":
        return
    assert prepared.state.snapshot is not None
    try:
        backup = _snapshot_tree(prepared.backup)
    except ConfigurationError as exc:
        raise ConfigurationError(
            "prior agent skill backup could not be verified; refusing to discard "
            f"user content: {prepared.backup}"
        ) from exc
    if backup != prepared.state.snapshot:
        raise ConfigurationError(
            "prior agent skill changed during installation; refusing to discard "
            f"user content: {prepared.backup}"
        )


def _commit_one(prepared: _PreparedTarget, expected: Mapping[Path, bytes]) -> None:
    state = prepared.state
    destination = state.destination
    parent = destination.parent
    if state.kind == "legacy":
        try:
            current = destination.lstat()
        except FileNotFoundError as exc:
            raise ConfigurationError(
                f"agent skill target changed during installation: {destination}"
            ) from exc
        assert state.snapshot is not None
        if stat.S_ISLNK(current.st_mode) or _identity(current) != state.snapshot.identity:
            raise ConfigurationError(
                f"agent skill target changed during installation: {destination}"
            )
        _rename_noreplace(destination, prepared.backup)
        prepared.backup_moved = True
        _fsync_directory(parent)
        _fsync_directory(prepared.transaction)
        _assert_prior_backup_unchanged(prepared)
    else:
        try:
            destination.lstat()
        except FileNotFoundError:
            pass
        else:
            raise ConfigurationError(
                f"agent skill target changed during installation: {destination}"
            )
    # Mark before entering the syscall.  This is deliberately conservative:
    # if cancellation lands after the kernel move but before Python returns,
    # rollback must retain this inode tree as publicly exposed.
    prepared.exposure_attempted = True
    try:
        _rename_noreplace(prepared.staged, destination)
    except FileExistsError:
        # RENAME_EXCL/RENAME_NOREPLACE guarantee that this error leaves both
        # names untouched, so the staged tree was never publicly exposed.
        prepared.exposure_attempted = False
        raise
    prepared.new_installed = True
    _fsync_directory(prepared.transaction)
    _fsync_directory(parent)
    installed = _snapshot_tree(destination)
    if installed.identity != prepared.staged_identity or not _is_current(installed, expected):
        raise OSError("installed agent skill failed its byte-for-byte check")


def _directory_identity_or_none(path: Path, *, label: str) -> tuple[int, int] | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise ConfigurationError(f"{label} is not a safe directory: {path}")
    return _identity(info)


def _rollback_rename(source: Path, destination: Path, identity: tuple[int, int]) -> None:
    """Rename during rollback, accepting an exception only if the move completed.

    A cancellation can arrive after the kernel completed ``rename`` but before
    Python returns.  The original installation exception is already being
    preserved by the caller, so rollback must finish when inode locations prove
    that this recovery rename succeeded.
    """

    try:
        _rename_noreplace(source, destination)
    except BaseException:
        source_identity = _directory_identity_or_none(source, label="rollback source")
        destination_identity = _directory_identity_or_none(
            destination, label="rollback destination"
        )
        if source_identity is None and destination_identity == identity:
            return
        raise


def _prepared_locations(prepared: _PreparedTarget) -> dict[str, tuple[int, int] | None]:
    transaction_identity = _directory_identity_or_none(
        prepared.transaction, label="agent skill transaction"
    )
    if transaction_identity != prepared.transaction_identity:
        raise ConfigurationError(
            f"agent skill transaction directory changed: {prepared.transaction}"
        )
    return {
        "destination": _directory_identity_or_none(
            prepared.state.destination, label="agent skill destination"
        ),
        "staged": _directory_identity_or_none(prepared.staged, label="staged agent skill"),
        "backup": _directory_identity_or_none(prepared.backup, label="prior agent skill backup"),
        "exposed_recovery": _directory_identity_or_none(
            prepared.exposed_recovery, label="exposed agent skill recovery"
        ),
    }


def _unique_location(
    locations: Mapping[str, tuple[int, int] | None], identity: tuple[int, int]
) -> str | None:
    matches = [name for name, observed in locations.items() if observed == identity]
    if len(matches) > 1:
        raise ConfigurationError(
            "agent skill transaction contains the same managed directory at "
            f"multiple locations: {', '.join(matches)}"
        )
    return matches[0] if matches else None


def _retain_exposed_new(
    prepared: _PreparedTarget,
    locations: Mapping[str, tuple[int, int] | None],
    new_location: str | None,
) -> bool:
    exposed = prepared.exposure_attempted or new_location in {
        "destination",
        "exposed_recovery",
    }
    if not exposed:
        return False
    if new_location is None:
        raise ConfigurationError(
            "cannot locate a possibly exposed agent skill tree; recovery transaction "
            f"preserved at {prepared.transaction}"
        )
    if new_location == "exposed_recovery":
        return True
    if new_location not in {"destination", "staged"}:
        raise ConfigurationError(
            "possibly exposed agent skill is in an unsafe recovery location; "
            f"transaction preserved at {prepared.transaction}"
        )
    if locations["exposed_recovery"] is not None:
        raise ConfigurationError(
            "exposed agent skill recovery path is occupied; transaction preserved at "
            f"{prepared.transaction}"
        )
    source = prepared.state.destination if new_location == "destination" else prepared.staged
    _rollback_rename(source, prepared.exposed_recovery, prepared.staged_identity)
    _fsync_directory(source.parent)
    if source.parent != prepared.transaction:
        _fsync_directory(prepared.transaction)
    prepared.new_installed = False
    return True


def _rollback_one(prepared: _PreparedTarget) -> None:
    destination = prepared.state.destination
    parent = destination.parent
    locations = _prepared_locations(prepared)
    new_location = _unique_location(locations, prepared.staged_identity)

    if prepared.state.kind == "absent":
        if not prepared.exposure_attempted and new_location in {"staged", None}:
            unexpected_transaction = {
                name: identity
                for name, identity in locations.items()
                if name != "destination"
                and identity is not None
                and identity != prepared.staged_identity
            }
            if not unexpected_transaction:
                # Atomic no-replace publication can report a concurrent public
                # target without having exposed our staged inode.  That target
                # belongs to the concurrent creator and must be left untouched;
                # the never-exposed staging tree remains safe to clean.
                prepared.new_installed = False
                return
        unexpected = {
            name: identity
            for name, identity in locations.items()
            if identity is not None and identity != prepared.staged_identity
        }
        if unexpected:
            raise ConfigurationError(
                "cannot restore an absent agent skill target because an unknown "
                f"directory occupies the transaction: {destination}"
            )
        retained = _retain_exposed_new(prepared, locations, new_location)
        if not retained and new_location not in {"staged", None}:
            raise ConfigurationError(
                f"installed agent skill is in an unsafe rollback location: {destination}"
            )
        if (
            retained
            and _directory_identity_or_none(
                prepared.exposed_recovery, label="exposed agent skill recovery"
            )
            != prepared.staged_identity
        ):
            raise ConfigurationError(
                f"exposed agent skill recovery could not be verified: {prepared.transaction}"
            )
        prepared.new_installed = False
        return

    assert prepared.state.snapshot is not None
    prior_identity = prepared.state.snapshot.identity
    prior_location = _unique_location(locations, prior_identity)
    allowed = {prepared.staged_identity, prior_identity}
    unexpected = {
        name: identity
        for name, identity in locations.items()
        if identity is not None and identity not in allowed
    }
    if unexpected:
        raise ConfigurationError(
            "cannot restore prior agent skill because an unknown directory occupies "
            f"the transaction; backup preserved at {prepared.backup}"
        )
    retained = _retain_exposed_new(prepared, locations, new_location)
    if prior_location == "destination":
        if not retained and new_location not in {"staged", None}:
            raise ConfigurationError(
                f"prior agent skill has an inconsistent transaction: {destination}"
            )
        prepared.backup_moved = False
        prepared.new_installed = False
        return
    if prior_location != "backup":
        raise ConfigurationError(
            "cannot locate the prior agent skill during rollback; transaction "
            f"preserved at {prepared.transaction}"
        )

    if not retained and new_location not in {"staged", None}:
        raise ConfigurationError(
            f"installed agent skill is in an unsafe rollback location: {destination}"
        )

    if _directory_identity_or_none(destination, label="agent skill destination") is not None:
        raise ConfigurationError(
            "cannot restore prior agent skill because its path is occupied: "
            f"{destination}; backup preserved at {prepared.backup}"
        )
    _rollback_rename(prepared.backup, destination, prior_identity)
    _fsync_directory(prepared.transaction)
    _fsync_directory(parent)
    restored = _directory_identity_or_none(destination, label="restored prior agent skill")
    if restored != prior_identity:
        raise ConfigurationError(
            f"prior agent skill restoration could not be verified: {destination}"
        )
    prepared.backup_moved = False
    prepared.new_installed = False


def _cleanup_transactions(
    prepared: Iterable[_PreparedTarget], *, committed: bool = False
) -> list[str]:
    errors: list[str] = []
    for item in reversed(tuple(prepared)):
        try:
            locations = _prepared_locations(item)
            backup_identity = locations["backup"]
            exposed_identity = locations["exposed_recovery"]
            staged_identity = locations["staged"]
            if committed and item.state.kind == "legacy":
                assert item.state.snapshot is not None
                if backup_identity != item.state.snapshot.identity:
                    raise ConfigurationError(
                        f"prior agent skill recovery backup is unavailable: {item.backup}"
                    )
            if (
                backup_identity is not None
                or exposed_identity is not None
                or (item.exposure_attempted and staged_identity is not None)
            ):
                # Any tree that may have appeared at the public destination is
                # retained by inode.  It may receive a late write through an
                # already-open descriptor after every possible snapshot.
                continue
            entries = list(item.transaction.iterdir())
            allowed_staging = (
                len(entries) == 1
                and entries[0] == item.staged
                and staged_identity == item.staged_identity
                and not item.exposure_attempted
            )
            if entries and not allowed_staging:
                raise ConfigurationError(
                    "refusing to clean an agent skill transaction containing "
                    f"unknown recovery data: {item.transaction}"
                )
            _remove_owned_tree(item.transaction, item.transaction_identity)
            _fsync_directory(item.transaction.parent)
        except BaseException as exc:  # cleanup must not prevent other rollbacks
            errors.append(f"{item.transaction}: {type(exc).__name__}: {exc}")
    return errors


def _recovery_paths(prepared: Iterable[_PreparedTarget]) -> tuple[Path, ...]:
    paths: list[Path] = []
    for item in prepared:
        initial_count = len(paths)
        try:
            locations = _prepared_locations(item)
        except ConfigurationError:
            if item.transaction.exists() or item.transaction.is_symlink():
                paths.append(item.transaction)
            continue
        if locations["backup"] is not None:
            paths.append(item.backup)
        if locations["exposed_recovery"] is not None:
            paths.append(item.exposed_recovery)
        if item.exposure_attempted and locations["staged"] is not None:
            paths.append(item.staged)
        if (
            len(paths) == initial_count
            and (item.exposure_attempted or item.backup_moved or item.new_installed)
            and (item.transaction.exists() or item.transaction.is_symlink())
        ):
            paths.append(item.transaction)
    return tuple(dict.fromkeys(path.resolve(strict=False) for path in paths))


def _attach_recovery_details(
    exception: BaseException,
    recovery_paths: Iterable[Path],
    *,
    rollback_errors: Iterable[str] = (),
) -> None:
    rendered_paths = tuple(str(path) for path in recovery_paths)
    details: list[str] = []
    if rendered_paths:
        details.append("agent skill recovery preserved at: " + ", ".join(rendered_paths))
        try:
            cast(Any, exception).recovery_paths = rendered_paths
        except BaseException:
            pass
    rendered_errors = tuple(
        error for error in rollback_errors if isinstance(error, str) and error.strip()
    )
    if rendered_errors:
        details.append("rollback warnings: " + "; ".join(rendered_errors))
        try:
            cast(Any, exception).rollback_errors = rendered_errors
        except BaseException:
            pass
    if not details:
        return
    note = "; ".join(details)
    try:
        exception.add_note(note)
    except (AttributeError, TypeError):
        pass
    try:
        if exception.args:
            exception.args = (f"{exception.args[0]}; {note}", *exception.args[1:])
        else:
            exception.args = (note,)
    except (AttributeError, TypeError):
        pass


def _records(
    states: Iterable[_TargetState],
    prepared_by_target: Mapping[str, _PreparedTarget],
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for state in states:
        if state.kind == "absent":
            status = "installed"
        elif state.kind == "legacy":
            status = "upgraded"
        else:
            status = "already_current"
        record = {
            "target": state.target,
            "destination": str(state.destination),
            "status": status,
        }
        if state.kind == "legacy":
            if state.prior_release is None:  # pragma: no cover - classifier invariant
                raise ConfigurationError("recognized prior agent skill omitted its release")
            record["from_release"] = state.prior_release
            record["to_release"] = __version__
            record["recovery_backup"] = str(prepared_by_target[state.target].backup)
        records.append(record)
    return records


def install_agent_skill(
    target: str = "all", *, home: Path | None = None, upgrade: bool = False
) -> list[dict[str, str]]:
    """Install or explicitly upgrade the packaged Research OS agent skill.

    A normal install accepts only a missing target or the exact current managed
    tree.  ``upgrade=True`` additionally accepts the byte-exact unmarked 0.1.0
    tree and byte-exact known managed releases.  All selected targets are staged
    before either target is changed, and ordinary exceptions (including
    cancellation) restore any already-replaced target before propagating.
    """

    if target not in {"all", *_DESTINATIONS}:
        raise ValueError("target must be one of: all, codex, claude")
    if not isinstance(upgrade, bool):
        raise TypeError("upgrade must be a boolean")
    selected_value: Iterable[str] = _DESTINATIONS if target == "all" else (target,)
    selected = tuple(selected_value)
    requested_home = Path.home() if home is None else Path(home)
    resolved_home = _resolve_home(requested_home)
    expected = _expected_files()

    with _installation_lock(resolved_home):
        states = tuple(
            _classify_one(name, resolved_home, expected, upgrade=upgrade) for name in selected
        )
        prepared: list[_PreparedTarget] = []
        try:
            for state in states:
                if state.kind != "current":
                    prepared.append(_stage_one(state, resolved_home, expected))
        except BaseException as primary:
            cleanup_errors = _cleanup_transactions(prepared)
            if cleanup_errors:
                raise ConfigurationError(
                    "agent skill staging failed and temporary cleanup was incomplete: "
                    + "; ".join(cleanup_errors)
                ) from primary
            raise

        try:
            for state in states:
                _assert_unchanged(state, resolved_home, expected, upgrade=upgrade)
            for item in prepared:
                _commit_one(item, expected)
            prepared_by_target = {item.state.target: item for item in prepared}
            for state in states:
                current = _classify_one(state.target, resolved_home, expected, upgrade=upgrade)
                if current.kind != "current":
                    raise OSError(
                        f"agent skill post-install verification failed: {state.destination}"
                    )
                item = prepared_by_target.get(state.target)
                expected_identity = (
                    state.snapshot.identity
                    if item is None and state.snapshot is not None
                    else item.staged_identity
                    if item is not None
                    else None
                )
                if current.snapshot is None or current.snapshot.identity != expected_identity:
                    raise ConfigurationError(
                        f"agent skill target changed during installation: {state.destination}"
                    )
            for item in prepared:
                _assert_prior_backup_unchanged(item)
        except BaseException as primary:
            rollback_errors: list[str] = []
            for item in reversed(prepared):
                try:
                    _rollback_one(item)
                except BaseException as exc:
                    rollback_errors.append(f"{item.state.destination}: {type(exc).__name__}: {exc}")
            if not rollback_errors:
                rollback_errors.extend(_cleanup_transactions(prepared))
            recovery_paths = _recovery_paths(prepared)
            _attach_recovery_details(
                primary,
                recovery_paths,
                rollback_errors=rollback_errors,
            )
            raise

        cleanup_errors = _cleanup_transactions(prepared, committed=True)
        if cleanup_errors:
            raise ConfigurationError(
                "agent skill installation completed but backup cleanup was incomplete: "
                + "; ".join(cleanup_errors)
            )
        return _records(states, prepared_by_target)


__all__ = ["install_agent_skill", "shipped_skill_tree_digest"]
