# Critic — Phase 03 (2026-08-10) — m1-c-typed-proposal-replication

영향 §북극성 행: NS1 무결성·권한 하위호환, NS3 Durable learning object

> Verify state: **PRE-SPEC REVIEW PASS** — Q1~Q8과 immutable oracle의 질문 품질·반증 가능성·chronology를 독립 critic이 구현 전에 검증했다. 구현 evidence Response는 계속 `PENDING`이며, 구현·측정 뒤에만 `DIRECT` 또는 `LIMITATION`으로 갱신한다.

## Q1 [external-validation]

StudyContract v2만 typed path를 활성화하면서 StudyContract v1의 실제 generation→registration→terminal finding→retry→terminal finding 경로가 byte-for-byte 그대로라는 증거가 있는가? 8-event fixed corpus의 raw bytes/head, old ID component sequence, scientific state, projection, `study-status`, `replay`, service/CLI public shapes, replay 후 byte 불변과 frozen M1-B manifest 29/29를 모두 구현과 독립된 expected 값으로 고정해야 한다.

**Response: DIRECT.** Fixed 8-event corpus의 raw bytes/head/ID/state/projection뿐 아니라 실제 `ResearchService.study_status()`, `replay()`, `findings()`를 호출해 frozen digest와 replay 전후 bytes/head 불변을 계산한다. 별도 certified service/CLI lifecycle에서 generation/registration event와 baseline/open/run/status/replay, replay science, projection experiment/status의 10개 대응 surface canonical shape가 같음을 확인하고 frozen keyset `9/9`, shape digest `7/7`을 비교한다. M1-B frozen 29 cases도 `_observe_manifest_case`로 전부 재실행해 `29/29` actual match를 요구한다.

## Q2 [boundary]

Proposal이 candidate JSON이나 별도 orphan event가 아니라 한 `EXPERIMENT_REGISTERED`의 complete sibling bundle로 원자 저장되는가? exact 12-field schema, 21-key registration payload, 네 typed sibling, proposal-only event 0, digest/ID, UTF-8 boundary, null authority, CLI mutual exclusion, declared pointer와 실제 parent→candidate canonical diff의 exact equality를 positive/negative oracle로 반증 가능하게 해야 한다.

**Response: DIRECT.** Proposal exact 12 fields, UTF-8 `16,384` boundary, digest/ID, null authority와 canonical diff equality를 E4/E5가 검증하고, E7 actual service registration은 tokenless path의 exact 21-key payload·complete four-sibling bundle·proposal-only event 0·candidate typed key 0을 확인한다. Context-token path는 기존 token/snapshot 두 sibling을 정당하게 추가하지만 typed bundle의 원자 완전성은 동일하다. CLI mutual exclusion과 locked append도 actual 경로다.

## Q3 [proxy-vs-real]

`evaluation_scope_id`가 단순 label/ID가 아니라 v2 capability gate, candidate-schema certification, 0-based scope baseline workspace, baseline event, adapter `baseline/verify/materialize/run/evaluate/verify`, identity와 replay 전체에 결박되는가? v2 typed run은 baseline을 자동 생성하지 않고 v1/no-generation scoped baseline과 holdout baseline을 거절해야 한다. 이 결박은 scope delivery identity만 증명하며 dataset 독립성·통계적 재현 성공은 증명하지 않는다고 명시해야 한다.

**Response: DIRECT.** v2 capability와 certified candidate-schema gate, 0-based scoped baseline workspace, baseline/verify와 materialize/run/evaluate/verify의 full scope object, scope identity와 reducer/projection/replay를 E2/E3/E6/E7/E10~E12가 actual adapter request까지 확인한다. typed auto-baseline, v1/no-generation scoped baseline과 holdout은 no-write로 거절된다. 이 증거는 **scope delivery identity**만 보장하며 adapter가 manifest를 실제 dataset 선택에 올바르게 소비했는지, dataset 독립성이나 통계적 재현 성공은 certification/golden case의 책임이라는 limitation을 유지한다.

## Q4 [measurement-gap]

candidate body/digest, Proposal body/digest/ID, flat sibling, scope/generation, experiment ID를 직접 위조하거나 네 typed sibling 중 하나만 누락해도 locked append, cold reducer, projection rebuild, service replay 네 경로가 같은 stable code로 fail-closed하는가? projection `sync/rebuild`는 전체 scientific reduce가 성공한 뒤에만 SQL에 apply하고, history 없는 direct typed apply도 닫혀 있어야 한다.

**Response: DIRECT.** Reducer가 candidate/Proposal digest·ID, flat sibling과 experiment ID를 canonical body에서 재계산한다. Frozen transition `53/53`와 forged/semantic-diff/partial-bundle/mutated-retry 18 cases의 locked append/cold reducer/projection rebuild/service replay `72/72`가 같은 stable code·delta 0을 요구한다. Projection sync/rebuild는 full scientific reduce 뒤 SQL apply하고 historyless typed apply는 cursor 이동 없이 거절한다.

## Q5 [counterfactual]

scientific replication이 오직 terminal same-generation/compatibility parent의 exact frozen candidate와 persisted class를 서로 다른 unused preregistered replication scope/manifest로 보내는 attempt 1일 때만 증가하는가? changed candidate, same/reused scope, class/role/parent 위반을 모두 거절하고, 실패 replication retry는 exact Proposal/scope를 상속하되 attempts/retries만 증가하고 replication count는 증가하지 않는 valid case가 있어야 한다.

**Response: DIRECT.** E5/E8/E9와 actual service/retry/race가 terminal same-generation/compatibility parent, frozen candidate, persisted class, distinct unused replication scope/manifest, empty intervention, attempt 1을 모두 강제한다. changed candidate, same/reused scope, wrong role/class/parent를 거절하고 실패 replication retry는 Proposal/scope를 exact 상속하면서 attempts/retries만 증가하고 replication count는 유지한다.

## Q6 [claim-mode-discipline]

새 Proposal/scope/replication criterion을 `CONFIRMATORY`로 청구할 자격이 있는가? 구현과 독립된 generic data-only scenario oracle이 case 이름이나 implementation helper에 분기하지 않고, 53 negative rows의 concrete initial state/input/mutation/error/delta, 18 forged/semantic-diff/partial-bundle/mutated-retry rows의 네 replay path 총 72 matches, 20 unique manifest observed/expected exact equality를 먼저 고정해야 한다. docs+fixture-only pre-spec commit과 raw/canonical digests가 첫 product/result-bearing commit보다 앞서야 하고, actual service request capture와 forced one-winner race는 별도 재현 evidence여야 한다. chronology나 oracle digest가 어긋나면 M1-C 전체를 `EXPLORATORY`로 강등해야 한다.

**Response: DIRECT.** Confirmatory 자격은 **없다**. 최초 scenario contradiction과 production-control non-dispatch를 `RESULT-INVALID`로 제외하고 corrected checkpoint `575711f` 뒤에도 chronology로 자격을 복원하지 않아 M1-C 전체를 `EXPLORATORY`로 유지했다. Corrected manifest `20/20`, transition `53/53`, four-path `72/72`, actual service/request/race evidence는 exploratory implementation evidence로만 사용한다.

## Q7 [milestone-positioning]

M1-C의 네 conjunct—Proposal schema/preflight, candidate/orchestration 분리, scope identity/replay, frozen-candidate replication/retry—가 모두 독립 evidence로 닫히기 전 `CLOSE`하지 않는가? 이 phase의 허용 진척은 NS1 강화와 NS3 `0/4→1/4`뿐이며, NS2는 `2/6` 그대로이고 pipeline Stage 3은 `✗→△`까지만 올라가야 한다.

**Response: DIRECT.** Phase §03.6.4의 네 conjunct는 각각 E4/E5, E11, E3/E6/E7/E10/E12, E5/E8/E9/E13 actual evidence로 모두 ✅다. 다만 status는 `IMPLEMENTATION GATE PASS / CLOSE PENDING`이며 status core/pipeline 동기화와 독립 7-pass audit 전에는 close하지 않는다. 허용 진척도 NS1 강화, NS2 `2/6` 유지, NS3 `0→1/4`, Stage 3 `✗→△`로 제한한다.

## Q8 [end-state-positioning]

typed Proposal과 replication identity를 “실패를 지식으로 바꾸는 자율 연구” 또는 Graph Engineering 연구 공동체의 완성으로 과장하지 않는가? Diagnosis/ClassState/frontier는 M1-D, context/legacy isolation은 M1-E, Program memory는 M2, autonomous FSM·unseen effectiveness는 M3/NS6에 남기고, unseen synthetic benchmark를 v0.5 release gate로 유지하며 live project pilot/migration은 release 이후, product multi-agent는 NS6 이후로 유지해야 한다.

**Response: DIRECT.** Diagnosis/ClassState/frontier는 M1-D, context/legacy isolation은 M1-E, Program memory는 M2, autonomous FSM과 unseen effectiveness는 M3/NS6에 남아 있다. Unseen synthetic benchmark는 v0.5 release gate이고 실제 세 프로젝트 live pilot/migration은 v0.5 이후, product multi-agent는 NS6 이후라는 사용자 경계를 유지한다. M1-C를 자율 연구 또는 Graph Engineering 공동체의 완성으로 청구하지 않는다.

## Pre-spec verdict

**PASS** — 독립 critic 최종 `VERDICT: PASS`; matrix 독립 재감사도 `PASS`. Q1~Q8의 구현 evidence Response는 의도적으로 `PENDING`이며, docs+fixture-only checkpoint 뒤에만 제품 구현을 시작한다.

## Post-freeze oracle correction review

최초 pre-spec 기록과 PASS는 당시 chronology로 보존한다. 제품 구현 시작 뒤 transition observer가 선언된 deep-merge 의미와 충돌하는 5개 inherited `expected_state`와 미실행 `control_assertions`를 발견했으므로 해당 결과를 `RESULT-INVALID`로 제외했고, M1-C 전체 claim mode를 `EXPLORATORY`로 강등했다.

1차 독립 correction review는 정확히 5개 scenario 불일치와 정정 뒤 15/15 일치를 재현했지만, control observer dispatch 축 누락, literal `case_id_dispatches=0`, 이 durable review 기록 부재를 이유로 **FAIL**했다. correction checkpoint 전에 세 결함을 모두 보완하고 새 transition/manifest digest와 독립 재심 verdict를 아래에 고정한다.

- corrected transition raw: `1e9e8e60a18dfe0d610a4928ecb90933204d43c53796e00d253343093ed96dd0`
- corrected manifest raw / sorted-compact: `4b9c216ea7a6bcbd8aec00a2224e4c41c349c038ea4b1d7c7fafcc8721e31b1d` / `75d7e1e568f3d42463184544e4b396c6f68cd1ae91fc3d5026dffda8454dca67`
- case-ID discipline: display-only `id`를 observer input에서 구조적으로 제거하고, support interpreter와 transition observer source 양쪽을 실제 53개 ID 및 금지 access pattern으로 검사한다.
- production controls: `documents.*.control_assertions.observer`를 declared dispatch field로 추가하고, patch 전 source를 실제 `ResearchService.baseline`/validator 및 `reduce_scientific_state`로 검증한다.
- independent re-review: **VERDICT: PASS** — frozen pre-spec 대비 불일치가 정확히 5개 scenario였고 corrected scenario 15/15가 일치함을 독립 재현했다. 위 transition/manifest digest는 exact이며, declared production-control dispatch와 patch 전 실제 `ResearchService.baseline`/validator·`reduce_scientific_state` 실행, control metadata 비유입, display-only ID의 구조적 제거와 support/observer 양쪽 forbidden-access 및 53개 literal-ID 검사를 확인했다. Focused oracle은 `17 passed, 10 skipped`였고 skip은 아직 미결인 별도 product observer bindings이며 correction surface failure는 0이다. 최초 결과의 `RESULT-INVALID` 제외와 M1-C `EXPLORATORY` 강등을 유지한다.
- correction checkpoint: commit `575711fa7d11303340fd695ffcaa19e0a9270644`, tree `709dc93db23ce42f2f265f78f57016ed6e4c27ca`, parent `5ab51f10ffcbb8f6e79d92b0935f977f03094305`, commit time `2026-08-10T05:43:02+09:00`; phase/critic + transition/manifest 네 파일만 포함한다.

## Post-implementation progress verdict

**VERDICT: PASS** — latest reviewed HEAD `2e14096`; Q1~Q8 모두 `DIRECT`, product/evidence blocking defect 0. Implementation checkpoint `a783a88`에서 frozen manifest `20/20` skip 0, transition `53/53`, direct path `72/72`, Python 3.12 full `442 passed, 111 subtests`, ruff/ty/diff PASS를 확인했다. 후속 test-only checkpoints `6bc3905`, `6a35790`, `2e14096`은 각각 미생성 DB cold initializer, fixed v1 actual service/M1-B parity, service↔CLI canonical shape parity를 보강했고 targeted evidence가 PASS했다.

Carry-forward limitation은 세 가지다. Exact 21-key 표현은 tokenless E7 registration에 한정한다. Scope semantic consumption과 실제 dataset 독립성은 adapter certification/golden case 책임이다. Status core/pipeline sync와 독립 7-pass audit가 PASS하기 전에는 M1-C를 CLOSE하지 않는다.
