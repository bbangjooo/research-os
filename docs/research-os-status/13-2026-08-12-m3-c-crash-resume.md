# §13 — M3-C crash-resume and authority closure (2026-08-12)

> Status: **ADVANCE 5/5 — critic Attempt 2 PASS; audit Attempt 1 FAIL correction active**
> Previous phase: [§12](12-2026-08-12-m3-b-finite-autonomy-loop.md)
> Active milestone: `M3-C`; M3-D blocked

## 13.0 TL;DR

M3-C turns M3-B's durable pending markers into exact crash recovery. Diagnosis/synthesis provider output is
captured in AutonomyLog before ProjectLog/ProgramLog side effects, so a restart never asks a nondeterministic
provider to recreate already-used truth. Thirteen frozen cutpoints must cold-restart to the same terminal episode,
with one terminal/disposition/Diagnosis/origin/Claim each, stale heads fail-closed, recursive authority null, and
deploy/merge/trade operation surface zero. The frozen result is `31/31`; focused/adjacent evidence passes. Critic
Attempt 1 exposed a lookup→append race witness gap; three exploratory interleavings now fail closed without controller
writes. Critic Attempt 2 passed; audit Attempt 1 found only ledger defects, so M3-D remains blocked by re-audit.

## 13.1 Scope, anchors, and exclusions

- **§북극성:** move NS5 from nominal `7/7` to crash-safe completion for all frozen incomplete boundaries;
  preserve NS1 authority/direct-operation zero. NS6/NS7 do not move.
- **§종착지 §8.4:** sharpen `Autonomy` from finite episode to restartable single-agent episode. Context and
  Program memory receive recovery-consumer evidence, not a rating increase.
- **Milestone:** close all five M3-C conjuncts. M3-B is closed at `08327ad`; no gate bypass.
- Out of scope: unseen 36-episode quality, v0.2 comparator, external project write/migration, product multi-agent,
  embedded model SDK, deploy/merge/trade execution, version 0.5.0 release.

## 13.2 Recovery contract and truth boundaries

M3-B already commits `provider_call_started` before provider I/O and `experiment_started` before the sealed
ResearchService call. M3-C adds one generic value-only `provider_output_captured.v1` event for diagnosis and
synthesis. It binds call ID/kind, stored request digest, normalized output and output digest, recursively null
authority. The reducer retains the captured value while the call remains pending; the existing linked event clears
both. Proposal uses existing `proposal_returned.v1`, which is already a durable output capture.

```text
pending provider call ── output captured ── truth-owner append/reuse ── linked
                              │                       │
                              │                       ├─ ProjectLog: terminal / Diagnosis
                              │                       └─ ProgramLog: disposition / origin / Claim
                              └─ AutonomyLog value only; never scientific authority
```

Recovery derives only from the three verified logs:

1. **Pending provider, no capture:** revalidate the stored request against current Context/Program head, invoke
   once without a second reservation, then durably capture or reject under the original call ID.
2. **Captured diagnosis/synthesis:** never reinvoke provider; parse the captured packet and continue exact
   truth-owner reconciliation.
3. **Started experiment:** locate zero or one exact registration/terminal by packet Proposal, candidate digest,
   generation/scope and terminal binding. Zero means call `ResearchService.run_once` once; one terminal means
   reconstruct the exact service summary; mismatch or multiplicity fails closed.
4. **Truth append already committed:** find and verify the exact disposition/Diagnosis/origin/Claim and its event;
   reuse it. Absence appends once. A mismatching same semantic ID is evidence-invalid, never overwritten.
5. **Derived next/stop before append:** rebuild from current canonical heads and append once; no external side
   effect exists to reconcile.

No recovery event may edit ProjectLog or ProgramLog directly. The controller still calls only ResearchService and
ProgramStore public boundaries; it never calls adapter/workspace, and provider receives only frozen JSON values.

## 13.3 Fault model and frozen measurement

A protected no-op checkpoint method marks the 13 post-commit/pre-link boundaries. Tests subclass the loop and
raise a process-death sentinel exactly once; a new loop/service/store instance then opens the same three logs.
The sentinel is not caught by production recovery code. Tests must compare cold final state/summary and exact raw
truth-owner counts, not same-object continuation.

Fixture: `tests/fixtures/autonomy/v1/m3c-manifest.json`; raw SHA-256:
`c3752c811e44cebd7c542a3653ee19c8c5d2b2b7c1daf11a9a11b23565e27c7b`.

| Gate | Literal denominator | Expected |
|---|---:|---:|
| cold crash-resume cutpoints | 13 | `13/13`, exact terminal state/summary; no budget recharge |
| duplicate truth suppression | 5 | terminal/disposition/Diagnosis/origin/Claim count `1` each |
| stale generation/program/evidence | 4 | `4/4` exact code; forbidden Project/Program write `0/0` |
| recursive null authority | 6 | `6/6`, non-null count `0` |
| deploy/merge/trade operation surface | 3 | callable surface count `0/0/0` |
| total | 31 | every literal ID consumed once; no extras |

Observed M3-C result: `(13/13) ∧ (duplicate five = 0) ∧ (stale 4/4) ∧ (authority 6/6) ∧
(operation surface 3/3 zero)`. All five conjuncts pass together; critic PASS is recorded and audit remains pending.

## 13.4 Stale-head and stop semantics

- A pending proposal request whose stored ProgramSnapshot/head is no longer current is rejected before provider
  reinvocation with `AUTONOMY_RECOVERY_STALE`; Project/Program delta stays `0/0`.
- A started but unregistered experiment whose Study generation changed is stopped incomplete with the same stable
  code and no ResearchService call. An observed registration/terminal with mismatching Proposal/candidate/
  generation/scope raises `AUTONOMY_RECOVERY_EVIDENCE_INVALID` and writes nothing to ProgramLog.
- A captured synthesis whose stored ProgramSnapshot is stale cannot append its Claim. It is rejected and stops
  incomplete; an already exact Claim may only be reused if it was committed on the captured request's head.
- Recovery never refunds or recharges reservations. Exact stop precedence remains M3-B's
  closed/study→experiment→provider→invalid→token→time after the pending step is reconciled.

## 13.5 Duplicate and authority proof

The final cold stream must contain exactly one semantic terminal, disposition, Diagnosis, origin and Claim for the
episode. Autonomy linking events also remain single. Repeating `advance(expected_phase=old_phase)` after recovery is
a no-op with Project/Program/Autonomy deltas `0/0/0`.

All newly captured payloads, state serialization, requests/packets, Context, linked refs and Claims are scanned
recursively for non-null `authorized_action`. The `research_os.autonomy` public surface and controller call graph
are inspected for callable deploy/merge/trade operations; text in errors/tests does not count as a callable.

## 13.6 Bounded plan and pre-score

- Product: `autonomy/loop.py` plus at most one compact `autonomy/recovery.py`; `<=900` added/churn lines.
- Tests+fixture: one literal-handler `test_m3c_crash_resume.py`; `<=1,400` lines.
- Phase+critic+receipt+audit docs `<=500`; inclusive cycle `<=2,800`.
- M3-B footprint finding decision: **retain** the audited `2,043` behavior, extract/refactor recovery helpers rather
  than expanding the monolith where practical, and do not weaken any M3-B conjunct. M3-C product cap is the
  confirmatory follow-up; result will be reported as met/missed, not silently rebaselined.
- Order: this pre-spec+fixture hash commit → independent critic questions → product/tests → frozen/focused/adjacent
  (no full) → critic verify → paired sync → independent seven-pass audit. Full suite remains M3-D code-freeze work.

Strongest failure hypothesis: a restart may appear successful while re-invoking a provider after its output already
changed Project/Program truth, duplicating a terminal/Claim, or using current heads to legitimize a stale captured
decision. Durable output capture, exact source reconciliation and one-factor stale mutations must refute it.

### 13.6.4 Milestone progress claim

**Current label: `ADVANCE`; M3-C engineering `5/5`; no `CLOSE` before critic and audit both pass.**

| M3-C exit conjunct | Previous | Required after phase | Evidence target |
|---|---:|---:|---|
| incomplete-step crash resume | M3-B raises `AUTONOMY_INCOMPLETE_STEP` | `13/13` PASS | frozen handler; new service/store/loop cold-open |
| duplicate terminal/Diagnosis/Claim | unmeasured | five semantic counts exactly `1` PASS | three-log raw/source reconciliation |
| stale generation/program head | unmeasured | `4/4` fail-closed PASS | one-factor mutations; write delta `0/0` |
| recursive authority null | M3-B nominal zero | `6/6` PASS | recursive scans plus exploratory forged rejects |
| deploy/merge/trade surface | nominal zero | `3/3` zero PASS | AST reachable calls plus injected-method witness |

- **Prerequisite gate:** M3-B closed at `08327ad`; M1/M2/M3-A are closed. No bypass.
- M3-D remains blocked until M3-C critic and progress audit both PASS.

### 13.6.5 End-state delta

**Classification: `구체화·검증`.** Before: an incomplete provider/service marker could not resume. After: every
frozen marker cold-restarts from canonical logs without duplicate truth, head laundering or new authority. Context
and Program memory ratings do not move; external billing exactly-once, distributed consensus, learning quality and
unseen release evidence remain absent.

### 13.6.6 Intent-execution reconciliation

- **Intent (§13.1; NS1/NS5):** source = approved M3-C chain and frozen manifest; sample = 13 incomplete boundaries,
  four stale cases, six authority rows and three forbidden operations; measurement = cold restart, no duplicate truth,
  fail-closed stale state and zero authority/operation calls, with M3-D/NS6/NS7 excluded.
- **Execution (§13.2~§13.6; NS1/NS5):** source = three canonical logs plus public service/store boundaries; sample =
  frozen `31` and exploratory capture/service/race/authority witnesses; measurement = `31/31`, race `3/3`, focused
  `41`, adjacent `142`, product/test caps PASS, external billing/hostile-provider/distributed quality unclaimed.

**Label: `MATCH`.** The executed sample and measurements implement exactly that intent without changing M3-D
thresholds, external migration timing, multi-agent gate, or product authorization policy.

### 13.6.7 Claim mode

**Label: `MIXED`.** Pre-spec `22190bf` (`06:14:30+09:00`) and critic questions `5291945` precede first product/data
`7394246` (`06:37:22+09:00`); manifest SHA remains `c3752c…65e27c7b`.

| evidence | mode | result |
|---|---|---|
| frozen 31 IDs, five conjuncts, stale codes and caps | `CONFIRMATORY` | `31/31`; corrected product `353/900`; tests+fixture `829/1,400` |
| nondeterministic pre/post capture `4/4` | `EXPLORATORY` | pre-capture reinvoke one; post-capture zero; truth count one |
| actual service registration-without-terminal | `EXPLORATORY` | one `RECOVERED_INTERRUPTED_RUN` terminal after cold reopen |
| forged nested authority and injected forbidden methods | `EXPLORATORY` | rejected before commit; calls `0/0/0` |
| lookup→append/service race interleavings | `EXPLORATORY` | generation/disposition/Claim `3/3` stable stale code; post-writer controller delta `0/0` |

### 13.6.8 Requirement-result divergence

**`GENUINE-FINDING` / EXPLORATORY correction.** Frozen denominator, codes, outcomes and caps match the pre-spec.
Critic Attempt 1 showed that the claimed Q3 counterfactual mutated before recovery rather than between lookup and
guarded append. A real interleaving also exposed a boundary exception that needed translation to
`AUTONOMY_RECOVERY_STALE`. The product seam and three exploratory witnesses were added without changing the frozen
31 or requirement. This is not fixture contamination (`RESULT-INVALID`) or a faulty requirement
(`REQUIREMENT-WRONG`); re-verification and audit remain mandatory.

## 13.7 Residual issues

- Exactly-once external provider billing is not claimed; recovery can reinvoke only when no output was durably
  captured, while episode reservation is charged once.
- A Python provider remains cooperative code, not a hostile-code sandbox.
- Cross-host distributed consensus and multi-agent scheduling remain out of scope.
- M3-D alone measures whether restartable autonomy actually selects better hypotheses under fixed budget.

## 13.10 Next action

Corrected re-audit must PASS before `CLOSE` and M3-D activation. The M3-D code-freeze pre-spec must also commit a
`race-confirmation-v1` generator before nonce reveal: a fresh 256-bit nonce selects 12 subprocess schedules (four
each for experiment lookup→service, disposition lookup→append, Claim lookup→append). Confirmatory PASS requires
`12/12` stable stale code, restarted provider/service call `0`, controller Project/Program delta `0/0`, unchanged
truth counts, and no product/policy edit after nonce reveal.
