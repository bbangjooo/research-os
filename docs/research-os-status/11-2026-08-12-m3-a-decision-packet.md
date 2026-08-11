# §11 — M3-A provider-neutral DecisionPacket (2026-08-12)

> Status: **MEASUREMENT COMPLETE — ADVANCE; engineering 4/4, critic/audit pending**
> Previous phase: [§10](10-2026-08-12-m2-d-disposition-v04-release.md)
> Active milestone: `M3-A`; M3-B~D blocked

## 11.0 TL;DR

M3-A는 외부 provider가 반환한 candidate + typed Proposal + knowledge disposition을 비신뢰
`DecisionPacket v1`로 받아 current canonical state에 대해 재검산한다. Frozen `32/32`, focused `41`,
adjacent `103`, corrected full `757+115`, ruff/ty가 PASS했다. 첫 full의 historical v0.4 verifier 결함은
`RESULT-INVALID`로 철회하고 checkpoint-bound verifier로 고쳤다. Engineering conjunct는 `4/4`지만
critic/audit 전이므로 M3-A는 `ADVANCE`, M3-B는 blocked, NS5 transition은 `0/7`이다.

## 11.1 Scope, end-state, and authority

- Target: M3-A four conjunct, NS1 regression, NS5의 provider→preflight seam, pipeline Context/Autonomy.
- Provider output은 실행 권한이 아닌 untrusted data다. Packet 검증은 project/program log를 쓰지
  않으며 ResearchService/event append/workspace/deploy/merge/trade capability를 provider input에 담지 않는다.
- Python provider는 same-process security sandbox가 아니다. 이 phase의 authority claim은 interface로
  service/store/log reference를 위임하지 않고 output 검증이 no-write이라는 capability boundary까지다.
- JSON subprocess는 shell 없는 argv, exact one stdin/stdout JSON, duplicate key/non-finite/extra stdout 거절,
  timeout/output cap/process-group cleanup을 요구한다. LLM SDK/API key/session은 core에 추가하지 않는다.
- External projects, live pilot/migration, product multi-agent, autonomous event loop, release version, unseen
  benchmark는 범위 밖이다.

## 11.2 Frozen DecisionPacket v1 contract

`tests/fixtures/autonomy/v1/m3a-manifest.json`의 exact 32 case를 product/result 전 고정한다.
Raw SHA-256은 `a43ba5980c257706fe49f0c5107b520683f85ff46b3d7d9848071a0382d747a2`이다.

Packet exact fields:

1. schema version, stable `packet_id`, echoed `provider_request_id`, project ID, combined Context token.
2. full canonical `ProgramSnapshot`, its digest, and exact current Program head.
3. retrieval query/result digests and every returned Claim ID/digest/role/relation IDs/reasons exactly once.
4. bounded normalized candidate, candidate digest-bound typed `Proposal`, full `ProposalKnowledgeDisposition`.
5. recursive `authorized_action=null`; packet canonical size ≤ 2 MiB.

Validation is current-state, not self-consistency only:

- Context validator recomputes retrieval from current ClaimSnapshot and current project token.
- Current ProgramStore snapshot must canonical-equal packet ProgramSnapshot; stale head is a distinct
  `DECISION_PACKET_STALE` no-write failure.
- Candidate digest must equal Proposal candidate digest. Proposal generation/class/scope must match the
  active current Context/retrieval contract and pass existing registration preflight without mutation.
- Disposition must exact-cover the same retrieval and Proposal through the M2-D validator.
- Any extra/missing/wrong-type/bool-number/forged ID/digest/reason/non-null authority is
  `DECISION_PACKET_INVALID`, before any service/event call.

## 11.3 Provider port contract

- Trusted outbound `ProviderDecisionRequest v1` contains only request ID, canonical Context v3,
  ProgramSnapshot, and null authority. It has no service/store/log/workspace object.
- Python `Protocol` accepts one immutable/value-only request and returns one mapping; return parsing and packet
  validation are outside provider code.
- JSON subprocess receives the same canonical request by stdin and returns exactly one strict JSON object.
  Transport failure codes are `PROVIDER_PROTOCOL_INVALID|PROVIDER_TIMEOUT|PROVIDER_OUTPUT_LIMIT`.
- Both ports are conformance-equivalent when given deterministic provider behavior: canonical packet bytes
  and validator result are equal.

## 11.4 Frozen measurement and expected outcomes

| Gate | Denominator | Expected |
|---|---:|---:|
| Provider conformance/read-set/authority | 8 exact cases | `8/8 PASS` |
| Malformed/stale/non-null/transport rejection | 24 exact cases | `24/24 PASS`, write delta 0 |
| M3-A four exit conjuncts | 4 AND | `4/4` |
| Regression | full suite | `>=713 tests`, `>=115 subtests`, authority non-null 0, product multi-agent false |

Expected result is all frozen cases PASS. Any failed case is a real M3-A failure unless a demonstrable
fixture/runner contamination makes it `RESULT-INVALID`; result exposure cannot change case IDs, denominator,
threshold, required fields, or error class while retaining a confirmatory claim.

## 11.5 Bounded plan and milestone discipline

- Product: `autonomy/protocol.py`, `autonomy/provider.py`, exports only; `<=1,100` gross lines.
- Tests+fixture: strict packet/ports/actual M2 vertical and no-write matrix; `<=1,250` gross lines.
- Docs: architecture/provider contract/phase close; `<=450`; total `<=2,800`.
- Order: pre-spec+manifest hash commit → independent critic questions commit → product/tests →
  focused/adjacent/full → critic verify → paired sync → independent seven-pass audit.
- M3-A prerequisite M2-D/parent M2 is closed at phase §10 with critic + corrected audit PASS.

M3-A exit exact AND:

1. Packet binds current ProgramSnapshot/head, returned Claim IDs/reasons, Proposal/disposition.
2. JSON subprocess and Python Protocol provider conformance PASS.
3. Provider receives no direct service/event capability; validation project/program write delta 0.
4. Malformed/stale/non-null-authority packets reject 100% with exact code/no-write.

## 11.6 Pessimistic pre-score and claim mode

Strongest failure hypothesis: a generic JSON envelope appears provider-neutral while merely echoing
provider-supplied digests, omitting one retrieved Claim/reason, accepting a stale Program head, or passing a
live service/store reference to an in-process provider. The actual M2 Context→ProgramSnapshot→retrieval→
Proposal/disposition vertical, one-factor negative matrix, bytes-delta checks, and port parity must refute it.

Initial claim mode is `CONFIRMATORY`: pre-spec commit `50ee73d` freezes exact
schema/cases/denominators/error classes/expected outcomes before product/data exposure. Absolute current fixture
digests are descriptive; only pre/post equality and canonical recomputation are outcomes. Critic-driven
additions after first result become EXPLORATORY/MIXED.

### 11.6.1 What was built

- `autonomy/protocol.py`는 recursively exact/value-only `ProviderDecisionRequest v1`과
  `DecisionPacket v1`을 parse하고 current ProgramStore, ProjectLog, Context v3 retrieval, registered
  Proposal preflight, M2-D disposition을 다시 계산한다. Provider가 내부 digest를 함께 위조해도 trusted
  outbound request/current store와 다르면 invalid/stale로 분리한다.
- `autonomy/provider.py`는 immutable mapping을 받는 Python Protocol port와 shell 없는 argv subprocess
  port를 제공한다. Subprocess는 strict single JSON, duplicate/non-finite/extra stdout 거절, combined
  output cap, timeout, descendant process-group cleanup을 강제한다.
- Packet accept/reject는 append/run을 하지 않는다. Provider input에는 service/store/log/workspace/path/
  callable이 없고 모든 authority field는 recursive literal null이다. Python callback 자체는 sandbox가 아니다.
- `tests/test_m3a_decision_packet.py`의 literal handler table은 frozen 32 ID와 exact operation/result를
  일대일 소비한다. 실제 M2 ProgramStore/ClaimSnapshot/Context/retrieval/Proposal/disposition vertical,
  actual Program-head advance, actual existing closed-class preflight, spawned subprocess를 사용한다.

### 11.6.2 Verification evidence

| Gate | 결과 | 재현 근거 |
|---|---:|---|
| Frozen contract | `32/32`; conformance `8/8`, rejection `24/24` | receipt `m3a-decision-packet-receipt.json`; raw SHA `a43ba5…47a2`; pre-spec diff 0 |
| Current read set / binding | PASS | actual M2 vertical; self-consistent snapshot forgery invalid, actual Program append stale |
| Port / transport | PASS | real Python callback + spawned argv process request bytes/packet/validator parity; exact protocol/timeout/limit codes |
| Authority / writes | forbidden capability `0`, non-null authority `0`, project/program write delta `0/0` | frozen rows + recursive/live-value/no-append tests |
| Focused / adjacent | `41`, `103` | receipt의 exact pytest commands @ `42c7557` |
| Historical release + M3-A | `58` | `test_release_verifier.py` + M3-A focused |
| Corrected full | `757 passed, 115 subtests` | `.venv/bin/python -m pytest -q`; `1262.65s` @ clean `42c7557` |
| Static quality | ruff PASS, ty PASS | `.venv/bin/python -m ruff check src tests scripts`; `uvx --offline ty check src` |

### 11.6.3 System impact and bounded scope

- **Before → after:** opaque provider mapping → exact current-state classified packet
  (`accepted|invalid|stale|transport error`) without append/run.
- **Newly possible:** M3-B can consume one immutable DecisionPacket instead of receiving service/event authority.
- **Newly impossible:** a conforming packet cannot omit/forge retrieved knowledge, bind an inactive proposal,
  carry non-null authority, or mutate canonical logs during validation.
- **Downstream/user-visible:** operators can reproduce an exact error code and request/packet bytes; no research
  episode completes yet, so this is infrastructure that enables M3-B/C rather than NS5 transition progress.

- M3-A product is `1,081/1,100` lines; focused test + provider fixture is `648/1,250` lines.
- Result-triggered historical release correction changed verifier/tests only and did not change the frozen manifest,
  packet/provider product, 32 IDs, thresholds, or expected error classes.
- `50ee73d..42c7557` adds `1,944` and removes `59` lines including critic/docs and the correction; closure docs
  keep the precommitted total `<=2,800`. External projects were read neither written nor migrated in this phase.

### 11.6.4 Milestone progress claim

**Label: `ADVANCE` — M3-A engineering conjunct `4/4`, close gate `0/2`.**

| M3-A exit conjunct | 이전 | 이번 phase 후 | 근거 |
|---|---:|---:|---|
| ProgramSnapshot/head + Claim IDs/reasons + Proposal/disposition bind | 0 | PASS | frozen binding rows + actual M2 vertical in focused `41` |
| Python Protocol + JSON subprocess conformance | 0 | PASS | conformance `8/8`, canonical request/packet parity |
| direct service/event authority 0 + validation write 0 | 미측정 | `0`, `0/0` | receipt aggregate + recursive/no-append tests |
| malformed/stale/non-null rejection 100% | 0/24 | `24/24` | literal frozen rejection rows and exact codes |

- **Prerequisite gate:** M2-D/parent M2 is closed by phase §10 critic + corrected audit PASS.
- **Close gate:** independent critic and seven-pass audit are pending; status remains M3-A active, M3-B blocked.
- This seam is not an FSM transition: NS5 remains `0/7`.

### 11.6.5 End-state delta

**Classification: `구체화·검증`.**

- **Before vision snapshot:** pipeline Context had retrieval/disposition but M3 packet consumption was open;
  Autonomy was a manually connected external conversation.
- **After vision snapshot:** a provider output can cross a value-only port and be checked against current
  Program/Context/retrieval/Proposal state with exact no-write outcomes.
- **Delta:** Context/Autonomy provider→preflight seam is concrete. No §8.2 action was removed or relaxed;
  event persistence, run, diagnosis, synthesis, next/stop remain absent.

### 11.6.6 Intent-execution reconciliation

**Label: `PIVOT`.**

- **§11.1 intent:** implement and measure the frozen provider→DecisionPacket current-state seam without
  changing its 32-row contract.
- **§11.2~§11.6 execution:** that seam passed `32/32`; the full regression additionally exposed and corrected
  a historical v0.4 evidence-scope bug without changing M3-A product/criteria.

The first full run exposed an unrelated historical v0.4
static gate that incorrectly demanded the current M3 HEAD equal the old v0.4 product tree. The within-cycle
amendment bound v0.4 evidence to its receipt/product commits and prohibited later receipt reissue. This did not
loosen M3-A or M3 exit criteria; status §2.2.4 records the trigger and amendment.

### 11.6.7 Claim mode

**Label: `MIXED`.**

| Claim row | Mode | Timestamp / discipline evidence |
|---|---|---|
| Literal frozen 32 cases | `CONFIRMATORY` | Pre-spec commit `50ee73d6af934402de6d713a4e93b565a81ebfdb` at `2026-08-12 02:13:40 +0900`; first-data/product commit `eb289c40fca42868a657f0170815b610f69935c9` at `2026-08-12 02:38:34 +0900`; manifest diff 0 |
| Historical v0.4 gate correction + corrected full | `EXPLORATORY` | First failure triggered correction `42c7557`; excluded from the frozen 32 claim; final release freeze will re-run the precommitted corrected contract |

The exact hashes and commands are in the receipt. The exploratory correction is a regression-boundary finding,
not evidence of learning quality or NS5 transition progress.

### 11.6.8 Requirement-result divergence

**Classification: `RESULT-INVALID` (first full only).**

- **Observed:** `4 failed, 751 passed, 115 subtests`; one root failure was the HEAD-bound historical v0.4 gate
  and three were nested floor cascades.
- **Disposition:** Attempt 1 is withdrawn and does not update any North-Star row.
- **Re-measurement:** after the verifier correction, the same full command returned `757+115`.
- **Contract effect:** no DecisionPacket requirement, denominator, threshold, or outcome changed.

## 11.7 Residual issues

- Packet acceptance does not run an experiment or append a disposition; M3-B owns FSM/preflight/run/synthesis.
- Provider call/event crash resume and finite provider/token/time budget are M3-C.
- Packet quality/learning effect and unseen 36 episodes are M3-D/NS6.
- Python provider code is not an OS sandbox; subprocess isolation is process-protocol, not hostile-code containment.

## 11.10 Next action

Fill critic Q1~Q8 from the receipt and actual witnesses, obtain independent critic PASS, sync status/pipeline as
an M3-A close candidate, then obtain independent seven-pass audit PASS. The final M3-D code-freeze verifier
contract will be precommitted and will re-run the corrected historical gate/full suite before release. M3-B stays
blocked until both M3-A independent gates pass.
