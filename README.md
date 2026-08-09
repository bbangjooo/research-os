# Research OS

Research OS is a local-first control plane for bounded, reproducible, and
auditable autonomous research.

You talk to Codex or Claude Code. The coding agent proposes hypotheses and
interprets evidence, while Research OS isolates experiments, enforces budgets
and integrity checks, and records every attempt in an append-only experiment
graph.

```text
user <-> Codex / Claude Code -> Research OS -> project adapter + evaluator
```

Project-specific science stays in each project. The same kernel can govern
model architecture search, learning-framework research, quantitative strategy
research, or another domain without importing an existing domain framework.

## Requirements

- Python 3.11+
- POSIX operating system (macOS or Linux)
- `uv` is recommended for installation

Research OS supports POSIX operating systems only; Windows is not supported in
this release. It has no third-party runtime dependencies.

## Install

```bash
git clone https://github.com/bbangjooo/research-os.git ~/research-os
cd ~/research-os
uv venv --python 3.12
uv pip install --python .venv/bin/python -e .

# Install the shared agent skill for both clients.
.venv/bin/research-os install-agent-skill --target all
```

To replace an exact, unmodified Research OS 0.1.0 skill installation, use the
explicit safe-upgrade path:

```bash
.venv/bin/research-os install-agent-skill --target all --upgrade
```

Unknown or locally modified skill trees are never overwritten.

This installs the skill at:

- `~/.agents/skills/research-os` for Codex
- `~/.claude/skills/research-os` for Claude Code

## Use through an agent

Open Codex or Claude Code in the project you want to research and speak
naturally:

```text
Improve this project with bounded autoresearch. Use at most six experiments.
```

That short request is enough. The agent performs scientific setup gates,
evaluator certification, graph bookkeeping, and CLI calls behind the
conversation; it asks only about material scientific choices, cost, or authority.

```text
Set up this project for bounded model architecture research with Research OS.
Use out-of-sample performance as the primary metric and run at most 8 experiments.
```

```text
Review the current experiment graph, explain what has been established, and
run at most 3 additional experiments. Do not deploy anything.
```

Explicit invocation is also available:

- Codex: `$research-os`
- Claude Code: `/research-os`

The agent handles the Research OS CLI and translates structured results into a
human-readable answer. The user does not need to edit candidate JSON or inspect
raw event records.

## What it enforces

- isolated, disposable experiment workspaces;
- immutable evaluator, evidence, and protected paths during a run;
- finite experiment, time, output, input, and artifact budgets;
- compatible repeated baselines verified through the same digest-bound adapter
  boundary as candidates;
- constitution-owned typed `gte`/`lte` hard and support gates with numeric
  signed/normalized slack in every promotion decision;
- pre-registered universes, selection/split policy, and holdout boundaries;
- hand-derived golden cases and independent evaluator certification;
- explicit graph actions, scientific changes, ancestry, ablations, replications,
  and retries;
- explore -> no-experiment diagnosis -> ablate/exploit -> replicate discipline;
- one conceptual intervention per node and repeated-class failure closure;
- hash-chained canonical events and content-addressed artifacts;
- stale-context rejection before an agent's proposal is registered;
- durable recording of invalid, failed, timed-out, and untrusted attempts.

Research OS itself proves protocol, isolation, provenance, compatibility, and
replay integrity; it cannot infer whether project-owned domain equations are
scientifically correct. The shared skill therefore blocks research until golden
cases pass and a separate read-only critic certifies the exact evaluator and
evidence boundary. A semantic change triggers change-control, re-certification,
and a new compatible baseline.

A validated result is research evidence only. It never authorizes a merge,
deployment, model release, capital allocation, or live trade.

## Add a new project

Ask Codex or Claude Code to set it up, or initialize the fail-closed scaffold
directly:

```bash
.venv/bin/research-os init /path/to/project \
  --id my-project \
  --name "My research project"
```

Each project owns its research brief, candidate schema, deterministic evaluator,
and eight-operation adapter. See [New project integration](docs/new-project.md)
and the [adapter protocol](docs/adapter-protocol.md).

## CLI

The agent normally calls these commands itself:

```bash
RESEARCH_REVIEW_DIR="$(mktemp -d)"
research-os --project /path/to/project doctor
research-os --project /path/to/project evaluator-review-subject \
  > "$RESEARCH_REVIEW_DIR/review-subject.json"
# The critic writes "$RESEARCH_REVIEW_DIR/review.json".
research-os --project /path/to/project certify-evaluator \
  "$RESEARCH_REVIEW_DIR/review.json"
research-os --project /path/to/project baseline
research-os --project /path/to/project agent-context
research-os --project /path/to/project run-once candidate.json \
  --graph-action explore --scientific-change "CLASS: ...; CHANGE: ..." \
  --context-token TOKEN
research-os --project /path/to/project conclude-branch conclusion.json \
  --context-token TOKEN
research-os --project /path/to/project status
research-os --project /path/to/project lineage
research-os --project /path/to/project findings
research-os --project /path/to/project replay
```

Codex and Claude Code use `agent-context` plus `--context-token`; that guarded
path requires a current independent evaluator certificate and an already sealed
baseline. Tokenless `run-once` remains only as a legacy/manual compatibility path
and does not enforce the agent-readiness gate. Replacing a certificate after
approved change-control requires `certify-evaluator /ABS/OUTSIDE/review.json --replace`.
The independent reviewer must copy the exact `digest` emitted by
`evaluator-review-subject` into the review's required `subject_digest` field;
an old review cannot certify changed inputs.
Both subject and review JSON belong in a private temporary directory outside
the project root; certification rejects an in-project review path.

See [agent usage](docs/agent-usage.md) and
[architecture](docs/architecture.md) for the complete contract.

## Development

```bash
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
uvx ruff check .
uvx ty check src
```

Licensed under the [MIT License](LICENSE).
