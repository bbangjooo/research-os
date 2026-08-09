# §02 — M1-B Study Generation and Cumulative Budget (2026-08-10)

> Status: **PLAN — 구현 전 사전 명세**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §02
> 직전 phase: [`§01 M1-A`](01-2026-08-09-m1-a-evidence-correctness.md)
> Pipeline 영향: [`docs/research-os-pipeline.md`](../research-os-pipeline.md) §2, §8.4 Study control, §9.4 M1-B
> 구현 전 기준선: commit `6bbe7a6`, Python 3.12에서 `290 passed, 67 subtests passed`

## 02.0 한 단락 요약 (TL;DR)

M1-B는 비정형 research brief의 search budget을 authority로 삼지 않고, exact `StudyContract`와 evaluation-sealed generation을 canonical event로 연다. 각 versioned experiment registration이 contract-fixed attempts/retries/elapsed/cost reservation을 원자적으로 debit하며, pure reducer가 live precondition과 replay에서 같은 ledger를 계산한다. 목표 §북극성은 NS1·NS2, 목표 종착지 delta는 §8.4 Study control 구체화, 목표 checkpoint는 M1-B 4 conjunct 전부 `CLOSE`다. 실제 elapsed/cost 측정이 아니라 보수적 reservation 회계임을 명시하고, 결과 전 oracle을 versioned fixture로 고정한다.

## 02.1 왜 이 작업을 하나

- 목표 §북극성:
  - **NS1 무결성·권한 하위호환** — event envelope v1/legacy registration을 rewrite하지 않고, 새 generation 이후 budget 우회를 fail-closed replay한다.
  - **NS2 기계 강제 scientific state** — 6 capability 중 generation/contract와 cumulative budget 두 capability를 canonical transition으로 만든다.
- Trigger: M1-A가 trustworthy evidence prerequisite를 닫았지만, 현재 `[budget]`은 adapter 1-call resource cap이고 `research-brief.md`의 search budget은 kernel이 합산하지 않는다.
- 선택한 seam: `science/contracts.py`의 immutable contract + `science/state.py`의 I/O-free reducer + `EventLog.append(precondition=...)`. `project.toml`/brief에 plan을 넣어 evaluator certification을 불필요하게 회전시키거나 SQLite를 budget authority로 삼지 않는다.
- 범위 경계: typed Proposal/evaluation-scope execution/replication은 M1-C, Diagnosis/ClassState는 M1-D, context v3/tokenless legacy isolation은 M1-E다. live migration과 product multi-agent는 각각 v0.5/NS6 이후다.
- 이 phase는 active `M1-B` 네 conjunct만 닫으며 gate-bypass가 아니다.

### 02.1.1 구현 전 고정 StudyContract v1

Contract exact top-level fields는 `schema_version`, `study_id`, `hypothesis_classes`, `intervention_surface`, `evaluation_scopes`, `frontier`, `stop_policy`, `change_control`, `budget`이다. 모든 nested object도 exact-key이며 unknown/missing/null-for-required를 거절한다.

- `hypothesis_classes[]`: exact `id`, `description`, `conclusive_rejection_limit`; ID unique, description non-empty, limit positive safe integer.
- `intervention_surface`: candidate schema SHA-256, unique RFC-6901 `allowed_json_pointers`, positive `max_changes ≤ pointer count`.
- `evaluation_scopes[]`: exact `id`, `role ∈ {development,diagnostic,replication,holdout}`, manifest SHA-256; ID unique, development role ≥1.
- `frontier.max_active_branches`: positive safe integer.
- `stop_policy`: exact three values `on_untrusted=stop`, `on_budget_exhausted=stop`, `when_all_classes_closed=stop`.
- `change_control.require_new_generation`: literal `true`.
- `budget`: `max_attempts` positive, `max_retries` nonnegative `< max_attempts`, positive `max_elapsed_milliseconds`와 positive per-attempt reservation. Cost triple `(cost_unit,max_cost_microunits,cost_reservation_per_attempt_microunits)`은 모두 null 또는 모두 valid/positive다.
- Semantically unordered hypothesis/scope/pointer arrays는 ID/pointer로 정렬해 canonical `to_dict()`와 digest를 만든다. duplicate·unsafe integer·NaN/Inf·bool-number·bad digest/pointer는 `STUDY_CONTRACT_INVALID`다.
- Fixed fixture: `tests/fixtures/scientific_state/v1/m1b-contract.json`; normalized contract digest `00029b4eae18e71513001bdee36bd8a3333b58720b1f27f78b1ab80d68ca1320`.
- Negative oracle: `m1b-contract-negative-matrix.json`, raw SHA-256 `73ddbe0dc4a5e4953073dde40c26c57f90ede53ca368f9c306e0f9f52b90808b`; exact-key/missing/null/duplicate/number/digest/pointer/role/budget/stop/change-control 24/24가 모두 `STUDY_CONTRACT_INVALID`여야 한다.

### 02.1.2 Generation, identity, change-control 계약

1. Service가 현재 effective compatibility, certification artifact digest, review-subject digest를 `evaluation_seal`로 만들고 별도 digest를 계산한다. Contract digest와 evaluation-seal digest는 직교 필드로 보존한다.
2. event type은 `research.study_generation_opened.v1`; payload는 exact `science_state_version`, `generation_id`, `study_contract_digest`, `evaluation_seal`, `evaluation_seal_digest`, `predecessor_generation_id`, `change_reason`, `contract`, `authorized_action=null`이다.
3. `generation_id = stable_id("generation", project_id, predecessor_generation_id, study_contract_digest, evaluation_seal_digest)`다. fixture first ID는 `generation_b87daa35b5f8e5593fe0c4f5d245f8a6`.
4. 첫 open은 predecessor/reason null. active와 exact contract+seal 재호출은 idempotent(event delta 0). 변경 open은 exact active predecessor와 non-empty reason이 필요하다.
5. 동일 contract+seal을 successor로 열어 budget만 reset하는 시도는 `STUDY_GENERATION_UNCHANGED`; stale/missing predecessor는 `STUDY_GENERATION_MISMATCH`, reason 누락은 `STUDY_CHANGE_REASON_REQUIRED`다.
6. 새 registration은 full science metadata bundle과 active generation을 bind한다. generation 시작 전 legacy registration은 `legacy_unstructured` replay지만, 시작 후 unbound/partial registration은 `STUDY_GENERATION_REQUIRED`/`STUDY_REGISTRATION_INVALID`다.
7. versioned experiment identity/attempt query는 generation ID를 별도 축으로 포함한다. generation field가 없는 legacy ID와 event bytes는 그대로 유지하며 parent/retry는 같은 generation이어야 한다.
8. open은 certification read lock과 EventLog locked pre/postcondition에서 seal·predecessor를 재검증한다. concurrent identical first-open은 같은 ID 2 success/event 1, divergent successor는 1 winner/1 `STUDY_GENERATION_MISMATCH`/event 1이어야 한다.

### 02.1.3 Cumulative budget와 atomic debit 계약

- Contract-fixed `budget_debit`를 registration에 내장한다: attempts `1`, retries `0|1`, `reserved_elapsed_milliseconds`, `reserved_cost_microunits|null`. caller가 값을 선택하지 못한다.
- 모든 registration은 terminal status와 무관하게 debit하며 환불하지 않는다. retry는 attempts와 retries 모두 소비한다.
- elapsed/cost는 실제 사용량이라 부르지 않고 **reserved allocation**으로만 청구한다. cost triple이 null이면 cost ledger 전체가 null이며 0으로 추정하지 않는다.
- Pure reducer는 canonical events만 받아 generation chain, registration binding, ledger를 재구성한다. projection/file/clock 호출은 금지한다.
- 판정 precedence: payload validity → active generation/digest/seal → attempts → retries → elapsed → cost. mismatch는 `STUDY_{REGISTRATION_INVALID|GENERATION_REQUIRED|GENERATION_MISMATCH|CONTRACT_MISMATCH|EVALUATION_SEAL_MISMATCH}`, 초과는 `BUDGET_{ATTEMPTS|RETRIES|ELAPSED|COST}_EXCEEDED`다.
- Live registration은 preflight 뒤 같은 reducer를 `EventLog.append` exclusive-lock precondition에서 다시 실행한다. callback은 supplied locked events만 읽고 log/projection에 재진입하지 않는다.
- context-token path는 기존 head/certification pre/postcondition과 budget precondition을 합성한다. tokenless path도 active generation 뒤에는 같은 budget gate를 거친다.

### 02.1.4 사전 예상 결과와 manifest oracle

Versioned oracle: `tests/fixtures/scientific_state/v1/manifest.json`; 29 cases, raw SHA-256 `a1ba1a6eccd2a10ead5ef0d2006a0fa850e15c0f73fc8b928e981c74c4e2f659`, sorted-compact JSON digest `7ddf837bceedebd2d4dca243e48d2cd734e34db9472f67f1273fcfe30dd11e2e`. Legacy corpus raw SHA-256는 `b35e9d74a64c729ceea3c5ca66303a7f4e14043129d4e4686741c5939cf178d6`, old projection canonical digest는 `9acf4e08a01756d39e4789a7e13f635d891cb426c183abcbfc4793c53d472e88`다.

| ID | 고정 입력 | 예상 결과 |
|---|---|---|
| E1 | exact/shuffled contract + negative matrix | digest exact/order 동일; 음성 `24/24` stable reject |
| E2 | first/idempotent open + concurrent identical open | ID exact, sequential second delta 0; race 2 success/event 1 |
| E3 | changed successor + invalid/reset + divergent race | successor digest/ID exact; invalid delta 0; race winner/reject/event `1/1/1` |
| E4 | fixed v1 corpus + legacy registration before/after generation | raw bytes/head/ID/projection exact; before unstructured, after fail-closed |
| E5 | invalid/infra/retry/rejected 4 registrations + same-sequence path parity | ledger exact `4/1/4000/10000`; live/replay/rebuild state·next failure exact |
| E6 | cost triple null | ledger cost `null`, 0 추정 없음 |
| E7 | isolated overrun + malformed direct append 7종 | dimension code/event 0; malformed replay `7/7` fail-closed |
| E8 | common tokenless gate에서 dimension별 두 concurrent workers | winner/reject/event `1/1/1`, block `4/4=100%`; context stale race는 별도 분모 |
| E9 | versioned registration seal/generation mismatch | stable mismatch code, event delta 0 |
| E10 | full regression/authority | 기존 `290+67` floor와 신규 suite PASS; changed 8 surfaces key `8/8`, non-null 0 |

어느 expected digest/ID/code/count/arithmetic/race ratio나 기존 regression이 다르면 M1-B CLOSE를 차단하고 §02.6.8 분류 후 재측정한다.

## 02.2 무엇을 만들 계획인가

| 작업 | 위치 | 예상 검증 산출물 |
|---|---|---|
| strict contract + generation/event payload | 신규 `src/research_os/science/{contracts,state}.py` | contract/digest/manifest unit tests |
| atomic generation open + registration debit | `service.py`, `errors.py`, `cli.py` | `open-generation`/`study-status` lifecycle + forced-race tests |
| generation-aware experiment identity/cache | `kernel/ids.py`, `kernel/projection.py` | legacy migration/ID/retry regression |
| public docs/examples | README/architecture/protocol/new-project as needed | example lifecycle tests |

## 02.3 검증 계획

- Focused: manifest contract/reducer, generation CLI/replay, ledger arithmetic, forced multiprocess race, projection legacy migration.
- Full: explicit Python 3.12 `pytest -q`; ruff; ty; `git diff --check`.
- Counterfactual: 24-row contract negatives, same contract reordered, exact budget equality, terminal-status non-refund, cost-null, partial/direct malformed bundle, context/tokenless append paths, v1 bytes/projection parity.
- Independent review: contract/digest/replay와 atomic concurrency/identity를 분리 검토한다.

## 02.4 결과 vs 가설

| 가설 | 실제 측정값 | 차이 사유 |
|---|---|---|
| E1~E10 exact + M1-B 4 conjunct close | 구현 전 — 미측정 | 구현 후 기록 |

## 02.5 발견된 부수 이슈

- 구현 중 관찰되지만 M1-B 밖인 actual usage settlement, Proposal/Diagnosis/context v3 문제는 근거와 함께 여기에 남긴다.

## 02.6 시스템 영향 분석 ★

- 이전: 연구 세대와 누적 예산은 brief/agent 규율이며 새 session/branch가 canonical counter를 공유하지 않는다.
- 이후 목표: operator가 typed contract로 generation별 finite reserved budget을 열고, 모든 versioned registration이 durable budget을 원자 debit하며 replay가 동일 ledger를 복원한다.
- 가능: M1-C Proposal이 exact generation/remaining budget/scope identity를 bind한다.
- 불가능: active generation 아래 unbound registration, unchanged budget reset, stale successor, concurrent last-slot double spend.
- 외부 관찰: `open-generation → study-status → run-once → study-status → replay → study-status`에서 차단과 동일 ledger가 보인다. v1 legacy bytes/API projection은 바뀌지 않는다.

## 02.6.4 마일스톤 진척 청구 ★

**영향 받은 M_i.j**: `M1-B` · **계획 라벨**: _CLOSE_

| conjunct | 이전 | 목표 | 고정 근거 |
|---|---|---|---|
| canonical StudyContract schema/digest tests PASS | ❌ | ✅ | E1 + fixture exact digest |
| generation open/replay tests PASS | ❌ | ✅ | E2~E4/E9 event and stable-code oracle |
| attempt/retry/elapsed/cost ledger arithmetic tests PASS | ❌ | ✅ | E5~E7/null/equality/non-refund |
| locked append overrun 100% reject·TOCTOU race PASS | ❌ | ✅ | E8 4 dimensions, 1 winner/1 reject |

- 모든 conjunct ✅ 확인 [ ] · status에서 M1-B closed/M1-C active [ ] · parent M1은 C~E가 남아 open [x] · prerequisite N/A/gate-bypass 없음.

## 02.6.5 종착지 비전 갱신 ★

- 계획 Delta: §8.4 Study control을 “brief/per-run cap”에서 “canonical StudyContract + atomic cumulative reservation”으로 구체화·검증한다.
- §8 endpoint, NS/M criterion, 다른 7영역은 유지한다. actual usage settlement나 multi-agent를 종착지에서 제거하지 않는다.
- pipeline §8.5 Cycle 02 행은 결과 후 추가 [ ].

## 02.6.6 의도-실행 정합 ★

**계획 라벨**: _MATCH_ — NS1/NS2, Study control, M1-B 네 conjunct의 실제 파일/test/manifest 결과를 구현 후 비교한다. 의미 변화면 PIVOT/DRIFT를 숨기지 않는다.

## 02.6.7 Claim Mode ★

**계획 라벨**: _CONFIRMATORY candidate_. Docs+fixture-only pre-spec은 `a6b4f86b66335cb0155a6d5b34ebd0b5079f6cc4` (`2026-08-10T01:36:03+09:00`)이며 7개 phase/critic/fixture 파일만 포함한다. 첫 implementation/result-bearing commit은 아직 `PENDING`; 사전 명세 전에 본 것은 현재 v0.2 seam뿐이고 E1~E10 결과는 미측정이다. 구현 commit이 앞서거나 oracle이 사후 변경되면 신규 청구 전체를 EXPLORATORY로 강등한다.

## 02.6.8 Requirement-Result Divergence ★

- `REQUIREMENT-WRONG`: reservation이 사용자 목표의 “같은 예산”을 잘못 대리하거나 M1-B criterion이 end-state를 못 잡음 → correction/필요시 Rule 9.
- `RESULT-INVALID`: E8에서 stale-context가 선행, harness race 미발생, reducer/live mismatch, wrong runtime, implementation bug, manifest drift → 결과 제외·동일 pre-spec 재측정.
- `GENUINE-FINDING`: 독립 최소 재현에서도 기존 lock/replay/legacy 의미가 예상과 다름 → M1-B 차단, EXPLORATORY + 재명세; context authority보다 budget precedence를 요구한 목표가 틀렸을 때만 `REQUIREMENT-WRONG`.

## 02.7 §북극성 갱신 계획

- NS1: full/legacy/authority/race evidence만 부분 진척; 전체 attack manifest/release gate는 open.
- NS2: generation/contract + cumulative budget이 exact manifest와 함께 동작하면 `0/6 → 2/6`; 그 전에는 0/6 유지.

## 02.8 §pipeline 매핑 영향

- 목표: Stage 2 Study generation `△ → ○`; §8.4 Study control current state 보강. endpoint 의미 변경 없음.

## 02.9 비관 재채점 — 이 phase 자체

- elapsed/cost는 actual telemetry가 아니라 non-refundable reservation이므로 실제 자원 효율을 측정하지 않는다.
- budget은 generation별 한도이며 study lifetime cap이 아니다. explicit successor가 새 sealed contract/reason으로 한도를 열 수 있고 반복 증액 자체를 막지 않는다.
- strict contract는 hypothesis/scopes가 과학적으로 좋은지 보증하지 않는다.
- legacy pre-generation registration은 replay되지만 typed state로 자동 추론하지 않는다.
- context v2는 generation/ledger를 직접 노출하지 않으며 M1-E까지 agent UX는 불완전하다.

## 02.10 다음 1행동

- 단일 최우선 행동: M1-B critic 질문을 생성·응답하고 docs+fixture pre-spec checkpoint를 commit한다.
- 그 다음: strict contracts/reducer → service atomic append/CLI → generation-aware identity/projection 순으로 구현하고 focused/full tests, critic verify, independent auditor를 통과한다.
