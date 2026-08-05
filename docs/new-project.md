# Integrating a new research domain

Research OS separates a reusable experimental control plane from project-owned scientific meaning. A new domain does not require a new kernel module or a copied framework. It requires a constitution, a bounded filesystem surface, and a deterministic adapter.

## Project boundary

The project owns:

- the candidate JSON schema;
- materialization into project configuration or code;
- the evaluator, dataset splits, costs, and hard constraints;
- artifact declarations;
- the agent or human process that proposes the next candidate.

Research OS owns:

- process protocol validation and budgets;
- disposable workspace construction and mutation-boundary checks;
- immutable-input and source-checkout verification;
- baseline compatibility and promotion policy;
- canonical events, experiment DAG, artifacts, and findings;
- replayable query state.

Codex or Claude Code owns the conversational loop: eliciting the project brief,
choosing hypotheses and graph parents, producing schema-valid candidates,
calling the OS, and explaining evidence. The user does not operate Research OS
directly during normal research.

## Minimal files

```text
your-project/
├── .research-os/
│   ├── project.toml
│   ├── constitution.toml
│   ├── adapter.py          # any language is allowed
│   ├── research-brief.md   # agent-facing goal, budget, and stop conditions
│   ├── candidate.schema.json
│   ├── candidate.inbox.json # ignored transient agent input
│   └── .gitignore          # ignores runtime/
├── evaluator.py            # example only
├── evidence/                # fixed evaluation inputs
├── experiment.json          # one declared mutable surface
└── candidates/
```

The tree above shows the intended integrated project; `evidence/` and
`candidates/` are project-owned examples rather than scaffold output. Start
from an existing, non-symlink project directory:

```bash
mkdir -p /path/to/your-project
research-os init /path/to/your-project \
  --id your-project --name "Your research project"
```

Initialization creates the two TOML contracts, a fail-closed Python adapter,
an unconfigured research brief and candidate schema, an ignored candidate
inbox, `.research-os/.gitignore`, `experiment.json`, and a fail-closed
`evaluator.py`.
It refuses to overwrite a colliding path and rolls back files created by a
failed initialization attempt. Replace or edit the scaffold; do not copy the OS
source tree into the project.

## Clean-room domain workflow

Integrate a brand-new domain from its own semantics, not by cloning an existing
quantitative, ML, or example project:

1. Write the domain's candidate JSON schema in plain terms: one candidate must
   represent one bounded, falsifiable change.
2. Build a deterministic evaluator and a fixed evidence set for that domain.
   Decide which scalar metric drives comparison and which constraints can veto
   it.
3. Run `research-os init` in the domain's own repository. Classify its paths as
   mutable candidate inputs, protected implementation/policy, or fixed evidence.
4. Set the constitution's metric direction, baseline repetitions and tolerance,
   and minimum improvement. These values are research policy, not adapter
   defaults or CLI tuning knobs.
5. Implement the eight protocol operations as a thin translation layer around
   that evaluator. Reuse the versioned wire contract, but do not reuse another
   project's candidate schema, evaluator, dataset assumptions, or domain codes.
6. Exercise each operation against a disposable copy, then run `inspect`,
   `doctor`, an explicit `baseline`, one deliberately invalid candidate, and one
   valid candidate before attaching an autonomous proposer.

This keeps the OS domain-neutral: adding a domain changes only the project
contract, adapter, evaluator, evidence, and candidate schema—not the Research OS
kernel.

## The eight operations

Every adapter implements protocol version 1 operations:

1. `describe`: declare all capabilities and an empty external side-effect list.
2. `fingerprint`: identify project-specific evaluator/data semantics.
3. `baseline`: evaluate the unchanged snapshot.
4. `materialize`: translate candidate JSON into declared mutable surfaces.
5. `run`: execute the bounded experiment.
6. `evaluate`: return finite metrics, constraints, provenance, resource usage, and artifact refs.
7. `verify`: perform domain-specific result validity checks.
8. `cleanup`: remove adapter-owned transient state inside the disposable workspace.

Each process receives one JSON request on stdin and must emit one JSON response
on stdout. Diagnostics belong in the response; stdout cannot contain logs. See
[adapter-protocol.md](adapter-protocol.md) for exact envelopes.

## Configure the bounded surface

In `.research-os/project.toml`, keep only candidate-controlled inputs in
`paths.mutable`. Put the adapter, evaluator, fixed data/splits, policies, and
other semantic inputs in `paths.protected`; list evaluation evidence identities
in `paths.evidence`. All paths are project-relative, and protocol v1 fixes the
runtime path at `.research-os/runtime`. Configure the adapter as an argument
array, not a shell command, and set explicit wall-clock, stdout/stderr, and
artifact-byte limits.

Mutable does not mean “excluded from provenance.” The source-project content of
each mutable path is the baseline seed and participates in the compatibility
digest. A missing mutable path is represented by a stable absence marker.
Editing, creating, deleting, or moving that source content rotates
compatibility, so an older baseline cannot authorize comparisons. Candidate
materialization changes only the disposable copy and does not rewrite this
source seed.

Research OS snapshots the project for each operation, accepts and captures new
output files only when `evaluate` or `baseline` declares them as artifacts, and
checks the source checkout plus protected inputs around adapter calls. `doctor`
fingerprints the static project, adapter execution environment, and
adapter-provided semantics; any compatibility change requires a new baseline.

## Designing a constitution

Choose one scalar primary metric. It should answer whether a candidate is better than a compatible baseline; secondary metrics and hard constraints can remain multidimensional.

`[baseline].repeats` is the single authoritative repetition count. Research OS
uses exactly that value both when sealing and when revalidating a baseline. The
optional `baseline --repeats N` argument is only an equality assertion for
automation; a different `N` is rejected and cannot override the constitution.
Changing the count, tolerance, objective, or promotion rule changes semantic
configuration and therefore baseline compatibility.

For ML architecture or learning-framework research, a project might use held-out loss, accuracy, calibration, latency, or memory as the primary metric/constraints. The evidence set, evaluator, split logic, and training budget belong in protected paths. A candidate can describe architecture components, optimizer behavior, objectives, or training schedules without teaching the OS what those fields mean.

For quantitative research, a project might use conservative out-of-sample risk-adjusted return as the primary metric and turnover, drawdown, capacity, leakage tests, and costs as hard constraints. Data snapshots, temporal split rules, fee/slippage models, and backtester code must be protected. A candidate describes a signal/portfolio/risk hypothesis. Live orders remain outside Research OS.

Keep `[authority].authorized_action = ""` unchanged. The loader rejects any
non-empty value, and resolved authority and research-outcome payloads represent
it as `authorized_action: null`.

The generic finding key `experiment_outcome` is reserved for Research OS. The
kernel derives exactly one such finding from each terminal attempt, binds it to
that terminal event's ID and hash, and repairs a missing append during recovery.
Project code and agents must use a different key for their own findings.

## First integration run

Create at least one candidate JSON object according to the project-owned schema,
then run the gates explicitly:

```bash
research-os --project /path/to/your-project inspect
research-os --project /path/to/your-project doctor
research-os --project /path/to/your-project baseline
research-os --project /path/to/your-project run-once \
  /path/to/your-project/candidates/first.json
research-os --project /path/to/your-project status
research-os --project /path/to/your-project lineage
research-os --project /path/to/your-project artifacts
research-os --project /path/to/your-project findings
research-os --project /path/to/your-project replay
```

`run-once` establishes a compatible repeated baseline when none exists, but
running `baseline` explicitly is preferable during integration because it
isolates baseline reproducibility and cleanup failures before candidate work.
Baseline artifacts are captured into the same content-addressed catalog as
candidate artifacts and embedded in `BASELINE_RECORDED`. The `artifacts`
command lists and verifies projected candidate artifact records; `replay`
verifies both candidate and baseline records and their blobs.

Each CLI invocation loads a fresh contract. Embedded callers that retain a
`ResearchService` must discard it and construct a new instance after editing
`.research-os/project.toml` or `.research-os/constitution.toml`; the cached
instance intentionally fails closed on configuration drift.

## Agent loop

The installed Research OS skill makes Codex or Claude Code the sole user-facing
researcher. It runs the following loop:

1. Run `doctor`, `replay`, and `agent-context`; read the bounded graph, brief,
   schema, findings, artifacts, and snapshot token.
2. Select a parent experiment and one falsifiable change.
3. Write one bounded candidate to `.research-os/candidate.inbox.json`.
4. Call `research-os --project PATH run-once PATH/.research-os/candidate.inbox.json --parent exp_<parent-id> --context-token <token>` (omit `--parent` for a root hypothesis).
5. Use the terminal status and diagnostics to update its hypothesis.
6. Continue until its explicit experiment/time/cost budget is exhausted.

If no finite budget was supplied, the shared skill permits one experiment and
zero retries. A status-only request starts no experiment. Changes to the
metric, evaluator, evidence, constitution, protected paths, or candidate schema
switch the agent out of research mode into explicit change-control and require
the appropriate compatible baseline before research resumes.

The OS rejects an identical candidate under the same parent and immutable compatibility fingerprint. Changed evaluator/data/config fingerprints force a new baseline, preventing incomparable evidence from sharing a promotion decision.

Do not resubmit a failed candidate as an ordinary `run-once`; duplicate evidence remains refused. If the most recent attempt timed out, was cancelled, was recovered after interruption, or ended with an adapter error that explicitly set `retryable: true`, request one new attempt with:

```text
research-os --project PATH run-once candidate.json --retry-of exp_<prior-id>
```

The requested retry preserves the prior attempt's DAG parent. If `--parent` is also supplied, it must match. The candidate JSON and immutable compatibility fingerprint must also match the referenced attempt. Each retry is a distinct durable node with `attempt` incremented and `retry_of` pointing to the immediately prior attempt. A stale attempt ID cannot be retried after a newer attempt exists, and invalid, rejected, validated, untrusted, or non-retryable infrastructure outcomes are never retryable. Research OS never starts a retry automatically.

## Cleanup and replay

For candidate attempts, adapter cleanup and local workspace-removal failures are
durable `secondary_errors`; they do not replace an already determined
scientific status. Integrity drift detected around cleanup still dominates as
`UNTRUSTED`. A baseline is stricter: every repetition's cleanup must succeed
before the baseline event is sealed.

`.research-os/runtime/events.jsonl` is canonical and `state.db` is rebuildable.
`replay` verifies the complete event chain and graph invariants before using
rebuildable state. For an abandoned registered/queued/running attempt, a durable
successful `evaluate` response triggers evidence recovery: existing manifests
must match its artifact declarations, or one safe orphan workspace must match
the registration-time source seal and pass reconstructed clean-snapshot and
mutation-boundary checks before its declared artifacts are captured and
published. The attempt then closes as retryable
`INFRA_FAILED/RECOVERED_INTERRUPTED_RUN`; recovered evidence is not promoted.

The same ordering applies to a caught interruption during a live attempt. Once
the successful `evaluate` stage is durable, Research OS captures and canonically
publishes all declared artifacts before it may append `CANCELLED` or clean the
workspace. If artifact capture or publication cannot be proven complete, the
attempt intentionally remains nonterminal and its workspace remains preserved;
the next service command resumes through the recovery path above.

If no successful evaluation was recorded, recovery infers no artifacts and may
clean the orphan before closing the attempt. If evaluated evidence cannot be
proven, recovery closes the attempt as
`UNTRUSTED/INTERRUPTED_EVIDENCE_UNTRUSTED` with
`preserve_workspace=true`; unresolved entries remain untouched and are excluded
from later generic orphan cleanup for compatible recovery or inspection. This
durable untrusted outcome is not the temporary pending-publication state above.
After recovery, `replay` rebuilds SQLite again and verifies every canonical
baseline and candidate artifact record, manifest, and blob. A successful replay
returns `events_replayed`, `artifacts_verified`, and current projected `status`.

## Production separation

`VALIDATED` means only that the sealed experiment passed its configured comparison and constraints. Every result has `authorized_action: null`. A separate reviewed system must decide whether to merge code, train a production model, allocate capital, or send an order.

Research OS is a trusted local-process control plane, not a sandbox for hostile
adapter code. Protocol v1 requires `side_effects: []`; adapters may write only
inside disposable workspaces and must not deploy, publish, allocate capital,
contact live execution systems, or perform any other external action.
