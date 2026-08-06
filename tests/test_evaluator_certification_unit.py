from __future__ import annotations

import copy
import json
import os
import stat
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from research_os.agent import load_agent_spec
from research_os.certification import (
    CERTIFICATION_BINDING_KEYS,
    EVALUATOR_CERTIFICATION_RELATIVE,
    EVALUATOR_REVIEW_KIND,
    REQUIRED_EVALUATOR_CHECK_IDS,
    build_evaluator_review_subject,
    ensure_certification_gitignore,
    inspect_evaluator_certification,
    load_evaluator_certification,
    require_evaluator_certification,
    validate_evaluator_review,
)
from research_os.certification import (
    record_evaluator_certification as _record_evaluator_certification,
)
from research_os.config import load_project_config
from research_os.contracts import sha256_json
from research_os.errors import (
    ConfigurationError,
    EvaluatorCertificationError,
    IntegrityError,
)
from research_os.execution.workspace import WorkspaceManager, hash_tree
from research_os.provenance import project_fingerprints
from research_os.scaffold import initialize_project
from research_os.service import ResearchService


def _review(
    *,
    passing: bool = True,
    independent: bool = True,
    subject_digest: str = "0" * 64,
) -> dict[str, object]:
    checks = [
        {
            "id": check_id,
            "status": "PASS",
            "evidence": f"golden evidence for {check_id}",
        }
        for check_id in sorted(REQUIRED_EVALUATOR_CHECK_IDS)
    ]
    if not passing:
        checks[0]["status"] = "FAIL"
    return {
        "schema_version": 1,
        "kind": EVALUATOR_REVIEW_KIND,
        "subject_digest": subject_digest,
        "reviewer": "independent-critic",
        "independent_reviewer": independent,
        "verdict": "PASS" if passing else "FAIL",
        "summary": "Evaluator review completed against fixed golden cases.",
        "checks": checks,
        "blocking_findings": [] if passing else ["golden control mismatch"],
    }


def _doctor_fingerprints(config, *, adapter_revision: str = "fixture-v1") -> dict[str, object]:
    source = project_fingerprints(config)
    project_digest = source["compatibility_digest"]
    adapter_value = {"fixture_adapter_revision": adapter_revision}
    adapter_digest = sha256_json(adapter_value)
    return {
        **source,
        "project_compatibility_digest": project_digest,
        "adapter": {"digest": adapter_digest, "value": adapter_value},
        "compatibility_digest": sha256_json({"project": project_digest, "adapter": adapter_digest}),
    }


def _refresh_doctor_fingerprints(
    config,
    fingerprints: dict[str, object],
) -> dict[str, object]:
    """Fixture refresh: recompute project inputs while polling the same adapter."""

    source = project_fingerprints(config)
    adapter = copy.deepcopy(fingerprints.get("adapter"))
    project_digest = source["compatibility_digest"]
    adapter_digest = adapter["digest"]
    return {
        **source,
        "project_compatibility_digest": project_digest,
        "adapter": adapter,
        "compatibility_digest": sha256_json(
            {"project": project_digest, "adapter": adapter_digest}
        ),
    }


def record_evaluator_certification(
    config,
    review_path,
    *,
    fingerprints: dict[str, object],
    fresh_fingerprints=None,
    replace: bool = False,
):
    """Call the public API with an explicit fresh-doctor fixture."""

    refresh = fresh_fingerprints or (
        lambda: _refresh_doctor_fingerprints(config, fingerprints)
    )
    return _record_evaluator_certification(
        config,
        review_path,
        fingerprints=fingerprints,
        fresh_fingerprints=refresh,
        replace=replace,
    )


class EvaluatorCertificationTests(unittest.TestCase):
    def make_project(self) -> tuple[tempfile.TemporaryDirectory[str], Path]:
        temporary = tempfile.TemporaryDirectory()
        project = Path(temporary.name) / "project"
        project.mkdir()
        initialize_project(project, "cert-project", "Certification project")
        return temporary, project

    def write_review(self, project: Path, value: object) -> Path:
        if isinstance(value, dict) and value.get("subject_digest") == "0" * 64:
            config = load_project_config(project)
            doctor = _doctor_fingerprints(config)
            value = {
                **value,
                "subject_digest": build_evaluator_review_subject(
                    config,
                    fingerprints=doctor,
                )["digest"],
            }
        path = project.parent / "evaluator-review.json"
        path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
        return path

    def test_review_requires_exact_checks_and_independence_declaration(self):
        normalized = validate_evaluator_review(_review())
        self.assertEqual(
            {check["id"] for check in normalized["checks"]},
            REQUIRED_EVALUATOR_CHECK_IDS,
        )

        missing = _review()
        missing["checks"] = missing["checks"][:-1]
        with self.assertRaisesRegex(ConfigurationError, "exact required checks"):
            validate_evaluator_review(missing)

        extra = _review()
        extra["checks"].append({"id": "not_a_required_check", "status": "PASS", "evidence": "x"})
        with self.assertRaisesRegex(ConfigurationError, "unexpected"):
            validate_evaluator_review(extra)

        undeclared = _review()
        undeclared.pop("independent_reviewer")
        with self.assertRaisesRegex(ConfigurationError, "independent_reviewer"):
            validate_evaluator_review(undeclared)

        legacy = _review()
        legacy.pop("subject_digest")
        with self.assertRaisesRegex(ConfigurationError, "subject_digest"):
            validate_evaluator_review(legacy)

    def test_records_current_full_bindings_and_requires_a_pass(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)

        missing = inspect_evaluator_certification(config)
        self.assertEqual(missing["status"], "MISSING")
        self.assertFalse(missing["current"])
        self.assertEqual(missing["reason"], "missing")
        with self.assertRaises(EvaluatorCertificationError) as caught:
            require_evaluator_certification(config)
        self.assertEqual(caught.exception.code, "EVALUATOR_CERTIFICATION_REQUIRED")
        self.assertEqual(caught.exception.details["reason"], "missing")

        doctor = _doctor_fingerprints(config)
        artifact = record_evaluator_certification(
            config,
            self.write_review(project, _review()),
            fingerprints=doctor,
        )
        self.assertTrue(artifact["certified"])
        self.assertEqual(set(artifact["bindings"]), set(CERTIFICATION_BINDING_KEYS))
        current = project_fingerprints(config)
        for key in ("constitution", "protected", "evidence", "environment"):
            self.assertEqual(artifact["bindings"][key], current[key])
        self.assertEqual(artifact["bindings"]["adapter"], doctor["adapter"])
        self.assertEqual(
            artifact["bindings"]["effective_compatibility"]["digest"],
            doctor["compatibility_digest"],
        )
        spec = load_agent_spec(project)
        bound_spec = {
            "brief_path": spec["brief_path"],
            "candidate_schema_path": spec["candidate_schema_path"],
            "brief": spec["brief"],
            "candidate_schema": spec["candidate_schema"],
        }
        self.assertEqual(artifact["bindings"]["agent_spec"]["digest"], sha256_json(bound_spec))
        summary = inspect_evaluator_certification(config)
        self.assertEqual(summary["status"], "CERTIFIED")
        self.assertTrue(summary["certified"])
        self.assertTrue(summary["current"])
        self.assertIsNone(summary["reason"])
        self.assertEqual(summary["certification_digest"], artifact["digest"])
        self.assertEqual(require_evaluator_certification(config)["digest"], artifact["digest"])

    def test_rejected_review_revokes_a_prior_pass(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        first_doctor = _doctor_fingerprints(config)
        review_path = self.write_review(
            project,
            _review(
                subject_digest=str(
                    build_evaluator_review_subject(
                        config,
                        fingerprints=first_doctor,
                    )["digest"]
                )
            ),
        )
        first = record_evaluator_certification(
            config, review_path, fingerprints=_doctor_fingerprints(config)
        )
        self.assertTrue(first["certified"])

        review_path.write_text(
            json.dumps(
                _review(
                    passing=False,
                    subject_digest=str(first["review"]["subject_digest"]),
                ),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ConfigurationError, "replace=True"):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=_doctor_fingerprints(config),
            )
        self.assertEqual(load_evaluator_certification(config), first)
        rejected = record_evaluator_certification(
            config,
            review_path,
            fingerprints=_doctor_fingerprints(config),
            replace=True,
        )
        self.assertFalse(rejected["certified"])
        summary = inspect_evaluator_certification(config)
        self.assertEqual(summary["status"], "REJECTED")
        self.assertTrue(summary["current"])
        self.assertEqual(summary["reason"], "rejected")
        with self.assertRaises(EvaluatorCertificationError) as caught:
            require_evaluator_certification(config)
        self.assertEqual(caught.exception.details["reason"], "rejected")

        review_path.write_text(
            json.dumps(
                _review(
                    independent=False,
                    subject_digest=str(first["review"]["subject_digest"]),
                ),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        non_independent = record_evaluator_certification(
            config,
            review_path,
            fingerprints=_doctor_fingerprints(config),
            replace=True,
        )
        self.assertFalse(non_independent["certified"])

    def test_record_requires_doctor_adapter_and_live_doctor_detects_adapter_drift(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        first_doctor = _doctor_fingerprints(config, adapter_revision="v1")
        review_path = self.write_review(
            project,
            _review(
                subject_digest=str(
                    build_evaluator_review_subject(
                        config,
                        fingerprints=first_doctor,
                    )["digest"]
                )
            ),
        )

        with self.assertRaisesRegex(ConfigurationError, "adapter binding"):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=project_fingerprints(config),
            )

        invalid_doctor = copy.deepcopy(first_doctor)
        invalid_doctor["compatibility_digest"] = "0" * 64
        with self.assertRaisesRegex(IntegrityError, "effective compatibility"):
            record_evaluator_certification(config, review_path, fingerprints=invalid_doctor)
        artifact = record_evaluator_certification(config, review_path, fingerprints=first_doctor)
        self.assertEqual(inspect_evaluator_certification(config)["status"], "CERTIFIED")
        self.assertEqual(
            inspect_evaluator_certification(config, fingerprints=first_doctor)["status"],
            "CERTIFIED",
        )
        self.assertEqual(
            inspect_evaluator_certification(config, fingerprints=project_fingerprints(config))[
                "status"
            ],
            "CERTIFIED",
        )

        second_doctor = _doctor_fingerprints(config, adapter_revision="v2")
        drifted = inspect_evaluator_certification(config, fingerprints=second_doctor)
        self.assertEqual(drifted["status"], "STALE")
        self.assertNotEqual(drifted["bindings"]["adapter"], second_doctor["adapter"]["digest"])
        self.assertEqual(artifact["bindings"]["adapter"], first_doctor["adapter"])

    def test_every_bound_surface_and_agent_spec_can_make_a_certificate_stale(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        record_evaluator_certification(
            config,
            self.write_review(project, _review()),
            fingerprints=_doctor_fingerprints(config),
        )

        brief = project / ".research-os" / "research-brief.md"
        brief.write_text(brief.read_text(encoding="utf-8") + "\nchange\n", encoding="utf-8")
        summary = inspect_evaluator_certification(config)
        self.assertEqual(summary["status"], "STALE")
        self.assertFalse(summary["current"])
        self.assertEqual(summary["reason"], "stale")
        self.assertIn("EVALUATOR_CERTIFICATION_STALE", summary["blockers"])

        # A supplied fingerprint snapshot is accepted only when it still
        # exactly matches live project inputs.
        current = copy.deepcopy(project_fingerprints(config))
        record_evaluator_certification(
            config,
            self.write_review(project, _review()),
            fingerprints=_doctor_fingerprints(config),
            replace=True,
        )
        current = copy.deepcopy(project_fingerprints(config))
        current["environment"]["digest"] = "0" * 64
        with self.assertRaisesRegex(IntegrityError, "disagree with current"):
            inspect_evaluator_certification(config, fingerprints=current)

    def test_artifact_is_atomic_private_and_excluded_from_snapshots(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        review_path = self.write_review(project, _review())
        config = load_project_config(project)
        before = hash_tree(project)

        record_evaluator_certification(
            config, review_path, fingerprints=_doctor_fingerprints(config)
        )
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        self.assertEqual(stat.S_IMODE(certificate.stat().st_mode), 0o600)
        self.assertEqual(certificate.stat().st_nlink, 1)
        self.assertEqual(hash_tree(project), before)
        self.assertFalse(any(path.name.endswith(".tmp") for path in certificate.parent.iterdir()))

        manager = WorkspaceManager(config)
        handle = manager.create("certification_copy_test")
        try:
            self.assertFalse((handle.path / EVALUATOR_CERTIFICATION_RELATIVE).exists())
        finally:
            manager.cleanup(handle)
            manager.close()

    def test_writable_or_multiply_linked_certificates_fail_closed(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        review_path = self.write_review(project, _review())
        record_evaluator_certification(
            config, review_path, fingerprints=_doctor_fingerprints(config)
        )
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE

        certificate.chmod(0o660)
        with self.assertRaisesRegex(IntegrityError, "group- or world-writable"):
            load_evaluator_certification(config)
        with self.assertRaisesRegex(IntegrityError, "group- or world-writable"):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=_doctor_fingerprints(config),
                replace=True,
            )

        certificate.chmod(0o600)
        second_link = certificate.with_name("evaluator-certification-linked.json")
        second_link.hardlink_to(certificate)
        with self.assertRaisesRegex(IntegrityError, "exactly one hard link"):
            load_evaluator_certification(config)
        with self.assertRaisesRegex(IntegrityError, "exactly one hard link"):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=_doctor_fingerprints(config),
                replace=True,
            )

    def test_tampering_and_unsafe_artifact_paths_fail_integrity(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        record_evaluator_certification(
            config,
            self.write_review(project, _review()),
            fingerprints=_doctor_fingerprints(config),
        )
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE

        value = json.loads(certificate.read_text(encoding="utf-8"))
        value["review"]["summary"] = "tampered"
        certificate.write_text(json.dumps(value) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(IntegrityError, "review digest"):
            load_evaluator_certification(config)

        certificate.unlink()
        outside = project.parent / "outside.json"
        outside.write_text("{}\n", encoding="utf-8")
        certificate.symlink_to(outside)
        with self.assertRaisesRegex(IntegrityError, "regular file"):
            load_evaluator_certification(config)

    def test_recombined_passing_review_and_current_bindings_is_rejected(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        first_doctor = _doctor_fingerprints(config)
        first = record_evaluator_certification(
            config,
            self.write_review(project, _review()),
            fingerprints=first_doctor,
        )

        evaluator = project / "evaluator.py"
        evaluator.write_text(
            evaluator.read_text(encoding="utf-8") + "\n# new reviewed binding\n",
            encoding="utf-8",
        )
        second_doctor = _doctor_fingerprints(config)
        second_subject = build_evaluator_review_subject(
            config,
            fingerprints=second_doctor,
        )
        second = record_evaluator_certification(
            config,
            self.write_review(
                project,
                _review(subject_digest=str(second_subject["digest"])),
            ),
            fingerprints=second_doctor,
            replace=True,
        )

        recombined = copy.deepcopy(second)
        recombined["review"] = copy.deepcopy(first["review"])
        recombined["review_digest"] = sha256_json(recombined["review"])
        unsigned = dict(recombined)
        unsigned.pop("digest")
        recombined["digest"] = sha256_json(unsigned)
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        certificate.write_text(
            json.dumps(recombined, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        with self.assertRaisesRegex(IntegrityError, "subject does not match"):
            load_evaluator_certification(config)

    def test_malformed_review_never_replaces_a_current_certificate(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        review_path = self.write_review(project, _review())
        original = record_evaluator_certification(
            config, review_path, fingerprints=_doctor_fingerprints(config)
        )

        review_path.write_text('{"schema_version":1,"schema_version":1}\n', encoding="utf-8")
        with self.assertRaises(ConfigurationError):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=_doctor_fingerprints(config),
                replace=True,
            )
        self.assertEqual(load_evaluator_certification(config), original)

    def test_old_review_cannot_be_replayed_after_bound_input_drift(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        review_path = self.write_review(project, _review())
        original = record_evaluator_certification(
            config,
            review_path,
            fingerprints=_doctor_fingerprints(config),
        )
        original_bytes = (project / EVALUATOR_CERTIFICATION_RELATIVE).read_bytes()

        evaluator = project / "evaluator.py"
        evaluator.write_text(
            evaluator.read_text(encoding="utf-8") + "\n# reviewed drift\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ConfigurationError, "subject_digest"):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=_doctor_fingerprints(config),
                replace=True,
            )
        self.assertEqual(
            (project / EVALUATOR_CERTIFICATION_RELATIVE).read_bytes(),
            original_bytes,
        )
        self.assertEqual(load_evaluator_certification(config), original)

    def test_cached_source_fingerprints_cannot_bypass_live_drift(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        cached = copy.deepcopy(project_fingerprints(config))
        record_evaluator_certification(
            config,
            self.write_review(project, _review()),
            fingerprints=_doctor_fingerprints(config),
        )
        brief = project / ".research-os" / "research-brief.md"
        brief.write_text(brief.read_text(encoding="utf-8") + "\ndrift\n", encoding="utf-8")
        with self.assertRaisesRegex(IntegrityError, "disagree with current"):
            require_evaluator_certification(config, fingerprints=cached)

    def test_untrusted_root_or_control_permissions_fail_closed(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        record_evaluator_certification(
            config,
            self.write_review(project, _review()),
            fingerprints=_doctor_fingerprints(config),
        )
        original_root_mode = stat.S_IMODE(project.stat().st_mode)
        project.chmod(original_root_mode | 0o020)
        try:
            with self.assertRaisesRegex(IntegrityError, "project root.*writable"):
                load_evaluator_certification(config)
        finally:
            project.chmod(original_root_mode)

        control = project / ".research-os"
        original_control_mode = stat.S_IMODE(control.stat().st_mode)
        control.chmod(original_control_mode | 0o002)
        try:
            with self.assertRaisesRegex(IntegrityError, "control directory.*writable"):
                load_evaluator_certification(config)
        finally:
            control.chmod(original_control_mode)

    def test_final_freshness_failure_preserves_prior_certificate_inode(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        review_path = self.write_review(project, _review())
        doctor = _doctor_fingerprints(config)
        original = record_evaluator_certification(
            config,
            review_path,
            fingerprints=doctor,
        )
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        before_identity = (certificate.stat().st_dev, certificate.stat().st_ino)
        live = project_fingerprints(config)
        drifted = copy.deepcopy(live)
        drifted["environment"]["digest"] = "f" * 64
        with (
            mock.patch(
                "research_os.certification.project_fingerprints",
                side_effect=[live, drifted],
            ),
            self.assertRaisesRegex(IntegrityError, "disagree with current"),
        ):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=doctor,
                replace=True,
            )
        self.assertEqual(
            (certificate.stat().st_dev, certificate.stat().st_ino),
            before_identity,
        )
        self.assertEqual(load_evaluator_certification(config), original)

    def test_fresh_doctor_adapter_drift_after_publication_never_reports_success(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        first_doctor = _doctor_fingerprints(config, adapter_revision="v1")
        second_doctor = _doctor_fingerprints(config, adapter_revision="v2")
        review_path = self.write_review(
            project,
            _review(
                subject_digest=str(
                    build_evaluator_review_subject(
                        config,
                        fingerprints=first_doctor,
                    )["digest"]
                )
            ),
        )
        refreshes = iter((first_doctor, second_doctor))

        with self.assertRaisesRegex(IntegrityError, "doctor inputs changed"):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=first_doctor,
                fresh_fingerprints=lambda: next(refreshes),
            )

        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        self.assertFalse(certificate.exists())
        self.assertEqual(inspect_evaluator_certification(config)["status"], "MISSING")

    def test_reentrant_doctor_callback_fails_fast_instead_of_deadlocking(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        doctor = _doctor_fingerprints(config)
        review_path = self.write_review(project, _review())
        service = ResearchService(project)
        outcomes: list[BaseException] = []

        def invoke() -> None:
            try:
                record_evaluator_certification(
                    config,
                    review_path,
                    fingerprints=doctor,
                    fresh_fingerprints=lambda: service.doctor().fingerprints,
                )
            except BaseException as exc:
                outcomes.append(exc)

        worker = threading.Thread(target=invoke, daemon=True)
        worker.start()
        worker.join(timeout=2.0)

        self.assertFalse(worker.is_alive(), "certification callback self-deadlocked")
        self.assertEqual(len(outcomes), 1)
        self.assertIsInstance(outcomes[0], IntegrityError)
        self.assertIn("re-entry would deadlock", str(outcomes[0]))
        self.assertFalse((project / EVALUATOR_CERTIFICATION_RELATIVE).exists())

    def test_source_drift_inside_first_publication_link_removes_certificate(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        doctor = _doctor_fingerprints(config)
        review_path = self.write_review(project, _review())
        evaluator = project / "evaluator.py"
        original_link = os.link

        def link_then_drift(source, destination, *args, **kwargs):
            result = original_link(source, destination, *args, **kwargs)
            if destination == EVALUATOR_CERTIFICATION_RELATIVE.name:
                evaluator.write_text(
                    evaluator.read_text(encoding="utf-8") + "\n# publication drift\n",
                    encoding="utf-8",
                )
            return result

        with (
            mock.patch(
                "research_os.certification.os.link",
                side_effect=link_then_drift,
            ),
            self.assertRaisesRegex(IntegrityError, "doctor inputs changed"),
        ):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=doctor,
            )

        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        self.assertFalse(certificate.exists())
        self.assertFalse(
            any(
                path.name.endswith((".tmp", ".rollback"))
                for path in certificate.parent.iterdir()
            )
        )

    def test_source_drift_inside_replace_restores_prior_inode_and_bytes(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        doctor = _doctor_fingerprints(config)
        review_path = self.write_review(project, _review())
        original = record_evaluator_certification(
            config,
            review_path,
            fingerprints=doctor,
        )
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        original_identity = (certificate.stat().st_dev, certificate.stat().st_ino)
        original_bytes = certificate.read_bytes()
        evaluator = project / "evaluator.py"
        original_replace = os.replace
        drifted = False

        def replace_then_drift(source, destination, *args, **kwargs):
            nonlocal drifted
            result = original_replace(source, destination, *args, **kwargs)
            if (
                destination == EVALUATOR_CERTIFICATION_RELATIVE.name
                and str(source).endswith(".tmp")
                and not drifted
            ):
                drifted = True
                evaluator.write_text(
                    evaluator.read_text(encoding="utf-8") + "\n# replace drift\n",
                    encoding="utf-8",
                )
            return result

        with (
            mock.patch(
                "research_os.certification.os.replace",
                side_effect=replace_then_drift,
            ),
            self.assertRaisesRegex(IntegrityError, "doctor inputs changed"),
        ):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=doctor,
                replace=True,
            )

        self.assertTrue(drifted)
        self.assertEqual(
            (certificate.stat().st_dev, certificate.stat().st_ino),
            original_identity,
        )
        self.assertEqual(certificate.read_bytes(), original_bytes)
        self.assertEqual(load_evaluator_certification(config), original)
        self.assertFalse(
            any(
                path.name.endswith((".tmp", ".rollback"))
                for path in certificate.parent.iterdir()
            )
        )

    def test_transaction_files_are_invisible_to_fresh_doctor_tree_hash(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        doctor = _doctor_fingerprints(config)
        review_path = self.write_review(project, _review())
        expected_tree = hash_tree(project)
        observed_trees: list[str] = []

        def refresh():
            observed_trees.append(hash_tree(project))
            return _refresh_doctor_fingerprints(config, doctor)

        record_evaluator_certification(
            config,
            review_path,
            fingerprints=doctor,
            fresh_fingerprints=refresh,
        )
        record_evaluator_certification(
            config,
            review_path,
            fingerprints=doctor,
            fresh_fingerprints=refresh,
            replace=True,
        )

        self.assertEqual(observed_trees, [expected_tree] * 4)

    def test_provisional_readback_failure_restores_prior_certificate(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        doctor = _doctor_fingerprints(config)
        review_path = self.write_review(project, _review())
        original = record_evaluator_certification(
            config,
            review_path,
            fingerprints=doctor,
        )
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        original_identity = (certificate.stat().st_dev, certificate.stat().st_ino)
        original_bytes = certificate.read_bytes()

        with (
            mock.patch(
                "research_os.certification._read_certification_bytes",
                return_value=b"{}\n",
            ),
            self.assertRaisesRegex(IntegrityError, "bytes changed before commit"),
        ):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=doctor,
                replace=True,
            )

        self.assertEqual(
            (certificate.stat().st_dev, certificate.stat().st_ino),
            original_identity,
        )
        self.assertEqual(certificate.read_bytes(), original_bytes)
        self.assertEqual(load_evaluator_certification(config), original)

    def test_publication_syscall_success_then_interrupt_is_rolled_back(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        doctor = _doctor_fingerprints(config)
        review_path = self.write_review(project, _review())
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        original_link = os.link

        def link_then_interrupt(source, destination, *args, **kwargs):
            original_link(source, destination, *args, **kwargs)
            raise KeyboardInterrupt("injected after link")

        with (
            mock.patch(
                "research_os.certification.os.link",
                side_effect=link_then_interrupt,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=doctor,
            )
        self.assertFalse(certificate.exists())

        original = record_evaluator_certification(
            config,
            review_path,
            fingerprints=doctor,
        )
        original_identity = (certificate.stat().st_dev, certificate.stat().st_ino)
        original_bytes = certificate.read_bytes()
        original_replace = os.replace
        interrupted = False

        def replace_then_interrupt(source, destination, *args, **kwargs):
            nonlocal interrupted
            result = original_replace(source, destination, *args, **kwargs)
            if str(source).endswith(".tmp") and not interrupted:
                interrupted = True
                raise KeyboardInterrupt("injected after replace")
            return result

        with (
            mock.patch(
                "research_os.certification.os.replace",
                side_effect=replace_then_interrupt,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=doctor,
                replace=True,
            )
        self.assertTrue(interrupted)
        self.assertEqual(
            (certificate.stat().st_dev, certificate.stat().st_ino),
            original_identity,
        )
        self.assertEqual(certificate.read_bytes(), original_bytes)
        self.assertEqual(load_evaluator_certification(config), original)

    def test_rollback_link_success_then_interrupt_preserves_prior_certificate(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        doctor = _doctor_fingerprints(config)
        review_path = self.write_review(project, _review())
        original = record_evaluator_certification(
            config,
            review_path,
            fingerprints=doctor,
        )
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        original_identity = (certificate.stat().st_dev, certificate.stat().st_ino)
        original_bytes = certificate.read_bytes()
        original_link = os.link

        def link_then_interrupt(source, destination, *args, **kwargs):
            original_link(source, destination, *args, **kwargs)
            raise KeyboardInterrupt("injected after rollback link")

        with (
            mock.patch(
                "research_os.certification.os.link",
                side_effect=link_then_interrupt,
            ),
            self.assertRaises(KeyboardInterrupt),
        ):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=doctor,
                replace=True,
            )

        self.assertEqual(
            (certificate.stat().st_dev, certificate.stat().st_ino),
            original_identity,
        )
        self.assertEqual(certificate.stat().st_nlink, 1)
        self.assertEqual(certificate.read_bytes(), original_bytes)
        self.assertEqual(load_evaluator_certification(config), original)
        self.assertFalse(
            any(path.name.endswith(".rollback") for path in certificate.parent.iterdir())
        )

    def test_committed_replace_survives_cleanup_unlink_and_fsync_faults(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        doctor = _doctor_fingerprints(config)
        review_path = self.write_review(project, _review())
        record_evaluator_certification(
            config,
            review_path,
            fingerprints=doctor,
        )
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        first_identity = (certificate.stat().st_dev, certificate.stat().st_ino)
        original_unlink = os.unlink
        interrupted = False

        def unlink_then_interrupt(path, *args, **kwargs):
            nonlocal interrupted
            result = original_unlink(path, *args, **kwargs)
            if str(path).endswith(".rollback") and not interrupted:
                interrupted = True
                raise KeyboardInterrupt("injected after cleanup unlink")
            return result

        with mock.patch(
            "research_os.certification.os.unlink",
            side_effect=unlink_then_interrupt,
        ):
            committed = record_evaluator_certification(
                config,
                review_path,
                fingerprints=doctor,
                replace=True,
            )
        second_identity = (certificate.stat().st_dev, certificate.stat().st_ino)
        self.assertTrue(interrupted)
        self.assertNotEqual(second_identity, first_identity)
        self.assertEqual(load_evaluator_certification(config), committed)

        original_fsync = os.fsync
        directory_syncs = 0

        def fail_cleanup_fsync(descriptor):
            nonlocal directory_syncs
            result = original_fsync(descriptor)
            if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                directory_syncs += 1
                if directory_syncs == 4:
                    raise KeyboardInterrupt("injected cleanup fsync interrupt")
            return result

        with mock.patch(
            "research_os.certification.os.fsync",
            side_effect=fail_cleanup_fsync,
        ):
            committed_again = record_evaluator_certification(
                config,
                review_path,
                fingerprints=doctor,
                replace=True,
            )
        self.assertEqual(directory_syncs, 4)
        self.assertNotEqual(
            (certificate.stat().st_dev, certificate.stat().st_ino),
            second_identity,
        )
        self.assertEqual(load_evaluator_certification(config), committed_again)

        third_identity = (certificate.stat().st_dev, certificate.stat().st_ino)
        original_stat = os.stat
        rollback_stats = 0

        def fail_cleanup_stat(path, *args, **kwargs):
            nonlocal rollback_stats
            if str(path).endswith(".rollback"):
                rollback_stats += 1
                if rollback_stats == 2:
                    raise OSError("injected cleanup stat failure")
            return original_stat(path, *args, **kwargs)

        with mock.patch(
            "research_os.certification.os.stat",
            side_effect=fail_cleanup_stat,
        ):
            committed_after_stat_fault = record_evaluator_certification(
                config,
                review_path,
                fingerprints=doctor,
                replace=True,
            )
        self.assertGreaterEqual(rollback_stats, 2)
        self.assertNotEqual(
            (certificate.stat().st_dev, certificate.stat().st_ino),
            third_identity,
        )
        self.assertEqual(
            load_evaluator_certification(config),
            committed_after_stat_fault,
        )

    def test_directory_fsync_failure_rolls_back_first_and_replace_publication(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        doctor = _doctor_fingerprints(config)
        review_path = self.write_review(project, _review())
        certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
        original_fsync = os.fsync

        def failing_directory_fsync(fail_at: int = 1):
            directory_syncs = 0

            def fsync_then_fail(descriptor):
                nonlocal directory_syncs
                result = original_fsync(descriptor)
                if stat.S_ISDIR(os.fstat(descriptor).st_mode):
                    directory_syncs += 1
                    if directory_syncs == fail_at:
                        raise OSError("injected directory fsync failure")
                return result

            return fsync_then_fail

        with (
            mock.patch(
                "research_os.certification.os.fsync",
                side_effect=failing_directory_fsync(2),
            ),
            self.assertRaisesRegex(IntegrityError, "cannot safely write"),
        ):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=doctor,
            )
        self.assertFalse(certificate.exists())

        original = record_evaluator_certification(
            config,
            review_path,
            fingerprints=doctor,
        )
        original_identity = (certificate.stat().st_dev, certificate.stat().st_ino)
        original_bytes = certificate.read_bytes()
        with (
            mock.patch(
                "research_os.certification.os.fsync",
                side_effect=failing_directory_fsync(2),
            ),
            self.assertRaisesRegex(IntegrityError, "cannot safely write"),
        ):
            record_evaluator_certification(
                config,
                review_path,
                fingerprints=doctor,
                replace=True,
            )
        self.assertEqual(
            (certificate.stat().st_dev, certificate.stat().st_ino),
            original_identity,
        )
        self.assertEqual(certificate.read_bytes(), original_bytes)
        self.assertEqual(load_evaluator_certification(config), original)

    def test_legacy_ignore_migration_is_idempotent_and_review_must_be_external(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        config = load_project_config(project)
        ignored = project / ".research-os" / ".gitignore"
        ignored.write_text("runtime/\ncustom-entry\n", encoding="utf-8")
        self.assertTrue(ensure_certification_gitignore(config))
        self.assertFalse(ensure_certification_gitignore(config))
        self.assertEqual(
            ignored.read_text(encoding="utf-8").splitlines(),
            ["runtime/", "custom-entry", "evaluator-certification.json"],
        )

        doctor = _doctor_fingerprints(config)
        subject = build_evaluator_review_subject(config, fingerprints=doctor)
        in_project = project / "review.json"
        in_project.write_text(
            json.dumps(_review(subject_digest=str(subject["digest"]))) + "\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ConfigurationError, "outside the project"):
            record_evaluator_certification(
                config,
                in_project,
                fingerprints=doctor,
            )

    def test_scaffold_declares_preregistration_and_reserves_certificate_path(self):
        temporary, project = self.make_project()
        self.addCleanup(temporary.cleanup)
        project_text = (project / ".research-os" / "project.toml").read_text(encoding="utf-8")
        self.assertIn('".research-os/research-brief.md"', project_text)
        self.assertIn('".research-os/candidate.schema.json"', project_text)
        brief = (project / ".research-os" / "research-brief.md").read_text(encoding="utf-8")
        for heading in (
            "## Evaluation certification",
            "## Universe preregistration",
            "## Holdout boundary",
            "## Golden controls",
            "## Hypothesis classes and failure threshold",
            "## Graph proposal policy",
        ):
            self.assertIn(heading, brief)
        ignored = (project / ".research-os" / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("evaluator-certification.json", ignored.splitlines())
        self.assertFalse((project / EVALUATOR_CERTIFICATION_RELATIVE).exists())

    def test_certificate_path_cannot_be_declared_as_a_project_surface(self):
        for group in ("mutable", "protected", "evidence"):
            with self.subTest(group=group):
                temporary, project = self.make_project()
                self.addCleanup(temporary.cleanup)
                certificate = project / EVALUATOR_CERTIFICATION_RELATIVE
                certificate.write_text("{}\n", encoding="utf-8")
                project_file = project / ".research-os" / "project.toml"
                text = project_file.read_text(encoding="utf-8")
                if group == "mutable":
                    text = text.replace(
                        'mutable = ["experiment.json"]',
                        'mutable = [".research-os/evaluator-certification.json"]',
                    )
                elif group == "protected":
                    marker = '"evaluator.py"]\nevidence ='
                    replacement = (
                        '"evaluator.py", ".research-os/evaluator-certification.json"]\nevidence ='
                    )
                    text = text.replace(marker, replacement)
                else:
                    text = text.replace(
                        'evidence = ["evaluator.py"]',
                        'evidence = [".research-os/evaluator-certification.json"]',
                    )
                project_file.write_text(text, encoding="utf-8")
                with self.assertRaisesRegex(
                    ConfigurationError, "control data|agent-transient path"
                ):
                    load_project_config(project)


if __name__ == "__main__":
    unittest.main()
