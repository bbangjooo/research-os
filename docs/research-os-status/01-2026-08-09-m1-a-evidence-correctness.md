# §01 — M1-A Evidence Correctness (2026-08-09)

> Status: **CLOSED — critic PASS + independent auditor PASS**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §01
> 직전 phase: [`§00 Bootstrap`](00-bootstrap-retro.md)
> Pipeline 영향: [`docs/research-os-pipeline.md`](../research-os-pipeline.md) §1, §8.4 Evidence semantics·Compatibility/authority, §9.4 M1-A
> 구현 전 기준선: 보존 tag `research-os-m1a-working-tree-baseline` / commit `50c4957` / tree `b7523f4`, Python 3.12에서 `262 passed, 57 subtests passed`

## 01.0 한 단락 요약 (TL;DR)

M1-A는 veto와 무관한 방향 보정 metric delta·promotion margin, constitution 소유 typed gate의 signed/normalized slack, baseline/candidate `VERIFY` 대칭성을 구현했다. 승인된 기존 certification patch는 nested immutable fingerprint의 실제 CLI lifecycle과 flat legacy replay까지 회귀했다. 사전 고정 E1~E9는 모두 exact match했고 Python 3.12 전체 suite는 `290 passed, 67 subtests`다. 네 exit conjunct와 common regression oracle은 progress critic과 독립 7-pass auditor의 PASS로 닫혔다.

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
| typed gate contract/config/policy | `contracts/results.py`, `contracts/__init__.py`, `config.py`, `policy.py` | src `+521/-18` | `test_policy_gates_unit.py` + M1-A E2E (`+752`) |
| baseline VERIFY symmetry | `service.py` | src `+149/-11` | real-subprocess symmetry/attack suite (`+504`) |
| nested certification normalization + atomic CLI JSON | 승인된 dirty patch 포함; `certification.py`, `cli.py` | src `+22/-6` | unit + real CLI lifecycle (`+372/-1`) |
| 문서·예제 계약 | `README.md`, `docs/{adapter-protocol,architecture,new-project}.md`, protocol/failure tests | docs `+81/-20`, tests `+28/-8` | examples protocol + failure contract |

구현 checkpoint `ed76067` 전체는 18 files, `+2429/-64`다. 위 행은 파일 소유 기준이며 `service.py`의 inspect/baseline 경계처럼 둘 이상의 기능을 잇는 코드는 중복 계산하지 않았다.

## 01.3 검증 (근거)

- 구현 전 dirty-working-tree 기준선은 tag `research-os-m1a-working-tree-baseline`의 commit `50c495780b6bec6058b7f0ee4393f8217c4ed169`(tree `b7523f4ff1aa2a986544fcbc73744b76f6984db6`, parent `6f36a1b`)으로 보존했다. 별도 detached worktree에서 `uv run --python 3.12 --with pytest --no-project env PYTHONPATH=src pytest -q` → `262 passed, 57 subtests passed in 54.66s`.
- 위 보존 tree는 parent 대비 승인된 dirty certification 파일 두 개만 `+91/-2`다. bootstrap docs commit `e728df9`는 기준선 코드 commit이 아니라 진행 문서 checkpoint이며, clean tree 자체의 수치는 `261/54`다.
- M1-A 집중 suite: `uv run --python 3.12 --with pytest --no-project env PYTHONPATH=src pytest -q tests/test_policy_gates_unit.py tests/test_baseline_verify_symmetry.py tests/test_evaluator_certification_cli.py tests/test_evaluator_certification_unit.py tests/test_m1a_evidence_e2e.py tests/test_examples_protocol.py tests/test_failure_contract.py` → `65 passed, 16 subtests passed in 8.00s`.
- 전체 regression: 같은 Python 3.12 명령의 전체 `pytest -q` → `290 passed, 67 subtests passed in 64.34s`.
- 정적 검사: `ruff check src tests` → `All checks passed!`; `ty check src` → `All checks passed!`; `git diff --check` → exit `0`.
- 독립 구현 검토 1: policy/gate reviewer가 unsafe integer→float rounding fail-open을 발견했고 수정 후 `PASS`; focused `15 passed`.
- 독립 구현 검토 2: baseline integrity reviewer가 legacy validation skip과 failed/malformed VERIFY mutation dominance를 발견했고 수정 후 `PASS`; focused `11 passed, 9 subtests`.
- progress critic verify: `PASS`; 독립 재현 focused `65/16`, full `290/67`, ruff/ty/diff-check PASS, Q1~Q8 모두 DIRECT 판정.
- 독립 progress auditor 1차: `FAIL` — 문서가 dirty baseline을 `e728df9` clean tree에 잘못 귀속해 E9 재현성을 잃었다고 판정했다. unreachable Git tree에서 exact working tree를 복구·tag/commit으로 보존하고 `262/57`을 재측정했다.
- 독립 progress auditor 재감사: `PASS`; 전체 trail은 [`01-m1-a-evidence-correctness.audit.md`](01-m1-a-evidence-correctness.audit.md).

## 01.4 결과 vs 가설

| ID | 실제 측정값 | 판정 |
|---|---|---|
| E1 | maximize의 legacy/typed hard veto 모두 improvement `12`, margin `7`, `REJECTED/HARD_CONSTRAINT_FAILED` | exact match |
| E2 | minimize의 legacy/typed hard veto 모두 improvement `12`, margin `7`, `REJECTED/HARD_CONSTRAINT_FAILED` | exact match |
| E3 | gte observed `12/8/10` → signed `2/-2/0`, normalized `0.5/-0.5/0`, pass `T/F/T` | exact match |
| E4 | lte observed `8/12/10` → signed `2/-2/0`, normalized `0.5/-0.5/0`, pass `T/F/T` | exact match |
| E5 | repeats `2`에서 `BASELINE→VERIFY` 2쌍과 digest-bound verification evidence 2개 | exact match |
| E6 | negative/malformed VERIFY 및 verify 뒤 source/artifact/workspace mutation에서 `BASELINE_RECORDED` 0; post-check failure가 parse/cleanup 오류보다 우선 | exact match |
| E7 | nested fingerprint doctor/review-subject/certify/inspect exit `0`, stderr empty, JSON stdout, equivalent callback drift `0` | exact match |
| E8 | flat certificate와 verification-less legacy baseline replay PASS; 현재 비교에는 미사용 후 reseal, malformed legacy는 skip 전에 거절 | exact match |
| E9 | 전체 `290 passed, 67 subtests`; changed Decision/event/CLI surface authority key 분모 `>=6`, non-null `0` | exact match |

## 01.5 발견된 부수 이슈

- M1-A 이전 외부 adapter가 candidate-only `VERIFY`를 구현했다면 baseline 호출 추가는 adapter change-control이 필요하다. v0.5 전 live migration을 하지 않으므로 여기서 호환된다고 추정하지 않는다.
- typed gate 산술의 정확성은 metric observation의 과학적 타당성까지 보증하지 않는다. metric 의미·scope·seal은 M1-B/C의 contract 대상이다.
- M1-A는 Diagnosis·ClassState를 생성하지 않는다. 실패를 다음 가설 제약으로 바꾸는 핵심 능력은 M1-D까지 여전히 없다.

## 01.6 시스템 영향 분석 ★

- 이 phase 이전: evaluator-owned opaque constraint가 delta보다 먼저 veto하고, baseline은 candidate VERIFY 경계와 비대칭이며, nested immutable fingerprint는 일부 API 경계에서 JSON 직렬화가 불안정하다.
- 이 phase 이후: veto와 무관한 delta/margin 및 kernel-owned typed slack이 terminal evidence에 남고, baseline/candidate가 대칭 검증되며, nested/flat certification lifecycle이 모두 replay 가능하다.
- 실제로 가능해질 행동: M1-D Diagnosis가 “효과 없음 / hard 위반 / support 부족”을 exact numeric evidence로 구분한다.
- 실제로 불가능해질 행동: unverified baseline이나 missing/non-finite gate observation이 candidate 승격을 지지하는 것.
- downstream: M1-B~D scientific state가 trustworthy evidence semantics를 소비할 수 있다.
- 외부 관찰: 새 constitution gate와 Decision evidence shape이 CLI/event output에 보이며, v0.2 legacy log는 무변환 replay한다.

## 01.6.4 마일스톤 진척 청구 (Milestone Position) ★

**영향 받은 M_i.j**: `M1-A`

**실측 라벨**: _CLOSE_ — 아래 네 conjunct와 공통 regression/authority oracle이 모두 재현됐다.

| conjunct | 이전 상태 | 실측 상태 | 근거 |
|---|---|---|---|
| veto 전 maximize/minimize delta·margin tests PASS | ❌ | ✅ | E1/E2 4 paired rows exact; focused/full PASS |
| typed gte/lte, hard/support, signed/normalized slack fail-closed tests PASS | ❌ | ✅ | E3/E4 + permutation + missing/non-finite/unsafe-int PASS |
| baseline verify 대칭 tests PASS | ❌ | ✅ | E5/E6/E8 real subprocess + mutation dominance PASS |
| nested certification CLI lifecycle + flat legacy replay PASS | 기존 dirty patch 탐색적 | ✅ | E7/E8 unit + real CLI lifecycle PASS |

- 모든 conjunct ✅ 확인 [x]
- status §2.3에서 `M1-A=closed`, `M1-B=active` 갱신 [x]
- parent M1은 M1-B~E가 남으므로 open 유지 [x]
- Prerequisite: M1은 첫 milestone이므로 N/A; gate-bypass 없음.

## 01.6.5 종착지 비전 갱신 (end-state delta) ★

- 이 phase 이전: pipeline §8.4 Evidence semantics는 “arbitrary constraint + pass/status, baseline verify 비대칭”.
- 이 phase 이후:
  - Evidence semantics: “directional delta + constitution-owned typed gate/slack + baseline/candidate verify symmetry”를 실행 증거로 구체화한다.
  - Compatibility/authority: nested immutable fingerprint CLI와 flat legacy certificate replay, changed authority surface non-null 0의 current evidence를 보강한다.
- 실측 Delta: **두 영역 구체화**; §8.4 endpoint 자체·NS/M exit 기준은 약화하거나 바꾸지 않았다.
- 제거/포기 항목: 없음.
- 그대로 유지: Study control 이후 영역과 v0.5 unseen benchmark gate; M1-A 범위 밖이다.
- pipeline §8.5 Cycle 01 행: 구현·검증 delta 추가 [x].

## 01.6.6 의도-실행 정합 (Intent-Execution Reconciliation) ★

**실측 라벨**: _MATCH_

- 의도: NS1·NS2를 위해 M1-A 네 conjunct를 모두 닫고 §8.4 Evidence semantics를 구체화한다.
- 실행: exact typed gate·baseline VERIFY·certification lifecycle만 구현했고, 실제 파일·test count·event/CLI 측정을 기록했다.
- PIVOT/DRIFT 없음. live migration, Diagnosis/ClassState, M chain 의미는 건드리지 않았다.

## 01.6.7 Claim Mode (청구 등급) ★

**실측 라벨**: _MIXED_

| 청구 행 | 등급 | 근거 |
|---|---|---|
| 승인 전에 존재한 certification normalization patch의 결함 수정 | EXPLORATORY | 코드 변경이 bootstrap pre-spec보다 먼저 존재했으므로 confirmatory로 청구하지 않는다. full lifecycle 회귀는 경계를 넓히지만 이 행의 등급을 소급 승격하지 않는다. |
| typed gate·delta/margin·baseline VERIFY 신규 동작 | CONFIRMATORY candidate | pre-spec `c1f1b75`가 implementation/result checkpoint `ed76067`보다 먼저이고 E1~E8이 exact match했다. |
| 기존 full regression 보존 | CONFIRMATORY candidate | E9 사전 고정 뒤 보존 baseline `50c4957`의 `262/57`과 implementation checkpoint `ed76067`의 전체 `290/67`을 각각 detached/current tree에서 재현했다. |

- Pre-spec checkpoint: `c1f1b7551f19b258d8811654fd168fb3e1e506bb`, `2026-08-09T23:41:51+09:00`.
- 첫 implementation/result-bearing checkpoint: `ed76067a4af2936f9637f2fa3053df6d0b23822f`, `2026-08-10T00:23:41+09:00`.
- timestamp 순서: pre-spec가 41분 50초 선행. certification patch 행은 이 순서와 무관하게 EXPLORATORY다.
- Dirty baseline preservation: tag `research-os-m1a-working-tree-baseline` → commit `50c495780b6bec6058b7f0ee4393f8217c4ed169` → tree `b7523f4ff1aa2a986544fcbc73744b76f6984db6`; tree 내용은 original base `6f36a1b` + 승인된 certification patch 두 파일뿐이다. 보존 ref 생성 시각은 결과 뒤이므로 certification patch 등급을 승격하지 않고, E9의 사전 고정 expected count와 현재 full-suite 결과의 선후관계만 confirmatory 후보로 청구한다.

## 01.6.8 Requirement-Result Divergence ★

**최종 유효 측정: 해당 없음 — E1~E9 exact match.**

개발 중 독립 검토가 (1) JS-safe 범위 밖 정수의 float 반올림 fail-open, (2) malformed legacy baseline을 reseal 전에 완전 검증하지 않는 경로, (3) failed/malformed VERIFY가 mutation post-check보다 먼저 오류를 내는 경로를 발견했다. 이는 모두 `RESULT-INVALID` implementation defect로 분류해 당시 결과를 폐기했고, 동일 pre-spec 아래 regression을 추가한 뒤 focused/full suite 전체를 다시 측정했다. 수정 전 결과를 CLOSE 근거로 사용하지 않았다.

1차 progress audit에서는 문서가 dirty-working-tree `262/57`을 clean bootstrap docs commit `e728df9`에 귀속한 탓에 E9 evidence가 `RESULT-INVALID`로 판정됐다. 그 audit 결과를 CLOSE 근거에서 제외한 뒤 exact unreachable tree `b7523f4`를 보존 commit/tag로 승격하고 별도 checkout에서 `262/57`을 재현했다. 요구값·NS1·M1-A criterion은 바꾸지 않았으며, 최종 E9는 보존 baseline과 current full suite를 모두 재현 가능한 측정으로 다시 판정한다.

구현 전 분류 신호를 다음처럼 고정한다. E1~E9 차이가 있으면 어떤 갈래든 M1-A CLOSE를 우선 차단한다.

- `REQUIREMENT-WRONG`: 두 독립 oracle(수기 산술/기존 v0.2 wire·replay contract)이 같은 결과를 내지만 E1~E9 또는 M1-A criterion 자체가 사용자 §1.4·§8 endpoint를 잘못 대표한다고 드러난 경우. 다음 행동은 Cycle 02 correction phase이며, §북극성/§8.4/M chain 의미가 바뀌면 Rule 9 사용자 retrospective까지 자동 요구한다.
- `RESULT-INVALID`: test harness가 operation/digest/event를 완전 관측하지 못함, fixture가 nondeterministic함, 잘못된 Python/runtime을 사용함, implementation bug로 사전 산술·wire oracle과 불일치함, 또는 측정 명령이 재현되지 않는 경우. 해당 결과는 §01.7 evidence에서 제외하고 동일 pre-spec 아래 harness/implementation을 수정한 뒤 전부 재측정한다.
- `GENUINE-FINDING`: harness·runtime·독립 oracle이 모두 유효하고 반복 재현되지만 기존 kernel의 문서화되지 않은 recovery/ordering/legacy interaction이 예상과 다르게 나타난 경우. 그 행은 §01.6.7에서 EXPLORATORY로만 청구하고, 최소 재현 fixture와 사전 고정 holdout regression을 다음 cycle에 수행한다. requirement 변경 없이 고칠 수 있더라도 이번 CLOSE 근거에는 포함하지 않는다.

## 01.7 §북극성 갱신 (이 cycle 이후)

- NS1: 기존+신규 전체 suite 100% PASS, M1-A changed authority surface non-null `0`, baseline/certification 공격 회귀를 확보했다. 그러나 versioned attack manifest·전체 v1 replay·release evidence가 남아 있어 NS1은 부분 진척이다.
- NS2: 후속 scientific state가 소비할 typed evidence prerequisite를 확보했지만 정의된 6 capability 중 닫힌 항목은 여전히 `0/6`이다. M1-A 산술을 NS2 capability 하나로 과대계상하지 않는다.

## 01.8 §pipeline 매핑 영향

- Stage 1 Evidence semantics `△ → ○`.
- Compatibility/authority current evidence는 nested/flat lifecycle과 authority-null scan으로 보강했지만, v1 replay 전체 gate 전까지 종착지 도달로 보지 않는다.
- pipeline §8.4·§8.5·§10.1을 같은 cycle에서 동기화했다.

## 01.9 비관 재채점 — 이 phase 자체

- unit/CLI synthetic lifecycle가 실제 외부 adapter 전부의 품질을 보장하지는 않는다.
- typed gate는 관측 의미가 올바른지를 증명하지 않고, constitution threshold/operator를 kernel이 일관되게 적용했다는 것만 보장한다.
- M1-A가 닫혀도 failure knowledge나 next-hypothesis 생성은 아직 생기지 않는다.

## 01.10 다음 1행동

- 단일 최우선 행동: M1-B Study generation/cumulative budget의 exact schema·산술·TOCTOU oracle을 구현 전에 phase plan과 critic으로 고정한다.
- 그 다음: pre-spec checkpoint 뒤 canonical StudyContract/generation/budget ledger를 구현하고 M1-B 4 conjunct를 검증한다.
- certification normalization patch 자체의 EXPLORATORY 등급은 유지한다. M1-E pre-spec에서 새 frozen nested/flat replay fixture와 release lifecycle을 고정한 뒤 별도 confirmatory regression으로 재측정한다.
- 실패 시: M1-B divergence를 새 phase 파일에 분류하고 M1-B를 open으로 유지한다.
