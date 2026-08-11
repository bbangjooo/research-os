#!/usr/bin/env python3
"""Create exactly one repository-external M3-D acceptance draw without running arms."""

from __future__ import annotations

import hashlib
import json
import platform
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence

from research_os.meta_evaluation import (
    generate_race_suite,
    generate_suite,
    load_generator_manifest,
    prearm_seal,
    suite_digest,
)
from scripts.verify_v05_release import (
    GENERATOR_PATH,
    PREARM_PATH,
    RACE_PATH,
    RECEIPT_PATH,
    ROOT,
    SUITE_PATH,
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def prepare() -> dict[str, Any]:
    if _git("status", "--porcelain"):
        raise RuntimeError("acceptance preparation requires a clean code-freeze checkpoint")
    for path in (SUITE_PATH, RACE_PATH, PREARM_PATH, RECEIPT_PATH):
        if path.exists():
            raise RuntimeError(f"acceptance artifact already exists: {path}")
    code_commit = _git("rev-parse", "HEAD")
    manifest = load_generator_manifest(GENERATOR_PATH)
    nonce = secrets.token_hex(32)
    suite = generate_suite(manifest, nonce)
    race = generate_race_suite(manifest, nonce)
    arm_order = ("v0.2", "v0.5") if int(nonce[:2], 16) % 2 == 0 else ("v0.5", "v0.2")
    environment = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "implementation": platform.python_implementation(),
    }
    generator_sha = _sha256(GENERATOR_PATH.read_bytes())
    source_sha = _sha256((ROOT / "src/research_os/meta_evaluation.py").read_bytes())
    prearm = prearm_seal(
        code_commit=code_commit,
        generator_manifest_sha256=generator_sha,
        generator_source_sha256=source_sha,
        v02_agent_sha256=manifest["arms"]["v0.2"]["agent_source_sha256"],
        v02_skill_sha256=manifest["arms"]["v0.2"]["packaged_skill_sha256"],
        nonce_commitment_sha256=suite["nonce_commitment_sha256"],
        suite_sha256=suite_digest(suite),
        race_suite_sha256=suite_digest(race),
        arm_order=arm_order,
        environment=environment,
    )
    custody = Path(tempfile.mkdtemp(prefix="research-os-m3d-custody-"))
    if ROOT == custody or ROOT in custody.parents or custody in ROOT.parents:
        raise RuntimeError("custody directory must be outside the repository")
    bundle = {"nonce": nonce, "suite": suite, "race": race, "prearm": prearm}
    bundle_bytes = json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    bundle_path = custody / "acceptance-bundle.json"
    bundle_path.write_bytes(bundle_bytes)
    bundle_path.chmod(0o600)
    transcript = {
        "custody_transcript_schema_version": 1,
        "nonce_source": "secrets.token_hex(32)",
        "nonce_call_count": 1,
        "acceptance_nonce": nonce,
        "nonce_commitment_sha256": suite["nonce_commitment_sha256"],
        "repository_external_directory": str(custody),
        "bundle_path": str(bundle_path),
        "bundle_sha256": _sha256(bundle_bytes),
        "arms_started": False,
        "authorized_action": None,
    }
    return {"suite": suite, "race": race, "prearm": prearm, "custody": transcript}


def main(argv: Sequence[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else list(argv)
    if values:
        print("M3-D preparation FAIL: arguments are forbidden", file=sys.stderr)
        return 2
    try:
        result = prepare()
    except (KeyError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"M3-D preparation FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
