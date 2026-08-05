"""Small canonical JSON helpers shared by the storage implementation.

This module intentionally does not import :mod:`research_os.contracts`.  The
event store is the lowest durable layer in the package and must remain usable
while higher-level contracts evolve.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any, NoReturn

JSONScalar = None | bool | int | float | str
JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]

_RFC3339_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[Tt]"
    r"(?P<time>\d{2}:\d{2}:\d{2})(?:\.\d+)?"
    r"(?P<zone>[Zz]|[+-]\d{2}:\d{2})$"
)


def _bad_constant(value: str) -> NoReturn:
    raise ValueError(f"non-finite JSON number is not permitted: {value}")


def json_value(value: Any, *, path: str = "$") -> JSONValue:
    """Return a detached, strictly JSON-compatible representation of *value*.

    Mapping keys must already be strings, floats must be finite, and arbitrary
    iterables are deliberately not accepted.  Those restrictions prevent two
    callers from hashing subtly different interpretations of the same object.
    """

    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{path}: non-finite JSON number is not permitted")
        return value
    if isinstance(value, Mapping):
        result: dict[str, JSONValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"{path}: JSON object key must be a string")
            result[key] = json_value(item, path=f"{path}.{key}")
        return result
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        return [
            json_value(item, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    raise TypeError(f"{path}: unsupported JSON value {type(value).__name__}")


def canonical_json(value: Any) -> str:
    """Encode *value* using the one representation accepted by the event log."""

    return json.dumps(
        json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_bytes(value: Any) -> bytes:
    return canonical_json(value).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def strict_json_loads(text: str) -> JSONValue:
    """Decode JSON while rejecting duplicate object keys and non-finite values."""

    def object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key!r}")
            result[key] = value
        return result

    decoded = json.loads(
        text,
        object_pairs_hook=object_pairs,
        parse_constant=_bad_constant,
    )
    return json_value(decoded)


def utc_now() -> str:
    """Return a UTC timestamp with a stable RFC 3339 spelling."""

    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z")
    )


def validate_timestamp(value: Any, *, field: str = "occurred_at") -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty RFC 3339 string")
    if _RFC3339_RE.fullmatch(value) is None:
        raise ValueError(f"{field} is not a valid RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(
            value.replace("z", "+00:00").replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError(f"{field} is not a valid RFC 3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must include a timezone")
    return value


def require_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()
