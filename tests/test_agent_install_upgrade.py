from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

from research_os import agent_install as installer
from research_os.agent_install import install_agent_skill
from research_os.errors import ConfigurationError

_TARGETS = {
    "codex": Path(".agents/skills/research-os"),
    "claude": Path(".claude/skills/research-os"),
}
_FAKE_LEGACY = {
    Path("SKILL.md"): b"legacy skill\n",
    Path("agents/openai.yaml"): b"legacy agent\n",
    Path("references/status-actions.md"): b"legacy status actions\n",
}


def _fake_managed_release(release: str) -> dict[Path, bytes]:
    packaged = {
        Path("SKILL.md"): b"managed prior skill\n",
        Path("agents/openai.yaml"): b"managed prior agent\n",
        Path("references/scientific-protocol.md"): b"managed prior protocol\n",
        Path("references/status-actions.md"): b"managed prior actions\n",
    }
    manifest = {
        "files": [
            {
                "path": relative.as_posix(),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
            for relative, content in sorted(
                packaged.items(), key=lambda item: item[0].as_posix()
            )
        ],
        "owner": installer._MANIFEST_OWNER,
        "release": release,
        "schema_version": 1,
    }
    return {
        **packaged,
        installer._MANIFEST_PATH: (
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("utf-8"),
    }


def _write_files(root: Path, files: dict[Path, bytes]) -> None:
    root.mkdir(parents=True)
    for relative, content in files.items():
        output = root / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(content)


def _capture_tree(root: Path) -> tuple[dict[Path, bytes], frozenset[Path]]:
    files: dict[Path, bytes] = {}
    directories: set[Path] = set()
    for entry in root.rglob("*"):
        relative = entry.relative_to(root)
        if entry.is_dir():
            directories.add(relative)
        else:
            files[relative] = entry.read_bytes()
    return files, frozenset(directories)


def _write_test_xattr(path: Path, name: str, value: bytes) -> None:
    if sys.platform == "darwin":
        subprocess.run(
            ["/usr/bin/xattr", "-wx", name, value.hex(), os.fspath(path)],
            check=True,
            capture_output=True,
        )
        return
    setter = getattr(os, "setxattr", None)
    if setter is None:
        raise AssertionError("test platform does not expose extended attributes")
    setter(path, name, value)


def _read_test_xattr(path: Path, name: str) -> bytes:
    if sys.platform == "darwin":
        result = subprocess.run(
            ["/usr/bin/xattr", "-px", name, os.fspath(path)],
            check=True,
            capture_output=True,
        )
        return bytes.fromhex(result.stdout.decode("ascii"))
    getter = getattr(os, "getxattr", None)
    if getter is None:
        raise AssertionError("test platform does not expose extended attributes")
    return getter(path, name)


@contextmanager
def _recognize_fake_legacy():
    signatures = {
        relative: (len(content), hashlib.sha256(content).hexdigest())
        for relative, content in _FAKE_LEGACY.items()
    }
    with mock.patch.object(installer, "_LEGACY_0_1_0_FILES", signatures):
        yield


@contextmanager
def _recognize_fake_managed_0_2():
    files = _fake_managed_release("0.2.0")
    signatures = {
        relative: (len(content), hashlib.sha256(content).hexdigest())
        for relative, content in files.items()
    }
    with mock.patch.object(
        installer,
        "_KNOWN_MANAGED_RELEASE_FILES",
        {"0.2.0": signatures},
    ):
        yield files


def _assert_no_transactions(test: unittest.TestCase, home: Path) -> None:
    recovery_root = home / installer._BACKUP_ROOT_NAME
    if recovery_root.exists():
        test.assertEqual(list(recovery_root.iterdir()), [])


def _exception_recovery_paths(exception: BaseException) -> tuple[Path, ...]:
    return tuple(Path(value) for value in getattr(exception, "recovery_paths", ()))


def _exception_rollback_errors(exception: BaseException) -> tuple[str, ...]:
    return tuple(getattr(exception, "rollback_errors", ()))


def _assert_reported_recoveries(
    test: unittest.TestCase,
    exception: BaseException,
    home: Path,
    *,
    count: int = 1,
) -> tuple[Path, ...]:
    paths = _exception_recovery_paths(exception)
    test.assertEqual(len(paths), count)
    recovery_root = (home / installer._BACKUP_ROOT_NAME).resolve()
    for path in paths:
        test.assertTrue(path.is_absolute())
        test.assertTrue(path.is_relative_to(recovery_root))
        test.assertTrue(path.exists())
    return paths


class AgentInstallUpgradeTests(unittest.TestCase):
    def test_recovery_details_attach_only_valid_structured_rollback_errors(self):
        failure = KeyboardInterrupt("cancelled")

        installer._attach_recovery_details(
            failure,
            (),
            rollback_errors=("codex: restore failed", "", "   "),
        )

        self.assertEqual(
            _exception_rollback_errors(failure),
            ("codex: restore failed",),
        )

    def test_upgrade_mode_supports_first_install_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            installed = install_agent_skill("all", home=home, upgrade=True)
            self.assertEqual({record["status"] for record in installed}, {"installed"})
            for relative in _TARGETS.values():
                manifest_path = home / relative / installer._MANIFEST_PATH
                manifest_bytes = manifest_path.read_bytes()
                manifest = json.loads(manifest_bytes)
                self.assertEqual(manifest["owner"], "research-os-agent-skill")
                self.assertEqual(manifest["schema_version"], 1)
                self.assertEqual(
                    manifest_bytes,
                    installer._managed_manifest(installer._packaged_files()),
                )

            repeated = install_agent_skill("all", home=home, upgrade=True)
            self.assertEqual({record["status"] for record in repeated}, {"already_current"})
            _assert_no_transactions(self, home)

    def test_exact_legacy_requires_upgrade_and_then_becomes_managed(self):
        with tempfile.TemporaryDirectory() as temporary, _recognize_fake_legacy():
            home = Path(temporary)
            destination = home / _TARGETS["codex"]
            _write_files(destination, _FAKE_LEGACY)
            before = _capture_tree(destination)

            with self.assertRaisesRegex(ConfigurationError, "--upgrade"):
                install_agent_skill("codex", home=home)
            self.assertEqual(_capture_tree(destination), before)

            records = install_agent_skill("codex", home=home, upgrade=True)
            self.assertEqual(records[0]["status"], "upgraded")
            self.assertEqual(records[0]["from_release"], "0.1.0")
            self.assertEqual(_capture_tree(destination)[0], installer._expected_files())
            recovery = Path(records[0]["recovery_backup"])
            self.assertEqual(_capture_tree(recovery)[0], _FAKE_LEGACY)
            self.assertEqual(
                recovery.parent.parent,
                home.resolve() / installer._BACKUP_ROOT_NAME,
            )
            self.assertTrue(recovery.parent.name.startswith("codex-upgrade-0.1.0-"))

    def test_exact_managed_0_2_requires_upgrade_and_retains_recovery(self):
        with tempfile.TemporaryDirectory() as temporary, _recognize_fake_managed_0_2() as prior:
            home = Path(temporary)
            destination = home / _TARGETS["codex"]
            _write_files(destination, prior)
            before = _capture_tree(destination)

            with self.assertRaisesRegex(ConfigurationError, "--upgrade"):
                install_agent_skill("codex", home=home)
            self.assertEqual(_capture_tree(destination), before)

            records = install_agent_skill("codex", home=home, upgrade=True)
            self.assertEqual(records[0]["status"], "upgraded")
            self.assertEqual(records[0]["from_release"], "0.2.0")
            self.assertEqual(records[0]["to_release"], "0.3.0")
            self.assertEqual(_capture_tree(destination)[0], installer._expected_files())
            recovery = Path(records[0]["recovery_backup"])
            self.assertEqual(_capture_tree(recovery)[0], prior)
            self.assertTrue(recovery.name.startswith("prior-0.2.0-recovery"))

    def test_managed_0_2_two_target_failure_restores_both_exactly(self):
        with tempfile.TemporaryDirectory() as temporary, _recognize_fake_managed_0_2() as prior:
            home = Path(temporary)
            destinations = {target: home / relative for target, relative in _TARGETS.items()}
            for destination in destinations.values():
                _write_files(destination, prior)
            before = {
                target: _capture_tree(destination)
                for target, destination in destinations.items()
            }
            original_commit = installer._commit_one

            def fail_second(prepared, expected):
                if prepared.state.target == "claude":
                    raise OSError("managed 0.2 second target failure")
                return original_commit(prepared, expected)

            with (
                mock.patch.object(installer, "_commit_one", side_effect=fail_second),
                self.assertRaisesRegex(OSError, "second target failure"),
            ):
                install_agent_skill("all", home=home, upgrade=True)

            for target, destination in destinations.items():
                self.assertEqual(_capture_tree(destination), before[target])

    def test_all_can_upgrade_one_target_and_first_install_the_other(self):
        with tempfile.TemporaryDirectory() as temporary, _recognize_fake_legacy():
            home = Path(temporary)
            codex = home / _TARGETS["codex"]
            _write_files(codex, _FAKE_LEGACY)

            records = install_agent_skill("all", home=home, upgrade=True)

            self.assertEqual(
                {record["target"]: record["status"] for record in records},
                {"codex": "upgraded", "claude": "installed"},
            )
            for relative in _TARGETS.values():
                self.assertEqual(_capture_tree(home / relative)[0], installer._expected_files())

    def test_drift_unknown_markers_and_extra_directories_are_rejected(self):
        mutations = {
            "modified file": lambda destination, outside: (destination / "SKILL.md").write_text(
                "local change\n", encoding="utf-8"
            ),
            "extra file": lambda destination, outside: (destination / "local.txt").write_text(
                "local\n", encoding="utf-8"
            ),
            "extra empty directory": lambda destination, outside: (
                destination / "empty-local-directory"
            ).mkdir(),
            "unknown marker": lambda destination, outside: (
                destination / installer._MANIFEST_PATH
            ).write_text(
                '{"owner":"someone-else","release":"99.0.0"}\n',
                encoding="utf-8",
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                install_agent_skill("codex", home=home)
                destination = home / _TARGETS["codex"]
                mutate(destination, home / "outside")
                before = _capture_tree(destination)

                with self.assertRaises(ConfigurationError):
                    install_agent_skill("codex", home=home, upgrade=True)

                self.assertEqual(_capture_tree(destination), before)

    def test_nested_and_destination_symlinks_are_rejected_without_following(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            install_agent_skill("codex", home=home)
            destination = home / _TARGETS["codex"]
            outside = home / "outside.md"
            outside.write_text("outside\n", encoding="utf-8")
            skill = destination / "SKILL.md"
            skill.unlink()
            skill.symlink_to(outside)

            with self.assertRaises(ConfigurationError):
                install_agent_skill("codex", home=home, upgrade=True)
            self.assertEqual(outside.read_text(encoding="utf-8"), "outside\n")

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            parent = home / _TARGETS["claude"].parent
            parent.mkdir(parents=True)
            outside = home / "outside"
            outside.mkdir()
            (parent / "research-os").symlink_to(outside, target_is_directory=True)

            with self.assertRaises(ConfigurationError):
                install_agent_skill("claude", home=home, upgrade=True)
            self.assertEqual(list(outside.iterdir()), [])

    def test_special_file_and_symlinked_ancestor_are_rejected(self):
        if hasattr(os, "mkfifo"):
            with tempfile.TemporaryDirectory() as temporary:
                home = Path(temporary)
                destination = home / _TARGETS["codex"]
                destination.mkdir(parents=True)
                os.mkfifo(destination / "pipe")
                with self.assertRaises(ConfigurationError):
                    install_agent_skill("codex", home=home, upgrade=True)

        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            outside = home / "outside"
            outside.mkdir()
            (home / ".agents").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ConfigurationError):
                install_agent_skill("codex", home=home, upgrade=True)
            self.assertEqual(list(outside.iterdir()), [])

    def test_staging_failure_on_second_target_preserves_both(self):
        with tempfile.TemporaryDirectory() as temporary, _recognize_fake_legacy():
            home = Path(temporary)
            destinations = {target: home / relative for target, relative in _TARGETS.items()}
            for destination in destinations.values():
                _write_files(destination, _FAKE_LEGACY)
            before = {
                target: _capture_tree(destination) for target, destination in destinations.items()
            }
            original_stage = installer._stage_one

            def fail_claude_stage(state, resolved_home, expected):
                if state.target == "claude":
                    raise OSError("simulated second-target staging failure")
                return original_stage(state, resolved_home, expected)

            with (
                mock.patch.object(installer, "_stage_one", side_effect=fail_claude_stage),
                self.assertRaisesRegex(OSError, "staging failure"),
            ):
                install_agent_skill("all", home=home, upgrade=True)

            for target, destination in destinations.items():
                self.assertEqual(_capture_tree(destination), before[target])
            _assert_no_transactions(self, home)

    def test_second_commit_failure_rolls_back_first_target(self):
        for failure in (OSError("commit failed"), KeyboardInterrupt("cancelled")):
            with (
                self.subTest(failure=type(failure).__name__),
                tempfile.TemporaryDirectory() as temporary,
                _recognize_fake_legacy(),
            ):
                home = Path(temporary)
                destinations = {target: home / relative for target, relative in _TARGETS.items()}
                for destination in destinations.values():
                    _write_files(destination, _FAKE_LEGACY)
                before = {
                    target: _capture_tree(destination)
                    for target, destination in destinations.items()
                }
                original_commit = installer._commit_one

                def fail_claude_commit(
                    prepared, expected, *, injected=failure, commit=original_commit
                ):
                    if prepared.state.target == "claude":
                        raise injected
                    return commit(prepared, expected)

                with (
                    mock.patch.object(installer, "_commit_one", side_effect=fail_claude_commit),
                    self.assertRaises(type(failure)) as caught,
                ):
                    install_agent_skill("all", home=home, upgrade=True)

                for target, destination in destinations.items():
                    self.assertEqual(_capture_tree(destination), before[target])
                recovery = _assert_reported_recoveries(self, caught.exception, home)[0]
                self.assertEqual(_capture_tree(recovery)[0], installer._expected_files())

    def test_upgrade_rollback_recovers_rename_that_succeeded_then_raised(self):
        failure_types = (OSError, KeyboardInterrupt)
        for rename_step in (1, 2):
            for failure_type in failure_types:
                with (
                    self.subTest(rename_step=rename_step, failure=failure_type.__name__),
                    tempfile.TemporaryDirectory() as temporary,
                    _recognize_fake_legacy(),
                ):
                    home = Path(temporary)
                    destination = home / _TARGETS["codex"]
                    _write_files(destination, _FAKE_LEGACY)
                    before = _capture_tree(destination)
                    original_rename = installer._rename_noreplace
                    calls = 0

                    def rename_then_raise(
                        source,
                        target,
                        *,
                        injected_step=rename_step,
                        injected_type=failure_type,
                        rename_impl=original_rename,
                    ):
                        nonlocal calls
                        calls += 1
                        rename_impl(source, target)
                        if calls == injected_step:
                            raise injected_type(
                                f"rename step {injected_step} completed before interruption"
                            )

                    with (
                        mock.patch.object(
                            installer, "_rename_noreplace", side_effect=rename_then_raise
                        ),
                        self.assertRaises(failure_type) as caught,
                    ):
                        install_agent_skill("codex", home=home, upgrade=True)

                    self.assertEqual(_capture_tree(destination), before)
                    if rename_step == 1:
                        self.assertEqual(_exception_recovery_paths(caught.exception), ())
                        _assert_no_transactions(self, home)
                    else:
                        recovery = _assert_reported_recoveries(self, caught.exception, home)[0]
                        self.assertEqual(_capture_tree(recovery)[0], installer._expected_files())

    def test_first_install_rollback_recovers_rename_that_succeeded_then_raised(self):
        for failure_type in (OSError, KeyboardInterrupt):
            with (
                self.subTest(failure=failure_type.__name__),
                tempfile.TemporaryDirectory() as temporary,
            ):
                home = Path(temporary)
                destination = home / _TARGETS["codex"]
                original_rename = installer._rename_noreplace
                injected = False

                def rename_then_raise(
                    source,
                    target,
                    *,
                    injected_type=failure_type,
                    rename_impl=original_rename,
                ):
                    nonlocal injected
                    rename_impl(source, target)
                    if not injected:
                        injected = True
                        raise injected_type("install rename completed before interruption")

                with (
                    mock.patch.object(
                        installer, "_rename_noreplace", side_effect=rename_then_raise
                    ),
                    self.assertRaises(failure_type) as caught,
                ):
                    install_agent_skill("codex", home=home, upgrade=True)

                self.assertFalse(destination.exists())
                self.assertFalse(destination.is_symlink())
                recovery = _assert_reported_recoveries(self, caught.exception, home)[0]
                self.assertEqual(_capture_tree(recovery)[0], installer._expected_files())

    def test_first_install_never_replaces_a_concurrently_created_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary).resolve()
            destination = home / _TARGETS["codex"]
            original_publish = installer._rename_noreplace
            attribute = (
                "com.research-os.concurrent-test"
                if sys.platform == "darwin"
                else "user.research_os.concurrent_test"
            )
            attribute_value = b"concurrent creator owns this inode"
            created_identity: tuple[int, int] | None = None
            injected = False

            def create_destination_then_publish(source: Path, target: Path) -> None:
                nonlocal created_identity, injected
                if target == destination and not injected:
                    injected = True
                    destination.mkdir(mode=0o711)
                    destination.chmod(0o711)
                    _write_test_xattr(destination, attribute, attribute_value)
                    info = destination.lstat()
                    created_identity = (info.st_dev, info.st_ino)
                original_publish(source, target)

            with (
                mock.patch.object(
                    installer,
                    "_rename_noreplace",
                    side_effect=create_destination_then_publish,
                ),
                self.assertRaises(FileExistsError),
            ):
                install_agent_skill("codex", home=home, upgrade=True)

            observed = destination.lstat()
            self.assertEqual((observed.st_dev, observed.st_ino), created_identity)
            self.assertEqual(stat.S_IMODE(observed.st_mode), 0o711)
            self.assertEqual(_read_test_xattr(destination, attribute), attribute_value)
            self.assertEqual(list(destination.iterdir()), [])
            _assert_no_transactions(self, home)

    def test_rollback_rename_never_replaces_an_intervening_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            destination = root / "destination"
            source.mkdir()
            (source / "managed.txt").write_bytes(b"managed tree\n")
            destination.mkdir(mode=0o711)
            destination.chmod(0o711)
            attribute = (
                "com.research-os.rollback-collision"
                if sys.platform == "darwin"
                else "user.research_os.rollback_collision"
            )
            attribute_value = b"do not overwrite rollback collision"
            _write_test_xattr(destination, attribute, attribute_value)
            source_info = source.lstat()
            destination_info = destination.lstat()

            with self.assertRaises(FileExistsError):
                installer._rollback_rename(
                    source,
                    destination,
                    (source_info.st_dev, source_info.st_ino),
                )

            observed_source = source.lstat()
            observed_destination = destination.lstat()
            self.assertEqual(
                (observed_source.st_dev, observed_source.st_ino),
                (source_info.st_dev, source_info.st_ino),
            )
            self.assertEqual(
                (observed_destination.st_dev, observed_destination.st_ino),
                (destination_info.st_dev, destination_info.st_ino),
            )
            self.assertEqual(stat.S_IMODE(observed_destination.st_mode), 0o711)
            self.assertEqual(
                _read_test_xattr(destination, attribute),
                attribute_value,
            )
            self.assertEqual((source / "managed.txt").read_bytes(), b"managed tree\n")

    def test_failed_fresh_install_retains_user_file_added_after_exposure(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            destination = home / _TARGETS["codex"]
            user_content = b"created after public exposure\n"
            original_commit = installer._commit_one

            def expose_edit_then_fail(prepared, expected):
                original_commit(prepared, expected)
                (prepared.state.destination / "user-created.txt").write_bytes(user_content)
                raise OSError("failure after fresh install exposure")

            with (
                mock.patch.object(installer, "_commit_one", side_effect=expose_edit_then_fail),
                self.assertRaisesRegex(OSError, "fresh install exposure") as caught,
            ):
                install_agent_skill("codex", home=home, upgrade=True)

            self.assertFalse(destination.exists())
            recovery = _assert_reported_recoveries(self, caught.exception, home)[0]
            self.assertEqual((recovery / "user-created.txt").read_bytes(), user_content)

    def test_failed_upgrade_retains_edited_exposed_new_tree(self):
        with tempfile.TemporaryDirectory() as temporary, _recognize_fake_legacy():
            home = Path(temporary)
            destinations = {target: home / relative for target, relative in _TARGETS.items()}
            for destination in destinations.values():
                _write_files(destination, _FAKE_LEGACY)
            user_content = b"new tree edit before later target failed\n"
            original_commit = installer._commit_one

            def edit_first_fail_second(prepared, expected):
                if prepared.state.target == "claude":
                    raise OSError("later upgrade target failed")
                original_commit(prepared, expected)
                (prepared.state.destination / "user-created.txt").write_bytes(user_content)

            with (
                mock.patch.object(installer, "_commit_one", side_effect=edit_first_fail_second),
                self.assertRaisesRegex(OSError, "later upgrade target") as caught,
            ):
                install_agent_skill("all", home=home, upgrade=True)

            for destination in destinations.values():
                self.assertEqual(_capture_tree(destination)[0], _FAKE_LEGACY)
            recovery = _assert_reported_recoveries(self, caught.exception, home)[0]
            self.assertEqual((recovery / "user-created.txt").read_bytes(), user_content)

    def test_failure_cleanup_refuses_to_delete_a_prior_backup(self):
        with tempfile.TemporaryDirectory() as temporary, _recognize_fake_legacy():
            home = Path(temporary).resolve()
            expected = installer._expected_files()
            destination = home / _TARGETS["codex"]
            _write_files(destination, _FAKE_LEGACY)
            state = installer._classify_one("codex", home, expected, upgrade=True)
            prepared = installer._stage_one(state, home, expected)
            os.rename(destination, prepared.backup)

            errors = installer._cleanup_transactions([prepared])

            self.assertEqual(errors, [])
            self.assertEqual(_capture_tree(prepared.backup)[0], _FAKE_LEGACY)
            self.assertTrue(prepared.transaction.exists())

    def test_committed_cleanup_preserves_backup_even_when_it_changes(self):
        with tempfile.TemporaryDirectory() as temporary, _recognize_fake_legacy():
            home = Path(temporary).resolve()
            expected = installer._expected_files()
            destination = home / _TARGETS["codex"]
            _write_files(destination, _FAKE_LEGACY)
            state = installer._classify_one("codex", home, expected, upgrade=True)
            prepared = installer._stage_one(state, home, expected)
            installer._commit_one(prepared, expected)
            user_edit = b"edit immediately before cleanup\n"
            (prepared.backup / "SKILL.md").write_bytes(user_edit)

            errors = installer._cleanup_transactions([prepared], committed=True)

            self.assertEqual(errors, [])
            self.assertEqual((prepared.backup / "SKILL.md").read_bytes(), user_edit)
            self.assertTrue(prepared.transaction.exists())

    def test_commit_fsyncs_both_cross_directory_rename_parents(self):
        with tempfile.TemporaryDirectory() as temporary, _recognize_fake_legacy():
            home = Path(temporary).resolve()
            expected = installer._expected_files()
            destination = home / _TARGETS["codex"]
            _write_files(destination, _FAKE_LEGACY)
            state = installer._classify_one("codex", home, expected, upgrade=True)
            prepared = installer._stage_one(state, home, expected)
            original_fsync = installer._fsync_directory
            synced: list[Path] = []

            def record_fsync(path: Path):
                synced.append(path)
                original_fsync(path)

            with mock.patch.object(installer, "_fsync_directory", side_effect=record_fsync):
                installer._commit_one(prepared, expected)

            self.assertGreaterEqual(synced.count(destination.parent), 2)
            self.assertGreaterEqual(synced.count(prepared.transaction), 2)

    def test_open_descriptor_edit_after_final_check_remains_recoverable(self):
        with tempfile.TemporaryDirectory() as temporary, _recognize_fake_legacy():
            home = Path(temporary)
            destination = home / _TARGETS["codex"]
            _write_files(destination, _FAKE_LEGACY)
            descriptor = os.open(destination / "SKILL.md", os.O_WRONLY)
            user_edit = b"late edit through an already-open descriptor\n"
            original_cleanup = installer._cleanup_transactions

            def edit_then_cleanup(prepared, *, committed=False):
                if committed:
                    os.ftruncate(descriptor, 0)
                    os.write(descriptor, user_edit)
                    os.fsync(descriptor)
                return original_cleanup(prepared, committed=committed)

            try:
                with mock.patch.object(
                    installer,
                    "_cleanup_transactions",
                    side_effect=edit_then_cleanup,
                ):
                    records = install_agent_skill("codex", home=home, upgrade=True)
            finally:
                os.close(descriptor)

            self.assertEqual(records[0]["status"], "upgraded")
            recovery = Path(records[0]["recovery_backup"])
            self.assertEqual((recovery / "SKILL.md").read_bytes(), user_edit)
            self.assertEqual(_capture_tree(destination)[0], installer._expected_files())

    def test_edit_after_preflight_is_restored_instead_of_discarded(self):
        with tempfile.TemporaryDirectory() as temporary, _recognize_fake_legacy():
            home = Path(temporary)
            destination = home / _TARGETS["codex"]
            _write_files(destination, _FAKE_LEGACY)
            user_edit = b"user edit after preflight\n"
            original_assert = installer._assert_unchanged
            injected = False

            def assert_then_edit(initial, resolved_home, expected, *, upgrade):
                nonlocal injected
                original_assert(initial, resolved_home, expected, upgrade=upgrade)
                if not injected:
                    injected = True
                    (initial.destination / "SKILL.md").write_bytes(user_edit)

            with (
                mock.patch.object(installer, "_assert_unchanged", side_effect=assert_then_edit),
                self.assertRaisesRegex(ConfigurationError, "changed during installation"),
            ):
                install_agent_skill("codex", home=home, upgrade=True)

            expected_restored = dict(_FAKE_LEGACY)
            expected_restored[Path("SKILL.md")] = user_edit
            self.assertEqual(_capture_tree(destination)[0], expected_restored)
            self.assertFalse((destination / installer._MANIFEST_PATH).exists())
            _assert_no_transactions(self, home)

    def test_edit_to_backup_after_commit_triggers_restore_before_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary, _recognize_fake_legacy():
            home = Path(temporary)
            destination = home / _TARGETS["codex"]
            _write_files(destination, _FAKE_LEGACY)
            user_edit = b"user edit while backup is retained\n"
            original_commit = installer._commit_one

            def commit_then_edit(prepared, expected):
                original_commit(prepared, expected)
                (prepared.backup / "SKILL.md").write_bytes(user_edit)

            with (
                mock.patch.object(installer, "_commit_one", side_effect=commit_then_edit),
                self.assertRaisesRegex(ConfigurationError, "changed during installation") as caught,
            ):
                install_agent_skill("codex", home=home, upgrade=True)

            expected_restored = dict(_FAKE_LEGACY)
            expected_restored[Path("SKILL.md")] = user_edit
            self.assertEqual(_capture_tree(destination)[0], expected_restored)
            self.assertFalse((destination / installer._MANIFEST_PATH).exists())
            recovery = _assert_reported_recoveries(self, caught.exception, home)[0]
            self.assertEqual(_capture_tree(recovery)[0], installer._expected_files())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
