# Critic — Phase 01 (2026-08-09) — m1-a-evidence-correctness

영향 §북극성 행: NS1 무결성·권한 하위호환, NS2 기계 강제 scientific state

> Verify state: **PASS** — Q1~Q8 모두 DIRECT. critic 독립 재현: focused `65/16`, full `290/67`, ruff/ty/diff-check PASS; pre-spec `c1f1b75`가 implementation `ed76067`보다 선행; M1-A 4/4와 NS1 부분/NS2 0/6 판정 일치.

## Q1 [milestone-positioning]
`M1-A CLOSE`는 네 exit conjunct 모두의 재현 증거를 요구하는데, §01.6.4에서 E1~E9 중 어느 exact test·CLI command·event assertion이 각 conjunct를 완전히 닫으며 하나라도 불일치하면 `ADVANCE`로 강등한다는 판정표를 어떻게 고정할 것인가?

**Response:** _DIRECT_
Phase §01.1.3의 critic-locked conjunct oracle이 네 conjunct별 exact test 이름, real CLI/subprocess 경계, event assertion과 공통 regression/authority scan을 고정했다. §01.3~§01.4의 보존 baseline `50c4957`에서 `262/57`, focused `65+16`, current full `290+67`, E1~E9 exact 결과와 §01.6.4의 4/4가 이 oracle을 닫는다. 어느 하나라도 달랐다면 해당 행 ❌ 및 phase `ADVANCE` 이하였지만 최종 유효 측정에는 불일치가 없다.

## Q2 [end-state-positioning]
`NS1`의 nested certification lifecycle·flat legacy replay는 §8.4 `Compatibility/authority`에도 직접 해당하는데 Phase 01이 `Evidence semantics`만 구체화한다고 쓰면 비전 delta가 누락되므로, Cycle 01에서 두 영역을 함께 갱신할 것인지 아니면 certification 작업이 Evidence semantics에만 속한다는 경계 근거가 무엇인가?

**Response:** _DIRECT_
두 영역을 함께 갱신했다. Phase §01.6.5와 pipeline §8.4 두 current-state cell, §8.5 Cycle 01, §10.1에 Evidence semantics의 typed delta/gate/baseline symmetry와 Compatibility/authority의 nested/flat certification replay·authority-null current evidence를 분리해 기록했다. endpoint/exit criterion의 의미 변경은 아니다.

## Q3 [claim-mode-discipline]
`NS1` 관련 certification 코드·테스트가 이미 dirty worktree에 있고 §01.6.7의 pre-spec hash가 `PENDING`인데, typed gate·baseline VERIFY의 confirmatory 행만 사전 명세로 인정되도록 어떤 docs-only pre-spec commit과 첫 구현·신규 결과 노출 commit을 구분하며 pre-spec 전에 worker가 코드를 쓰지 않았음을 어떻게 검증할 것인가?

**Response:** _DIRECT_
docs-only pre-spec은 `c1f1b7551f19b258d8811654fd168fb3e1e506bb` (`2026-08-09T23:41:51+09:00`), 첫 implementation/result-bearing checkpoint는 `ed76067a4af2936f9637f2fa3053df6d0b23822f` (`2026-08-10T00:23:41+09:00`)다. 전자가 41분 50초 선행한다. 승인 전에 dirty였던 exact tree는 tag `research-os-m1a-working-tree-baseline`/commit `50c4957`로 보존했지만 certification patch 행은 관계없이 `EXPLORATORY`, typed gate·baseline VERIFY와 고정 full regression 행만 `CONFIRMATORY candidate`로 기록했다.

## Q4 [divergence-diagnosis]
`NS2`의 E1~E9 exact 결과가 하나라도 어긋날 때 §01.6.8은 단지 세 갈래 중 하나를 고른다고만 하는데, 어떤 관측 신호가 `REQUIREMENT-WRONG`·`RESULT-INVALID`·`GENUINE-FINDING`을 각각 판별하며 각 갈래가 correction·재측정·exploratory 후속 검증 중 무엇을 자동 요구하는가?

**Response:** _DIRECT_
Phase §01.6.8에 구현 전 신호와 자동 후속 행동을 고정했다. 실제로 독립 구현 검토가 unsafe-int rounding, malformed legacy validation skip, failed/malformed VERIFY mutation dominance 결함을 찾아 `RESULT-INVALID`로 처리했다. 수정 전 결과는 폐기하고 같은 pre-spec 아래 회귀를 추가한 뒤 focused/full suite를 전부 다시 측정했다. `REQUIREMENT-WRONG`이나 `GENUINE-FINDING`은 발생하지 않았다.

## Q5 [counterfactual]
`NS2`의 E1/E2가 “hard veto”를 legacy constraint와 새 typed hard gate로 분리하지 않으면 한 코드 경로에서만 delta가 보존돼도 통과할 수 있는데, maximize/minimize 각각 두 veto 경로 모두에서 improvement `12`와 margin `7`이 동일하게 남는다는 paired evidence는 무엇인가?

**Response:** _DIRECT_
Phase E1/E2의 maximize/minimize × legacy/typed hard veto 4-row oracle가 모두 improvement `12`, promotion margin `7`, `REJECTED/HARD_CONSTRAINT_FAILED`로 exact 통과했다. 근거는 `tests/test_policy_gates_unit.py::{test_maximize_preserves_delta_and_margin_across_both_hard_veto_paths,test_minimize_preserves_delta_and_margin_across_both_hard_veto_paths}`다.

## Q6 [measurement-gap]
`NS1`의 baseline VERIFY 대칭성은 E5의 호출 수 `2`만으로 증명되지 않는데, 각 repeat의 result digest·VERIFY 응답·verify 전후 immutable 검사·artifact recapture가 동일 baseline event에 결합되고 negative/mutation 경로에서는 `BASELINE_RECORDED`가 0건임을 real subprocess 경계에서 무엇으로 검증하는가?

**Response:** _DIRECT_
`tests/test_baseline_verify_symmetry.py` real subprocess suite가 adapter durable trace의 repeat별 `BASELINE→VERIFY` operation/result digest와 `BASELINE_RECORDED.verifications`를 대조한다. source/artifact/workspace mutation과 malformed/negative VERIFY에서 event count `0` 및 post-check dominance를 통과했고, legacy verification-less event는 replay PASS·current comparison skip/reseal, malformed legacy는 skip 전 거절로 E8을 닫았다.

## Q7 [boundary]
`NS2`의 E3/E4 단일 gate 사례만으로는 첫 실패에서 short-circuit하지 않고 모든 slack을 보존한다는 보장이 없는데, hard/support gate의 순서·operator를 바꾼 permutation에서도 complete gate evidence와 최종 status/reason이 순서 독립적임을 어떤 테스트가 판정하는가?

**Response:** _DIRECT_
`tests/test_policy_gates_unit.py::test_gate_permutations_preserve_complete_evidence_and_dominance`가 hard/support와 gte/lte 정의 순서를 permutation하고 gate ID로 정규화한 모든 observed/signed/normalized slack을 exact 비교해 통과했다. hard failure dominance와 support-only `INSUFFICIENT_EVIDENCE/SUPPORT_GATE_FAILED`, definition/evidence 완전성도 순서 독립적으로 통과했다.

## Q8 [falsifiable]
`NS1`의 E9 “`authorized_action` non-null 0”은 관측한 payload 분모가 없으면 필드를 검사하지 않고도 0이 될 수 있는데, Phase 01이 새로 만들거나 변경하는 Decision·event·CLI JSON surface 전체를 열거하고 non-null 발생 시 실패시키는 exact test 또는 scan command는 무엇인가?

**Response:** _DIRECT_
`tests/test_m1a_evidence_e2e.py::test_m1a_changed_surfaces_keep_authority_null`은 typed Decision, candidate terminal Decision/event, baseline event/verification, doctor/review-subject/certify/inspect CLI JSON을 명시적으로 수집해 재귀 scan한다. authority key 분모 `>=6`과 값 전부 `None`을 통과했고, authority field가 없는 subject/certification surface도 별도 exact-empty assertion으로 열거했다.
