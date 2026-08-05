"""Version 1 JSON stdin/stdout adapter protocol."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, cast

from .common import (
    JSONObject,
    JSONValue,
    canonical_json,
    copy_json_object,
    copy_json_value,
    decode_json_object,
    freeze_json_object,
    freeze_json_value,
    normalize_json_value,
    require_fields,
)
from .results import ResultEnvelope
from .status import TerminalStatus

PROTOCOL_VERSION = 1


class Operation(str, Enum):
    """Operations an adapter may implement in protocol v1."""

    DESCRIBE = "describe"
    FINGERPRINT = "fingerprint"
    BASELINE = "baseline"
    MATERIALIZE = "materialize"
    RUN = "run"
    EVALUATE = "evaluate"
    VERIFY = "verify"
    CLEANUP = "cleanup"

    @classmethod
    def parse(cls, value: "Operation | str") -> "Operation":
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise TypeError("operation must be a string")
        try:
            return cls(value)
        except ValueError as exc:
            allowed = ", ".join(operation.value for operation in cls)
            raise ValueError(
                f"unknown operation {value!r}; expected one of: {allowed}"
            ) from exc


ProtocolOperation = Operation


class FailureCategory(str, Enum):
    """Stable adapter-failure classes with deterministic terminal outcomes.

    ``code`` remains adapter-defined detail.  Orchestration decisions must use
    this closed taxonomy and never infer semantics from substrings in a code.
    """

    INVALID_EXPERIMENT = "INVALID_EXPERIMENT"
    TIMED_OUT = "TIMED_OUT"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    INFRASTRUCTURE = "INFRASTRUCTURE"

    @classmethod
    def parse(cls, value: "FailureCategory | str") -> "FailureCategory":
        if isinstance(value, cls):
            return value
        if not isinstance(value, str):
            raise TypeError("failure category must be a string")
        try:
            return cls(value)
        except ValueError as exc:
            allowed = ", ".join(item.value for item in cls)
            raise ValueError(
                f"unknown failure category {value!r}; expected one of: {allowed}"
            ) from exc

    @property
    def terminal_status(self) -> TerminalStatus:
        return {
            FailureCategory.INVALID_EXPERIMENT: TerminalStatus.INVALID_EXPERIMENT,
            FailureCategory.TIMED_OUT: TerminalStatus.TIMED_OUT,
            FailureCategory.INSUFFICIENT_EVIDENCE: (
                TerminalStatus.INSUFFICIENT_EVIDENCE
            ),
            FailureCategory.INFRASTRUCTURE: TerminalStatus.INFRA_FAILED,
        }[self]


_UNIVERSAL_FAILURE_CATEGORIES = frozenset(
    {FailureCategory.TIMED_OUT, FailureCategory.INFRASTRUCTURE}
)

FAILURE_CATEGORIES_BY_OPERATION: Mapping[Operation, frozenset[FailureCategory]] = (
    MappingProxyType(
        {
            Operation.DESCRIBE: _UNIVERSAL_FAILURE_CATEGORIES,
            Operation.FINGERPRINT: _UNIVERSAL_FAILURE_CATEGORIES,
            Operation.BASELINE: _UNIVERSAL_FAILURE_CATEGORIES,
            Operation.MATERIALIZE: _UNIVERSAL_FAILURE_CATEGORIES
            | {FailureCategory.INVALID_EXPERIMENT},
            Operation.RUN: _UNIVERSAL_FAILURE_CATEGORIES,
            Operation.EVALUATE: _UNIVERSAL_FAILURE_CATEGORIES
            | {FailureCategory.INSUFFICIENT_EVIDENCE},
            Operation.VERIFY: _UNIVERSAL_FAILURE_CATEGORIES
            | {FailureCategory.INSUFFICIENT_EVIDENCE},
            Operation.CLEANUP: _UNIVERSAL_FAILURE_CATEGORIES,
        }
    )
)


def validate_failure_category(
    operation: Operation | str, category: FailureCategory | str
) -> FailureCategory:
    """Validate that an adapter failure category belongs to its operation."""

    parsed_operation = Operation.parse(operation)
    parsed_category = FailureCategory.parse(category)
    if parsed_category not in FAILURE_CATEGORIES_BY_OPERATION[parsed_operation]:
        raise ValueError(
            f"failure category {parsed_category.value} is not valid for "
            f"{parsed_operation.value}"
        )
    return parsed_category


# Protocol-v1 adapters predate ``error.category``.  Only this exact, closed
# allowlist is accepted when reading an old response.  Unknown codes fail
# closed as malformed protocol instead of being classified by name patterns.
LEGACY_FAILURE_CATEGORIES: Mapping[str, FailureCategory] = MappingProxyType(
    {
        "INVALID_CANDIDATE": FailureCategory.INVALID_EXPERIMENT,
        "BAD_CANDIDATE": FailureCategory.INVALID_EXPERIMENT,
        "UNSUPPORTED_CANDIDATE": FailureCategory.INVALID_EXPERIMENT,
        "ADAPTER_TIMEOUT": FailureCategory.TIMED_OUT,
        "EVALUATOR_TIMEOUT": FailureCategory.TIMED_OUT,
        "TIMED_OUT": FailureCategory.TIMED_OUT,
        "MISSING_EVIDENCE": FailureCategory.INSUFFICIENT_EVIDENCE,
        "INSUFFICIENT_EVIDENCE": FailureCategory.INSUFFICIENT_EVIDENCE,
        "EVALUATOR_FAILED": FailureCategory.INFRASTRUCTURE,
        "ADAPTER_EXCEPTION": FailureCategory.INFRASTRUCTURE,
        "ADAPTER_FAILED": FailureCategory.INFRASTRUCTURE,
        "INTERNAL_ERROR": FailureCategory.INFRASTRUCTURE,
        "INFRASTRUCTURE_FAILURE": FailureCategory.INFRASTRUCTURE,
        "NOT_CONFIGURED": FailureCategory.INFRASTRUCTURE,
    }
)


def _version(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("protocol_version must be an integer")
    if value != PROTOCOL_VERSION:
        raise ValueError(
            f"unsupported protocol_version {value!r}; expected {PROTOCOL_VERSION}"
        )
    return value


def _nonempty_string(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TypeError(f"{field_name} must be a non-empty string")
    if "\x00" in value:
        raise ValueError(f"{field_name} contains a NUL byte")
    return value


def _optional_string(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _nonempty_string(value, field_name)


def _absolute_path(value: Any, field_name: str) -> str:
    try:
        text = os.fspath(value)
    except TypeError as exc:
        raise TypeError(f"{field_name} must be a path string") from exc
    text = _nonempty_string(text, field_name)
    if not Path(text).is_absolute():
        raise ValueError(f"{field_name} must be an absolute path")
    return text


def _diagnostics(value: Any) -> tuple[JSONValue, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        raise TypeError("diagnostics must be a JSON array")
    normalized = tuple(normalize_json_value(item) for item in value)
    for item in normalized:
        if not isinstance(item, (str, dict)):
            raise TypeError("each diagnostic must be a string or JSON object")
    return tuple(cast(JSONValue, freeze_json_value(item)) for item in normalized)


@dataclass(frozen=True, slots=True)
class ProtocolError:
    """Machine-readable adapter failure."""

    code: str
    message: str
    details: Mapping[str, JSONValue] = field(
        default_factory=lambda: MappingProxyType({})
    )
    category: FailureCategory | str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _nonempty_string(self.code, "error.code"))
        object.__setattr__(
            self, "message", _nonempty_string(self.message, "error.message")
        )
        category = self.category
        if category is None:
            category = LEGACY_FAILURE_CATEGORIES.get(self.code)
            if category is None:
                raise ValueError(
                    "error.category is required for code "
                    f"{self.code!r}; the code is not in the protocol-v1 legacy allowlist"
                )
        object.__setattr__(self, "category", FailureCategory.parse(category))
        object.__setattr__(
            self,
            "details",
            freeze_json_object(self.details, field_name="error.details"),
        )

    def to_dict(self) -> JSONObject:
        category = self.category
        if category is None:
            raise ValueError("normalized protocol error is missing category")
        return {
            "code": self.code,
            "message": self.message,
            "category": FailureCategory.parse(category).value,
            "details": copy_json_object(self.details, field_name="error.details"),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "ProtocolError":
        if not isinstance(data, Mapping):
            raise TypeError("error must be a JSON object")
        require_fields(data, "code", "message")
        return cls(
            code=data["code"],
            message=data["message"],
            category=data.get("category"),
            details=data.get("details", {}),
        )


@dataclass(frozen=True, slots=True)
class VerifyResult:
    """Operation-specific evidence verdict returned by ``verify``."""

    valid: bool
    reason_code: str
    category: FailureCategory | str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.valid, bool):
            raise TypeError("verify.valid must be a boolean")
        object.__setattr__(
            self,
            "reason_code",
            _nonempty_string(self.reason_code, "verify.reason_code"),
        )
        category = self.category
        if self.valid:
            if category is not None:
                raise ValueError("a valid verify result cannot contain category")
            return
        if category is None:
            raise ValueError("verify.category is required when verify.valid is false")
        parsed = validate_failure_category(Operation.VERIFY, category)
        if parsed is not FailureCategory.INSUFFICIENT_EVIDENCE:
            raise ValueError(
                "verify.category must be INSUFFICIENT_EVIDENCE when verify.valid is false"
            )
        object.__setattr__(self, "category", parsed)

    def to_dict(self) -> JSONObject:
        result: JSONObject = {
            "valid": self.valid,
            "reason_code": self.reason_code,
        }
        category = self.category
        if category is not None:
            result["category"] = FailureCategory.parse(category).value
        return result

    @classmethod
    def from_dict(cls, data: Any) -> "VerifyResult":
        if not isinstance(data, Mapping):
            raise TypeError("verify payload must be a JSON object")
        require_fields(data, "valid", "reason_code")
        return cls(
            valid=data["valid"],
            reason_code=data["reason_code"],
            category=data.get("category"),
        )


@dataclass(frozen=True, slots=True)
class ProtocolRequest:
    """One protocol-v1 adapter request."""

    protocol_version: int
    request_id: str
    operation: Operation
    project_root: str
    payload: Mapping[str, JSONValue]
    workspace: str | None = None
    experiment_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_version", _version(self.protocol_version))
        object.__setattr__(
            self, "request_id", _nonempty_string(self.request_id, "request_id")
        )
        object.__setattr__(self, "operation", Operation.parse(self.operation))
        object.__setattr__(
            self, "project_root", _absolute_path(self.project_root, "project_root")
        )
        object.__setattr__(
            self,
            "payload",
            freeze_json_object(self.payload, field_name="payload"),
        )
        if self.workspace is not None:
            object.__setattr__(
                self, "workspace", _absolute_path(self.workspace, "workspace")
            )
        object.__setattr__(
            self,
            "experiment_id",
            _optional_string(self.experiment_id, "experiment_id"),
        )
        discovery = self.operation in {Operation.DESCRIBE, Operation.FINGERPRINT}
        if discovery and (self.workspace is not None or self.experiment_id is not None):
            raise ValueError(
                f"{self.operation.value} must run against the sealed project root without an experiment"
            )
        if not discovery and (self.workspace is None or self.experiment_id is None):
            raise ValueError(
                f"{self.operation.value} requires both workspace and experiment_id"
            )

    def to_dict(self) -> JSONObject:
        result: JSONObject = {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "operation": self.operation.value,
            "project_root": self.project_root,
            "payload": copy_json_object(self.payload, field_name="payload"),
        }
        if self.workspace is not None:
            result["workspace"] = self.workspace
        if self.experiment_id is not None:
            result["experiment_id"] = self.experiment_id
        return result

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Any) -> "ProtocolRequest":
        if not isinstance(data, Mapping):
            raise TypeError("protocol request must be a JSON object")
        require_fields(
            data,
            "protocol_version",
            "request_id",
            "operation",
            "project_root",
            "payload",
        )
        return cls(
            protocol_version=data["protocol_version"],
            request_id=data["request_id"],
            operation=data["operation"],
            project_root=data["project_root"],
            payload=data["payload"],
            workspace=data.get("workspace"),
            experiment_id=data.get("experiment_id"),
        )

    from_mapping = from_dict

    @classmethod
    def from_json(cls, data: str | bytes | bytearray) -> "ProtocolRequest":
        return cls.from_dict(decode_json_object(data))

    @classmethod
    def create(
        cls,
        *,
        request_id: str,
        operation: Operation | str,
        project_root: str | Path,
        payload: Mapping[str, JSONValue],
        workspace: str | Path | None = None,
        experiment_id: str | None = None,
    ) -> "ProtocolRequest":
        return cls(
            protocol_version=PROTOCOL_VERSION,
            request_id=request_id,
            operation=Operation.parse(operation),
            project_root=os.fspath(project_root),
            payload=payload,
            workspace=None if workspace is None else os.fspath(workspace),
            experiment_id=experiment_id,
        )


@dataclass(frozen=True, slots=True)
class ProtocolResponse:
    """One protocol-v1 adapter response.

    Failed responses must carry a structured ``error``.  Successful responses
    must not carry one.  Readers ignore unknown top-level fields.
    """

    protocol_version: int
    request_id: str
    ok: bool
    retryable: bool
    payload: Mapping[str, JSONValue]
    diagnostics: tuple[JSONValue, ...] = ()
    error: ProtocolError | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "protocol_version", _version(self.protocol_version))
        object.__setattr__(
            self, "request_id", _nonempty_string(self.request_id, "request_id")
        )
        if not isinstance(self.ok, bool):
            raise TypeError("ok must be a boolean")
        if not isinstance(self.retryable, bool):
            raise TypeError("retryable must be a boolean")
        object.__setattr__(
            self,
            "payload",
            freeze_json_object(self.payload, field_name="payload"),
        )
        object.__setattr__(self, "diagnostics", _diagnostics(self.diagnostics))

        error = self.error
        if error is not None and not isinstance(error, ProtocolError):
            error = ProtocolError.from_dict(error)
            object.__setattr__(self, "error", error)
        if self.ok and error is not None:
            raise ValueError("a successful response cannot contain error")
        if not self.ok and error is None:
            raise ValueError("a failed response must contain an error object")
        if self.ok and self.retryable:
            raise ValueError("a successful response cannot be retryable")

    def to_dict(self) -> JSONObject:
        result: JSONObject = {
            "protocol_version": self.protocol_version,
            "request_id": self.request_id,
            "ok": self.ok,
            "retryable": self.retryable,
            "payload": copy_json_object(self.payload, field_name="payload"),
            "diagnostics": [copy_json_value(item) for item in self.diagnostics],
        }
        if self.error is not None:
            result["error"] = self.error.to_dict()
        return result

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @classmethod
    def from_dict(cls, data: Any) -> "ProtocolResponse":
        if not isinstance(data, Mapping):
            raise TypeError("protocol response must be a JSON object")
        require_fields(
            data, "protocol_version", "request_id", "ok", "retryable", "payload"
        )
        if data["ok"] is False and "error" not in data:
            raise ValueError("missing required field(s): error")
        if data["ok"] is True and "error" in data:
            raise ValueError("a successful response must omit error")
        return cls(
            protocol_version=data["protocol_version"],
            request_id=data["request_id"],
            ok=data["ok"],
            retryable=data["retryable"],
            payload=data["payload"],
            diagnostics=data.get("diagnostics", ()),
            error=data.get("error"),
        )

    from_mapping = from_dict

    @classmethod
    def from_json(cls, data: str | bytes | bytearray) -> "ProtocolResponse":
        return cls.from_dict(decode_json_object(data))

    @classmethod
    def success(
        cls,
        *,
        request_id: str,
        payload: Mapping[str, JSONValue],
        diagnostics: Sequence[JSONValue] = (),
    ) -> "ProtocolResponse":
        clean_diagnostics = _diagnostics(diagnostics)
        return cls(
            protocol_version=PROTOCOL_VERSION,
            request_id=request_id,
            ok=True,
            retryable=False,
            payload=payload,
            diagnostics=clean_diagnostics,
        )

    @classmethod
    def failure(
        cls,
        *,
        request_id: str,
        error: ProtocolError | Mapping[str, Any],
        retryable: bool = False,
        payload: Mapping[str, JSONValue] | None = None,
        diagnostics: Sequence[JSONValue] = (),
    ) -> "ProtocolResponse":
        clean_diagnostics = _diagnostics(diagnostics)
        clean_error = (
            error
            if isinstance(error, ProtocolError)
            else ProtocolError.from_dict(error)
        )
        return cls(
            protocol_version=PROTOCOL_VERSION,
            request_id=request_id,
            ok=False,
            retryable=retryable,
            payload={} if payload is None else payload,
            diagnostics=clean_diagnostics,
            error=clean_error,
        )

    def result_envelope(self) -> ResultEnvelope:
        if not self.ok:
            raise ValueError("a failed response has no result envelope")
        return ResultEnvelope.from_dict(self.payload)

    def verify_result(self) -> VerifyResult:
        if not self.ok:
            raise ValueError("a failed response has no verify result")
        return VerifyResult.from_dict(self.payload)


AdapterRequest = ProtocolRequest
AdapterResponse = ProtocolResponse


DESIGN_PROVENANCE: dict[str, tuple[str, ...]] = {
    "Operation": ("Incremental complexity",),
    "FailureCategory": ("Incremental complexity", "Experiment DAG"),
    "ProtocolError": ("Incremental complexity", "Experiment DAG"),
    "ProtocolRequest": ("Incremental complexity", "Fixed experiment budget"),
    "ProtocolResponse": ("Incremental complexity", "Experiment DAG"),
    "VerifyResult": ("Immutable evaluation", "Typed provenance"),
}
