"""Stable, visibly namespaced identifiers."""

from __future__ import annotations

import re
import secrets
from typing import Any

from ._canonical import canonical_bytes, require_text, sha256_hex

_NAMESPACE_RE = re.compile(r"^[a-z][a-z0-9]{0,31}$")
_ID_RE = re.compile(
    r"^(?P<namespace>[a-z][a-z0-9]{0,31})_(?P<body>[a-zA-Z0-9][a-zA-Z0-9._-]*)$"
)

_PREFIXES = {
    "event": "evt",
    "experiment": "exp",
    "project": "prj",
    "session": "ses",
    "baseline": "base",
    "stage": "stage",
    "artifact": "art",
    "finding": "find",
}


def namespace_prefix(namespace: str) -> str:
    namespace = require_text(namespace, "namespace").lower()
    prefix = _PREFIXES.get(namespace, namespace)
    if not _NAMESPACE_RE.fullmatch(prefix):
        raise ValueError(f"invalid identifier namespace: {namespace!r}")
    return prefix


def stable_id(namespace: str, *components: Any, length: int = 32) -> str:
    """Return a deterministic ID for a namespace and canonical components."""

    if not 16 <= length <= 64:
        raise ValueError("stable ID digest length must be between 16 and 64")
    normalized_namespace = require_text(namespace, "namespace").lower()
    prefix = namespace_prefix(normalized_namespace)
    digest = sha256_hex(canonical_bytes([normalized_namespace, *components]))
    return f"{prefix}_{digest[:length]}"


def new_id(namespace: str) -> str:
    """Return a collision-resistant new ID with a stable namespace prefix."""

    return f"{namespace_prefix(namespace)}_{secrets.token_hex(16)}"


def new_experiment_id(
    project_id: str,
    candidate_digest: str,
    *,
    parent_id: str | None = None,
    compatibility_digest: str | None = None,
    generation_id: str | None = None,
    evaluation_scope_id: str | None = None,
    attempt: int = 1,
) -> str:
    """Derive a stable ID for one candidate attempt in one study generation.

    The two-argument form represents a root experiment.  Supplying
    ``parent_id`` aligns ID identity with :meth:`ProjectionStore.candidate_exists`.
    Retry attempts deliberately receive distinct deterministic IDs.  A missing
    ``generation_id`` uses the original component sequence byte-for-byte so
    legacy experiment IDs remain stable; a present generation is an orthogonal
    identity axis for versioned studies.  A present evaluation scope adds the
    final v2 identity axis, while a null scope retains every prior component
    sequence exactly.
    """

    project_id = require_text(project_id, "project_id")
    candidate_digest = require_text(candidate_digest, "candidate_digest")
    if parent_id is not None:
        parent_id = require_text(parent_id, "parent_id")
    if compatibility_digest is not None:
        compatibility_digest = require_text(
            compatibility_digest, "compatibility_digest"
        )
    if generation_id is not None:
        generation_id = require_text(generation_id, "generation_id")
    if evaluation_scope_id is not None:
        evaluation_scope_id = require_text(
            evaluation_scope_id,
            "evaluation_scope_id",
        )
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt must be a positive integer")
    if evaluation_scope_id is not None:
        if generation_id is None or compatibility_digest is None:
            raise ValueError(
                "evaluation_scope_id requires generation_id and compatibility_digest"
            )
        return stable_id(
            "experiment",
            project_id,
            generation_id,
            compatibility_digest,
            parent_id,
            candidate_digest,
            evaluation_scope_id,
            attempt,
        )
    if generation_id is not None:
        if compatibility_digest is None:
            return stable_id(
                "experiment",
                project_id,
                generation_id,
                parent_id,
                candidate_digest,
                attempt,
            )
        return stable_id(
            "experiment",
            project_id,
            generation_id,
            compatibility_digest,
            parent_id,
            candidate_digest,
            attempt,
        )
    if compatibility_digest is None:
        return stable_id(
            "experiment", project_id, parent_id, candidate_digest, attempt
        )
    return stable_id(
        "experiment",
        project_id,
        compatibility_digest,
        parent_id,
        candidate_digest,
        attempt,
    )


def validate_namespaced_id(value: str, namespace: str | None = None) -> str:
    value = require_text(value, "id")
    match = _ID_RE.fullmatch(value)
    if match is None:
        raise ValueError(f"invalid namespaced ID: {value!r}")
    if namespace is not None and match.group("namespace") != namespace_prefix(
        namespace
    ):
        raise ValueError(f"expected {namespace_prefix(namespace)!r} ID, got {value!r}")
    return value
