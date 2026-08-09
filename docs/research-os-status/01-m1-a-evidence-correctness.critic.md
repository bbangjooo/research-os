# Critic — Phase 01 (2026-08-09) — m1-a-evidence-correctness

영향 §북극성 행: NS1 무결성·권한 하위호환, NS2 기계 강제 scientific state

## Q1 [milestone-positioning]
`M1-A CLOSE`는 네 exit conjunct 모두의 재현 증거를 요구하는데, §01.6.4에서 E1~E9 중 어느 exact test·CLI command·event assertion이 각 conjunct를 완전히 닫으며 하나라도 불일치하면 `ADVANCE`로 강등한다는 판정표를 어떻게 고정할 것인가?

**Response:** _DIRECT_
Phase §01.1.3의 critic-locked conjunct oracle이 네 conjunct별 exact test 이름, real CLI/subprocess 경계, event assertion과 공통 regression/authority scan을 고정한다. §01.6.4는 네 행 모두 ✅이며 공통 regression도 PASS일 때만 `CLOSE`로 전환하고, 어느 하나라도 다르면 해당 행 ❌ 및 phase `ADVANCE` 이하로 강등한다. 구현 후 집중/full command와 commit을 §01.3에 기록한다.

## Q2 [end-state-positioning]
`NS1`의 nested certification lifecycle·flat legacy replay는 §8.4 `Compatibility/authority`에도 직접 해당하는데 Phase 01이 `Evidence semantics`만 구체화한다고 쓰면 비전 delta가 누락되므로, Cycle 01에서 두 영역을 함께 갱신할 것인지 아니면 certification 작업이 Evidence semantics에만 속한다는 경계 근거가 무엇인가?

**Response:** _DIRECT_
두 영역을 함께 갱신한다. Phase §01.1과 §01.6.5에 Evidence semantics의 typed delta/gate/baseline symmetry와 Compatibility/authority의 nested/flat certification replay·authority-null current evidence를 분리했다. 구현 증거 후 pipeline §8.4 두 current-state cell, §8.5 Cycle 01, §10.1을 같은 cycle에서 갱신한다. endpoint/exit criterion의 의미 변경은 아니다.

## Q3 [claim-mode-discipline]
`NS1` 관련 certification 코드·테스트가 이미 dirty worktree에 있고 §01.6.7의 pre-spec hash가 `PENDING`인데, typed gate·baseline VERIFY의 confirmatory 행만 사전 명세로 인정되도록 어떤 docs-only pre-spec commit과 첫 구현·신규 결과 노출 commit을 구분하며 pre-spec 전에 worker가 코드를 쓰지 않았음을 어떻게 검증할 것인가?

**Response:** _DIRECT_
이 phase plan+critic+bootstrap operational close만 explicit path로 stage한 docs-only commit을 pre-spec으로 만든다. commit 직전 `git diff --cached --name-only`에 `docs/` 밖 0개, `git diff -- src/research_os/certification.py tests/test_evaluator_certification_unit.py`에 승인 전 dirty patch가 그대로 존재함을 기록한다. 그 hash/timestamp를 §01.6.7에 넣고, 이후 첫 implementation/result-bearing commit hash/timestamp와 `git log`로 순서를 비교한다. certification patch 행은 관계없이 `EXPLORATORY`, typed gate·baseline VERIFY와 고정 full regression 행만 `CONFIRMATORY` 후보다.

## Q4 [divergence-diagnosis]
`NS2`의 E1~E9 exact 결과가 하나라도 어긋날 때 §01.6.8은 단지 세 갈래 중 하나를 고른다고만 하는데, 어떤 관측 신호가 `REQUIREMENT-WRONG`·`RESULT-INVALID`·`GENUINE-FINDING`을 각각 판별하며 각 갈래가 correction·재측정·exploratory 후속 검증 중 무엇을 자동 요구하는가?

**Response:** _DIRECT_
Phase §01.6.8에 구현 전 신호와 자동 후속 행동을 고정했다. user goal/end-state를 잘못 대표한 criterion은 `REQUIREMENT-WRONG→correction(+필요시 Rule 9)`, 불완전 harness·wrong runtime·implementation bug·비재현 측정은 `RESULT-INVALID→evidence 제외+동일 pre-spec 재측정`, 유효한 독립 oracle에서 재현되는 문서화되지 않은 kernel interaction은 `GENUINE-FINDING→EXPLORATORY+pre-fixed holdout regression`이며 세 갈래 모두 이번 CLOSE를 차단한다.

## Q5 [counterfactual]
`NS2`의 E1/E2가 “hard veto”를 legacy constraint와 새 typed hard gate로 분리하지 않으면 한 코드 경로에서만 delta가 보존돼도 통과할 수 있는데, maximize/minimize 각각 두 veto 경로 모두에서 improvement `12`와 margin `7`이 동일하게 남는다는 paired evidence는 무엇인가?

**Response:** _DIRECT_
Phase E1/E2를 maximize/minimize × legacy/typed hard veto의 4-row oracle로 수정했다. `tests/test_policy_gates_unit.py::{test_maximize_preserves_delta_and_margin_across_both_hard_veto_paths,test_minimize_preserves_delta_and_margin_across_both_hard_veto_paths}`가 각 두 경로에서 improvement `12`, promotion margin `7`, `REJECTED/HARD_CONSTRAINT_FAILED`를 exact assert하도록 사전 고정됐다.

## Q6 [measurement-gap]
`NS1`의 baseline VERIFY 대칭성은 E5의 호출 수 `2`만으로 증명되지 않는데, 각 repeat의 result digest·VERIFY 응답·verify 전후 immutable 검사·artifact recapture가 동일 baseline event에 결합되고 negative/mutation 경로에서는 `BASELINE_RECORDED`가 0건임을 real subprocess 경계에서 무엇으로 검증하는가?

**Response:** _DIRECT_
Phase §01.1.3이 `tests/test_baseline_verify_symmetry.py` real subprocess suite를 고정한다. adapter durable trace의 repeat별 `BASELINE→VERIFY` operation/result digest와 `BASELINE_RECORDED.verifications`를 대조하고, verify 전후 immutable check 및 exact artifact recapture를 source-mutation/artifact-mutation mode로 각각 깨뜨려 event count `0`을 assert한다. legacy verification-less event는 replay PASS지만 current baseline lookup은 skip/reseal하는 별도 assertion으로 E8을 분리한다.

## Q7 [boundary]
`NS2`의 E3/E4 단일 gate 사례만으로는 첫 실패에서 short-circuit하지 않고 모든 slack을 보존한다는 보장이 없는데, hard/support gate의 순서·operator를 바꾼 permutation에서도 complete gate evidence와 최종 status/reason이 순서 독립적임을 어떤 테스트가 판정하는가?

**Response:** _DIRECT_
`tests/test_policy_gates_unit.py::test_gate_permutations_preserve_complete_evidence_and_dominance`가 hard/support와 gte/lte 정의 순서를 permutation하고 결과를 gate ID로 정규화해 모든 ID의 observed/signed/normalized slack이 존재하는지 비교한다. hard failure가 있으면 순서와 무관하게 `HARD_CONSTRAINT_FAILED`가 지배하고, hard가 모두 pass한 support-only failure는 `INSUFFICIENT_EVIDENCE/SUPPORT_GATE_FAILED`가 되며 evidence count가 definition count보다 작으면 실패한다.

## Q8 [falsifiable]
`NS1`의 E9 “`authorized_action` non-null 0”은 관측한 payload 분모가 없으면 필드를 검사하지 않고도 0이 될 수 있는데, Phase 01이 새로 만들거나 변경하는 Decision·event·CLI JSON surface 전체를 열거하고 non-null 발생 시 실패시키는 exact test 또는 scan command는 무엇인가?

**Response:** _DIRECT_
Phase §01.1.3의 `test_m1a_changed_surfaces_keep_authority_null`은 typed Decision dict, persisted candidate terminal Decision/event, new baseline event/verification payload, doctor/review-subject/certify/inspect CLI JSON을 명시적으로 수집해 재귀 scan한다. `authorized_action` key 분모가 `>0`인지 먼저 assert하고 발견된 값 전부가 `None`인지 판정하며, changed surface의 새 non-null 값 하나라도 있으면 실패한다. CLI surface에 authority key가 없다는 사실은 별도 명시적 surface enumeration으로 남겨 “0개를 검사해 0”인 주장을 하지 않는다.
