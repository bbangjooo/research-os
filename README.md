# Research OS

A local-first control plane for bounded, reproducible, and auditable autonomous
research.

You talk to Codex or Claude Code. The agent proposes hypotheses and interprets
evidence. Research OS isolates each experiment, enforces budgets and integrity
checks, and records every attempt — including the failures — in an append-only
event log.

```text
user <-> Codex / Claude Code -> Research OS -> project adapter + evaluator
```

Domain science stays in each project. The same kernel can govern model
architecture search, learning-framework research, quantitative strategy
research, or another field without importing a domain framework.

## What it proves, and what it does not

Research OS proves **protocol, isolation, provenance, compatibility, and replay
integrity**. It cannot tell you whether your project's equations, labels, splits,
or evaluator are scientifically correct.

That boundary is enforced rather than assumed: research is blocked until
hand-derived golden cases pass and a separate read-only critic certifies the
exact evaluator and evidence boundary. A semantic change triggers
change-control, re-certification, and a new compatible baseline.

**A validated result is research evidence only.** It never authorizes a merge,
deployment, model release, capital allocation, or live trade. Every command and
response keeps `authorized_action` literal `null`.

## Three lanes

| Lane | Purpose | Authority |
| --- | --- | --- |
| **Confirmatory loop** | Run pre-registered experiments inside a fixed contract | Opens experiments and generations |
| **Discovery** (opt-in) | Record anomalies, assumption conflicts, sealed external evidence, and rival frame drafts; read cross-frame material | None — advisory only |
| **Frame transition** (opt-in) | Compare rival frames and adopt a successor after isolated piloting and independent review | Opens exactly one successor generation |

The cost is deliberately asymmetric. Discovery is nearly frictionless because it
grants nothing. Adoption keeps the full ritual because it opens a successor.

## Requirements

- Python 3.11+
- POSIX (macOS or Linux) — Windows is not supported
- `uv` recommended

No third-party runtime dependencies.

## Install

```bash
git clone https://github.com/bbangjooo/research-os.git ~/research-os
cd ~/research-os
uv venv --python 3.12
uv pip install --python .venv/bin/python -e .
.venv/bin/research-os install-agent-skill --target all
```

This installs the shared agent skill at `~/.agents/skills/research-os` (Codex)
and `~/.claude/skills/research-os` (Claude Code).

To replace an existing installation:

```bash
.venv/bin/research-os install-agent-skill --target all --upgrade
```

`--upgrade` replaces only a tree that is byte-identical to a published
checkpoint, and retains the prior tree in the reported `recovery_backup`.
Unknown or locally modified trees are never overwritten — if you see
`refusing to overwrite a different Research OS agent skill`, the installed tree
is not a published release, and you must inspect and remove it yourself.

## Use through an agent

Open Codex or Claude Code in the project you want to research and speak
naturally:

```text
Improve this project with bounded autoresearch. Use at most six experiments.
```

```text
Set up this project for bounded model architecture research with Research OS.
Use out-of-sample performance as the primary metric and run at most 8 experiments.
```

```text
Review the current experiment graph, explain what has been established, and
run at most 3 additional experiments. Do not deploy anything.
```

The agent performs setup gates, evaluator certification, graph bookkeeping, and
CLI calls behind the conversation, and asks only about material scientific
choices, cost, or authority. You never need to edit candidate JSON or read raw
event records.

Explicit invocation: `$research-os` (Codex), `/research-os` (Claude Code).

Scientific sessions default to a high-reasoning frontier model, with explicit
lower-cost control and independent-audit routes. See
[model routing](docs/model-routing.md).

## Add a project

Ask the agent to set it up, or scaffold it directly:

```bash
.venv/bin/research-os init /path/to/project \
  --id my-project \
  --name "My research project"
```

Each project owns its research brief, candidate schema, deterministic evaluator,
and eight-operation adapter. See [new project integration](docs/new-project.md)
and the [adapter protocol](docs/adapter-protocol.md).

## What the confirmatory loop enforces

- isolated, disposable experiment workspaces;
- immutable evaluator, evidence, and protected paths during a run;
- finite experiment, time, output, input, and artifact budgets;
- strict versioned study contracts whose per-generation attempt, retry, elapsed,
  and optional cost allocations are reserved atomically and are
  **non-refundable** — reopening a contract cannot reset its budget;
- compatible repeated baselines verified through the same digest-bound adapter
  boundary as candidates;
- constitution-owned typed `gte`/`lte` hard and support gates, with numeric
  signed slack recorded in every promotion decision;
- pre-registered universes, selection/split policy, and holdout boundaries;
- explicit graph actions, ancestry, ablations, replications, and retries;
- one conceptual intervention per node, and class closure after repeated
  conclusive rejection;
- hash-chained canonical events and content-addressed artifacts;
- stale-context rejection before a proposal is registered;
- durable recording of invalid, failed, timed-out, and untrusted attempts.

Elapsed and cost values are **reserved allocations, not measured usage**, and the
limit is per generation rather than a study lifetime cap.

### Contracts the loop is built on

- **StudyContract v2** replaces legacy graph flags with a typed `Proposal` and a
  pre-registered evaluation scope. The adapter must advertise
  `evaluation_scope_v1` first. Research OS binds the declared scope to the
  baseline, every candidate operation, experiment identity, and replay; it does
  **not** infer that two datasets are independent because their scope IDs differ.
- **Diagnosis** — every terminal experiment leaves one pending Diagnosis, and no
  further registration, retry, or successor is accepted until it is submitted.
  The kernel, not the agent's narrative, derives class status, closure, and the
  semantic/retry frontier.
- **Context v3** is the default agent packet. `diagnosis-template` emits a
  fail-closed body; the agent replaces only `interpretation`, `failure_type`,
  `falsifier`, and `recommendation`.
- **ProgramLog** is a separate append-only log for conditional Claims. A
  registered Proposal may record one immutable disposition covering every
  retrieved Claim exactly once as `used`, `rejected`, or `not_applicable`.
  Canonical digests and relation IDs are the auditable authority, not prose.
- **Finite autonomy loop** — each provider decision is a strict DecisionPacket
  bound to the current Context, retrieval result, Program head, candidate
  budget, and literal-null authority. Invalid output has a bounded retry path;
  closed classes, stale heads, exhausted budgets, and post-terminal calls fail
  closed. Interrupted runs resume the recorded pending seam.

## CLI

The agent normally calls these itself.

### Setup and the research loop

```bash
RESEARCH_REVIEW_DIR="$(mktemp -d)"
research-os --project PROJECT doctor
research-os --project PROJECT evaluator-review-subject > "$RESEARCH_REVIEW_DIR/review-subject.json"
# an independent critic writes "$RESEARCH_REVIEW_DIR/review.json"
research-os --project PROJECT certify-evaluator "$RESEARCH_REVIEW_DIR/review.json"
research-os --project PROJECT open-generation study-contract.json
research-os --project PROJECT baseline --evaluation-scope-id development
research-os --project PROJECT agent-context
research-os --project PROJECT run-once candidate.json --proposal proposal.json
research-os --project PROJECT diagnosis-template > diagnosis.json
research-os --project PROJECT diagnose diagnosis.json
research-os --project PROJECT study-status
research-os --project PROJECT status
research-os --project PROJECT lineage
research-os --project PROJECT findings
research-os --project PROJECT replay
```

Both the review subject and the review belong in a private temporary directory
**outside** the project root; certification rejects an in-project review path.
The reviewer must copy the exact `digest` from `evaluator-review-subject` into
the review's `subject_digest`, so an old review cannot certify changed inputs.
Replacing a certificate after approved change-control requires
`certify-evaluator /ABS/OUTSIDE/review.json --replace`.

`agent-context` plus `--context-token` is the guarded path and requires a current
independent certificate and a sealed baseline. Tokenless `run-once` remains only
as a legacy compatibility path and does not enforce the agent-readiness gate.

A retry inherits the persisted candidate, Proposal, parent, and scope:

```bash
research-os --project PROJECT run-once candidate.json --retry-of exp_PRIOR
```

### Discovery lane (advisory)

Two of the four exhaustion signal kinds a frame inquiry can cite —
`unresolved_anomaly` and `assumption_conflict` — exist only in diagnosis
interpretation, which is discarded at session end. The journal makes them
citable, and opens a read path to cross-frame material that exact-class
retrieval structurally excludes.

```bash
research-os --project PROJECT discovery-note note.json
research-os --project PROJECT discovery-status [--kind KIND] [--limit N]
research-os --project PROJECT discovery-status --exhaustion
research-os --project PROJECT discovery-status --residual
research-os --project PROJECT discovery-status --yield
research-os --project PROJECT discovery-analogies query.json \
  --program-root PROGRAM_ROOT --program-id PROGRAM_ID
```

- Notes are append-only: there is no edit or delete command. Correct a note by
  recording a new one.
- A `rival_draft` is field-identical to a frame-transition rival, so a draft is
  quotable as an inquiry input without conversion. It needs a firing falsifier,
  a canonical reference, and assumptions plus a mechanism no recorded draft
  already states.
- `--exhaustion` reports canonical and advisory signal counts separately.
  Advisory notes may corroborate exhaustion; they never establish it alone.
- `--residual` computes, for each closed hypothesis class, the mechanisms that
  failed and asks for the commitment they share to be negated.
- `--yield` is the measurement that decides whether the lane earns its keep.
- `discovery-analogies` returns cross-class or cross-generation Claims, all
  marked advisory. Canonical retrieval is unchanged and remains exact-class.

Nothing in this lane can be an input to registration, validation, promotion,
sealing, or a successor generation. See the
[discovery lane specification](docs/discovery-lane-improvement.md).

### Frame transition (governed, opt-in)

An outer control plane for material J2/J3 or ambiguous-material changes. The
inner loop is unchanged; receipts go in the same canonical EventLog.

```bash
research-os --project PROJECT frame-transition-gate-a gate-a.json
research-os --project PROJECT frame-transition-open inquiry.json
research-os --project PROJECT frame-transition-decide decision.json
research-os --project PROJECT frame-transition-authorize-pilot authorization.json
research-os --project PROJECT frame-transition-record-pilot pilot-result.json
research-os --project PROJECT frame-transition-review review.json
research-os --project PROJECT frame-transition-adopt-policy frameinquiry_ID
research-os --project PROJECT frame-transition-activate frameinquiry_ID successor-contract.json
research-os --project PROJECT frame-transition-revoke revocation.json
research-os --project PROJECT frame-transition-status --inquiry frameinquiry_ID
```

Every stage is a distinct, non-reusable receipt. The literal final flow is
`PASS_FOR_ADOPTION` → independent `APPROVE` → deterministic `POLICY_ADOPTION` →
separate `frame-transition-activate`.

- **Gate A** ends as `GO`, `NO_BUILD`, or `UNSTABLE_RUBRIC`. The latter two are
  normal successful endings with zero product change.
- **Opening an inquiry** requires at least two exhaustion signals of two
  distinct kinds, including at least one canonical-lane signal, plus at least
  two rivals that differ substantively in assumptions or mechanism, and a
  discriminator fixed before results.
- **A decision** is exactly `ABSTAIN`, `REJECT`, or `RECOMMEND_FOR_PILOT`. The
  first two close with zero durable successor writes.
- **Pilot authorization is not adoption.** It grants `PILOT_ONLY` authority over
  isolated non-canonical state and expires.
- **`adopt-policy` takes only an inquiry ID** — no ratifier identity, no
  caller-authored file. The reducer derives every field from canonical state
  against a built-in policy that requires `PASS_FOR_ADOPTION`, a fresh
  independent `APPROVE`, and exact activation bindings, with external authority
  false. The reviewer may revoke until the successor opens, which invalidates
  the derived adoption.
- **Only `frame-transition-activate`** delegates to the generation writer, which
  revalidates the unexpired, unrevoked chain under the append lock.

The extension validates supplied evidence. It does not collect provider outputs,
synthesize the independent review, or fabricate Gate A evidence. Keep the review
JSON outside the project tree — the adoption review binds the current full
source-tree digest, so editing files in the tree after review correctly makes
the review stale at activation. See the
[controlled transition specification](docs/controlled-frame-transition-improvement.md).

## Documentation

| Document | Contents |
| --- | --- |
| [architecture.md](docs/architecture.md) | Kernel, logs, authority boundaries |
| [agent-usage.md](docs/agent-usage.md) | How an agent drives the OS |
| [new-project.md](docs/new-project.md) | Project integration walkthrough |
| [adapter-protocol.md](docs/adapter-protocol.md) | The eight adapter operations |
| [research-os-pipeline.md](docs/research-os-pipeline.md) | End-to-end pipeline |
| [research-os-status.md](docs/research-os-status.md) | Current state, gaps, known issues |
| [discovery-lane-improvement.md](docs/discovery-lane-improvement.md) | Discovery and generation lane design |
| [controlled-frame-transition-improvement.md](docs/controlled-frame-transition-improvement.md) | Frame-transition design |
| [model-routing.md](docs/model-routing.md) | Model allocation per session role |
| [canonical-json.md](docs/canonical-json.md) | Canonical serialization rules |

To preview the Context v3 and Diagnosis authoring path without touching another
project:

```bash
.venv/bin/python examples/m1e_context_v3_demo.py
```

## Development

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check src tests
uvx ty check src
```

The full suite runs three nested self-oracle child suites and takes roughly
35 minutes. A small number of failures are expected and tracked: historical
release witnesses and live external-project snapshot monitoring share the default
test graph, so witnesses that pin bytes or versions from a past release stop
reproducing once the repository moves past it. See the known-issues section of
[research-os-status.md](docs/research-os-status.md) before treating a failure as
a regression.

Licensed under the [MIT License](LICENSE).
