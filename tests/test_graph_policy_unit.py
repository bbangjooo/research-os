from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from research_os.errors import GraphPolicyError, IntegrityError
from research_os.graph_policy import (
    MAX_SCIENTIFIC_CHANGE_BYTES,
    GraphAction,
    graph_metadata_from_payload,
    graph_metadata_from_values,
    inherit_retry_graph_metadata,
    validate_graph_candidate_change,
    validate_graph_relationship,
    validate_retry_graph_metadata,
)
from research_os.kernel._canonical import canonical_bytes, sha256_hex
from research_os.kernel.events import EVENT_VERSION, Event
from research_os.kernel.ids import stable_id
from research_os.kernel.projection import ProjectionStore
from research_os.memory.findings import make_finding_event

PROJECT_ID = "graph-policy-test"
COMPATIBILITY = "compatibility-a"


def _event(
    previous: Event | None,
    event_type: str,
    payload: dict[str, object],
    *,
    event_id: str,
) -> Event:
    unsigned = {
        "event_id": event_id,
        "event_type": event_type,
        "occurred_at": "2026-08-05T00:00:00Z",
        "payload": payload,
        "prev_hash": previous.hash if previous is not None else None,
        "project_id": PROJECT_ID,
        "sequence": previous.sequence + 1 if previous is not None else 1,
        "version": EVENT_VERSION,
    }
    return Event.from_mapping({**unsigned, "hash": sha256_hex(canonical_bytes(unsigned))})


def _registration(
    experiment_id: str,
    candidate_digest: str,
    *,
    parent_id: str | None = None,
    attempt: int = 1,
    retry_of: str | None = None,
    compatibility_digest: str = COMPATIBILITY,
    graph_action: str | None = None,
    scientific_change: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "experiment_id": experiment_id,
        "parent_id": parent_id,
        "candidate_digest": candidate_digest,
        "compatibility_digest": compatibility_digest,
        "attempt": attempt,
        "retry_of": retry_of,
        "status": "registered",
    }
    if graph_action is not None or scientific_change is not None:
        payload.update(
            {
                "graph_metadata_version": 1,
                "graph_action": graph_action,
                "scientific_change": scientific_change,
            }
        )
    return payload


class GraphPolicyHelperTests(unittest.TestCase):
    def test_context_values_require_one_complete_declaration(self):
        with self.assertRaisesRegex(GraphPolicyError, "required"):
            graph_metadata_from_values(None, None, required=True)
        with self.assertRaisesRegex(GraphPolicyError, "provided together"):
            graph_metadata_from_values("explore", None)
        with self.assertRaisesRegex(GraphPolicyError, "unknown graph_action"):
            graph_metadata_from_values("retry", "same candidate")
        with self.assertRaisesRegex(GraphPolicyError, "non-empty"):
            graph_metadata_from_values("explore", "   ")

        metadata = graph_metadata_from_values("explore", "change threshold only")
        assert metadata is not None
        self.assertEqual(metadata.graph_action, GraphAction.EXPLORE)
        self.assertEqual(
            metadata.to_payload(),
            {
                "graph_metadata_version": 1,
                "graph_action": "explore",
                "scientific_change": "change threshold only",
            },
        )

    def test_payload_is_either_legacy_or_complete_version_one(self):
        self.assertIsNone(graph_metadata_from_payload({"candidate": {"x": 1}}))
        with self.assertRaisesRegex(GraphPolicyError, "incomplete"):
            graph_metadata_from_payload({"graph_action": "explore"})
        with self.assertRaisesRegex(GraphPolicyError, "must equal 1"):
            graph_metadata_from_payload(
                {
                    "graph_metadata_version": 2,
                    "graph_action": "explore",
                    "scientific_change": "one change",
                }
            )

    def test_scientific_change_has_a_utf8_byte_limit(self):
        accepted = "가" * (MAX_SCIENTIFIC_CHANGE_BYTES // 3)
        self.assertIsNotNone(graph_metadata_from_values("explore", accepted))
        rejected = accepted + "가"
        with self.assertRaisesRegex(GraphPolicyError, "byte limit"):
            graph_metadata_from_values("explore", rejected)

    def test_action_parent_contract_and_parent_evidence(self):
        explore = graph_metadata_from_values("explore", "new mechanism")
        exploit = graph_metadata_from_values("exploit", "tighten threshold")
        assert explore is not None and exploit is not None

        validate_graph_relationship(explore, None)
        with self.assertRaisesRegex(GraphPolicyError, "parent_id to be null"):
            validate_graph_relationship(explore, "exp_parent")
        with self.assertRaisesRegex(GraphPolicyError, "requires a parent"):
            validate_graph_relationship(exploit, None)
        with self.assertRaisesRegex(GraphPolicyError, "terminal parent"):
            validate_graph_relationship(exploit, "exp_parent", parent_is_terminal=False)
        with self.assertRaisesRegex(GraphPolicyError, "compatibility-matching"):
            validate_graph_relationship(
                exploit,
                "exp_parent",
                parent_is_terminal=True,
                compatibility_digest="new",
                parent_compatibility_digest="old",
            )

        validate_graph_candidate_change(
            exploit,
            candidate_digest="candidate-child",
            parent_candidate_digest="candidate-parent",
        )
        with self.assertRaisesRegex(GraphPolicyError, "must differ"):
            validate_graph_candidate_change(
                exploit,
                candidate_digest="candidate-same",
                parent_candidate_digest="candidate-same",
            )

    def test_retry_inherits_exact_metadata_and_legacy_absence(self):
        prior_payload = {
            "graph_metadata_version": 1,
            "graph_action": "ablate",
            "scientific_change": "remove the volume gate only",
        }
        inherited = inherit_retry_graph_metadata(prior_payload)
        self.assertEqual(inherited, graph_metadata_from_payload(prior_payload))
        validate_retry_graph_metadata(inherited, inherited)
        validate_retry_graph_metadata(None, None)

        with self.assertRaisesRegex(GraphPolicyError, "inherited"):
            inherit_retry_graph_metadata(
                prior_payload,
                graph_action="ablate",
                scientific_change="remove the volume gate only",
            )
        changed = graph_metadata_from_values("ablate", "remove two gates")
        with self.assertRaisesRegex(GraphPolicyError, "exactly match"):
            validate_retry_graph_metadata(changed, inherited)
        with self.assertRaisesRegex(GraphPolicyError, "exactly match"):
            validate_retry_graph_metadata(inherited, None)

class GraphPolicyProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.store = ProjectionStore(Path(self.temporary.name) / "state.db")
        self.initialized = _event(
            None,
            "PROJECT_INITIALIZED",
            {"project_id": PROJECT_ID, "status": "active"},
            event_id="evt_initialized",
        )
        self.store.apply(self.initialized)

    def test_legacy_registration_and_retry_remain_valid(self):
        first_payload = _registration("exp_legacy_1", "candidate-legacy")
        first_payload.pop("compatibility_digest")
        first = _event(
            self.initialized,
            "EXPERIMENT_REGISTERED",
            first_payload,
            event_id="evt_legacy_1",
        )
        self.store.apply(first)
        terminal = _event(
            first,
            "EXPERIMENT_TERMINATED",
            {
                "experiment_id": "exp_legacy_1",
                "status": "TIMED_OUT",
                "reason_code": "ADAPTER_TIMEOUT",
                "attempt": 1,
                "retry_of": None,
                "retryable": True,
            },
            event_id="evt_legacy_terminal",
        )
        self.store.apply(terminal)
        retry_payload = _registration(
            "exp_legacy_2",
            "candidate-legacy",
            attempt=2,
            retry_of="exp_legacy_1",
        )
        retry_payload.pop("compatibility_digest")
        retry = _event(
            terminal,
            "EXPERIMENT_REGISTERED",
            retry_payload,
            event_id="evt_legacy_2",
        )
        self.store.apply(retry)

        projected = self.store.experiment(PROJECT_ID, "exp_legacy_2")
        self.assertNotIn("graph_action", projected["payload"])
        self.assertEqual(projected["compatibility_digest"], "")

    def test_versioned_graph_registration_requires_compatibility_digest(self):
        payload = _registration(
            "exp_versioned",
            "candidate-versioned",
            graph_action="explore",
            scientific_change="introduce a versioned mechanism",
        )
        payload.pop("compatibility_digest")
        event = _event(
            self.initialized,
            "EXPERIMENT_REGISTERED",
            payload,
            event_id="evt_versioned",
        )

        with self.assertRaisesRegex(IntegrityError, "requires compatibility_digest"):
            self.store.apply(event)

    def test_projection_rejects_partial_metadata_and_non_root_parent_state(self):
        partial_payload = _registration("exp_partial", "candidate-partial")
        partial_payload["graph_action"] = "explore"
        partial = _event(
            self.initialized,
            "EXPERIMENT_REGISTERED",
            partial_payload,
            event_id="evt_partial",
        )
        with self.assertRaisesRegex(IntegrityError, "graph metadata is incomplete"):
            self.store.apply(partial)

        root = _event(
            self.initialized,
            "EXPERIMENT_REGISTERED",
            _registration(
                "exp_root",
                "candidate-root",
                graph_action="explore",
                scientific_change="introduce a new mechanism",
            ),
            event_id="evt_root",
        )
        self.store.apply(root)
        child_while_running = _event(
            root,
            "EXPERIMENT_REGISTERED",
            _registration(
                "exp_child",
                "candidate-child",
                parent_id="exp_root",
                graph_action="exploit",
                scientific_change="tighten one threshold",
            ),
            event_id="evt_child_running",
        )
        with self.assertRaisesRegex(IntegrityError, "terminal parent"):
            self.store.apply(child_while_running)

        terminal = _event(
            root,
            "EXPERIMENT_TERMINATED",
            {
                "experiment_id": "exp_root",
                "status": "REJECTED",
                "reason_code": "NO_IMPROVEMENT",
                "retryable": False,
            },
            event_id="evt_root_terminal",
        )
        self.store.apply(terminal)
        incompatible_child = _event(
            terminal,
            "EXPERIMENT_REGISTERED",
            _registration(
                "exp_child",
                "candidate-child",
                parent_id="exp_root",
                compatibility_digest="compatibility-b",
                graph_action="exploit",
                scientific_change="tighten one threshold",
            ),
            event_id="evt_child_incompatible",
        )
        with self.assertRaisesRegex(IntegrityError, "compatibility-matching"):
            self.store.apply(incompatible_child)

        valid_child = _event(
            terminal,
            "EXPERIMENT_REGISTERED",
            _registration(
                "exp_child",
                "candidate-child",
                parent_id="exp_root",
                graph_action="exploit",
                scientific_change="tighten one threshold",
            ),
            event_id="evt_child_valid",
        )
        self.store.apply(valid_child)

        identical_child = _event(
            valid_child,
            "EXPERIMENT_REGISTERED",
            _registration(
                "exp_identical_child",
                "candidate-root",
                parent_id="exp_root",
                graph_action="ablate",
                scientific_change="claim a change without changing the candidate",
            ),
            event_id="evt_identical_child",
        )
        with self.assertRaisesRegex(IntegrityError, "must differ"):
            self.store.apply(identical_child)

    def test_projection_rejects_retry_relabeling(self):
        first = _event(
            self.initialized,
            "EXPERIMENT_REGISTERED",
            _registration(
                "exp_attempt_1",
                "candidate-retry",
                graph_action="explore",
                scientific_change="one root change",
            ),
            event_id="evt_attempt_1",
        )
        self.store.apply(first)
        terminal = _event(
            first,
            "EXPERIMENT_TERMINATED",
            {
                "experiment_id": "exp_attempt_1",
                "status": "TIMED_OUT",
                "reason_code": "ADAPTER_TIMEOUT",
                "attempt": 1,
                "retry_of": None,
                "retryable": True,
            },
            event_id="evt_attempt_terminal",
        )
        self.store.apply(terminal)
        changed = _event(
            terminal,
            "EXPERIMENT_REGISTERED",
            _registration(
                "exp_attempt_2",
                "candidate-retry",
                attempt=2,
                retry_of="exp_attempt_1",
                graph_action="explore",
                scientific_change="pretend this is another change",
            ),
            event_id="evt_attempt_2_changed",
        )
        with self.assertRaisesRegex(IntegrityError, "exactly match"):
            self.store.apply(changed)

        inherited = _event(
            terminal,
            "EXPERIMENT_REGISTERED",
            _registration(
                "exp_attempt_2",
                "candidate-retry",
                attempt=2,
                retry_of="exp_attempt_1",
                graph_action="explore",
                scientific_change="one root change",
            ),
            event_id="evt_attempt_2_inherited",
        )
        self.store.apply(inherited)

    def test_projection_does_not_impose_a_lifetime_root_budget(self):
        previous = self.initialized
        for index in range(3):
            previous = _event(
                previous,
                "EXPERIMENT_REGISTERED",
                _registration(
                    f"exp_root_{index}",
                    f"candidate-root-{index}",
                    graph_action="explore",
                    scientific_change=f"root mechanism {index}",
                ),
                event_id=f"evt_root_{index}",
            )
            self.store.apply(previous)

        fourth = _event(
            previous,
            "EXPERIMENT_REGISTERED",
            _registration(
                "exp_root_3",
                "candidate-root-3",
                graph_action="explore",
                scientific_change="root mechanism 3",
            ),
            event_id="evt_root_3",
        )
        self.store.apply(fourth)
        self.assertEqual(len(self.store.lineage(PROJECT_ID)), 4)

    def test_projection_requires_exact_managed_branch_envelope_and_versions(self):
        registration = _event(
            self.initialized,
            "EXPERIMENT_REGISTERED",
            _registration("exp_branch", "candidate-branch"),
            event_id="evt_branch_registration",
        )
        self.store.apply(registration)
        terminal = _event(
            registration,
            "EXPERIMENT_TERMINATED",
            {
                "experiment_id": "exp_branch",
                "status": "REJECTED",
                "reason_code": "NO_IMPROVEMENT",
                "retryable": False,
            },
            event_id="evt_branch_terminal",
        )
        self.store.apply(terminal)

        content = {
            "branch_experiment_ids": ["exp_branch"],
            "hypothesis_class": "class-a",
            "failure_signature": "no improvement",
            "conclusion": "the mechanism is not supported",
            "confidence": "falsified",
            "next_step": "stop",
            "compatibility_digest": COMPATIBILITY,
        }
        evidence = [
            {
                "experiment_id": "exp_branch",
                "event_id": terminal.event_id,
                "event_hash": terminal.hash,
            }
        ]
        finding_id = stable_id(
            "finding",
            PROJECT_ID,
            "branch_conclusion",
            1,
            content,
            evidence,
        )
        payload = make_finding_event(
            PROJECT_ID,
            content,
            key="branch_conclusion",
            evidence=evidence,
            metadata={
                "claim_authority": "agent_interpretation",
                "authorized_action": None,
                "agent_context_token": "context-token",
                "agent_context_schema_version": 2,
            },
            finding_id=finding_id,
        )
        payload["branch_conclusion_version"] = 1

        float_version = dict(payload)
        float_version["branch_conclusion_version"] = 1.0
        with self.assertRaisesRegex(IntegrityError, "version is invalid"):
            self.store.apply(
                _event(
                    terminal,
                    "FINDING_RECORDED",
                    float_version,
                    event_id="evt_branch_float_version",
                )
            )

        float_context_version = dict(payload)
        float_context_version["metadata"] = {
            **payload["metadata"],
            "agent_context_schema_version": 2.0,
        }
        with self.assertRaisesRegex(IntegrityError, "metadata is invalid"):
            self.store.apply(
                _event(
                    terminal,
                    "FINDING_RECORDED",
                    float_context_version,
                    event_id="evt_branch_float_context_version",
                )
            )

        global_scope = dict(payload)
        global_scope.update({"scope": "global", "project_id": None})
        with self.assertRaisesRegex(IntegrityError, "envelope is invalid"):
            self.store.apply(
                _event(
                    terminal,
                    "FINDING_RECORDED",
                    global_scope,
                    event_id="evt_branch_global",
                )
            )

        extra_metadata = dict(payload)
        extra_metadata["metadata"] = {**payload["metadata"], "deployment": True}
        with self.assertRaisesRegex(IntegrityError, "metadata is invalid"):
            self.store.apply(
                _event(
                    terminal,
                    "FINDING_RECORDED",
                    extra_metadata,
                    event_id="evt_branch_extra_metadata",
                )
            )

        valid = _event(
            terminal,
            "FINDING_RECORDED",
            payload,
            event_id="evt_branch_valid",
        )
        self.store.apply(valid)
        projected = self.store.findings(project_id=PROJECT_ID)[-1]
        self.assertEqual(projected["finding_id"], finding_id)


if __name__ == "__main__":
    unittest.main()
