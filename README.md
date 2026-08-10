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

To replace an exact, unmodified Research OS 0.1.0 installation or a byte-exact
managed Research OS 0.2.0 skill, use the explicit safe-upgrade path:

```bash
.venv/bin/research-os install-agent-skill --target all --upgrade
```

Unknown or locally modified skill trees are never overwritten. A successful
upgrade retains the prior inode tree in the reported `recovery_backup`; inspect
that recovery before deleting it manually.

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
- strict, versioned study contracts whose generation-wide attempt, retry,
  elapsed-allocation, and optional cost-allocation budgets are reserved atomically;
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
research-os --project /path/to/project open-generation study-contract.json
research-os --project /path/to/project study-status
research-os --project /path/to/project baseline
research-os --project /path/to/project agent-context
research-os --project /path/to/project agent-context --schema-version 3
research-os --project /path/to/project run-once candidate.json \
  --graph-action explore --scientific-change "CLASS: ...; CHANGE: ..." \
  --context-token TOKEN
research-os --project /path/to/project diagnose diagnosis.json
research-os --project /path/to/project diagnosis-template \
  > diagnosis.json
research-os --project /path/to/project conclude-branch conclusion.json \
  --context-token TOKEN
research-os --project /path/to/project status
research-os --project /path/to/project lineage
research-os --project /path/to/project findings
research-os --project /path/to/project replay
```

StudyContract v2 uses a typed Proposal and a preregistered evaluation scope
instead of the legacy graph flags:

```bash
research-os --project /path/to/project baseline \
  --evaluation-scope-id development
research-os --project /path/to/project run-once candidate.json \
  --proposal proposal.json
# A retry inherits the persisted candidate, Proposal, parent, and scope.
research-os --project /path/to/project run-once candidate.json \
  --retry-of exp_PRIOR
```

The adapter must advertise `evaluation_scope_v1` before a v2 generation can
open. Research OS binds the full declared scope to the baseline, all four
candidate operations, experiment identity, and replay; it does not infer that
two datasets are scientifically independent merely because their scope IDs
differ.

Every terminal experiment in a version-two generation leaves one pending
Diagnosis. Before another registration, retry, or successor generation can be
accepted, the agent must submit a strict `Diagnosis` JSON with `diagnose`. The
object binds the exact terminal event and hash, Proposal, evaluation scope,
Decision observation, and artifact evidence. The kernel—not the agent's
narrative—derives class status, immutable closure, and the semantic/retry
frontier. Context v3 and the Diagnosis template expose that state without
changing the canonical event contract.

Research OS 0.3 emits Context v3 by default. After a typed terminal result, run
`agent-context`, then `diagnosis-template`
(add `--experiment ID` if more than one is pending). The generated body is
fail-closed until the agent replaces only `interpretation`, `failure_type`,
`falsifier`, and `recommendation`, after which it can be submitted to
`diagnose`. Use `agent-context --schema-version 2` only for explicit compatibility;
its packet and context-token snapshot schema remain unchanged.

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

`open-generation` requires a current evaluator certificate and records an exact
`StudyContract` plus a separate evaluation seal in the canonical event log.
Every later registration in that generation receives a contract-fixed,
non-refundable budget reservation under the same event-log lock; `study-status`
derives the remaining allocation by replay. Elapsed and cost values are reserved
allocations, not measured usage. The limit is per generation rather than a study
lifetime cap. Replacing the contract or seal therefore requires an explicit
successor with `--predecessor-generation-id` and `--change-reason`; reopening the
same contract cannot reset its budget.

See [agent usage](docs/agent-usage.md) and
[architecture](docs/architecture.md) for the complete contract.

To preview the opt-in Context v3 and Diagnosis authoring path without touching
another project, run the disposable local example:

```bash
.venv/bin/python examples/m1e_context_v3_demo.py
```

## Development

```bash
.venv/bin/python -W error::ResourceWarning -m unittest discover -s tests -v
uvx ruff check .
uvx ty check src
```

Licensed under the [MIT License](LICENSE).
