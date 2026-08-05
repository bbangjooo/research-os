"""Canonical, append-only, hash-chained JSONL event storage."""

from __future__ import annotations

import fcntl
import os
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from research_os.errors import IntegrityError

from ._canonical import (
    JSONValue,
    canonical_bytes,
    json_value,
    require_text,
    sha256_hex,
    strict_json_loads,
    utc_now,
    validate_timestamp,
)
from .ids import new_id

EVENT_VERSION = 1
_HASH_LENGTH = 64
_UNSAFE_WRITE_BITS = stat.S_IWGRP | stat.S_IWOTH


@dataclass(frozen=True, slots=True)
class Event(Mapping[str, Any]):
    """The fixed event envelope; ``payload`` remains domain-neutral."""

    version: int
    sequence: int
    project_id: str
    event_id: str
    event_type: str
    occurred_at: str
    payload: dict[str, JSONValue]
    prev_hash: str | None
    hash: str

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "version",
        "sequence",
        "project_id",
        "event_id",
        "event_type",
        "occurred_at",
        "payload",
        "prev_hash",
        "hash",
    )

    @property
    def type(self) -> str:
        return self.event_type

    @property
    def timestamp(self) -> str:
        return self.occurred_at

    @property
    def seq(self) -> int:
        return self.sequence

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "event_type": self.event_type,
            "occurred_at": self.occurred_at,
            "payload": json_value(self.payload),
            "prev_hash": self.prev_hash,
            "project_id": self.project_id,
            "sequence": self.sequence,
            "version": self.version,
        }

    def to_dict(self) -> dict[str, Any]:
        result = self.unsigned_dict()
        result["hash"] = self.hash
        return result

    def __getitem__(self, key: str) -> Any:
        aliases = {"type": "event_type", "timestamp": "occurred_at", "seq": "sequence"}
        key = aliases.get(key, key)
        if key not in self._FIELDS:
            raise KeyError(key)
        if key == "payload":
            return json_value(self.payload)
        return getattr(self, key)

    def __iter__(self) -> Iterator[str]:
        return iter(self._FIELDS)

    def __len__(self) -> int:
        return len(self._FIELDS)

    @classmethod
    def from_mapping(
        cls, raw: Mapping[str, Any], *, canonical: bool = False
    ) -> "Event":
        if not isinstance(raw, Mapping):
            raise IntegrityError("event must be a JSON object")
        keys = set(raw)
        required = set(cls._FIELDS)
        if keys != required:
            missing = sorted(required - keys)
            extra = sorted(keys - required)
            raise IntegrityError(
                f"invalid event envelope keys (missing={missing}, extra={extra})"
            )
        try:
            version = raw["version"]
            sequence = raw["sequence"]
            project_id = require_text(raw["project_id"], "project_id")
            event_id = require_text(raw["event_id"], "event_id")
            event_type = require_text(raw["event_type"], "event_type")
            occurred_at = validate_timestamp(raw["occurred_at"])
            payload = json_value(raw["payload"], path="$.payload")
            prev_hash = raw["prev_hash"]
            digest = raw["hash"]
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrityError(f"invalid event envelope: {exc}") from exc
        if version != EVENT_VERSION or isinstance(version, bool):
            raise IntegrityError(f"unsupported event version: {version!r}")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise IntegrityError("event sequence must be a positive integer")
        if not isinstance(payload, dict):
            raise IntegrityError("event payload must be a JSON object")
        if prev_hash is not None and (
            not isinstance(prev_hash, str)
            or len(prev_hash) != _HASH_LENGTH
            or any(ch not in "0123456789abcdef" for ch in prev_hash)
        ):
            raise IntegrityError(
                "event prev_hash must be null or a lowercase SHA-256 digest"
            )
        if (
            not isinstance(digest, str)
            or len(digest) != _HASH_LENGTH
            or any(ch not in "0123456789abcdef" for ch in digest)
        ):
            raise IntegrityError("event hash must be a lowercase SHA-256 digest")
        event = cls(
            version=version,
            sequence=sequence,
            project_id=project_id,
            event_id=event_id,
            event_type=event_type,
            occurred_at=occurred_at,
            payload=payload,
            prev_hash=prev_hash,
            hash=digest,
        )
        calculated = sha256_hex(canonical_bytes(event.unsigned_dict()))
        if calculated != digest:
            raise IntegrityError(
                f"event {sequence} hash mismatch: expected {calculated}, found {digest}"
            )
        return event


def _event_from_line(line: bytes, line_number: int) -> Event:
    try:
        text = line.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntegrityError(
            f"event log line {line_number} is not valid UTF-8"
        ) from exc
    try:
        raw = strict_json_loads(text)
    except (TypeError, ValueError) as exc:
        raise IntegrityError(
            f"invalid JSON on event log line {line_number}: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise IntegrityError(f"event log line {line_number} is not a JSON object")
    event = Event.from_mapping(raw)
    if canonical_bytes(event.to_dict()) != line:
        raise IntegrityError(f"event log line {line_number} is not canonical JSON")
    return event


def verify_events(events: list[Event], *, project_id: str | None = None) -> None:
    previous: Event | None = None
    seen_ids: set[str] = set()
    for supplied in events:
        # Event is frozen, but its generic payload is a detached mutable dict.
        # Reconstructing catches post-construction payload mutation as well as
        # hand-built Event instances with an invalid digest.
        event = Event.from_mapping(supplied.to_dict())
        expected_sequence = 1 if previous is None else previous.sequence + 1
        expected_hash = None if previous is None else previous.hash
        if event.sequence != expected_sequence:
            raise IntegrityError(
                f"event sequence discontinuity: expected {expected_sequence}, found {event.sequence}"
            )
        if event.prev_hash != expected_hash:
            raise IntegrityError(
                f"event {event.sequence} prev_hash does not match the preceding event"
            )
        if project_id is not None and event.project_id != project_id:
            raise IntegrityError(
                f"event {event.sequence} belongs to {event.project_id!r}, expected {project_id!r}"
            )
        if event.event_id in seen_ids:
            raise IntegrityError(
                f"duplicate event ID at sequence {event.sequence}: {event.event_id}"
            )
        seen_ids.add(event.event_id)
        previous = event


class EventLog:
    """A project-bound append-only JSONL log.

    Writers take an exclusive ``fcntl`` lock, re-verify the complete stream,
    append exactly one canonical line, and ``fsync`` it before releasing the
    lock.  Readers take a shared lock and reject partial tails, non-canonical
    JSON, sequence gaps, project mixing, duplicate IDs, and hash-chain damage.
    """

    def __init__(self, path: str | os.PathLike[str], project_id: str):
        self.path = Path(os.path.abspath(os.fspath(Path(path).expanduser())))
        self.project_id = require_text(project_id, "project_id")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise IntegrityError(f"event log must not be a symbolic link: {self.path}")

    def _read_bytes_fd(self, fd: int) -> bytes:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise IntegrityError(f"event log is not a regular file: {self.path}")
        if info.st_mode & _UNSAFE_WRITE_BITS:
            raise IntegrityError(
                "event log must not be group- or world-writable: "
                f"{self.path} (mode {stat.S_IMODE(info.st_mode):04o})"
            )
        os.lseek(fd, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)

    def _events_from_bytes(self, data: bytes) -> list[Event]:
        if not data:
            return []
        if not data.endswith(b"\n"):
            raise IntegrityError(
                "event log has an unterminated or partially written final line"
            )
        lines = data[:-1].split(b"\n")
        if any(not line for line in lines):
            raise IntegrityError("event log contains an empty line")
        events = [_event_from_line(line, index) for index, line in enumerate(lines, 1)]
        verify_events(events, project_id=self.project_id)
        return events

    def _read_fd(self, fd: int) -> list[Event]:
        return self._events_from_bytes(self._read_bytes_fd(fd))

    def _recover_tail_fd(self, fd: int) -> tuple[int, list[Event]]:
        """Discard only an uncommitted final fragment from a locked log.

        A newline is the durable record commit marker.  Every complete line
        before a fragment must pass canonical JSON, hash-chain, project, and
        event-ID verification before truncation is allowed.  Consequently a
        corrupt committed line is never reclassified as crash residue.
        """

        data = self._read_bytes_fd(fd)
        if not data or data.endswith(b"\n"):
            return 0, self._events_from_bytes(data)
        prefix_length = data.rfind(b"\n") + 1
        prefix = data[:prefix_length]
        events = self._events_from_bytes(prefix)
        removed = len(data) - prefix_length
        try:
            os.ftruncate(fd, prefix_length)
            os.fsync(fd)
        except OSError as exc:
            raise IntegrityError(
                "could not durably remove an incomplete event-log tail"
            ) from exc
        os.lseek(fd, 0, os.SEEK_END)
        return removed, events

    def read(self) -> list[Event]:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags)
        except FileNotFoundError:
            return []
        except OSError as exc:
            raise IntegrityError(
                f"cannot safely open event log {self.path}: {exc}"
            ) from exc
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            return self._read_fd(fd)
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    @contextmanager
    def locked_read(self) -> Iterator[list[Event]]:
        """Yield one verified snapshot while retaining a shared log lock.

        Projection rebuilds use this API to keep an append from changing the
        canonical stream between their read and SQLite commit.  Unlike
        :meth:`read`, this creates the empty log when necessary so even the
        empty-stream snapshot has an inode that an appender must lock.
        """

        existed = self.path.exists()
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise IntegrityError(
                f"cannot safely open event log {self.path}: {exc}"
            ) from exc
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            if not existed:
                self._fsync_parent()
            yield self._read_fd(fd)
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def __iter__(self) -> Iterator[Event]:
        return iter(self.read())

    def verify(self) -> bool:
        self.read()
        return True

    def head(self) -> Event | None:
        events = self.read()
        return events[-1] if events else None

    def recover_tail(self) -> int:
        """Durably remove one crash-left, non-newline final fragment.

        Returns the number of discarded bytes.  Missing and fully committed
        logs return zero after verification.  Recovery takes an exclusive lock
        and repairs writable-by-group/world mode before examining the file.
        """

        flags = os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags)
        except FileNotFoundError:
            return 0
        except OSError as exc:
            raise IntegrityError(
                f"cannot safely open event log {self.path}: {exc}"
            ) from exc
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.fchmod(fd, 0o600)
            removed, _ = self._recover_tail_fd(fd)
            return removed
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        *,
        event_id: str | None = None,
        occurred_at: str | None = None,
    ) -> Event:
        event_type = require_text(event_type, "event_type")
        if payload is None:
            clean_payload: dict[str, JSONValue] = {}
        else:
            converted = json_value(payload, path="$.payload")
            if not isinstance(converted, dict):
                raise TypeError("event payload must be a mapping")
            clean_payload = converted
        event_id = (
            new_id("event") if event_id is None else require_text(event_id, "event_id")
        )
        occurred_at = (
            utc_now() if occurred_at is None else validate_timestamp(occurred_at)
        )

        existed = self.path.exists()
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise IntegrityError(f"cannot open event log {self.path}: {exc}") from exc
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            os.fchmod(fd, 0o600)
            _, events = self._recover_tail_fd(fd)
            original_size = os.fstat(fd).st_size
            previous = events[-1] if events else None
            if any(existing.event_id == event_id for existing in events):
                raise IntegrityError(f"duplicate event ID: {event_id}")
            unsigned = {
                "event_id": event_id,
                "event_type": event_type,
                "occurred_at": occurred_at,
                "payload": clean_payload,
                "prev_hash": previous.hash if previous else None,
                "project_id": self.project_id,
                "sequence": previous.sequence + 1 if previous else 1,
                "version": EVENT_VERSION,
            }
            digest = sha256_hex(canonical_bytes(unsigned))
            event = Event.from_mapping({**unsigned, "hash": digest})
            encoded = canonical_bytes(event.to_dict()) + b"\n"
            try:
                offset = 0
                while offset < len(encoded):
                    written = os.write(fd, encoded[offset:])
                    if written <= 0:
                        raise OSError("short write while appending event")
                    offset += written
                os.fsync(fd)
                if not existed:
                    self._fsync_parent()
            except BaseException:
                # A short write or failed durability barrier must not poison
                # every subsequent read with a partial final JSON line.  The
                # exclusive lock remains held throughout rollback.
                rollback_error: BaseException | None = None
                try:
                    os.ftruncate(fd, original_size)
                    os.fsync(fd)
                except BaseException as exc:
                    rollback_error = exc
                if rollback_error is not None:
                    raise IntegrityError(
                        "event append failed and rollback durability could not be confirmed"
                    ) from rollback_error
                raise
            return event
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def _fsync_parent(self) -> None:
        try:
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)


# Compatibility spelling for callers that prefer the noun first.
JSONLEventLog = EventLog
