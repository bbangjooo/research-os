"""Portable references to adapter-produced and OS-captured artifacts."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from .common import JSONObject, decode_json_object, require_fields

_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


def _artifact_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError("artifact path must be a non-empty string")
    if "\x00" in value:
        raise ValueError("artifact path contains a NUL byte")
    windows = PureWindowsPath(value)
    normalized_text = value.replace("\\", "/")
    path = PurePosixPath(normalized_text)
    if path.is_absolute() or windows.is_absolute() or windows.drive:
        raise ValueError("artifact path must be relative")
    if any(part == ".." for part in path.parts):
        raise ValueError("artifact path cannot contain '..'")
    clean_parts = tuple(part for part in path.parts if part not in ("", "."))
    if not clean_parts:
        raise ValueError("artifact path must name a file or directory")
    return PurePosixPath(*clean_parts).as_posix()


def _nonempty(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise ValueError(f"{name} contains a NUL byte")
    return value.strip()


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """An artifact path plus declared handling policy and optional capture data.

    ``path`` is always relative to the disposable workspace.  Adapters declare
    the first four fields; the OS fills ``sha256`` and ``size_bytes`` only after
    it has safely captured the artifact.
    """

    path: str
    media_type: str = "application/octet-stream"
    retention: str = "run"
    sensitivity: str = "internal"
    sha256: str | None = None
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _artifact_path(self.path))
        object.__setattr__(self, "media_type", _nonempty(self.media_type, "media_type"))
        object.__setattr__(self, "retention", _nonempty(self.retention, "retention"))
        object.__setattr__(
            self, "sensitivity", _nonempty(self.sensitivity, "sensitivity")
        )
        if self.sha256 is not None:
            if not isinstance(self.sha256, str) or not _SHA256_RE.fullmatch(
                self.sha256
            ):
                raise ValueError("sha256 must be a 64-character hexadecimal digest")
            object.__setattr__(self, "sha256", self.sha256.lower())
        if self.size_bytes is not None:
            if isinstance(self.size_bytes, bool) or not isinstance(
                self.size_bytes, int
            ):
                raise TypeError("size_bytes must be an integer")
            if self.size_bytes < 0:
                raise ValueError("size_bytes cannot be negative")
        if (self.sha256 is None) != (self.size_bytes is None):
            raise ValueError(
                "sha256 and size_bytes must either both be set or both be absent"
            )

    @property
    def relative_path(self) -> Path:
        return Path(self.path)

    @property
    def captured(self) -> bool:
        return self.sha256 is not None

    def with_capture(self, *, sha256: str, size_bytes: int) -> "ArtifactRef":
        return replace(self, sha256=sha256, size_bytes=size_bytes)

    def to_dict(self) -> JSONObject:
        result: JSONObject = {
            "path": self.path,
            "media_type": self.media_type,
            "retention": self.retention,
            "sensitivity": self.sensitivity,
        }
        if self.sha256 is not None:
            result["sha256"] = self.sha256
            result["size_bytes"] = self.size_bytes
        return result

    @classmethod
    def from_dict(cls, data: Any) -> "ArtifactRef":
        if not isinstance(data, dict):
            from collections.abc import Mapping

            if not isinstance(data, Mapping):
                raise TypeError("artifact reference must be a JSON object")
        require_fields(data, "path", "media_type", "retention", "sensitivity")
        return cls(
            path=data["path"],
            media_type=data["media_type"],
            retention=data["retention"],
            sensitivity=data["sensitivity"],
            sha256=data.get("sha256"),
            size_bytes=data.get("size_bytes"),
        )

    from_mapping = from_dict

    @classmethod
    def from_json(cls, data: str | bytes | bytearray) -> "ArtifactRef":
        return cls.from_dict(decode_json_object(data))


DESIGN_PROVENANCE: dict[str, tuple[str, ...]] = {
    "ArtifactRef": ("Typed provenance", "Fixed experiment budget"),
}
