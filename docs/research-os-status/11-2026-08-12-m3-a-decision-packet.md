# §11 — M3-A provider-neutral DecisionPacket (2026-08-12)

> Status: **PRE-SPEC — product implementation not started; 0/4**
> Previous phase: [§10](10-2026-08-12-m2-d-disposition-v04-release.md)
> Active milestone: `M3-A`; M3-B~D blocked

## 11.0 TL;DR

M3-A는 외부 provider가 반환한 candidate + typed Proposal + knowledge disposition을 비신뢰
`DecisionPacket v1`로 받는다. Packet은 current Context v3 token, full ProgramSnapshot/digest/head,
retrieval exact Claim IDs/reasons, Proposal/disposition을 bind한다. Research OS는 canonical state에서 전체
read set을 재계산하여 stale/malformed/non-null authority를 no-write 거절한다. Python Protocol과
bounded strict-JSON subprocess는 동일 packet을 생성해야 하며 provider에 service/store/log capability를
넘기지 않는다. FSM/event persistence/run은 M3-B/C이다.

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

Initial claim mode is `CONFIRMATORY`: exact schema/cases/denominators/error classes/expected outcomes are frozen
before product/data exposure. Absolute current fixture digests are descriptive; only pre/post equality and
canonical recomputation are outcomes. Critic-driven additions after first result become EXPLORATORY/MIXED.

## 11.7 Residual issues

- Packet acceptance does not run an experiment or append a disposition; M3-B owns FSM/preflight/run/synthesis.
- Provider call/event crash resume and finite provider/token/time budget are M3-C.
- Packet quality/learning effect and unseen 36 episodes are M3-D/NS6.
- Python provider code is not an OS sandbox; subprocess isolation is process-protocol, not hostile-code containment.

## 11.10 Next action

Commit this pre-spec and manifest, generate at most eight independent closed critic questions, and commit those
questions before adding any `src/research_os/autonomy` product code or M3-A executable test result.
