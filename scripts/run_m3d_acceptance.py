#!/usr/bin/env python3
"""Run the one armed M3-D acceptance and print its immutable final receipt."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from scripts.verify_v05_release import (
    CUSTODY_PATH,
    MANIFEST_PATH,
    PREARM_PATH,
    RACE_PATH,
    RECEIPT_PATH,
    SUITE_PATH,
    V05ReleaseGateError,
    collect_runtime_evidence,
    reproduce_benchmark,
    strict_json,
    validate_prearm,
)


def _exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def run_acceptance() -> dict[str, Any]:
    if RECEIPT_PATH.exists():
        raise V05ReleaseGateError("an immutable v0.5 acceptance receipt already exists")
    manifest = strict_json(MANIFEST_PATH)
    suite = strict_json(SUITE_PATH)
    race = strict_json(RACE_PATH)
    prearm = strict_json(PREARM_PATH)
    custody = strict_json(CUSTODY_PATH)
    if custody.get("nonce_call_count") != 1 or custody.get("arms_started") is not False:
        raise V05ReleaseGateError("custody transcript is not an unused one-draw seal")
    nonce = custody.get("acceptance_nonce")
    if not isinstance(nonce, str):
        raise V05ReleaseGateError("acceptance nonce is missing")
    custody_directory = Path(custody["repository_external_directory"])
    bundle_path = Path(custody["bundle_path"])
    if custody_directory == MANIFEST_PATH.parents[4] or MANIFEST_PATH.parents[4] in custody_directory.parents:
        raise V05ReleaseGateError("custody path is not repository-external")
    bundle_bytes = bundle_path.read_bytes()
    if hashlib.sha256(bundle_bytes).hexdigest() != custody.get("bundle_sha256"):
        raise V05ReleaseGateError("repository-external custody bundle changed")
    bundle = json.loads(bundle_bytes)
    if bundle != {"nonce": nonce, "suite": suite, "race": race, "prearm": prearm}:
        raise V05ReleaseGateError("checked-in acceptance artifacts differ from custody bundle")
    external_transcript = strict_json(Path(custody["custodian_transcript_path"]))
    reservation = strict_json(Path(custody["draw_reservation_path"]))
    if (
        external_transcript.get("acceptance_nonce") != nonce
        or external_transcript.get("nonce_call_count") != 1
        or external_transcript.get("code_commit") != prearm.get("code_commit")
        or reservation.get("state") != "reserved-before-nonce"
        or reservation.get("code_commit") != prearm.get("code_commit")
    ):
        raise V05ReleaseGateError("durable custodian reservation/transcript mismatch")
    current = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    if current:
        raise V05ReleaseGateError("acceptance requires a clean prearm checkpoint")
    validate_prearm(manifest, suite, race, prearm, nonce)
    arm_reservation_path = custody_directory / "arm-run-reservation.json"
    external_result_path = custody_directory / "acceptance-result.json"
    reservation_body = {
        "arm_run_reservation_schema_version": 1,
        "state": "reserved-before-arms",
        "code_commit": prearm["code_commit"],
        "prearm_seal_sha256": prearm["seal_sha256"],
        "suite_sha256": prearm["suite_sha256"],
        "race_suite_sha256": prearm["race_suite_sha256"],
        "arm_order": prearm["arm_order"],
        "authorized_action": None,
    }
    try:
        _exclusive_json(arm_reservation_path, reservation_body)
    except FileExistsError as exc:
        raise V05ReleaseGateError(
            "this custody draw already reserved its single arm execution"
        ) from exc
    try:
        benchmark = reproduce_benchmark(nonce=nonce, suite=suite, race=race, prearm=prearm)
        runtime = collect_runtime_evidence(manifest, race)
    except BaseException as exc:
        failure = {
            "receipt_schema_version": 1,
            "kind": "research_os.v0.5.acceptance_release_receipt",
            "release": "0.5.0",
            "result": "FAIL",
            "classification": "GENUINE-FINDING_OR_RESULT-INVALID_REVIEW_REQUIRED",
            "error_type": type(exc).__name__,
            "error": str(exc),
            "prearm_seal_sha256": prearm["seal_sha256"],
            "arm_run_reservation_path": str(arm_reservation_path),
            "authorized_action": None,
            "product_multi_agent": False,
            "live_migration": False,
        }
        _exclusive_json(external_result_path, failure)
        raise
    receipt = {
        "receipt_schema_version": 1,
        "kind": "research_os.v0.5.acceptance_release_receipt",
        "release": "0.5.0",
        "result": "PASS",
        "acceptance_nonce": nonce,
        "prearm_seal_sha256": prearm["seal_sha256"],
        "benchmark": benchmark,
        "runtime": runtime,
        "custody": {
            "arm_run_reservation_path": str(arm_reservation_path),
            "external_result_path": str(external_result_path),
        },
        "authorized_action": None,
        "product_multi_agent": False,
        "live_migration": False,
    }
    _exclusive_json(external_result_path, receipt)
    return receipt


def main(argv: Sequence[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else list(argv)
    if values:
        print("M3-D acceptance FAIL: arguments are forbidden", file=sys.stderr)
        return 2
    try:
        receipt = run_acceptance()
    except (KeyError, TypeError, ValueError, OSError, V05ReleaseGateError) as exc:
        failure = {
            "receipt_schema_version": 1,
            "kind": "research_os.v0.5.acceptance_release_receipt",
            "release": "0.5.0",
            "result": "FAIL",
            "classification": "GENUINE-FINDING_OR_RESULT-INVALID_REVIEW_REQUIRED",
            "error": str(exc),
            "authorized_action": None,
            "product_multi_agent": False,
            "live_migration": False,
        }
        print(json.dumps(failure, sort_keys=True, separators=(",", ":")))
        return 1
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
