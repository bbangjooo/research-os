"""Value-only Python and bounded strict-JSON DecisionPacket provider ports."""

from __future__ import annotations

import math
import os
import signal
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol

from research_os.contracts.common import (
    FrozenJSONObject,
    canonical_json_bytes,
    decode_json_object,
    normalize_json_object,
)
from research_os.errors import ConfigurationError

from .protocol import ProviderRequest

_POLL_SECONDS = 0.005
_TERM_GRACE_SECONDS = 0.25
_KILL_GRACE_SECONDS = 0.25
_MAX_ERROR_TEXT = 4096


class ProviderPortError(ConfigurationError):
    """Stable machine-readable provider transport failure."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        self.code = code
        self.details = MappingProxyType(dict(details or {}))
        super().__init__(f"{code}: {message}")


class PythonDecisionProvider(Protocol):
    """Same-process provider contract; this interface is not a security sandbox."""

    def decide(self, request: FrozenJSONObject) -> Mapping[str, Any]: ...


def _protocol_error(message: str, **details: object) -> ProviderPortError:
    return ProviderPortError("PROVIDER_PROTOCOL_INVALID", message, details=details)


def _positive_float(value: object, *, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigurationError(f"{name} must be a positive finite number")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise ConfigurationError(f"{name} must be a positive finite number")
    return parsed


def _positive_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigurationError(f"{name} must be a positive integer")
    return value


def _argv(value: Sequence[str]) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)):
        raise ConfigurationError("provider command must be an argv sequence, not a shell string")
    command = tuple(value)
    if not command:
        raise ConfigurationError("provider command must not be empty")
    if any(
        not isinstance(argument, str) or not argument or "\x00" in argument for argument in command
    ):
        raise ConfigurationError("provider argv must contain non-empty NUL-free strings")
    return command


def _strict_result(value: object) -> dict[str, Any]:
    def value_only(item: object, active: set[int] | None = None) -> None:
        if item is None or isinstance(item, (bool, int, float, str)):
            return
        if callable(item):
            raise TypeError("callable values are not JSON data")
        if active is None:
            active = set()
        identity = id(item)
        if identity in active:
            raise TypeError("cyclic values are not JSON data")
        if isinstance(item, Mapping):
            active.add(identity)
            try:
                for key, nested in item.items():
                    if not isinstance(key, str):
                        raise TypeError("JSON object keys must be strings")
                    value_only(nested, active)
            finally:
                active.remove(identity)
            return
        if isinstance(item, Sequence) and not isinstance(item, (str, bytes, bytearray, memoryview)):
            active.add(identity)
            try:
                for nested in item:
                    value_only(nested, active)
            finally:
                active.remove(identity)
            return
        raise TypeError(f"live {type(item).__name__} values are not JSON data")

    try:
        value_only(value)
        return normalize_json_object(value, field_name="provider result")
    except (TypeError, ValueError) as exc:
        raise _protocol_error(
            "provider must return one strict JSON object", reason=str(exc)
        ) from exc


class PythonProviderPort:
    """Invoke a Python provider with one recursively immutable value request."""

    def __init__(self, provider: PythonDecisionProvider):
        if not callable(getattr(provider, "decide", None)):
            raise ConfigurationError("Python provider must implement decide(request)")
        self.provider = provider

    def invoke(self, request: ProviderRequest) -> dict[str, Any]:
        if not isinstance(request, ProviderRequest):
            raise TypeError("request must be a ProviderRequest")
        try:
            result = self.provider.decide(request.frozen_mapping())
        except ProviderPortError:
            raise
        except Exception as exc:
            raise _protocol_error(
                "Python provider raised an exception", exception_type=type(exc).__name__
            ) from exc
        return _strict_result(result)


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


def _signal_group(process: subprocess.Popen[bytes], sig: int) -> None:
    try:
        if os.name == "posix" and hasattr(os, "killpg"):
            os.killpg(process.pid, sig)
        elif sig == signal.SIGTERM:
            process.terminate()
        else:
            process.kill()
    except (ProcessLookupError, PermissionError):
        pass


def _wait_group(process: subprocess.Popen[bytes], seconds: float) -> bool:
    deadline = time.monotonic() + max(0.0, seconds)
    while _group_exists(process):
        process.poll()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(_POLL_SECONDS, remaining))
    process.poll()
    return True


def _terminate_group(process: subprocess.Popen[bytes]) -> None:
    if _group_exists(process):
        _signal_group(process, signal.SIGTERM)
        if not _wait_group(process, _TERM_GRACE_SECONDS):
            _signal_group(process, signal.SIGKILL)
            _wait_group(process, _KILL_GRACE_SECONDS)
    try:
        process.wait(timeout=0)
    except (ChildProcessError, subprocess.TimeoutExpired):
        pass


def _size(stream: Any) -> int:
    try:
        return os.fstat(stream.fileno()).st_size
    except OSError:
        return 0


def _bounded_stderr(stream: Any) -> str:
    try:
        stream.seek(0)
        value = stream.read(_MAX_ERROR_TEXT).decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return ""
    return value


class JSONSubprocessProvider:
    """Run an argv provider in a fresh process group and isolated temporary cwd."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        timeout_seconds: float = 30.0,
        max_output_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.command = _argv(command)
        self.timeout_seconds = _positive_float(timeout_seconds, name="timeout_seconds")
        self.max_output_bytes = _positive_int(max_output_bytes, name="max_output_bytes")

    def invoke(self, request: ProviderRequest) -> dict[str, Any]:
        if not isinstance(request, ProviderRequest):
            raise TypeError("request must be a ProviderRequest")
        request_bytes = canonical_json_bytes(request.to_dict()) + b"\n"
        process: subprocess.Popen[bytes] | None = None
        with tempfile.TemporaryDirectory(prefix="research-os-provider-") as directory:
            cwd = Path(directory)
            with (
                tempfile.TemporaryFile() as stdin_file,
                tempfile.TemporaryFile() as stdout_file,
                tempfile.TemporaryFile() as stderr_file,
            ):
                stdin_file.write(request_bytes)
                stdin_file.seek(0)
                environment = {
                    "PATH": os.defpath,
                    "LANG": "C.UTF-8",
                    "LC_ALL": "C.UTF-8",
                }
                try:
                    process = subprocess.Popen(
                        self.command,
                        stdin=stdin_file,
                        stdout=stdout_file,
                        stderr=stderr_file,
                        cwd=cwd,
                        env=environment,
                        close_fds=True,
                        start_new_session=True,
                    )
                except OSError as exc:
                    raise _protocol_error(
                        "provider process could not be started", reason=str(exc)
                    ) from exc
                deadline = time.monotonic() + self.timeout_seconds
                overflow = False
                timed_out = False
                try:
                    while process.poll() is None:
                        if _size(stdout_file) + _size(stderr_file) > self.max_output_bytes:
                            overflow = True
                            break
                        if time.monotonic() >= deadline:
                            timed_out = True
                            break
                        time.sleep(_POLL_SECONDS)
                    if overflow or timed_out:
                        _terminate_group(process)
                    elif _group_exists(process):
                        # A provider may not leave descendants after its response.
                        _terminate_group(process)
                    output_size = _size(stdout_file) + _size(stderr_file)
                    if overflow or output_size > self.max_output_bytes:
                        raise ProviderPortError(
                            "PROVIDER_OUTPUT_LIMIT",
                            "provider stdout/stderr exceeded the configured byte limit",
                            details={
                                "limit": self.max_output_bytes,
                                "observed_at_least": output_size,
                            },
                        )
                    if timed_out:
                        raise ProviderPortError(
                            "PROVIDER_TIMEOUT",
                            "provider exceeded its wall-clock timeout",
                            details={"timeout_seconds": self.timeout_seconds},
                        )
                    return_code = process.poll()
                    if return_code != 0:
                        raise _protocol_error(
                            "provider process exited unsuccessfully",
                            return_code=return_code,
                            stderr=_bounded_stderr(stderr_file),
                        )
                    stdout_file.seek(0)
                    output = stdout_file.read(self.max_output_bytes + 1)
                    try:
                        decoded = output.decode("utf-8", errors="strict")
                        return decode_json_object(decoded)
                    except (UnicodeDecodeError, TypeError, ValueError) as exc:
                        raise _protocol_error(
                            "provider stdout is not exactly one strict JSON object",
                            reason=str(exc),
                        ) from exc
                finally:
                    if process is not None:
                        _terminate_group(process)
