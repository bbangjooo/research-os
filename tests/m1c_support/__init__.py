"""Generic, case-ID-independent support for the frozen M1-C oracle."""

from .oracle import (
    DocumentResolver,
    DuplicateKeyError,
    OperationRegistry,
    ProposalNegativeInterpreter,
    apply_patch,
    sha256_bytes,
    sorted_compact_digest,
    strict_load_json,
    strict_load_json_lines,
)

__all__ = [
    "DocumentResolver",
    "DuplicateKeyError",
    "OperationRegistry",
    "ProposalNegativeInterpreter",
    "apply_patch",
    "sha256_bytes",
    "sorted_compact_digest",
    "strict_load_json",
    "strict_load_json_lines",
]
