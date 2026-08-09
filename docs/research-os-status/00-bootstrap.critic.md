# Critic Bootstrap — research-os (2026-08-09)

대상: 초기 §북극성 표 + §1.4 진짜 목표 + §종착지 Cycle 0

## Q1 [vision-aligned]
`NS6. Fixed-budget 학습 효과`를 §8.4 `Meta-evaluation`과 §1.4의 “더 정확하고 덜 낭비적으로 다음 가설을 선택”에 정렬하려면 각 episode의 올바른 hypothesis-choice oracle과 선택 오류 정의가 필요한데, 현재 §7.2의 terminal/diagnosis oracle만으로 “다음 가설 선택” 개선을 어떻게 직접 판정하는가?

**Response:** _REVISED_
status §12.2 `NS6`과 그 아래 choice 판정 규칙, pipeline §7.2·§8.2·§9.4 M3-D를 수정했다. 이제 모든 non-terminal decision point가 exact 허용/최적 `(hypothesis_class, action)` oracle set을 가지며, set 밖 선택·closed/duplicate class·required decision 생략을 오류로 센다. `next-hypothesis choice accuracy ≥ min(90%, v0.2+20%p)`를 terminal decision과 별도 exit conjunct로 추가해 §1.4의 “다음 가설 선택”을 직접 측정한다.

## Q2 [proxy-vs-real]
`NS6. Fixed-budget 학습 효과`의 36개 synthetic episode가 구현자에게 전부 보이는 동일 저장소 fixture라면 suite-specific policy를 Research OS의 학습 능력으로 오인할 수 있는데, unseen acceptance partition 없이 이 지표가 §1.4의 진짜 목표를 대리하지 않는다는 것을 무엇으로 보장하는가?

**Response:** _REVISED_
status §12.2 `NS6` unseen 판정과 pipeline §7.2·§9.4 M3-D를 수정했다. 구현 전에는 generator schema/world family/oracle/metric만 commit하고, M3 code freeze 뒤 repo 밖 custody 경계에서 새 256-bit nonce로 36 unseen episode body를 생성한다. 한 receipt가 code commit·generator digest·nonce commitment·suite digest·두 arm 결과를 묶으며, 결과 노출 후 code/policy 변경은 receipt를 무효화한다. 따라서 release effectiveness 판정은 구현자에게 사전 노출된 고정 body가 아니라 post-freeze acceptance body에서만 성립한다.

## Q3 [measurable]
`NS1. 무결성·권한 하위호환`의 “protocol violation 차단률 100%”는 위반 universe와 분모가 고정되지 않으면 자명하게 100%가 될 수 있는데, 어떤 versioned attack manifest·fixture digest·재현 명령이 그 분모를 고정하는가?

**Response:** _REVISED_
status §12.2 `NS1`과 pipeline §7.2를 수정했다. `tests/fixtures/protocol_attacks/v1/manifest.json`의 전체 행이 분모이며 각 행은 surface/schema version, initial state, forbidden input, stable rejection code, no-write invariant를 가진다. manifest SHA-256과 재현 명령을 각 phase evidence에 기록하도록 고정했다.

## Q4 [falsifiable]
`NS2. 기계 강제 scientific state`의 “6/6 동작”에서 각 capability의 입력 상태·허용 transition·거절 code·class closure threshold가 명시된 판정표가 없는데, 독립 검증자가 같은 seeded transition으로 동일한 6개 ✅/❌를 어떻게 산출하는가?

**Response:** _REVISED_
status §12.2 `NS2`와 pipeline §2.2를 수정했다. `tests/fixtures/scientific_state/v1/manifest.json`이 여섯 capability별 initial state, submitted transition, expected next state 또는 stable rejection code, closure threshold, budget delta를 행 단위로 고정한다. 판정은 manifest exact-match 행 수/전체 행이며 SHA-256을 phase evidence에 기록한다.

## Q5 [independently-verifiable]
`NS4. Program memory 정확도`의 recall·contradiction·supersession·contamination 수치는 query 집합, scope 충돌, 동률 정렬, empty-result 처리와 분모가 정의되지 않았는데, 이를 고정한 retrieval oracle manifest 없이 누가 동일한 4/4 판정을 재현할 수 있는가?

**Response:** _REVISED_
status §12.2 `NS4`와 pipeline §5.2를 수정했다. `tests/fixtures/program_memory/retrieval-v1.json`이 query, scope/status/relations, candidate IDs와 exact ordered expected active/contradiction/superseded/irrelevant sets를 고정한다. canonical tie key, 각 recall/exclusion/contamination 분모, expected-empty exact-empty 규칙을 명시해 독립 실행이 같은 4/4를 산출하도록 했다.

## Q6 [proxy-vs-real]
`NS7. 기존 프로젝트 read-only 호환성`의 “무변환 replay 또는 `legacy_unstructured` 판정”이라는 OR 조건은 세 프로젝트를 모두 opaque로 격리해도 3/3 성공할 수 있는데, 실제 log 보존·replay와 의미 격리를 별도 conjunct로 요구하지 않으면 호환성의 대리지표가 아닌가?

**Response:** _REVISED_
status §12.2 `NS7`과 pipeline §9.4 M3-D를 AND 조건으로 수정했다. 세 프로젝트 모두 기존 complete event bytes/hash/derived v1 state 무변환 replay 3/3을 먼저 만족하고, 별도로 typed schema가 없는 legacy free text만 100% `legacy_unstructured`이며 자동 typed inference가 0건이어야 한다. before/after writer/file diff도 0이어야 하므로 opaque 격리만으로 통과할 수 없다.

## Q7 [milestone-prerequisite-realism]
`M2` prerequisite는 M1의 typed Diagnosis/ClassState·generation identity가 필요하다고 하지만 `M2-A ProgramManifest·ProgramLog`의 hash-chain·recovery·lock-order는 그 객체 없이도 시작 가능한데, M1의 어느 exit conjunct가 M2-A 시작의 기술적 전제이며 없다면 왜 M2-B/close만 gate하고 M2-A 병렬 착수를 허용하지 않는가?

**Response:** _REVISED_
pipeline §9.2 M2 prerequisite와 §9.4 M2-A exit conjunction을 수정했다. M2-A는 이제 M1-E가 닫은 stable StudyContract/generation/evaluation-scope schema version·digest를 ProgramManifest에 bind하고, M1 Diagnosis/ClassState origin evidence를 ProgramLog append 시 exact 검증해야 종료된다. 범용 hash-chain utility는 기존 EventLog에 이미 있어 선행 구현할 독립 가치가 없으며, M1 전 착수하면 unstable identity에 program format을 고정하므로 M1-E close가 M2-A의 기술적 전제다.

## Q8 [milestone-necessity-ordering]
`M3` prerequisite는 M2 memory가 없으면 loop가 v0.2 반복 실행기라고 하지만 `M3-A DecisionPacket`과 `M3-B`의 provider·FSM 기반은 M2 없이 구현·검증 가능하므로, `NS5. 단일 자율 루프 완결성` 구축까지 M2 close 뒤로 막는 순서가 논리적 의존성인지 단순 출시 순서인지 구분해 M chain을 수정해야 하지 않는가?

**Response:** _REVISED_
pipeline §9.2 M3 prerequisite와 §9.4 M3-A/M3-B exit conjunction을 수정했다. DecisionPacket은 M2-D의 ProgramSnapshot/head, retrieved Claim IDs/reasons, knowledge dispositions를 필수 bind하고, FSM은 매 next proposal에서 M2 retrieval을 읽고 synthesis에서 evidence-bound Claim/ClassState를 write back해야 한다. M2 없는 generic provider/FSM은 §1.4의 학습 loop가 아닌 기반 코드라 M3 진척으로 세지 않으므로 M2-D close가 packet read/write set을 정의하는 논리적 전제다.
