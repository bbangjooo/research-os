from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path
from unittest import mock

import pytest

from research_os import __version__, agent_install
from research_os.errors import ConfigurationError
from scripts.verify_release import V04_UPGRADE_CASES, _control_tree
from tests.test_agent_install_upgrade import (
    _TARGETS,
    _capture_tree,
    _exception_recovery_paths,
    _fake_managed_release,
    _write_files,
)

ROOT = Path(__file__).resolve().parents[1]
M2D_MANIFEST = json.loads(
    (ROOT / "tests/fixtures/program_memory/v3/m2d-manifest.json").read_text(encoding="utf-8")
)
SEALED_COMMITS = {
    "0.2.0": subprocess.check_output(
        ["git", "rev-parse", "6f36a1b^{commit}"], cwd=ROOT, text=True
    ).strip(),
    "0.3.0": M2D_MANIFEST["managed_upgrade"]["sealed_0_3_commit"],
}
UPGRADE_CASE_IDS = tuple(M2D_MANIFEST["managed_upgrade"]["upgrade_cases"])


def _git_bytes(commit: str, relative: Path) -> bytes:
    return subprocess.check_output(
        [
            "git",
            "show",
            f"{commit}:src/research_os/resources/research-os/{relative.as_posix()}",
        ],
        cwd=ROOT,
    )


def _managed_manifest(release: str, files: dict[Path, bytes]) -> bytes:
    value = {
        "files": [
            {
                "path": path.as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for path, content in sorted(files.items(), key=lambda item: item[0].as_posix())
        ],
        "owner": agent_install._MANIFEST_OWNER,
        "release": release,
        "schema_version": 1,
    }
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode()


def _sealed_prior(release: str) -> dict[Path, bytes]:
    commit = SEALED_COMMITS[release]
    paths = tuple(
        path
        for path in agent_install._KNOWN_MANAGED_RELEASE_FILES[release]
        if path != agent_install._MANIFEST_PATH
    )
    files = {path: _git_bytes(commit, path) for path in paths}
    files[agent_install._MANIFEST_PATH] = _managed_manifest(release, files)
    expected = agent_install._KNOWN_MANAGED_RELEASE_FILES[release]
    observed = {
        path: (len(content), hashlib.sha256(content).hexdigest()) for path, content in files.items()
    }
    assert observed == expected
    return files


def _transactions_empty(home: Path) -> bool:
    root = home / agent_install._BACKUP_ROOT_NAME
    return not root.exists() or not any(root.iterdir())


def _observe_upgrade(case_id: str, home: Path) -> dict[str, object]:
    destination = home / _TARGETS["codex"]
    if case_id in {"exact-0.2-to-0.4", "exact-0.3-to-0.4"}:
        release = "0.2.0" if case_id.startswith("exact-0.2") else "0.3.0"
        prior = _sealed_prior(release)
        _write_files(destination, prior)
        records = agent_install.install_agent_skill("codex", home=home, upgrade=True)
        recovery = Path(records[0]["recovery_backup"])
        return {
            "from_release": records[0]["from_release"],
            "to_release": records[0]["to_release"],
            "status": records[0]["status"],
            "destination_current": _capture_tree(destination)[0] == agent_install._expected_files(),
            "recovery_is_prior": _capture_tree(recovery)[0] == prior,
        }
    if case_id == "drifted-0.3-rejected-no-write":
        _write_files(destination, _sealed_prior("0.3.0"))
        (destination / "SKILL.md").write_bytes(b"drifted 0.3\n")
        before = _capture_tree(destination)
        with pytest.raises(ConfigurationError) as caught:
            agent_install.install_agent_skill("codex", home=home, upgrade=True)
        return {
            "error_type": type(caught.value).__name__,
            "destination_unchanged": _capture_tree(destination) == before,
            "transactions_empty": _transactions_empty(home),
        }
    if case_id == "unknown-release-rejected-no-write":
        _write_files(destination, _fake_managed_release("9.9.9"))
        before = _capture_tree(destination)
        with pytest.raises(ConfigurationError) as caught:
            agent_install.install_agent_skill("codex", home=home, upgrade=True)
        return {
            "error_type": type(caught.value).__name__,
            "destination_unchanged": _capture_tree(destination) == before,
            "transactions_empty": _transactions_empty(home),
        }
    if case_id == "commit-failure-restores-prior":
        prior = _sealed_prior("0.3.0")
        destinations = {target: home / relative for target, relative in _TARGETS.items()}
        for target in destinations.values():
            _write_files(target, prior)
        before = {name: _capture_tree(path) for name, path in destinations.items()}
        original = agent_install._commit_one

        def fail_second(prepared, expected):
            if prepared.state.target == "claude":
                raise OSError("M2-D second-target commit failure")
            return original(prepared, expected)

        with (
            mock.patch.object(agent_install, "_commit_one", side_effect=fail_second),
            pytest.raises(OSError) as caught,
        ):
            agent_install.install_agent_skill("all", home=home, upgrade=True)
        return {
            "error_type": type(caught.value).__name__,
            "codex_unchanged": _capture_tree(destinations["codex"]) == before["codex"],
            "claude_unchanged": _capture_tree(destinations["claude"]) == before["claude"],
        }
    if case_id == "publish-failure-retains-recovery":
        prior = _sealed_prior("0.3.0")
        _write_files(destination, prior)
        original = agent_install._rename_noreplace
        calls = 0

        def publish_then_fail(source: Path, target: Path) -> None:
            nonlocal calls
            calls += 1
            original(source, target)
            if calls == 2:
                raise OSError("M2-D publish failure")

        with (
            mock.patch.object(agent_install, "_rename_noreplace", side_effect=publish_then_fail),
            pytest.raises(OSError) as caught,
        ):
            agent_install.install_agent_skill("codex", home=home, upgrade=True)
        recovery = _exception_recovery_paths(caught.value)
        return {
            "error_type": type(caught.value).__name__,
            "destination_is_prior": _capture_tree(destination)[0] == prior,
            "recovery_count": len(recovery),
            "recovery_is_current": len(recovery) == 1
            and _capture_tree(recovery[0])[0] == agent_install._expected_files(),
        }
    raise AssertionError(case_id)


@pytest.mark.parametrize("case_id", UPGRADE_CASE_IDS, ids=UPGRADE_CASE_IDS)
def test_v04_managed_upgrade_subcase(case_id: str, tmp_path: Path) -> None:
    observed = _observe_upgrade(case_id, tmp_path)
    expected = next(case["expected"] for case in V04_UPGRADE_CASES if case["id"] == case_id)
    assert observed == expected


def _strict_external_tree(path: Path) -> dict[str, object]:
    base = _control_tree(path)
    digest = hashlib.sha256()
    if not path.exists():
        digest.update(b"absent")
        return {**base, "metadata_sha256": digest.hexdigest(), "symlink_count": 0}
    symlinks = 0
    for current, directories, files in os.walk(path, followlinks=False):
        for name in sorted([*directories, *files]):
            item = Path(current) / name
            info = item.lstat()
            symlinks += int(stat.S_ISLNK(info.st_mode))
            relative = item.relative_to(path).as_posix().encode()
            digest.update(len(relative).to_bytes(8, "big") + relative)
            digest.update(stat.S_IMODE(info.st_mode).to_bytes(4, "big"))
            digest.update(info.st_size.to_bytes(8, "big"))
    return {**base, "metadata_sha256": digest.hexdigest(), "symlink_count": symlinks}


def test_external_three_project_snapshot_is_independent_and_read_only() -> None:
    expected = M2D_MANIFEST["external_read_only"]["projects"]
    roots = {name: ROOT.parent / name / ".research-os" for name in expected}
    before = {name: _strict_external_tree(path) for name, path in roots.items()}
    assert {
        name: {key: value[key] for key in ("exists", "entry_count", "sha256")}
        for name, value in before.items()
    } == expected
    assert all(value["symlink_count"] == 0 for value in before.values())
    assert roots["BinancePredictionStrategy"].exists() is False
    after = {name: _strict_external_tree(path) for name, path in roots.items()}
    assert after == before
    assert roots["BinancePredictionStrategy"].exists() is False


def test_v04_release_contract_binds_all_literal_ids() -> None:
    ids = [case["id"] for case in M2D_MANIFEST["cases"]]
    assert len(ids) == len(set(ids)) == 23
    assert UPGRADE_CASE_IDS == (
        "exact-0.2-to-0.4",
        "exact-0.3-to-0.4",
        "drifted-0.3-rejected-no-write",
        "unknown-release-rejected-no-write",
        "commit-failure-restores-prior",
        "publish-failure-retains-recovery",
    )
    assert M2D_MANIFEST["release"]["version"] == __version__ == "0.4.0"
