# §12 — M3-B finite autonomous state machine (2026-08-12)

> Status: **IMPLEMENTED — independent critic verify pending**
> Previous phase: [§11](11-2026-08-12-m3-a-decision-packet.md)
> Active milestone: `M3-B`; M3-C/D blocked

## 12.0 TL;DR

M3-B는 M3-A의 value-only DecisionPacket을 실제 single-provider 연구 episode로 연결한다. 별도
append-only `AutonomyLog`가 orchestration state만 소유하고, 기존 Project EventLog는 evaluator/terminal/
Diagnosis, ProgramLog는 disposition/origin/Claim을 계속 소유한다. 제품 전에 literal 43-case manifest와
여섯 exit conjunct, fixed reservation budget, expected exact outcomes를 고정한다. M3-C crash injection과
M3-D unseen learning quality는 이 phase의 진척으로 세지 않는다.

## 12.1 Scope, three anchors, and exclusions

- **§북극성:** NS5 `0/7 → 7/7` nominal canonical transitions와 closed-class registration 0을 직접
  측정한다. NS1은 새 surface의 exact reject/no-authority regression만 유지한다. NS6/NS7은 움직이지 않는다.
- **§종착지 §8.4:** `Autonomy` 영역을 provider seam에서 finite episode로 **구체화·검증**한다.
  `Context`와 `Program memory`는 next-query read/write consumer evidence를 보강하지만 rating을 자동
  올리지 않는다.
- **Milestone:** 이 phase는 `M3-B` 여섯 conjunct 전체를 `CLOSE` 대상으로 삼는다. M3-A/parent M2는
  closed이며 gate bypass는 없다.
- 제품 multi-agent, distributed worker, embedded LLM SDK, deploy/merge/trade, 외부 세 프로젝트 write/
  migration, crash fault injection, code-freeze unseen benchmark, version 0.5.0은 범위 밖이다.

## 12.2 Canonical FSM and truth boundaries

Project EventLog에 loop bookkeeping을 먼저 append하면 M3-A가 bind한 project Context token을 자기 손으로
stale하게 만든다. ProgramLog에 넣어도 Program head가 stale한다. 따라서 orchestration은 별도 hash-chained
`AutonomyLog`에 기록하며 이 로그는 evaluator/scientific/claim truth를 복제하지 않고 exact refs만 가진다.

```text
AutonomyLog: context → proposal → preflight → run → diagnosis → synthesis → next/stop
                    │          │         │             │
                    │          │         │             └── ProgramLog Claim/ClassState ref
                    │          │         └── Project EventLog Diagnosis ref
                    │          └── sealed ResearchService terminal ref
                    └── M3-A DecisionPacket + M2 retrieval/disposition
```

Canonical event types:

1. `research_os.autonomy.episode_started.v1`
2. `research_os.autonomy.provider_call_started.v1`
3. `research_os.autonomy.proposal_returned.v1`
4. `research_os.autonomy.preflight_accepted.v1`
5. `research_os.autonomy.experiment_started.v1`
6. `research_os.autonomy.experiment_linked.v1`
7. `research_os.autonomy.diagnosis_linked.v1`
8. `research_os.autonomy.synthesis_linked.v1`
9. `research_os.autonomy.next_planned.v1`
10. `research_os.autonomy.stopped.v1`
11. `research_os.autonomy.provider_rejected.v1`

Every payload is exact-schema/versioned, recursively `authorized_action=null`, bound to one episode ID and
the prior AutonomyLog head. The pure reducer rejects illegal ordering, duplicate semantic transitions, cross-
episode refs, unknown unnamespaced events, and impossible budget arithmetic. Replaying the same three canonical
logs must derive the same state and terminal summary.

## 12.3 Provider-neutral stage contracts

- Existing `ProviderDecisionRequest/DecisionPacket v1` remains the proposal contract and is current-state
  revalidated before preflight.
- `ProviderDiagnosisRequest/Packet v1` contains only value data: episode/call/request IDs, exact terminal-bound
  Diagnosis template, Proposal/terminal refs, and null authority. The returned Diagnosis is still validated and
  appended only by `ResearchService.record_diagnosis`.
- `ProviderSynthesisRequest/Packet v1` contains the recorded Diagnosis, exact linked OriginEvidenceRef, derived
  ClassState ID/digest, current ProgramSnapshot, original retrieval/disposition, and allowed `next|stop` decision.
  It returns one evidence-bound Claim and either a logical next-query plan or a stop reason.
- One provider port invokes all three request schemas as immutable strict JSON values. It receives no service,
  store, log, adapter, workspace, filesystem path, callable, API key, deployment, or trading capability.
- `next` query identity/head is rebuilt by the kernel after the Claim append; provider-supplied stale Program
  identity is never trusted. The next Context v3 must contain exact current active/contradictory Claims/reasons.

## 12.4 Finite budget and stop semantics

`AutonomyPolicy v1` fixes positive maxima for experiments, provider calls, invalid packets, canonical token units,
and reserved elapsed milliseconds. Each provider call charges one fixed provider-call/token/time reservation in
`provider_call_started`; each experiment charges the active StudyContract's existing elapsed reservation in
`experiment_started`. A new cycle begins only if one experiment plus the proposal/diagnosis/synthesis three-call
completion reserve fits. Thus the loop cannot create a terminal experiment it lacks reserved interpretation/
synthesis capacity to finish.

- Canonical token unit = `ceil(canonical request-or-response UTF-8 bytes / 4)`; this is a provider-neutral
  finiteness/accounting unit, not model-vendor billing telemetry.
- Fixed reservations, not post-hoc actual usage, determine eligibility and stop reason. Exact precedence is:
  closed/study stop → experiment → provider calls → invalid packets → token → time.
- Exhaustion appends exactly one `stopped.v1` and invokes neither provider nor evaluator afterward.
- Invalid/transport output consumes its already-reserved provider call and increments invalid count; it never
  registers an experiment. Retry is allowed only if the full three-call completion reserve still fits.

## 12.5 Frozen measurement and expected outcomes

Fixture: `tests/fixtures/autonomy/v1/m3b-manifest.json`; raw SHA-256:
`29684ed79c0dcf224a3959753f324f6f55f261e696b5c366218b48ef2dc99bc1`.

| Gate | Literal denominator | Expected |
|---|---:|---:|
| Seven FSM branch transitions | 7 | `7/7` exact event/from/to/authority |
| M2 read + disposition/origin/Claim/ClassState writeback | 6 | `6/6` exact refs/head/evidence |
| Repeated committed transition idempotency | 7 | `7/7`, project/program/autonomy delta `0/0/0` |
| Closed-class guards | 4 | `4/4`, experiment registration `0` |
| Experiment/provider/invalid/token/time stop | 5 | `5/5` exact precedence/reason, forbidden call `0` |
| Sealed service + exact terminal summary | 6 | `6/6`, direct adapter/workspace call `0`, authority non-null `0` |
| Strict rejection/no-write | 8 | `8/8` exact code and scoped no-write |
| Total frozen cases | 43 | `43/43 PASS`; every ID consumed once, no extras |

Actual outcome: all 43 literal cases PASS, focused `51 passed in 54.33s`, adjacent M2-D/M3-A/M3-B
`116 passed in 60.69s`, M3-B six conjuncts `6/6`, and M3-A manifest SHA remained
`a43ba5980c257706fe49f0c5107b520683f85ff46b3d7d9848071a0382d747a2`. The exact receipt is
`12-m3-b-finite-autonomy-loop.receipt.json`. IDs, denominators, precedence, thresholds, event schemas, and expected
codes were not changed after result exposure.

## 12.6 Bounded plan and pre-score

- Product target: `autonomy/loop.py`, minimal `protocol.py`/`provider.py` generalization, exports; `<=1,600`
  gross lines.
- Tests+fixture target: executable literal handler table, pure reducer, actual M2/M3-A vertical, sealed
  ResearchService E2E; `<=1,700` gross lines.
- Phase+critic+receipt+audit docs `<=500`; inclusive gross `<=3,900`.
- Measurement order: pre-spec+manifest hash commit → independent critic questions commit → product/tests →
  frozen/focused/adjacent (no full) → critic verify → paired sync → independent seven-pass audit.
- Final full suite is reserved for M3 code freeze/M3-D unless a focused failure implicates broad regression.

Strongest failure hypothesis: the controller may look finite while storing only an in-memory enum, smuggling
provider output into Project/Program truth, bypassing `ResearchService`, creating an undiagnosed terminal node when
budget expires, or claiming idempotency without showing all three log deltas. Literal event replay, fixed completion
reservation, actual M2/M3-A vertical, and exact three-log refs must refute it.

### 12.6.4 Milestone progress claim

**Candidate label: `CLOSE`; engineering `6/6`; blocked on independent critic and audit.**

| M3-B exit conjunct | 이전 | actual | receipt/test evidence |
|---|---:|---:|---|
| transitions 7/7 | `0/7` | `7/7` | 7 manifest rows + exact cold reducer/summary |
| next reads M2; synthesis writes Claim/ClassState | 0 | PASS | disposition/origin/Claim `1/1/1`; current-head next packet revalidated |
| transition idempotency | `0/7` | `7/7` | three-log delta `0/0/0` |
| closed-class registration 0 | 미측정 | `4/4`, reg `0` | four literal guards |
| five budget stops | `0/5` | `5/5` | fixed reservation and exact precedence |
| sealed service + exact evidence summary | 0 | PASS | service `1`, adapter/workspace `0/0`, exact refs, authority `0` |

- **Prerequisite gate:** M3-A is closed at `effaabd`; parent M2 is closed. No bypass.
- M3-C remains blocked until independent critic and seven-pass progress audit both PASS.

### 12.6.5 End-state delta

**Actual classification: `구체화·검증`.** Before: Autonomy had a validated provider packet but no canonical
episode state. After: a single provider completes a finite evidence-bound episode; ProjectLog owns terminal/
Diagnosis, ProgramLog owns disposition/origin/Claim, and AutonomyLog owns only orchestration refs. A written Claim
changes the next Context and a fresh DecisionPacket is revalidated on the new Program head. Crash/incomplete-step
resume remains M3-C and unseen learning quality remains M3-D; neither receives a rating increase here.

### 12.6.6 Intent-execution reconciliation

**Actual label: `MATCH`.** The implementation retained the exact six-conjunct finite loop, separate truth owners,
fixed completion reserve, and sealed service boundary. The pre-data critic caused stricter precommit validation and
post-terminal incomplete-stop checks without changing scope. The later next-packet witness measured an already
specified §12.3 requirement; it did not change the frozen 43-case contract.

### 12.6.7 Claim mode

**Actual label: `MIXED`.** Frozen 43 cases, six conjuncts, schemas, stop precedence, and expected outcomes are
`CONFIRMATORY`: pre-spec `9069cbd` at `2026-08-12T04:05:38+09:00` precedes first product/data `ede020c` at
`2026-08-12T04:51:09+09:00`, and the manifest SHA is unchanged. The critic's explicit next-packet witness was
added after first data in `64d7249`, so that additional witness is `EXPLORATORY`. It strengthens but is not needed
to reinterpret the literal `43/43`.

### 12.6.8 Requirement-result divergence

Functional expected and actual results match exactly: `43/43`, six conjuncts `6/6`, forbidden direct calls `0`,
closed-class registrations `0`, and M3-A SHA unchanged. The product gross estimate missed (`1,861 > 1,600`) while
tests+fixture (`1,081 <= 1,700`) and inclusive estimate (`3,239 <= 3,900`) remain bounded. This engineering-footprint
surprise is `GENUINE-FINDING`/EXPLORATORY, not functional release evidence; M3-C pre-spec must explicitly retain,
trim, or rebaseline it without weakening behavior. No `RESULT-INVALID` or `REQUIREMENT-WRONG` condition occurred.

## 12.7 Residual issues

- Fault injection at every incomplete stage, exact crash resume, duplicate append races, and stale-head attack
  matrix are M3-C, though M3-B must leave durable event-derived seams for them.
- Token units are provider-neutral payload accounting, not vendor tokenizer/billing usage.
- Learning-quality and next-hypothesis correctness are not inferred from 43 conformance rows; NS6/M3-D owns the
  sealed unseen 36-episode comparison.
- Python same-process provider remains cooperative code, not a hostile-code sandbox; JSON subprocess retains the
  M3-A timeout/output/process-group boundary.
- Product gross additions exceeded the pre-score subtarget by 261 lines. M3-C must precommit whether recovery
  durability can share/refactor this reducer without behavior loss; the miss cannot silently disappear.

## 12.10 Next action

Complete the independent critic verify against the receipt and responses below. Only after PASS, synchronize the
paired status/pipeline docs and run the independent seven-pass audit; M3-C remains blocked until both gates pass.
