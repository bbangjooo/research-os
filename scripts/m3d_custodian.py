#!/usr/bin/env python3
"""Own the one irreversible, repository-external M3-D nonce reservation."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
import subprocess
import sys
from pathlib import Path
from typing import Any, Sequence

ROOT = Path(__file__).resolve().parents[1]
CUSTODY_PARENT = Path.home() / ".research-os-custody" / "m3d-v05"


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


def _safe_parent(path: Path) -> None:
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            current.mkdir(mode=0o700)
            info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise RuntimeError(f"unsafe custody directory: {current}")


def reserve_draw(code_commit: str, *, custody_parent: Path = CUSTODY_PARENT) -> dict[str, Any]:
    if len(code_commit) != 40 or any(item not in "0123456789abcdef" for item in code_commit):
        raise RuntimeError("code commit must be a full lowercase git SHA")
    _safe_parent(custody_parent)
    custody = custody_parent / code_commit
    try:
        custody.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise RuntimeError(
            "this code checkpoint already has a durable M3-D draw reservation"
        ) from exc
    reservation = {
        "reservation_schema_version": 1,
        "code_commit": code_commit,
        "state": "reserved-before-nonce",
        "authorized_action": None,
    }
    reservation_path = custody / "draw-reservation.json"
    descriptor = os.open(
        reservation_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        os.write(descriptor, _canonical(reservation))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    nonce = secrets.token_hex(32)
    transcript = {
        "custodian_transcript_schema_version": 1,
        "code_commit": code_commit,
        "nonce_source": "secrets.token_hex(32)",
        "nonce_call_count": 1,
        "acceptance_nonce": nonce,
        "nonce_commitment_sha256": hashlib.sha256(bytes.fromhex(nonce)).hexdigest(),
        "reservation_path": str(reservation_path),
        "custody_directory": str(custody),
        "authorized_action": None,
    }
    transcript_path = custody / "nonce-transcript.json"
    descriptor = os.open(
        transcript_path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        os.write(descriptor, _canonical(transcript))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent_descriptor = os.open(custody, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)
    return transcript


def main(argv: Sequence[str] | None = None) -> int:
    values = sys.argv[1:] if argv is None else list(argv)
    if values:
        print("M3-D custodian FAIL: arguments are forbidden", file=sys.stderr)
        return 2
    try:
        status = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ).strip()
        if status:
            raise RuntimeError("custodian requires a clean code-freeze checkpoint")
        code_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        transcript = reserve_draw(code_commit)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"M3-D custodian FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(transcript, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
