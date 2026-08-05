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

This installs the skill at:

- `~/.agents/skills/research-os` for Codex
- `~/.claude/skills/research-os` for Claude Code

## Use through an agent

Open Codex or Claude Code in the project you want to research and speak
naturally:

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
- compatible repeated baselines and deterministic promotion thresholds;
- explicit experiment ancestry, ablations, replications, and retries;
- hash-chained canonical events and content-addressed artifacts;
- stale-context rejection before an agent's proposal is registered;
- durable recording of invalid, failed, timed-out, and untrusted attempts.

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
research-os --project /path/to/project doctor
research-os --project /path/to/project baseline
research-os --project /path/to/project agent-context
research-os --project /path/to/project run-once candidate.json
research-os --project /path/to/project status
research-os --project /path/to/project lineage
research-os --project /path/to/project findings
research-os --project /path/to/project replay
```

See [agent usage](docs/agent-usage.md) and
[architecture](docs/architecture.md) for the complete contract.

## Development

```bash
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
uvx ruff check .
uvx ty check src
```

Licensed under the [MIT License](LICENSE).
