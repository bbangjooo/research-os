"""Content-addressed capture of bounded workspace artifacts."""

from __future__ import annotations

import errno
import hashlib
import mimetypes
import os
import stat
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar, cast

from research_os.errors import IntegrityError
from research_os.kernel._canonical import (
    JSONValue,
    canonical_bytes,
    json_value,
    require_text,
    strict_json_loads,
    utc_now,
    validate_timestamp,
)
from research_os.kernel.ids import stable_id, validate_namespaced_id


@dataclass(frozen=True, slots=True)
class ArtifactRecord(Mapping[str, Any]):
    artifact_id: str
    project_id: str
    experiment_id: str
    digest: str
    algorithm: str
    size: int
    relative_path: str
    storage_path: str
    role: str | None
    media_type: str | None
    metadata: dict[str, JSONValue]
    captured_at: str

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "artifact_id",
        "project_id",
        "experiment_id",
        "digest",
        "algorithm",
        "size",
        "relative_path",
        "storage_path",
        "role",
        "media_type",
        "metadata",
        "captured_at",
    )

    def __post_init__(self) -> None:
        try:
            artifact_id = validate_namespaced_id(self.artifact_id, "artifact")
            project_id = require_text(self.project_id, "project_id")
            experiment_id = require_text(self.experiment_id, "experiment_id")
            digest = require_text(self.digest, "digest").lower()
            algorithm = require_text(self.algorithm, "algorithm").lower()
            relative_path = require_text(self.relative_path, "relative_path")
            storage_path = require_text(self.storage_path, "storage_path")
            captured_at = validate_timestamp(self.captured_at, field="captured_at")
            metadata = json_value(self.metadata, path="$.metadata")
        except (TypeError, ValueError) as exc:
            raise IntegrityError(f"invalid artifact record: {exc}") from exc
        if algorithm != "sha256":
            raise IntegrityError("artifact algorithm must be 'sha256'")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise IntegrityError("artifact digest must be a lowercase SHA-256 digest")
        if (
            not isinstance(self.size, int)
            or isinstance(self.size, bool)
            or self.size < 0
        ):
            raise IntegrityError("artifact size must be a non-negative integer")
        if not isinstance(metadata, dict):
            raise IntegrityError("artifact metadata must be a JSON object")
        relative = PurePosixPath(relative_path)
        if (
            not relative.parts
            or relative.is_absolute()
            or "\\" in relative_path
            or any(part in {"", ".", ".."} for part in relative.parts)
        ):
            raise IntegrityError("artifact relative_path is unsafe")
        expected_storage = f"blobs/sha256/{digest[:2]}/{digest}"
        if storage_path != expected_storage:
            raise IntegrityError(
                "artifact storage_path does not match its content digest"
            )
        role = None if self.role is None else require_text(self.role, "role")
        media_type = (
            None
            if self.media_type is None
            else require_text(self.media_type, "media_type")
        )
        expected_id = stable_id(
            "artifact",
            project_id,
            experiment_id,
            relative_path,
            digest,
            role,
            media_type,
            metadata,
        )
        if artifact_id != expected_id:
            raise IntegrityError("artifact ID does not match its immutable metadata")
        object.__setattr__(self, "artifact_id", artifact_id)
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "experiment_id", experiment_id)
        object.__setattr__(self, "digest", digest)
        object.__setattr__(self, "algorithm", algorithm)
        object.__setattr__(self, "relative_path", relative_path)
        object.__setattr__(self, "storage_path", storage_path)
        object.__setattr__(self, "role", role)
        object.__setattr__(self, "media_type", media_type)
        object.__setattr__(self, "metadata", metadata)
        object.__setattr__(self, "captured_at", captured_at)

    @property
    def sha256(self) -> str:
        return self.digest

    @property
    def size_bytes(self) -> int:
        return self.size

    def to_dict(self) -> dict[str, Any]:
        return {key: self[key] for key in self._FIELDS}

    def __getitem__(self, key: str) -> Any:
        aliases = {
            "id": "artifact_id",
            "sha256": "digest",
            "size_bytes": "size",
            "path": "relative_path",
            "blob_path": "storage_path",
            "mime_type": "media_type",
        }
        key = aliases.get(key, key)
        if key not in self._FIELDS:
            raise KeyError(key)
        value = getattr(self, key)
        return json_value(value) if key == "metadata" else value

    def __iter__(self) -> Iterator[str]:
        return iter(self._FIELDS)

    def __len__(self) -> int:
        return len(self._FIELDS)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "ArtifactRecord":
        try:
            metadata = json_value(value["metadata"])
            if not isinstance(metadata, dict):
                raise TypeError("metadata must be a JSON object")
            return cls(
                artifact_id=require_text(value["artifact_id"], "artifact_id"),
                project_id=require_text(value["project_id"], "project_id"),
                experiment_id=require_text(value["experiment_id"], "experiment_id"),
                digest=require_text(value["digest"], "digest"),
                algorithm=require_text(value["algorithm"], "algorithm"),
                size=value["size"],
                relative_path=require_text(value["relative_path"], "relative_path"),
                storage_path=require_text(value["storage_path"], "storage_path"),
                role=value.get("role"),
                media_type=value.get("media_type"),
                metadata=metadata,
                captured_at=require_text(value["captured_at"], "captured_at"),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrityError(f"invalid artifact record: {exc}") from exc


@dataclass(frozen=True, slots=True)
class _CaptureRef:
    source: str | os.PathLike[str]
    role: str | None
    media_type: str | None
    metadata: dict[str, JSONValue]
    expected_digest: str | None
    expected_size: int | None


class ArtifactCatalog:
    """Capture regular files into an immutable SHA-256 blob catalog."""

    def __init__(self, root: str | os.PathLike[str], max_bytes: int):
        if (
            not isinstance(max_bytes, int)
            or isinstance(max_bytes, bool)
            or max_bytes < 0
        ):
            raise ValueError("max_bytes must be a non-negative integer")
        self.root = Path(os.path.abspath(os.fspath(Path(root).expanduser())))
        if self.root.is_symlink():
            raise IntegrityError(
                f"artifact catalog root must not be a symbolic link: {self.root}"
            )
        self.max_bytes = max_bytes
        self.blob_root = self.root / "blobs" / "sha256"
        self.record_root = self.root / "records"
        self.blob_root.mkdir(parents=True, exist_ok=True)
        self.record_root.mkdir(parents=True, exist_ok=True)
        for directory in (
            self.root,
            self.root / "blobs",
            self.blob_root,
            self.record_root,
        ):
            info = directory.lstat()
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise IntegrityError(
                    f"artifact catalog path must be a real directory: {directory}"
                )
            os.chmod(directory, 0o700)

    def capture(
        self,
        workspace: str | os.PathLike[str],
        project_id: str,
        experiment_id: str,
        refs: Any,
    ) -> list[ArtifactRecord]:
        """Capture all refs, enforcing a total uncompressed byte budget.

        A ref may be a relative path, an object with a ``path`` attribute, or a
        mapping with ``path``/``relative_path`` plus optional ``role`` (or
        ``kind``), ``media_type`` and JSON ``metadata``.  Absolute paths are
        accepted only when their resolved target is inside *workspace*.
        """

        project_id = require_text(project_id, "project_id")
        experiment_id = require_text(experiment_id, "experiment_id")
        workspace_path = Path(workspace).expanduser().resolve(strict=True)
        if not workspace_path.is_dir():
            raise IntegrityError(f"workspace is not a directory: {workspace_path}")

        workspace_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        workspace_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            workspace_fd = os.open(workspace_path, workspace_flags)
        except OSError as exc:
            raise IntegrityError(
                f"cannot safely open workspace {workspace_path}: {exc}"
            ) from exc
        workspace_info = os.fstat(workspace_fd)
        if not stat.S_ISDIR(workspace_info.st_mode):
            os.close(workspace_fd)
            raise IntegrityError(f"workspace is not a directory: {workspace_path}")

        try:
            capture_refs = self._coerce_refs(refs)
            prepared: list[tuple[_CaptureRef, str, os.stat_result]] = []
            seen_relative_paths: set[str] = set()
            declared_total = 0
            for ref in capture_refs:
                raw_path = Path(ref.source).expanduser()
                candidate = (
                    raw_path if raw_path.is_absolute() else workspace_path / raw_path
                )
                if candidate.is_symlink():
                    raise IntegrityError(
                        f"artifact ref must not be a symbolic link: {ref.source}"
                    )
                try:
                    source = candidate.resolve(strict=True)
                    relative = source.relative_to(workspace_path).as_posix()
                except (OSError, RuntimeError, ValueError) as exc:
                    raise IntegrityError(
                        f"artifact ref escapes or does not resolve in the workspace: {ref.source}"
                    ) from exc
                if not PurePosixPath(relative).parts:
                    raise IntegrityError(f"artifact ref must name a file: {ref.source}")
                if relative in seen_relative_paths:
                    raise IntegrityError(f"duplicate artifact path: {relative}")
                seen_relative_paths.add(relative)
                inspection_fd = -1
                try:
                    inspection_fd = self._open_workspace_file(workspace_fd, relative)
                    info = os.fstat(inspection_fd)
                except OSError as exc:
                    raise IntegrityError(
                        f"cannot safely inspect artifact ref {ref.source}: {exc}"
                    ) from exc
                finally:
                    if inspection_fd >= 0:
                        os.close(inspection_fd)
                if not stat.S_ISREG(info.st_mode):
                    raise IntegrityError(
                        f"artifact ref is not a regular file: {ref.source}"
                    )
                declared_total += info.st_size
                if declared_total > self.max_bytes:
                    raise IntegrityError(
                        f"artifact capture exceeds {self.max_bytes} byte limit"
                    )
                prepared.append((ref, relative, info))

            records: list[ArtifactRecord] = []
            consumed = 0
            for ref, relative, before in prepared:
                record, copied = self._capture_one(
                    workspace_fd,
                    relative,
                    before,
                    project_id,
                    experiment_id,
                    ref,
                    remaining=self.max_bytes - consumed,
                )
                consumed += copied
                records.append(record)
            return records
        finally:
            os.close(workspace_fd)

    @staticmethod
    def _coerce_refs(refs: Any) -> list[_CaptureRef]:
        if refs is None:
            return []
        if isinstance(refs, (str, os.PathLike)):
            values: list[Any] = [refs]
        elif isinstance(refs, Mapping):
            if any(key in refs for key in ("path", "relative_path", "file")):
                values = [refs]
            else:
                values = []
                for label, value in refs.items():
                    if isinstance(value, Mapping):
                        enriched = dict(value)
                        enriched.setdefault("role", str(label))
                    else:
                        enriched = {"path": value, "role": str(label)}
                    values.append(enriched)
        else:
            try:
                values = list(refs)
            except TypeError as exc:
                raise TypeError(
                    "artifact refs must be a path, mapping, or iterable"
                ) from exc

        result: list[_CaptureRef] = []
        for value in values:
            if isinstance(value, (str, os.PathLike)):
                source = value
                role = None
                media_type = None
                raw_metadata: Any = {}
                expected_digest = None
                expected_size = None
                declared: dict[str, Any] = {}
            elif isinstance(value, Mapping):
                source = value.get(
                    "path", value.get("relative_path", value.get("file"))
                )
                role = value.get("role", value.get("kind"))
                media_type = value.get("media_type", value.get("mime_type"))
                raw_metadata = value.get("metadata", {})
                expected_digest = value.get("sha256")
                expected_size = value.get("size_bytes")
                declared = {
                    key: value[key]
                    for key in ("retention", "sensitivity")
                    if key in value
                }
            else:
                source = getattr(value, "path", getattr(value, "relative_path", None))
                role = getattr(value, "role", getattr(value, "kind", None))
                media_type = getattr(
                    value, "media_type", getattr(value, "mime_type", None)
                )
                raw_metadata = getattr(value, "metadata", {})
                expected_digest = getattr(value, "sha256", None)
                expected_size = getattr(value, "size_bytes", None)
                declared = {
                    key: item
                    for key in ("retention", "sensitivity")
                    if (item := getattr(value, key, None)) is not None
                }
            if not isinstance(source, (str, os.PathLike)):
                raise TypeError("each artifact ref must supply a filesystem path")
            source_path = cast(str | os.PathLike[str], source)
            if role is not None:
                role = require_text(role, "artifact role")
            if media_type is not None:
                media_type = require_text(media_type, "artifact media_type")
            metadata = json_value(raw_metadata, path="$.metadata")
            if not isinstance(metadata, dict):
                raise TypeError("artifact metadata must be a mapping")
            for key, item in declared.items():
                metadata.setdefault(key, json_value(item, path=f"$.metadata.{key}"))
            if expected_digest is not None:
                expected_digest = require_text(
                    expected_digest, "artifact sha256"
                ).lower()
                if len(expected_digest) != 64 or any(
                    char not in "0123456789abcdef" for char in expected_digest
                ):
                    raise ValueError(
                        "artifact sha256 must be a 64-character hexadecimal digest"
                    )
            if expected_size is not None and (
                not isinstance(expected_size, int)
                or isinstance(expected_size, bool)
                or expected_size < 0
            ):
                raise ValueError("artifact size_bytes must be a non-negative integer")
            if (expected_digest is None) != (expected_size is None):
                raise ValueError(
                    "artifact sha256 and size_bytes must be supplied together"
                )
            result.append(
                _CaptureRef(
                    source_path,
                    role,
                    media_type,
                    metadata,
                    expected_digest,
                    expected_size,
                )
            )
        return result

    def _capture_one(
        self,
        workspace_fd: int,
        relative: str,
        before: os.stat_result,
        project_id: str,
        experiment_id: str,
        ref: _CaptureRef,
        *,
        remaining: int,
    ) -> tuple[ArtifactRecord, int]:
        try:
            source_fd = self._open_workspace_file(workspace_fd, relative)
        except OSError as exc:
            raise IntegrityError(f"cannot open artifact {relative}: {exc}") from exc
        temp_path: Path | None = None
        temp_fd: int | None = None
        try:
            opened = os.fstat(source_fd)
            if not stat.S_ISREG(opened.st_mode):
                raise IntegrityError(
                    f"artifact changed type before capture: {relative}"
                )
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise IntegrityError(f"artifact changed before capture: {relative}")
            temp_fd, temp_name = tempfile.mkstemp(
                prefix=".capture-", dir=self.blob_root
            )
            temp_path = Path(temp_name)
            os.fchmod(temp_fd, 0o600)
            digest = hashlib.sha256()
            size = 0
            while True:
                chunk = os.read(source_fd, 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > remaining:
                    raise IntegrityError(
                        f"artifact capture exceeds {self.max_bytes} byte limit"
                    )
                digest.update(chunk)
                offset = 0
                while offset < len(chunk):
                    written = os.write(temp_fd, chunk[offset:])
                    if written <= 0:
                        raise OSError("short write while copying artifact")
                    offset += written
            after = os.fstat(source_fd)
            if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
                opened.st_dev,
                opened.st_ino,
                opened.st_size,
                opened.st_mtime_ns,
            ) or size != after.st_size:
                raise IntegrityError(
                    f"artifact changed while being captured: {relative}"
                )
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = None

            hexdigest = digest.hexdigest()
            if ref.expected_digest is not None and hexdigest != ref.expected_digest:
                raise IntegrityError(
                    f"artifact digest does not match its declared sha256: {relative}"
                )
            if ref.expected_size is not None and size != ref.expected_size:
                raise IntegrityError(
                    f"artifact size does not match its declared size_bytes: {relative}"
                )
            blob_dir = self.blob_root / hexdigest[:2]
            blob_dir.mkdir(parents=True, exist_ok=True)
            blob_info = blob_dir.lstat()
            if stat.S_ISLNK(blob_info.st_mode) or not stat.S_ISDIR(blob_info.st_mode):
                raise IntegrityError(f"artifact blob path is unsafe: {blob_dir}")
            os.chmod(blob_dir, 0o700)
            blob_path = blob_dir / hexdigest
            try:
                os.link(temp_path, blob_path)
                self._fsync_directory(blob_dir)
            except FileExistsError:
                self._verify_blob(blob_path, hexdigest, size)
            finally:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass
                temp_path = None

            media_type = ref.media_type or mimetypes.guess_type(relative)[0]
            storage_path = blob_path.relative_to(self.root).as_posix()
            artifact_id = stable_id(
                "artifact",
                project_id,
                experiment_id,
                relative,
                hexdigest,
                ref.role,
                media_type,
                ref.metadata,
            )
            proposed = ArtifactRecord(
                artifact_id=artifact_id,
                project_id=project_id,
                experiment_id=experiment_id,
                digest=hexdigest,
                algorithm="sha256",
                size=size,
                relative_path=relative,
                storage_path=storage_path,
                role=ref.role,
                media_type=media_type,
                metadata=ref.metadata,
                captured_at=utc_now(),
            )
            record = self._write_or_read_manifest(proposed)
            return record, size
        except OSError as exc:
            raise IntegrityError(
                f"failed to capture artifact {relative}: {exc}"
            ) from exc
        finally:
            os.close(source_fd)
            if temp_fd is not None:
                os.close(temp_fd)
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass

    @staticmethod
    def _open_workspace_file(workspace_fd: int, relative: str) -> int:
        """Open a relative file without following any path-component symlink."""

        parts = PurePosixPath(relative).parts
        if not parts or any(part in {"", ".", ".."} for part in parts):
            raise OSError(errno.EINVAL, "unsafe relative artifact path", relative)
        current_fd = os.dup(workspace_fd)
        try:
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_flags |= getattr(os, "O_CLOEXEC", 0) | getattr(
                os, "O_NOFOLLOW", 0
            )
            for part in parts[:-1]:
                next_fd = os.open(part, directory_flags, dir_fd=current_fd)
                os.close(current_fd)
                current_fd = next_fd
            file_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
            file_flags |= getattr(os, "O_NOFOLLOW", 0)
            return os.open(parts[-1], file_flags, dir_fd=current_fd)
        finally:
            os.close(current_fd)

    @staticmethod
    def _hash_file(path: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(path, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise IntegrityError(f"catalog blob is not a regular file: {path}")
            os.fchmod(fd, 0o600)
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                digest.update(chunk)
        finally:
            os.close(fd)
        return digest.hexdigest(), size

    def _verify_blob(self, path: Path, digest: str, size: int) -> None:
        try:
            actual_digest, actual_size = self._hash_file(path)
        except OSError as exc:
            raise IntegrityError(
                f"cannot verify existing catalog blob {path}: {exc}"
            ) from exc
        if actual_digest != digest or actual_size != size:
            raise IntegrityError(f"existing content-addressed blob is corrupt: {path}")

    def _write_or_read_manifest(self, proposed: ArtifactRecord) -> ArtifactRecord:
        manifest_path = self.record_root / f"{proposed.artifact_id}.json"
        encoded = canonical_bytes(proposed.to_dict()) + b"\n"
        temp_fd, temp_name = tempfile.mkstemp(prefix=".manifest-", dir=self.record_root)
        temp_path = Path(temp_name)
        try:
            os.fchmod(temp_fd, 0o600)
            offset = 0
            while offset < len(encoded):
                written = os.write(temp_fd, encoded[offset:])
                if written <= 0:
                    raise OSError("short write while storing artifact manifest")
                offset += written
            os.fsync(temp_fd)
            os.close(temp_fd)
            temp_fd = -1
            try:
                os.link(temp_path, manifest_path)
                self._fsync_directory(self.record_root)
                return proposed
            except FileExistsError:
                existing = self.get(proposed.artifact_id)
                comparison = proposed.to_dict()
                comparison["captured_at"] = existing.captured_at
                if existing.to_dict() != comparison:
                    raise IntegrityError(
                        f"artifact manifest ID collision: {proposed.artifact_id}"
                    ) from None
                return existing
        finally:
            if temp_fd >= 0:
                os.close(temp_fd)
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    def get(self, artifact_id: str) -> ArtifactRecord:
        try:
            artifact_id = validate_namespaced_id(artifact_id, "artifact")
        except ValueError as exc:
            raise IntegrityError(str(exc)) from exc
        path = self.record_root / f"{artifact_id}.json"
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise IntegrityError(
                f"cannot read artifact manifest {artifact_id}: {exc}"
            ) from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise IntegrityError(
                    f"artifact manifest is not a regular file: {artifact_id}"
                )
            os.fchmod(descriptor, 0o600)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            data = b"".join(chunks)
        finally:
            os.close(descriptor)
        if not data.endswith(b"\n") or data.count(b"\n") != 1:
            raise IntegrityError(
                f"artifact manifest is not one complete JSON record: {artifact_id}"
            )
        try:
            decoded = strict_json_loads(data[:-1].decode("utf-8"))
        except (UnicodeDecodeError, TypeError, ValueError) as exc:
            raise IntegrityError(
                f"artifact manifest is corrupt: {artifact_id}"
            ) from exc
        if not isinstance(decoded, dict) or canonical_bytes(decoded) + b"\n" != data:
            raise IntegrityError(f"artifact manifest is not canonical: {artifact_id}")
        record = ArtifactRecord.from_mapping(decoded)
        if record.artifact_id != artifact_id:
            raise IntegrityError(f"artifact manifest ID mismatch: {artifact_id}")
        self._verify_blob(self.root / record.storage_path, record.digest, record.size)
        return record

    def records_for_experiment(
        self, project_id: str, experiment_id: str
    ) -> list[ArtifactRecord]:
        """Return verified manifests captured for one experiment identity."""

        project_id = require_text(project_id, "project_id")
        experiment_id = require_text(experiment_id, "experiment_id")
        try:
            with os.scandir(self.record_root) as scanner:
                entries = sorted(
                    (
                        entry.name,
                        entry.stat(follow_symlinks=False),
                    )
                    for entry in scanner
                    if entry.name.endswith(".json")
                )
        except OSError as exc:
            raise IntegrityError("cannot enumerate artifact manifests") from exc
        records: list[ArtifactRecord] = []
        for name, info in entries:
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
                raise IntegrityError(f"artifact manifest path is unsafe: {name}")
            record = self.get(name.removesuffix(".json"))
            if (
                record.project_id == project_id
                and record.experiment_id == experiment_id
            ):
                records.append(record)
        return records

    def blob_path(self, record: ArtifactRecord | Mapping[str, Any]) -> Path:
        normalized = (
            record
            if isinstance(record, ArtifactRecord)
            else ArtifactRecord.from_mapping(record)
        )
        path = (self.root / normalized.storage_path).resolve(strict=True)
        try:
            path.relative_to(self.root)
        except ValueError as exc:
            raise IntegrityError("artifact storage path escapes catalog root") from exc
        self._verify_blob(path, normalized.digest, normalized.size)
        return path

    resolve = blob_path

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            fd = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
