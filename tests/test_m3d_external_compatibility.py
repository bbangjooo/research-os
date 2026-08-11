from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

import pytest

from research_os.kernel._canonical import canonical_bytes
from research_os.kernel.events import EventLog
from research_os.kernel.ids import stable_id
from research_os.memory import create_legacy_opaque_record, validate_legacy_content
from research_os.science import reduce_scientific_state

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = (
    ROOT / "tests/fixtures/meta_evaluation/v1/external-read-only-manifest.json"
)
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
PROJECTS = tuple(MANIFEST["projects"])


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _complete_event_count(root: Path) -> int:
    path = root / "runtime/events.jsonl"
    if not path.is_file() or path.is_symlink():
        return 0
    data = path.read_bytes()
    if not data or not data.endswith(b"\n") or b"\n\n" in data:
        return 0
    return len(data.splitlines())


def _select_control_root(top_level: Path) -> tuple[Path, str]:
    root = top_level / ".research-os"
    if _complete_event_count(root) > 0:
        return root, "non-empty-root"
    candidates = sorted(
        (
            (_complete_event_count(candidate), candidate)
            for candidate in top_level.rglob(".research-os")
            if candidate.is_dir() and not candidate.is_symlink()
        ),
        key=lambda item: (-item[0], item[1].as_posix()),
    )
    positive = [item for item in candidates if item[0] > 0]
    if not positive:
        raise AssertionError(f"no non-empty Research OS root under {top_level}")
    return positive[0][1], "nested-max-event-count"


def _read_regular_bytes(path: Path) -> bytes:
    before = path.lstat()
    assert stat.S_ISREG(before.st_mode)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        assert (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino)
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _strict_tree(root: Path) -> dict[str, Any]:
    assert root.is_dir() and not root.is_symlink()
    digest = hashlib.sha256()
    entries = 0
    for current, directories, files in os.walk(root, followlinks=False):
        directories.sort()
        files.sort()
        for name in [*directories, *files]:
            path = Path(current) / name
            info = path.lstat()
            relative = path.relative_to(root).as_posix().encode()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISLNK(info.st_mode):
                kind = b"l"
                content = os.readlink(path).encode()
            elif stat.S_ISDIR(info.st_mode):
                kind = b"d"
                content = b""
            elif stat.S_ISREG(info.st_mode):
                kind = b"f"
                content = _read_regular_bytes(path)
            else:
                raise AssertionError(f"unsupported external entry: {path}")
            digest.update(kind)
            digest.update(len(relative).to_bytes(8, "big") + relative)
            digest.update(mode.to_bytes(4, "big"))
            digest.update(len(content).to_bytes(8, "big") + content)
            entries += 1
    return {"entry_count": entries, "tree_sha256": digest.hexdigest()}


def _state_sha256(value: dict[str, Any]) -> str:
    return _sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def test_external_manifest_is_literal_and_non_vacuous() -> None:
    assert set(MANIFEST) == {
        "schema_version",
        "manifest_id",
        "status",
        "selection_rule",
        "projects",
        "requirements",
        "authorized_action",
    }
    assert MANIFEST["schema_version"] == 1
    assert MANIFEST["status"] == "precommitted-before-acceptance-nonce"
    assert MANIFEST["authorized_action"] is None
    assert [case["name"] for case in PROJECTS] == [
        "crypto-new",
        "manager",
        "BinancePredictionStrategy",
    ]
    assert [case["event_count"] for case in PROJECTS] == [1, 15, 32]
    assert all(case["event_count"] > 0 for case in PROJECTS)


@pytest.mark.parametrize("case", PROJECTS, ids=lambda case: case["name"])
def test_external_project_exact_replay_opaque_and_zero_write(
    case: dict[str, Any], tmp_path: Path
) -> None:
    top_level = Path(case["top_level_root"])
    selected, selection_kind = _select_control_root(top_level)
    assert selected == Path(case["selected_control_root"])
    assert selection_kind == case["selection_kind"]
    before = _strict_tree(selected)

    source_events = _read_regular_bytes(selected / "runtime/events.jsonl")
    assert _sha256(source_events) == case["event_bytes_sha256"]
    temporary_log_path = tmp_path / "runtime/events.jsonl"
    temporary_log_path.parent.mkdir(parents=True)
    temporary_log_path.write_bytes(source_events)
    temporary_log_path.chmod(0o600)
    events = EventLog(temporary_log_path, case["project_id"]).read()
    reconstructed = b"".join(canonical_bytes(event.to_dict()) + b"\n" for event in events)
    assert reconstructed == source_events
    assert len(events) == case["event_count"]
    assert events[-1].hash == case["event_head_sha256"]
    state = reduce_scientific_state(events, project_id=case["project_id"]).to_dict()
    assert _state_sha256(state) == case["science_state_sha256"]
    assert reduce_scientific_state(
        EventLog(temporary_log_path, case["project_id"]).read(),
        project_id=case["project_id"],
    ).to_dict() == state

    opaque_path = selected / case["opaque_source"]
    opaque_content = _read_regular_bytes(opaque_path)
    assert len(opaque_content) == case["opaque_bytes"]
    assert _sha256(opaque_content) == case["opaque_sha256"]
    record = create_legacy_opaque_record(
        program_id=stable_id("program", case["name"], "m3d-read-only"),
        source_project_id=case["project_id"],
        source_kind="file",
        source_locator=case["opaque_source"],
        content=opaque_content,
        media_type="text/markdown",
    )
    validate_legacy_content(record, opaque_content)
    assert record.classification == "legacy_unstructured"
    assert record.typed_claim_ids == ()
    assert record.authorized_action is None
    assert opaque_content not in canonical_bytes(record.to_dict())

    after = _strict_tree(selected)
    assert after == before
