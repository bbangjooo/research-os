from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from typing import Any
from unittest import mock

import pytest

from research_os.contracts import sha256_json
from research_os.errors import ScientificStateError
from research_os.frame_transition import (
    FrameTransitionPlan,
    FrameTransitionState,
    controlled_change_reason,
)
from research_os.frame_transition_service import FrameTransitionService
from research_os.kernel.events import Event, EventLog
from research_os.science import GENERATION_EVENT_TYPE, StudyContract
from research_os.service import ResearchService
from tests.test_m1b_authority_surfaces import _authority_values
from tests.test_m1b_service_cli import (
    CONTRACT_PATH,
    ROOT,
    _configure_agent_files,
    _passing_review,
)

_EVENT_TYPE = "test.frame_transition_receipt.v1"
_PROJECT_ID = "frame-transition-service-test"
_WINNER_TIME = "2026-08-16T00:00:00Z"
_LOSER_TIME = "2026-08-16T00:00:01Z"


def _payload(key: str, recorded_at: str) -> dict[str, Any]:
    body = {
        "schema_version": 1,
        "receipt_id": f"frame_receipt_{key}",
        "key": key,
        "recorded_at": recorded_at,
        "authorized_action": None,
    }
    return {**body, "receipt_digest": sha256_json(body)}


def _planner(
    events: Sequence[Event | Mapping[str, Any]],
    *,
    project_id: str,
    raw: Mapping[str, Any],
    recorded_at: str,
) -> FrameTransitionPlan:
    del project_id
    key = raw["key"]
    if not isinstance(key, str):
        raise TypeError("key must be text")
    for event in events:
        event_type = event.event_type if isinstance(event, Event) else event["event_type"]
        payload = event.payload if isinstance(event, Event) else event["payload"]
        if event_type != _EVENT_TYPE or payload.get("key") != key:
            continue
        event_id = event.event_id if isinstance(event, Event) else event.get("event_id")
        assert isinstance(event_id, str)
        return FrameTransitionPlan(
            event_type=_EVENT_TYPE,
            payload=dict(payload),
            receipt_id=str(payload["receipt_id"]),
            receipt_digest=str(payload["receipt_digest"]),
            append_required=False,
            existing_event_id=event_id,
        )
    payload = _payload(key, recorded_at)
    return FrameTransitionPlan(
        event_type=_EVENT_TYPE,
        payload=payload,
        receipt_id=str(payload["receipt_id"]),
        receipt_digest=str(payload["receipt_digest"]),
        append_required=True,
    )


class _RacingEventLog(EventLog):
    """Inject an exact earlier winner immediately before the guarded append."""

    def __init__(self, path: Path):
        super().__init__(path, _PROJECT_ID)
        self.injected = False

    def append(
        self,
        event_type: str,
        payload: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Event:
        if not self.injected and kwargs.get("precondition") is not None:
            self.injected = True
            if payload is None:  # pragma: no cover - harness invariant
                raise AssertionError("planned receipt payload is required")
            winner = _payload(str(payload["key"]), _WINNER_TIME)
            EventLog.append(
                self,
                event_type,
                winner,
                occurred_at=_WINNER_TIME,
            )
        return EventLog.append(self, event_type, payload, **kwargs)


class _ResearchHarness:
    def __init__(self, event_log: EventLog):
        self.config = SimpleNamespace(project_id=_PROJECT_ID)
        self.event_log = event_log
        self.sync_calls = 0

    def _assert_config_unchanged(self) -> None:
        return None

    def _sync(self) -> int:
        self.sync_calls += 1
        return 0


class _ServiceHarness(FrameTransitionService):
    def __init__(self, event_log: EventLog):
        research = _ResearchHarness(event_log)
        self.research = research
        self.config = research.config
        self.event_log = event_log

    def _state(
        self,
        events: Sequence[Event],
        *,
        as_of: str | None = None,
    ) -> FrameTransitionState:
        del events, as_of
        return FrameTransitionState(
            project_id=_PROJECT_ID,
            active_generation_id=None,
            active_compatibility_digest=None,
            active_contract_digest=None,
            gates=(),
            inquiries=(),
            revoked_receipt_digests=frozenset(),
        )


class _ReadOnlyEventLog:
    def __init__(self, events: Sequence[Event] = ()):
        self.events = list(events)

    @contextmanager
    def locked_read(self):
        yield list(self.events)

    def read(self) -> list[Event]:
        return list(self.events)


class _ActivationResearch:
    def __init__(self, failure: Exception | None = None):
        self.config = SimpleNamespace(project_id=_PROJECT_ID)
        self.calls: list[tuple[Mapping[str, Any], dict[str, Any]]] = []
        self.failure = failure

    def _assert_config_unchanged(self) -> None:
        return None

    def open_generation(
        self,
        contract: Mapping[str, Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        self.calls.append((contract, kwargs))
        if self.failure is not None:
            raise self.failure
        return {
            "project_id": _PROJECT_ID,
            "event_type": "research.study_generation_opened.v1",
            "generation_id": "generation_successor",
            "appended": True,
            "appended_events": 1,
            "authorized_action": None,
        }


class _ActivationHarness(FrameTransitionService):
    def __init__(
        self,
        *,
        event_log: Any | None = None,
        failure: Exception | None = None,
    ):
        self.research = _ActivationResearch(failure)
        self.config = self.research.config
        self.event_log = _ReadOnlyEventLog() if event_log is None else event_log
        policy_adoption = {
            "receipt_digest": "a" * 64,
            "successor_compatibility_digest": "b" * 64,
        }
        initial = {
            "inquiry_id": "frame_inquiry_fixture",
            "policy_adoption": policy_adoption,
            "successor_generation_id": None,
            "durable_successor_writer_count": 0,
            "authorized_action": None,
        }
        final = {
            **initial,
            "successor_generation_id": "generation_successor",
            "durable_successor_writer_count": 1,
            "stage": "ACTIVATED",
            "terminal_result": "GO_ADOPTION",
        }
        self.states = [
            FrameTransitionState(
                project_id=_PROJECT_ID,
                active_generation_id="generation_predecessor",
                active_compatibility_digest="c" * 64,
                active_contract_digest="d" * 64,
                gates=(),
                inquiries=(initial,),
                revoked_receipt_digests=frozenset(),
            ),
            FrameTransitionState(
                project_id=_PROJECT_ID,
                active_generation_id="generation_successor",
                active_compatibility_digest="b" * 64,
                active_contract_digest="e" * 64,
                gates=(),
                inquiries=(final,),
                revoked_receipt_digests=frozenset(),
            ),
        ]

    def _state(
        self,
        events: Sequence[Event],
        *,
        as_of: str | None = None,
    ) -> FrameTransitionState:
        del events, as_of
        return self.states.pop(0)


def _controlled_generation_event(path: Path) -> tuple[EventLog, Event]:
    log = EventLog(path, _PROJECT_ID)
    reason = "controlled-frame-transition:frame_inquiry_fixture:" + "a" * 64
    event = log.append(
        "research.study_generation_opened.v1",
        {
            "generation_id": "generation_successor",
            "study_contract_digest": "e" * 64,
            "evaluation_seal": {"compatibility_digest": "b" * 64},
            "evaluation_seal_digest": "f" * 64,
            "predecessor_generation_id": "generation_predecessor",
            "change_reason": reason,
            "authorized_action": None,
        },
        occurred_at=_WINNER_TIME,
    )
    return log, event


class FrameTransitionServiceTests(unittest.TestCase):
    def test_empty_status_is_read_only_and_non_authorizing(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        event_log = EventLog(Path(temporary.name) / "events.jsonl", _PROJECT_ID)
        service = _ServiceHarness(event_log)

        with mock.patch(
            "research_os.frame_transition_service.utc_now",
            return_value=_LOSER_TIME,
        ):
            result = service.status()

        self.assertEqual(result["project_id"], _PROJECT_ID)
        self.assertEqual(result["gates"], [])
        self.assertEqual(result["inquiries"], [])
        self.assertIsNone(result["authorized_action"])
        self.assertEqual(event_log.read(), [])
        self.assertEqual(service.research.sync_calls, 0)

    def test_activation_delegates_exact_binding_to_generation_writer(self) -> None:
        service = _ActivationHarness()
        contract_digest = "e" * 64
        initial_binding = {
            "predecessor_generation_id": "generation_predecessor",
            "successor_generation_id": None,
            "source_tree_digest": "c" * 64,
            "already_activated": False,
            "authorized_action": None,
        }
        final_binding = {
            "predecessor_generation_id": "generation_predecessor",
            "successor_generation_id": "generation_successor",
            "source_tree_digest": "c" * 64,
            "already_activated": True,
            "authorized_action": None,
        }

        with (
            mock.patch(
                "research_os.frame_transition_service.utc_now",
                return_value=_LOSER_TIME,
            ),
            mock.patch(
                "research_os.frame_transition_service.StudyContract.from_mapping",
                return_value=SimpleNamespace(digest=contract_digest),
            ),
            mock.patch(
                "research_os.frame_transition_service.validate_controlled_activation",
                side_effect=[initial_binding, final_binding],
            ) as validate,
        ):
            result = service.activate(
                "frame_inquiry_fixture",
                {"contract": "fixture"},
            )

        expected_reason = "controlled-frame-transition:frame_inquiry_fixture:" + "a" * 64
        self.assertEqual(
            validate.call_args_list,
            [
                mock.call(
                    (),
                    project_id=_PROJECT_ID,
                    inquiry_id="frame_inquiry_fixture",
                    policy_adoption_digest="a" * 64,
                    target_contract_digest=contract_digest,
                    target_successor_compatibility_digest="b" * 64,
                    change_reason=expected_reason,
                    as_of=_LOSER_TIME,
                ),
                mock.call(
                    (),
                    project_id=_PROJECT_ID,
                    inquiry_id="frame_inquiry_fixture",
                    policy_adoption_digest="a" * 64,
                    target_contract_digest=contract_digest,
                    target_successor_compatibility_digest="b" * 64,
                    change_reason=expected_reason,
                    as_of=_LOSER_TIME,
                ),
            ],
        )
        self.assertEqual(
            service.research.calls,
            [
                (
                    {"contract": "fixture"},
                    {
                        "predecessor_generation_id": "generation_predecessor",
                        "change_reason": expected_reason,
                        "controlled_transition": {
                            "inquiry_id": "frame_inquiry_fixture",
                            "policy_adoption_digest": "a" * 64,
                            "source_tree_digest": "c" * 64,
                            "successor_compatibility_digest": "b" * 64,
                        },
                    },
                )
            ],
        )
        self.assertEqual(result["generation_id"], "generation_successor")
        self.assertEqual(result["frame_transition"]["terminal_result"], "GO_ADOPTION")
        self.assertIsNone(result["authorized_action"])

    def test_already_activated_returns_canonical_winner_without_writer_call(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        event_log, _ = _controlled_generation_event(Path(temporary.name) / "events.jsonl")
        service = _ActivationHarness(event_log=event_log)
        binding = {
            "predecessor_generation_id": "generation_predecessor",
            "successor_generation_id": "generation_successor",
            "successor_compatibility_digest": "b" * 64,
            "source_tree_digest": "c" * 64,
            "already_activated": True,
            "authorized_action": None,
        }

        with (
            mock.patch(
                "research_os.frame_transition_service.utc_now",
                return_value=_LOSER_TIME,
            ),
            mock.patch(
                "research_os.frame_transition_service.StudyContract.from_mapping",
                return_value=SimpleNamespace(digest="e" * 64),
            ),
            mock.patch(
                "research_os.frame_transition_service.validate_controlled_activation",
                return_value=binding,
            ),
        ):
            result = service.activate(
                "frame_inquiry_fixture",
                {"contract": "fixture"},
            )

        self.assertEqual(service.research.calls, [])
        self.assertEqual(result["generation_id"], "generation_successor")
        self.assertFalse(result["appended"])
        self.assertEqual(result["appended_events"], 0)
        self.assertEqual(
            result["frame_transition"]["durable_successor_writer_count"],
            1,
        )
        self.assertIsNone(result["authorized_action"])

    def test_writer_error_is_recovered_only_for_exact_concurrent_winner(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        event_log, _ = _controlled_generation_event(Path(temporary.name) / "events.jsonl")
        writer_error = RuntimeError("predecessor changed during activation")
        service = _ActivationHarness(event_log=event_log, failure=writer_error)
        initial_binding = {
            "predecessor_generation_id": "generation_predecessor",
            "successor_generation_id": None,
            "source_tree_digest": "c" * 64,
            "already_activated": False,
            "authorized_action": None,
        }
        winner_binding = {
            "predecessor_generation_id": "generation_predecessor",
            "successor_generation_id": "generation_successor",
            "successor_compatibility_digest": "b" * 64,
            "source_tree_digest": "c" * 64,
            "already_activated": True,
            "authorized_action": None,
        }

        with (
            mock.patch(
                "research_os.frame_transition_service.utc_now",
                return_value=_LOSER_TIME,
            ),
            mock.patch(
                "research_os.frame_transition_service.StudyContract.from_mapping",
                return_value=SimpleNamespace(digest="e" * 64),
            ),
            mock.patch(
                "research_os.frame_transition_service.validate_controlled_activation",
                side_effect=[initial_binding, winner_binding],
            ),
        ):
            result = service.activate(
                "frame_inquiry_fixture",
                {"contract": "fixture"},
            )

        self.assertEqual(len(service.research.calls), 1)
        self.assertEqual(result["generation_id"], "generation_successor")
        self.assertFalse(result["appended"])
        self.assertIsNone(result["authorized_action"])

    def test_writer_error_is_not_swallowed_without_exact_winner(self) -> None:
        writer_error = RuntimeError("generation writer failed")
        service = _ActivationHarness(failure=writer_error)
        initial_binding = {
            "predecessor_generation_id": "generation_predecessor",
            "successor_generation_id": None,
            "source_tree_digest": "c" * 64,
            "already_activated": False,
            "authorized_action": None,
        }

        with self.assertRaisesRegex(RuntimeError, "generation writer failed"):
            with (
                mock.patch(
                    "research_os.frame_transition_service.utc_now",
                    return_value=_LOSER_TIME,
                ),
                mock.patch(
                    "research_os.frame_transition_service.StudyContract.from_mapping",
                    return_value=SimpleNamespace(digest="e" * 64),
                ),
                mock.patch(
                    "research_os.frame_transition_service.validate_controlled_activation",
                    side_effect=[
                        initial_binding,
                        ScientificStateError(
                            "FRAME_TRANSITION_INQUIRY_STALE",
                            "no exact concurrent activation exists",
                        ),
                    ],
                ),
            ):
                service.activate(
                    "frame_inquiry_fixture",
                    {"contract": "fixture"},
                )

        self.assertEqual(len(service.research.calls), 1)

    def test_exact_append_race_returns_the_canonical_winner(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        event_log = _RacingEventLog(Path(temporary.name) / "events.jsonl")
        service = _ServiceHarness(event_log)

        with mock.patch(
            "research_os.frame_transition_service.utc_now",
            return_value=_LOSER_TIME,
        ):
            result = service._commit(_planner, {"key": "same"}, label="test receipt")

        events = event_log.read()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].payload["recorded_at"], _WINNER_TIME)
        self.assertFalse(result["appended"])
        self.assertEqual(result["appended_events"], 0)
        self.assertTrue(result["idempotent_reuse"])
        self.assertEqual(result["event_id"], events[0].event_id)
        self.assertEqual(result["receipt"], events[0].payload)
        self.assertIsNone(result["authorized_action"])
        self.assertEqual(service.research.sync_calls, 1)


def test_real_controlled_activation_race_has_one_exact_writer(tmp_path: Path) -> None:
    project = tmp_path / "project"
    shutil.copytree(ROOT / "examples" / "toy_optimization", project)
    runtime = project / ".research-os" / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    _configure_agent_files(project)

    research = ResearchService(project)
    subject = research.evaluator_review_subject()
    research.certify_evaluator(
        _passing_review(
            tmp_path / "initial-review.json",
            subject_digest=str(subject["digest"]),
        )
    )
    first = research.open_generation(CONTRACT_PATH)
    first_event = next(
        event
        for event in research.event_log.read()
        if event.event_type == GENERATION_EVENT_TYPE
    )
    first_seal = first_event.payload["evaluation_seal"]
    assert isinstance(first_seal, Mapping)
    predecessor_compatibility = str(first_seal["compatibility_digest"])
    def digest(label: str) -> str:
        return sha256_json({"fixture": label})

    expires_at = "2099-01-01T00:00:00Z"

    frame = FrameTransitionService(project)
    gate = frame.gate_a(
        {
            "schema_version": 1,
            "predecessor_generation_id": first["generation_id"],
            "compatibility_digest": predecessor_compatibility,
            "corpus_manifest_digest": digest("corpus"),
            "provider_revision": "provider-integration-v1",
            "privacy_policy_digest": digest("privacy"),
            "retention_policy_digest": digest("retention"),
            "rubric_digest": digest("rubric"),
            "label_owner_id": "label-owner",
            "review_owner_id": "review-owner",
            "independent_reviewer_id": "gate-reviewer",
            "sample_count": 20,
            "actual_output_count": 20,
            "recurrent_j2_j3_count": 3,
            "recurrence_threshold": 2,
            "rubric_stable": True,
            "evidence_digest": digest("gate-evidence"),
            "authorized_action": None,
        }
    )
    inquiry = frame.open_inquiry(
        {
            "schema_version": 1,
            "gate_receipt_digest": gate["receipt_digest"],
            "maker_id": "inquiry-maker",
            "claimed_jump_class": "J2",
            "changed_pointers": ["/representation/embedding"],
            "material_change": True,
            "exhaustion_signals": [
                {
                    "signal_id": "repeated-failure",
                    "kind": "repeated_failure",
                    "evidence_digest": digest("failure"),
                    "lane": "canonical",
                    "source_generation_id": first["generation_id"],
                    "source_compatibility_digest": predecessor_compatibility,
                },
                {
                    "signal_id": "unresolved-anomaly",
                    "kind": "unresolved_anomaly",
                    "evidence_digest": digest("anomaly"),
                    "lane": "canonical",
                    "source_generation_id": first["generation_id"],
                    "source_compatibility_digest": predecessor_compatibility,
                },
            ],
            "rivals": [
                {
                    "rival_id": "sparse-frame",
                    "label": "Sparse frame",
                    "assumptions": ["Failures arise from aliasing."],
                    "mechanism": "Separate aliased states with a sparse basis.",
                    "predictions": ["Replication error decreases."],
                    "falsifiers": ["Aliasing remains unchanged."],
                    "uncertainty": "Basis sensitivity remains unknown.",
                },
                {
                    "rival_id": "relational-frame",
                    "label": "Relational frame",
                    "assumptions": ["Failures arise from missing relations."],
                    "mechanism": "Encode relations in the candidate schema.",
                    "predictions": ["Relational failures decrease."],
                    "falsifiers": ["Relational failures persist."],
                    "uncertainty": "Relation extraction may be noisy.",
                },
            ],
            "discriminator": {
                "discriminator_id": "frozen-discriminator",
                "procedure": "Run the same paired task suite for both rivals.",
                "outcome_rule": "Prefer the lower replication error.",
                "plan_digest": digest("discriminator"),
            },
            "authorized_action": None,
        }
    )
    candidate = {
        "candidate_id": "candidate-frame-v2",
        "candidate_digest": digest("candidate"),
        "change_digest": digest("change"),
        "coverage_digest": digest("coverage"),
        "isolation_digest": digest("isolation"),
    }
    pilot_plan = {
        "pilot_plan_id": "pilot-plan",
        "task_digest": digest("task"),
        "provider_revision": "provider-integration-v1",
        "arms": ["llm_only", "llm_tools_memory", "llm_research_os"],
        "per_arm_call_limit": 2,
        "per_arm_token_limit": 1_000,
        "per_arm_elapsed_milliseconds_limit": 5_000,
        "per_arm_cost_microunits_limit": 1_000,
        "primary_metric": "replication_score",
        "higher_is_better": True,
        "minimum_effect_microunits": 20,
        "max_critical_false_promotions": 0,
        "privacy_policy_digest": digest("privacy"),
        "retention_policy_digest": digest("retention"),
        "teardown_policy": "Delete isolated pilot artifacts after receipt capture.",
    }
    decision = frame.decide_inquiry(
        {
            "schema_version": 1,
            "inquiry_id": inquiry["receipt_id"],
            "maker_id": "inquiry-maker",
            "outcome": "RECOMMEND_FOR_PILOT",
            "rationale": "The frozen discriminator favored the isolated candidate.",
            "evidence_digest": digest("decision"),
            "candidate": candidate,
            "pilot_plan": pilot_plan,
            "authorized_action": None,
        }
    )
    authorization = frame.authorize_pilot(
        {
            "schema_version": 1,
            "inquiry_id": inquiry["receipt_id"],
            "authorizer_id": "pilot-authorizer",
            "authority": "PILOT_ONLY",
            "candidate_digest": candidate["candidate_digest"],
            "pilot_plan_digest": decision["receipt"]["pilot_plan_digest"],
            "expires_at": expires_at,
            "evidence_digest": digest("pilot-authorization"),
            "authorized_action": None,
        }
    )
    pilot = frame.record_pilot(
        {
            "schema_version": 1,
            "inquiry_id": inquiry["receipt_id"],
            "evaluator_id": "pilot-evaluator",
            "authorization_receipt_digest": authorization["receipt_digest"],
            "arm_results": [
                {
                    "arm": arm,
                    "score_microunits": score,
                    "calls": 1,
                    "tokens": 100,
                    "elapsed_milliseconds": 100,
                    "cost_microunits": 100,
                    "critical_false_promotions": 0,
                }
                for arm, score in zip(
                    ("llm_only", "llm_tools_memory", "llm_research_os"),
                    (100, 110, 150),
                    strict=True,
                )
            ],
            "privacy_breach": False,
            "invariant_regression": False,
            "evidence_digest": digest("pilot-result"),
            "authorized_action": None,
        }
    )
    assert pilot["receipt"]["outcome"] == "PASS_FOR_ADOPTION"

    adapter_path = project / ".research-os" / "adapter.py"
    adapter_path.write_text(
        adapter_path.read_text(encoding="utf-8")
        + "\n# controlled frame-transition compatibility rotation\n",
        encoding="utf-8",
    )
    changed_research = ResearchService(project)
    changed_subject = changed_research.evaluator_review_subject()
    changed_research.certify_evaluator(
        _passing_review(
            tmp_path / "changed-review.json",
            subject_digest=str(changed_subject["digest"]),
        ),
        replace=True,
    )
    frame = FrameTransitionService(project)
    report = frame.research._doctor_snapshot(event_count=len(frame.event_log.read()))
    successor_seal = frame.research._evaluation_seal_from_report(report)
    assert successor_seal.compatibility_digest != predecessor_compatibility
    successor_raw = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    successor_raw["budget"]["max_attempts"] = 5
    successor_contract = StudyContract.from_mapping(successor_raw)
    review_raw = {
        "schema_version": 1,
        "inquiry_id": inquiry["receipt_id"],
        "reviewer_id": "adoption-reviewer",
        "verdict": "APPROVE",
        "candidate_digest": candidate["candidate_digest"],
        "change_digest": candidate["change_digest"],
        "coverage_digest": candidate["coverage_digest"],
        "pilot_receipt_digest": pilot["receipt_digest"],
        "tree_digest": report.fingerprints["source_tree_digest"],
        "predecessor_generation_id": first["generation_id"],
        "successor_contract_digest": successor_contract.digest,
        "successor_compatibility_digest": successor_seal.compatibility_digest,
        "expires_at": expires_at,
        "evidence_digest": digest("adoption-review"),
        "authorized_action": None,
    }
    review = frame.review_adoption(review_raw)
    drift_path = project / "unprotected-after-review.txt"
    drift_path.write_text("drift\n", encoding="utf-8")
    retry = frame.review_adoption(review_raw)
    assert retry["idempotent_reuse"] is True
    drift_path.unlink()
    policy_adoption = frame.adopt_policy(inquiry["receipt_id"])
    assert policy_adoption["receipt"]["decision"] == "POLICY_ADOPTION"
    assert policy_adoption["receipt"]["review_receipt_digest"] == review["receipt_digest"]
    assert "ratifier_id" not in policy_adoption["receipt"]

    drift_path.write_text("stale tree\n", encoding="utf-8")
    with pytest.raises(ScientificStateError) as stale_tree:
        frame.activate(inquiry["receipt_id"], successor_raw)
    assert stale_tree.value.code == "FRAME_TRANSITION_TREE_MISMATCH"

    drifted_report = frame.research._doctor_snapshot(
        event_count=len(frame.event_log.read())
    )
    drifted_tree_digest = drifted_report.fingerprints["source_tree_digest"]
    assert drifted_tree_digest != report.fingerprints["source_tree_digest"]
    with pytest.raises(ScientificStateError) as direct_bridge_bypass:
        frame.research.open_generation(
            successor_raw,
            predecessor_generation_id=first["generation_id"],
            change_reason=controlled_change_reason(
                inquiry["receipt_id"],
                policy_adoption["receipt_digest"],
            ),
            controlled_transition={
                "inquiry_id": inquiry["receipt_id"],
                "policy_adoption_digest": policy_adoption["receipt_digest"],
                "source_tree_digest": drifted_tree_digest,
                "successor_compatibility_digest": successor_seal.compatibility_digest,
            },
        )
    assert direct_bridge_bypass.value.code == "FRAME_TRANSITION_TREE_MISMATCH"
    drift_path.unlink()

    original_append = EventLog.append
    barrier = Barrier(2)

    def append_after_barrier(
        event_log: EventLog,
        event_type: str,
        *args: Any,
        **kwargs: Any,
    ) -> Event:
        if event_type == GENERATION_EVENT_TYPE:
            barrier.wait(timeout=15)
        return original_append(event_log, event_type, *args, **kwargs)

    def activate(_: int) -> dict[str, Any]:
        return FrameTransitionService(project).activate(
            inquiry["receipt_id"],
            successor_raw,
        )

    with mock.patch.object(EventLog, "append", new=append_after_barrier):
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(activate, range(2)))

    assert len({result["generation_id"] for result in results}) == 1
    assert sorted(result["appended"] for result in results) == [False, True]
    generation_events = [
        event
        for event in frame.event_log.read()
        if event.event_type == GENERATION_EVENT_TYPE
    ]
    assert len(generation_events) == 2
    final = FrameTransitionService(project).status(inquiry["receipt_id"])["inquiries"][0]
    assert final["terminal_result"] == "GO_ADOPTION"
    assert final["durable_successor_writer_count"] == 1
    assert policy_adoption["appended"] is True
    assert all(value is None for result in results for value in _authority_values(result))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
