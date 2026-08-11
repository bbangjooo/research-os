# Critic — Phase 12 (2026-08-12) — m3-b-finite-autonomy-loop

영향 §북극성 행: NS5. 단일 자율 루프 완결성, NS1. 무결성·권한 하위호환, NS3. Durable learning 객체, NS4. Program memory 정확도

## Q1 [proxy-vs-real]
NS5·NS3·NS4의 “Program memory 실제 소비”가 ID 전달 proxy가 아님을, actual M2/M3-A vertical에서 terminal Diagnosis→exact origin→Claim append/cold replay→새 Program head→현재 active/contradiction Claim과 이유가 포함된 next Context→재검증된 next DecisionPacket까지 하나의 실행 경로로 어떻게 증명할 것인가?

**Response: DIRECT.** `tests/test_m3b_finite_autonomy.py::test_m3b_next_context_revalidates_a_fresh_packet_on_current_program_head`
runs the actual M2 store/M3-A packet path through terminal→Diagnosis→origin→Claim, then checks the new Program head,
nonempty active/contradiction hits and reasons, and successful preflight of a fresh second packet. Focused result:
`51 passed`; receipt witness `next_context_current_program_head_and_packet_revalidation`.

## Q2 [measurement-gap]
NS5 정의의 “7 transition 모두 canonical state로 재개 가능” 중 crash-resume는 M3-C로 제외하면서 M3-B에서 `7/7`을 청구하므로, 각 숫자가 actual service-backed committed transition과 cold reducer 재현 중 무엇을 측정하며 아직 증명하지 않은 incomplete-step resume를 어떤 근거로 명시적으로 제외하는가?

**Response: DIRECT.** The frozen seven rows measure each nominal committed FSM edge and repeated-edge idempotency;
`test_m3b_cold_replay_and_terminal_summary_are_exact` re-reduces the committed AutonomyLog. They do not inject a
crash between started/completed events. `advance()` raises `AUTONOMY_INCOMPLETE_STEP` for that state, and §12.7
explicitly assigns exact incomplete-step recovery to M3-C.

## Q3 [counterfactual]
별도 AutonomyLog가 자기 유발 stale을 피했다는 설명이 우연한 단일 순서에만 성립하지 않음을, ProjectLog의 terminal/Diagnosis와 ProgramLog의 disposition/origin/Claim 쓰기마다 head·Context를 재계산하고 stale DecisionPacket은 거절하면서 세 로그의 exact refs로 동일 terminal summary를 cold replay하는 실제 interleaving으로 반증할 수 있는가?

**Response: DIRECT.** The actual episode writes terminal+Diagnosis to ProjectLog, disposition+origin+Claim to
ProgramLog, recomputes the next Context/head, rejects the frozen `stale-program-head` row, and cold-reduces exact
terminal/Diagnosis/Claim/ClassState refs. The Q1 witness then validates a second packet on that recomputed state.

## Q4 [boundary]
세 provider-call completion reserve는 호출 용량만 보장하고 유효 응답은 보장하지 않는데, experiment가 terminal이 된 뒤 diagnosis 또는 synthesis가 invalid/transport 실패를 반복해 invalid·provider·token·time 예산을 소진하는 경계에서도 undiagnosed terminal을 완료로 청구하거나 Claim을 부분 append하지 않고 exact stop reason·추가 evaluator 호출 0·세 로그 write delta를 결정적으로 보이는가?

**Response: DIRECT.** `test_m3b_post_terminal_invalid_output_stops_incomplete_without_rerun` parameterizes invalid
Diagnosis and invalid synthesis evidence. Both exhaust the invalid budget with exact reason, `complete=false`,
summary status `incomplete`, evaluator calls `1` total/extra `0`, terminal history `1`, and Claim history `0`.

## Q5 [end-state-positioning]
§8.4 Autonomy를 packet-only에서 finite evidence-bound episode로 실제 구체화하면서도 crash-resume·학습 품질은 open으로, Context와 Program memory는 consumer evidence만 강화된 것으로 유지했음을 §12.6.5와 pipeline §8.5 Cycle 12에서 어떤 전후 관찰 가능 행동·세 truth-owner 경계·잔여 갭으로 기록해 rating inflation이나 vision-loosening을 막을 것인가?

**Response: DIRECT.** §12.6.5 records observable before/after behavior and the three exclusive truth owners. It
leaves crash/incomplete-step resume at M3-C and unseen learning quality at M3-D, with no NS6/NS7 increase.

## Q6 [milestone-positioning]
M3-B를 `CLOSE`하려면 frozen `43/43` 합계만이 아니라 여섯 exit conjunct 각각에 actual M2/M3-A/service 실행, transition `7/7`, memory writeback, 반복 시 three-log delta `0/0/0`, closed-class registration 0, 다섯 stop precedence, sealed-service/summary exact refs의 독립 재현 근거가 모두 있어야 하는데 §12.6.4는 이를 어떤 파일·명령·receipt 행에 일대일 매핑하고 두 independent gate 전 M3-C를 계속 차단하는가?

**Response: DIRECT.** §12.6.4 maps all six conjuncts to receipt rows and executable tests: transition `7/7`,
writeback `1/1/1` plus next rebound, idempotency `0/0/0`, four closed guards with registration `0`, stop `5/5`,
and sealed service `1` with direct calls/authority `0`. M3-C stays blocked until critic and audit both PASS.

## Q7 [claim-mode-discipline]
새 43-case 계약·AutonomyLog event schema·stop precedence·three-call reserve를 `CONFIRMATORY`로 청구하려면 pre-spec `9069cbd`가 첫 product/data commit보다 이르고 manifest SHA·bytes가 그대로임을 어떤 git 명령과 timestamp로 증명하며, 첫 결과나 critic 뒤 추가·수정된 기준과 witness는 §12.6.7에서 어느 행을 `EXPLORATORY`로 분리해 `MIXED`로 강등할 것인가?

**Response: DIRECT.** `git show -s --format='%H %cI' 9069cbd ede020c` proves `04:05:38` before `04:51:09`;
`sha256sum tests/fixtures/autonomy/v1/m3b-manifest.json` remains `29684e…bc1`. §12.6.7 therefore keeps the frozen
43/six-conjunct result CONFIRMATORY but marks the post-data Q1 witness commit `64d7249` EXPLORATORY and the phase
`MIXED`.

## Q8 [divergence-diagnosis]
사전 예상 `43/43`, M3-B `6/6`, NS5 `7/7`, closed-class/direct-call/non-null-authority 0 또는 M3-A manifest 불변 중 하나라도 어긋나면 §12.6.8에서 fixture·runner 오염만 `RESULT-INVALID`로 철회·재측정하고, AutonomyLog/reservation 요구 자체의 부적합은 `REQUIREMENT-WRONG` correction phase로, 유효한 예상 밖 동작은 `GENUINE-FINDING`/EXPLORATORY holdout으로 보내는 판정 증거와 자동 후속 행동은 무엇인가?

**Response: DIRECT.** §12.6.8 records functional exact match and separately diagnoses the only divergence:
product gross `1,861 > 1,600` as an exploratory `GENUINE-FINDING`. M3-C must precommit retain/trim/rebaseline action.
Fixture contamination would force `RESULT-INVALID` remeasurement; owner/reservation misfit would block M3-C with
`REQUIREMENT-WRONG`. Neither occurred, so no correction phase is triggered now.
