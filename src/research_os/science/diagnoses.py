"""Canonical immutable Diagnosis bodies and event payloads."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from research_os.contracts.common import normalize_json_value, sha256_json
from research_os.contracts.results import GateEvaluation
from research_os.errors import LifecycleError
from research_os.kernel.ids import stable_id, validate_namespaced_id
from research_os.kernel.lifecycle import TERMINAL_STATES, coerce_state

from .contracts import _array, _digest, _fail, _object, _text

DIAGNOSIS_SCHEMA_VERSION = 1
DIAGNOSIS_FAILURE_TYPES = frozenset(
    {
        "mechanism",
        "implementation",
        "evidence",
        "constraint",
        "operational",
        "supported",
    }
)
DIAGNOSIS_RECOMMENDATIONS = frozenset(
    {
        "stop",
        "change_control",
        "explore",
        "ablate",
        "exploit",
        "replicate",
        "retry",
    }
)
MAX_DIAGNOSIS_NARRATIVE_UTF8_BYTES = 16_384

_DIAGNOSIS_KEYS = {
    "diagnosis_schema_version",
    "generation_id",
    "compatibility_digest",
    "experiment_id",
    "proposal_id",
    "proposal_digest",
    "hypothesis_class_id",
    "evaluation_scope_id",
    "terminal_evidence",
    "artifact_evidence",
    "observation",
    "interpretation",
    "failure_type",
    "falsifier",
    "recommendation",
    "authorized_action",
}
_TERMINAL_EVIDENCE_KEYS = {"experiment_id", "event_id", "event_hash"}
_ARTIFACT_EVIDENCE_KEYS = {
    "artifact_id",
    "artifact_digest",
    "event_id",
    "event_hash",
}
_OBSERVATION_KEYS = {
    "terminal_status",
    "reason_code",
    "verified",
    "retryable",
    "primary_metric",
    "candidate_value",
    "baseline_value",
    "improvement",
    "promotion_margin",
    "gate_evaluations",
}
_DIAGNOSIS_EVENT_PAYLOAD_KEYS = {
    "science_state_version",
    "generation_id",
    "study_contract_digest",
    "evaluation_seal_digest",
    "compatibility_digest",
    "diagnosis",
    "diagnosis_digest",
    "diagnosis_id",
    "authorized_action",
}


def _literal_version(value: Any, *, path: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value != 1:
        raise _fail("DIAGNOSIS_INVALID", f"{path} must equal literal integer 1", path=path)
    return 1


def _literal_boolean(value: Any, *, path: str) -> bool:
    if not isinstance(value, bool):
        raise _fail("DIAGNOSIS_INVALID", f"{path} must be a literal boolean", path=path)
    return value


def _null_authority(value: Any, *, path: str) -> None:
    if value is not None:
        raise _fail("DIAGNOSIS_INVALID", f"{path} must be literal null", path=path)
    return None


def _namespaced_id(value: Any, namespace: str, *, path: str) -> str:
    text = _text(value, path=path, code="DIAGNOSIS_INVALID")
    try:
        identifier = validate_namespaced_id(text, namespace)
    except (TypeError, ValueError) as exc:
        raise _fail(
            "DIAGNOSIS_INVALID",
            f"{path} must be a {namespace} ID",
            path=path,
        ) from exc
    return identifier


def _narrative(value: Any, *, path: str) -> str:
    text = _text(value, path=path, code="DIAGNOSIS_INVALID")
    if len(text.encode("utf-8")) > MAX_DIAGNOSIS_NARRATIVE_UTF8_BYTES:
        raise _fail(
            "DIAGNOSIS_INVALID",
            f"{path} must not exceed {MAX_DIAGNOSIS_NARRATIVE_UTF8_BYTES} UTF-8 bytes",
            path=path,
        )
    return text


def _nullable_text(value: Any, *, path: str) -> str | None:
    if value is None:
        return None
    return _text(value, path=path, code="DIAGNOSIS_INVALID")


def _nullable_number(value: Any, *, path: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _fail(
            "DIAGNOSIS_INVALID",
            f"{path} must be a finite canonical JSON number or null",
            path=path,
        )
    try:
        normalized = normalize_json_value(value)
    except (TypeError, ValueError) as exc:
        raise _fail(
            "DIAGNOSIS_INVALID",
            f"{path} must be a finite canonical JSON number or null",
            path=path,
        ) from exc
    assert isinstance(normalized, (int, float)) and not isinstance(normalized, bool)
    return normalized


def normalize_terminal_status(
    value: Any,
    *,
    path: str = "$.terminal_status",
) -> str:
    """Return the kernel's canonical lifecycle spelling for one status value."""

    if not isinstance(value, str) or not value.strip():
        raise _fail(
            "DIAGNOSIS_INVALID",
            f"{path} must be a non-empty lifecycle status",
            path=path,
        )
    if any(0xD800 <= ord(character) <= 0xDFFF for character in value):
        raise _fail(
            "DIAGNOSIS_INVALID",
            f"{path} must contain Unicode scalar values",
            path=path,
        )
    try:
        return coerce_state(value).value
    except (LifecycleError, TypeError, ValueError) as exc:
        raise _fail(
            "DIAGNOSIS_INVALID",
            f"{path} is not a recognized lifecycle status",
            path=path,
        ) from exc


def default_terminal_reason_code(event_type: Any) -> str:
    """Return the frozen fallback reason for a generic terminal event type."""

    text = _text(event_type, path="$.event_type", code="DIAGNOSIS_INVALID")
    normalized = text.upper().replace("-", "_").replace(" ", "_")
    reasons = {
        "EXPERIMENT_STATUS_CHANGED": "STATUS_CHANGED",
        "EXPERIMENT_TERMINATED": "TERMINATED",
    }
    try:
        return reasons[normalized]
    except KeyError as exc:
        raise _fail(
            "DIAGNOSIS_INVALID",
            "$.event_type does not have a terminal reason fallback",
            path="$.event_type",
        ) from exc


@dataclass(frozen=True, slots=True)
class TerminalEvidenceRef:
    """Exact identity of the canonical terminal Event bound by a Diagnosis."""

    experiment_id: str
    event_id: str
    event_hash: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "TerminalEvidenceRef":
        value = _object(
            raw,
            _TERMINAL_EVIDENCE_KEYS,
            path="$.terminal_evidence",
            code="DIAGNOSIS_INVALID",
        )
        return cls(
            experiment_id=_namespaced_id(
                value["experiment_id"],
                "experiment",
                path="$.terminal_evidence.experiment_id",
            ),
            event_id=_namespaced_id(
                value["event_id"],
                "event",
                path="$.terminal_evidence.event_id",
            ),
            event_hash=_digest(
                value["event_hash"],
                path="$.terminal_evidence.event_hash",
                code="DIAGNOSIS_INVALID",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment_id": self.experiment_id,
            "event_id": self.event_id,
            "event_hash": self.event_hash,
        }


@dataclass(frozen=True, slots=True)
class ArtifactEvidenceRef:
    """Exact identity of one canonical artifact record Event."""

    artifact_id: str
    artifact_digest: str
    event_id: str
    event_hash: str

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any], *, index: int = 0) -> "ArtifactEvidenceRef":
        path = f"$.artifact_evidence[{index}]"
        value = _object(
            raw,
            _ARTIFACT_EVIDENCE_KEYS,
            path=path,
            code="DIAGNOSIS_INVALID",
        )
        return cls(
            artifact_id=_namespaced_id(
                value["artifact_id"],
                "artifact",
                path=f"{path}.artifact_id",
            ),
            artifact_digest=_digest(
                value["artifact_digest"],
                path=f"{path}.artifact_digest",
                code="DIAGNOSIS_INVALID",
            ),
            event_id=_namespaced_id(
                value["event_id"],
                "event",
                path=f"{path}.event_id",
            ),
            event_hash=_digest(
                value["event_hash"],
                path=f"{path}.event_hash",
                code="DIAGNOSIS_INVALID",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_digest": self.artifact_digest,
            "event_id": self.event_id,
            "event_hash": self.event_hash,
        }


@dataclass(frozen=True, slots=True)
class DiagnosisObservation:
    """Exact kernel-derived observation preserved by one Diagnosis."""

    terminal_status: str
    reason_code: str
    verified: bool
    retryable: bool
    primary_metric: str | None
    candidate_value: int | float | None
    baseline_value: int | float | None
    improvement: int | float | None
    promotion_margin: int | float | None
    gate_evaluations: tuple[GateEvaluation, ...]

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "DiagnosisObservation":
        code = "DIAGNOSIS_INVALID"
        value = _object(raw, _OBSERVATION_KEYS, path="$.observation", code=code)

        status_raw = _text(
            value["terminal_status"],
            path="$.observation.terminal_status",
            code=code,
        )
        terminal_status = normalize_terminal_status(
            status_raw,
            path="$.observation.terminal_status",
        )
        if terminal_status != status_raw:
            raise _fail(
                code,
                "$.observation.terminal_status must use its canonical spelling",
                path="$.observation.terminal_status",
            )
        if coerce_state(terminal_status) not in TERMINAL_STATES:
            raise _fail(
                code,
                "$.observation.terminal_status must be terminal",
                path="$.observation.terminal_status",
            )

        evaluations: list[GateEvaluation] = []
        for index, item in enumerate(
            _array(
                value["gate_evaluations"],
                path="$.observation.gate_evaluations",
                code=code,
                nonempty=False,
            )
        ):
            path = f"$.observation.gate_evaluations[{index}]"
            gate_raw = _object(
                item,
                {
                    "id",
                    "metric",
                    "role",
                    "operator",
                    "threshold",
                    "unit",
                    "scale",
                    "observed",
                    "signed_slack",
                    "normalized_slack",
                    "passed",
                },
                path=path,
                code=code,
            )
            if not isinstance(gate_raw["passed"], bool):
                raise _fail(code, f"{path}.passed must be a literal boolean", path=f"{path}.passed")
            try:
                evaluation = GateEvaluation.from_mapping(gate_raw)
            except (TypeError, ValueError) as exc:
                raise _fail(code, f"{path} is invalid: {exc}", path=path) from exc
            if evaluation.to_dict() != dict(gate_raw):
                raise _fail(code, f"{path} must be canonical", path=path)
            evaluations.append(evaluation)

        gate_ids = tuple(item.id for item in evaluations)
        if len(set(gate_ids)) != len(gate_ids):
            raise _fail(
                code,
                "gate evaluation IDs must be unique",
                path="$.observation.gate_evaluations",
            )
        if gate_ids != tuple(sorted(gate_ids)):
            raise _fail(
                code,
                "gate evaluations must be ordered by ID",
                path="$.observation.gate_evaluations",
            )

        observation = cls(
            terminal_status=terminal_status,
            reason_code=_text(
                value["reason_code"],
                path="$.observation.reason_code",
                code=code,
            ),
            verified=_literal_boolean(
                value["verified"],
                path="$.observation.verified",
            ),
            retryable=_literal_boolean(
                value["retryable"],
                path="$.observation.retryable",
            ),
            primary_metric=_nullable_text(
                value["primary_metric"],
                path="$.observation.primary_metric",
            ),
            candidate_value=_nullable_number(
                value["candidate_value"],
                path="$.observation.candidate_value",
            ),
            baseline_value=_nullable_number(
                value["baseline_value"],
                path="$.observation.baseline_value",
            ),
            improvement=_nullable_number(
                value["improvement"],
                path="$.observation.improvement",
            ),
            promotion_margin=_nullable_number(
                value["promotion_margin"],
                path="$.observation.promotion_margin",
            ),
            gate_evaluations=tuple(evaluations),
        )
        try:
            sha256_json(observation.to_dict())
        except (TypeError, ValueError) as exc:  # pragma: no cover - field validators cover it
            raise _fail(code, f"observation is not canonical JSON: {exc}", path="$.observation") from exc
        return observation

    def to_dict(self) -> dict[str, Any]:
        return {
            "terminal_status": self.terminal_status,
            "reason_code": self.reason_code,
            "verified": self.verified,
            "retryable": self.retryable,
            "primary_metric": self.primary_metric,
            "candidate_value": self.candidate_value,
            "baseline_value": self.baseline_value,
            "improvement": self.improvement,
            "promotion_margin": self.promotion_margin,
            "gate_evaluations": [item.to_dict() for item in self.gate_evaluations],
        }


@dataclass(frozen=True, slots=True)
class Diagnosis:
    """One immutable interpretation bound to exact terminal evidence."""

    diagnosis_schema_version: int
    generation_id: str
    compatibility_digest: str
    experiment_id: str
    proposal_id: str
    proposal_digest: str
    hypothesis_class_id: str
    evaluation_scope_id: str
    terminal_evidence: TerminalEvidenceRef
    artifact_evidence: tuple[ArtifactEvidenceRef, ...]
    observation: DiagnosisObservation
    interpretation: str
    failure_type: str
    falsifier: str
    recommendation: str
    authorized_action: None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "Diagnosis":
        code = "DIAGNOSIS_INVALID"
        root = _object(raw, _DIAGNOSIS_KEYS, path="$", code=code)
        _literal_version(root["diagnosis_schema_version"], path="$.diagnosis_schema_version")
        _null_authority(root["authorized_action"], path="$.authorized_action")

        artifact_evidence = tuple(
            ArtifactEvidenceRef.from_mapping(item, index=index)
            for index, item in enumerate(
                _array(
                    root["artifact_evidence"],
                    path="$.artifact_evidence",
                    code=code,
                    nonempty=False,
                )
            )
        )
        artifact_keys = tuple(
            (item.artifact_id, item.event_id) for item in artifact_evidence
        )
        if len(set(artifact_keys)) != len(artifact_keys):
            raise _fail(
                code,
                "artifact evidence references must be unique",
                path="$.artifact_evidence",
            )
        if artifact_keys != tuple(sorted(artifact_keys)):
            raise _fail(
                code,
                "artifact evidence must be ordered by artifact_id and event_id",
                path="$.artifact_evidence",
            )

        failure_type = _text(root["failure_type"], path="$.failure_type", code=code)
        if failure_type not in DIAGNOSIS_FAILURE_TYPES:
            raise _fail(code, "$.failure_type is unsupported", path="$.failure_type")
        recommendation = _text(
            root["recommendation"],
            path="$.recommendation",
            code=code,
        )
        if recommendation not in DIAGNOSIS_RECOMMENDATIONS:
            raise _fail(
                code,
                "$.recommendation is unsupported",
                path="$.recommendation",
            )

        diagnosis = cls(
            diagnosis_schema_version=DIAGNOSIS_SCHEMA_VERSION,
            generation_id=_namespaced_id(
                root["generation_id"],
                "generation",
                path="$.generation_id",
            ),
            compatibility_digest=_digest(
                root["compatibility_digest"],
                path="$.compatibility_digest",
                code=code,
            ),
            experiment_id=_namespaced_id(
                root["experiment_id"],
                "experiment",
                path="$.experiment_id",
            ),
            proposal_id=_namespaced_id(
                root["proposal_id"],
                "proposal",
                path="$.proposal_id",
            ),
            proposal_digest=_digest(
                root["proposal_digest"],
                path="$.proposal_digest",
                code=code,
            ),
            hypothesis_class_id=_text(
                root["hypothesis_class_id"],
                path="$.hypothesis_class_id",
                code=code,
            ),
            evaluation_scope_id=_text(
                root["evaluation_scope_id"],
                path="$.evaluation_scope_id",
                code=code,
            ),
            terminal_evidence=TerminalEvidenceRef.from_mapping(root["terminal_evidence"]),
            artifact_evidence=artifact_evidence,
            observation=DiagnosisObservation.from_mapping(root["observation"]),
            interpretation=_narrative(root["interpretation"], path="$.interpretation"),
            failure_type=failure_type,
            falsifier=_narrative(root["falsifier"], path="$.falsifier"),
            recommendation=recommendation,
        )
        try:
            sha256_json(diagnosis.to_dict())
        except (TypeError, ValueError) as exc:  # pragma: no cover - field validators cover it
            raise _fail(code, f"diagnosis is not canonical JSON: {exc}", path="$") from exc
        return diagnosis

    @property
    def digest(self) -> str:
        return sha256_json(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "diagnosis_schema_version": self.diagnosis_schema_version,
            "generation_id": self.generation_id,
            "compatibility_digest": self.compatibility_digest,
            "experiment_id": self.experiment_id,
            "proposal_id": self.proposal_id,
            "proposal_digest": self.proposal_digest,
            "hypothesis_class_id": self.hypothesis_class_id,
            "evaluation_scope_id": self.evaluation_scope_id,
            "terminal_evidence": self.terminal_evidence.to_dict(),
            "artifact_evidence": [item.to_dict() for item in self.artifact_evidence],
            "observation": self.observation.to_dict(),
            "interpretation": self.interpretation,
            "failure_type": self.failure_type,
            "falsifier": self.falsifier,
            "recommendation": self.recommendation,
            "authorized_action": None,
        }


def diagnosis_id(project_id: str, diagnosis_digest: str) -> str:
    """Derive the project-scoped identity of one canonical Diagnosis body."""

    project_id = _text(project_id, path="$.project_id", code="DIAGNOSIS_INVALID")
    diagnosis_digest = _digest(
        diagnosis_digest,
        path="$.diagnosis_digest",
        code="DIAGNOSIS_INVALID",
    )
    return stable_id("diagnosis", project_id, diagnosis_digest)


@dataclass(frozen=True, slots=True)
class DiagnosisEventPayload:
    """Exact payload of ``research.experiment_diagnosed.v1``."""

    science_state_version: int
    generation_id: str
    study_contract_digest: str
    evaluation_seal_digest: str
    compatibility_digest: str
    diagnosis: Diagnosis
    diagnosis_digest: str
    diagnosis_id: str
    authorized_action: None = None

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
        *,
        project_id: str,
    ) -> "DiagnosisEventPayload":
        code = "DIAGNOSIS_INVALID"
        root = _object(raw, _DIAGNOSIS_EVENT_PAYLOAD_KEYS, path="$", code=code)
        _literal_version(root["science_state_version"], path="$.science_state_version")
        _null_authority(root["authorized_action"], path="$.authorized_action")
        diagnosis = Diagnosis.from_mapping(root["diagnosis"])
        parsed = cls(
            science_state_version=1,
            generation_id=_namespaced_id(
                root["generation_id"],
                "generation",
                path="$.generation_id",
            ),
            study_contract_digest=_digest(
                root["study_contract_digest"],
                path="$.study_contract_digest",
                code=code,
            ),
            evaluation_seal_digest=_digest(
                root["evaluation_seal_digest"],
                path="$.evaluation_seal_digest",
                code=code,
            ),
            compatibility_digest=_digest(
                root["compatibility_digest"],
                path="$.compatibility_digest",
                code=code,
            ),
            diagnosis=diagnosis,
            diagnosis_digest=_digest(
                root["diagnosis_digest"],
                path="$.diagnosis_digest",
                code=code,
            ),
            diagnosis_id=_namespaced_id(
                root["diagnosis_id"],
                "diagnosis",
                path="$.diagnosis_id",
            ),
        )
        if parsed.diagnosis_digest != diagnosis.digest:
            raise _fail(
                "DIAGNOSIS_DIGEST_MISMATCH",
                "$.diagnosis_digest does not match the canonical Diagnosis body",
                path="$.diagnosis_digest",
            )
        if parsed.diagnosis_id != diagnosis_id(project_id, parsed.diagnosis_digest):
            raise _fail(
                "DIAGNOSIS_ID_MISMATCH",
                "$.diagnosis_id does not match its project-scoped identity",
                path="$.diagnosis_id",
            )
        if parsed.generation_id != diagnosis.generation_id:
            raise _fail(
                "DIAGNOSIS_GENERATION_MISMATCH",
                "wrapper and Diagnosis generation IDs differ",
                path="$.generation_id",
            )
        if parsed.compatibility_digest != diagnosis.compatibility_digest:
            raise _fail(
                "DIAGNOSIS_COMPATIBILITY_MISMATCH",
                "wrapper and Diagnosis compatibility digests differ",
                path="$.compatibility_digest",
            )
        return parsed

    @classmethod
    def from_diagnosis(
        cls,
        *,
        project_id: str,
        generation_id: str,
        study_contract_digest: str,
        evaluation_seal_digest: str,
        compatibility_digest: str,
        diagnosis: Diagnosis | Mapping[str, Any],
    ) -> "DiagnosisEventPayload":
        if isinstance(diagnosis, Diagnosis):
            diagnosis = Diagnosis.from_mapping(diagnosis.to_dict())
        else:
            diagnosis = Diagnosis.from_mapping(diagnosis)
        digest = diagnosis.digest
        return cls.from_mapping(
            {
                "science_state_version": 1,
                "generation_id": generation_id,
                "study_contract_digest": study_contract_digest,
                "evaluation_seal_digest": evaluation_seal_digest,
                "compatibility_digest": compatibility_digest,
                "diagnosis": diagnosis.to_dict(),
                "diagnosis_digest": digest,
                "diagnosis_id": diagnosis_id(project_id, digest),
                "authorized_action": None,
            },
            project_id=project_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "science_state_version": self.science_state_version,
            "generation_id": self.generation_id,
            "study_contract_digest": self.study_contract_digest,
            "evaluation_seal_digest": self.evaluation_seal_digest,
            "compatibility_digest": self.compatibility_digest,
            "diagnosis": self.diagnosis.to_dict(),
            "diagnosis_digest": self.diagnosis_digest,
            "diagnosis_id": self.diagnosis_id,
            "authorized_action": None,
        }


__all__ = [
    "DIAGNOSIS_FAILURE_TYPES",
    "DIAGNOSIS_RECOMMENDATIONS",
    "DIAGNOSIS_SCHEMA_VERSION",
    "MAX_DIAGNOSIS_NARRATIVE_UTF8_BYTES",
    "ArtifactEvidenceRef",
    "Diagnosis",
    "DiagnosisEventPayload",
    "DiagnosisObservation",
    "TerminalEvidenceRef",
    "default_terminal_reason_code",
    "diagnosis_id",
    "normalize_terminal_status",
]
