"""Pure contracts and replay for the opt-in advisory discovery lane.

Discovery records observations, anomalies, assumption conflicts, ideas, and
rival frame drafts.  Every entry is advisory: it grants no authority, is never
read by the scientific reducer or ProgramLog, and cannot be an input to
registration, validation, promotion, sealing, or a successor generation.  Its
only downstream consumers are human/LLM reading and the evidence an outer
frame-transition inquiry chooses to quote.

The lane exists because two of the four exhaustion signal kinds declared in
:mod:`research_os.frame_transition` -- ``unresolved_anomaly`` and
``assumption_conflict`` -- live only in diagnosis interpretation, which is
discarded at session end.  Without a journal they are unreachable, leaving the
two mechanically derived kinds as the only usable evidence for a gate that
requires two distinct kinds.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from research_os.contracts import sha256_json
from research_os.errors import ScientificStateError
from research_os.frame_transition import rival_fingerprint
from research_os.kernel._canonical import json_value, validate_timestamp
from research_os.kernel.events import Event
from research_os.kernel.ids import stable_id
from research_os.science.state import reduce_scientific_state

DISCOVERY_NOTE_EVENT_TYPE = "research.discovery_note.v1"
DISCOVERY_EVENT_TYPES = frozenset({DISCOVERY_NOTE_EVENT_TYPE})
DISCOVERY_SCHEMA_VERSION = 1

NOTE_KINDS = frozenset(
    {"observation", "anomaly", "assumption_conflict", "idea", "rival_draft"}
)

#: Kinds whose notes may be quoted as an advisory exhaustion signal.  These
#: require non-empty ``evidence_refs`` so that free text alone cannot become
#: signal material.
SIGNAL_BEARING_KINDS = frozenset({"observation", "anomaly", "assumption_conflict"})

#: Mapping from a note kind to the exhaustion signal kind it can corroborate.
SIGNAL_KIND_BY_NOTE_KIND = {
    "anomaly": "unresolved_anomaly",
    "assumption_conflict": "assumption_conflict",
}

_DIGEST_LENGTH = 64

_NOTE_INPUT_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "body",
        "refs",
        "analogy_query_digest",
        "authorized_action",
    }
)
_NOTE_PAYLOAD_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "body",
        "refs",
        "analogy_query_digest",
        "content_digest",
        "note_id",
        "note_sequence",
        "recorded_at",
        "receipt_digest",
    }
)

# The rival_draft body is field-identical to frame_transition's rival contract
# on purpose: a draft must be quotable as an inquiry rival without conversion.
_RIVAL_DRAFT_KEYS = frozenset(
    {
        "rival_id",
        "label",
        "assumptions",
        "mechanism",
        "predictions",
        "falsifiers",
        "uncertainty",
    }
)
_SIGNAL_BODY_KEYS = frozenset({"summary", "evidence_refs", "open_question"})
_IDEA_BODY_KEYS = frozenset({"summary", "motivating_refs"})

_BODY_KEYS_BY_KIND: dict[str, frozenset[str]] = {
    "observation": _SIGNAL_BODY_KEYS,
    "anomaly": _SIGNAL_BODY_KEYS,
    "assumption_conflict": _SIGNAL_BODY_KEYS,
    "idea": _IDEA_BODY_KEYS,
    "rival_draft": _RIVAL_DRAFT_KEYS,
}


def _error(code: str, message: str, **details: object) -> ScientificStateError:
    return ScientificStateError(code, message, details=details)


def _object(
    value: Any,
    keys: frozenset[str],
    *,
    path: str,
    code: str = "DISCOVERY_INVALID",
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise _error(code, f"{path} must be an object", path=path)
    observed = set(value)
    if observed != keys:
        raise _error(
            code,
            f"{path} must have exact fields",
            path=path,
            missing_fields=sorted(keys - observed),
            unknown_fields=sorted(observed - keys),
        )
    try:
        converted = json_value(value, path=path)
    except (TypeError, ValueError) as exc:
        raise _error(code, str(exc), path=path) from exc
    if not isinstance(converted, dict):  # pragma: no cover - guarded above
        raise _error(code, f"{path} must be an object", path=path)
    return converted


def _text(value: Any, *, path: str, code: str = "DISCOVERY_INVALID") -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise _error(code, f"{path} must be trimmed non-empty text", path=path)
    return value


def _digest(value: Any, *, path: str, code: str = "DISCOVERY_INVALID") -> str:
    text = _text(value, path=path, code=code)
    if len(text) != _DIGEST_LENGTH or any(ch not in "0123456789abcdef" for ch in text):
        raise _error(code, f"{path} must be a lowercase SHA-256 digest", path=path)
    return text


def _array(value: Any, *, path: str, minimum: int = 0) -> list[Any]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise _error("DISCOVERY_INVALID", f"{path} must be an array", path=path)
    result = list(value)
    if len(result) < minimum:
        raise _error(
            "DISCOVERY_EVIDENCE_INSUFFICIENT",
            f"{path} must contain at least {minimum} items",
            path=path,
        )
    return result


def _text_array(value: Any, *, path: str, minimum: int = 0) -> list[str]:
    return [
        _text(item, path=f"{path}[{index}]")
        for index, item in enumerate(_array(value, path=path, minimum=minimum))
    ]


def _unique_text_array(value: Any, *, path: str, minimum: int = 0) -> list[str]:
    items = _text_array(value, path=path, minimum=minimum)
    if len(set(items)) != len(items):
        raise _error("DISCOVERY_INVALID", f"{path} must not repeat an entry", path=path)
    return items


def _timestamp(value: Any, *, path: str) -> str:
    try:
        return validate_timestamp(value, field=path)
    except (TypeError, ValueError) as exc:
        raise _error("DISCOVERY_INVALID", str(exc), path=path) from exc


def _schema(raw: Mapping[str, Any]) -> None:
    version = raw.get("schema_version")
    if isinstance(version, bool) or version != DISCOVERY_SCHEMA_VERSION:
        raise _error(
            "DISCOVERY_INVALID",
            "unsupported discovery schema version",
            path="$.schema_version",
        )


def _literal_null_authority(raw: Mapping[str, Any]) -> None:
    if raw.get("authorized_action") is not None:
        raise _error(
            "DISCOVERY_AUTHORITY_INVALID",
            "authorized_action must be literal null",
            path="$.authorized_action",
        )


def _validate_signal_body(body: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(body)
    _text(result["summary"], path="$.body.summary")
    _text(result["open_question"], path="$.body.open_question")
    # A note that cites nothing is an opinion.  Requiring at least one canonical
    # reference is what keeps a self-authored note from becoming free-floating
    # exhaustion evidence later.
    _unique_text_array(result["evidence_refs"], path="$.body.evidence_refs", minimum=1)
    return result


def _validate_idea_body(body: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(body)
    _text(result["summary"], path="$.body.summary")
    _unique_text_array(result["motivating_refs"], path="$.body.motivating_refs")
    return result


def _validate_rival_draft_body(body: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(body)
    _text(result["rival_id"], path="$.body.rival_id")
    _text(result["label"], path="$.body.label")
    _text(result["mechanism"], path="$.body.mechanism")
    _text(result["uncertainty"], path="$.body.uncertainty")
    _text_array(result["assumptions"], path="$.body.assumptions", minimum=1)
    _text_array(result["predictions"], path="$.body.predictions", minimum=1)
    # A frame proposal without a falsifier cannot lose, so it cannot be
    # compared against a rival either.  This is the one substantive screen the
    # advisory lane applies.
    _text_array(result["falsifiers"], path="$.body.falsifiers", minimum=1)
    return result


_BODY_VALIDATORS = {
    "observation": _validate_signal_body,
    "anomaly": _validate_signal_body,
    "assumption_conflict": _validate_signal_body,
    "idea": _validate_idea_body,
    "rival_draft": _validate_rival_draft_body,
}


def draft_fingerprint(body: Mapping[str, Any]) -> str:
    """Return the frame-transition rival fingerprint for a rival_draft body."""

    return rival_fingerprint(
        [str(item) for item in body["assumptions"]],
        str(body["mechanism"]),
    )


def screen_note(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the admissibility screen and return the validated note core.

    This is a screen, not a gate.  It checks that a note is well formed,
    falsifiable where that is meaningful, and grounded in at least one
    reference.  It never judges whether the content is good; that judgement
    belongs to the inner loop and the frame-transition path.
    """

    data = _object(raw, _NOTE_INPUT_KEYS, path="$")
    _schema(data)
    _literal_null_authority(data)

    kind = _text(data["kind"], path="$.kind")
    if kind not in NOTE_KINDS:
        raise _error("DISCOVERY_INVALID", "unknown discovery note kind", path="$.kind")

    body = _object(data["body"], _BODY_KEYS_BY_KIND[kind], path="$.body")
    body = _BODY_VALIDATORS[kind](body)

    # rival_draft is the only kind that can be promoted into an inquiry rival,
    # so it must carry at least one canonical reference of its own.
    refs = _unique_text_array(
        data["refs"],
        path="$.refs",
        minimum=1 if kind == "rival_draft" else 0,
    )

    analogy_query_digest = data["analogy_query_digest"]
    if analogy_query_digest is not None:
        analogy_query_digest = _digest(
            analogy_query_digest,
            path="$.analogy_query_digest",
        )

    core = {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "kind": kind,
        "body": body,
        "refs": refs,
        "analogy_query_digest": analogy_query_digest,
    }
    core["content_digest"] = sha256_json({"kind": kind, "body": body, "refs": refs})
    return core


@dataclass(frozen=True, slots=True)
class DiscoveryPlan:
    event_type: str
    payload: Mapping[str, Any]
    note_id: str
    receipt_digest: str
    append_required: bool = True


@dataclass(frozen=True, slots=True)
class DiscoveryState:
    project_id: str
    notes: tuple[Mapping[str, Any], ...]

    @property
    def note_count(self) -> int:
        return len(self.notes)

    @property
    def rival_fingerprints(self) -> frozenset[str]:
        return frozenset(
            draft_fingerprint(note["body"])
            for note in self.notes
            if note.get("kind") == "rival_draft"
        )

    def notes_of_kind(self, kind: str) -> tuple[Mapping[str, Any], ...]:
        return tuple(note for note in self.notes if note.get("kind") == kind)

    def to_dict(self, *, kind: str | None = None, limit: int | None = None) -> dict[str, Any]:
        notes = self.notes if kind is None else self.notes_of_kind(kind)
        selected = notes if limit is None else notes[-limit:]
        return {
            "schema_version": DISCOVERY_SCHEMA_VERSION,
            "project_id": self.project_id,
            "lane": "advisory",
            "note_count": self.note_count,
            "returned_count": len(selected),
            "distinct_rival_fingerprints": len(self.rival_fingerprints),
            "notes": [json_value(item) for item in selected],
            "authorized_action": None,
        }


def _event_parts(
    event: Event | Mapping[str, Any], *, project_id: str
) -> tuple[str, Mapping[str, Any], str | None]:
    if isinstance(event, Event):
        if event.project_id != project_id:
            raise _error(
                "DISCOVERY_PROJECT_MISMATCH",
                "event belongs to another project",
                expected_project_id=project_id,
                observed_project_id=event.project_id,
            )
        return event.event_type, event.payload, event.occurred_at
    observed_project = event.get("project_id")
    if observed_project is not None and observed_project != project_id:
        raise _error(
            "DISCOVERY_PROJECT_MISMATCH",
            "event belongs to another project",
            expected_project_id=project_id,
            observed_project_id=observed_project,
        )
    payload = event.get("payload")
    if not isinstance(payload, Mapping):
        raise _error("DISCOVERY_INVALID", "event payload must be an object")
    return str(event.get("event_type")), payload, event.get("occurred_at")


def _validate_recorded_note(payload: Mapping[str, Any]) -> dict[str, Any]:
    note = _object(payload, _NOTE_PAYLOAD_KEYS, path="$.payload")
    core = screen_note(
        {
            "schema_version": note["schema_version"],
            "kind": note["kind"],
            "body": note["body"],
            "refs": note["refs"],
            "analogy_query_digest": note["analogy_query_digest"],
            "authorized_action": None,
        }
    )
    if core["content_digest"] != note["content_digest"]:
        raise _error(
            "DISCOVERY_DIGEST_MISMATCH",
            "recorded discovery note content digest does not match its body",
            note_id=note["note_id"],
        )
    body = {key: note[key] for key in note if key != "receipt_digest"}
    if sha256_json(body) != note["receipt_digest"]:
        raise _error(
            "DISCOVERY_DIGEST_MISMATCH",
            "recorded discovery note receipt digest does not match its payload",
            note_id=note["note_id"],
        )
    return note


def reduce_discovery_state(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
) -> DiscoveryState:
    """Replay the advisory discovery journal for one project.

    The journal is append-only: there is no edit or delete event, so replay is a
    filter over recorded notes.  Recording the same body twice yields two
    distinct notes, which is why note identity binds the note's position in the
    journal rather than its content alone.
    """

    notes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_fingerprints: set[str] = set()
    for event in events:
        event_type, payload, _occurred_at = _event_parts(event, project_id=project_id)
        if event_type != DISCOVERY_NOTE_EVENT_TYPE:
            continue
        note = _validate_recorded_note(payload)
        note_id = str(note["note_id"])
        if note_id in seen_ids:
            raise _error(
                "DISCOVERY_DUPLICATE_NOTE",
                "discovery note identity is not unique",
                note_id=note_id,
            )
        expected_sequence = len(notes)
        if note["note_sequence"] != expected_sequence:
            raise _error(
                "DISCOVERY_SEQUENCE_INVALID",
                "discovery note sequence does not match journal order",
                note_id=note_id,
                expected_sequence=expected_sequence,
                observed_sequence=note["note_sequence"],
            )
        if note_id != _note_identity(note["content_digest"], expected_sequence):
            raise _error(
                "DISCOVERY_DIGEST_MISMATCH",
                "discovery note identity does not match its content and position",
                note_id=note_id,
            )
        if note["kind"] == "rival_draft":
            # The append path already rejects a colliding draft, so replaying the
            # same rule cannot reject a legitimately produced journal.  It does
            # reject a hand-forged one whose per-note digests are all valid.
            fingerprint = draft_fingerprint(note["body"])
            if fingerprint in seen_fingerprints:
                raise _error(
                    "DISCOVERY_DRAFT_NOT_DISTINCT",
                    "journal contains two rival drafts with the same assumptions and mechanism",
                    note_id=note_id,
                )
            seen_fingerprints.add(fingerprint)
        seen_ids.add(note_id)
        notes.append(note)
    return DiscoveryState(project_id=project_id, notes=tuple(notes))


def _note_identity(content_digest: str, note_sequence: int) -> str:
    return stable_id("discoverynote", content_digest, note_sequence)


def plan_discovery_note(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    raw: Mapping[str, Any],
    recorded_at: str,
) -> DiscoveryPlan:
    """Plan one append-only discovery note.

    Unlike a frame-transition receipt there is no idempotent reuse path.  Two
    identical bodies are two observations, not one repeated claim, so each
    request appends a new note.
    """

    state = reduce_discovery_state(events, project_id=project_id)
    core = screen_note(raw)
    if core["kind"] == "rival_draft":
        fingerprint = draft_fingerprint(core["body"])
        if fingerprint in state.rival_fingerprints:
            raise _error(
                "DISCOVERY_DRAFT_NOT_DISTINCT",
                "a recorded rival draft already states these assumptions and mechanism",
                path="$.body",
            )
    note_sequence = state.note_count
    note_id = _note_identity(core["content_digest"], note_sequence)
    body = {
        **core,
        "note_id": note_id,
        "note_sequence": note_sequence,
        "recorded_at": _timestamp(recorded_at, path="$.recorded_at"),
    }
    payload = {**body, "receipt_digest": sha256_json(body)}
    if set(payload) != set(_NOTE_PAYLOAD_KEYS):  # pragma: no cover - planner invariant
        raise RuntimeError(
            "invalid discovery note planner fields: "
            f"{sorted(set(payload) ^ set(_NOTE_PAYLOAD_KEYS))}"
        )
    synthetic = {
        "project_id": project_id,
        "event_type": DISCOVERY_NOTE_EVENT_TYPE,
        "occurred_at": payload["recorded_at"],
        "payload": payload,
    }
    reduce_discovery_state((*events, synthetic), project_id=project_id)
    return DiscoveryPlan(
        event_type=DISCOVERY_NOTE_EVENT_TYPE,
        payload=payload,
        note_id=note_id,
        receipt_digest=str(payload["receipt_digest"]),
    )


def exhaustion_projection(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
) -> dict[str, Any]:
    """Summarize which exhaustion signal kinds currently have material.

    This reads canonical scientific state and the advisory journal and writes
    nothing.  Canonical rows come from class lifecycle and terminal rejections;
    advisory rows come from journal notes.  The frame-transition gate needs two
    distinct kinds with at least one canonical row, so both counts are reported
    separately rather than summed.
    """

    scientific = reduce_scientific_state(events, project_id=project_id)
    discovery = reduce_discovery_state(events, project_id=project_id)

    closed_classes = tuple(
        item.hypothesis_class_id
        for item in scientific.class_states
        if item.lifecycle == "closed"
    )
    rejected_by_class: dict[str, int] = {}
    for registration in scientific.registrations:
        if registration.terminal_status != "REJECTED":
            continue
        class_id = registration.proposal.hypothesis_class_id
        rejected_by_class[class_id] = rejected_by_class.get(class_id, 0) + 1
    repeated_failure_classes = tuple(
        sorted(class_id for class_id, count in rejected_by_class.items() if count >= 2)
    )

    canonical = {
        "class_closure": len(closed_classes),
        "repeated_failure": len(repeated_failure_classes),
    }
    advisory = {
        signal_kind: len(discovery.notes_of_kind(note_kind))
        for note_kind, signal_kind in SIGNAL_KIND_BY_NOTE_KIND.items()
    }
    canonical_kinds = sorted(kind for kind, count in canonical.items() if count > 0)
    advisory_kinds = sorted(kind for kind, count in advisory.items() if count > 0)
    distinct_kinds = sorted(set(canonical_kinds) | set(advisory_kinds))
    return {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "project_id": project_id,
        "lane": "advisory",
        "active_generation_id": scientific.active_generation_id,
        "canonical_signal_counts": canonical,
        "advisory_signal_counts": advisory,
        "canonical_signal_kinds": canonical_kinds,
        "advisory_signal_kinds": advisory_kinds,
        "distinct_signal_kinds": distinct_kinds,
        "closed_hypothesis_class_ids": sorted(closed_classes),
        "repeated_failure_hypothesis_class_ids": list(repeated_failure_classes),
        # The gate needs two distinct kinds and at least one canonical row.
        "inquiry_signal_conditions_met": len(distinct_kinds) >= 2
        and bool(canonical_kinds),
        "authorized_action": None,
    }


def _margin_trajectory(scientific: Any, class_id: str) -> list[dict[str, Any]]:
    """Extract the ordered decision-margin series for one hypothesis class.

    Raw evidence, deliberately unjudged: whether a flattening series means
    stagnation, noise, or a dead axis is an interpretation, and interpretation
    belongs to the reader, not to this projection.
    """

    rows: list[tuple[int, dict[str, Any]]] = []
    for registration in scientific.registrations:
        if registration.proposal.hypothesis_class_id != class_id:
            continue
        if registration.terminal_status is None:
            continue
        payload = registration.terminal_payload
        decision = payload.get("decision") if isinstance(payload, Mapping) else None
        margin = decision.get("promotion_margin") if isinstance(decision, Mapping) else None
        rows.append(
            (
                registration.terminal_event_sequence
                if registration.terminal_event_sequence is not None
                else 2**63,
                {
                    "experiment_id": registration.experiment_id,
                    "terminal_status": registration.terminal_status,
                    "promotion_margin": margin,
                    "mechanism": registration.proposal.mechanism,
                },
            )
        )
    rows.sort(key=lambda item: item[0])
    return [row for _, row in rows]


#: The questions a frame-health packet asks its reader to answer.  These name
#: the exhaustion modes the canonical signals cannot count: a frame can be
#: wrong long before it is exhausted, and locally improving margins can mask a
#: dead axis.  The OS deliberately computes no verdict for any of them.
FRAME_HEALTH_INTERPRETATION_REQUESTS = (
    {
        "id": "stagnation",
        "question": (
            "Looking at each open class's margin trajectory, is progress "
            "converging toward zero while the class stays open?  Counting "
            "rejections cannot see this."
        ),
        "if_judged_yes": (
            "Record an `anomaly` discovery note citing the experiment IDs in "
            "the flattening series; it becomes an unresolved_anomaly signal."
        ),
    },
    {
        "id": "assumption_misfit",
        "question": (
            "Do the mechanisms tried so far share a commitment that the "
            "accumulated evidence quietly contradicts, even where individual "
            "experiments still pass?"
        ),
        "if_judged_yes": (
            "Record an `assumption_conflict` note naming the shared commitment "
            "and citing the contradicting experiments or diagnoses."
        ),
    },
    {
        "id": "frame_misfit",
        "question": (
            "Is the declared hypothesis-class list itself the wrong carving -- "
            "would a differently shaped class, representation, or objective "
            "explain the pattern of failures better than any member of the "
            "declared classes?"
        ),
        "if_judged_yes": (
            "Draft one or more `rival_draft` notes; generate several and let "
            "the fingerprint screen discard the ones that only relabel."
        ),
    },
)


def frame_health_projection(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
) -> dict[str, Any]:
    """Assemble the evidence an LLM needs to judge whether a jump is due.

    This is an interpretation packet, not a verdict.  Canonical facts -- class
    lifecycles, margin trajectories, closure counters, the all-classes-closed
    stop condition, journal contents -- are laid out next to the explicit
    questions only a reader can answer.  The packet never says "stagnating" or
    "misfit"; it says what happened and asks.
    """

    scientific = reduce_scientific_state(events, project_id=project_id)
    discovery = reduce_discovery_state(events, project_id=project_id)

    classes = []
    for class_state in scientific.class_states:
        classes.append(
            {
                "hypothesis_class_id": class_state.hypothesis_class_id,
                "lifecycle": class_state.lifecycle,
                "support": class_state.support,
                "conclusive_rejections": class_state.conclusive_rejections,
                "conclusive_rejection_limit": class_state.conclusive_rejection_limit,
                "closure_reason": class_state.closure_reason,
                "margin_trajectory": _margin_trajectory(
                    scientific, class_state.hypothesis_class_id
                ),
            }
        )

    open_questions = [
        {
            "note_id": note["note_id"],
            "kind": note["kind"],
            "open_question": note["body"]["open_question"],
        }
        for note in discovery.notes
        if note.get("kind") in SIGNAL_BEARING_KINDS
    ]

    study_stop = scientific.study_stop
    return {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "project_id": project_id,
        "lane": "advisory",
        "active_generation_id": scientific.active_generation_id,
        "study_stop": study_stop,
        "all_classes_closed": bool(study_stop.get("all_classes_closed")),
        "classes": classes,
        "recorded_open_questions": open_questions,
        "rival_draft_count": len(discovery.notes_of_kind("rival_draft")),
        "interpretation_requests": [
            dict(item) for item in FRAME_HEALTH_INTERPRETATION_REQUESTS
        ],
        "authorized_action": None,
    }


def residual_task(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
) -> dict[str, Any]:
    """Compute the residual generation task for each closed hypothesis class.

    A jump has one mechanical form: negate what every failed attempt in the
    exhausted class held in common.  ``Proposal`` records a mechanism rather
    than a separate assumption list, so the shared commitment is presented as
    the mechanisms that were tried and the falsifiers they offered.  This is a
    projection over canonical state; it creates no truth of its own and is
    omitted entirely when no class is closed.
    """

    scientific = reduce_scientific_state(events, project_id=project_id)
    tasks: list[dict[str, Any]] = []
    for class_state in scientific.class_states:
        if class_state.lifecycle != "closed":
            continue
        attempts = [
            {
                "experiment_id": registration.experiment_id,
                "mechanism": registration.proposal.mechanism,
                "predicted_effect": registration.proposal.predicted_effect,
                "falsifier": registration.proposal.falsifier,
            }
            for registration in scientific.registrations
            if registration.proposal.hypothesis_class_id == class_state.hypothesis_class_id
            and registration.terminal_status == "REJECTED"
        ]
        if not attempts:
            continue
        tasks.append(
            {
                "hypothesis_class_id": class_state.hypothesis_class_id,
                "closure_reason": class_state.closure_reason,
                "failed_attempt_count": len(attempts),
                "failed_attempts": attempts,
                "instruction": (
                    "These attempts failed inside a closed hypothesis class. "
                    "State the commitment their mechanisms share, then propose a "
                    "frame in which that commitment is false."
                ),
            }
        )
    return {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "project_id": project_id,
        "lane": "advisory",
        "active_generation_id": scientific.active_generation_id,
        "residual_tasks": tasks,
        "authorized_action": None,
    }


def yield_projection(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
) -> dict[str, Any]:
    """Report the draft yield curve that decides whether the lane stays.

    Counting admissible notes, distinct rival fingerprints, and how many drafts
    were produced while reading cross-frame material is the whole measurement
    plan.  It needs no held-out set, because it measures the rate at which
    frame-exceeding candidates appear rather than whether any of them is right.
    """

    discovery = reduce_discovery_state(events, project_id=project_id)
    scientific = reduce_scientific_state(events, project_id=project_id)
    drafts = discovery.notes_of_kind("rival_draft")
    analogy_backed = tuple(
        note for note in drafts if note.get("analogy_query_digest") is not None
    )
    return {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "project_id": project_id,
        "lane": "advisory",
        "active_generation_id": scientific.active_generation_id,
        "admissible_note_count": discovery.note_count,
        "admissible_notes_by_kind": {
            kind: len(discovery.notes_of_kind(kind)) for kind in sorted(NOTE_KINDS)
        },
        "rival_draft_count": len(drafts),
        "distinct_rival_fingerprints": len(discovery.rival_fingerprints),
        "analogy_backed_rival_draft_count": len(analogy_backed),
        "analogy_backed_ratio_microunits": (
            0 if not drafts else (len(analogy_backed) * 1_000_000) // len(drafts)
        ),
        "authorized_action": None,
    }


def jump_dossier(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    note_id: str,
) -> dict[str, Any]:
    """Assemble everything an LLM must hold to author a real frame jump.

    A rival draft is advisory free text; a real J2/J3 change is a successor
    StudyContract plus, usually, a new candidate schema and a fresh evaluator
    certification.  Between the two sits a cliff of project-owned obligations
    that nothing previously enumerated.  The dossier makes every wall of that
    cliff explicit -- current contract facts on one side, the draft on the
    other, and the ordered authoring obligations in between.

    It grants nothing and generates nothing: the successor contract, the schema
    delta, and the inquiry inputs are all authored by the reader.  A dossier is
    a map of the climb, not a lift.
    """

    scientific = reduce_scientific_state(events, project_id=project_id)
    discovery = reduce_discovery_state(events, project_id=project_id)

    draft = next(
        (note for note in discovery.notes_of_kind("rival_draft") if note["note_id"] == note_id),
        None,
    )
    if draft is None:
        raise _error(
            "DISCOVERY_NOTE_UNKNOWN",
            "no rival_draft with this note identity is recorded",
            note_id=note_id,
        )

    contract = scientific.contract
    current_frame: dict[str, Any] | None = None
    if contract is not None:
        current_frame = {
            "study_id": contract.study_id,
            "study_contract_digest": contract.digest,
            "hypothesis_classes": [
                {
                    "id": item.id,
                    "description": item.description,
                    "conclusive_rejection_limit": item.conclusive_rejection_limit,
                }
                for item in contract.hypothesis_classes
            ],
            "evaluation_scopes": [scope.to_dict() for scope in contract.evaluation_scopes],
            "intervention_surface": contract.intervention_surface.to_dict(),
        }

    exhaustion = exhaustion_projection(events, project_id=project_id)

    # Ordered, explicit, and advisory: each obligation names what must be
    # authored or re-certified and by whom.  None of them is performed here.
    obligations = [
        {
            "id": "successor_contract",
            "owner": "author",
            "obligation": (
                "Write the successor StudyContract: new hypothesis classes "
                "expressing the draft's mechanism, evaluation scopes, "
                "intervention surface, stop policy, and budget.  The draft's "
                "assumptions and falsifiers should reappear as class "
                "descriptions and stop conditions, not vanish in translation."
            ),
        },
        {
            "id": "candidate_schema",
            "owner": "author",
            "obligation": (
                "Decide whether the draft's representation fits the current "
                "candidate schema.  If not, the project's candidate.schema.json "
                "must change, and the successor contract's "
                "intervention_surface.candidate_schema_digest must bind the new "
                "bytes."
            ),
        },
        {
            "id": "evaluator_recertification",
            "owner": "independent_reviewer",
            "obligation": (
                "A changed candidate schema or evaluator is a semantic change: "
                "an independent reviewer must re-certify via `certify-evaluator "
                "--replace` with a fresh review binding the new "
                "evaluator-review-subject digest.  The author may not perform "
                "this step."
            ),
        },
        {
            "id": "objective_change_control",
            "owner": "independent_reviewer",
            "obligation": (
                "If the draft changes the objective, metric, or evaluator "
                "meaning (J3), the evaluator itself and possibly the adapter "
                "change; that passes through project change-control before any "
                "inquiry can bind it."
            ),
        },
        {
            "id": "frame_transition_inquiry",
            "owner": "author",
            "obligation": (
                "Open the governed path: a current Gate A GO receipt, at least "
                "two substantively distinct rivals (this draft may be one), "
                "exhaustion signals of two distinct kinds including at least "
                "one canonical, and a discriminator frozen before results."
            ),
        },
        {
            "id": "adoption_boundary",
            "owner": "designated_human",
            "obligation": (
                "Pilot authorization is not adoption.  A durable successor "
                "opens only after PASS_FOR_ADOPTION, a fresh independent "
                "APPROVE, deterministic POLICY_ADOPTION, and a separate "
                "activate call binding the exact successor contract."
            ),
        },
    ]

    return {
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "project_id": project_id,
        "lane": "advisory",
        "active_generation_id": scientific.active_generation_id,
        "draft": json_value(draft),
        "draft_fingerprint": draft_fingerprint(draft["body"]),
        "current_frame": current_frame,
        "exhaustion": exhaustion,
        "inquiry_signal_conditions_met": exhaustion["inquiry_signal_conditions_met"],
        "authoring_obligations": obligations,
        "authorized_action": None,
    }


__all__ = [
    "DISCOVERY_EVENT_TYPES",
    "DISCOVERY_NOTE_EVENT_TYPE",
    "DISCOVERY_SCHEMA_VERSION",
    "FRAME_HEALTH_INTERPRETATION_REQUESTS",
    "NOTE_KINDS",
    "SIGNAL_BEARING_KINDS",
    "SIGNAL_KIND_BY_NOTE_KIND",
    "DiscoveryPlan",
    "DiscoveryState",
    "draft_fingerprint",
    "exhaustion_projection",
    "frame_health_projection",
    "jump_dossier",
    "plan_discovery_note",
    "reduce_discovery_state",
    "residual_task",
    "screen_note",
    "yield_projection",
]
