#!/usr/bin/env python3
"""Run the one armed M3-D acceptance and print its immutable final receipt."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

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
    current = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
    if current:
        raise V05ReleaseGateError("acceptance requires a clean prearm checkpoint")
    validate_prearm(manifest, suite, race, prearm, nonce)
    benchmark = reproduce_benchmark(nonce=nonce, suite=suite, race=race, prearm=prearm)
    runtime = collect_runtime_evidence(manifest, race)
    return {
        "receipt_schema_version": 1,
        "kind": "research_os.v0.5.acceptance_release_receipt",
        "release": "0.5.0",
        "result": "PASS",
        "acceptance_nonce": nonce,
        "prearm_seal_sha256": prearm["seal_sha256"],
        "benchmark": benchmark,
        "runtime": runtime,
        "authorized_action": None,
        "product_multi_agent": False,
        "live_migration": False,
    }


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
