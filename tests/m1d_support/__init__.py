"""Case-independent support for the frozen M1-D executable oracle."""

from .oracle import (
    DuplicateKeyError,
    M1DOracle,
    OperationRegistry,
    apply_json_patch,
    canonical_event_digest,
    json_canonical_equal,
    recursive_key_values,
    sha256_bytes,
    sorted_compact_digest,
    strict_load_json,
)

__all__ = [
    "DuplicateKeyError",
    "M1DOracle",
    "OperationRegistry",
    "apply_json_patch",
    "canonical_event_digest",
    "json_canonical_equal",
    "recursive_key_values",
    "sha256_bytes",
    "sorted_compact_digest",
    "strict_load_json",
]
