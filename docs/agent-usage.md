# Using Research OS through Codex or Claude Code

## Interface contract

The user talks only to Codex or Claude Code. The coding agent is the researcher
and conversational interface; Research OS is a headless local control plane.
It does not contain an LLM SDK, model API key, chat session, or autonomous
provider loop.

```text
user conversation
      |
Codex or Claude Code
      |  shared research-os Agent Skill
      |  strict JSON CLI
Research OS
      |  isolated workspace + project adapter
project evaluator
      |
canonical events, artifacts, findings, DAG
      |
Codex or Claude Code explains the evidence
```

This split lets the user change coding agents without changing experimental
history or domain adapters.

## One-time installation

From the Research OS checkout:

```bash
~/research-os/.venv/bin/research-os install-agent-skill --target all
```

Existing exact 0.1.0 installations and byte-exact managed 0.2.0 installations
require the explicit recognized-release upgrade:

```bash
~/research-os/.venv/bin/research-os install-agent-skill --target all --upgrade
```

A successful upgrade reports `from_release`, `to_release`, and `recovery_backup`,
and retains the original inode tree there. The installer never deletes that backup automatically,
because another process may still hold an open descriptor to an old skill file.
Before any manual deletion, inspect and diff the retained tree against the new
installation, preserve or merge every late write, and verify its provenance.
Writer shutdown and a working 0.3.0 installation are necessary but not
sufficient: retention exists specifically so edits through an already-open old
descriptor are not silently discarded.

The command copies one packaged Agent Skills-standard workflow to:

- `~/.agents/skills/research-os` for Codex;
- `~/.claude/skills/research-os` for Claude Code.

It accepts an existing byte-identical installation and refuses symlinks,
special files, or different content rather than overwriting local work.

Codex may invoke the skill implicitly or through `$research-os`. Claude Code
may invoke it implicitly or through `/research-os`.

## Normal conversation

Start Codex or Claude Code at the target project and ask for the scientific
outcome, not an OS command. A short request is sufficient:

```text
Improve this strategy with bounded autoresearch. Use at most six experiments.
```

The agent performs project discovery, scientific setup gates, certification,
graph metadata, and CLI work behind the conversation. It asks only when the
scientific contract is materially ambiguous, an expensive run needs approval,
or the requested action crosses an authority boundary. More detailed requests
remain useful:

```text
Set this repository up to search for a lower validation-loss architecture.
Keep the evaluator and split fixed. Ask me before starting expensive training.
```

```text
Use at most six experiments. Explore two independent signal hypotheses, then
spend the remaining budget on the more informative branch. No retries and no
live trading.
```

```text
Summarize what the graph has established, including negative evidence. Do not
run a new experiment.
```

The skill makes the agent resolve the project, run the required gates, call the
CLI, parse JSON, and report in natural language. Raw JSON is shown only on
request.

## Agent context and stale-proposal protection

`agent-context` emits Context v3 by default. Explicit `--schema-version 2`
preserves the prior packet for compatibility. The bounded read model contains:

- the resolved scientific contract and authority boundary;
- the research brief and candidate JSON Schema;
- canonical status and event cursor;
- recent experiments and current graph frontier;
- only the latest retry-eligible attempts;
- recent durable findings and verified artifact metadata;
- counts showing whether each section was truncated.

Large values are replaced by deterministic digest handles and the complete
packet has a 2 MiB ceiling. The packet contains `snapshot.context_token`. The
agent writes its one candidate to the excluded transient inbox, then supplies
the token to `run-once`. A changed event graph, evaluator compatibility input,
brief, or schema makes the token stale and prevents registration.

## Mode separation

The shared skill enforces three modes:

1. **Status:** query and explain only; no experiment.
2. **Setup/change-control:** configure or deliberately revise the adapter,
   evaluator, evidence, metric, candidate schema, constitution, and baseline.
3. **Research:** change only the candidate inbox and execute bounded graph
   iterations.

The agent cannot silently revise the evaluator or policy after seeing a result.
Any such request leaves research mode and goes through a new compatibility and
baseline gate.

Setup is not complete merely because `doctor` passes. Before the first baseline,
the agent pre-registers the evaluation universe, selection cutoff, development
and replication splits, hypothesis classes, repeated-class failure threshold,
costs, and holdout boundary. It runs hand-derived golden cases, marks the fully
implemented candidate contract configured, then runs `inspect` and `doctor` to
establish the project and adapter-reported evaluation seal. A separate read-only
critic certifies that exact brief/schema, evaluator, adapter, selection/split
logic, fixtures, and evidence state. Adapter `verify` and baseline repeatability
remain useful gates, but they are not this independent scientific review.

The critic emits the strict nine-check review JSON documented by the packaged
skill. The agent first emits the exact bound subject and gives it to the critic:

```text
research-os --project PATH evaluator-review-subject
```

Store this output and the review in a private temporary directory outside the
project root. The critic copies the subject's `digest` into the required
`subject_digest` field, completes the review, and the agent calls:

```text
research-os --project PATH certify-evaluator /ABS/OUTSIDE/REVIEW.json
```

Replacing an existing managed certificate is explicit:

```text
research-os --project PATH certify-evaluator /ABS/OUTSIDE/REVIEW.json --replace
```

Research OS manages `.research-os/evaluator-certification.json`, binds it to the
current constitution, protected/evidence/environment fingerprints, adapter
doctor seal, and agent-spec digest, and exposes current certification in
`agent-context`. The managed file is
gitignored and snapshot/workspace-excluded; it is never hand-edited or declared
mutable, protected, or evidence.

Locked-holdout bytes remain outside the project, Research OS workspaces and
research evidence, and the iterative evaluator's readable environment. Because
Research OS is not an operating-system sandbox, a genuine lock also requires
actual byte absence or a separate account, container/mount, or custodian. Final
holdout evaluation occurs once after the candidate and implementation are frozen
and does not feed another tuning iteration.

## Study generation and cumulative reservation

For versioned research, setup produces a strict `StudyContract` JSON after the
scientific inputs are fixed and the evaluator certificate is current. Open it
before obtaining the agent context used for the first proposal:

```text
research-os --project PATH open-generation /ABS/PATH/study-contract.json
research-os --project PATH study-status
research-os --project PATH baseline
research-os --project PATH agent-context
```

The contract pre-registers hypothesis classes, allowed candidate JSON pointers,
evaluation scopes, frontier/stop policy, and fixed per-registration reservations.
All objects use exact version-one keys; unknown, missing, duplicate, unsafe, or
semantically inconsistent values fail closed. The generation event binds the
normalized contract separately from the current compatibility and evaluator
certification seal.

Every registration after that event atomically reserves one attempt, an optional
retry, elapsed allocation, and optional cost allocation. A failed, invalid,
cancelled, timed-out, untrusted, rejected, or validated terminal outcome consumes
the same reservation; there is no refund. These are conservative allocations,
not actual usage telemetry. `study-status` is replay-derived and is the operator's
current budget view.

A scientific or evaluation change opens an explicit successor only after the
normal change-control and re-certification work:

```text
research-os --project PATH open-generation NEW-CONTRACT.json \
  --predecessor-generation-id generation_CURRENT \
  --change-reason "state the preregistered change"
```

The same contract and seal cannot be used to reset a generation. A genuinely
changed successor receives a fresh per-generation budget; repeated successors
are auditable but there is not yet a study-lifetime cap.

## Terminal Diagnosis gate

After every terminal experiment in a version-two generation, stop proposing
experiments and prepare one strict Diagnosis bound to the returned experiment,
terminal event ID/hash, persisted Proposal and scope, Decision observation, and
verified artifacts. Record it before any next registration, retry, or successor:

```text
research-os --project PATH diagnose /ABS/PATH/diagnosis.json
research-os --project PATH study-status
research-os --project PATH replay
```

Research OS derives `ClassState`, immutable class closure, and the
semantic/retry frontiers from verified evidence. Treat the agent's
interpretation, falsifier, and recommendation as bounded research provenance,
not as execution or closure authority. Current `agent-context` v2 does not
expose these fields or generate the strict JSON, so the caller must preserve the
exact IDs until context v3 and the Diagnosis authoring template land.

The opt-in M1-E preview removes that manual evidence copying while preserving
context v2 as the default:

```text
research-os --project PATH agent-context --schema-version 3
research-os --project PATH diagnosis-template > /ABS/PATH/diagnosis.json
# If several terminal experiments are pending:
research-os --project PATH diagnosis-template --experiment exp_ID \
  > /ABS/PATH/diagnosis.json
```

Replace only the four `REPLACE_ME` fields (`interpretation`, `failure_type`,
`falsifier`, and `recommendation`), then call `diagnose`. The template command
is read-only and derives every identity, artifact reference, and quantitative
observation from canonical replay.

## Scientific graph workflow

Research follows a phase machine rather than unconstrained sequential parameter
search:

1. **Explore:** test independent, pre-registered mechanism classes as root nodes.
2. **Diagnose:** after every terminal result, inspect the exact reason, constraints,
   and relevant artifacts without running an experiment.
3. **Ablate or exploit:** isolate an uncertain mechanism or improve a supported
   one using a scientifically defensible parent.
4. **Replicate:** apply a pre-registered controlled variation to a promising
   mechanism without turning replication into another tuning round.

Each `run-once` records orchestration metadata through top-level CLI flags rather
than forcing it into every project candidate schema:

```text
research-os --project PATH run-once PATH/.research-os/candidate.inbox.json \
  --graph-action explore \
  --scientific-change "CLASS: momentum; CHANGE: add one volatility regime gate" \
  --context-token TOKEN

research-os --project PATH run-once PATH/.research-os/candidate.inbox.json \
  --graph-action ablate \
  --scientific-change "CLASS: momentum; CHANGE: remove only the volume term" \
  --parent exp_PARENT --context-token TOKEN
```

`explore` has no parent; `ablate`, `exploit`, and `replicate` require a compatible
completed parent. The scientific-change declaration must name the hypothesis
class and completely cover one conceptual intervention. Several fields may move
together only when they are scientifically indivisible. Undeclared differences
and unrelated bundles are refused before registration.

The brief pre-registers how many conclusive rejections close a hypothesis class;
the default is three. Operational and insufficient-evidence outcomes do not
count. Once closed, the agent cannot submit another variant from that class. It
may explore an untouched pre-registered class, or it must enter change-control.
Changing the evaluator, golden oracle, universe, selection rule, split, holdout
boundary, costs, evidence, metric, candidate schema, or immutable policy requires
user approval, new golden results, independent re-certification, and a new
compatible baseline.

At class closure, or after a materially supported replicated branch, the agent
records an evidence-bound interpretation with `conclude-branch`. The strict JSON
contains exactly `branch_experiment_ids`, `hypothesis_class`,
`failure_signature`, `conclusion`, `confidence`, and `next_step`. The agent writes
it to the snapshot-excluded transient inbox and calls:

```text
research-os --project PATH conclude-branch \
  PATH/.research-os/candidate.inbox.json --context-token TOKEN
```

The command binds the finding to the named terminal events. It authorizes no
production action, and the agent refreshes `agent-context` afterward.

## Authority

`VALIDATED` means that one sealed experiment met the research constitution. It
does not authorize a merge, deployment, model release, allocation of capital,
or live order. Codex or Claude Code must report `authorized_action: null` and
handle any production proposal as a separate reviewed workflow.
