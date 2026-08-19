from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

SCRIPT = Path(__file__).parents[1] / "loop" / "experiment_loop.py"
SPEC = importlib.util.spec_from_file_location("experiment_loop", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
experiment_loop = importlib.util.module_from_spec(SPEC)
# dataclasses resolve annotations through sys.modules, so the module must be
# registered before it is executed.
sys.modules["experiment_loop"] = experiment_loop
SPEC.loader.exec_module(experiment_loop)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A git repo whose objective is the number in value.txt (lower is better)."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root.parent, "init", "-q", "-b", "work", str(root))
    _git(root, "config", "user.email", "loop@example.invalid")
    _git(root, "config", "user.name", "Experiment Loop Test")
    (root / "value.txt").write_text("10\n", encoding="utf-8")
    (root / "app.py").write_text("VALUE = 10\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    return root


@pytest.fixture
def objective(tmp_path: Path) -> Path:
    """The objective lives outside the worktree, as the loop's own docs recommend."""
    path = tmp_path / "objective.py"
    path.write_text(
        "from pathlib import Path\nprint(Path('value.txt').read_text().strip())\n",
        encoding="utf-8",
    )
    return path


def _agent(tmp_path: Path, body: str, name: str = "agent.py") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def _write_spec(
    tmp_path: Path,
    objective: Path,
    agent: Path,
    *,
    iterations: int = 1,
    guards: list[dict] | None = None,
    integrity: list[str] | None = None,
    target: float | None = None,
    margin: float = 0.0,
    dest: Path | None = None,
    loop_id: str = "unit",
) -> Path:
    spec = {
        "loop_id": loop_id,
        "objective": {
            "command": [sys.executable, str(objective)],
            "direction": "minimize",
            "margin": margin,
            "timeout_seconds": 60,
        },
        "agent": {"command": [sys.executable, str(agent)], "timeout_seconds": 60},
        "budget": {"iterations": iterations},
        "prompt": "Reduce the value.",
    }
    if target is not None:
        spec["objective"]["target"] = target
    if guards is not None:
        spec["guards"] = guards
    if integrity is not None:
        spec["integrity"] = integrity
    path = tmp_path / "spec.yaml" if dest is None else dest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def _trial_spec(
    repo: Path, tmp_path: Path, objective: Path, agent: Path, *, slot: str = "2026-08-18-unit", **kw
) -> Path:
    """A spec where a trial belongs: `loop/runs/<slot>/spec.yaml` inside the worktree."""
    return _write_spec(
        tmp_path, objective, agent, dest=repo / "loop" / "runs" / slot / "spec.yaml", **kw
    )


def _run(repo: Path, spec: Path, *args: str) -> tuple[subprocess.CompletedProcess[str], dict]:
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "run", str(spec), *args],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    return result, json.loads(result.stdout)


def _ledger(payload: dict) -> list[dict]:
    return [json.loads(line) for line in Path(payload["ledger"]).read_text().splitlines() if line]


# --- spec validation -------------------------------------------------------


def test_spec_rejects_shell_string_command(tmp_path: Path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "loop_id": "x",
                "objective": {"command": "echo 1", "direction": "minimize"},
                "agent": {"command": ["true"]},
                "budget": {"iterations": 1},
                "prompt": "go",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(experiment_loop.SpecError, match="not a shell string"):
        experiment_loop.load_spec(path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ({"loop_id": "bad id"}, "alphanumerics"),
        ({"budget": {"iterations": 0}}, "positive integer"),
        ({"prompt": "  "}, "non-empty string"),
        ({"unexpected": 1}, "unknown keys"),
    ],
)
def test_spec_rejects_malformed_fields(tmp_path: Path, mutation: dict, message: str) -> None:
    spec = {
        "loop_id": "ok",
        "objective": {"command": ["true"], "direction": "minimize"},
        "agent": {"command": ["true"]},
        "budget": {"iterations": 1},
        "prompt": "go",
    }
    spec.update(mutation)
    path = tmp_path / "spec.yaml"
    path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    with pytest.raises(experiment_loop.SpecError, match=message):
        experiment_loop.load_spec(path)


def test_spec_rejects_duplicate_guard_ids(tmp_path: Path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "loop_id": "ok",
                "objective": {"command": ["true"], "direction": "minimize"},
                "agent": {"command": ["true"]},
                "guards": [
                    {"id": "same", "command": ["true"]},
                    {"id": "same", "command": ["true"]},
                ],
                "budget": {"iterations": 1},
                "prompt": "go",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(experiment_loop.SpecError, match="duplicates an earlier guard"):
        experiment_loop.load_spec(path)


# --- preconditions ---------------------------------------------------------


def test_refuses_dirty_worktree(repo: Path, objective: Path, tmp_path: Path) -> None:
    agent = _agent(tmp_path, "pass\n")
    spec = _write_spec(tmp_path, objective, agent)
    (repo / "value.txt").write_text("999\n", encoding="utf-8")
    result, payload = _run(repo, spec)
    assert result.returncode == 3
    assert payload["status"] == "REFUSED"
    assert "uncommitted changes" in payload["error"]
    assert (repo / "value.txt").read_text().strip() == "999"


def test_refuses_protected_branch(repo: Path, objective: Path, tmp_path: Path) -> None:
    _git(repo, "branch", "-m", "main")
    agent = _agent(tmp_path, "pass\n")
    spec = _write_spec(tmp_path, objective, agent)
    result, payload = _run(repo, spec)
    assert result.returncode == 3
    assert "protected branch" in payload["error"]


def test_refuses_missing_pinned_path(repo: Path, objective: Path, tmp_path: Path) -> None:
    agent = _agent(tmp_path, "pass\n")
    spec = _write_spec(tmp_path, objective, agent, integrity=["nope.txt"])
    result, payload = _run(repo, spec)
    assert result.returncode == 3
    assert "do not exist" in payload["error"]


# --- accept / reject -------------------------------------------------------


IMPROVING_AGENT = """
from pathlib import Path

current = int(Path('value.txt').read_text().strip())
Path('value.txt').write_text(f"{current - 1}\\n")
print("SUMMARY: decremented the value")
"""

WORSENING_AGENT = """
from pathlib import Path

current = int(Path('value.txt').read_text().strip())
Path('value.txt').write_text(f"{current + 5}\\n")
Path('junk.txt').write_text("stray\\n")
print("SUMMARY: made it worse")
"""


def test_accepts_and_commits_an_improvement(repo: Path, objective: Path, tmp_path: Path) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _write_spec(tmp_path, objective, agent, iterations=3)
    before_head = _git(repo, "rev-parse", "HEAD")

    result, payload = _run(repo, spec)

    assert result.returncode == 0, result.stdout + result.stderr
    assert payload["accepted"] == 3
    assert (repo / "value.txt").read_text().strip() == "7"
    assert _git(repo, "status", "--porcelain") == ""
    assert len(_git(repo, "rev-list", f"{before_head}..HEAD").splitlines()) == 3

    records = _ledger(payload)
    assert [record["decision"] for record in records] == ["accepted"] * 3
    assert records[0]["objective_before"] == 10.0
    assert records[0]["objective_after"] == 9.0
    assert records[0]["agent_summary"] == "decremented the value"
    assert records[0]["commit"]


def test_rejects_and_reverts_a_regression(repo: Path, objective: Path, tmp_path: Path) -> None:
    agent = _agent(tmp_path, WORSENING_AGENT)
    spec = _write_spec(tmp_path, objective, agent, iterations=2)
    before_head = _git(repo, "rev-parse", "HEAD")

    result, payload = _run(repo, spec)

    assert result.returncode == 0
    assert payload["accepted"] == 0
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert (repo / "value.txt").read_text().strip() == "10"
    assert not (repo / "junk.txt").exists()
    assert _git(repo, "status", "--porcelain") == ""

    records = _ledger(payload)
    assert [record["decision"] for record in records] == ["rejected", "rejected"]
    assert "did not improve" in records[0]["reason"]


def test_margin_rejects_an_improvement_that_is_too_small(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _write_spec(tmp_path, objective, agent, margin=2.0)
    _, payload = _run(repo, spec)
    assert payload["accepted"] == 0
    assert "did not improve" in _ledger(payload)[0]["reason"]


def test_no_op_agent_is_recorded_without_a_commit(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, "print('SUMMARY: did nothing')\n")
    spec = _write_spec(tmp_path, objective, agent)
    _, payload = _run(repo, spec)
    record = _ledger(payload)[0]
    assert record["decision"] == "rejected"
    assert record["reason"] == "the agent left the worktree unchanged"
    assert record["commit"] is None


def test_stops_early_when_the_target_is_reached(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _write_spec(tmp_path, objective, agent, iterations=10, target=8)
    _, payload = _run(repo, spec)
    assert payload["stopped"] == "target_reached"
    assert payload["iterations_run"] == 2
    assert (repo / "value.txt").read_text().strip() == "8"


def test_max_iterations_caps_the_spec_budget(repo: Path, objective: Path, tmp_path: Path) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _write_spec(tmp_path, objective, agent, iterations=10)
    _, payload = _run(repo, spec, "--max-iterations", "1")
    assert payload["iterations_run"] == 1


# --- guards ----------------------------------------------------------------


def test_guard_failure_reverts_even_when_the_objective_improves(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    agent = _agent(
        tmp_path,
        IMPROVING_AGENT + "\nfrom pathlib import Path\nPath('app.py').write_text('broken(\\n')\n",
    )
    checker = _agent(
        tmp_path,
        "import ast\nimport sys\nfrom pathlib import Path\n\n"
        "try:\n    ast.parse(Path('app.py').read_text())\n"
        "except SyntaxError:\n    sys.exit(1)\n",
        name="parses.py",
    )
    spec = _write_spec(
        tmp_path,
        objective,
        agent,
        guards=[{"id": "parses", "command": [sys.executable, str(checker)]}],
    )
    before_head = _git(repo, "rev-parse", "HEAD")

    _, payload = _run(repo, spec)

    record = _ledger(payload)[0]
    assert record["decision"] == "rejected"
    assert record["reason"] == "guard parses exited 1"
    assert record["guards"] == [
        {"id": "parses", "kind": "exit_zero", "status": "fail", "exit_code": 1}
    ]
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert (repo / "app.py").read_text() == "VALUE = 10\n"


def test_non_decreasing_number_guard_blocks_deleted_checks(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """The classic failure: the agent improves the metric by deleting the tests."""
    (repo / "checks.txt").write_text("a\nb\nc\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add checks")
    counter = _agent(
        tmp_path,
        "from pathlib import Path\n"
        "print(len([x for x in Path('checks.txt').read_text().splitlines() if x]))\n",
        name="count.py",
    )
    agent = _agent(
        tmp_path,
        IMPROVING_AGENT + "\nfrom pathlib import Path\nPath('checks.txt').write_text('a\\n')\n",
    )
    spec = _write_spec(
        tmp_path,
        objective,
        agent,
        guards=[
            {
                "id": "check-count",
                "command": [sys.executable, str(counter)],
                "kind": "non_decreasing_number",
            }
        ],
    )

    _, payload = _run(repo, spec)

    record = _ledger(payload)[0]
    assert record["decision"] == "rejected"
    assert record["reason"] == "guard check-count dropped from 3 to 1"
    assert (repo / "checks.txt").read_text() == "a\nb\nc\n"


def test_unchanged_output_guard_blocks_a_surface_change(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    surface = _agent(
        tmp_path,
        "from pathlib import Path\nprint(Path('app.py').read_text().splitlines()[0])\n",
        name="surface.py",
    )
    agent = _agent(
        tmp_path,
        IMPROVING_AGENT
        + "\nfrom pathlib import Path\nPath('app.py').write_text('RENAMED = 1\\n')\n",
    )
    spec = _write_spec(
        tmp_path,
        objective,
        agent,
        guards=[
            {
                "id": "public-surface",
                "command": [sys.executable, str(surface)],
                "kind": "unchanged_output",
            }
        ],
    )

    _, payload = _run(repo, spec)

    record = _ledger(payload)[0]
    assert record["reason"] == "guard public-surface output changed"
    assert (repo / "app.py").read_text() == "VALUE = 10\n"


def test_guard_failing_before_the_loop_starts_is_refused(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    failing = _agent(tmp_path, "raise SystemExit(1)\n", name="failing.py")
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _write_spec(
        tmp_path,
        objective,
        agent,
        guards=[
            {
                "id": "baseline",
                "command": [sys.executable, str(failing)],
                "kind": "non_decreasing_number",
            }
        ],
    )
    result, payload = _run(repo, spec)
    assert result.returncode == 3
    assert "must pass before the stage starts" in payload["error"]


# --- integrity -------------------------------------------------------------


def test_editing_a_pinned_path_voids_the_iteration(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """An agent that rewrites the scoring rules gets its whole iteration discarded."""
    (repo / "scoring.txt").write_text("honest\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add scoring")
    agent = _agent(
        tmp_path,
        IMPROVING_AGENT
        + "\nfrom pathlib import Path\nPath('scoring.txt').write_text('rigged\\n')\n",
    )
    spec = _write_spec(tmp_path, objective, agent, integrity=["scoring.txt"])
    before_head = _git(repo, "rev-parse", "HEAD")

    _, payload = _run(repo, spec)

    record = _ledger(payload)[0]
    assert record["decision"] == "void"
    assert record["reason"] == "a pinned path changed during the iteration"
    assert (repo / "scoring.txt").read_text() == "honest\n"
    assert (repo / "value.txt").read_text().strip() == "10"
    assert _git(repo, "rev-parse", "HEAD") == before_head


# --- prompt and subcommands ------------------------------------------------


def test_prompt_carries_history_so_the_agent_needs_no_memory(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, WORSENING_AGENT)
    spec = _write_spec(tmp_path, objective, agent, iterations=2)
    _, payload = _run(repo, spec)
    second = Path(payload["run_dir"]) / "prompt-main-0002.txt"
    text = second.read_text(encoding="utf-8")
    assert "#1 rejected" in text
    assert "made it worse" in text
    assert "- iteration: 2 of 2" in text


def test_validate_reports_the_resolved_plan(repo: Path, objective: Path, tmp_path: Path) -> None:
    agent = _agent(tmp_path, "pass\n")
    spec = _write_spec(tmp_path, objective, agent)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "validate", str(spec)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 0
    assert payload["status"] == "SPEC_VALID"
    assert payload["loop_id"] == "unit"
    assert payload["run_dir"].endswith("/.git/experiment-loop/unit")


def test_status_summarises_the_ledger(repo: Path, objective: Path, tmp_path: Path) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _write_spec(tmp_path, objective, agent, iterations=2)
    _run(repo, spec)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "status", str(spec)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["iterations"] == 2
    assert payload["decisions"] == {"accepted": 2}
    assert payload["objective_first"] == 10.0
    assert payload["objective_latest_accepted"] == 8.0


def test_ledger_survives_the_revert(repo: Path, objective: Path, tmp_path: Path) -> None:
    """The ledger lives in the git dir, so 'git clean -fd' cannot erase the history."""
    agent = _agent(tmp_path, WORSENING_AGENT)
    spec = _write_spec(tmp_path, objective, agent, iterations=2)
    _, payload = _run(repo, spec)
    ledger = Path(payload["ledger"])
    assert ledger.is_relative_to(repo / ".git")
    assert len(_ledger(payload)) == 2


# --- trial folders ---------------------------------------------------------


def test_refuses_an_untracked_spec_inside_the_worktree(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """`git clean -fd` on the first rejection would delete it mid-run."""
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent)

    result, payload = _run(repo, spec)

    assert result.returncode == 3
    assert payload["status"] == "REFUSED"
    assert "untracked" in payload["error"]
    assert "git clean -fd" in payload["error"]
    assert spec.exists()


def test_accepts_a_committed_spec_inside_the_worktree(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent, iterations=2)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec")

    result, payload = _run(repo, spec)

    assert result.returncode == 0, result.stdout + result.stderr
    assert payload["accepted"] == 2
    assert (repo / "value.txt").read_text().strip() == "8"


def test_a_finished_trial_leaves_a_summary_beside_its_spec(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent, iterations=2)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec")
    start_commit = _git(repo, "rev-parse", "HEAD")

    _, payload = _run(repo, spec)

    summary_path = spec.parent / "summary.json"
    assert Path(payload["summary"]) == summary_path
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["loop_id"] == "unit"
    assert summary["start_commit"] == start_commit
    assert summary["objective"]["baseline"] == 10.0
    assert summary["objective"]["final"] == 8.0
    assert summary["objective"]["direction"] == "minimize"
    assert summary["accepted"] == 2
    assert summary["decisions"] == {"accepted": 2}
    assert summary["stopped"] == "budget_exhausted"
    assert summary["run_dir"] == payload["run_dir"]
    assert [record["decision"] for record in summary["iterations"]] == ["accepted", "accepted"]
    assert "improved" in summary["iterations"][0]["reason"]
    assert summary["run_id"] == payload["run_id"]
    assert summary["spec_digest"] == hashlib.sha256(spec.read_bytes()).hexdigest()


def test_a_trial_that_accepted_nothing_still_leaves_a_summary(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """A failed trial is a result to keep, not a trace to erase."""
    agent = _agent(tmp_path, WORSENING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent, iterations=2)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec")

    _, payload = _run(repo, spec)

    summary = json.loads((spec.parent / "summary.json").read_text(encoding="utf-8"))
    assert summary["accepted"] == 0
    assert summary["decisions"] == {"rejected": 2}
    assert summary["objective"]["final"] is None
    assert [record["decision"] for record in summary["iterations"]] == ["rejected", "rejected"]


def test_a_trial_folder_must_end_with_its_loop_id(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """Otherwise the folder and the ledger at .git/experiment-loop/<loop_id>/ split up."""
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent, slot="2026-08-18-something-else")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec")

    for command in ("validate", "run"):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "--repo", str(repo), command, str(spec)],
            cwd=repo,
            check=False,
            capture_output=True,
            text=True,
        )
        payload = json.loads(result.stdout)
        assert result.returncode == 2, command
        assert payload["status"] == "SPEC_INVALID"
        assert "must be named" in payload["error"]


def test_a_spec_outside_the_worktree_stays_untouched(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """The loop leaves no files where it was not invited."""
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _write_spec(tmp_path, objective, agent)

    result, payload = _run(repo, spec)

    assert result.returncode == 0
    assert payload["accepted"] == 1
    assert "summary" not in payload
    assert not (spec.parent / "summary.json").exists()


def test_a_trial_spec_must_sit_directly_in_its_folder(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """A nested spec would drop its summary somewhere other than the trial root."""
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _write_spec(
        tmp_path,
        objective,
        agent,
        dest=repo / "loop" / "runs" / "2026-08-18-unit" / "nested" / "spec.yaml",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "validate", str(spec)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert "must sit directly in its trial folder" in payload["error"]


def test_a_trial_folder_may_not_bury_the_loop_id_in_the_middle(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """'2026-08-18-other-unit' ends with '-unit' but names a different trial."""
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent, slot="2026-08-18-other-unit")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "validate", str(spec)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert "must be named" in payload["error"]


def test_a_trial_folder_without_a_date_is_still_the_loop_id(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent, slot="unit")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "validate", str(spec)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout)["status"] == "SPEC_VALID"


def test_an_agent_that_rewrites_its_own_spec_voids_the_iteration(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """An in-worktree spec is a scoring input, so it is pinned like any other."""
    spec_path = repo / "loop" / "runs" / "2026-08-18-unit" / "spec.yaml"
    tamper = _agent(
        tmp_path,
        IMPROVING_AGENT
        + f"\nfrom pathlib import Path\nPath({str(spec_path)!r}).write_text('loop_id: rigged\\n')\n",
        name="tamper.py",
    )
    spec = _trial_spec(repo, tmp_path, objective, tamper)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec")
    before_head = _git(repo, "rev-parse", "HEAD")

    _, payload = _run(repo, spec)

    record = _ledger(payload)[0]
    assert record["decision"] == "void"
    assert record["reason"] == "a pinned path changed during the iteration"
    assert _git(repo, "rev-parse", "HEAD") == before_head
    assert "loop_id: unit" in spec.read_text(encoding="utf-8")


def test_the_summary_covers_this_run_only(repo: Path, objective: Path, tmp_path: Path) -> None:
    """The ledger is keyed by loop_id and append-only; earlier trials are not this one."""
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent, iterations=1)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec")

    _run(repo, spec)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "keep the first summary")
    second_start = _git(repo, "rev-parse", "HEAD")

    _, payload = _run(repo, spec)

    assert len(_ledger(payload)) == 2
    summary = json.loads((spec.parent / "summary.json").read_text(encoding="utf-8"))
    assert summary["start_commit"] == second_start
    assert [record["iteration"] for record in summary["iterations"]] == [1]
    assert summary["objective"]["baseline"] == 9.0
    assert summary["objective"]["final"] == 8.0


def test_refuses_a_run_dir_inside_the_worktree(repo: Path, objective: Path, tmp_path: Path) -> None:
    """The loop's own revert would erase the ledger that records the rejection."""
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _write_spec(tmp_path, objective, agent)
    result, payload = _run(repo, spec, "--run-dir", str(repo / "loop" / "runs" / "2026-08-18-unit"))
    assert result.returncode == 3
    assert "inside the worktree" in payload["error"]


def test_the_summary_replaces_a_symlink_instead_of_writing_through_it(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent)
    outsider = tmp_path / "outsider.json"
    outsider.write_text("keep me\n", encoding="utf-8")
    (spec.parent / "summary.json").symlink_to(outsider)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec")

    _run(repo, spec)

    assert outsider.read_text(encoding="utf-8") == "keep me\n"
    summary_path = spec.parent / "summary.json"
    assert not summary_path.is_symlink()
    assert json.loads(summary_path.read_text(encoding="utf-8"))["loop_id"] == "unit"


# --- stages ----------------------------------------------------------------


STAGED_AGENT = """
import os
from pathlib import Path

stage = os.environ["EXPERIMENT_LOOP_STAGE"]
if stage == "scaffold":
    Path('flag.txt').write_text("ok\\n")
    print("SUMMARY: created the flag")
else:
    current = int(Path('value.txt').read_text().strip())
    Path('value.txt').write_text(f"{current - 1}\\n")
    print("SUMMARY: decremented the value")
"""

FLAG_OBJECTIVE = "from pathlib import Path\nprint(0 if Path('flag.txt').exists() else 1)\n"


@pytest.fixture
def flag_objective(tmp_path: Path) -> Path:
    """1 while the scaffold file is missing, 0 once it exists."""
    path = tmp_path / "flag_objective.py"
    path.write_text(FLAG_OBJECTIVE, encoding="utf-8")
    return path


def _stage(
    stage_id: str,
    objective: Path,
    *,
    iterations: int = 1,
    target: float | None = None,
    margin: float = 1.0,
    guards: list[dict] | None = None,
    integrity: list[str] | None = None,
    on_incomplete: str | None = None,
) -> dict:
    stage: dict = {
        "id": stage_id,
        "objective": {
            "command": [sys.executable, str(objective)],
            "direction": "minimize",
            "margin": margin,
            "timeout_seconds": 60,
        },
        "budget": {"iterations": iterations},
        "prompt": f"Do the {stage_id} work.",
    }
    if target is not None:
        stage["objective"]["target"] = target
    if guards is not None:
        stage["guards"] = guards
    if integrity is not None:
        stage["integrity"] = integrity
    if on_incomplete is not None:
        stage["on_incomplete"] = on_incomplete
    return stage


def _write_stages_spec(
    tmp_path: Path,
    agent: Path,
    stages: list[dict],
    *,
    dest: Path | None = None,
    loop_id: str = "unit",
    integrity: list[str] | None = None,
) -> Path:
    spec: dict = {
        "loop_id": loop_id,
        "agent": {"command": [sys.executable, str(agent)], "timeout_seconds": 60},
        "stages": stages,
    }
    if integrity is not None:
        spec["integrity"] = integrity
    path = tmp_path / "spec.yaml" if dest is None else dest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return path


def test_spec_rejects_stages_mixed_with_a_top_level_objective(
    tmp_path: Path, objective: Path
) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _write_stages_spec(tmp_path, agent, [_stage("one", objective)])
    raw = yaml.safe_load(spec.read_text())
    raw["objective"] = {"command": ["true"], "direction": "minimize"}
    spec.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "validate", str(spec)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "declares both $.stages and top-level" in json.loads(result.stdout)["error"]


@pytest.mark.parametrize(
    ("stages", "message"),
    [
        ([], "$.stages must be a non-empty list"),
        ("scaffold", "$.stages must be a non-empty list"),
    ],
)
def test_spec_rejects_unusable_stage_lists(tmp_path: Path, stages: object, message: str) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text(
        yaml.safe_dump(
            {"loop_id": "unit", "agent": {"command": ["true"]}, "stages": stages}, sort_keys=False
        ),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "validate", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert message in json.loads(result.stdout)["error"]


def test_spec_rejects_duplicate_stage_ids(tmp_path: Path, objective: Path) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _write_stages_spec(
        tmp_path, agent, [_stage("same", objective), _stage("same", objective)]
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "validate", str(spec)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "duplicates an earlier stage" in json.loads(result.stdout)["error"]


def test_a_spec_with_neither_stages_nor_an_objective_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text(
        yaml.safe_dump({"loop_id": "unit", "agent": {"command": ["true"]}}, sort_keys=False),
        encoding="utf-8",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "validate", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert "must declare either $.stages" in json.loads(result.stdout)["error"]


def test_stages_run_in_order_each_measured_by_its_own_objective(
    repo: Path, objective: Path, flag_objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, STAGED_AGENT)
    spec = _write_stages_spec(
        tmp_path,
        agent,
        [
            _stage("scaffold", flag_objective, iterations=3, target=0),
            _stage("work", objective, iterations=5, target=8),
        ],
    )
    result, payload = _run(repo, spec)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (repo / "flag.txt").exists()
    assert (repo / "value.txt").read_text().strip() == "8"
    assert payload["stopped"] == "target_reached"
    assert payload["stopped_stage"] == "work"
    assert [record["stage"] for record in _ledger(payload)] == ["scaffold", "work", "work"]
    assert [stage["id"] for stage in payload["stages"]] == ["scaffold", "work"]

    subjects = _git(repo, "log", "-3", "--format=%s").splitlines()
    assert subjects[-1].startswith("exp(unit/scaffold): iteration 1")
    assert subjects[0].startswith("exp(unit/work): iteration 2")


def test_a_stage_pins_only_its_own_integrity_paths(
    repo: Path, objective: Path, flag_objective: Path, tmp_path: Path
) -> None:
    """The stage that creates the scoring input cannot pin it; the next one must."""
    agent = _agent(
        tmp_path,
        STAGED_AGENT
        + """
if stage != "scaffold":
    Path('flag.txt').write_text("tampered\\n")
""",
    )
    spec = _write_stages_spec(
        tmp_path,
        agent,
        [
            _stage("scaffold", flag_objective, iterations=2, target=0),
            _stage("work", objective, iterations=2, target=8, integrity=["flag.txt"]),
        ],
    )
    _, payload = _run(repo, spec)

    records = _ledger(payload)
    scaffold = [record for record in records if record["stage"] == "scaffold"]
    work = [record for record in records if record["stage"] == "work"]
    assert [record["decision"] for record in scaffold] == ["accepted"]
    assert [record["decision"] for record in work] == ["void", "void"]
    assert work[0]["reason"] == "a pinned path changed during the iteration"
    assert (repo / "flag.txt").read_text().strip() == "ok"


def test_an_incomplete_stage_stops_the_run_by_default(
    repo: Path, objective: Path, flag_objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, "print('SUMMARY: did nothing')\n")
    spec = _write_stages_spec(
        tmp_path,
        agent,
        [
            _stage("scaffold", flag_objective, iterations=2, target=0),
            _stage("work", objective, iterations=2, target=8),
        ],
    )
    _, payload = _run(repo, spec)

    assert payload["stopped"] == "budget_exhausted"
    assert payload["stopped_stage"] == "scaffold"
    assert {record["stage"] for record in _ledger(payload)} == {"scaffold"}
    assert [stage["id"] for stage in payload["stages"]] == ["scaffold"]


def test_on_incomplete_continue_lets_the_next_stage_run(
    repo: Path, objective: Path, flag_objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, STAGED_AGENT)
    spec = _write_stages_spec(
        tmp_path,
        agent,
        [
            # target 0 is unreachable in one iteration only if the agent no-ops; here the
            # stage simply runs out of budget before its target, and says carry on.
            _stage("scaffold", flag_objective, iterations=1, target=-1, on_incomplete="continue"),
            _stage("work", objective, iterations=1, target=8),
        ],
    )
    _, payload = _run(repo, spec)

    assert {record["stage"] for record in _ledger(payload)} == {"scaffold", "work"}
    assert [stage["id"] for stage in payload["stages"]] == ["scaffold", "work"]


def test_a_later_stage_that_cannot_be_measured_stops_the_run_with_a_summary(
    repo: Path, flag_objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, STAGED_AGENT)
    broken = _agent(tmp_path, "raise SystemExit(1)\n", name="broken_objective.py")
    spec = _write_stages_spec(
        tmp_path,
        agent,
        [
            _stage("scaffold", flag_objective, iterations=2, target=0),
            _stage("work", broken, iterations=2),
        ],
        dest=repo / "loop" / "runs" / "2026-08-18-unit" / "spec.yaml",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "spec")

    result, payload = _run(repo, spec)

    assert result.returncode == 0
    assert payload["stopped"] == "objective_unmeasurable"
    assert payload["stopped_stage"] == "work"
    summary = json.loads(Path(payload["summary"]).read_text())
    assert summary["stopped_stage"] == "work"
    assert [stage["id"] for stage in summary["stages"]] == ["scaffold", "work"]


def test_a_stage_already_at_its_target_is_skipped_without_calling_the_agent(
    repo: Path, objective: Path, flag_objective: Path, tmp_path: Path
) -> None:
    (repo / "flag.txt").write_text("ok\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "flag already there")
    agent = _agent(tmp_path, STAGED_AGENT)
    spec = _write_stages_spec(
        tmp_path,
        agent,
        [
            _stage("scaffold", flag_objective, iterations=3, target=0),
            _stage("work", objective, iterations=1, target=8),
        ],
    )
    _, payload = _run(repo, spec)

    assert {record["stage"] for record in _ledger(payload)} == {"work"}
    scaffold = payload["stages"][0]
    assert scaffold["stopped"] == "target_reached"
    assert scaffold["iterations_run"] == 0


def test_from_stage_skips_the_stages_before_it(
    repo: Path, objective: Path, flag_objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, STAGED_AGENT)
    spec = _write_stages_spec(
        tmp_path,
        agent,
        [
            _stage("scaffold", flag_objective, iterations=2, target=0),
            _stage("work", objective, iterations=1, target=8),
        ],
    )
    _, payload = _run(repo, spec, "--from-stage", "work")

    assert not (repo / "flag.txt").exists()
    assert {record["stage"] for record in _ledger(payload)} == {"work"}


def test_from_stage_rejects_an_unknown_stage(
    repo: Path, objective: Path, flag_objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, STAGED_AGENT)
    spec = _write_stages_spec(tmp_path, agent, [_stage("scaffold", flag_objective)])
    result, payload = _run(repo, spec, "--from-stage", "nope")
    assert result.returncode == 3
    assert "is not a stage of this spec" in payload["error"]


def test_the_guard_baseline_is_recaptured_for_each_stage(
    repo: Path, objective: Path, flag_objective: Path, tmp_path: Path
) -> None:
    """A stage compares against the tree it inherited, not the one the run started on.

    Stage 1 raises the guard's number; stage 2 puts it back.  Only a per-stage baseline
    notices — a baseline captured once at run start would wave the regression through.
    """
    (repo / "checks.txt").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "checks")
    counter = _agent(
        tmp_path,
        "from pathlib import Path\nprint(len(Path('checks.txt').read_text().split()))\n",
        name="counter.py",
    )
    agent = _agent(
        tmp_path,
        STAGED_AGENT
        + """
if stage == "scaffold":
    Path('checks.txt').write_text("a\\nb\\n")
else:
    Path('checks.txt').write_text("a\\n")
""",
    )
    guards = [
        {"id": "checks", "command": [sys.executable, str(counter)], "kind": "non_decreasing_number"}
    ]
    spec = _write_stages_spec(
        tmp_path,
        agent,
        [
            _stage("scaffold", flag_objective, iterations=1, target=0, guards=guards),
            _stage("work", objective, iterations=1, target=8, guards=guards),
        ],
    )
    _, payload = _run(repo, spec)

    records = {record["stage"]: record for record in _ledger(payload)}
    assert records["scaffold"]["decision"] == "accepted"
    assert records["work"]["decision"] == "rejected"
    assert "dropped from 2 to 1" in records["work"]["reason"]


def test_status_can_filter_by_stage(
    repo: Path, objective: Path, flag_objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, STAGED_AGENT)
    spec = _write_stages_spec(
        tmp_path,
        agent,
        [
            _stage("scaffold", flag_objective, iterations=1, target=0),
            _stage("work", objective, iterations=2, target=8),
        ],
    )
    _run(repo, spec)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "status", str(spec), "--stage", "work"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["iterations"] == 2
    assert [stage["id"] for stage in payload["stages"]] == ["work"]


def test_max_iterations_caps_the_whole_run_not_each_stage(
    repo: Path, objective: Path, flag_objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, STAGED_AGENT)
    spec = _write_stages_spec(
        tmp_path,
        agent,
        [
            _stage("scaffold", flag_objective, iterations=2, target=0),
            _stage("work", objective, iterations=5, target=5),
        ],
    )
    _, payload = _run(repo, spec, "--max-iterations", "3")
    assert payload["iterations_run"] == 3


def test_shared_integrity_coexists_with_stages(
    repo: Path, objective: Path, flag_objective: Path, tmp_path: Path
) -> None:
    """`integrity` is shared, not stage-defining: declaring both forms is not a mix."""
    agent = _agent(
        tmp_path,
        STAGED_AGENT
        + """
Path('app.py').write_text("VALUE = 0\\n")
""",
    )
    spec = _write_stages_spec(
        tmp_path,
        agent,
        [
            _stage("scaffold", flag_objective, iterations=1, target=0),
            _stage("work", objective, iterations=1, target=8),
        ],
        integrity=["app.py"],
    )
    _, payload = _run(repo, spec)

    records = _ledger(payload)
    assert [record["decision"] for record in records] == ["void"]
    assert records[0]["reason"] == "a pinned path changed during the iteration"
    assert payload["stopped"] == "budget_exhausted"


def test_a_nondeterministic_counting_guard_is_refused(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """A guard whose number moves on an unchanged tree would reject at random."""
    drifting = _agent(
        tmp_path,
        "from pathlib import Path\n"
        "counter = Path(__file__).with_name('reads.txt')\n"
        "n = int(counter.read_text()) if counter.exists() else 0\n"
        "counter.write_text(str(n + 1))\n"
        "print(n)\n",
        name="drifting_guard.py",
    )
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _write_spec(
        tmp_path,
        objective,
        agent,
        guards=[
            {
                "id": "drifting",
                "command": [sys.executable, str(drifting)],
                "kind": "non_decreasing_number",
            }
        ],
    )
    result, payload = _run(repo, spec)
    assert result.returncode == 3
    assert "is not deterministic" in payload["error"]


# --- what a spec in the worktree costs -------------------------------------


def test_refuses_a_symlinked_spec_inside_the_worktree(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """Pinning a symlink pins its target's bytes, not where it points."""
    agent = _agent(tmp_path, IMPROVING_AGENT)
    real = _write_spec(tmp_path, objective, agent)
    link = repo / "loop" / "runs" / "2026-08-18-unit" / "spec.yaml"
    link.parent.mkdir(parents=True)
    link.symlink_to(real)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec")

    result, payload = _run(repo, link)

    assert result.returncode == 3
    assert "is a symlink" in payload["error"]


def test_a_trial_folder_holds_exactly_one_spec(repo: Path, objective: Path, tmp_path: Path) -> None:
    """Two specs in one folder would fight over the folder's single summary.json."""
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _write_spec(
        tmp_path,
        objective,
        agent,
        dest=repo / "loop" / "runs" / "2026-08-18-unit" / "other.yaml",
    )
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "validate", str(spec)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert "named spec.yaml" in payload["error"]


def test_validate_reports_the_spec_it_will_pin_for_you(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent, integrity=["value.txt"])
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "validate", str(spec)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert payload["integrity"] == ["value.txt"]
    assert payload["effective_integrity"] == {
        "main": ["value.txt", "loop/runs/2026-08-18-unit/spec.yaml"]
    }


def test_the_spec_that_runs_is_the_spec_that_is_checked(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """A symlinked directory plus '..' must not let an outside spec borrow an inside one's
    tracked status, pins and summary location."""
    inside = _trial_spec(repo, tmp_path, objective, _agent(tmp_path, IMPROVING_AGENT), slot="unit")
    outside_agent = _agent(
        tmp_path,
        IMPROVING_AGENT
        + "\nfrom pathlib import Path\nPath('outside-ran.txt').write_text('x\\n')\n",
        name="outside_agent.py",
    )
    outside = _write_spec(
        tmp_path, objective, outside_agent, dest=tmp_path / "outside" / "unit" / "spec.yaml"
    )
    (tmp_path / "outside" / "child").mkdir()
    (repo / "loop" / "runs" / "link").symlink_to(tmp_path / "outside" / "child")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec and link")

    result, payload = _run(repo, repo / "loop" / "runs" / "link" / ".." / "unit" / "spec.yaml")

    assert result.returncode == 0, result.stdout + result.stderr
    # The outside spec ran, so the outside spec is what the checks had to apply to.
    assert (repo / "outside-ran.txt").exists()
    assert "summary" not in payload
    assert not (outside.parent / "summary.json").exists()
    assert not (inside.parent / "summary.json").exists()


def test_a_spec_path_with_dot_dot_still_finds_its_trial_folder(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """The path is absolutised but not normalised, so it must still place correctly."""
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec")
    detoured = spec.parent / ".." / spec.parent.name / spec.name

    result, payload = _run(repo, detoured)

    assert result.returncode == 0, result.stdout + result.stderr
    assert payload["accepted"] == 1
    assert (spec.parent / "summary.json").exists()


def test_a_spec_path_through_a_missing_directory_is_rejected(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """'missing/../real.yaml' is a path the OS cannot open; folding it away would run a
    different, reachable spec than the one named."""
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent)
    detoured = repo / "definitely-missing" / ".." / spec.relative_to(repo)
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo", str(repo), "validate", str(detoured)],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert result.returncode == 2
    assert payload["status"] == "SPEC_INVALID"


# --- the summary is published, not just written ----------------------------


def test_a_truncated_ledger_tail_does_not_swallow_this_run(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """A run killed mid-write leaves a line without its newline; the next append must not
    fuse with it, or both records become unreadable and the run reports as empty."""
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec")
    ledger = Path(experiment_loop.default_run_dir(repo, "unit")) / "ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text('{"decision": "accepted", "iterat', encoding="utf-8")

    _, payload = _run(repo, spec)

    summary = json.loads((spec.parent / "summary.json").read_text(encoding="utf-8"))
    assert summary["accepted"] == 1
    assert [record["decision"] for record in summary["iterations"]] == ["accepted"]
    lines = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert json.loads(lines[-1])["run_id"] == payload["run_id"]


def test_the_summary_inherits_the_permissions_of_its_spec(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec")
    spec.chmod(0o640)

    _run(repo, spec)

    assert stat.S_IMODE((spec.parent / "summary.json").stat().st_mode) == 0o640


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_an_unreadable_symlink_target_does_not_block_the_summary(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """The destination link is replaced, not followed, so its referent must never be
    reached — not even to read a permission bit."""
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent)
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "old-summary.json").write_text("{}\n", encoding="utf-8")
    (spec.parent / "summary.json").symlink_to(vault / "old-summary.json")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec")
    vault.chmod(0o000)
    try:
        result, payload = _run(repo, spec)
    finally:
        vault.chmod(0o755)

    assert result.returncode == 0, result.stdout + result.stderr
    assert payload["status"] == "COMPLETED"
    summary_path = spec.parent / "summary.json"
    assert not summary_path.is_symlink()
    assert json.loads(summary_path.read_text(encoding="utf-8"))["loop_id"] == "unit"
    assert (vault / "old-summary.json").read_text(encoding="utf-8") == "{}\n"


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory permissions")
def test_a_summary_that_cannot_be_written_does_not_swallow_the_run(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    agent = _agent(tmp_path, IMPROVING_AGENT)
    spec = _trial_spec(repo, tmp_path, objective, agent)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add trial spec")
    spec.parent.chmod(0o555)
    try:
        result, payload = _run(repo, spec)
    finally:
        spec.parent.chmod(0o755)

    assert result.returncode == 0
    assert payload["status"] == "COMPLETED_WITHOUT_SUMMARY"
    assert payload["accepted"] == 1
    assert "summary_error" in payload
    assert "summary" not in payload
    assert not (spec.parent / "summary.json").exists()
    # A failed write leaves nothing for the next run's clean-worktree check to trip on.
    assert [child.name for child in spec.parent.iterdir()] == ["spec.yaml"]


# --- guard bands, ratchets, and a deterministic objective -------------------


COUNTER = """
from pathlib import Path

print(len([x for x in Path('checks.txt').read_text().splitlines() if x]))
"""

REWRITE_CHECKS = "\nfrom pathlib import Path\nPath('checks.txt').write_text({body!r})\n"


def _with_checks(repo: Path, lines: str) -> None:
    (repo / "checks.txt").write_text(lines, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add checks")


def _checks_agent(tmp_path: Path, body: str, name: str = "agent.py") -> Path:
    return _agent(tmp_path, IMPROVING_AGENT + REWRITE_CHECKS.format(body=body), name=name)


def test_non_increasing_number_guard_blocks_a_rise(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """The mirror of non_decreasing: some metrics must not grow (debt, latency, size)."""
    _with_checks(repo, "a\nb\n")
    counter = _agent(tmp_path, COUNTER, name="count.py")
    spec = _write_spec(
        tmp_path,
        objective,
        _checks_agent(tmp_path, "a\nb\nc\n"),
        guards=[
            {
                "id": "debt",
                "command": [sys.executable, str(counter)],
                "kind": "non_increasing_number",
            }
        ],
    )

    _, payload = _run(repo, spec)

    record = _ledger(payload)[0]
    assert record["decision"] == "rejected"
    assert record["reason"] == "guard debt rose from 2 to 3"
    assert (repo / "checks.txt").read_text() == "a\nb\n"


def test_non_increasing_number_guard_allows_a_drop(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    _with_checks(repo, "a\nb\n")
    counter = _agent(tmp_path, COUNTER, name="count.py")
    spec = _write_spec(
        tmp_path,
        objective,
        _checks_agent(tmp_path, "a\n"),
        guards=[
            {
                "id": "debt",
                "command": [sys.executable, str(counter)],
                "kind": "non_increasing_number",
            }
        ],
    )

    _, payload = _run(repo, spec)

    assert _ledger(payload)[0]["decision"] == "accepted"


def test_tolerance_admits_noise_but_not_a_real_regression(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """A 25% band lets 4 -> 5 through and still stops 4 -> 6."""
    _with_checks(repo, "a\nb\nc\nd\n")
    counter = _agent(tmp_path, COUNTER, name="count.py")
    guards = [
        {
            "id": "cost",
            "command": [sys.executable, str(counter)],
            "kind": "non_increasing_number",
            "tolerance": 0.25,
        }
    ]

    within = _checks_agent(tmp_path, "a\nb\nc\nd\ne\n", name="within.py")
    _, payload = _run(repo, _write_spec(tmp_path, objective, within, guards=guards))
    assert _ledger(payload)[0]["decision"] == "accepted"

    _git(repo, "reset", "-q", "--hard", "HEAD~1")
    beyond = _checks_agent(tmp_path, "a\nb\nc\nd\ne\nf\n", name="beyond.py")
    _, payload = _run(
        repo, _write_spec(tmp_path, objective, beyond, guards=guards, dest=tmp_path / "b.yaml")
    )
    record = _ledger(payload)[-1]
    assert record["decision"] == "rejected"
    assert record["reason"] == "guard cost rose from 4 to 6 (tolerance 0.25)"


def test_ratchet_keeps_what_an_accepted_iteration_won(
    repo: Path, objective: Path, tmp_path: Path
) -> None:
    """Without ratchet the floor is the stage-entry value, so a gain can be handed back.

    Iteration 1 adds a check and is accepted; iteration 2 deletes it again.  A plain
    non_decreasing guard compares 2 against the entry reading of 2 and lets that through.
    """
    _with_checks(repo, "a\nb\n")
    counter = _agent(tmp_path, COUNTER, name="count.py")
    agent = _agent(
        tmp_path,
        IMPROVING_AGENT + "\nimport os\n"
        "from pathlib import Path\n"
        "first = os.environ['EXPERIMENT_LOOP_ITERATION'] == '1'\n"
        "Path('checks.txt').write_text('a\\nb\\nc\\n' if first else 'a\\nb\\n')\n",
    )

    def run(ratchet: bool, dest: Path) -> list[dict]:
        guard: dict = {
            "id": "checks",
            "command": [sys.executable, str(counter)],
            "kind": "non_decreasing_number",
        }
        if ratchet:
            guard["ratchet"] = True
        _, payload = _run(
            repo,
            _write_spec(tmp_path, objective, agent, iterations=2, guards=[guard], dest=dest),
        )
        return _ledger(payload)

    plain = run(False, tmp_path / "plain.yaml")[-2:]
    assert [record["decision"] for record in plain] == ["accepted", "accepted"]
    assert (repo / "checks.txt").read_text() == "a\nb\n"

    _git(repo, "reset", "-q", "--hard", "HEAD~2")
    ratcheted = run(True, tmp_path / "ratchet.yaml")[-2:]
    assert [record["decision"] for record in ratcheted] == ["accepted", "rejected"]
    assert ratcheted[1]["reason"] == "guard checks dropped from 3 to 2"
    assert (repo / "checks.txt").read_text() == "a\nb\nc\n"


@pytest.mark.parametrize("extra", [{"tolerance": 0.1}, {"ratchet": True}])
def test_band_and_ratchet_are_rejected_on_kinds_that_record_no_number(
    tmp_path: Path, extra: dict
) -> None:
    path = tmp_path / "spec.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "loop_id": "ok",
                "objective": {"command": ["true"], "direction": "minimize"},
                "agent": {"command": ["true"]},
                "guards": [{"id": "g", "command": ["true"], "kind": "exit_zero", **extra}],
                "budget": {"iterations": 1},
                "prompt": "go",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(experiment_loop.SpecError, match="only applies to"):
        experiment_loop.load_spec(path)


def test_a_nondeterministic_objective_is_refused_before_the_agent_runs(
    repo: Path, tmp_path: Path
) -> None:
    """Every accept compares two readings of this command, so it must agree with itself."""
    drifting = tmp_path / "drifting.py"
    drifting.write_text(
        "from pathlib import Path\n"
        "state = Path(__file__).with_suffix('.state')\n"
        "n = int(state.read_text()) if state.exists() else 0\n"
        "state.write_text(str(n + 1))\n"
        "print(n)\n",
        encoding="utf-8",
    )
    spec = _write_spec(tmp_path, drifting, _agent(tmp_path, IMPROVING_AGENT))

    result, payload = _run(repo, spec)

    assert result.returncode == 3
    assert "objective is not deterministic" in payload["error"]
    assert "two runs on the same tree disagree (0 then 1)" in payload["error"]
