"""Deterministic JSON and digest primitives used by public contracts.

Canonical JSON policy version 1 is an RFC-8785-style interoperable subset.
Strings must be Unicode scalar values, Python integers must fit JavaScript's
exactly representable range, and floats are rendered with ECMAScript binary64
number formatting. Object keys are ordered by UTF-16 code units, as they are in
ECMAScript. These rules keep a digest stable across processes and languages.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, TypeAlias, cast

JSONScalar: TypeAlias = None | bool | int | float | str
JSONValue: TypeAlias = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
JSONObject: TypeAlias = dict[str, JSONValue]

# Changing an acceptance or encoding rule requires a new policy version.
CANONICAL_JSON_VERSION = 1
MAX_SAFE_JSON_INTEGER = (1 << 53) - 1

# Contract instances store this recursively immutable representation. Public
# wire/export helpers still return the ordinary dict/list JSONValue shape.
FrozenJSONValue: TypeAlias = (
    JSONScalar | tuple["FrozenJSONValue", ...] | Mapping[str, "FrozenJSONValue"]
)
FrozenJSONObject: TypeAlias = Mapping[str, FrozenJSONValue]


DESIGN_PROVENANCE: dict[str, tuple[str, ...]] = {
    "CANONICAL_JSON_VERSION": ("Typed provenance",),
    "canonical_json": ("Typed provenance",),
    "sha256_json": ("Typed provenance", "Immutable evaluation"),
    "sha256_file": ("Typed provenance", "Immutable evaluation"),
}


def _unicode_scalar_string(value: str, *, field_name: str = "string") -> str:
    """Reject unpaired UTF-16 surrogates, which cannot be encoded as UTF-8."""

    for character in value:
        if 0xD800 <= ord(character) <= 0xDFFF:
            raise ValueError(
                f"canonical JSON {field_name} contains an unpaired surrogate"
            )
    return value


def _portable_number(value: int | float) -> int | float:
    """Normalize one number under canonical JSON policy version 1.

    Python integers retain exact-integer semantics and therefore must fit the
    interoperable safe range. Floats are IEEE-754 binary64 values in both
    Python and JavaScript; their cross-runtime spelling is handled by the
    canonical encoder below.
    """

    if isinstance(value, int):
        if abs(value) > MAX_SAFE_JSON_INTEGER:
            raise ValueError(
                "canonical JSON integers must be within the JavaScript safe "
                f"range [-{MAX_SAFE_JSON_INTEGER}, {MAX_SAFE_JSON_INTEGER}]"
            )
        return value

    if not math.isfinite(value):
        raise ValueError("canonical JSON does not permit NaN or infinity")
    if value == 0.0:
        return 0
    return value


def _json_value(value: Any, *, _active: set[int] | None = None) -> JSONValue:
    """Convert supported contract values into an ordinary JSON value.

    Conversion is strict rather than relying on ``default=str``.  Accidentally
    hashing a Python representation would make provenance dependent on a local
    implementation detail.
    """

    if isinstance(value, Enum):
        return _json_value(value.value, _active=_active)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _portable_number(value)
    if isinstance(value, str):
        return _unicode_scalar_string(value)
    if isinstance(value, Path):
        return _unicode_scalar_string(value.as_posix(), field_name="path")

    if hasattr(value, "to_dict") and callable(value.to_dict):
        return _json_value(value.to_dict(), _active=_active)

    if is_dataclass(value) and not isinstance(value, type):
        return _json_value(
            {field.name: getattr(value, field.name) for field in fields(value)},
            _active=_active,
        )

    if _active is None:
        _active = set()
    object_id = id(value)
    if object_id in _active:
        raise ValueError("canonical JSON cannot encode cyclic values")

    if isinstance(value, Mapping):
        _active.add(object_id)
        try:
            converted: JSONObject = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise TypeError("canonical JSON object keys must be strings")
                _unicode_scalar_string(key, field_name="object key")
                converted[key] = _json_value(item, _active=_active)
            return converted
        finally:
            _active.remove(object_id)

    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray, memoryview)
    ):
        _active.add(object_id)
        try:
            return [_json_value(item, _active=_active) for item in value]
        finally:
            _active.remove(object_id)

    raise TypeError(f"value of type {type(value).__name__!r} is not JSON-compatible")


def normalize_json_value(value: Any) -> JSONValue:
    """Validate and defensively copy a JSON-compatible value."""

    return _json_value(value)


def normalize_json_object(value: Any, *, field_name: str = "value") -> JSONObject:
    """Validate and defensively copy a JSON object."""

    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a JSON object")
    normalized = _json_value(value)
    assert isinstance(normalized, dict)
    return normalized


def _freeze_normalized(value: JSONValue) -> FrozenJSONValue:
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_normalized(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_normalized(item) for item in value)
    return value


def freeze_json_value(value: Any) -> FrozenJSONValue:
    """Validate, detach, and recursively freeze a JSON-compatible value."""

    return _freeze_normalized(_json_value(value))


def freeze_json_object(value: Any, *, field_name: str = "value") -> FrozenJSONObject:
    """Validate, detach, and recursively freeze a JSON object."""

    normalized = normalize_json_object(value, field_name=field_name)
    return cast(FrozenJSONObject, _freeze_normalized(normalized))


def copy_json_value(value: Any) -> JSONValue:
    """Return a fresh ordinary dict/list tree from mutable or frozen JSON."""

    return _json_value(value)


def copy_json_object(value: Any, *, field_name: str = "value") -> JSONObject:
    """Return a fresh ordinary dictionary tree from mutable or frozen JSON."""

    return normalize_json_object(value, field_name=field_name)


def _utf16_sort_key(value: str) -> bytes:
    # Surrogates were rejected during normalization, so strict UTF-16 encoding
    # is equivalent to ECMAScript's code-unit lexicographic order.
    return value.encode("utf-16-be")


def _canonical_float(value: float) -> str:
    """Render a finite binary64 value with ECMAScript JSON number formatting.

    CPython and modern ECMAScript engines choose the same shortest round-trip
    significant digits but use different fixed/exponent thresholds. Reframing
    those digits gives the RFC-8785/ECMAScript spelling without a runtime
    dependency.
    """

    if not math.isfinite(value):
        raise ValueError("canonical JSON does not permit NaN or infinity")
    if value == 0.0:
        return "0"
    negative = value < 0
    rendered = repr(-value if negative else value).lower()
    mantissa, separator, exponent_text = rendered.partition("e")
    exponent = int(exponent_text) if separator else 0
    integer, point, fraction = mantissa.partition(".")
    digits = integer + (fraction if point else "")
    decimal_position = len(integer) + exponent

    leading = len(digits) - len(digits.lstrip("0"))
    digits = digits[leading:]
    decimal_position -= leading
    digits = digits.rstrip("0") or "0"

    if -6 < decimal_position <= 21:
        if decimal_position <= 0:
            body = "0." + ("0" * -decimal_position) + digits
        elif decimal_position >= len(digits):
            body = digits + ("0" * (decimal_position - len(digits)))
        else:
            body = digits[:decimal_position] + "." + digits[decimal_position:]
    else:
        scientific_exponent = decimal_position - 1
        coefficient = digits[0]
        if len(digits) > 1:
            coefficient += "." + digits[1:]
        exponent_sign = "+" if scientific_exponent >= 0 else ""
        body = f"{coefficient}e{exponent_sign}{scientific_exponent}"
    return "-" + body if negative else body


def _canonical_encode(value: JSONValue) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _canonical_float(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, list):
        return "[" + ",".join(_canonical_encode(item) for item in value) + "]"
    return "{" + ",".join(
        json.dumps(key, ensure_ascii=False, separators=(",", ":"))
        + ":"
        + _canonical_encode(value[key])
        for key in sorted(value, key=_utf16_sort_key)
    ) + "}"


def canonical_json(value: Any) -> str:
    """Return canonical JSON text under policy version 1."""

    return _canonical_encode(_json_value(value))


def canonical_json_bytes(value: Any) -> bytes:
    """Return :func:`canonical_json` encoded as UTF-8."""

    return canonical_json(value).encode("utf-8")


def sha256_bytes(data: bytes | bytearray | memoryview) -> str:
    """Return the lowercase SHA-256 hexadecimal digest of bytes."""

    return hashlib.sha256(bytes(data)).hexdigest()


def sha256_text(text: str) -> str:
    """Return the SHA-256 digest of UTF-8 text."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return sha256_bytes(text.encode("utf-8"))


def sha256_json(value: Any) -> str:
    """Return the SHA-256 digest of canonical JSON for ``value``."""

    return sha256_bytes(canonical_json_bytes(value))


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Securely stream one stable regular file into a SHA-256 digest.

    The path is inspected without following its final component, opened with
    ``O_NOFOLLOW`` where the platform provides it, and checked again through
    the descriptor and pathname after reading.  This makes a concurrent
    symlink swap, replacement, or in-place write a hard failure instead of
    silently producing ambiguous provenance.
    """

    if (
        isinstance(chunk_size, bool)
        or not isinstance(chunk_size, int)
        or chunk_size <= 0
    ):
        raise ValueError("chunk_size must be a positive integer")
    file_path = Path(path)
    try:
        before = file_path.lstat()
    except OSError as exc:
        raise OSError(f"cannot inspect file for hashing {file_path}: {exc}") from exc
    if stat.S_ISLNK(before.st_mode):
        raise OSError(f"refusing to hash symbolic link: {file_path}")
    if not stat.S_ISREG(before.st_mode):
        raise OSError(f"refusing to hash non-regular file: {file_path}")

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    digest = hashlib.sha256()
    try:
        descriptor = os.open(file_path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise OSError(f"refusing to hash non-regular file: {file_path}")
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise OSError(f"file was replaced while opening it: {file_path}")
        while chunk := os.read(descriptor, chunk_size):
            digest.update(chunk)
        after_descriptor = os.fstat(descriptor)
    except OSError as exc:
        raise OSError(f"cannot securely hash file {file_path}: {exc}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    try:
        after_path = file_path.lstat()
    except OSError as exc:
        raise OSError(
            f"file disappeared while it was being hashed {file_path}: {exc}"
        ) from exc
    stable_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    expected = tuple(getattr(opened, field) for field in stable_fields)
    if tuple(getattr(after_descriptor, field) for field in stable_fields) != expected:
        raise OSError(f"file changed while it was being hashed: {file_path}")
    if tuple(getattr(after_path, field) for field in stable_fields) != expected:
        raise OSError(f"file was replaced while it was being hashed: {file_path}")
    return digest.hexdigest()


def _reject_constant(token: str) -> None:
    raise ValueError(f"invalid non-finite JSON number: {token}")


def _parse_json_integer(token: str) -> int | float:
    """Preserve safe integers; interpret larger JSON numbers as binary64.

    JavaScript has one numeric type and may emit an integral-looking decimal
    for a large binary64 value. Converting those wire tokens to float keeps the
    same semantics while direct Python integers outside the safe range remain
    rejected by ``canonical_json``.
    """

    exact = int(token)
    if abs(exact) <= MAX_SAFE_JSON_INTEGER:
        return exact
    converted = float(token)
    if not math.isfinite(converted):
        raise ValueError("JSON number exceeds the finite binary64 range")
    return converted


def _unique_object(pairs: list[tuple[str, JSONValue]]) -> JSONObject:
    result: JSONObject = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def decode_json_object(data: str | bytes | bytearray) -> JSONObject:
    """Decode one JSON object, rejecting duplicates and non-finite numbers."""

    value = json.loads(
        data,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
        parse_int=_parse_json_integer,
    )
    return normalize_json_object(value, field_name="JSON document")


def require_fields(data: Mapping[str, Any], *names: str) -> None:
    """Raise ``ValueError`` when any required wire field is absent.

    Unknown fields are intentionally not rejected; protocol readers can safely
    consume newer producers while still failing closed on their own essentials.
    """

    missing = [name for name in names if name not in data]
    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(f"missing required field(s): {joined}")
