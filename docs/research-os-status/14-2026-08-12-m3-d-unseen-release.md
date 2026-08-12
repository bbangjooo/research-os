# §14 — M3-D unseen benchmark and v0.5 release (2026-08-12)

> Status: **ACCEPTANCE ATTEMPT 1 RESULT-INVALID — 0/8; critic Attempt 4 FAIL preserved; path-corrected candidate pending Attempt 5**
> Previous phase: [§13](13-2026-08-12-m3-c-crash-resume.md) (`CLOSED 5/5` at `7b00e0b`)
> Active milestone: `M3-D`; product multi-agent and live migration remain blocked

## 14.0 TL;DR

M3-D is the sole remaining v0.5 milestone. It must compare a byte-fixed v0.2 arm with the frozen v0.5 single-agent
system on 36 post-freeze unseen synthetic episodes, pass protocol/evidence/choice/terminal/waste gates, confirm three
external projects read-only, and ship one 0.5.0 release gate. The initial pre-spec froze the generator/oracle/metric;
the corrected harness received critic Attempt 3 PASS and drew one externally custodied suite. The run was
`RESULT-INVALID` because a chronology test inspected the post-draw working tree instead of the sealed code commit.
That draw is immutable, archived, and prohibited from rerun; it makes no quality or release claim.

## 14.1 Intent, scope, and prerequisites

- **§북극성:** close NS6 without weakening NS1/NS5/NS7. The target is improved next-hypothesis choice and fixed-budget
  efficiency, not merely loop completion or more nodes.
- **§종착지 §8.4:** move Meta-evaluation from absent to paired unseen evidence and Compatibility from synthetic-only to
  actual read-only `3/3`; Autonomy code/rating stays frozen after M3-C.
- **Prerequisite:** M3-C critic Attempt 2 and corrected audit Attempt 2 PASS; M1/M2/M3-A/B/C closed.
- **Out of scope:** external project writes/live migration, multi-agent product behavior, hostile-provider sandbox,
  distributed execution, deploy/merge/trade, real capital or live trading.
- Binance has only nested Research OS roots. The pre-result rule selects a non-empty root with maximum complete event
  count, then lexicographic path on ties; this fixes `research/research-os/polymarket-profit-g2/.research-os`
  (`32` rows observed versus two `0`-row roots). No root `.research-os` is invented.

## 14.2 Precommitted generator and arm contract

Frozen spec path: `tests/fixtures/meta_evaluation/v1/generator-manifest.json`; raw SHA-256
initial `3f7e010a79106140fb311578300af4cda5b43e87fa8a5e813e9bc1c6959ff46c`, corrected operative
`dd767fcb787aa44cdf1c5aaad851f5556205bbd5143ccde169cbf469066e04a3`. It fixes six families × six episodes,
candidate language, same selector/budget rule, v0.2 commit
`6f36a1b97cf8bc3c5925a3b35f0b189d82f6bcb6`, v0.5 visible surface, hidden-field prohibitions, transition/oracle
rules, metric formulas, receipt custody and `race-confirmation-v1` before any acceptance body exists. Critic-driven
pre-implementation corrections remove `oracle_rank_if_visible`, retain the complete historical Context v2 mapping,
make zero baseline waste an anti-vacuity failure, and select a non-empty Binance boundary; the updated SHA below is
the operative frozen contract.

The v0.2 and v0.5 arms receive the identical hidden world, candidate list, experiment budget, deterministic selector
and tie break. Only their documented context surfaces differ. The comparator must prove by trace that no v0.5 typed
class/memory/recovery field enters v0.2 and no hidden/oracle field enters either arm.

## 14.3 Eight conjuncts and exact thresholds

| # | exit conjunct | pre-result state |
|---:|---|---|
| 1 | precommitted generator + post-freeze 256-bit nonce + pre-arm receipt seal + exact 36 bodies | `0/1` |
| 2 | frozen protocol attack manifest whole-universe block rate | development `24/24`; sealed acceptance `0/1` |
| 3 | v0.5 evidence-bound conclusion | `0/36`, required `36/36` |
| 4 | v0.5 closed-class retry | unmeasured, required `0` |
| 5 | next-choice accuracy | unmeasured, required `v0.5 ≥ max(v0.2, min(90%, v0.2+20%p))` |
| 6 | terminal accuracy | unmeasured, required `v0.5 ≥ max(v0.2, min(90%, v0.2+20%p))` |
| 7 | positive-waste aggregate | unmeasured, required `≤70%`; each v0.2-zero episode requires v0.5 zero |
| 8 | NS7 actual read-only `3/3` + opaque `3/3` + writer delta zero + 0.5.0 docs/version/upgrades/wheel/full | `0/1` |

No conjunct can compensate for another. A quality miss cannot be waived by regression PASS; a release cannot be
called v0.5 while a threshold is unmet.

## 14.4 Custody and anti-leak sequence

1. Commit this pre-spec and generator manifest; record raw SHA and confirm there is no acceptance body/nonce.
2. Obtain independent critic questions before generator/comparator/attack/release implementation.
3. Implement generator, common selector, two context adapters, oracle, attack manifest, pure tests and representative
   public-boundary E2E without generating the 36 acceptance bodies.
4. Independent critic verifies proxy-vs-real, arm symmetry, hidden-field isolation, metric arithmetic and custody.
5. Freeze all product/policy/generator/oracle/metric bytes in one code checkpoint.
6. In the repo-external fixed path `~/.research-os-custody/m3d-v05/<code-commit>`, atomically persist
   `reserved-before-nonce`, call `secrets.token_hex(32)` once, generate 36 bodies and 12 race schedules, then seal
   code/generator/v0.2/nonce commitment/suite digests before either arm runs.
7. Run both arms once, actual external read-only checks, release/upgrades/full suite; append one immutable receipt.
8. Any post-result relevant byte change invalidates—not edits—the receipt and requires a new pre-spec/nonce cycle.

Raw nonce is never accepted from an implementer-selected fixture. Its commitment and generated suite may be
published after the pre-arm seal so an independent auditor can reproduce the body and oracle.

## 14.5 Required executable surfaces

- Pure generator/comparator should be a test/release seam, not product autonomy policy and not a hidden LLM SDK.
- v0.5 evidence paths must be material: mutation/removal of ClassState, relation/status/retrieval reason or recovery
  head must change the selected action or fail the gate in the applicable family.
- Representative E2E uses actual public ResearchService/ProgramStore/autonomy boundaries where the family permits;
  a pure function calling itself is not sufficient.
- The initially missing `tests/fixtures/protocol_attacks/v1/manifest.json` was a pre-result
  **GENUINE-FINDING** in the planned evidence surface. M3-D now owns and freezes executable literal rows before nonce;
  it does not retroactively treat M3-A's rejection count as that manifest.
- External checks snapshot bytes, modes and symlink targets before and after. They never open SQLite writable, invoke
  adapters, install skills into those projects, or infer typed meaning from opaque text.

## 14.6 Bounded plan and pre-score

- Benchmark/generator/release script additions or churn: `<=1,800` lines.
- Tests + generator/attack/release fixtures, excluding generated 36 bodies: `<=2,400` lines.
- Generated acceptance body: `<=1,200` lines; phase+critic+receipt+audit: `<=800` lines.
- Inclusive M3-D cap: `<=6,000` churn/lines under the category convention; full suite latency is reported separately.
- No acceptance result may cause a cap or threshold rebaseline.

Strongest failure hypothesis: the comparator will appear to prove learning because the v0.5 arm sees an answer-like
field, the v0.2 arm is artificially crippled, or episode bodies/thresholds are tuned after results. The common
selector, hidden-field scans, material-ablation tests, fixed v0.2 bytes, post-freeze nonce and immutable receipt must
refute all five routes.

### 14.6.4 Milestone progress claim

**Current label: `ADVANCE 0/8`.** M3-D exists and M3-C is closed, but Attempt 1 was `RESULT-INVALID`; no engineering
or release conjunct is claimed.
Product multi-agent remains prohibited until NS6 passes; live pilot/migration remains post-v0.5.

### 14.6.5 End-state delta

**Classification: `구체화` (planned).** Before: restartable autonomy exists but learning quality is unmeasured. After
the phase only if all gates pass: operators can compare v0.2/v0.5 choice, terminal correctness and waste on sealed
unseen worlds and install 0.5.0 without mutating prior projects. No other stage rating moves.

### 14.6.6 Intent-execution reconciliation

- **Intent (§14.1; NS1/NS6/NS7):** source = approved unseen-release gate and pipeline §7/§9.4; sample = 36 unseen,
  protocol attack universe, six public-boundary E2E, three external snapshots; measurement = the eight AND gates.
- **Execution:** the corrected generator/comparator/public-boundary/protocol/custody implementation exists and has
  development evidence. One unseen draw exists only as immutable invalid-attempt evidence; no valid unseen result exists.

**Label: `MATCH` for pre-spec scope only.** Result matching is deliberately unclaimed.

### 14.6.7 Claim mode

**`MIXED`.** Generator/world/oracle/metric preceded Attempt 1, but its body result is unusable because the release
conjunction did not complete. The chronology correction is EXPLORATORY. A future new-nonce result may remain
CONFIRMATORY only against a newly sealed clean code checkpoint; Attempt 1 is never relabeled.

### 14.6.8 Requirement-result divergence

No valid result exists. Attempt 1 fixture/runner chronology failure is `RESULT-INVALID`; a defective oracle/metric is
`REQUIREMENT-WRONG`; a valid quality/cap/compatibility miss is `GENUINE-FINDING` and blocks release. Results are never
silently regenerated or relabeled.

The corrected pre-unseen implementation already has one engineering divergence: benchmark/generator/release-script
churn is `2,349/1,800`, while tests+fixtures are `1,696/2,400`, phase+critic evidence is `455/800`, and inclusive
M3-D churn is `4,707/6,000`. This is a `GENUINE-FINDING`/EXPLORATORY subtarget miss, not permission to weaken an
eight-gate threshold or the inclusive cap. The exact inclusive count is frozen in status §13 at the checkpoint.

## 14.7 Residual limitations

- Synthetic worlds test deterministic learning-state use, not open-domain scientific creativity or model quality.
- The v0.2 packaged-skill arm is a frozen historical comparator, not a claim about every possible v0.2 LLM.
- Actual external validation is read-only compatibility, not production pilot, data migration or write enablement.

## 14.10 Next action

Validate the path-corrected chronology proof and commit it at a clean checkpoint, then obtain independent critic
Attempt 5. Only after PASS may a new external custody path draw a new nonce
exactly once. Never rerun or reconstruct Attempt 1.

## 14.11 Pre-unseen critic Attempt 1 FAIL and correction contract

Checkpoint `0fa3a6c` implemented the first complete release harness, but independent critic Attempt 1 at `f21ba61`
returned **FAIL** before any acceptance draw. The failure is preserved and no nonce, generated acceptance body,
pre-arm seal, custody transcript, arm result, or final receipt exists. External read-only compatibility alone is
DIRECT (`1/15/32` events, replay/opaque/no-write `3/3`); the other release conjuncts remain unclaimed.

The correction is pre-result and must replace, not relabel, the defective evidence:

1. Separate hidden-world generation, public observation rendering, and oracle derivation. v0.5 selection consumes
   real `ClassState`, `RetrievalResult`/Context v3, and autonomy-state serialization; six generated representative
   episodes cross their actual nearest public boundary and check terminal/evidence/ref against the isolated oracle.
2. Execute the exact `6f36a1b` Context v2 builder in a temporary archived checkout. The byte-fixed v0.2 packaged
   skill must materially bind the common selector policy; current code may not stand in for historical execution.
3. Add semantic action/priority/ID permutation and oracle-mutation isolation so literal hidden-key absence cannot
   substitute for anti-gaming evidence.
4. Move nonce ownership to a separate repository-external custodian. It atomically reserves one deterministic
   code-commit path before calling `secrets.token_hex(32)`; a crash or repeated invocation remains durably blocked.
5. Make selected actions drive trajectory. Wrong/early terminal choices omit the remaining fixed decision points,
   wrong experiments count as waste, and v0.5 must also be non-regressive when v0.2 already exceeds 90%.
6. Replace the imported M3-A handler table with M3-D-owned literal handlers over public validators and an actual
   `AutonomyEpisodeLog`; replace historical-node-only boundary evidence with generated-episode E2E `6/6`.
7. Run only the seven parametrized upgrade/rollback rows in the release verifier. Correct the discovered current
   full-suite legacy-v1 `run_once` shape regression without changing the frozen historical oracle.

All changed generator/oracle/metric/attack/release bytes require a new clean pre-nonce checkpoint and a second
independent critic PASS. The defective `min(90%, baseline+20%p)` formula was tightened pre-nonce with the intended
non-regression conjunct; no gate was weakened and the eight release conjuncts are unchanged. Product multi-agent, live
migration, and acceptance preparation remain prohibited until that PASS.

## 14.12 Corrected pre-unseen implementation candidate

The Attempt 1 correction contract is now implemented but not yet independently accepted:

- hidden decision state, public observation rendering, and oracle derivation are separate; oracle-only mutation leaves
  selector bytes unchanged. Candidate arrays/IDs and reversed action priority do not change exact v0.5 choices.
- v0.5 public evidence is produced by actual `ClassState.to_dict()`, `retrieve_claims(ClaimSnapshot, query)`,
  `ProposalKnowledgeDisposition.to_dict()`, and `AutonomyEpisodeState.to_dict()` boundaries. Generated family E2E is
  literal `6/6`; removal, class-ID permutation, and contradiction attacks are material `6/6` per family/mutation.
- v0.2 executes the exact archived `6f36a1b` Context builder in an isolated subprocess and binds the byte-fixed skill
  digest into the common selector policy. Current `build_agent_context` is not the historical execution path.
- M3-D owns its literal 24-row attack handler table; actual Project/Program/AutonomyLog no-write is `24/24`.
- custody has durable draw and arm-run reservations plus an immutable external result path. At the Attempt 3 critic
  checkpoint none had been invoked; the later single invocation is preserved as Attempt 1 in §14.15.
- the legacy `run_once` return surface again matches the frozen v1/M1-B observer, while canonical terminal events keep
  captured artifact digest/size evidence.

Current executable evidence before the Q4-only correction: M3-D focused `63/63`, adjacent M3-A/B/C `142/142`, full
`921+115` in `1195.61s`, targeted legacy parity `1/1`, actual ResearchService/autonomy evidence `1/1`, Ruff, ty, and
`git diff --check` PASS. The Q4 correction's targeted durability tests pass `2/2`. After the Attempt 1 chronology
correction, current focused is `64/64`, collection is `922`, and Ruff/ty/diff PASS. This remains engineering evidence:
Attempt 1 has no valid paired result or release receipt, and the independent final progress audit does not exist.
Therefore M3-D remains `ADVANCE 0/8`, product multi-agent/live migration stay blocked, and a new arm execution is
prohibited until a new clean checkpoint receives critic Attempt 5 PASS and distinct custody preparation is committed.

## 14.13 Critic Attempt 2 FAIL — Q4 crash durability correction

Attempt 2 independently closed Q1–Q3 and Q5–Q8 as DIRECT, but found that `draw-reservation.json` was file-fsynced
without fsyncing its checkpoint directory and custody parent before the nonce draw. A filesystem/power crash could
therefore lose the directory entry and permit a redraw. The pre-data correction now fsyncs the checkpoint directory
and custody parent after the exclusive reservation write and before `secrets.token_hex(32)`. The executable test
records both directory-sync events before the mocked nonce event and still rejects a second draw. No real custodian,
acceptance script, nonce, body, prearm seal or receipt was invoked.

## 14.14 Critic Attempt 3 PASS

Clean checkpoint `0388931` received independent **PASS** with Q1–Q8 all DIRECT. Q4 reproduced the exact exclusive
reservation→file fsync→checkpoint-directory fsync→custody-parent fsync→single nonce order; Q1–Q3/Q5–Q8 remained
byte-identical or hash-only manifest updates from their Attempt 2 DIRECT evidence. Targeted Q4+manifest `3/3`, complete
release-gate `10/10`, Ruff/ty/diff PASS, and checked-in acceptance artifacts `0/5` were independently confirmed. This
authorizes the one-draw acceptance chronology only; it does not claim any M3-D release conjunct or live authority.

## 14.15 Acceptance Attempt 1 `RESULT-INVALID`

The clean code checkpoint `a0ea755476880a0b337678af4e5e7a6b6cc999d2` was prepared exactly once under the
repository-external custody path
`/Users/bbangjo/.research-os-custody/m3d-v05/a0ea755476880a0b337678af4e5e7a6b6cc999d2`. Its pre-arm seal was
`86d60c8d2cf8b1143b59b891798619b00bf7aa6693b6c260aeca385a055314c4`; the four generated canonical
objects were committed at `604e1d01cef5e74383ecad11d6784340fdd7118d` before the arms ran.

The one-shot command completed with outer full-suite evidence `917 passed, 4 failed, 115 subtests`. All four failures
descended from `test_generator_manifest_is_precommitted_and_has_no_acceptance_body`: that test used a glob against the
post-draw working tree, so the valid presence of the checked-in suite/race body made its own chronology assertion fail.
The immutable external failure result has SHA-256
`9b67285b816648e3225f14b80d186367ca764cbcfe1233cd3318fcb7d92aaf80`. It records
`authorized_action=null`, `product_multi_agent=false`, and `live_migration=false`.

This is **not** a benchmark quality failure or pass. The benchmark had begun, but acceptance metrics were not persisted
through a complete release conjunction, so no accuracy, terminal, waste, compatibility, or release conjunct is inferred.
The same draw is never rerun. Its exact suite, race suite, prearm seal, and custody transcript are preserved under the
`failed-attempt-1-*` / `14-m3-d-attempt-1-*` names, with digests recorded in
`14-m3-d-attempt-1-failure-review.json`; the external reservation/result remains untouched.

The pre-data correction replaces current-working-tree absence with a direct Git proof: each generated body must be
absent at the prearm document's sealed `code_commit`. A dedicated archive test applies that proof to Attempt 1, so the
post-draw chronology is immediately executable instead of relying on a body-absence test that becomes false by design.
No generator, oracle, selector, metric threshold, v0.2 arm, or product policy changed. The correction requires focused
and static PASS, a new clean checkpoint, independent critic Attempt 5, and a distinct code-commit custody path/new nonce
before one new one-shot execution. M3-D remains `0/8`; product multi-agent and live migration remain blocked.

## 14.16 Critic Attempt 4 FAIL — historical path correction

Independent Attempt 4 verified Q1–Q3 and Q5–Q8 DIRECT but returned **FAIL** on Q4. The archived test proved that the
new `failed-attempt-1-*` names were absent at `a0ea755`, not that the two then-canonical `acceptance-suite.json` and
`acceptance-race-suite.json` paths were absent. Direct Git inspection confirmed the intended historical fact, but the
executable witness did not encode it and could false-pass at `604e1d0`, where canonical bodies existed while archive
names did not.

The minimum test-only correction now separates current artifact paths from sealed Git lookup paths: archived files
must exist under their preserved names, while `git cat-file` queries the historical canonical pair at the prearm code
commit. The current-draw path uses the same canonical pair for both roles. No product, generator, oracle, selector,
metric, threshold, historical arm, custodian, runner, or verifier byte changes. The bound manifest hash, focused/static
evidence, a new clean checkpoint, and independent Attempt 5 PASS are required before any new draw.
