# Critic — Phase 02 (2026-08-10) — m1-b-study-generation-budget

영향 §북극성 행: NS1 무결성·권한 하위호환, NS2 기계 강제 scientific state

> Verify state: **PLAN** — 구현 전 DIRECT oracle 8개를 phase/fixture에 고정했다. 구현 후 critic이 exact 결과·commit chronology를 재검증하기 전에는 PASS가 아니다.

## Q1 [measurement-gap]
`NS1 무결성·권한 하위호환`에서 `kernel/ids.py`·`kernel/projection.py`를 generation-aware로 바꾼 뒤 E10의 단순 full-suite PASS가 아니라 고정된 v1 legacy event corpus의 원문 bytes/hash, experiment ID, derived projection이 전후 100% 동일함을 어떤 fixture digest와 재현 명령으로 판정할 것인가?

**Response:** _DIRECT_
`tests/fixtures/scientific_state/v1/legacy-v1-events.jsonl`의 raw SHA-256은 `b35e9d74a64c729ceea3c5ca66303a7f4e14043129d4e4686741c5939cf178d6`, 고정 experiment ID는 `exp_9c077608f342414ce35c5dec5d7aa07b`, expected projection canonical digest는 `9acf4e08a01756d39e4789a7e13f635d891cb426c183abcbfc4793c53d472e88`다. manifest `legacy-v1-byte-projection-parity`가 `sha256sum .../legacy-v1-events.jsonl`와 focused test에서 raw bytes/head hash/ID/old API projection exact equality를 모두 요구하며, nullable generation schema가 legacy decoded row에 새 key를 노출해도 실패한다.

## Q2 [counterfactual]
`NS1 무결성·권한 하위호환`의 E10 `authorized_action` non-null 0은 새 필드를 아예 누락해도 통과할 수 있는데, Phase 02가 추가·변경하는 generation event, registration event, Decision·CLI·status JSON surface 전체의 고정 분모를 열거하고 각 payload에서 key가 존재하며 값이 null임을 판정하는 exact oracle은 무엇인가?

**Response:** _DIRECT_
manifest `authority-null-changed-surfaces`가 generation event, open-generation service/CLI, registration event, run-once service/CLI, study-status CLI, replay CLI의 고정 8 surfaces를 열거한다. expected는 surface `8`, `authorized_action` key `8`, non-null `0`이며 누락도 실패다. 중첩 Decision은 run-once service/CLI recursive scan에 포함한다.

## Q3 [claim-mode-discipline]
`NS1` E10과 신규 기준을 `CONFIRMATORY`로 청구하려면 raw/canonical manifest digest와 E1~E10이 담긴 docs+fixture-only pre-spec commit이 첫 science/service/identity/projection 코드 또는 결과 노출 commit보다 앞선다는 것을 어떤 두 full hash·timestamp·diff로 입증하며, 순서가 어긋나면 어느 청구를 `EXPLORATORY`로 강등할 것인가?

**Response:** _DIRECT_
docs+fixture-only pre-spec은 `a6b4f86b66335cb0155a6d5b34ebd0b5079f6cc4` (`2026-08-10T01:36:03+09:00`)이며 `git diff-tree --no-commit-id --name-only -r` 결과는 phase/critic 2개와 fixture 5개뿐이다. 첫 product/result-bearing commit은 아직 `PENDING`이며 같은 세 값을 구현 후 병기한다. 순서가 어긋나면 StudyContract/generation/budget/E1~E10 신규 결과 전부 `EXPLORATORY`로 강등하며 legacy corpus 자체의 사전 고정 사실만 남긴다.

## Q4 [sample-dependence]
`NS2 기계 강제 scientific state`의 contract capability를 E1만으로 1/6로 셀 수 있는가: exact-key/missing/null, duplicate ID/pointer, bool-number/nonfinite/unsafe integer, bad digest/RFC-6901, role/development, retry/attempt, cost-triple, stop/change-control 제약 각각을 한 행 이상 깨뜨리는 versioned negative matrix와 고정 분모는 무엇인가?

**Response:** _DIRECT_
`m1b-contract-negative-matrix.json` raw SHA-256 `73ddbe0dc4a5e4953073dde40c26c57f90ede53ca368f9c306e0f9f52b90808b`가 지적된 모든 범주를 24 named rows로 고정한다. manifest `contract-negative-matrix`의 exact 분모/분자는 `24/24`, 모든 code는 `STUDY_CONTRACT_INVALID`; 한 행이라도 accept·다른 code·미실행이면 capability 청구와 M1-B를 차단한다.

## Q5 [counterfactual]
`NS2`의 E4/E5/E8은 replay·pure reduction·live race를 서로 다른 입력으로 통과시킬 수 있는데, 동일한 persisted event sequence를 service append 직후 state, cold replay, projection rebuild 세 경로에 넣어 active generation·contract/seal binding·ledger와 failure code가 exact-match하고 malformed direct append가 모두 fail-closed임을 어떤 paired oracle로 보일 것인가?

**Response:** _DIRECT_
manifest `live-replay-rebuild-parity`가 동일 generation+ordinary+retry sequence를 post-append/cold-replay/projection-rebuild-then-status 3경로에서 비교해 generation/contract/seal과 ledger `2 attempts, 1 retry, 2000 ms, 5000 microunits` exact equality 및 다음 retry의 `BUDGET_RETRIES_EXCEEDED`를 요구한다. `malformed-direct-append-matrix`는 unbound/partial/contract/seal/generation/debit/overrun 7/7을 cold replay에서 지정 code로 fail-closed한다.

## Q6 [end-state-positioning]
`NS2 0/6→2/6`와 §8.4 `Study control` 구체화·검증을 청구하려면 fixed reservation이 actual elapsed/cost를 측정하지 않고 successor가 새 budget을 여는 설계에서 “finite generation budget”이 세대별 한도인지 study lifetime 한도인지 명시하고, 반복 budget 증액 가능성과 actual-usage 미계측을 비전 축소 없이 pipeline current-state에 남기면서 어떤 CLI/replay lifecycle로 단순 schema 추가 이상의 종착지 변화를 관찰할 것인가?

**Response:** _DIRECT_
M1-B 한도는 **generation별 non-refundable reserved allocation**이며 study-lifetime cap이 아니다. 명시적 successor는 새 evaluation-sealed contract와 reason으로 새 한도를 열 수 있고 반복 증액을 기술적으로 막지 않으며 actual elapsed/cost settlement도 미계측이다. 이 두 limitation을 phase §02.9와 결과 후 pipeline current-state에 유지한다. `open-generation → study-status → run-once → study-status → replay → study-status` lifecycle에서 registration 전 atomic 차단과 replay 동일 ledger가 관찰될 때만 2/6으로 센다.

## Q7 [milestone-positioning]
`M1-B CLOSE`의 generation open/replay conjunct는 E2/E3의 순차 호출만 고정했는데, 동일 first-open 동시 호출과 같은 active predecessor에서 서로 다른 successor 동시 호출에서도 generation event와 active child가 각각 하나뿐이며 loser stable code/event delta가 exact임을 검증하지 않고 atomic Study control을 닫을 근거가 있는가?

**Response:** _DIRECT_
닫을 근거가 없으므로 manifest에 두 forced-barrier race를 추가했다. `generation-first-open-race`는 2 success가 같은 ID를 받고 generation event delta `1`; `generation-divergent-successor-race`는 winner/reject `1/1`, delta `1`, loser `STUDY_GENERATION_MISMATCH`, active child가 사전 계산된 두 ID 중 winner와 exact 일치해야 한다. 둘 중 하나라도 다르면 generation conjunct는 ❌다.

## Q8 [divergence-diagnosis]
`NS2` E8에서 context-token 경쟁의 loser가 기존 head/certification precondition 때문에 budget code보다 먼저 거절될 수 있는데, 어느 registration path에서 각 차원의 `BUDGET_*_EXCEEDED`를 강제할지 사전 고정하고 `STALE_CONTEXT`·race 미발생·reducer/live 불일치를 각각 `REQUIREMENT-WRONG`, `RESULT-INVALID`, `GENUINE-FINDING` 중 무엇으로 분류하며 어떤 경우든 exact E8 불일치가 M1-B CLOSE를 차단하는가?

**Response:** _DIRECT_
E8은 shared **common tokenless registration gate**에서 preflight 뒤·locked append 직전 barrier를 걸어 4개 budget code를 강제한다. context-token 경쟁은 별도 oracle이며 loser `STALE_AGENT_CONTEXT`, E8 분모 제외다. E8에서 stale code가 나오거나 race가 실제 겹치지 않거나 reducer/live가 다르면 `RESULT-INVALID`로 결과를 폐기한다. 독립 최소 재현이 기존 lock 의미 자체가 사전 requirement와 충돌함을 보이면 `GENUINE-FINDING`으로 강등·재명세하고, context authority보다 budget precedence를 요구한 목표가 잘못임이 드러날 때만 `REQUIREMENT-WRONG`이다. 어느 갈래든 exact E8 불일치는 M1-B CLOSE를 차단한다.
