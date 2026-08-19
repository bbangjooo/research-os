#!/usr/bin/env python3
"""Run a bounded, reversible experiment loop over a git worktree.

One iteration is: measure the objective, let an external agent command make **one**
change, re-measure, then either commit the change or throw it away with
``git reset --hard``.  Every iteration is appended to a durable ledger, so the loop
carries its own history instead of relying on the agent to remember anything.

The loop owns four things and nothing else:

* **a scalar objective** — one command that prints one number;
* **reversibility** — a rejected iteration leaves the worktree byte-identical to its
  parent commit;
* **a short horizon** — the agent is invoked once per iteration and is expected to
  make a single conceptual change;
* **a finite budget** — iteration count and per-command timeouts.

Whether the change *preserves behaviour* is not this module's judgement.  That
belongs to the guards, and for production refactors the guard is
``scripts/refactor_proof.py verify``, whose contract is owned by the refactor
skill (``.agents/skills/refactor/SKILL.md``).
A loop with weak guards optimises the objective by breaking the program, so the
guards — not the loop — are where the review effort belongs.

The agent is any argv the operator supplies.  This module never imports or assumes
a specific agent vendor.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shlex
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

LEDGER_SCHEMA = "experiment-loop-ledger-v2"
BASELINE_SCHEMA = "experiment-loop-baseline-v2"
SPEC_SCHEMA = "experiment-loop-spec-v2"
SUMMARY_SCHEMA = "experiment-loop-summary-v2"

DEFAULT_PROTECTED_BRANCHES = ("main", "master")
DEFAULT_OBJECTIVE_TIMEOUT = 900
DEFAULT_GUARD_TIMEOUT = 1800
DEFAULT_AGENT_TIMEOUT = 900
DEFAULT_LEDGER_TAIL = 20

# One trial is one folder: `loop/runs/<YYYY-MM-DD>-<loop_id>/` holds the spec that
# produced it and the summary written once the loop ends.  The ledger stays under
# `.git/` because a rejected iteration wipes the worktree.
RUNS_ROOT = Path("loop") / "runs"
SUMMARY_NAME = "summary.json"
TRIAL_DATE_PREFIX = re.compile(r"^\d{4}-\d{2}-\d{2}-")
SPEC_NAME = "spec.yaml"

DIRECTIONS = ("minimize", "maximize")
GUARD_KINDS = (
    "exit_zero",
    "unchanged_output",
    "non_decreasing_number",
    "non_increasing_number",
)

# The kinds that read a number and compare it against a recorded one.  `tolerance` and
# `ratchet` only mean something here: `exit_zero` records nothing to compare against and
# `unchanged_output` compares bytes, where a band and a ratchet are both meaningless.
NUMERIC_GUARD_KINDS = ("non_decreasing_number", "non_increasing_number")
ON_INCOMPLETE = ("stop", "continue")

# A spec without `stages` is one stage named this, so a single-stage trial reads and
# records exactly as it did before stages existed.
DEFAULT_STAGE_ID = "main"

# What makes something a stage.  `integrity` is deliberately not here: it is shared at
# the top level and *added to* per stage, so its presence says nothing about the form.
_STAGE_ONLY_KEYS = {"objective", "guards", "budget", "prompt"}
_SPEC_KEYS = {"loop_id", "agent", "revert", "stages", "integrity"} | _STAGE_ONLY_KEYS
_STAGE_KEYS = {"id", "on_incomplete", "integrity"} | _STAGE_ONLY_KEYS
_OBJECTIVE_KEYS = {"command", "direction", "margin", "target", "timeout_seconds"}
_AGENT_KEYS = {"command", "timeout_seconds", "summary_prefix"}
_GUARD_KEYS = {"id", "command", "kind", "timeout_seconds", "tolerance", "ratchet"}
_BUDGET_KEYS = {"iterations"}
_REVERT_KEYS = {"clean_ignored"}


class SpecError(ValueError):
    """The loop specification is unusable."""


class PreconditionError(RuntimeError):
    """The repository is not in a state where the loop may run."""


def _require_mapping(value: Any, *, path: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SpecError(f"{path} must be a mapping")
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise SpecError(f"{path} has unknown keys: {', '.join(unknown)}")
    return dict(value)


def _require_command(value: Any, *, path: str) -> tuple[str, ...]:
    if isinstance(value, str):
        raise SpecError(f"{path} must be a list of arguments, not a shell string")
    if not isinstance(value, Sequence) or not value:
        raise SpecError(f"{path} must be a non-empty list of arguments")
    out: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise SpecError(f"{path}[{index}] must be a string")
        out.append(item)
    return tuple(out)


def _require_timeout(value: Any, *, path: str, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SpecError(f"{path} must be a positive integer number of seconds")
    return value


@dataclass(frozen=True)
class Guard:
    guard_id: str
    command: tuple[str, ...]
    kind: str
    timeout_seconds: int
    tolerance: float = 0.0
    ratchet: bool = False

    def allows(self, current: float, recorded: float) -> bool:
        """Is ``current`` still acceptable against the ``recorded`` reading?

        The band is a fraction of the recorded value's *magnitude*, not of the value
        itself, so a negative baseline widens in the same direction a positive one does.
        A zero baseline has no magnitude and therefore no band — say so in the spec by
        picking a metric that cannot sit at zero, not by raising the tolerance.
        """
        slack = abs(recorded) * self.tolerance
        if self.kind == "non_increasing_number":
            return current <= recorded + slack
        return current >= recorded - slack


@dataclass(frozen=True)
class Objective:
    command: tuple[str, ...]
    direction: str
    margin: float
    target: float | None
    timeout_seconds: int

    def is_improvement(self, before: float, after: float) -> bool:
        if self.direction == "minimize":
            return after <= before - self.margin
        return after >= before + self.margin

    def reached_target(self, value: float) -> bool:
        if self.target is None:
            return False
        if self.direction == "minimize":
            return value <= self.target
        return value >= self.target


def _objective_to_dict(objective: Objective) -> dict[str, Any]:
    return {
        "command": list(objective.command),
        "direction": objective.direction,
        "margin": objective.margin,
        "target": objective.target,
        "timeout_seconds": objective.timeout_seconds,
    }


@dataclass(frozen=True)
class Stage:
    """One leg of a run: its own objective, its own guards, its own budget.

    Stages exist because a single objective cannot describe work that changes shape.
    Preparing the ground ("does the contract file exist yet") and doing the work
    ("how many files are still in the wrong place") are different numbers, and the
    guards that may run differ with them: a guard that cannot pass before the ground
    is prepared would refuse the whole run if it were declared once, globally.

    Guard strength is expected to *increase* down the list.  The weak-guard stage is
    the one that only adds files; by the time production code moves, the expensive
    guards are in force.
    """

    stage_id: str
    objective: Objective
    guards: tuple[Guard, ...]
    integrity_paths: tuple[str, ...]
    iterations: int
    prompt: str
    on_incomplete: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.stage_id,
            "objective": _objective_to_dict(self.objective),
            "guards": [
                {
                    "id": guard.guard_id,
                    "command": list(guard.command),
                    "kind": guard.kind,
                    "timeout_seconds": guard.timeout_seconds,
                }
                for guard in self.guards
            ],
            "integrity": list(self.integrity_paths),
            "budget": {"iterations": self.iterations},
            "on_incomplete": self.on_incomplete,
        }


@dataclass(frozen=True)
class Spec:
    loop_id: str
    stages: tuple[Stage, ...]
    agent_command: tuple[str, ...]
    agent_timeout_seconds: int
    agent_summary_prefix: str
    integrity_paths: tuple[str, ...]
    clean_ignored: bool
    source_path: Path | None = field(default=None, compare=False)
    # Pinned at parse time: the spec now lives in the worktree, so the file on disk
    # can be rewritten while the loop runs.  Evidence must name the spec that ran.
    source_digest: str | None = field(default=None, compare=False)

    @property
    def objective(self) -> Objective:
        """The first stage's objective — what the run is measured from at entry."""
        return self.stages[0].objective

    def stage_integrity(self, stage: Stage) -> list[str]:
        """Everything pinned while ``stage`` runs: the shared set plus its own."""
        merged = list(self.integrity_paths)
        for path in stage.integrity_paths:
            if path not in merged:
                merged.append(path)
        return merged

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_schema": SPEC_SCHEMA,
            "loop_id": self.loop_id,
            "agent": {
                "command": list(self.agent_command),
                "timeout_seconds": self.agent_timeout_seconds,
                "summary_prefix": self.agent_summary_prefix,
            },
            "integrity": list(self.integrity_paths),
            "revert": {"clean_ignored": self.clean_ignored},
            "stages": [stage.to_dict() for stage in self.stages],
        }


def load_spec(path: Path) -> Spec:
    """Parse and fully validate a loop spec.  Rejects anything ambiguous."""
    source_bytes = path.read_bytes()
    try:
        raw = yaml.safe_load(source_bytes.decode("utf-8"))
    except yaml.YAMLError as error:  # pragma: no cover - message passthrough
        raise SpecError(f"{path} is not valid YAML: {error}") from error
    value = _require_mapping(raw, path="$", allowed=_SPEC_KEYS)

    loop_id = value.get("loop_id")
    if not isinstance(loop_id, str) or not loop_id:
        raise SpecError("$.loop_id must be a non-empty string")
    if not all(character.isalnum() or character in "-_" for character in loop_id):
        raise SpecError("$.loop_id may only contain alphanumerics, '-' and '_'")

    agent_raw = _require_mapping(value.get("agent"), path="$.agent", allowed=_AGENT_KEYS)
    summary_prefix = agent_raw.get("summary_prefix", "SUMMARY:")
    if not isinstance(summary_prefix, str) or not summary_prefix:
        raise SpecError("$.agent.summary_prefix must be a non-empty string")

    revert_raw = _require_mapping(value.get("revert", {}), path="$.revert", allowed=_REVERT_KEYS)
    clean_ignored = revert_raw.get("clean_ignored", False)
    if not isinstance(clean_ignored, bool):
        raise SpecError("$.revert.clean_ignored must be a boolean")

    stages = _load_stages(value)

    return Spec(
        loop_id=loop_id,
        stages=stages,
        agent_command=_require_command(agent_raw.get("command"), path="$.agent.command"),
        agent_timeout_seconds=_require_timeout(
            agent_raw.get("timeout_seconds"),
            path="$.agent.timeout_seconds",
            default=DEFAULT_AGENT_TIMEOUT,
        ),
        agent_summary_prefix=summary_prefix,
        integrity_paths=_load_integrity(value, path="$"),
        clean_ignored=clean_ignored,
        source_path=path,
        source_digest=hashlib.sha256(source_bytes).hexdigest(),
    )


def _load_objective(value: Mapping[str, Any], *, path: str) -> Objective:
    raw = _require_mapping(
        value.get("objective"), path=f"{path}.objective", allowed=_OBJECTIVE_KEYS
    )
    direction = raw.get("direction")
    if direction not in DIRECTIONS:
        raise SpecError(f"{path}.objective.direction must be one of {', '.join(DIRECTIONS)}")
    margin = raw.get("margin", 0.0)
    if isinstance(margin, bool) or not isinstance(margin, (int, float)) or margin < 0:
        raise SpecError(f"{path}.objective.margin must be a non-negative number")
    target = raw.get("target")
    if target is not None and (isinstance(target, bool) or not isinstance(target, (int, float))):
        raise SpecError(f"{path}.objective.target must be a number when present")
    return Objective(
        command=_require_command(raw.get("command"), path=f"{path}.objective.command"),
        direction=direction,
        margin=float(margin),
        target=None if target is None else float(target),
        timeout_seconds=_require_timeout(
            raw.get("timeout_seconds"),
            path=f"{path}.objective.timeout_seconds",
            default=DEFAULT_OBJECTIVE_TIMEOUT,
        ),
    )


def _require_tolerance(value: Any, *, kind: str, path: str) -> float:
    if value is None:
        return 0.0
    if kind not in NUMERIC_GUARD_KINDS:
        raise SpecError(f"{path} only applies to {' or '.join(NUMERIC_GUARD_KINDS)}, not {kind}")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise SpecError(f"{path} must be a non-negative number")
    return float(value)


def _load_guards(value: Mapping[str, Any], *, path: str) -> tuple[Guard, ...]:
    guards_raw = value.get("guards", [])
    if not isinstance(guards_raw, Sequence) or isinstance(guards_raw, str):
        raise SpecError(f"{path}.guards must be a list")
    guards: list[Guard] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(guards_raw):
        guard_value = _require_mapping(item, path=f"{path}.guards[{index}]", allowed=_GUARD_KEYS)
        guard_id = guard_value.get("id")
        if not isinstance(guard_id, str) or not guard_id:
            raise SpecError(f"{path}.guards[{index}].id must be a non-empty string")
        if guard_id in seen_ids:
            raise SpecError(f"{path}.guards[{index}].id duplicates an earlier guard")
        seen_ids.add(guard_id)
        kind = guard_value.get("kind", "exit_zero")
        if kind not in GUARD_KINDS:
            raise SpecError(f"{path}.guards[{index}].kind must be one of {', '.join(GUARD_KINDS)}")
        tolerance = _require_tolerance(
            guard_value.get("tolerance"), kind=kind, path=f"{path}.guards[{index}].tolerance"
        )
        ratchet = guard_value.get("ratchet", False)
        if not isinstance(ratchet, bool):
            raise SpecError(f"{path}.guards[{index}].ratchet must be true or false")
        if ratchet and kind not in NUMERIC_GUARD_KINDS:
            raise SpecError(
                f"{path}.guards[{index}].ratchet only applies to "
                f"{' or '.join(NUMERIC_GUARD_KINDS)}, not {kind}"
            )
        guards.append(
            Guard(
                guard_id=guard_id,
                command=_require_command(
                    guard_value.get("command"), path=f"{path}.guards[{index}].command"
                ),
                kind=kind,
                timeout_seconds=_require_timeout(
                    guard_value.get("timeout_seconds"),
                    path=f"{path}.guards[{index}].timeout_seconds",
                    default=DEFAULT_GUARD_TIMEOUT,
                ),
                tolerance=tolerance,
                ratchet=ratchet,
            )
        )
    return tuple(guards)


def _load_integrity(value: Mapping[str, Any], *, path: str) -> tuple[str, ...]:
    integrity_raw = value.get("integrity", [])
    if not isinstance(integrity_raw, Sequence) or isinstance(integrity_raw, str):
        raise SpecError(f"{path}.integrity must be a list of paths")
    integrity: list[str] = []
    for index, item in enumerate(integrity_raw):
        if not isinstance(item, str) or not item:
            raise SpecError(f"{path}.integrity[{index}] must be a non-empty path string")
        integrity.append(item)
    if len(set(integrity)) != len(integrity):
        raise SpecError(f"{path}.integrity must not repeat a path")
    return tuple(integrity)


def _load_stage(value: Mapping[str, Any], *, path: str, stage_id: str) -> Stage:
    budget_raw = _require_mapping(value.get("budget"), path=f"{path}.budget", allowed=_BUDGET_KEYS)
    iterations = budget_raw.get("iterations")
    if not isinstance(iterations, int) or isinstance(iterations, bool) or iterations <= 0:
        raise SpecError(f"{path}.budget.iterations must be a positive integer")

    prompt = value.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise SpecError(f"{path}.prompt must be a non-empty string")

    on_incomplete = value.get("on_incomplete", "stop")
    if on_incomplete not in ON_INCOMPLETE:
        raise SpecError(f"{path}.on_incomplete must be one of {', '.join(ON_INCOMPLETE)}")

    return Stage(
        stage_id=stage_id,
        objective=_load_objective(value, path=path),
        guards=_load_guards(value, path=path),
        integrity_paths=_load_integrity(value, path=path),
        iterations=iterations,
        prompt=prompt,
        on_incomplete=on_incomplete,
    )


def _load_stages(value: Mapping[str, Any]) -> tuple[Stage, ...]:
    """One stage per entry under `stages`, or the whole spec read as a single stage.

    The two forms are exclusive.  A spec that declares both would leave the reader
    guessing which objective governs, and guessing is how a loop optimises the wrong
    number for twenty iterations.
    """
    raw = value.get("stages")
    stage_fields = sorted(_STAGE_ONLY_KEYS & set(value))
    if raw is None:
        if not stage_fields:
            raise SpecError("$ must declare either $.stages or a single-stage $.objective")
        return (_load_stage(value, path="$", stage_id=DEFAULT_STAGE_ID),)
    if stage_fields:
        raise SpecError(
            "$ declares both $.stages and top-level "
            f"{', '.join('$.' + name for name in stage_fields)}; move them into a stage"
        )
    if not isinstance(raw, Sequence) or isinstance(raw, str) or not raw:
        raise SpecError("$.stages must be a non-empty list")

    stages: list[Stage] = []
    seen: set[str] = set()
    for index, item in enumerate(raw):
        path = f"$.stages[{index}]"
        stage_value = _require_mapping(item, path=path, allowed=_STAGE_KEYS)
        stage_id = stage_value.get("id")
        if not isinstance(stage_id, str) or not stage_id:
            raise SpecError(f"{path}.id must be a non-empty string")
        if not all(character.isalnum() or character in "-_" for character in stage_id):
            raise SpecError(f"{path}.id may only contain alphanumerics, '-' and '_'")
        if stage_id in seen:
            raise SpecError(f"{path}.id duplicates an earlier stage")
        seen.add(stage_id)
        stages.append(_load_stage(stage_value, path=path, stage_id=stage_id))
    return tuple(stages)


def _relative_within(root: Path, path: Path) -> Path | None:
    """The path relative to ``root``, or None when it lives outside it.

    Both the lexical and the resolved form are tried, because the two answer different
    questions and both matter here.  A symlink parked inside the worktree *lives* there
    — ``git clean -fd`` deletes it — even though it resolves elsewhere; and a worktree
    reached through a symlinked prefix (``/tmp`` on macOS) only matches once resolved.
    Whichever form places the path inside wins: containment is the fail-closed answer.
    """
    lexical_root = Path(os.path.abspath(root))
    resolved_root = root.resolve()
    roots = [lexical_root] if lexical_root == resolved_root else [lexical_root, resolved_root]
    for candidate in (Path(os.path.abspath(path)), path.resolve()):
        for base in roots:
            try:
                return candidate.relative_to(base)
            except ValueError:
                continue
    return None


def check_spec_placement(repo: Path, spec: Spec) -> None:
    """A trial folder and its ``loop_id`` must agree, or the trial loses its ledger.

    The ledger lives at ``.git/experiment-loop/<loop_id>/``.  If the folder says one
    thing and the spec says another, nothing links the two afterwards.  Only specs under
    ``loop/runs/`` are held to this; a spec anywhere else is the operator's business.
    """
    if spec.source_path is None:
        return
    relative = _relative_within(repo, spec.source_path)
    if relative is None or relative.parts[: len(RUNS_ROOT.parts)] != RUNS_ROOT.parts:
        return
    if len(relative.parts) != len(RUNS_ROOT.parts) + 2:
        raise SpecError(
            f"a spec under {RUNS_ROOT.as_posix()}/ must sit directly in its trial folder "
            f"({RUNS_ROOT.as_posix()}/<YYYY-MM-DD>-<loop_id>/spec.yaml), "
            f"not at {relative.as_posix()}"
        )
    if relative.name != SPEC_NAME:
        raise SpecError(
            f"a trial folder holds exactly one spec, named {SPEC_NAME}; "
            f"{relative.as_posix()} would share the folder's single {SUMMARY_NAME}"
        )
    slot = relative.parts[len(RUNS_ROOT.parts)]
    if TRIAL_DATE_PREFIX.sub("", slot) != spec.loop_id:
        raise SpecError(
            f"trial folder {RUNS_ROOT.as_posix()}/{slot}/ must be named "
            f"'<YYYY-MM-DD>-{spec.loop_id}' or '{spec.loop_id}' after its loop_id; "
            f"otherwise the ledger at .git/experiment-loop/{spec.loop_id}/ belongs to a "
            "folder nobody can find"
        )


def _git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=check, capture_output=True, text=True)
    return result.stdout.strip()


@dataclass
class CommandResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def run_command(
    command: Sequence[str], *, cwd: Path, timeout_seconds: int, env: Mapping[str, str] | None = None
) -> CommandResult:
    merged = dict(os.environ)
    if env:
        merged.update(env)
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=merged,
        )
    except subprocess.TimeoutExpired as expired:
        return CommandResult(
            exit_code=124,
            stdout=expired.stdout.decode("utf-8", "replace") if expired.stdout else "",
            stderr=expired.stderr.decode("utf-8", "replace") if expired.stderr else "",
            timed_out=True,
        )
    return CommandResult(
        exit_code=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        timed_out=False,
    )


def parse_scalar(stdout: str) -> float:
    """Read the objective value from a command's stdout: the last non-empty line."""
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise ValueError("objective command produced no output")
    try:
        return float(lines[-1])
    except ValueError as error:
        raise ValueError(f"objective output {lines[-1]!r} is not a number") from error


def effective_integrity_paths(repo: Path, spec: Spec, stage: Stage) -> list[str]:
    """What actually gets pinned while ``stage`` runs.

    The stage's own set, plus the spec itself when it is reachable: an in-worktree spec
    is a scoring input like any other — the agent can edit it — so it joins the pinned
    set even though the operator did not list it.  Declaring it too is harmless; the
    path simply appears once.
    """
    paths = spec.stage_integrity(stage)
    relative = _relative_within(repo, spec.source_path) if spec.source_path else None
    if relative is not None and relative.as_posix() not in paths:
        paths.append(relative.as_posix())
    return paths


def digest_paths(repo: Path, paths: Sequence[str]) -> dict[str, str]:
    """Digest every pinned path.  A missing path is recorded, not silently skipped."""
    digests: dict[str, str] = {}
    for relative in paths:
        candidate = Path(relative)
        target = candidate if candidate.is_absolute() else repo / candidate
        if not target.exists():
            digests[relative] = "MISSING"
            continue
        if target.is_dir():
            hasher = hashlib.sha256()
            for child in sorted(p for p in target.rglob("*") if p.is_file()):
                hasher.update(str(child.relative_to(target)).encode("utf-8"))
                hasher.update(child.read_bytes())
            digests[relative] = hasher.hexdigest()
            continue
        digests[relative] = hashlib.sha256(target.read_bytes()).hexdigest()
    return digests


def _worktree_is_clean(repo: Path) -> bool:
    return _git(repo, "status", "--porcelain") == ""


def _check_spec_survives_a_revert(repo: Path, spec_path: Path | None) -> None:
    """An in-worktree spec must be a real, tracked file the loop cannot destroy."""
    if spec_path is None:
        return
    relative = _relative_within(repo, spec_path)
    if relative is None:
        return
    if spec_path.is_symlink():
        # A symlink is pinned by the bytes it points at, not by where it points, so an
        # agent could retarget it without changing any digest.  Nothing legitimate needs
        # one here: a trial's spec is a file the trial folder owns.
        raise PreconditionError(
            f"spec {relative.as_posix()} is a symlink; an in-worktree spec must be a real "
            "file so that pinning it also pins what the loop actually read. Copy the spec "
            "into the trial folder, or keep it outside the worktree."
        )
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", relative.as_posix()],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if tracked.returncode != 0:
        raise PreconditionError(
            f"spec {relative.as_posix()} is inside the worktree but untracked; a rejected "
            "iteration runs 'git clean -fd' and would delete it. Commit it — a trial belongs "
            f"in {RUNS_ROOT.as_posix()}/<YYYY-MM-DD>-<loop_id>/ — or keep the spec outside "
            "the worktree."
        )


def _check_run_dir_survives_a_revert(repo: Path, run_dir: Path) -> None:
    """The ledger cannot live where the loop's own revert can reach it."""
    if _relative_within(repo, run_dir) is None:
        return
    git_dir = Path(_git(repo, "rev-parse", "--absolute-git-dir"))
    if _relative_within(git_dir, run_dir) is not None:
        return
    raise PreconditionError(
        f"--run-dir {run_dir} is inside the worktree; a rejected iteration runs "
        "'git reset --hard' and 'git clean -fd', which would erase the ledger that "
        "records the rejection. Leave it under .git/experiment-loop/<loop_id>/ or point "
        "it outside the worktree."
    )


def check_preconditions(
    repo: Path,
    *,
    allow_branch: bool,
    protected: Sequence[str],
    spec_path: Path | None = None,
) -> str:
    """Fail closed before anything destructive can happen."""
    if not (repo / ".git").exists():
        raise PreconditionError(f"{repo} is not a git repository")
    # Before the clean-worktree check: an untracked spec is *why* the worktree is
    # dirty, and "commit or stash first" is the wrong advice for it.
    _check_spec_survives_a_revert(repo, spec_path)
    if not _worktree_is_clean(repo):
        raise PreconditionError(
            "the worktree has uncommitted changes; the loop reverts with 'git reset --hard' "
            "and would destroy them. Commit or stash first."
        )
    branch = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if branch == "HEAD":
        raise PreconditionError("HEAD is detached; check out a dedicated loop branch first")
    if branch in protected and not allow_branch:
        raise PreconditionError(
            f"refusing to run on protected branch {branch!r}; "
            "check out a dedicated loop branch or pass --allow-branch"
        )
    return branch


def default_run_dir(repo: Path, loop_id: str) -> Path:
    """Keep loop state inside the git dir, which survives 'reset --hard' and 'clean -fd'."""
    git_dir = Path(_git(repo, "rev-parse", "--absolute-git-dir"))
    return git_dir / "experiment-loop" / loop_id


def _revert(repo: Path, *, clean_ignored: bool) -> None:
    _git(repo, "reset", "--hard")
    _git(repo, "clean", "-fdx" if clean_ignored else "-fd")


def _accept(
    repo: Path, *, loop_id: str, stage_id: str, iteration: int, before: float, after: float
) -> str:
    _git(repo, "add", "-A")
    # The stage is in the subject because a multi-stage run leaves one history where
    # "iteration 3" happens several times over.
    scope = loop_id if stage_id == DEFAULT_STAGE_ID else f"{loop_id}/{stage_id}"
    message = f"exp({scope}): iteration {iteration} objective {before:g} -> {after:g}"
    _git(repo, "commit", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def append_record(ledger: Path, record: Mapping[str, Any]) -> None:
    """Append one record, repairing a truncated tail first.

    A run killed mid-write leaves a line without its newline.  Appending straight onto it
    fuses two records into one unparseable line, and both are then dropped on read — the
    loop would report an empty run over commits it really made.
    """
    if ledger.exists() and ledger.stat().st_size:
        with ledger.open("rb") as handle:
            handle.seek(-1, os.SEEK_END)
            truncated = handle.read(1) != b"\n"
    else:
        truncated = False
    with ledger.open("a", encoding="utf-8") as handle:
        if truncated:
            handle.write("\n")
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def _ledger_tail(ledger: Path, limit: int) -> list[dict[str, Any]]:
    if not ledger.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records[-limit:]


def build_prompt(
    spec: Spec,
    stage: Stage,
    *,
    position: int,
    iteration: int,
    objective_value: float,
    history: list[dict],
) -> str:
    lines = [stage.prompt.strip(), "", "## Loop state"]
    if len(spec.stages) > 1:
        lines.append(f"- stage: {stage.stage_id} ({position} of {len(spec.stages)})")
    lines += [
        f"- iteration: {iteration} of {stage.iterations}",
        f"- objective: {objective_value:g} (direction: {stage.objective.direction})",
    ]
    if stage.objective.target is not None:
        lines.append(f"- target: {stage.objective.target:g}")
    lines.append("")
    lines.append("## Previous iterations")
    if not history:
        lines.append("- none yet")
    for record in history:
        lines.append(
            f"- #{record.get('iteration')} {record.get('decision')}: "
            f"{record.get('objective_before')} -> {record.get('objective_after')} — "
            f"{record.get('agent_summary') or record.get('reason') or ''}"
        )
    lines += [
        "",
        "## Rules",
        "- Make exactly one conceptual change this iteration.",
        "- A change that does not improve the objective is discarded automatically, so do not",
        "  try to fix an earlier rejected idea by stacking another change on top of it.",
        f"- Never edit these pinned paths: {', '.join(spec.stage_integrity(stage)) or '(none)'}.",
        f"- End your output with a line starting with '{spec.agent_summary_prefix}' stating what",
        "  you changed and why, in one sentence.",
    ]
    return "\n".join(lines) + "\n"


def _agent_argv(command: Sequence[str], *, prompt: str, prompt_file: Path) -> list[str]:
    return [
        item.replace("{prompt_file}", str(prompt_file)).replace("{prompt}", prompt)
        for item in command
    ]


def _extract_summary(stdout: str, prefix: str) -> str | None:
    for line in reversed(stdout.splitlines()):
        stripped = line.strip()
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return None


def _evaluate_guard(
    guard: Guard, result: CommandResult, baseline: Mapping[str, Any]
) -> tuple[str | None, float | None]:
    """Return ``(reason, reading)``: reason is None when the guard passes.

    ``reading`` is the number a numeric guard saw, so an accepted iteration can ratchet
    the baseline forward to it.  It is None for every other kind and for any failure
    that happened before a number could be read.
    """
    if guard.kind == "exit_zero":
        if result.timed_out:
            return f"guard {guard.guard_id} timed out", None
        return (None if result.ok else f"guard {guard.guard_id} exited {result.exit_code}"), None
    if result.timed_out:
        return f"guard {guard.guard_id} timed out", None
    if result.exit_code != 0:
        return f"guard {guard.guard_id} exited {result.exit_code}", None
    recorded = baseline.get(guard.guard_id)
    if guard.kind == "unchanged_output":
        if result.stdout != recorded:
            return f"guard {guard.guard_id} output changed", None
        return None, None
    try:
        current = parse_scalar(result.stdout)
        previous = float(recorded)
    except (TypeError, ValueError):
        return f"guard {guard.guard_id} did not produce a number", None
    if not guard.allows(current, previous):
        moved = "rose" if guard.kind == "non_increasing_number" else "dropped"
        band = f" (tolerance {guard.tolerance:g})" if guard.tolerance else ""
        return (
            f"guard {guard.guard_id} {moved} from {previous:g} to {current:g}{band}",
            current,
        )
    return None, current


def _guard_reading(guard: Guard, repo: Path) -> tuple[CommandResult, Any]:
    result = run_command(guard.command, cwd=repo, timeout_seconds=guard.timeout_seconds)
    if not result.ok:
        raise PreconditionError(
            f"guard {guard.guard_id} must pass before the stage starts "
            f"(exit {result.exit_code}); fix the tree or the guard first"
        )
    if guard.kind == "unchanged_output":
        return result, result.stdout
    return result, parse_scalar(result.stdout)


def capture_guard_baseline(guards: Sequence[Guard], repo: Path) -> dict[str, Any]:
    """Also the stage's entry gate: a guard that cannot pass now never will.

    Every baselined guard is read twice on an unchanged tree.  A guard compared against
    a recorded value only means something if it is deterministic, and the cheap way to
    write one is not — ``pytest --collect-only | tr -dc 0-9`` sweeps the digits of
    "241 tests collected in 0.07s" into the count, so the number drifts with the clock
    and the guard rejects good iterations at random.  Catching that here costs one
    extra run of a counter; catching it mid-run costs a discarded iteration and a
    reason line that blames the agent.
    """
    baseline: dict[str, Any] = {}
    for guard in guards:
        if guard.kind == "exit_zero":
            continue
        _, first = _guard_reading(guard, repo)
        _, second = _guard_reading(guard, repo)
        if first != second:
            raise PreconditionError(
                f"guard {guard.guard_id} is not deterministic: two runs on the same tree "
                f"disagree ({first!r} then {second!r}). A {guard.kind} guard is compared "
                "against a recorded reading, so it must report the same value for the "
                "same tree — read the one number you mean, not every digit on the line"
            )
        baseline[guard.guard_id] = first
    return baseline


@dataclass
class Iteration:
    iteration: int
    decision: str
    reason: str
    objective_before: float | None = None
    objective_after: float | None = None
    commit: str | None = None
    agent_exit_code: int | None = None
    agent_summary: str | None = None
    guards: list[dict[str, Any]] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_record(self, spec: Spec, stage: Stage, *, run_id: str) -> dict[str, Any]:
        return {
            "ledger_schema": LEDGER_SCHEMA,
            "loop_id": spec.loop_id,
            "run_id": run_id,
            "stage": stage.stage_id,
            "iteration": self.iteration,
            "decision": self.decision,
            "reason": self.reason,
            "direction": stage.objective.direction,
            "margin": stage.objective.margin,
            "objective_before": self.objective_before,
            "objective_after": self.objective_after,
            "commit": self.commit,
            "agent_exit_code": self.agent_exit_code,
            "agent_summary": self.agent_summary,
            "guards": self.guards,
            "duration_seconds": round(self.duration_seconds, 3),
        }


def run_iteration(
    spec: Spec,
    stage: Stage,
    repo: Path,
    *,
    position: int,
    iteration: int,
    run_dir: Path,
    pinned: Mapping[str, str],
    guard_baseline: MutableMapping[str, Any],
    history: list[dict[str, Any]],
) -> Iteration:
    started = time.monotonic()
    state = Iteration(iteration=iteration, decision="rejected", reason="")

    measurement = run_command(
        stage.objective.command, cwd=repo, timeout_seconds=stage.objective.timeout_seconds
    )
    if not measurement.ok:
        state.decision = "void"
        state.reason = (
            f"objective command failed before the agent ran (exit {measurement.exit_code})"
        )
        state.duration_seconds = time.monotonic() - started
        return state
    before = parse_scalar(measurement.stdout)
    state.objective_before = before

    prompt = build_prompt(
        spec,
        stage,
        position=position,
        iteration=iteration,
        objective_value=before,
        history=history,
    )
    prompt_file = run_dir / f"prompt-{stage.stage_id}-{iteration:04d}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    agent = run_command(
        _agent_argv(spec.agent_command, prompt=prompt, prompt_file=prompt_file),
        cwd=repo,
        timeout_seconds=spec.agent_timeout_seconds,
        env={
            "EXPERIMENT_LOOP_PROMPT_FILE": str(prompt_file),
            "EXPERIMENT_LOOP_ITERATION": str(iteration),
            "EXPERIMENT_LOOP_ID": spec.loop_id,
            "EXPERIMENT_LOOP_STAGE": stage.stage_id,
        },
    )
    (run_dir / f"agent-{stage.stage_id}-{iteration:04d}.log").write_text(
        agent.stdout + ("\n--- stderr ---\n" + agent.stderr if agent.stderr else ""),
        encoding="utf-8",
    )
    state.agent_exit_code = agent.exit_code
    state.agent_summary = _extract_summary(agent.stdout, spec.agent_summary_prefix)

    if digest_paths(repo, list(pinned)) != dict(pinned):
        _revert(repo, clean_ignored=spec.clean_ignored)
        state.decision = "void"
        state.reason = "a pinned path changed during the iteration"
        state.duration_seconds = time.monotonic() - started
        return state

    if _worktree_is_clean(repo):
        state.reason = "the agent left the worktree unchanged"
        state.objective_after = before
        state.duration_seconds = time.monotonic() - started
        return state

    if agent.timed_out:
        _revert(repo, clean_ignored=spec.clean_ignored)
        state.reason = "the agent timed out"
        state.duration_seconds = time.monotonic() - started
        return state

    failures: list[str] = []
    readings: dict[str, float] = {}
    for guard in stage.guards:
        result = run_command(guard.command, cwd=repo, timeout_seconds=guard.timeout_seconds)
        reason, reading = _evaluate_guard(guard, result, guard_baseline)
        record: dict[str, Any] = {
            "id": guard.guard_id,
            "kind": guard.kind,
            "status": "pass" if reason is None else "fail",
            "exit_code": result.exit_code,
        }
        if reading is not None:
            record["reading"] = reading
            if guard.ratchet:
                readings[guard.guard_id] = reading
        state.guards.append(record)
        if reason is not None:
            failures.append(reason)
            break

    if failures:
        _revert(repo, clean_ignored=spec.clean_ignored)
        state.reason = failures[0]
        state.duration_seconds = time.monotonic() - started
        return state

    after_measurement = run_command(
        stage.objective.command, cwd=repo, timeout_seconds=stage.objective.timeout_seconds
    )
    if not after_measurement.ok:
        _revert(repo, clean_ignored=spec.clean_ignored)
        state.reason = (
            f"objective command failed after the change (exit {after_measurement.exit_code})"
        )
        state.duration_seconds = time.monotonic() - started
        return state
    after = parse_scalar(after_measurement.stdout)
    state.objective_after = after

    if not stage.objective.is_improvement(before, after):
        _revert(repo, clean_ignored=spec.clean_ignored)
        state.reason = f"objective did not improve ({before:g} -> {after:g})"
        state.duration_seconds = time.monotonic() - started
        return state

    # Only now, past every gate: a ratcheted guard's floor moves up to what this
    # accepted tree actually reads.  Do it earlier and a rejected iteration would raise
    # the bar for the ones that follow it.
    guard_baseline.update(readings)

    state.commit = _accept(
        repo,
        loop_id=spec.loop_id,
        stage_id=stage.stage_id,
        iteration=iteration,
        before=before,
        after=after,
    )
    state.decision = "accepted"
    state.reason = f"objective improved ({before:g} -> {after:g})"
    state.duration_seconds = time.monotonic() - started
    return state


@dataclass
class StageRun:
    """What one stage did, so the summary can say where a run actually stopped."""

    stage_id: str
    stopped: str
    reason: str = ""
    objective_entry: float | None = None
    objective_final: float | None = None
    iterations_run: int = 0
    accepted: int = 0

    def to_dict(self, stage: Stage) -> dict[str, Any]:
        return {
            "id": self.stage_id,
            "objective": _objective_to_dict(stage.objective),
            "entry": self.objective_entry,
            "final": self.objective_final,
            "iterations_run": self.iterations_run,
            "accepted": self.accepted,
            "stopped": self.stopped,
            "reason": self.reason,
        }


class _StageEntryError(RuntimeError):
    """A stage cannot start.  Fatal before any work; a recorded stop after it."""

    def __init__(self, stopped: str, message: str) -> None:
        super().__init__(message)
        self.stopped = stopped


def _enter_stage(
    spec: Spec,
    stage: Stage,
    repo: Path,
    *,
    run_dir: Path,
    branch: str,
    start_commit: str,
    run_id: str,
    write_legacy_baseline: bool,
) -> tuple[dict[str, str], dict[str, Any], float]:
    """Measure, pin and gate a stage before its first agent runs.

    Pinning happens here rather than once per run because stages disagree about what
    is sacred: the stage that *creates* the scoring script cannot have it pinned, and
    the stage that *uses* it must.
    """
    # Read twice on the unchanged tree, for the same reason guards are (see
    # capture_guard_baseline).  Every accept/reject in this stage is a comparison of two
    # readings of this command, so a command that disagrees with itself does not decide
    # anything — it samples noise and commits whichever sample looked like progress.
    readings: list[float] = []
    for _ in range(2):
        probe = run_command(
            stage.objective.command, cwd=repo, timeout_seconds=stage.objective.timeout_seconds
        )
        if not probe.ok:
            raise _StageEntryError(
                "objective_unmeasurable",
                f"stage {stage.stage_id}: objective command failed at entry "
                f"(exit {probe.exit_code})",
            )
        try:
            readings.append(parse_scalar(probe.stdout))
        except ValueError as error:
            raise _StageEntryError(
                "objective_unmeasurable", f"stage {stage.stage_id}: {error}"
            ) from error
    if readings[0] != readings[1]:
        raise _StageEntryError(
            "objective_unmeasurable",
            f"stage {stage.stage_id}: objective is not deterministic: two runs on the "
            f"same tree disagree ({readings[0]:g} then {readings[1]:g}). Every decision "
            "in this stage compares two readings of this command, so it must report the "
            "same value for the same tree — read the one number you mean, not every "
            "digit on the line",
        )
    entry_value = readings[0]

    pinned = digest_paths(repo, effective_integrity_paths(repo, spec, stage))
    missing = sorted(name for name, value in pinned.items() if value == "MISSING")
    if missing:
        raise _StageEntryError(
            "pinned_path_missing",
            f"pinned path(s) do not exist: {', '.join(missing)}",
        )

    try:
        guard_baseline = capture_guard_baseline(stage.guards, repo)
    except PreconditionError as error:
        raise _StageEntryError("guard_baseline_failed", str(error)) from error

    payload = json.dumps(
        {
            "baseline_schema": BASELINE_SCHEMA,
            "loop_id": spec.loop_id,
            "run_id": run_id,
            "stage": stage.stage_id,
            "branch": branch,
            "start_commit": start_commit,
            "objective_entry": entry_value,
            "pinned": pinned,
            "guards": {
                key: value
                if isinstance(value, (int, float))
                else hashlib.sha256(value.encode("utf-8")).hexdigest()
                for key, value in guard_baseline.items()
            },
            "spec": spec.to_dict(),
        },
        indent=2,
        sort_keys=True,
    )
    (run_dir / f"baseline-{stage.stage_id}.json").write_text(payload + "\n", encoding="utf-8")
    if write_legacy_baseline:
        (run_dir / "baseline.json").write_text(payload + "\n", encoding="utf-8")
    return pinned, guard_baseline, entry_value


def _run_stage(
    spec: Spec,
    stage: Stage,
    repo: Path,
    *,
    position: int,
    run_dir: Path,
    ledger: Path,
    branch: str,
    start_commit: str,
    run_id: str,
    budget: int,
    write_legacy_baseline: bool,
) -> StageRun:
    state = StageRun(stage_id=stage.stage_id, stopped="budget_exhausted")
    pinned, guard_baseline, entry_value = _enter_stage(
        spec,
        stage,
        repo,
        run_dir=run_dir,
        branch=branch,
        start_commit=start_commit,
        run_id=run_id,
        write_legacy_baseline=write_legacy_baseline,
    )
    state.objective_entry = entry_value
    state.objective_final = entry_value
    if stage.objective.reached_target(entry_value):
        # Nothing to do: re-running a finished stage must not spend an agent call.
        state.stopped = "target_reached"
        state.reason = f"objective already at target ({entry_value:g})"
        return state

    for iteration in range(1, budget + 1):
        history = [
            record
            for record in _ledger_tail(ledger, DEFAULT_LEDGER_TAIL)
            if record.get("stage", DEFAULT_STAGE_ID) == stage.stage_id
        ]
        result = run_iteration(
            spec,
            stage,
            repo,
            position=position,
            iteration=iteration,
            run_dir=run_dir,
            pinned=pinned,
            guard_baseline=guard_baseline,
            history=history,
        )
        append_record(ledger, result.to_record(spec, stage, run_id=run_id))
        state.iterations_run = iteration
        label = stage.stage_id if len(spec.stages) > 1 else ""
        print(
            f"{label + ' ' if label else ''}iteration {iteration}/{budget} "
            f"{result.decision}: {result.reason}",
            file=sys.stderr,
            flush=True,
        )
        if result.objective_after is not None:
            state.objective_final = result.objective_after
        if result.decision == "accepted":
            state.accepted += 1
            if result.objective_after is not None and stage.objective.reached_target(
                result.objective_after
            ):
                state.stopped = "target_reached"
                state.reason = f"objective reached target ({result.objective_after:g})"
                return state
        if result.decision == "void" and result.objective_before is None:
            state.stopped = "objective_unmeasurable"
            state.reason = result.reason
            return state
    state.reason = f"budget of {budget} iteration(s) exhausted"
    return state


def run_loop(
    spec: Spec,
    repo: Path,
    *,
    run_dir: Path,
    allow_branch: bool,
    protected: Sequence[str],
    max_iterations: int | None = None,
    from_stage: str | None = None,
) -> dict[str, Any]:
    branch = check_preconditions(
        repo, allow_branch=allow_branch, protected=protected, spec_path=spec.source_path
    )
    _check_run_dir_survives_a_revert(repo, run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    ledger = run_dir / "ledger.jsonl"
    start_commit = _git(repo, "rev-parse", "HEAD")
    # The ledger is append-only and keyed by loop_id, so it may already hold earlier
    # runs.  Every record this invocation writes carries the same run_id, and the summary
    # selects by it rather than by position — an offset would mis-slice the moment an
    # earlier run left a truncated line behind.
    run_id = secrets.token_hex(8)

    stages = list(spec.stages)
    if from_stage is not None:
        stage_ids = [stage.stage_id for stage in stages]
        if from_stage not in stage_ids:
            raise PreconditionError(
                f"--from-stage {from_stage!r} is not a stage of this spec ({', '.join(stage_ids)})"
            )
        stages = stages[stage_ids.index(from_stage) :]

    # `--max-iterations` caps the whole run, not each stage: it is the operator's
    # emergency brake, and a per-stage reading would let a four-stage spec spend
    # four times what was asked for.
    remaining = max_iterations
    stage_runs: list[dict[str, Any]] = []
    stopped = "target_reached"
    stopped_stage: str | None = None
    total_iterations = 0
    total_accepted = 0

    for position, stage in enumerate(stages, start=1):
        if remaining is not None and remaining <= 0:
            stopped, stopped_stage = "budget_exhausted", stage.stage_id
            break
        budget = stage.iterations if remaining is None else min(stage.iterations, remaining)
        try:
            state = _run_stage(
                spec,
                stage,
                repo,
                position=position,
                run_dir=run_dir,
                ledger=ledger,
                branch=branch,
                start_commit=start_commit,
                run_id=run_id,
                budget=budget,
                write_legacy_baseline=position == 1,
            )
        except _StageEntryError as error:
            if position == 1:
                # Nothing has been committed yet, so the honest answer is a refusal
                # rather than a half-run with a summary.
                raise PreconditionError(str(error)) from error
            state = StageRun(stage_id=stage.stage_id, stopped=error.stopped, reason=str(error))
            stage_runs.append(state.to_dict(stage))
            stopped, stopped_stage = error.stopped, stage.stage_id
            break

        stage_runs.append(state.to_dict(stage))
        total_iterations += state.iterations_run
        total_accepted += state.accepted
        if remaining is not None:
            remaining -= state.iterations_run
        if state.stopped != "target_reached":
            stopped, stopped_stage = state.stopped, stage.stage_id
            if stage.on_incomplete == "stop":
                break
        else:
            stopped, stopped_stage = "target_reached", stage.stage_id

    result = {
        "loop_id": spec.loop_id,
        "run_id": run_id,
        "branch": branch,
        "run_dir": str(run_dir),
        "ledger": str(ledger),
        "iterations_run": total_iterations,
        "accepted": total_accepted,
        "stopped": stopped,
        "stopped_stage": stopped_stage,
        "stages": stage_runs,
        "head": _git(repo, "rev-parse", "HEAD"),
    }
    try:
        summary = write_summary(
            spec,
            repo,
            result=result,
            ledger=ledger,
            start_commit=start_commit,
            run_id=run_id,
        )
    except OSError as error:
        # The commits and the ledger are the run's real output; a summary that could not
        # be written must not swallow them.
        result["summary_error"] = str(error)
    else:
        if summary is not None:
            result["summary"] = str(summary)
    return result


def _summarise_records(records: Sequence[Mapping[str, Any]], ledger: Path) -> dict[str, Any]:
    decisions: dict[str, int] = {}
    for record in records:
        decision = str(record.get("decision", "unknown"))
        decisions[decision] = decisions.get(decision, 0) + 1
    values = [
        record["objective_after"]
        for record in records
        if record.get("decision") == "accepted" and record.get("objective_after") is not None
    ]
    first = next(
        (
            record["objective_before"]
            for record in records
            if record.get("objective_before") is not None
        ),
        None,
    )
    stages: dict[str, dict[str, Any]] = {}
    for record in records:
        stage_id = str(record.get("stage", DEFAULT_STAGE_ID))
        entry = stages.setdefault(
            stage_id, {"id": stage_id, "iterations": 0, "accepted": 0, "objective_latest": None}
        )
        entry["iterations"] += 1
        if record.get("decision") == "accepted":
            entry["accepted"] += 1
            if record.get("objective_after") is not None:
                entry["objective_latest"] = record["objective_after"]
    return {
        "ledger": str(ledger),
        "iterations": len(records),
        "decisions": decisions,
        "objective_first": first,
        "objective_latest_accepted": values[-1] if values else None,
        "stages": list(stages.values()),
        "recent": list(records[-5:]),
    }


def summarise(ledger: Path, *, stage: str | None = None) -> dict[str, Any]:
    """The whole ledger, which may span more than one run of the same loop_id."""
    records = _ledger_tail(ledger, 10**9)
    if stage is not None:
        records = [record for record in records if record.get("stage", DEFAULT_STAGE_ID) == stage]
    return _summarise_records(records, ledger)


def build_summary(
    spec: Spec,
    *,
    result: Mapping[str, Any],
    ledger: Path,
    start_commit: str,
    run_id: str,
) -> dict[str, Any]:
    """What a finished trial leaves behind: what it measured and how it ended."""
    records = [record for record in _ledger_tail(ledger, 10**9) if record.get("run_id") == run_id]
    status = _summarise_records(records, ledger)
    return {
        "summary_schema": SUMMARY_SCHEMA,
        "loop_id": spec.loop_id,
        "run_id": run_id,
        "spec_digest": spec.source_digest,
        "branch": result.get("branch"),
        "start_commit": start_commit,
        "head": result.get("head"),
        # The first stage's objective: what the run was measured from at entry.  A
        # multi-stage run changes what it measures, so `stages` below is the full answer.
        "objective": {
            **_objective_to_dict(spec.stages[0].objective),
            "baseline": status["objective_first"],
            "final": status["objective_latest_accepted"],
        },
        "stages": list(result.get("stages", [])),
        "iterations_run": result.get("iterations_run"),
        "accepted": result.get("accepted"),
        "decisions": status["decisions"],
        "iterations": [
            {
                "stage": record.get("stage", DEFAULT_STAGE_ID),
                "iteration": record.get("iteration"),
                "decision": record.get("decision"),
                "reason": record.get("reason"),
                "objective_before": record.get("objective_before"),
                "objective_after": record.get("objective_after"),
                "commit": record.get("commit"),
            }
            for record in records
        ],
        "run_dir": result.get("run_dir"),
        "ledger": str(ledger),
        "stopped": result.get("stopped"),
        "stopped_stage": result.get("stopped_stage"),
    }


def _summary_mode(path: Path, spec_path: Path) -> int:
    """Inherit the summary's permissions rather than asserting them.

    An existing summary keeps whatever mode it was given; a first one matches its spec.
    A symlink at either place is ignored — the destination is about to be replaced, and
    following one can raise on a referent the loop has no business reading.
    """
    for candidate in (path, spec_path):
        try:
            info = candidate.lstat()
        except OSError:
            continue
        if stat.S_ISREG(info.st_mode):
            return stat.S_IMODE(info.st_mode) & 0o666
    return 0o644


def write_summary(
    spec: Spec,
    repo: Path,
    *,
    result: Mapping[str, Any],
    ledger: Path,
    start_commit: str,
    run_id: str,
) -> Path | None:
    """Write the trial summary next to its spec, once, after the last iteration.

    A trial that accepted nothing still gets one — "no iteration was accepted" is a
    result to keep, not a trace to erase.  Specs outside the worktree get nothing:
    the loop leaves no files where it was not invited.
    """
    if spec.source_path is None or _relative_within(repo, spec.source_path) is None:
        return None
    path = spec.source_path.parent / SUMMARY_NAME
    payload = (
        json.dumps(
            build_summary(
                spec,
                result=result,
                ledger=ledger,
                start_commit=start_commit,
                run_id=run_id,
            ),
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    # Write beside the target and rename over it: a reader never sees half a summary,
    # and a symlink sitting at the destination is replaced rather than written through.
    # The staging name is unique and created exclusively, so it cannot be a planted
    # symlink either, and a failed write leaves nothing behind for the next run to trip on.
    handle, staged_name = tempfile.mkstemp(dir=path.parent, prefix=".summary-", suffix=".partial")
    staged = Path(staged_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(payload)
            # mkstemp creates 0600, which is narrower than the trial folder it publishes
            # into.  Inherit instead of picking a mode: whoever can read the spec is
            # exactly who should be able to read its verdict.
            os.fchmod(stream.fileno(), _summary_mode(path, spec.source_path))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(staged, path)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise
    return path


def _resolve_run_dir(args: argparse.Namespace, repo: Path, spec: Spec) -> Path:
    if args.run_dir:
        return Path(args.run_dir).resolve()
    return default_run_dir(repo, spec.loop_id)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=".", help="repository root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="parse the spec and report the resolved plan")
    validate.add_argument("spec")
    validate.add_argument("--run-dir")

    run = subparsers.add_parser("run", help="execute the loop")
    run.add_argument("spec")
    run.add_argument("--run-dir")
    run.add_argument(
        "--max-iterations",
        type=int,
        default=None,
        help="cap the whole run, across every stage",
    )
    run.add_argument(
        "--from-stage",
        default=None,
        help="skip the stages before this one (resume a partly finished run)",
    )
    run.add_argument(
        "--allow-branch",
        action="store_true",
        help="permit running on a protected branch (main/master)",
    )
    run.add_argument("--protected-branch", nargs="*", default=list(DEFAULT_PROTECTED_BRANCHES))

    status = subparsers.add_parser("status", help="summarise a ledger")
    status.add_argument("spec")
    status.add_argument("--run-dir")
    status.add_argument("--stage", default=None, help="only this stage's iterations")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    repo = Path(args.repo).resolve()
    try:
        # Resolve the directories the OS will walk, keep the final name as given.  Only
        # the parent needs real filesystem meaning — `.resolve()` on the whole path would
        # erase where the spec lives, and collapsing `..` lexically would name a different
        # file than the one actually opened — while an unresolved leaf keeps a symlinked
        # spec detectable.  stat() first, so a missing, unreadable or looping component
        # fails here instead of being folded away into some other, reachable spec.
        given = Path(args.spec)
        absolute = given if given.is_absolute() else Path.cwd() / given
        absolute.parent.stat()
        spec = load_spec(absolute.parent.resolve(strict=True) / absolute.name)
        check_spec_placement(repo, spec)
    except (SpecError, OSError) as error:
        print(json.dumps({"status": "SPEC_INVALID", "error": str(error)}, indent=2))
        return 2

    run_dir = _resolve_run_dir(args, repo, spec)

    if args.command == "validate":
        plan = spec.to_dict()
        plan["run_dir"] = str(run_dir)
        # `integrity` is what the spec declares; this is what each stage will pin.
        plan["effective_integrity"] = {
            stage.stage_id: effective_integrity_paths(repo, spec, stage) for stage in spec.stages
        }
        plan["agent_argv_preview"] = _agent_argv(
            spec.agent_command, prompt="<prompt>", prompt_file=run_dir / "prompt-0001.txt"
        )
        plan["status"] = "SPEC_VALID"
        print(json.dumps(plan, indent=2, sort_keys=True))
        return 0

    if args.command == "status":
        print(
            json.dumps(
                summarise(run_dir / "ledger.jsonl", stage=args.stage), indent=2, sort_keys=True
            )
        )
        return 0

    try:
        result = run_loop(
            spec,
            repo,
            run_dir=run_dir,
            allow_branch=args.allow_branch,
            protected=args.protected_branch,
            max_iterations=args.max_iterations,
            from_stage=args.from_stage,
        )
    except (PreconditionError, ValueError) as error:
        print(json.dumps({"status": "REFUSED", "error": str(error)}, indent=2))
        return 3
    except subprocess.CalledProcessError as error:  # pragma: no cover - git failure passthrough
        detail = (error.stderr or "").strip() or shlex.join(error.cmd)
        print(json.dumps({"status": "GIT_FAILED", "error": detail}, indent=2))
        return 4

    result["status"] = "COMPLETED_WITHOUT_SUMMARY" if "summary_error" in result else "COMPLETED"
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
