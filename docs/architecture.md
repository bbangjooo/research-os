# Architecture

Research OS v1 is deliberately a single-machine modular monolith.

```text
User
    |
Codex / Claude Code (shared Agent Skill)
    |
agent-context / run-once JSON CLI
    |
ResearchService
    +-- ProjectConfig + constitution
    +-- AdapterClient ---- project adapter/evaluator process
    +-- WorkspaceManager - disposable snapshot + drift checks
    +-- ArtifactCatalog -- immutable SHA-256 blobs
    +-- EventLog --------- canonical hash-chained JSONL
    +-- ProjectionStore -- rebuildable SQLite views
    +-- FindingStore ----- scoped durable conclusions
```

Research OS has no chat interface and does not call an LLM provider. Codex or
Claude Code is the conversational researcher: it gathers the user's intent,
selects a graph action, creates one bounded candidate, invokes the control
plane, and translates durable evidence back to the user. The shared packaged
skill defines that workflow; the CLI remains a headless provider-neutral
boundary.

Before proposing, the agent reads one bounded `agent-context` packet. The packet
binds its research brief and candidate schema to the current canonical event
cursor and compatibility fingerprint. `run-once --context-token` checks this
snapshot before and after doctor/recovery, after any baseline creation, and again
immediately before registration. Agent workflows therefore seal the baseline
before issuing context; a state-changing implicit baseline makes the token stale.
The transient candidate inbox is excluded from source snapshots so writing the
candidate does not invalidate that token or crash recovery.

The canonical graph is an event stream. `EXPERIMENT_REGISTERED` supplies a node,
optional parent edge, and top-level `graph_action` and `scientific_change`
metadata; stage, artifact, finding, and terminal events attach typed evidence.
The project-owned candidate remains a domain payload and need not duplicate that
orchestration metadata. SQLite accelerates queries but can be deleted and rebuilt
with `replay`.

Every candidate identity is the tuple `(project, compatibility, parent, candidate digest)`. Its first registration has `attempt: 1` and `retry_of: null`. A retry is a new graph node with a deterministic attempt-aware ID, a contiguous attempt number, the same identity tuple, and `retry_of` pointing to the immediately preceding attempt. The scientific DAG parent does not change: `parent_id` represents hypothesis ancestry, while `retry_of` represents execution-attempt lineage. The projection independently validates both relationships during live sync and full replay.

This avoids graph-database and distributed-worker complexity until a measured need appears. The process protocol and canonical events are already versioned seams for those later changes.

The shared skill applies additional graph discipline: `explore` creates roots;
diagnosis is a read-only, no-experiment phase after every terminal node;
`ablate`/`exploit` and `replicate` require compatible parents; and one scientific
change must cover exactly one conceptual intervention. It also closes a
pre-registered hypothesis class after its configured number of conclusive
rejections, defaulting to three. These are proposer-policy gates on top of the
kernel's durable ancestry and duplicate checks.

## Compatibility seal

A compatible baseline is bound to the digests of both TOML contracts, protected
paths, evidence paths, adapter execution environment, adapter-provided
fingerprint, and the source state of declared mutable paths. Mutable paths are
fingerprinted as content-bearing files/trees or explicit missing-path markers;
they are not excluded simply because a candidate may later change their
workspace copies. Changing a mutable default, or making a missing mutable path
appear or disappear, rotates the compatibility digest and forces a new
baseline.

The constitution owns the baseline repeat count. `ResearchService.baseline()`
always uses `[baseline].repeats`, and a sealed baseline is revalidated against
that same value. CLI `--repeats` is only an equality assertion and cannot mutate
policy. A `ResearchService` instance caches its validated `ProjectConfig`; if
either TOML contract changes, callers must create a new instance. Public methods
fail closed on a stale cached configuration.

## Scientific correctness boundary

Research OS proves that configured bytes and protocol results are bounded,
compatible, reproducible, and auditable. It cannot infer whether an evaluator's
domain equations, execution timing, labels, costs, or split logic are correct.
Adapter `verify` is a separate protocol operation over a normalized result, but
it is still implemented by the same project integration. It is not independent
evaluator certification.

The shared skill therefore blocks initial research until small golden cases with
independently derived answers pass and a separate read-only critic issues a PASS
certificate bound to the evaluator, adapter, universe/selection, split, cost,
fixture, and evidence digests. A reviewed semantic change invalidates that
certificate and requires change-control, new golden results, re-certification,
and a new compatible baseline. The critic submits a strict review through
`certify-evaluator`; Research OS manages
`.research-os/evaluator-certification.json` and binds it to the full current
constitution/protected/evidence/environment fingerprints, adapter-reported
fingerprint and effective compatibility seal, plus the canonical agent-spec
digest. The managed file is gitignored and excluded from snapshots and
workspaces; it must not itself be declared mutable, protected, or evidence. Its
reviewed scientific inputs remain protected/evidence as appropriate.
Before review, `evaluator-review-subject` emits those complete bindings and one
canonical digest. Certification accepts only a critic-authored review carrying
that exact digest, preventing a PASS review from being replayed after drift.

Certification enforcement is the context-token-backed Codex/Claude boundary.
The tokenless direct service/CLI path remains available for legacy integrations
and intentionally does not claim agent research readiness.

The evaluation universe, selection cutoff, development/replication splits, and
holdout boundary are similarly pre-registered before the first baseline. Locked
holdout bytes stay outside the project, workspaces, configured research evidence,
artifacts, and iterative evaluator environment until the selected candidate and
implementation are frozen.

## Failure semantics

- Adapter-declared invalid input becomes `INVALID_EXPERIMENT`.
- A wall-clock process timeout becomes `TIMED_OUT`.
- Spawn, process, output-limit, or protocol failures become `INFRA_FAILED`.
- Protected/source/mutation-boundary drift becomes `UNTRUSTED`.
- Missing evidence becomes `INSUFFICIENT_EVIDENCE`.
- A user interrupt becomes `CANCELLED` after its terminal event is recorded.
- A valid non-improvement becomes `REJECTED`.
- A verified improvement satisfying constraints becomes `VALIDATED`.

Every registered attempt eventually receives exactly one durable terminal event.
If a worker disappears between registration and termination, the next
serialized service command (including `replay`) first rebuilds the projection
from canonical events and performs evidence recovery before closing the attempt.

Once a successful `evaluate` stage is durable, a caught `KeyboardInterrupt`
does not immediately write the `CANCELLED` terminal. The live worker first
captures every declared artifact and proves that all corresponding
`ARTIFACT_RECORDED` events are canonical. It may clean the workspace and append
the cancellation terminal only after publication is complete. If capture or
publication fails and completeness cannot be proven from canonical history,
the worker detaches and preserves the workspace, leaves the attempt without a
terminal event, and re-raises the interruption or publication error. The next
serialized service command then applies the restart-recovery rules below.

For an interrupted attempt with one successful canonical `evaluate` stage,
Research OS parses that recorded `ResultEnvelope` and requires existing catalog
records to match its artifact declarations exactly. If records are missing, it
adopts exactly one safe orphan workspace only when the current source tree still
matches the registration-time source seal. Adoption reconstructs the clean
pre-run manifest and protected seals from a fresh reference snapshot, rechecks
the orphan's identity, verifies its mutation boundary, captures and validates
all declared artifacts, and appends their `ARTIFACT_RECORDED` events. Only then
may the orphan be removed. Already-complete manifests are validated and
published without trusting workspace state.

After evidence recovery, the attempt still terminates `INFRA_FAILED` with reason
`RECOVERED_INTERRUPTED_RUN`: preserved output is evidence of an interrupted
attempt, not permission to infer a scientific verdict. If the canonical history
has no successful evaluation, no output is inferred; the attempt is closed and
ordinary orphan cleanup may remove its residue. If evaluated evidence cannot be
proven or captured—because the source seal drifted, the orphan is missing,
ambiguous, unsafe, or fails verification—the command fails closed before the
ordinary infrastructure terminal can be written. It instead appends one
`UNTRUSTED/INTERRUPTED_EVIDENCE_UNTRUSTED` terminal with
`preserve_workspace=true`. Pre-adoption entries remain untouched; an adopted
orphan is relinquished without deletion, and later generic cleanup excludes the
experiment's residue so it remains available for inspection.

For a terminalized live candidate, cleanup occurs after evidence and policy
evaluation but before the terminal event is appended. The incomplete-publication
case above deliberately skips cleanup and terminalization so restart recovery
retains the evidence source. Otherwise, an adapter cleanup response failure or
local workspace-removal failure is recorded in `secondary_errors`; it does not
replace the already established scientific status. Protected/source/adapter
drift found around cleanup is different: it is primary integrity evidence and
dominates as `UNTRUSTED`. Baseline cleanup is a sealing gate, so any
repetition's cleanup failure prevents `BASELINE_RECORDED` from being appended.

Ordinary duplicate registration is refused even after an infrastructure failure. A retry is an explicit caller request and is permitted only for the most recent attempt when its terminal evidence is one of:

- an adapter error whose response declared `retryable: true`;
- `TIMED_OUT`;
- `CANCELLED`;
- an incomplete registered/queued/running node recovered as `RECOVERED_INTERRUPTED_RUN`.

`INVALID_EXPERIMENT`, `REJECTED`, `VALIDATED`, `UNTRUSTED`, and non-retryable infrastructure failures cannot be retried. Retry eligibility, `attempt`, and `retry_of` are recorded in the terminal event so replay reaches the same decision without consulting transient worker state.

The caller must submit the identical candidate and explicitly name the latest
eligible attempt:

```text
research-os --project PATH run-once candidate.json --retry-of exp_<prior-id> \
  --context-token TOKEN
```

Supplying `--parent` on a retry is optional; when supplied it must equal the
prior attempt's scientific parent. There is no automatic retry loop.

## Durable state and replay

`.research-os/runtime/events.jsonl` is the canonical, project-bound,
hash-chained stream. Complete event lines are append-only. Startup recovery may
truncate only an unterminated final fragment; all preceding complete lines must
first pass canonical JSON, sequence, project, event-ID, and hash-chain checks.

Concretely, every committed line must be one canonical UTF-8 JSON event followed
by one newline, with exactly the version-1 envelope fields. Validation rejects
duplicate JSON keys, unsupported/non-finite values, invalid timestamps, extra or
missing envelope fields, non-positive or discontinuous sequences, mixed project
IDs, duplicate event IDs, malformed hashes, a wrong `prev_hash`, or a mismatch
between `hash` and the SHA-256 of the canonical unsigned envelope. A corrupt
complete line is never treated as crash residue.

`.research-os/runtime/state.db` is a disposable projection. `replay` verifies
the canonical stream, rebuilds the projection, durably closes any abandoned
registered/queued/running nodes and repairs a missing outcome finding, then rebuilds
again. Projection lifecycle checks independently reject malformed parent and
retry graphs. If SQLite identifies the cache as corrupt or not a database,
Research OS preserves the derived files as `state.db*.corrupt-<token>`, creates
a clean projection, and repopulates it from canonical events on the next
service operation.

Both baseline and candidate artifacts are captured before their disposable
workspaces are deleted. Baseline artifact records live in `BASELINE_RECORDED`;
candidate artifact records also project into the `artifacts` query. `replay`
collects both sets, validates each immutable catalog record, and re-hashes its
SHA-256 blob. Its `artifacts_verified` result counts unique artifact records,
not unique blob contents.

Artifact validation has three linked layers:

1. Capture opens a declared workspace-relative regular file without following
   symlinks, checks that its identity and size/mtime stay stable while copying,
   enforces the total byte budget, computes SHA-256, and verifies any
   adapter-declared digest/size pair.
2. The blob is stored at `blobs/sha256/<first-two-hex>/<digest>`. Its byte count
   and re-hashed digest must match. The one-line manifest under `records/` must
   be canonical JSON and must recompute to the deterministic artifact ID from
   project, experiment, relative path, digest, role, media type, and metadata.
   Record validation also requires algorithm `sha256`, a safe relative path, a
   non-negative size, a valid capture timestamp, JSON metadata, and the exact
   storage path derived from the digest.
3. The normalized `ArtifactRecord` fields in canonical evidence must agree
   exactly with that manifest: candidate records are `ARTIFACT_RECORDED`
   payloads; baseline records are embedded in `BASELINE_RECORDED` with their
   repetition. `artifacts` verifies the projected event payload, manifest, and
   blob; `replay` performs the same linkage for all baseline and candidate
   records.

An orphan blob or manifest created before a failed canonical append grants no
research authority. Only the hash-chained event stream binds captured bytes to
an attempt or sealed baseline.

## Findings

`experiment_outcome` is a kernel-reserved finding key. For every terminal
attempt, Research OS derives a deterministic project-scoped finding whose sole
evidence item is that terminal event's ID and hash. Recovery may repair a
missing outcome-finding append, but it rejects conflicting ownership, duplicate
coverage, or inconsistent content. Project and agent-authored findings must use
other keys.

`conclude-branch` records a `branch_conclusion` finding from an exact strict JSON
object. Every named experiment must be terminal and all must share one
compatibility digest. The finding binds the agent's hypothesis class, failure
signature, conclusion, confidence, and next step to the canonical terminal event
IDs and hashes. This makes class closure and materially supported replicated
branches durable without promoting agent interpretation to deployment authority.

## Authority boundary

Research OS is a trusted local-process boundary on POSIX, not an operating
system sandbox for hostile native code. It executes configured adapters without
a shell, applies process/output/time bounds, seals declared inputs, and rejects
protocol-v1 adapters that declare external side effects. Authority-bearing
research payloads contain `authorized_action: null`; deployment, source merges,
model release, capital allocation, and live orders require a separate reviewed
system. In particular, protected/evidence declarations prove the identity of
declared inputs but cannot prevent adapter code from opening some other readable
local file. A physical locked-holdout claim therefore requires actual byte
absence or isolation outside this process boundary.
