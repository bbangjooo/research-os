"""Bounded process client for the versioned adapter JSON protocol."""

from __future__ import annotations

import json
import math
import os
import signal
import stat
import subprocess
import tempfile
import time
import uuid
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any

from research_os.contracts.common import decode_json_object
from research_os.contracts.protocol import (
    PROTOCOL_VERSION,
    Operation,
    ProtocolRequest,
    ProtocolResponse,
)
from research_os.errors import ConfigurationError, ProtocolError

ERROR_INVALID_CALL = "adapter_invalid_call"
ERROR_SPAWN = "adapter_spawn_failed"
ERROR_TIMEOUT = "adapter_timeout"
ERROR_OUTPUT_LIMIT = "adapter_output_limit"
ERROR_PROCESS = "adapter_process_failed"
ERROR_INVALID_RESPONSE = "adapter_invalid_response"
ERROR_VERSION_MISMATCH = "adapter_version_mismatch"
ERROR_REQUEST_ID_MISMATCH = "adapter_request_id_mismatch"

_EMPTY_PAYLOAD: Mapping[str, Any] = MappingProxyType({})
_POLL_SECONDS = 0.01
_TERM_GRACE_SECONDS = 0.25
_KILL_GRACE_SECONDS = 0.25
_MAX_ERROR_STDERR_CHARS = 4096


def _config_value(config: object, name: str, default: Any = None) -> Any:
    if isinstance(config, Mapping):
        return config.get(name, default)
    return getattr(config, name, default)


class AdapterProtocolError(ProtocolError):
    """Stable, machine-readable failure of the adapter process boundary.

    ``code`` is one of the exported ``ERROR_*`` constants and ``details`` has
    code-specific scalar values.  Adapter-declared failures (valid responses
    with ``ok == False``) are *not* represented by this exception; they are
    returned to the caller as :class:`ProtocolResponse`.
    """

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.details = MappingProxyType(dict(details or {}))


class AdapterTimeoutError(AdapterProtocolError, TimeoutError):
    """Adapter protocol failure that also classifies as a wall-clock timeout."""


def _positive_float(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{name} must be a positive finite number")
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise ConfigurationError(f"{name} must be a positive finite number")
    return result


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigurationError(f"{name} must be a positive integer")
    return value


def _command_argv(value: Any) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)):
        raise ConfigurationError(
            "adapter_command must be an argv sequence, not a shell string"
        )
    try:
        command = tuple(value)
    except TypeError as exc:
        raise ConfigurationError(
            "adapter_command must be a non-empty argv sequence"
        ) from exc
    if not command:
        raise ConfigurationError("adapter_command must be a non-empty argv sequence")
    for argument in command:
        if not isinstance(argument, str) or not argument or "\x00" in argument:
            raise ConfigurationError(
                "adapter_command arguments must be non-empty strings without NUL bytes"
            )
    return command


def _directory_without_symlink(path: Path, label: str) -> Path:
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise ConfigurationError(f"{label} does not exist: {path}") from exc
    if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISDIR(path_stat.st_mode):
        raise ConfigurationError(f"{label} must be a non-symlink directory: {path}")
    return path


def _stream_size(stream: Any) -> int:
    try:
        return os.fstat(stream.fileno()).st_size
    except OSError:
        return 0


def _group_exists(process: subprocess.Popen[bytes]) -> bool:
    if os.name == "posix" and hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    return process.poll() is None


def _signal_process_group(process: subprocess.Popen[bytes], sig: int) -> None:
    if os.name == "posix" and hasattr(os, "killpg"):
        try:
            os.killpg(process.pid, sig)
        except (ProcessLookupError, PermissionError):
            return
    else:
        try:
            if sig == signal.SIGTERM:
                process.terminate()
            else:
                process.kill()
        except (ProcessLookupError, PermissionError):
            return


def _wait_for_group_exit(process: subprocess.Popen[bytes], seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, seconds)
    while _group_exists(process):
        process.poll()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(_POLL_SECONDS, remaining))
    process.poll()
    return True


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Bounded TERM-then-KILL cleanup for the process and all descendants."""

    if _group_exists(process):
        _signal_process_group(process, signal.SIGTERM)
        if not _wait_for_group_exit(process, _TERM_GRACE_SECONDS):
            _signal_process_group(process, signal.SIGKILL)
            _wait_for_group_exit(process, _KILL_GRACE_SECONDS)
    try:
        process.wait(timeout=0)
    except (subprocess.TimeoutExpired, ChildProcessError):
        pass


def _bounded_text(data: bytes, *, strict: bool) -> str:
    errors = "strict" if strict else "replace"
    text = data.decode("utf-8", errors=errors)
    if len(text) > _MAX_ERROR_STDERR_CHARS:
        return text[:_MAX_ERROR_STDERR_CHARS] + "…"
    return text


class AdapterClient:
    """Invoke a configured adapter with one request and one response object."""

    def __init__(self, config: object):
        self.config = config
        raw_root = _config_value(config, "root", _config_value(config, "project_root"))
        if raw_root is None:
            raise ConfigurationError("adapter config requires root")
        try:
            supplied_root = Path(os.fspath(raw_root)).expanduser()
        except TypeError as exc:
            raise ConfigurationError("adapter root must be a filesystem path") from exc
        if supplied_root.is_symlink():
            raise ConfigurationError("adapter root must not be a symbolic link")
        try:
            project_root = supplied_root.resolve(strict=True)
        except OSError as exc:
            raise ConfigurationError(
                f"adapter root does not exist: {supplied_root}"
            ) from exc
        self.project_root = _directory_without_symlink(project_root, "adapter root")
        project_stat = self.project_root.lstat()
        self._project_identity = (project_stat.st_dev, project_stat.st_ino)

        self.command = _command_argv(_config_value(config, "adapter_command"))
        self.timeout_seconds = _positive_float(
            _config_value(config, "timeout_seconds", 60.0), "timeout_seconds"
        )
        self.max_output_bytes = _positive_int(
            _config_value(config, "max_output_bytes", 1024 * 1024),
            "max_output_bytes",
        )

        self.workspaces_root = (
            self.project_root / ".research-os" / "runtime" / "workspaces"
        )

    def _assert_project_root(self) -> None:
        try:
            project_stat = self.project_root.lstat()
        except OSError as exc:
            raise AdapterProtocolError(
                ERROR_INVALID_CALL,
                "project root is unavailable",
                details={"project_root": os.fspath(self.project_root)},
            ) from exc
        if (
            stat.S_ISLNK(project_stat.st_mode)
            or not stat.S_ISDIR(project_stat.st_mode)
            or (project_stat.st_dev, project_stat.st_ino) != self._project_identity
        ):
            raise AdapterProtocolError(
                ERROR_INVALID_CALL,
                "project root was replaced after client initialization",
                details={"project_root": os.fspath(self.project_root)},
            )

    def _workspace_path(self, workspace: Any) -> Path | None:
        if workspace is None:
            return None
        raw_path = getattr(workspace, "path", workspace)
        try:
            supplied = Path(os.fspath(raw_path))
        except TypeError as exc:
            raise AdapterProtocolError(
                ERROR_INVALID_CALL,
                "workspace must be a path or WorkspaceHandle",
            ) from exc
        if not supplied.is_absolute():
            raise AdapterProtocolError(
                ERROR_INVALID_CALL,
                "workspace must be an absolute path",
                details={"workspace": os.fspath(supplied)},
            )

        expected_parts = (
            self.project_root / ".research-os",
            self.project_root / ".research-os" / "runtime",
            self.workspaces_root,
        )
        for component in expected_parts:
            try:
                component_stat = component.lstat()
            except OSError as exc:
                raise AdapterProtocolError(
                    ERROR_INVALID_CALL,
                    "workspace runtime path is unavailable",
                    details={"path": os.fspath(component)},
                ) from exc
            if stat.S_ISLNK(component_stat.st_mode) or not stat.S_ISDIR(
                component_stat.st_mode
            ):
                raise AdapterProtocolError(
                    ERROR_INVALID_CALL,
                    "workspace runtime path is unsafe",
                    details={"path": os.fspath(component)},
                )
        try:
            supplied_stat = supplied.lstat()
            resolved = supplied.resolve(strict=True)
        except OSError as exc:
            raise AdapterProtocolError(
                ERROR_INVALID_CALL,
                "workspace does not exist",
                details={"workspace": os.fspath(supplied)},
            ) from exc
        if stat.S_ISLNK(supplied_stat.st_mode) or not stat.S_ISDIR(
            supplied_stat.st_mode
        ):
            raise AdapterProtocolError(
                ERROR_INVALID_CALL,
                "workspace must be a non-symlink directory",
                details={"workspace": os.fspath(supplied)},
            )
        if resolved.parent != self.workspaces_root.resolve(strict=True):
            raise AdapterProtocolError(
                ERROR_INVALID_CALL,
                "workspace is outside the managed workspace directory",
                details={"workspace": os.fspath(resolved)},
            )
        return resolved

    def _request(
        self,
        operation: Operation | str,
        *,
        payload: Mapping[str, Any],
        workspace: Path | None,
        experiment_id: str | None,
    ) -> tuple[str, bytes]:
        request_id = uuid.uuid4().hex
        try:
            request = ProtocolRequest.create(
                request_id=request_id,
                operation=operation,
                project_root=self.project_root,
                workspace=workspace,
                experiment_id=experiment_id,
                payload=payload,
            )
            request_data = request.to_dict()
            # The process boundary always carries the workspace key.  ``null``
            # distinguishes a deliberate source-root operation from a producer
            # that omitted its isolation context by mistake.
            request_data["workspace"] = (
                None if workspace is None else os.fspath(workspace)
            )
            request_bytes = (
                json.dumps(
                    request_data,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                )
                + "\n"
            ).encode("utf-8")
        except (TypeError, ValueError, OSError) as exc:
            raise AdapterProtocolError(
                ERROR_INVALID_CALL,
                "adapter request is invalid",
                details={"reason": str(exc)},
            ) from exc
        return request_id, request_bytes

    def call(
        self,
        operation: Operation | str,
        *,
        payload: Mapping[str, Any] = _EMPTY_PAYLOAD,
        workspace: Any = None,
        experiment_id: str | None = None,
    ) -> ProtocolResponse:
        """Call the adapter and return a validated protocol-v1 response.

        The adapter must exit successfully and write exactly one UTF-8 JSON
        object to stdout.  Valid ``ok=false`` responses are returned unchanged;
        only process-boundary and protocol violations raise
        :class:`AdapterProtocolError`.
        """

        self._assert_project_root()
        workspace_path = self._workspace_path(workspace)
        request_id, request_bytes = self._request(
            operation,
            payload=payload,
            workspace=workspace_path,
            experiment_id=experiment_id,
        )
        operation_text = (
            operation.value if isinstance(operation, Operation) else operation
        )
        base_details = {
            "operation": operation_text,
            "request_id": request_id,
        }

        process: subprocess.Popen[bytes] | None = None
        with (
            tempfile.TemporaryFile(mode="w+b") as stdin_file,
            tempfile.TemporaryFile(mode="w+b") as stdout_file,
            tempfile.TemporaryFile(mode="w+b") as stderr_file,
        ):
            stdin_file.write(request_bytes)
            stdin_file.seek(0)
            try:
                child_environment = os.environ.copy()
                child_environment["PYTHONDONTWRITEBYTECODE"] = "1"
                child_environment.pop("PYTHONPYCACHEPREFIX", None)
                process = subprocess.Popen(
                    self.command,
                    stdin=stdin_file,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    cwd=workspace_path or self.project_root,
                    env=child_environment,
                    shell=False,
                    close_fds=True,
                    start_new_session=True,
                )
            except OSError as exc:
                raise AdapterProtocolError(
                    ERROR_SPAWN,
                    "adapter process could not be started",
                    details={
                        **base_details,
                        "errno": exc.errno,
                        "reason": exc.strerror or str(exc),
                    },
                ) from exc

            deadline = time.monotonic() + self.timeout_seconds
            failure: str | None = None
            stdout_bytes = 0
            stderr_bytes = 0
            try:
                while True:
                    stdout_bytes = _stream_size(stdout_file)
                    stderr_bytes = _stream_size(stderr_file)
                    if stdout_bytes + stderr_bytes > self.max_output_bytes:
                        failure = ERROR_OUTPUT_LIMIT
                        break
                    return_code = process.poll()
                    if return_code is not None:
                        break
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        failure = ERROR_TIMEOUT
                        break
                    time.sleep(min(_POLL_SECONDS, remaining))

                # Whether the parent timed out or exited, terminate any process
                # group members that remain.  This prevents orphan workers from
                # retaining the output files or mutating a workspace later.
                _terminate_process_group(process)
                stdout_bytes = _stream_size(stdout_file)
                stderr_bytes = _stream_size(stderr_file)
                if (
                    failure is None
                    and stdout_bytes + stderr_bytes > self.max_output_bytes
                ):
                    failure = ERROR_OUTPUT_LIMIT

                stdout_file.seek(0)
                stderr_file.seek(0)
                stdout_data = stdout_file.read(self.max_output_bytes + 1)
                stderr_data = stderr_file.read(self.max_output_bytes + 1)
            finally:
                if process is not None:
                    _terminate_process_group(process)

        stderr_text = _bounded_text(stderr_data, strict=False)
        if failure == ERROR_OUTPUT_LIMIT:
            raise AdapterProtocolError(
                ERROR_OUTPUT_LIMIT,
                "adapter output exceeded the configured byte limit",
                details={
                    **base_details,
                    "max_output_bytes": self.max_output_bytes,
                    "stdout_bytes": stdout_bytes,
                    "stderr_bytes": stderr_bytes,
                },
            )
        if failure == ERROR_TIMEOUT:
            raise AdapterTimeoutError(
                ERROR_TIMEOUT,
                "adapter exceeded the configured wall-clock timeout",
                details={
                    **base_details,
                    "timeout_seconds": self.timeout_seconds,
                    "stderr": stderr_text,
                },
            )

        return_code = process.returncode
        if return_code != 0:
            raise AdapterProtocolError(
                ERROR_PROCESS,
                "adapter process exited unsuccessfully",
                details={
                    **base_details,
                    "returncode": return_code,
                    "stderr": stderr_text,
                },
            )

        try:
            stdout_text = stdout_data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise AdapterProtocolError(
                ERROR_INVALID_RESPONSE,
                "adapter stdout is not valid UTF-8",
                details={**base_details, "reason": "invalid_utf8"},
            ) from exc
        try:
            raw_response = decode_json_object(stdout_text)
        except (TypeError, ValueError) as exc:
            raise AdapterProtocolError(
                ERROR_INVALID_RESPONSE,
                "adapter stdout must contain exactly one JSON object",
                details={**base_details, "reason": str(exc)},
            ) from exc
        if not isinstance(raw_response, dict):
            raise AdapterProtocolError(
                ERROR_INVALID_RESPONSE,
                "adapter stdout JSON must be an object",
                details={**base_details, "actual_type": type(raw_response).__name__},
            )

        if "protocol_version" in raw_response and (
            isinstance(raw_response["protocol_version"], bool)
            or not isinstance(raw_response["protocol_version"], int)
            or raw_response["protocol_version"] != PROTOCOL_VERSION
        ):
            raise AdapterProtocolError(
                ERROR_VERSION_MISMATCH,
                "adapter response protocol version does not match the request",
                details={
                    **base_details,
                    "expected": PROTOCOL_VERSION,
                    "actual": raw_response["protocol_version"],
                },
            )
        if "request_id" in raw_response and raw_response["request_id"] != request_id:
            raise AdapterProtocolError(
                ERROR_REQUEST_ID_MISMATCH,
                "adapter response request_id does not match the request",
                details={
                    **base_details,
                    "actual": raw_response["request_id"],
                },
            )
        try:
            return ProtocolResponse.from_dict(raw_response)
        except (TypeError, ValueError) as exc:
            raise AdapterProtocolError(
                ERROR_INVALID_RESPONSE,
                "adapter response failed protocol validation",
                details={**base_details, "reason": str(exc)},
            ) from exc


__all__ = [
    "AdapterClient",
    "AdapterProtocolError",
    "AdapterTimeoutError",
    "ERROR_INVALID_CALL",
    "ERROR_INVALID_RESPONSE",
    "ERROR_OUTPUT_LIMIT",
    "ERROR_PROCESS",
    "ERROR_REQUEST_ID_MISMATCH",
    "ERROR_SPAWN",
    "ERROR_TIMEOUT",
    "ERROR_VERSION_MISMATCH",
]
