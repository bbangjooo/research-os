"""Shipping a different agent skill must be a deliberate release decision.

v0.5.0 published one skill tree, then the tree changed twice on the same
``__version__`` without registering a checkpoint.  Every installation made after
that point reported ``release: "0.5.0"`` while holding bytes no published 0.5.0
ever had, so ``install-agent-skill --upgrade`` correctly refused to recognize it
and the only remaining path was deleting the installed tree by hand.  These
tests make that failure mode loud at the source instead of at a user's terminal.
"""

from __future__ import annotations

import hashlib
import subprocess

from research_os import __version__
from research_os.agent_install import (
    _KNOWN_MANAGED_RELEASE_FILES,
    _MANIFEST_PATH,
    _SHIPPED_SKILL_TREE_DIGEST,
    _expected_files,
    shipped_skill_tree_digest,
)

_RELEASE_COMMITS = {"0.5.0": "2bb7a88", "0.6.0": "b8b7b8f"}
_RESOURCE_PREFIX = "src/research_os/resources/research-os/"


def test_shipped_tree_digest_is_pinned() -> None:
    # Fails whenever a shipped resource byte or the release identity changes
    # without a matching edit in agent_install.py.  When it fails, register the
    # outgoing tree in _KNOWN_MANAGED_RELEASE_FILES, bump __version__, and
    # update _SHIPPED_SKILL_TREE_DIGEST.
    assert shipped_skill_tree_digest() == _SHIPPED_SKILL_TREE_DIGEST


def test_current_version_is_not_registered_as_a_prior_release() -> None:
    # The registry names trees an upgrade may replace.  The version being shipped
    # is never one of them, so a collision means a released identity is being
    # reused for a second, different tree.
    assert __version__ not in _KNOWN_MANAGED_RELEASE_FILES


def test_registered_releases_are_distinct_trees() -> None:
    signatures = {
        release: signature[_MANIFEST_PATH]
        for release, signature in _KNOWN_MANAGED_RELEASE_FILES.items()
    }
    assert len(set(signatures.values())) == len(signatures)


def test_registered_signatures_cover_the_same_paths_as_a_current_install() -> None:
    expected_paths = set(_expected_files())
    for release, signature in _KNOWN_MANAGED_RELEASE_FILES.items():
        assert set(signature) == expected_paths, release


def test_registered_release_bytes_match_their_published_commit() -> None:
    # Reconstruct each recorded signature from git rather than trusting the
    # constant, so a typo or a signature copied from a developer's own
    # installation cannot silently authorize replacing an unpublished tree.
    for release, commit in _RELEASE_COMMITS.items():
        signature = _KNOWN_MANAGED_RELEASE_FILES[release]
        names = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", commit, _RESOURCE_PREFIX],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
        assert names, release
        for name in names:
            content = subprocess.run(
                ["git", "cat-file", "-p", f"{commit}:{name}"],
                capture_output=True,
                check=True,
            ).stdout
            relative = name[len(_RESOURCE_PREFIX) :]
            recorded = next(
                value for path, value in signature.items() if path.as_posix() == relative
            )
            assert recorded == (
                len(content),
                hashlib.sha256(content).hexdigest(),
            ), f"{release}:{relative}"
