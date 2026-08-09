# §01 — M1-A Evidence Correctness (2026-08-09)

> Status: **PLAN — 구현 전 사전 명세**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §01
> 직전 phase: [`§00 Bootstrap`](00-bootstrap-retro.md)
> Pipeline 영향: [`docs/research-os-pipeline.md`](../research-os-pipeline.md) §1, §8.4 Evidence semantics·Compatibility/authority, §9.4 M1-A
> 구현 전 기준선: commit `e728df9`, Python 3.12에서 `262 passed, 57 subtests passed`

## 01.0 한 단락 요약 (TL;DR)

M1-A는 veto가 있더라도 방향 보정 metric delta와 promotion margin을 보존하고, constitution 소유 typed gate를 evaluator metric 관측과 결합해 signed/normalized slack으로 판정한다. baseline도 candidate와 같은 sealed `VERIFY` 경계를 통과시키며, 승인된 기존 certification patch는 nested immutable fingerprint의 실제 CLI lifecycle까지 회귀한다. 목표 §북극성은 NS1·NS2, 목표 종착지 delta는 §8.4 Evidence semantics 구체화와 Compatibility/authority current-state 보강, 목표 checkpoint는 M1-A의 네 conjunct 전부를 `CLOSE`하는 것이다. 구현 결과가 기록되기 전이므로 이 파일의 결과·측정 절은 아직 미완료다.

## 01.1 왜 이 작업을 하나

- 목표 §북극성:
  - **NS1 무결성·권한 하위호환** — baseline/candidate verify 비대칭과 nested JSON 직렬화 실패를 제거하되 legacy replay와 `authorized_action=null`을 보존한다.
  - **NS2 기계 강제 scientific state** — 후속 Diagnosis가 소비할 방향 보정 delta, promotion margin, typed gate slack을 kernel이 재계산 가능한 evidence로 만든다.
- Trigger: v0.2 policy는 legacy constraint를 delta 계산 전에 veto해 “효과는 있었으나 hard gate 위반”과 “효과 없음”을 구분할 수 없고, baseline은 candidate와 달리 adapter `VERIFY`를 거치지 않는다.
- 선택한 설계: evaluator의 기존 `ResultEnvelope.metrics`를 observation wire로 재사용하고, gate의 threshold/operator/role/unit/scale은 constitution이 소유한다. 새 observation 필드를 결과 envelope에 추가해 과거 digest를 불필요하게 바꾸는 대안은 채택하지 않는다.
- 범위 경계: StudyContract·Diagnosis·ClassState·generation budget은 M1-B~D, 실제 프로젝트 migration과 live pilot은 v0.5 이후, multi-agent 제품 기능은 NS6 통과 이후다.
- 비전 매핑 경계: typed delta/gate와 baseline symmetry는 §8.4 Evidence semantics를 구체화한다. nested/flat certification replay는 endpoint 정의를 바꾸지 않고 §8.4 Compatibility/authority의 현재 상태를 보강한다. Cycle 01에서는 두 영역을 함께 갱신한다.

### 01.1.1 구현 전 고정 판정 계약

1. `[[promotion.gates]]`는 exact fields `id`, `metric`, `role`, `operator`, `threshold`, `unit`, `scale`을 가진다.
2. `role ∈ {hard, support}`, `operator ∈ {gte, lte}`이며 ID는 trim 후 unique, metric/unit은 non-empty, threshold는 finite, scale은 finite positive다. unknown/missing/duplicate/non-finite/bool-number 입력은 configuration 단계에서 거절한다.
3. evaluator는 `ResultEnvelope.metrics[gate.metric]`의 finite observation만 제공한다. evaluator가 threshold나 pass/fail을 선언하지 않는다.
4. `gte: signed_slack = observed - threshold`, `lte: signed_slack = threshold - observed`, `passed = signed_slack >= 0`, `normalized_slack = signed_slack / scale`이다. 계산 결과가 non-finite이면 fail-closed다.
5. primary improvement는 `maximize: candidate - baseline`, `minimize: baseline - candidate`, promotion margin은 `improvement - minimum_improvement`다. hard/support/legacy veto 판정보다 먼저 계산하고 Decision에 보존한다. 계산 결과가 non-finite이면 fail-closed다.
6. precedence는 verify/필수 evidence 유효성 → delta/margin 계산 → 모든 typed gate 계산 → legacy constraint 또는 hard gate veto → support gate 실패 → strict promotion margin 판정 순서다.
7. legacy constraint 또는 hard gate 실패는 `REJECTED/HARD_CONSTRAINT_FAILED`, support gate 실패는 `INSUFFICIENT_EVIDENCE/SUPPORT_GATE_FAILED`, missing gate metric은 `INSUFFICIENT_EVIDENCE/GATE_METRIC_MISSING`, gate 산술 non-finite는 `INVALID_EXPERIMENT/NON_FINITE_GATE_SLACK`이다.
8. promotion은 기존 의미대로 `promotion_margin > 0`일 때만 성공한다. gate equality는 통과하지만 improvement equality는 승격하지 않는다.
9. gate가 없는 v0.2 constitution과 arbitrary legacy constraint는 계속 읽고 판정한다. 과거 event bytes/schema를 rewrite하지 않는다.
10. baseline 각 repeat는 candidate와 동일하게 result digest를 bind한 adapter `VERIFY`, verify 전후 immutable workspace 검사, exact artifact recapture를 통과해야만 `BASELINE_RECORDED`가 된다. 새 baseline event에는 repeat별 verification evidence를 저장하며, 이 필드가 없는 legacy event는 replay할 수 있지만 새 승격의 baseline으로 재사용하지 않고 다시 seal한다.
11. certification JSON schema/digest version은 같은 portable JSON에 대해 유지한다. frozen nested structure는 doctor→review-subject→certify→inspect 경계에서 ordinary dict/list로 정규화되고 CLI stdout은 완전한 JSON 렌더가 성공한 뒤에만 한 번에 기록한다.

### 01.1.2 사전 예상 결과 (divergence 기준)

| ID | 구현 전 고정 입력 | 예상 결과 |
|---|---|---|
| E1 | maximize, baseline `100`, candidate `112`, minimum `5`; (a) legacy hard constraint, (b) typed hard gate 각각 veto | 두 경로 모두 improvement `12`, promotion margin `7`, `REJECTED/HARD_CONSTRAINT_FAILED` |
| E2 | minimize, baseline `100`, candidate `88`, minimum `5`; (a) legacy hard constraint, (b) typed hard gate 각각 veto | 두 경로 모두 improvement `12`, promotion margin `7`, `REJECTED/HARD_CONSTRAINT_FAILED` |
| E3 | gte threshold `10`, scale `4`, observed `12/8/10` | slack `2/-2/0`, normalized `0.5/-0.5/0`, pass `true/false/true` |
| E4 | lte threshold `10`, scale `4`, observed `8/12/10` | slack `2/-2/0`, normalized `0.5/-0.5/0`, pass `true/false/true` |
| E5 | baseline repeats `2` | `BASELINE→VERIFY` 두 쌍, exact result digest 두 개, 성공 시 verification evidence 두 개 |
| E6 | baseline VERIFY negative 또는 verify 후 source/artifact mutation | `BASELINE_RECORDED` 0건, terminal failure/exception은 기존 failure dominance 규칙 준수 |
| E7 | nested adapter fingerprint CLI lifecycle | doctor/review-subject/certify/inspect 각각 exit `0`, stderr empty, stdout JSON parse 성공, equivalent frozen/list↔dict callback drift `0` |
| E8 | v0.2 flat certificate와 verification 없는 legacy baseline event | replay `PASS`; legacy baseline은 current-policy authorization에 사용하지 않고 reseal |
| E9 | 전체 regression | 기존 `262 tests + 57 subtests`와 모든 신규 M1-A tests 100% PASS, `authorized_action` non-null `0` |

의미 있는 divergence는 위 exact 값·호출 수·event 수·status/reason 중 하나라도 다르거나 기존 regression 한 건이라도 실패하는 경우다. 그런 경우 §01.6.8에서 `REQUIREMENT-WRONG`, `RESULT-INVALID`, `GENUINE-FINDING` 중 하나로 분류하고 M1-A를 닫지 않는다.

### 01.1.3 Critic-locked conjunct oracle

| M1-A conjunct | 고정 evidence | PASS 판정 | 불일치 처리 |
|---|---|---|---|
| delta·margin | `tests/test_policy_gates_unit.py::{test_maximize_preserves_delta_and_margin_across_both_hard_veto_paths,test_minimize_preserves_delta_and_margin_across_both_hard_veto_paths}` | E1/E2 네 paired rows exact match | 해당 conjunct ❌, phase `ADVANCE` 이하 |
| typed gates | 같은 파일의 `test_gte_and_lte_slack_exact_cases`, `test_gate_permutations_preserve_complete_evidence_and_dominance`, invalid/missing/overflow config/policy tests | E3/E4 exact + 모든 permutation의 gate-ID별 evidence 완전성 + stable dominance/fail-closed | 해당 conjunct ❌, phase `ADVANCE` 이하 |
| baseline symmetry | `tests/test_baseline_verify_symmetry.py`의 real subprocess lifecycle suite | repeat별 digest/response/pre-post immutable/artifact recapture binding; E5/E6/E8 event counts exact | 해당 conjunct ❌, phase `ADVANCE` 이하 |
| certification | `tests/test_evaluator_certification_unit.py` + `tests/test_evaluator_certification_cli.py` | E7/E8 exact; 성공 stdout 전부 JSON, 실패 stdout empty | 해당 conjunct ❌, phase `ADVANCE` 이하 |
| 공통 regression/authority | explicit focused command + Python 3.12 full suite + `test_m1a_changed_surfaces_keep_authority_null` recursive scan | 모든 신규/기존 test PASS; changed Decision/event/CLI surface를 열거한 분모 `>0`, non-null `0` | M1-A `CLOSE` 금지 |

baseline real-subprocess test는 adapter가 받은 operation/result digest를 durable trace로 남기고 event payload의 repeat별 verification과 대조한다. verifier가 source 또는 artifact를 변조하는 두 mode에서는 verify 이후 immutable/recapture 검사와 `BASELINE_RECORDED == 0`을 각각 판정한다. gate permutation test는 constitution 순서와 무관하게 gate-ID로 정규화한 모든 evaluation이 존재하는지 비교하며 첫 실패 short-circuit를 허용하지 않는다.

## 01.2 무엇을 만들었나

| 작업 | 위치 | LOC | 검증 산출물 |
|---|---|---:|---|
| typed gate contract/config/policy | 계획: `contracts/results.py`, `config.py`, `policy.py` | TBD | 계획: unit + service E2E |
| baseline VERIFY symmetry | 계획: `service.py` | TBD | 계획: lifecycle/regression tests |
| nested certification normalization + atomic CLI JSON | 승인된 dirty patch 포함; `certification.py`, `service.py`, `cli.py` | TBD | 계획: unit + real CLI lifecycle |
| 문서·예제 계약 | 계획: examples/docs as needed | TBD | 계획: protocol example tests |

## 01.3 검증 (근거)

- 구현 전 기준선: `uv run --python 3.12 --with pytest --no-project env PYTHONPATH=src pytest -q` → `262 passed, 57 subtests passed in 55.31s`.
- 신규 집중 테스트: 구현 후 기록.
- 전체 regression/정적 검사: 구현 후 기록.
- critic verify와 독립 auditor: 구현 후 기록.

## 01.4 결과 vs 가설

| 가설 | 실제 측정값 | 차이 사유 |
|---|---|---|
| E1~E9가 exact 일치하고 M1-A 4 conjunct를 모두 닫는다 | 구현 전 — 미측정 | 구현 후 기록 |

## 01.5 발견된 부수 이슈

- 현재 없음. 구현 중 관찰되지만 M1-A 밖인 항목은 질문/근거와 함께 여기에 남긴다.

## 01.6 시스템 영향 분석 ★

- 이 phase 이전: evaluator-owned opaque constraint가 delta보다 먼저 veto하고, baseline은 candidate VERIFY 경계와 비대칭이며, nested immutable fingerprint는 일부 API 경계에서 JSON 직렬화가 불안정하다.
- 이 phase 이후 목표: veto와 무관한 delta/margin 및 kernel-owned typed slack이 terminal evidence에 남고, baseline/candidate가 대칭 검증되며, nested/flat certification lifecycle이 모두 replay 가능하다.
- 실제로 가능해질 행동: M1-D Diagnosis가 “효과 없음 / hard 위반 / support 부족”을 exact numeric evidence로 구분한다.
- 실제로 불가능해질 행동: unverified baseline이나 missing/non-finite gate observation이 candidate 승격을 지지하는 것.
- downstream: M1-B~D scientific state가 trustworthy evidence semantics를 소비할 수 있다.
- 외부 관찰: 새 constitution gate와 Decision evidence shape이 CLI/event output에 보이며, v0.2 legacy log는 무변환 replay한다.

## 01.6.4 마일스톤 진척 청구 (Milestone Position) ★

**영향 받은 M_i.j**: `M1-A`

**계획 라벨**: _CLOSE_ — 아래 네 conjunct가 모두 재현 가능한 evidence로 ✅일 때만 실제 CLOSE로 바꾼다.

| conjunct | 이전 상태 | 이번 phase 목표 | 근거 |
|---|---|---|---|
| veto 전 maximize/minimize delta·margin tests PASS | ❌ | ✅ | E1/E2 집중 tests + terminal Decision evidence |
| typed gte/lte, hard/support, signed/normalized slack fail-closed tests PASS | ❌ | ✅ | E3/E4 + invalid/missing/overflow tests |
| baseline verify 대칭 tests PASS | ❌ | ✅ | E5/E6/E8 lifecycle tests |
| nested certification CLI lifecycle + flat legacy replay PASS | 기존 dirty patch 탐색적 | ✅ | E7/E8 unit + real CLI tests |

- 모든 conjunct ✅ 확인 [ ]
- status §2.3에서 `M1-A=closed`, `M1-B=active` 갱신 [ ]
- parent M1은 M1-B~E가 남으므로 open 유지 [x]
- Prerequisite: M1은 첫 milestone이므로 N/A; gate-bypass 없음.

## 01.6.5 종착지 비전 갱신 (end-state delta) ★

- 이 phase 이전: pipeline §8.4 Evidence semantics는 “arbitrary constraint + pass/status, baseline verify 비대칭”.
- 이 phase 이후 목표:
  - Evidence semantics: “directional delta + constitution-owned typed gate/slack + baseline/candidate verify symmetry”를 실행 증거로 구체화한다.
  - Compatibility/authority: nested immutable fingerprint CLI와 flat legacy certificate replay, changed authority surface non-null 0의 current evidence를 보강한다.
- 계획 Delta: **두 영역 구체화**; §8.4 endpoint 자체·NS/M exit 기준은 약화하거나 바꾸지 않는다.
- 제거/포기 항목: 없음.
- 그대로 유지: Study control 이후 영역과 v0.5 unseen benchmark gate; M1-A 범위 밖이다.
- pipeline §8.5 Cycle 01 행: 구현/검증 후 추가 [ ].

## 01.6.6 의도-실행 정합 (Intent-Execution Reconciliation) ★

**계획 라벨**: _MATCH_

- 의도: NS1·NS2를 위해 M1-A 네 conjunct를 모두 닫고 §8.4 Evidence semantics를 구체화한다.
- 실행: 구현 후 실제 파일·test count·event/CLI 측정을 기록한다.
- PIVOT/DRIFT가 발생하면 MATCH로 닫지 않고 status §2 Decision chain 또는 correction phase를 먼저 갱신한다.

## 01.6.7 Claim Mode (청구 등급) ★

**계획 라벨**: _MIXED_

| 청구 행 | 등급 | 근거 계획 |
|---|---|---|
| 승인 전에 존재한 certification normalization patch의 결함 수정 | EXPLORATORY | 코드 변경이 bootstrap pre-spec보다 먼저 존재했으므로 confirmatory로 청구하지 않는다. full lifecycle 회귀는 경계를 넓히지만 이 행의 등급을 소급 승격하지 않는다. |
| typed gate·delta/margin·baseline VERIFY 신규 동작 | CONFIRMATORY 목표 | 본 phase plan+critic pre-spec checkpoint hash/timestamp가 구현·신규 결과 노출 commit보다 앞서야 한다. hash는 checkpoint 후 기록한다. |
| 기존 full regression 보존 | CONFIRMATORY 목표 | 사전 고정 E9와 구현 후 독립 full-suite 결과를 commit 순서로 기록한다. |

- Pre-spec checkpoint: `PENDING`.
- 첫 데이터 노출 commit: `PENDING`.
- timestamp 순서 확인: 구현 후 기록.

## 01.6.8 Requirement-Result Divergence ★

구현 전 분류 신호를 다음처럼 고정한다. E1~E9 차이가 있으면 어떤 갈래든 M1-A CLOSE를 우선 차단한다.

- `REQUIREMENT-WRONG`: 두 독립 oracle(수기 산술/기존 v0.2 wire·replay contract)이 같은 결과를 내지만 E1~E9 또는 M1-A criterion 자체가 사용자 §1.4·§8 endpoint를 잘못 대표한다고 드러난 경우. 다음 행동은 Cycle 02 correction phase이며, §북극성/§8.4/M chain 의미가 바뀌면 Rule 9 사용자 retrospective까지 자동 요구한다.
- `RESULT-INVALID`: test harness가 operation/digest/event를 완전 관측하지 못함, fixture가 nondeterministic함, 잘못된 Python/runtime을 사용함, implementation bug로 사전 산술·wire oracle과 불일치함, 또는 측정 명령이 재현되지 않는 경우. 해당 결과는 §01.7 evidence에서 제외하고 동일 pre-spec 아래 harness/implementation을 수정한 뒤 전부 재측정한다.
- `GENUINE-FINDING`: harness·runtime·독립 oracle이 모두 유효하고 반복 재현되지만 기존 kernel의 문서화되지 않은 recovery/ordering/legacy interaction이 예상과 다르게 나타난 경우. 그 행은 §01.6.7에서 EXPLORATORY로만 청구하고, 최소 재현 fixture와 사전 고정 holdout regression을 다음 cycle에 수행한다. requirement 변경 없이 고칠 수 있더라도 이번 CLOSE 근거에는 포함하지 않는다.

실측 후 이 절 맨 앞에 `해당 없음 — E1~E9 exact match` 또는 실제 갈래/근거를 추가한다.

## 01.7 §북극성 갱신 (이 cycle 이후)

- NS1: 기존 regression + baseline/certification integrity evidence가 생기면 부분 진척. NS1 전체 attack manifest/release gate는 후속 phase이므로 갭=0 청구하지 않는다.
- NS2: evidence semantics capability만 부분 진척. NS2의 6/6 scientific state는 M1-B~E 후에만 닫힌다.

## 01.8 §pipeline 매핑 영향

- 목표: Stage 1 Evidence semantics `△ → ○`; Compatibility/authority의 current evidence 보강(등급은 v1 replay 전체 gate 전까지 유지).
- pipeline §8.4·§8.5·§10.1 갱신은 구현 증거 후 수행한다.
- 새 함정/메트릭이 발견되면 pipeline §1.2/§1.3에 반영한다.

## 01.9 비관 재채점 — 이 phase 자체

- unit/CLI synthetic lifecycle가 실제 외부 adapter 전부의 품질을 보장하지는 않는다.
- typed gate는 관측 의미가 올바른지를 증명하지 않고, constitution threshold/operator를 kernel이 일관되게 적용했다는 것만 보장한다.
- M1-A가 닫혀도 failure knowledge나 next-hypothesis 생성은 아직 생기지 않는다.

## 01.10 다음 1행동

- 단일 최우선 행동: M1-A 사전 critic 질문을 생성·응답하고 pre-spec checkpoint를 commit한다.
- 그 다음: disjoint ownership으로 typed policy, baseline symmetry, certification lifecycle를 구현하고 집중/전체 tests → critic verify → 독립 auditor 순서로 닫는다.
- 실패 시: exact divergence를 §01.6.8에 분류하고 해당 conjunct를 open으로 유지한다.
