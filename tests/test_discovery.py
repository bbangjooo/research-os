"""The advisory discovery journal screens, replays, and grants no authority."""

from __future__ import annotations

import copy
from typing import Any

import pytest

from research_os.contracts import sha256_json
from research_os.discovery import (
    DISCOVERY_NOTE_EVENT_TYPE,
    NOTE_KINDS,
    draft_fingerprint,
    exhaustion_projection,
    frame_health_projection,
    jump_dossier,
    plan_discovery_note,
    reduce_discovery_state,
    residual_task,
    screen_note,
    yield_projection,
)
from research_os.errors import ScientificStateError
from research_os.frame_transition import rival_fingerprint

_PROJECT_ID = "discovery-journal-test"
_T0 = "2026-08-17T00:00:00Z"


def _anomaly(**overrides: Any) -> dict[str, Any]:
    raw = {
        "schema_version": 1,
        "kind": "anomaly",
        "body": {
            "summary": "Residual drift persists after the class-a sweep.",
            "evidence_refs": ["experiment_0001"],
            "open_question": "Is the drift an artifact of the holdout split?",
        },
        "refs": ["diagnosis_0001"],
        "analogy_query_digest": None,
        "authorized_action": None,
    }
    raw.update(overrides)
    return raw


def _draft(**overrides: Any) -> dict[str, Any]:
    raw = {
        "schema_version": 1,
        "kind": "rival_draft",
        "body": {
            "rival_id": "rival_alpha",
            "label": "Latent regime switch",
            "assumptions": ["The generating process is stationary"],
            "mechanism": "Replace the stationary prior with a two-regime mixture",
            "predictions": ["Residual drift disappears inside each regime"],
            "falsifiers": ["Drift persists after conditioning on the regime label"],
            "uncertainty": "Regime boundaries are not directly observed.",
        },
        "refs": ["experiment_0001"],
        "analogy_query_digest": None,
        "authorized_action": None,
    }
    raw.update(overrides)
    return raw


def _event(plan: Any) -> dict[str, Any]:
    return {
        "project_id": _PROJECT_ID,
        "event_type": plan.event_type,
        "occurred_at": plan.payload["recorded_at"],
        "payload": dict(plan.payload),
    }


def _journal(*raws: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, raw in enumerate(raws):
        plan = plan_discovery_note(
            events,
            project_id=_PROJECT_ID,
            raw=raw,
            recorded_at=f"2026-08-17T00:00:{index:02d}Z",
        )
        events.append(_event(plan))
    return events


# --- schema screen ---------------------------------------------------------


def test_every_declared_kind_has_a_body_schema() -> None:
    for kind in NOTE_KINDS:
        with pytest.raises(ScientificStateError) as excinfo:
            screen_note({**_anomaly(), "kind": kind, "body": {}})
        assert excinfo.value.code == "DISCOVERY_INVALID"


def test_unknown_kind_is_rejected() -> None:
    with pytest.raises(ScientificStateError) as excinfo:
        screen_note({**_anomaly(), "kind": "speculation"})
    assert excinfo.value.code == "DISCOVERY_INVALID"


def test_unknown_body_field_is_rejected() -> None:
    raw = _anomaly()
    raw["body"] = {**raw["body"], "confidence": "high"}
    with pytest.raises(ScientificStateError) as excinfo:
        screen_note(raw)
    assert excinfo.value.code == "DISCOVERY_INVALID"


def test_non_null_authority_is_rejected() -> None:
    with pytest.raises(ScientificStateError) as excinfo:
        screen_note(_anomaly(authorized_action="open_generation"))
    assert excinfo.value.code == "DISCOVERY_AUTHORITY_INVALID"


def test_screened_note_carries_null_authority() -> None:
    core = screen_note(_anomaly())
    assert "authorized_action" not in core
    plan = plan_discovery_note([], project_id=_PROJECT_ID, raw=_anomaly(), recorded_at=_T0)
    assert plan.payload.get("authorized_action") is None


# --- G4 admissibility screen ----------------------------------------------


def test_signal_bearing_note_requires_evidence_refs() -> None:
    raw = _anomaly()
    raw["body"] = {**raw["body"], "evidence_refs": []}
    with pytest.raises(ScientificStateError) as excinfo:
        screen_note(raw)
    assert excinfo.value.code == "DISCOVERY_EVIDENCE_INSUFFICIENT"


def test_rival_draft_requires_a_falsifier() -> None:
    raw = _draft()
    raw["body"] = {**raw["body"], "falsifiers": []}
    with pytest.raises(ScientificStateError) as excinfo:
        screen_note(raw)
    assert excinfo.value.code == "DISCOVERY_EVIDENCE_INSUFFICIENT"


def test_rival_draft_requires_a_canonical_reference() -> None:
    with pytest.raises(ScientificStateError) as excinfo:
        screen_note(_draft(refs=[]))
    assert excinfo.value.code == "DISCOVERY_EVIDENCE_INSUFFICIENT"


def test_idea_is_the_cheapest_kind_and_needs_no_reference() -> None:
    core = screen_note(
        {
            "schema_version": 1,
            "kind": "idea",
            "body": {"summary": "Try a spectral view of the residual.", "motivating_refs": []},
            "refs": [],
            "analogy_query_digest": None,
            "authorized_action": None,
        }
    )
    assert core["kind"] == "idea"


def test_repeated_reference_is_rejected() -> None:
    with pytest.raises(ScientificStateError) as excinfo:
        screen_note(_draft(refs=["experiment_0001", "experiment_0001"]))
    assert excinfo.value.code == "DISCOVERY_INVALID"


# --- G3 divergence ---------------------------------------------------------


def test_draft_fingerprint_matches_frame_transition_rival_fingerprint() -> None:
    body = _draft()["body"]
    assert draft_fingerprint(body) == rival_fingerprint(
        body["assumptions"], body["mechanism"]
    )


def test_relabelled_draft_is_rejected_as_a_duplicate() -> None:
    events = _journal(_draft())
    relabelled = _draft()
    relabelled["body"] = {
        **relabelled["body"],
        "rival_id": "rival_beta",
        "label": "A completely different name",
        "assumptions": ["the   GENERATING process IS stationary"],
        "mechanism": "REPLACE the stationary   prior with a two-regime mixture",
    }
    with pytest.raises(ScientificStateError) as excinfo:
        plan_discovery_note(
            events, project_id=_PROJECT_ID, raw=relabelled, recorded_at=_T0
        )
    assert excinfo.value.code == "DISCOVERY_DRAFT_NOT_DISTINCT"


def test_substantively_different_draft_is_accepted() -> None:
    events = _journal(_draft())
    other = _draft()
    other["body"] = {
        **other["body"],
        "rival_id": "rival_gamma",
        "label": "Measurement error",
        "assumptions": ["The instrument is unbiased"],
        "mechanism": "Model the instrument bias as a latent offset",
    }
    plan = plan_discovery_note(events, project_id=_PROJECT_ID, raw=other, recorded_at=_T0)
    assert plan.payload["note_sequence"] == 1


# --- append-only replay ----------------------------------------------------


def test_identical_bodies_produce_two_distinct_notes() -> None:
    events = _journal(_anomaly(), _anomaly())
    state = reduce_discovery_state(events, project_id=_PROJECT_ID)
    assert state.note_count == 2
    note_ids = {note["note_id"] for note in state.notes}
    assert len(note_ids) == 2


def test_replay_is_stable_across_repeated_reduction() -> None:
    events = _journal(_anomaly(), _draft())
    first = reduce_discovery_state(events, project_id=_PROJECT_ID).to_dict()
    second = reduce_discovery_state(events, project_id=_PROJECT_ID).to_dict()
    assert first == second
    assert first["lane"] == "advisory"
    assert first["authorized_action"] is None


def test_tampered_body_is_rejected_on_replay() -> None:
    events = _journal(_anomaly())
    tampered = copy.deepcopy(events)
    tampered[0]["payload"]["body"]["summary"] = "Rewritten after the fact."
    with pytest.raises(ScientificStateError) as excinfo:
        reduce_discovery_state(tampered, project_id=_PROJECT_ID)
    assert excinfo.value.code == "DISCOVERY_DIGEST_MISMATCH"


def test_reordered_journal_is_rejected_on_replay() -> None:
    events = _journal(_anomaly(), _draft())
    with pytest.raises(ScientificStateError) as excinfo:
        reduce_discovery_state(list(reversed(events)), project_id=_PROJECT_ID)
    assert excinfo.value.code in {
        "DISCOVERY_SEQUENCE_INVALID",
        "DISCOVERY_DIGEST_MISMATCH",
    }


def test_duplicated_event_is_rejected_on_replay() -> None:
    events = _journal(_anomaly())
    with pytest.raises(ScientificStateError) as excinfo:
        reduce_discovery_state([*events, copy.deepcopy(events[0])], project_id=_PROJECT_ID)
    assert excinfo.value.code in {
        "DISCOVERY_DUPLICATE_NOTE",
        "DISCOVERY_SEQUENCE_INVALID",
    }


def test_forged_note_identity_is_rejected_on_replay() -> None:
    events = _journal(_anomaly())
    forged = copy.deepcopy(events)
    payload = forged[0]["payload"]
    payload["note_id"] = "discoverynote_" + "0" * 32
    body = {key: payload[key] for key in payload if key != "receipt_digest"}
    payload["receipt_digest"] = sha256_json(body)
    with pytest.raises(ScientificStateError) as excinfo:
        reduce_discovery_state(forged, project_id=_PROJECT_ID)
    assert excinfo.value.code == "DISCOVERY_DIGEST_MISMATCH"


def test_events_from_another_project_are_rejected() -> None:
    events = _journal(_anomaly())
    with pytest.raises(ScientificStateError) as excinfo:
        reduce_discovery_state(events, project_id="another-project")
    assert excinfo.value.code == "DISCOVERY_PROJECT_MISMATCH"


def test_unrelated_events_are_ignored() -> None:
    events = _journal(_anomaly())
    noise = {
        "project_id": _PROJECT_ID,
        "event_type": "research.some_other_extension.v1",
        "occurred_at": _T0,
        "payload": {"anything": True},
    }
    state = reduce_discovery_state([noise, *events], project_id=_PROJECT_ID)
    assert state.note_count == 1


# --- projections -----------------------------------------------------------


def test_exhaustion_projection_separates_canonical_from_advisory() -> None:
    events = _journal(_anomaly(), _anomaly(kind="assumption_conflict"))
    projection = exhaustion_projection(events, project_id=_PROJECT_ID)

    assert projection["advisory_signal_kinds"] == [
        "assumption_conflict",
        "unresolved_anomaly",
    ]
    assert projection["canonical_signal_kinds"] == []
    # Two advisory kinds and no canonical row must not satisfy the gate, or a
    # maker could open an inquiry entirely from notes they wrote themselves.
    assert projection["inquiry_signal_conditions_met"] is False
    assert projection["authorized_action"] is None


def test_exhaustion_projection_writes_nothing() -> None:
    events = _journal(_anomaly())
    before = copy.deepcopy(events)
    exhaustion_projection(events, project_id=_PROJECT_ID)
    assert events == before


def test_residual_task_is_empty_without_a_closed_class() -> None:
    events = _journal(_anomaly())
    projection = residual_task(events, project_id=_PROJECT_ID)
    assert projection["residual_tasks"] == []
    assert projection["authorized_action"] is None


def test_yield_projection_counts_admissible_distinct_drafts() -> None:
    other = _draft()
    other["body"] = {
        **other["body"],
        "rival_id": "rival_delta",
        "label": "Measurement error",
        "assumptions": ["The instrument is unbiased"],
        "mechanism": "Model the instrument bias as a latent offset",
    }
    events = _journal(_anomaly(), _draft(), other)
    projection = yield_projection(events, project_id=_PROJECT_ID)

    assert projection["admissible_note_count"] == 3
    assert projection["rival_draft_count"] == 2
    assert projection["distinct_rival_fingerprints"] == 2
    assert projection["analogy_backed_rival_draft_count"] == 0
    assert projection["analogy_backed_ratio_microunits"] == 0


def test_yield_projection_tracks_analogy_backed_drafts() -> None:
    events = _journal(_draft(analogy_query_digest="a" * 64))
    projection = yield_projection(events, project_id=_PROJECT_ID)
    assert projection["analogy_backed_rival_draft_count"] == 1
    assert projection["analogy_backed_ratio_microunits"] == 1_000_000


def test_analogy_query_digest_must_be_a_digest() -> None:
    with pytest.raises(ScientificStateError) as excinfo:
        screen_note(_draft(analogy_query_digest="not-a-digest"))
    assert excinfo.value.code == "DISCOVERY_INVALID"


def test_note_event_type_is_namespaced_outside_the_scientific_reducer() -> None:
    assert DISCOVERY_NOTE_EVENT_TYPE == "research.discovery_note.v1"


# --- frame health and dossier ----------------------------------------------


def test_frame_health_carries_questions_not_verdicts() -> None:
    events = _journal(_anomaly())
    packet = frame_health_projection(events, project_id=_PROJECT_ID)

    request_ids = [item["id"] for item in packet["interpretation_requests"]]
    assert request_ids == ["stagnation", "assumption_misfit", "frame_misfit"]
    # The packet must never pre-judge what only a reader can decide.  If a
    # future edit adds a computed verdict, this names the regression.
    for forbidden in ("stagnating", "misfit_detected", "jump_recommended"):
        assert forbidden not in packet
    assert packet["lane"] == "advisory"
    assert packet["authorized_action"] is None


def test_frame_health_surfaces_recorded_open_questions() -> None:
    events = _journal(_anomaly(), _anomaly(kind="assumption_conflict"))
    packet = frame_health_projection(events, project_id=_PROJECT_ID)

    kinds = {row["kind"] for row in packet["recorded_open_questions"]}
    assert kinds == {"anomaly", "assumption_conflict"}
    for row in packet["recorded_open_questions"]:
        assert row["open_question"]
        assert row["note_id"].startswith("discoverynote_")


def test_frame_health_writes_nothing() -> None:
    events = _journal(_anomaly())
    before = copy.deepcopy(events)
    frame_health_projection(events, project_id=_PROJECT_ID)
    assert events == before


def test_dossier_requires_a_recorded_rival_draft() -> None:
    events = _journal(_anomaly())
    with pytest.raises(ScientificStateError) as excinfo:
        jump_dossier(events, project_id=_PROJECT_ID, note_id="discoverynote_" + "0" * 32)
    assert excinfo.value.code == "DISCOVERY_NOTE_UNKNOWN"


def test_dossier_refuses_a_non_draft_note_identity() -> None:
    events = _journal(_anomaly())
    anomaly_id = events[0]["payload"]["note_id"]
    with pytest.raises(ScientificStateError) as excinfo:
        jump_dossier(events, project_id=_PROJECT_ID, note_id=anomaly_id)
    assert excinfo.value.code == "DISCOVERY_NOTE_UNKNOWN"


def test_dossier_separates_authoring_owners() -> None:
    events = _journal(_draft())
    draft_id = events[0]["payload"]["note_id"]
    dossier = jump_dossier(events, project_id=_PROJECT_ID, note_id=draft_id)

    owners = {row["id"]: row["owner"] for row in dossier["authoring_obligations"]}
    # The separation of powers is the content: the author may not certify, and
    # neither author nor reviewer may ratify adoption.
    assert owners["successor_contract"] == "author"
    assert owners["evaluator_recertification"] == "independent_reviewer"
    assert owners["adoption_boundary"] == "designated_human"
    assert dossier["draft_fingerprint"] == draft_fingerprint(_draft()["body"])
    assert dossier["lane"] == "advisory"
    assert dossier["authorized_action"] is None
