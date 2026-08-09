# Critic — Phase 03 (2026-08-10) — m1-c-typed-proposal-replication

영향 §북극성 행: NS1 무결성·권한 하위호환, NS3 Durable learning object

> Verify state: **PRE-SPEC REVIEW PASS** — Q1~Q8과 immutable oracle의 질문 품질·반증 가능성·chronology를 독립 critic이 구현 전에 검증했다. 구현 evidence Response는 계속 `PENDING`이며, 구현·측정 뒤에만 `DIRECT` 또는 `LIMITATION`으로 갱신한다.

## Q1 [external-validation]

StudyContract v2만 typed path를 활성화하면서 StudyContract v1의 실제 generation→registration→terminal finding→retry→terminal finding 경로가 byte-for-byte 그대로라는 증거가 있는가? 8-event fixed corpus의 raw bytes/head, old ID component sequence, scientific state, projection, `study-status`, `replay`, service/CLI public shapes, replay 후 byte 불변과 frozen M1-B manifest 29/29를 모두 구현과 독립된 expected 값으로 고정해야 한다.

**Response:** _PENDING_

## Q2 [boundary]

Proposal이 candidate JSON이나 별도 orphan event가 아니라 한 `EXPERIMENT_REGISTERED`의 complete sibling bundle로 원자 저장되는가? exact 12-field schema, 21-key registration payload, 네 typed sibling, proposal-only event 0, digest/ID, UTF-8 boundary, null authority, CLI mutual exclusion, declared pointer와 실제 parent→candidate canonical diff의 exact equality를 positive/negative oracle로 반증 가능하게 해야 한다.

**Response:** _PENDING_

## Q3 [proxy-vs-real]

`evaluation_scope_id`가 단순 label/ID가 아니라 v2 capability gate, candidate-schema certification, 0-based scope baseline workspace, baseline event, adapter `baseline/verify/materialize/run/evaluate/verify`, identity와 replay 전체에 결박되는가? v2 typed run은 baseline을 자동 생성하지 않고 v1/no-generation scoped baseline과 holdout baseline을 거절해야 한다. 이 결박은 scope delivery identity만 증명하며 dataset 독립성·통계적 재현 성공은 증명하지 않는다고 명시해야 한다.

**Response:** _PENDING_

## Q4 [measurement-gap]

candidate body/digest, Proposal body/digest/ID, flat sibling, scope/generation, experiment ID를 직접 위조하거나 네 typed sibling 중 하나만 누락해도 locked append, cold reducer, projection rebuild, service replay 네 경로가 같은 stable code로 fail-closed하는가? projection `sync/rebuild`는 전체 scientific reduce가 성공한 뒤에만 SQL에 apply하고, history 없는 direct typed apply도 닫혀 있어야 한다.

**Response:** _PENDING_

## Q5 [counterfactual]

scientific replication이 오직 terminal same-generation/compatibility parent의 exact frozen candidate와 persisted class를 서로 다른 unused preregistered replication scope/manifest로 보내는 attempt 1일 때만 증가하는가? changed candidate, same/reused scope, class/role/parent 위반을 모두 거절하고, 실패 replication retry는 exact Proposal/scope를 상속하되 attempts/retries만 증가하고 replication count는 증가하지 않는 valid case가 있어야 한다.

**Response:** _PENDING_

## Q6 [claim-mode-discipline]

새 Proposal/scope/replication criterion을 `CONFIRMATORY`로 청구할 자격이 있는가? 구현과 독립된 generic data-only scenario oracle이 case 이름이나 implementation helper에 분기하지 않고, 53 negative rows의 concrete initial state/input/mutation/error/delta, 18 forged/semantic-diff/partial-bundle/mutated-retry rows의 네 replay path 총 72 matches, 20 unique manifest observed/expected exact equality를 먼저 고정해야 한다. docs+fixture-only pre-spec commit과 raw/canonical digests가 첫 product/result-bearing commit보다 앞서야 하고, actual service request capture와 forced one-winner race는 별도 재현 evidence여야 한다. chronology나 oracle digest가 어긋나면 M1-C 전체를 `EXPLORATORY`로 강등해야 한다.

**Response:** _PENDING_

## Q7 [milestone-positioning]

M1-C의 네 conjunct—Proposal schema/preflight, candidate/orchestration 분리, scope identity/replay, frozen-candidate replication/retry—가 모두 독립 evidence로 닫히기 전 `CLOSE`하지 않는가? 이 phase의 허용 진척은 NS1 강화와 NS3 `0/4→1/4`뿐이며, NS2는 `2/6` 그대로이고 pipeline Stage 3은 `✗→△`까지만 올라가야 한다.

**Response:** _PENDING_

## Q8 [end-state-positioning]

typed Proposal과 replication identity를 “실패를 지식으로 바꾸는 자율 연구” 또는 Graph Engineering 연구 공동체의 완성으로 과장하지 않는가? Diagnosis/ClassState/frontier는 M1-D, context/legacy isolation은 M1-E, Program memory는 M2, autonomous FSM·unseen effectiveness는 M3/NS6에 남기고, unseen synthetic benchmark를 v0.5 release gate로 유지하며 live project pilot/migration은 release 이후, product multi-agent는 NS6 이후로 유지해야 한다.

**Response:** _PENDING_

## Pre-spec verdict

**PASS** — 독립 critic 최종 `VERDICT: PASS`; matrix 독립 재감사도 `PASS`. Q1~Q8의 구현 evidence Response는 의도적으로 `PENDING`이며, docs+fixture-only checkpoint 뒤에만 제품 구현을 시작한다.
