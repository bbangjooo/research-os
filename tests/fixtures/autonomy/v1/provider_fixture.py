"""Minimal external process used to exercise the M3-A JSON provider port."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _valid(request_bytes: bytes, packet_path: Path, record_path: Path) -> int:
    request = json.loads(request_bytes)
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    if packet["provider_request_id"] != request["provider_request_id"]:
        return 3
    record_path.write_bytes(request_bytes)
    sys.stdout.write(json.dumps(packet, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


def main() -> int:
    mode = sys.argv[1]
    request_bytes = sys.stdin.buffer.read()
    if mode == "valid":
        return _valid(request_bytes, Path(sys.argv[2]), Path(sys.argv[3]))
    if mode == "duplicate_key":
        sys.stdout.write('{"packet":1,"packet":2}')
        return 0
    if mode == "nonfinite":
        sys.stdout.write('{"packet":NaN}')
        return 0
    if mode == "extra_stdout":
        sys.stdout.write("{}\nnot-json")
        return 0
    if mode == "timeout":
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        Path(sys.argv[2]).write_text(str(child.pid), encoding="ascii")
        time.sleep(60)
        return 0
    if mode == "output_limit":
        block = b"x" * 4096
        for _ in range(256):
            os.write(sys.stdout.fileno(), block)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
