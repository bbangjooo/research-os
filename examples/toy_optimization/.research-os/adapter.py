#!/usr/bin/env python3
"""Standalone JSON process adapter for the scalar optimization example."""

import json
import subprocess
import sys
from pathlib import Path

VERSION = 1
OPERATIONS = {
    "describe",
    "fingerprint",
    "baseline",
    "materialize",
    "run",
    "evaluate",
    "verify",
    "cleanup",
}


def respond(request, *, ok=True, payload=None, error=None, retryable=False):
    value = {
        "protocol_version": VERSION,
        "request_id": request.get("request_id"),
        "ok": ok,
        "retryable": retryable,
        "payload": payload or {},
        "diagnostics": [],
    }
    if error is not None:
        value["error"] = error
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


def load_result(workspace):
    return json.loads((workspace / "outputs" / "result.json").read_text())


def main():
    try:
        request = json.loads(sys.stdin.read())
        operation = request["operation"]
        if request.get("protocol_version") != VERSION or operation not in OPERATIONS:
            raise ValueError("unsupported protocol or operation")
        project = Path(request["project_root"]).resolve()
        workspace_value = request.get("workspace")
        workspace = Path(workspace_value).resolve() if workspace_value else project
        payload = request.get("payload") or {}

        if operation == "describe":
            respond(
                request,
                payload={"capabilities": sorted(OPERATIONS), "side_effects": []},
            )
        elif operation == "fingerprint":
            respond(
                request,
                payload={"dataset": "target-v1", "evaluator": "squared-error-v1"},
            )
        elif operation == "materialize":
            candidate = payload.get("candidate") or {}
            x = candidate.get("x")
            if not isinstance(x, (int, float)) or isinstance(x, bool):
                respond(
                    request,
                    ok=False,
                    error={
                        "category": "INVALID_EXPERIMENT",
                        "code": "INVALID_CANDIDATE",
                        "message": "x must be numeric",
                    },
                )
                return
            (workspace / "parameter.json").write_text(
                json.dumps({"x": float(x)}, sort_keys=True) + "\n"
            )
            respond(request)
        elif operation in {"baseline", "run"}:
            completed = subprocess.run(
                [sys.executable, str(project / "evaluator.py"), str(workspace)],
                check=False,
                capture_output=True,
                text=True,
            )
            if completed.returncode:
                respond(
                    request,
                    ok=False,
                    retryable=False,
                    error={
                        "category": "INFRASTRUCTURE",
                        "code": "EVALUATOR_FAILED",
                        "message": completed.stderr[-1000:],
                    },
                )
                return
            if operation == "baseline":
                result = load_result(workspace)
                result["artifacts"] = [
                    {
                        "path": "outputs/result.json",
                        "media_type": "application/json",
                        "retention": "run",
                        "sensitivity": "public",
                    }
                ]
                respond(request, payload=result)
            else:
                respond(request)
        elif operation == "evaluate":
            result = load_result(workspace)
            result["artifacts"] = [
                {
                    "path": "outputs/result.json",
                    "media_type": "application/json",
                    "retention": "project",
                    "sensitivity": "public",
                }
            ]
            respond(request, payload=result)
        elif operation == "verify":
            result = load_result(workspace)
            valid = isinstance(result.get("metrics", {}).get("loss"), (int, float))
            verdict = {
                "valid": valid,
                "reason_code": "OK" if valid else "MISSING_LOSS",
            }
            if not valid:
                verdict["category"] = "INSUFFICIENT_EVIDENCE"
            respond(request, payload=verdict)
        else:
            respond(request)
    except Exception as exc:
        fallback = locals().get("request", {})
        respond(
            fallback,
            ok=False,
            error={
                "category": "INFRASTRUCTURE",
                "code": "ADAPTER_EXCEPTION",
                "message": str(exc),
            },
        )


if __name__ == "__main__":
    main()
