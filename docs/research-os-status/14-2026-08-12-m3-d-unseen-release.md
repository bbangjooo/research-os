# §14 — M3-D unseen benchmark and v0.5 release (2026-08-12)

> Status: **PRE-SPEC — 0/8; no acceptance nonce/body exists**
> Previous phase: [§13](13-2026-08-12-m3-c-crash-resume.md) (`CLOSED 5/5` at `7b00e0b`)
> Active milestone: `M3-D`; product multi-agent and live migration remain blocked

## 14.0 TL;DR

M3-D is the sole remaining v0.5 milestone. It must compare a byte-fixed v0.2 arm with the frozen v0.5 single-agent
system on 36 post-freeze unseen synthetic episodes, pass protocol/evidence/choice/terminal/waste gates, confirm three
external projects read-only, and ship one 0.5.0 release gate. This commit freezes the generator/oracle/metric contract
only. It intentionally creates no nonce, episode body, result, version change or release claim.

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
`3f7e010a79106140fb311578300af4cda5b43e87fa8a5e813e9bc1c6959ff46c`. It fixes six families × six episodes,
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
| 2 | frozen protocol attack manifest whole-universe block rate | `0/1`; pipeline path is currently absent |
| 3 | v0.5 evidence-bound conclusion | `0/36`, required `36/36` |
| 4 | v0.5 closed-class retry | unmeasured, required `0` |
| 5 | next-choice accuracy | unmeasured, required `v0.5 ≥ min(90%, v0.2+20%p)` |
| 6 | terminal accuracy | unmeasured, required `v0.5 ≥ min(90%, v0.2+20%p)` |
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
6. In a repo-external temporary directory create `secrets.token_hex(32)`, generate 36 bodies and 12 race schedules,
   then seal code/generator/v0.2/nonce commitment/suite digests before either arm runs.
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
- The missing `tests/fixtures/protocol_attacks/v1/manifest.json` is a pre-result
  **GENUINE-FINDING** in the planned evidence surface. M3-D must create/freeze executable literal rows before nonce;
  it may not retroactively pretend M3-A's rejection count was that manifest.
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

**Current label: `ADVANCE 0/8`.** M3-D exists and M3-C is closed, but no engineering or release conjunct is claimed.
Product multi-agent remains prohibited until NS6 passes; live pilot/migration remains post-v0.5.

### 14.6.5 End-state delta

**Classification: `구체화` (planned).** Before: restartable autonomy exists but learning quality is unmeasured. After
the phase only if all gates pass: operators can compare v0.2/v0.5 choice, terminal correctness and waste on sealed
unseen worlds and install 0.5.0 without mutating prior projects. No other stage rating moves.

### 14.6.6 Intent-execution reconciliation

- **Intent (§14.1; NS1/NS6/NS7):** source = approved unseen-release gate and pipeline §7/§9.4; sample = 36 unseen,
  protocol attack universe, six public-boundary E2E, three external snapshots; measurement = the eight AND gates.
- **Execution:** no result yet; only the generator/oracle/metric/custody specification is frozen.

**Label: `MATCH` for pre-spec scope only.** Result matching is deliberately unclaimed.

### 14.6.7 Claim mode

**Planned `MIXED`.** Generator/world/oracle/metric precede implementation and nonce, so frozen rows and future body
results remain CONFIRMATORY if custody holds. The critic-driven no-leak, full-v0.2, anti-vacuity and non-empty external
selection corrections are EXPLORATORY and cannot be relabeled.

### 14.6.8 Requirement-result divergence

No result exists. Future fixture/runner corruption is `RESULT-INVALID`; a defective oracle/metric is
`REQUIREMENT-WRONG`; a valid quality/cap/compatibility miss is `GENUINE-FINDING` and blocks release. Results are never
silently regenerated or relabeled.

## 14.7 Residual limitations

- Synthetic worlds test deterministic learning-state use, not open-domain scientific creativity or model quality.
- The v0.2 packaged-skill arm is a frozen historical comparator, not a claim about every possible v0.2 LLM.
- Actual external validation is read-only compatibility, not production pilot, data migration or write enablement.

## 14.10 Next action

Commit this manifest/phase, record SHA/timestamps, then obtain independent M3-D critic questions. Do not implement the
generator or create a nonce/body before that critic artifact is committed.

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
independent critic PASS. Thresholds and the eight release conjuncts are unchanged. Product multi-agent, live
migration, and acceptance preparation remain prohibited until that PASS.
