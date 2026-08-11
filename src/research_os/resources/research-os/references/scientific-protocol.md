# Scientific workflow gates

Use this checklist during setup/change-control and before the first research
iteration. These are scientific-validity gates layered on top of Research OS's
protocol, integrity, budget, and replay checks.

## Hidden setup gate

The user may ask simply to research or improve a project. Perform this gate
yourself; do not make the user operate the CLI or learn this vocabulary.

Proceed in this order:

1. pre-register the scientific contract;
2. implement the evaluator and adapter;
3. pass independent-oracle golden cases;
4. mark the fully implemented candidate contract configured;
5. run `inspect` and `doctor` to establish the project and adapter seal;
6. emit `evaluator-review-subject`, have an independent critic review that exact
   subject, and submit its digest-bound review with `certify-evaluator`;
7. run an explicit `baseline`, an invalid candidate, one approved valid smoke
   candidate, and `replay`.

Certification binds the exact brief and candidate schema from step 4. Any
semantic edit after step 5 invalidates the certificate. Do not solve a failed
gate by relaxing the oracle, tolerance, split, costs, or constraints.

## Pre-registration record

Record these items in the research brief before sealing a baseline:

- objective, primary metric, direction, promotion threshold, and veto constraints;
- finite experiment, retry, time, and cost budgets;
- allowed candidate surface and pre-registered hypothesis classes;
- class-failure threshold, defaulting to three when the user did not choose one;
- evaluation-universe identity, selection rule, selection cutoff, exclusions,
  missing-data policy, and manifest digest;
- development, diagnostic, and replication splits or cohorts and their permitted
  uses;
- fee, slippage, funding, latency, preprocessing, seed, and other domain policies;
- locked-holdout identity and the physical boundary that makes it inaccessible
  during iterative research;
- golden-case locations and the managed evaluator-certification state.

Universe means the repeated units over which a claim is selected or evaluated,
such as assets, pairs, symbols, datasets, tasks, prompts, cohorts, environments,
or seeds. Freeze the manifest and selection code under protected/evidence paths.
An unexplained hard-coded list is not pre-registration. If discovering the
universe is itself the objective, separate discovery data from evaluation data,
freeze the selected universe at the declared cutoff, and evaluate it without
using the locked holdout.

## Physical holdout boundary

A locked holdout is not merely a date filter applied after loading a larger file.
Its content must be absent from the project root, Research OS snapshots,
configured research evidence, agent context, artifacts, and the iterative
evaluator's readable environment. A visible manifest may contain only an opaque
identity, digest, and the minimum metadata needed to prove the boundary.

Research OS v1 is a trusted local-process control plane, not an OS sandbox. File
classification alone cannot prevent arbitrary adapter code from reading another
local path. Require a separate account, container/mount boundary, remote custodian,
or actual absence of the bytes when a genuine lock matters. If none exists,
describe the split as ordinary held-out development evidence, not locked holdout.

Unlock once only after the candidate payload, evaluator, adapter, universe,
selection/split logic, costs, and code digests are frozen. Run final holdout
evaluation outside the iterative graph. Do not tune from its result. A subsequent
research generation needs a new untouched holdout.

## Golden-case matrix

Expected results must be hand-derived or produced by a simpler independent
oracle, never copied from the evaluator under test.

| Case | Required proof |
| --- | --- |
| Unchanged baseline | Exact expected primary metric and constraints on a tiny fixture. |
| Positive control | One known candidate moves the expected output in the expected direction. |
| Invalid control | A malformed or forbidden candidate fails before expensive execution. |
| Repeatability | Repeated runs with fixed inputs/seeds agree within declared tolerance. |
| Split boundary | Future, replication, or unavailable rows cannot affect earlier selection/signals. |
| Universe boundary | Unknown or post-cutoff units cannot enter evaluation silently. |
| Cost/metric edge | Hand-computed fees, penalties, aggregation, and constraint direction agree. |
| Domain edge | Exercise the failure-prone semantics that could reverse the scientific conclusion. |
| Holdout tripwire | Iterative evaluation succeeds with locked bytes absent and fails if code requests them. |

For trading evaluators, domain edges normally include signal/entry alignment,
next-open versus same-bar execution, stop/take-profit collision policy, fees,
slippage, funding, missing bars, position accounting, and long/short exit signs.
For ML or retrieval evaluators, use the equivalent leakage, masking, seed,
preprocessing, label, aggregation, and resource-limit cases.

## Independent evaluator certification

The certifier must be a separate read-only critic agent or reviewer that did not
implement the evaluator and cannot edit it during review. `doctor` checks protocol
and integrity; repeated baseline agreement checks reproducibility; adapter
`verify` checks one normalized result through the same project integration. None
is independent scientific certification.

The critic reviews code, fixtures, expected answers, and actual outputs, then
writes one strict JSON object with exactly these top-level fields and no extras:

Before review, run `research-os --project ABS evaluator-review-subject`. Give
the complete output to the critic; it covers every certification binding and
the effective compatibility seal. The critic authors the review against that
subject and copies its exact `digest` below. Store both JSON files in a private
temporary directory outside the project root; never reuse an older review.

```json
{
  "schema_version": 1,
  "kind": "research-os-evaluator-review",
  "subject_digest": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "reviewer": "independent critic identity",
  "independent_reviewer": true,
  "verdict": "PASS",
  "summary": "bounded review conclusion",
  "checks": [
    {"id": "evidence_isolation", "status": "PASS", "evidence": "..."},
    {"id": "evaluation_timing_or_causality", "status": "PASS", "evidence": "..."},
    {"id": "outcome_accounting", "status": "PASS", "evidence": "..."},
    {"id": "cost_and_resource_model", "status": "PASS", "evidence": "..."},
    {"id": "metric_semantics", "status": "PASS", "evidence": "..."},
    {"id": "constraint_semantics", "status": "PASS", "evidence": "..."},
    {"id": "candidate_contract", "status": "PASS", "evidence": "..."},
    {"id": "deterministic_golden_cases", "status": "PASS", "evidence": "..."},
    {"id": "external_state_isolation", "status": "PASS", "evidence": "..."}
  ],
  "blocking_findings": []
}
```

`subject_digest` must exactly match the current emitted review subject.
`reviewer`, `summary`, and every `evidence` value must be non-empty strings.
`verdict` and every check `status` accept only `PASS` or `FAIL`.
`blocking_findings` is an array of unique non-empty strings. The nine check IDs
above are exact and complete: omit none, add none, and do not duplicate one.
Certification is passing only when `independent_reviewer` is true, the verdict
and all nine checks are `PASS`, and `blocking_findings` is empty.

The critic must reject hidden whole-file holdout reads, look-ahead or target
leakage, wrong timing or accounting, inconsistent metric direction, candidate
fields that do not materialize as declared, unpriced costs, nondeterminism beyond
tolerance, and golden expectations generated by the evaluator itself. Invoke:

```text
research-os --project ABS certify-evaluator /ABS/OUTSIDE/REVIEW.json
```

Research OS validates the review and manages
`.research-os/evaluator-certification.json`. The managed artifact is gitignored
and excluded from source snapshots and workspaces; never hand-edit it or declare
it mutable, protected, or evidence. It binds the full current constitution,
protected/evidence/environment fingerprint objects, the adapter-reported
fingerprint and effective compatibility seal observed by `doctor`, and canonical
agent-spec digest (brief plus candidate schema), as well as review and artifact digests.
Keep reviewed scientific inputs in their proper protected/evidence surfaces. Any
bound change makes certification non-current and requires a new independent
review.

## Graph phase and metadata discipline

`graph_action` and `scientific_change` are top-level Research OS experiment
metadata supplied through CLI flags. Do not require them inside the project-owned
candidate JSON schema. A project may separately carry richer hypothesis metadata.

| Phase | Experiment? | Parent rule | Required decision |
| --- | --- | --- | --- |
| `explore` | Yes | No parent | Independent root in a pre-registered class. |
| Diagnose | No | Inspect the completed node | State observed mechanism/failure and evidence. |
| `ablate` | Yes | Compatible completed parent | Remove/isolate one uncertain mechanism. |
| `exploit` | Yes | Compatible completed parent | Improve one already-supported mechanism. |
| `replicate` | Yes | Compatible completed parent | Apply one pre-registered controlled variation without tuning. |

The `scientific_change` declaration must name the hypothesis class and the whole
conceptual intervention, for example:

```text
CLASS: cross-sectional momentum; CHANGE: replace absolute entry rank with a
sector-neutral rank while keeping holding, exits, costs, and universe fixed
```

Compare the complete candidate with its parent before submission. One conceptual
intervention may require coupled fields only when separating them would make the
mechanism undefined; say why. Otherwise split the work. Undeclared differences,
unrelated parameter bundles, and cosmetic duplicate avoidance are invalid
proposals. `explore` must have no parent; every other graph action must have a
scientifically defensible compatible parent. A retry repeats the original
candidate and is not a graph-phase transition. Omit `--graph-action` and
`--scientific-change`; Research OS inherits both exactly from the immediately
prior attempt and refuses relabeling.

## Diagnosis and repeated-class closure

After every terminal attempt, diagnose before proposing again:

1. quote the exact status and reason code;
2. compare the primary metric with the compatible baseline and threshold;
3. identify failed constraints and inspect only relevant artifacts;
4. classify the outcome as mechanism, implementation, evidence, constraint, or
   operational failure;
5. state what evidence would falsify the diagnosis.

Only scientifically conclusive `REJECTED` nodes under the same compatibility
count against a hypothesis class. Do not count `INVALID_EXPERIMENT`,
`INSUFFICIENT_EVIDENCE`, `INFRA_FAILED`, `TIMED_OUT`, `CANCELLED`, or `UNTRUSTED`.
When the pre-registered threshold is reached, close the class and run no fourth
variant when the default threshold of three applies. Prefer an untouched
pre-registered class. Do not silently widen the candidate language to keep the
loop alive.

## Durable branch conclusions

At repeated-class closure and after a materially supported replicated branch,
record the diagnosis as an evidence-bound finding. Write exactly this object,
with no extra fields, to the snapshot-excluded transient inbox:

```json
{
  "branch_experiment_ids": ["exp_..."],
  "hypothesis_class": "pre-registered class",
  "failure_signature": "shared failure, or NONE for supported evidence",
  "conclusion": "bounded evidence-backed interpretation",
  "confidence": "falsified",
  "next_step": "explore"
}
```

`branch_experiment_ids` must be a non-empty duplicate-free array of terminal
experiments from one compatibility generation. `hypothesis_class`,
`failure_signature`, and `conclusion` are non-empty strings. `confidence` is
exactly one of `supported`, `falsified`, or `inconclusive`; `next_step` is exactly
one of `stop`, `change_control`, `explore`, `ablate`, `exploit`, or `replicate`.

Use `.research-os/candidate.inbox.json` as the transient conclusion input so
writing the object does not stale the context token, then invoke:

```text
research-os --project ABS conclude-branch \
  ABS/.research-os/candidate.inbox.json --context-token TOKEN
```

The command binds the interpretation to canonical terminal event IDs and hashes.
It does not authorize production action. Refresh `agent-context` afterward
because the new finding advances canonical state.

Enter explicit change-control when a discovered defect or next defensible idea
would change the evaluator, adapter semantics, golden oracle, universe, selection
rule, split, holdout boundary, evidence, costs, metric, constraints, candidate
schema, or immutable policy. Obtain user approval for the semantic change, retain
the old graph as its own evidence generation, update the protected contract,
repeat golden cases, submit a new independent `certify-evaluator /ABS/OUTSIDE/REVIEW.json
--replace` review, and seal a new compatible baseline before research resumes.

For terminal status handling and retry eligibility, follow
[status-actions.md](status-actions.md).

## Program memory disposition protocol (v0.4.0)

A Proposal knowledge disposition is an immutable ProgramLog companion to one
canonical typed Proposal registration. It binds the Proposal ID/digest,
generation, hypothesis class, evaluation scope, combined Context v3 token,
Program head, retrieval query digest, and retrieval result digest. Its sorted
entries cover every returned active or contradiction Claim exactly once and
carry the exact Claim digest, retrieval role, relation IDs, Proposal field
references, bounded rationale, and literal-null authority. `used` applies only
to active hits, `rejected` only to contradiction hits with their relation refs,
and `not_applicable` only to active hits with an exact bounded reason code.

Before append, recompute Context retrieval from the current Claim snapshot and
verify the Proposal exists in canonical project registration replay. ProgramLog
replay repeats retrieval at the referenced prefix. Any missing, duplicate,
unknown, stale, forged, extra, or non-null field fails before write. Untyped
legacy input is never semantically inferred: record only source metadata,
content SHA-256 and size, literal `legacy_unstructured`, and an empty typed-Claim
list. Raw legacy content is not part of ProgramLog. Neither record authorizes
deployment, merge, release, capital allocation, or trading.
