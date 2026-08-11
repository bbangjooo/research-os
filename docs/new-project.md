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
│   ├── evaluator-certification.json # OS-managed, gitignored/snapshot-excluded
│   ├── candidate.inbox.json # ignored transient agent input
│   └── .gitignore          # ignores runtime, transient inputs, certification
├── evaluator.py            # example only
├── evidence/                # fixed development/replication inputs and manifests
│   └── universe-manifest.json
├── tests/golden/            # tiny fixtures with independently derived answers
├── experiment.json          # one declared mutable surface
└── candidates/
```

The tree above shows the intended integrated project; `evidence/`,
`tests/golden/`, and `candidates/` are project-owned examples rather than
scaffold output. Research OS creates the managed certification after a review;
do not hand-edit or classify it as mutable/protected/evidence. Locked-holdout
content is deliberately not shown: keep it outside the project and iterative
evaluator environment. Start
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

1. Run `research-os init` in the domain's own repository before creating any of
   the scaffold-owned paths. It refuses to overwrite collisions, so initialize
   first and then replace or edit the generated placeholders. Classify project
   paths as mutable candidate inputs, protected implementation/policy, or fixed
   evidence.
2. Write the domain's candidate JSON schema in plain terms: one candidate must
   represent one bounded, falsifiable change.
3. Pre-register the evaluation universe or task population, selection rule and
   cutoff, development and replication splits, costs, hypothesis classes,
   repeated-class failure threshold, and locked-holdout boundary. Default the
   class-failure threshold to three only when the user did not choose one.
4. Build a deterministic evaluator and a fixed development/replication evidence
   set for that domain. Decide which scalar metric drives comparison and which
   constraints can veto it.
5. Create tiny golden cases with hand-derived or independently computed expected
   answers. They must cover an unchanged baseline, a positive control, invalid
   input, repeatability, leakage/split and universe boundaries, and the
   domain-critical edge cases that could reverse a conclusion.
6. Set the constitution's metric direction, baseline repetitions and tolerance,
   and minimum improvement. These values are research policy, not adapter
   defaults or CLI tuning knobs.
7. Implement the eight protocol operations as a thin translation layer around
   that evaluator. Reuse the versioned wire contract, but do not reuse another
   project's candidate schema, evaluator, dataset assumptions, or domain codes.
8. Run the golden cases, then set `x-research-os-configured=true` once the adapter
   enforces the final candidate contract. Run `inspect` and `doctor` to establish
   the project and adapter-reported evaluation seal. Have a separate read-only
   critic agent audit the evaluator, adapter, evidence boundaries, and independent
   oracles.
   Invoke `research-os --project ROOT evaluator-review-subject` and give the
   complete output to the critic. The critic emits the strict review JSON
   documented by the packaged skill with that output's exact `digest` in
   `subject_digest`. Keep both JSON files in a private temporary directory
   outside the project root. Then invoke
   `research-os --project ROOT certify-evaluator /ABS/OUTSIDE/REVIEW.json`; Research OS binds
   the review to current scientific-input fingerprints and manages
   `.research-os/evaluator-certification.json`. The implementing agent cannot
   self-certify; `doctor`, baseline repeats, and adapter `verify` are not a
   substitute.
9. After certification passes and remains current, exercise each operation
   against a disposable copy, then run an explicit `baseline`, one deliberately
   invalid candidate, one approved valid candidate, and `replay` before attaching
   an autonomous proposer. Issue `agent-context` only after doctor and baseline.
10. Any reviewed semantic change invalidates the certificate and returns the
    project to change-control, golden testing, certification, and a new compatible
    baseline.

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
7. `verify`: perform domain-specific result validity checks for every baseline
   and candidate result digest.
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

Put universe/selection manifests, split logic, golden fixtures/oracles, evaluator,
adapter imports, and cost model under protected and/or evidence paths as
appropriate. Research OS separately binds its canonical agent-spec digest (the
research brief plus candidate schema) into the managed certification. The
managed `.research-os/evaluator-certification.json` is gitignored and excluded
from source snapshots/workspaces; it must not be declared mutable, protected, or
evidence. The candidate JSON remains the project-owned domain payload. Research
OS records `graph_action` and `scientific_change` as top-level experiment
metadata supplied by CLI flags; projects need not duplicate those fields in
their candidate schema.

## Pre-register universe, splits, and holdout

Universe means the repeated units over which a claim is selected or evaluated:
assets or pairs, datasets or tasks, prompts, cohorts, environments, seeds, or the
domain equivalent. Its manifest must state the source identity, selection rule,
cutoff, eligibility and exclusion rules, missing-data policy, and digest. A bare
hard-coded list without its derivation is not a reproducible universe.

Use development evidence for candidate discovery and diagnosis. Define separate,
pre-registered cohorts, regimes, windows, or seeds for controlled replication.
Changing an evaluation unit, date range, selection rule, or replication axis
during research is not an ordinary candidate adjustment; it is change-control.
When universe discovery is itself the research objective, perform selection on
discovery data, freeze the selected universe at the declared cutoff, and evaluate
on separate evidence.

A locked holdout is physical separation, not a filter applied after an evaluator
has loaded a file containing future or final rows. Its bytes must be absent from
the project root, snapshots, configured research evidence, artifacts, agent
context, and iterative evaluator environment. Research OS v1 does not sandbox
arbitrary local reads, so a genuine lock requires actual byte absence or a
separate account, container/mount, or custodian. If that boundary is unavailable,
call the split held-out development evidence rather than locked holdout. Unlock
once only after the candidate and implementation digests are frozen; do not tune
from the final result.

## Designing a constitution

Choose one scalar primary metric. It should answer whether a candidate is better than a compatible baseline; secondary metrics and hard constraints can remain multidimensional.

Prefer kernel-owned typed gates for promotion-critical secondary metrics. The
adapter returns only observations in `ResultEnvelope.metrics`; the constitution
owns the comparison:

```toml
[[promotion.gates]]
id = "latency-budget"
metric = "latency_ms"
role = "hard"       # hard | support
operator = "lte"    # gte | lte
threshold = 50.0
unit = "ms"
scale = 50.0
```

Gate IDs must be unique after trimming. Thresholds are finite, scales are
finite and positive, and every configured metric must be present in the result.
`hard` failure rejects the candidate; `support` failure records insufficient
evidence. Equality passes a gate, while primary promotion still requires strict
improvement beyond `minimum_improvement`. Existing arbitrary `constraints`
remain compatible legacy hard vetoes but do not carry operator/threshold/slack
evidence.

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
prepare a strict `StudyContract` JSON for versioned research, then run the gates
explicitly:

```bash
RESEARCH_REVIEW_DIR="$(mktemp -d)"
research-os --project /path/to/your-project inspect
research-os --project /path/to/your-project doctor
research-os --project /path/to/your-project evaluator-review-subject \
  > "$RESEARCH_REVIEW_DIR/review-subject.json"
# After the independent critic writes "$RESEARCH_REVIEW_DIR/review.json":
research-os --project /path/to/your-project certify-evaluator \
  "$RESEARCH_REVIEW_DIR/review.json"
research-os --project /path/to/your-project open-generation \
  /absolute/path/to/study-contract.json
research-os --project /path/to/your-project study-status
research-os --project /path/to/your-project baseline
research-os --project /path/to/your-project run-once \
  /path/to/your-project/candidates/first.json
research-os --project /path/to/your-project status
research-os --project /path/to/your-project lineage
research-os --project /path/to/your-project artifacts
research-os --project /path/to/your-project findings
research-os --project /path/to/your-project replay
```

For StudyContract v2, the adapter first advertises
`evaluation_scope_v1`, and the execution portion becomes:

```bash
research-os --project /path/to/your-project baseline \
  --evaluation-scope-id development
research-os --project /path/to/your-project run-once \
  /path/to/your-project/candidates/first.json \
  --proposal /absolute/path/to/proposal.json
```

`StudyContract` versions 1 and 2 have the same exact-key shape and contain:

- `schema_version` and a stable `study_id`;
- unique `hypothesis_classes` with conclusive-rejection limits;
- an `intervention_surface` binding the candidate-schema digest, allowed RFC-6901
  pointers, and maximum changes;
- unique `evaluation_scopes`, including at least one `development` scope, each
  bound to a manifest digest;
- finite `frontier`, literal fail-closed `stop_policy`, and mandatory
  new-generation `change_control`;
- a `budget` for attempts, retries, elapsed reservation per attempt, and either a
  complete cost-unit/limit/reservation triple or three nulls.

Version 2 additionally rejects two scope IDs that alias the same
`manifest_digest`, requires the adapter capability `evaluation_scope_v1`, and
requires the contract candidate-schema digest to match the current certified
project schema. It activates the exact 12-field Proposal contract:

```json
{
  "proposal_schema_version": 1,
  "generation_id": "generation_...",
  "candidate_digest": "0000000000000000000000000000000000000000000000000000000000000000",
  "hypothesis_class_id": "class-a",
  "action": "explore",
  "mechanism": "Why this intervention could affect the metric.",
  "predicted_effect": "A falsifiable directional prediction.",
  "falsifier": "The observation that would reject the mechanism.",
  "parent_experiment_id": null,
  "evaluation_scope_id": "development",
  "intervention_json_pointers": ["/x"],
  "authorized_action": null
}
```

`explore` has no parent. `exploit` and `ablate` require a terminal parent, a
changed candidate, and declared pointers exactly equal to the canonical
parent-to-candidate diff. `replicate` requires the parent's exact frozen
candidate and hypothesis class, an empty pointer list, and a different unused
preregistered replication scope. A retry supplies only `--retry-of` and the
same candidate; it inherits the persisted Proposal and scope and is not counted
as a new scientific replication. Proposal fields remain sibling evidence on
the registration event and never become candidate fields.

The opened generation binds this normalized contract to a separate evaluation
seal. Each later registration receives the contract-fixed debit inside the
canonical append lock. `study-status` reports reserved allocations; it does not
claim actual elapsed time or cost. Limits are per generation, and a changed
successor requires both the exact predecessor ID and a reason. An identical
successor is rejected instead of resetting the ledger.

Before the first generation, the legacy/manual tokenless `run-once` path
establishes a compatible repeated
baseline when none exists. Codex and Claude Code must use `--context-token` and
must run `baseline` explicitly before obtaining that context; an implicit
baseline changes canonical state and correctly makes an older token stale. The
tokenless path is retained only for direct API/CLI compatibility and does not
enforce the agent certification gate. After a generation opens, tokenless and
context-token registrations share the same generation binding, typed Proposal,
pending Diagnosis, class-closure, and atomic budget gates. Explicit baseline setup also isolates
reproducibility and cleanup failures before candidate work.
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

1. Run `doctor`, `replay`, and `agent-context`; Context v3 is the default. Read
   the bounded scientific state, graph, brief, schema, findings, artifacts, and
   snapshot token. Use explicit `--schema-version 2` only for compatibility.
2. Explore independent pre-registered hypothesis classes as root nodes.
3. After every terminal node, diagnose the exact status, constraints, and
   relevant artifacts without running another experiment.
4. Select a scientifically defensible parent and one conceptual intervention for
   an ablation or exploitation, then use a pre-registered controlled variation to
   replicate a promising mechanism.
5. Write one bounded domain candidate to `.research-os/candidate.inbox.json`.
6. Call `run-once` with top-level `--graph-action` and `--scientific-change`
   metadata. Omit `--parent` only for `explore`; require it for `ablate`,
   `exploit`, and `replicate`.
7. Continue until the finite budget, a safety gate, or a pre-registered
   repeated-class failure threshold stops the loop.

For Research OS 0.4.0 Program memory integrations, bind retrieval to Context v3
before proposing, disposition every returned Claim exactly once, and append the
companion only after the typed Proposal is present in canonical project replay.
Treat old notes, findings, or branch text without a typed schema as
`legacy_unstructured`: retain only source metadata plus content digest/size,
never infer Claims and never store raw legacy content in ProgramLog. This setup
does not authorize migrating an existing project or taking any live action.

For example:

```text
research-os --project PATH run-once PATH/.research-os/candidate.inbox.json \
  --graph-action explore \
  --scientific-change "CLASS: retrieval weighting; CHANGE: add title weight only" \
  --context-token TOKEN

research-os --project PATH run-once PATH/.research-os/candidate.inbox.json \
  --graph-action exploit \
  --scientific-change "CLASS: retrieval weighting; CHANGE: bound title weight" \
  --parent exp_<parent-id> --context-token TOKEN
```

The scientific-change declaration must name the class and cover the complete
semantic diff from the parent, or from the baseline for a root. Multiple coupled
fields are one change only when separating them would make the mechanism
undefined. Candidate schemas may contain richer project-owned hypothesis fields,
but they do not need to duplicate the top-level orchestration metadata.

Only conclusive `REJECTED` outcomes under the current compatibility count toward
class closure. The default threshold is three when the brief did not choose one.
At the threshold the agent submits no further variant from that class. It may
explore an untouched pre-registered class; otherwise it stops or enters explicit
change-control. A semantic change requires user approval, new golden evidence,
independent re-certification, and a new compatible baseline before research
resumes.

At class closure and after a materially supported replicated branch, the agent
writes an exact branch conclusion object containing only
`branch_experiment_ids`, `hypothesis_class`, `failure_signature`, `conclusion`,
`confidence`, and `next_step` to the transient inbox, then records it with:

```text
research-os --project PATH conclude-branch \
  PATH/.research-os/candidate.inbox.json --context-token TOKEN
```

All named experiments must be terminal and share one compatibility digest.
`confidence` is `supported`, `falsified`, or `inconclusive`; `next_step` is
`stop`, `change_control`, `explore`, `ablate`, `exploit`, or `replicate`. The
result is an evidence-bound agent finding, not authority for production action.

If no finite budget was supplied, the shared skill permits one experiment and
zero retries. A status-only request starts no experiment. Changes to the
metric, evaluator, evidence, constitution, protected paths, or candidate schema
switch the agent out of research mode into explicit change-control and require
golden cases, independent certification, and the appropriate compatible baseline
before research resumes. The same rule applies to universe, selection, split,
holdout-boundary, cost-model, and immutable-policy changes.

The OS rejects an identical candidate under the same parent and immutable compatibility fingerprint. Changed evaluator/data/config fingerprints force a new baseline, preventing incomparable evidence from sharing a promotion decision.

Do not resubmit a failed candidate as an ordinary `run-once`; duplicate evidence remains refused. If the most recent attempt timed out, was cancelled, was recovered after interruption, or ended with an adapter error that explicitly set `retryable: true`, request one new attempt with:

```text
research-os --project PATH run-once candidate.json --retry-of exp_<prior-id> \
  --context-token TOKEN
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
