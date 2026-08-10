# §04 — M1-D Diagnosis, ClassState, and Semantic Frontier (2026-08-10)

> Status: **PRE-SPEC PASS — implementation forbidden until docs+fixture checkpoint commit**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §02
> 직전 phase: [`§03 M1-C`](03-2026-08-10-m1-c-typed-proposal-replication.md)
> Pipeline 영향: [`docs/research-os-pipeline.md`](../research-os-pipeline.md) §3, §8.4 Study inference, §9.4 M1-D
> 구현 전 기준선: commit `a5f232d`, Python 3.12에서 `442 passed, 111 subtests passed`

## 04.0 한 단락 요약 (TL;DR)

M1-D는 StudyContract v2의 모든 terminal experiment를 exact event/hash·Proposal·scope·quantitative decision·artifact evidence에 묶인 typed `Diagnosis`로 닫기 전에는 다음 registration, retry, successor generation을 허용하지 않는다. Agent가 적는 interpretation·failure type·falsifier·recommendation은 지식으로 보존하되 class count나 frontier 권한으로 신뢰하지 않는다. Kernel은 exact verified terminal evidence만으로 Proposal retry-chain당 conclusive rejection을 최대 한 번 세고, preregistered threshold에서 derived `ClassState`를 비가역적으로 닫는다. Semantic frontier는 active generation/compatibility의 diagnosed verified `VALIDATED` scientific leaves만 deterministic하게 고른다. 목표 §북극성은 NS1·NS2·NS3, 목표 종착지 delta는 실패를 replayable state와 다음 선택 입력으로 바꾸는 것이며, 목표 checkpoint는 M1-D 다섯 conjunct 전부 `CLOSE`다.

## 04.1 왜 이 작업을 하나

- 목표 §북극성:
  - **NS1 무결성·권한 하위호환** — Diagnosis/event/class/frontier 위조를 locked live path와 replay에서 같은 code로 fail-closed하고 모든 authority를 null로 유지한다.
  - **NS2 기계 강제 scientific state** — diagnosis gate, class closure, semantic frontier 세 capability를 canonical reducer가 직접 강제한다.
  - **NS3 Durable learning 객체** — Proposal에 이어 Diagnosis와 derived ClassState를 digest·origin evidence와 함께 replay한다.
- Trigger: M1-C는 terminal을 Proposal/class/scope에 연결했지만 실패 해석은 generic Finding/대화에 남고, 다음 registration은 diagnosis·class closure를 우회할 수 있다.
- 선택한 seam: dedicated namespaced `research.experiment_diagnosed.v1` event와 `science/state.py`의 pure reducer가 권위다. SQLite는 Diagnosis/ClassState truth를 소유하지 않는 rebuildable cache다.
- 범위 경계: Context v3와 complete legacy isolation은 M1-E, cross-project conditional Claim/Program memory는 M2, provider-neutral autonomous FSM과 unseen effectiveness는 M3다.
- 사용자 승인 경계: unseen synthetic benchmark는 v0.5 release gate다. `crypto-new`, `manager`, `BinancePredictionStrategy`의 live pilot·migration은 v0.5 이후이고 그 전에는 read-only다. 제품 multi-agent는 NS6 통과 이후다.
- 이 phase는 기존 M1-D 다섯 conjunct 의미를 바꾸지 않는다. M-chain Rule 9 retrospective는 적용하지 않는다.

### 04.1.1 activation과 authoritative control 정의

1. Diagnosis gate는 active `StudyContract.schema_version == 2`의 typed registrations에만 적용한다. Event envelope v1, science-state event literal 1, StudyContract v1, Proposal v1, context v2, branch conclusion v1은 수정하지 않는다.
2. 현 Proposal v1·StudyContract v2에는 registered control을 선언하는 authoritative field가 없다. 따라서 `evaluation_scope.role=diagnostic`, reason code, Diagnosis narrative, 임의 `is_control`을 control로 해석하지 않는다.
3. M1-D의 control은 experiment registration 밖의 certified golden control과 `BASELINE_RECORDED`뿐이다. 이들은 pending Diagnosis, class count, semantic frontier의 분모에 들어가지 않는다.
4. Registered control experiment 지원은 새 versioned preregistered schema가 생기기 전까지 명시적 limitation이다. Agent-controlled control label을 추가해 rejection count 회피 통로를 만들지 않는다.

### 04.1.2 canonical Diagnosis v1

Event payload exact 9 fields:

| field | exact contract |
|---|---|
| `science_state_version` | literal integer `1` |
| `generation_id` | active generation ID |
| `study_contract_digest` | active contract digest |
| `evaluation_seal_digest` | active evaluation seal digest |
| `compatibility_digest` | terminal registration compatibility digest |
| `diagnosis` | exact Diagnosis body |
| `diagnosis_digest` | `sha256_json(diagnosis)` |
| `diagnosis_id` | `stable_id("diagnosis", project_id, diagnosis_digest)` |
| `authorized_action` | required literal `null` |

Diagnosis body exact 16 fields:

| field | exact contract |
|---|---|
| `diagnosis_schema_version` | literal integer `1` |
| `generation_id`, `compatibility_digest` | active terminal registration과 exact |
| `experiment_id` | one active typed terminal registration |
| `proposal_id`, `proposal_digest` | persisted Proposal sibling과 exact |
| `hypothesis_class_id`, `evaluation_scope_id` | persisted Proposal/contract와 exact |
| `terminal_evidence` | exact `{experiment_id,event_id,event_hash}`; Diagnosis보다 앞선 terminal envelope |
| `artifact_evidence` | ordered unique exact artifact refs; 규칙은 아래 |
| `observation` | terminal/Decision에서 kernel이 재구성한 exact observation |
| `interpretation`, `falsifier` | trimmed Unicode scalar text, 각각 UTF-8 `≤16,384` bytes |
| `failure_type` | `mechanism|implementation|evidence|constraint|operational|supported` |
| `recommendation` | `stop|change_control|explore|ablate|exploit|replicate|retry` |
| `authorized_action` | required literal `null` |

- `terminal_evidence`의 event ID/hash/project/experiment/sequence는 canonical event envelope와 exact 일치해야 한다. Public append/replay/projection/observer 경계는 모든 loose Mapping을 `Event.from_mapping()`으로 exact parse하고 전체 ordered history를 `verify_events()`로 검증한 뒤 reducer에 전달한다. Reducer가 이미 검증된 Event를 받는 내부 seam과 달리, 참조되지 않은 event라는 이유로 envelope/hash-chain 검증을 생략하지 않는다.
- `artifact_evidence[]` item은 exact `{artifact_id,artifact_digest,event_id,event_hash}`다. `(artifact_id,event_id)` canonical order, duplicate-free이며 Diagnosis보다 앞선 same-project/same-experiment canonical artifact다. 목록은 terminal 이전의 그 experiment canonical artifact events **전체 set과 exact equality**여야 한다. Terminal에 `result`가 있으면 current `ResultEnvelope.to_dict()` exact shape를 parse하고 result의 captured `ArtifactRef`도 canonical `ArtifactRecord` 전체 set과 exact 대응해야 한다: `path=relative_path`, `sha256=digest`, `size_bytes=size`, `media_type=media_type`, `retention=metadata.retention`, `sensitivity=metadata.sensitivity`; canonical record의 `role`은 null이고 metadata keyset은 exact `retention,sensitivity`여야 한다. Empty array는 canonical artifact event와 result artifact가 모두 없는 outcome에만 허용한다. Agent가 불리한 artifact를 누락하거나 서로 다른 두 표현의 extra metadata를 숨길 선택권은 없다.
- `observation` exact keys는 `terminal_status`, `reason_code`, `verified`, `retryable`, `primary_metric`, `candidate_value`, `baseline_value`, `improvement`, `promotion_margin`, `gate_evaluations`다. `terminal_evidence`는 raw Event envelope를 결박하지만 observation의 `terminal_status`는 `coerce_state(raw_status).value`로 canonical normalize한다. 따라서 `SUCCESS|PASSED→SUCCEEDED`, `COMPLETE→COMPLETED`, `TIMEOUT|TIMEDOUT→TIMED_OUT`, `CANCELED→CANCELLED`, `ERROR→FAILED`다.
- Terminal payload에 non-empty `reason_code`가 없으면 normalized event type에 따라 exact `STATUS_CHANGED` 또는 `TERMINATED`, `verified`가 없으면 false다. `primary_metric`은 terminal non-empty field → Decision field → registration/baseline historical field → null 순서다. `retryable`은 기존 kernel terminal-evidence derivation 결과이며 선언 field가 있으면 exact literal boolean으로 대조한다. Decision이 없는 outcome의 numeric fields는 null, gates는 `[]`다. Nonterminal status change는 pending Diagnosis를 만들지 않는다.
- Decision이 있는 terminal은 current `Decision.to_dict()` exact 9 fields—`status,reason_code,primary_metric,candidate_value,baseline_value,improvement,promotion_margin,gate_evaluations,authorized_action`—를 전량 보존하며 `authorized_action`은 null이다. Diagnosis observation은 그 Decision의 status/reason/quantitative/gate fields와 terminal status/reason을 모두 exact 대조한다.
- Gate item은 existing `GateEvaluation.to_dict()` exact 11 fields—`id,metric,role,operator,threshold,unit,scale,observed,signed_slack,normalized_slack,passed`—를 재사용하고 ID 순으로 canonicalize한다.
- interpretation/failure type/falsifier/recommendation은 agent interpretation이다. Schema·evidence binding은 검증하지만 conclusive disposition, support, closure, maturity, frontier eligibility를 결정할 권한은 없다.
- Same experiment에는 Diagnosis 하나만 허용한다. Service에 동일 body를 다시 제출하면 existing canonical event를 찾아 append 0의 idempotent success를 반환한다. Canonical log에 두 Diagnosis events가 실제로 존재하면 body가 같아도 replay `DIAGNOSIS_ALREADY_RECORDED`; 다른 body 제출도 같은 code와 append 0이다.

### 04.1.3 kernel-derived disposition과 count

모든 v2 terminal은 status와 무관하게 pending Diagnosis를 만든다. Countability는 Diagnosis text가 아니라 persisted registration과 exact terminal/Decision에서만 파생한다.

Conclusive rejection은 다음 conjunction을 모두 만족할 때 Proposal retry-chain당 최대 한 번 센다.

1. active v2 typed registration이고 exact terminal Diagnosis가 있다.
2. chain identity인 persisted `proposal_id`가 아직 count되지 않았다.
3. terminal status와 Decision status가 exact `REJECTED`, `verified=true`이며 terminal payload에 top-level `error` key가 없다. Cleanup 등 `secondary_errors`는 별도 보존되며 이 predicate의 primary error가 아니다.
4. terminal reason과 Decision reason이 exact `NO_MEANINGFUL_IMPROVEMENT`다.
5. Decision의 primary metric/candidate/baseline/improvement/promotion margin/gates가 exact observation과 일치하고 promotion margin은 `≤0`, failed hard/support gate는 0이다.

`HARD_CONSTRAINT_FAILED`는 중요한 negative Diagnosis로 보존하지만 **class count는 0**이다. Pure reducer에는 certified constitution의 complete typed-gate definitions가 없어, self-consistent gate row가 실제 preregistered gate membership/completeness를 증명하지 못하기 때문이다. 향후 generation-bound evaluation-policy snapshot이 생기기 전에는 count하지 않는다. `VALIDATED`, invalid, insufficient evidence, infrastructure failure, timeout, cancelled, untrusted, generic/unknown terminal, missing/forged Decision, registered experiment가 아닌 baseline/golden control도 모두 0이다. Diagnostic scope는 control이 아니므로 exact no-improvement conjunction을 만족하면 정상적으로 센다. Retry 후 final conclusive terminal은 같은 Proposal chain의 1건이고 retry 자체나 operational attempt를 별도 count하지 않는다.

### 04.1.4 pending gate와 generation laundering 방지

- `pending_diagnosis_experiment_ids`는 terminal event sequence 오름차순이다. Canonical EventLog sequence는 project 안에서 전역 유일·연속이므로 typed v2 history에는 sequence tie가 존재하지 않는다.
- Pending이 하나라도 있으면 새 first attempt와 retry는 payload/debit parsing 전에 차단되고 event/budget/adapter/projection delta는 0이다. Active-generation stop reason도 있으면 registration priority상 `STUDY_STOPPED`, stop이 없으면 `DIAGNOSIS_REQUIRED`다.
- Successor generation도 pending이 있으면 `DIAGNOSIS_REQUIRED`; active typed nonterminal이 있으면 `STUDY_ACTIVE_EXPERIMENTS`다. Pending을 drop, carry, auto-synthesize해 generation을 바꾸지 않는다.
- Diagnosis append와 registration/generation append는 모두 locked events에서 같은 pure reducer/validator를 재실행한다. Forced race의 두 schedule 모두 직렬화된 canonical outcome과 no split-brain을 요구한다.
- 한 class만 closed이고 global stop이 아니면 그 class의 first attempt와 retry는 `HYPOTHESIS_CLASS_CLOSED`이고 모든 deltas 0이다. 모든 classes가 closed면 global `ALL_CLASSES_CLOSED` stop이 우선해 `STUDY_STOPPED`다.
- Active generation에서 `UNTRUSTED` terminal이 하나라도 생기면 Diagnosis 전후 모두 canonical `study_stop.reasons`에 `UNTRUSTED`가 남는다. Pending Diagnosis를 해소해도 **그 active generation의** registration/retry는 `STUDY_STOPPED`이고 frontier는 비워진다. Stop은 required Diagnosis append를 막지 않는다.
- Attempts/elapsed/cost 중 새 first attempt를 하나도 reserve할 수 없는 dimension이 있으면 `BUDGET_EXHAUSTED`, 모든 classes가 closed면 `ALL_CLASSES_CLOSED`를 canonical stop reason으로 더한다. `study_stop.reasons` priority는 exact `UNTRUSTED`, `BUDGET_EXHAUSTED`, `ALL_CLASSES_CLOSED`; `budget_exhausted_dimensions` priority는 exact `attempts`, `elapsed_milliseconds`, `cost_microunits`; `untrusted_experiment_ids`는 unique terminal event sequence 오름차순이다.
- `study_stop`은 이름과 달리 active-generation stop projection이다. M1-B의 frozen change control을 보존해, pending Diagnosis와 active nonterminal이 0이면 genuinely changed sealed contract + predecessor + reason을 가진 successor generation은 stop reason과 무관하게 열 수 있고 새 generation에서 stop/ClassState/budget을 새로 파생한다. Unchanged reset/stale predecessor/reason 누락은 기존 M1-B code 그대로 거절한다.

Stable Diagnosis ordering은 structural `DIAGNOSIS_INVALID` → contract/digest/ID/generation/seal/compatibility → experiment/Proposal → terminal → observation/artifact → duplicate 순이며 `STUDY_STOPPED`를 적용하지 않는다. Registration/retry는 stop → pending → closed class → supported replication parent → payload/debit 순이다. Successor generation은 pending → active nonterminal → frozen M1-B change-control 순이고 active-generation stop 자체는 blocker가 아니다. Exact axis codes는 immutable negative matrix에 고정한다.

### 04.1.5 derived ClassState

ClassState는 별도 event가 아니다. Diagnosis append와 같은 reducer transition에서 active contract class 순서로 파생되어 terminal/Diagnosis split을 만들지 않는다. Public wrapper exact fields는 `class_state_id`, `class_state_digest`, `class_state`; ID는 `stable_id("classstate", project_id, generation_id, hypothesis_class_id)`, digest는 exact body에 public RFC-8785-style `sha256_json(class_state)`를 적용한다.

ClassState body exact 15 fields:

`class_state_schema_version`, `generation_id`, `hypothesis_class_id`, `lifecycle`, `support`, `replication_required`, `conclusive_rejection_limit`, `conclusive_rejections`, `conclusive_diagnosis_ids`, `provisional_diagnosis_ids`, `replicated_diagnosis_ids`, `inconclusive_diagnosis_ids`, `closure_reason`, `closure_evidence`, `authorized_action`.

- `lifecycle`: `open|closed`. Unique count가 limit에 처음 도달하면 closed가 되며 같은 generation에서 재개방하지 않는다.
- `support`: `none|provisional|replicated`. Lifecycle과 독립된 `evidence_supported` predicate를 만족하는 exact verified `VALIDATED/PRIMARY_METRIC_IMPROVED` non-replication은 provisional이다. Exact successful replication은 같은 frozen candidate/new scope의 evidence-supported parent를 가져야 replicated다. Class가 terminal 이후 닫혔거나 Diagnosis가 closure 뒤 append되어도 evidentiary support는 보존·상향되고 낮아지지 않는다.
- `replication_required`: lifecycle open, support provisional이며 qualifying supported leaf에 unused distinct preregistered replication scope가 있을 때만 true다.
- Negative/inconclusive evidence는 existing support를 삭제하지 않고 positive evidence도 rejection count를 삭제하지 않는다. Orthogonal axes와 evidence ID arrays가 둘을 함께 보존한다.
- `closure_reason`은 null 또는 `CONCLUSIVE_REJECTION_LIMIT_REACHED`. `closure_evidence`는 null 또는 exact `{diagnosis_id,diagnosis_digest,diagnosis_event_id,diagnosis_event_hash,terminal_event_id,terminal_event_hash}`이며 최초 threshold-crossing evidence에서 불변이다.
- Closure 뒤 이미 terminal이었던 concurrent node의 Diagnosis는 기록할 수 있으나 새 registration은 불가하다. Count/list는 늘 수 있어도 closure evidence는 바뀌지 않는다.
- 네 evidence arrays는 canonical Diagnosis event sequence 오름차순이다. Event sequence가 전역 유일하므로 별도 tie rule은 없다. **그 hypothesis class에 속한** 모든 active-generation Diagnosis ID는 정확히 하나에만 들어가며 union은 그 class의 full Diagnosis ID set과 같다: qualifying supported non-replication은 `provisional`, qualifying supported replication은 `replicated`, first countable Diagnosis per Proposal은 `conclusive`, 나머지는 전부 `inconclusive`다.
- `evidence_supported`는 active generation/compatibility, typed/latest Proposal retry-chain, exact diagnosed terminal+Decision `VALIDATED/PRIMARY_METRIC_IMPROVED`, `verified=true`, full quantitative fields exact, `promotion_margin>0`, failed hard/support gate 0, terminal top-level `error` absent인 registration이다. Gate list는 비어 있거나 non-empty all-passed일 수 있다. Class lifecycle는 이 base evidence predicate에 들어가지 않는다.
- `executable_supported_parent`는 `evidence_supported ∧ class.lifecycle=open`이다. `replicate` registration은 먼저 closed-class priority와 기존 M1-C structural parent gates를 보존한다: nonterminal은 `PROPOSAL_PARENT_NOT_TERMINAL`, predecessor-generation lookup 실패는 `PROPOSAL_PARENT_MISMATCH`, compatibility mismatch defense-in-depth seam은 `PROPOSAL_PARENT_COMPATIBILITY_MISMATCH`다. 다만 canonical history에서는 active typed registration이 active seal compatibility와 exact하고 successor generation이 registration set을 reset하므로, compatibility mismatch parent row는 도달 불가능하다. M1-D executable literal gate는 이를 위조하지 않고 predecessor mismatch를 고정하며, compatibility code는 M1-C injected-state regression surface에서 보존한다. Structurally valid terminal parent가 base evidence predicate를 만족하지 않을 때만 locked `PROPOSAL_PARENT_NOT_SUPPORTED`이며 append/budget delta는 0이다. Decision/Diagnosis observation mismatch는 이 gate보다 앞선 binding/replay error다. Semantic negatives는 rejected, wrong reason, missing Decision, unverified, margin `≤0`, failed hard/support gate, top-level error, superseded retry를 모두 고정한다. ClassState support와 registration semantic gate는 같은 base predicate를 공유하되 execution gate만 class-open을 추가한다. 따라서 rejected/invalid/generic parent에서 성공처럼 보이는 child를 만들어 `support=replicated`나 maturity rank 0으로 승격할 수 없다.

### 04.1.6 semantic frontier와 retry frontier

Semantic frontier eligibility는 다음 conjunction이다.

1. active generation과 active compatibility의 typed node다.
2. Proposal retry-chain의 latest attempt이며 terminal+Diagnosis complete다.
3. terminal/Decision이 exact verified `VALIDATED/PRIMARY_METRIC_IMPROVED`, full quantitative fields exact, `promotion_margin>0`, failed hard/support gate 0, no top-level `error`다.
4. class lifecycle가 open이다.
5. qualifying successful child가 없는 semantic leaf다. Pending, rejected, invalid, operational, inconclusive child는 successful parent를 소비하지 않는다.

따라서 closed/incompatible/legacy/control/nonterminal/pending/retry ancestor/REJECTED/invalid/insufficient/operational/untrusted/generic node는 100% 제외한다. 실패 지식은 Diagnosis/ClassState에 남지만 실패한 parent를 다음 executable parent로 자동 승격하지 않는다.

Ordering/cap은 implementation 전에 다음처럼 고정한다.

1. successful `replicate` maturity rank 0, 그 밖의 supported node rank 1.
2. rank 안에서 terminal event sequence 내림차순, experiment ID 오름차순.
3. class diversity pass로 각 class의 best-ranked leaf를 먼저 global rank 순으로 고른다.
4. capacity가 남으면 unselected leaves를 같은 global rank로 채운다.
5. `frontier.max_active_branches`에서 자르고 `eligible_total`, `returned`, `truncated`를 함께 낸다.

`qualifying successful child`는 direct `parent_experiment_id`가 대상 node이고, child 자체가 active generation/compatibility의 latest chain이며 exact diagnosed qualifying validated predicate를 만족하는 registration이다. 그 child만 parent를 소비한다.

Public semantic frontier wrapper exact fields는 `max_active_branches,eligible_total,returned,truncated,blocked_by,entries,authorized_action`. Entry exact fields는 `experiment_id,proposal_id,diagnosis_id,hypothesis_class_id,evaluation_scope_id,action,parent_experiment_id,candidate_digest,terminal_event_sequence,maturity,eligible_actions,authorized_action`. Eligible actions는 canonical sorted `ablate|exploit`와 unused replication scope가 있을 때만 `replicate`다. 같은 active generation/compatibility에서 같은 frozen candidate+replication scope registration이 한 번이라도 존재하면 terminal outcome과 무관하게 그 scope는 used이고, retry는 새 candidate-scope pair를 만들지 않는다. Diversity/fill에서 선택한 순서가 public `entries` order다.

Kernel-derived retryable latest attempts는 semantic frontier에 섞지 않는다. Separate retry frontier는 terminal status allowlist 없이 active generation/compatibility, diagnosed, class-open, exact kernel-retryable latest chain을 terminal sequence 내림차순/ID 오름차순으로 노출한다. 따라서 `TIMED_OUT`, qualifying `INFRA_FAILED`/`INSUFFICIENT_EVIDENCE`, `CANCELLED` 모두 같은 predicate를 만족할 수 있다. Wrapper는 `eligible_total,blocked_by,entries,authorized_action`; entry는 `experiment_id,proposal_id,diagnosis_id,hypothesis_class_id,evaluation_scope_id,attempt,retry_of,terminal_event_sequence,authorized_action`다.

`study_stop.stopped=true`면 양 frontier의 eligible total과 entries는 0이며 `blocked_by`는 canonical stop reasons를 그대로 노출한다. Retry budget만 소진되고 first-attempt capacity는 남은 경우 semantic frontier는 유지하되 retry frontier만 `RETRY_BUDGET_EXHAUSTED`로 막는다. 이 blocker는 execution authority가 아니라 “현재 kernel gate상 이 frontier를 실행할 수 없음”을 정확히 나타내며 authority는 계속 null이다.

### 04.1.7 public state와 compatibility

StudyContract v2 `ScientificState.to_dict()`는 기존 generation/contract/budget/M1-C fields에 다음 additive fields를 갖는다: `diagnosis_count`, event-order `diagnoses`, `pending_diagnosis_experiment_ids`, contract-order `class_states`, `study_stop`, `semantic_frontier`, `retry_frontier`. Diagnosis public wrapper는 exact `diagnosis_id,diagnosis_digest,diagnosis_event_id,diagnosis_event_hash,event_sequence,diagnosis`다. `study_stop` exact fields는 `stopped,reasons,untrusted_experiment_ids,budget_exhausted_dimensions,all_classes_closed,authorized_action`; arrays는 contract-defined priority/order로 canonical하다.

- StudyContract v1 state, fixed v1 event bytes/head/projection/service/CLI shapes에는 신규 key 0을 요구한다.
- M1-C Proposal/scope/identity/budget의 old fields와 IDs는 유지한다. M1-D가 계획된 v2 transition을 강화하므로 M1-C test scenarios의 terminal→next registration에는 exact Diagnosis를 추가하되 frozen M1-C inputs/expected old-field values를 바꾸지 않는다.
- Namespaced Diagnosis event는 SQLite의 canonical truth table을 만들지 않지만 projection cursor 우회를 막기 위해 full scientific-history-required set에 포함한다. Cold reducer, fresh projection rebuild, service replay가 같은 state/error를 내야 한다.
- Context v2와 branch conclusion v1은 M1-E까지 exact 보존한다. Diagnosis는 generic Finding으로 자동 추론하거나 legacy branch conclusion으로 대체하지 않는다.

## 04.2 immutable oracle과 사전 예상 결과

Versioned oracle은 `tests/fixtures/scientific_state/v3/manifest.json`과 supporting fixture 7개다.

| corpus | fixed denominator / purpose |
|---|---|
| manifest | 28 unique case nodes, observed/expected exact equality; operation name은 중복 가능 |
| terminal / valid Diagnosis | isolated canonical histories 23, terminal Event envelopes 119, ArtifactRecords 4, exact extended Diagnosis 18; canonical generic 6 + alias 7 + nonterminal control 1 포함 |
| Diagnosis negative matrix | 115/115 stable reject code; individual Decision/observation/artifact-reference binding과 nested exact-schema·Decision/Result/ArtifactRef/ArtifactRecord·trimmed Unicode scalar·literal boolean·UTF-8·gate order·precedence attacks 포함, locked append/cold reducer/fresh rebuild/service replay `460/460`; encodable materialization 113/113 with 832 Events, pre-hash surrogate rejection 2/2, UTF-8 boundary accepts 2, public idempotency control 1 |
| full state / transition / race | full literal states 54, terminal-pending 23, counting taxonomy 26, literal transition gates 37, forced races 7; raw-history Event envelopes `452 + 119 + 284 + 41`, accepted gate/race operation Event 16; hidden string schedule 0 |
| counting taxonomy | 26/26; exact no-improvement와 one-per-chain만 count; margin zero, non-empty all-passed gates, key-present `error:null`, agent `is_control:true`, hard-gate/invalid/control/inconclusive 경계를 포함 |
| frontier exclusion | 20 axes/21 subcases; closed/incompatible/non-scientific + shared support single-flip 6축 전부 제외 |
| frontier positive | eligible 5에서 exact ordered/capped 3; cap `1,2,3,4,7`의 returned `1,2,3,4,5`, selector-free rename-invariant observer rows 46 |
| compatibility | fixed v1 bytes/head/state/projection/status/replay, M1-C manifest 20/20 + transitions 53/53 + four paths 72/72 |
| authority | Diagnosis/ClassState/frontier/service/CLI ten surfaces key 10/10, recursive non-null 0 |

State를 주장하는 각 transition은 unchanged legacy generation/contract/budget/M1-C fields와 M1-D additions를 모두 포함한 full literal `ScientificState.to_dict()`를 가진다. `$ref`, `extends`, template, inherited state, subset assertion은 금지한다. 입력도 scenario label이 아니라 ordered literal event history이며, Diagnosis가 참조하는 terminal/artifact/Diagnosis envelope identity와 payload를 모두 포함한다. 각 row는 full ordered Diagnosis list, all ClassStates, pending order, semantic/retry frontier, pre/post state digest, event/budget/projection deltas 또는 exact error를 literal로 가진다. Empty, conclusive N-1/N뿐 아니라 provisional, replicated, inconclusive, mixed positive+negative partition을 각각 full state로 고정한다. Expected state는 production reducer로 생성하거나 수정하지 않는다.

Digest algorithm은 이름만으로 추정하지 않는다. `diagnosis_digest`, `class_state_digest`, contract와 oracle의 `pre_state_digest`/`post_state_digest`/`final_state_digest`는 public RFC-8785-style `sha256_json(exact_to_dict_value)`다. Event hash와 모든 `stable_id`는 kernel compact canonical encoder(`sort_keys=true`, `ensure_ascii=false`)를 사용한다. Oracle observer는 이 둘을 같은 serializer로 대체하면 안 되며, frozen 값과 독립 재계산을 모두 대조한다.

Anti-self-echo:

- Observer dispatch에는 case `id`와 `expected`를 제거한 `{operation,input}`만 전달한다.
- Dispatch는 declared operation만 사용한다. Observer/support source에서 `case["id"]`, `case.get("id")`, literal 28 case IDs, expected access를 정적으로 금지한다. Manifest input에는 case/gate/race selector, required operation 목록, display ID/label이 0이어야 하며 fixture의 literal rows 전체를 관찰한다.
- Negative mutation은 selected canonical wrapper/history의 deep copy에 적용한다. Valid body를 바꿔 deeper binding error를 관찰하는 case는 fixture에 선언된 순서대로 `diagnosis_digest`, `diagnosis_id`를 재계산하고, 선언되지 않은 derived field는 byte-for-byte 유지한다. Digest/ID 위조 case는 재계산하지 않으며 gate-slack case는 명시된 hard-constraint base를 사용한다.
- Source document patch 전에 named production control observer를 실행하고 control metadata는 product payload에 들어가지 않는다.
- Positive는 real `ResearchService`, deterministic adapter, public Diagnosis service/CLI, locked EventLog, reducer, fresh rebuild, `study_status/replay`를 호출한다. Race harness는 schedule만 강제한다.

어느 digest/ID/code/count/order/full state/race ratio나 compatibility가 다르면 M1-D CLOSE를 차단한다.

## 04.3 무엇을 만들 계획인가

| 작업 | 위치 | 예상 검증 산출물 |
|---|---|---|
| strict Diagnosis model/digest/ID | 신규 `science/diagnoses.py`, `science/__init__.py` | canonical 18 + negative 115 + UTF-8 accepts 2 |
| event-aware reducer, ClassState/frontiers | `science/state.py` | full literal states 54, terminal-pending 23, count 26, exclusion 20 axes/21 subcases |
| locked service + CLI | `service.py`, `cli.py` | idempotency, 7 forced schedules/14 literal operation rows, actual public shape |
| replay/projection history gate | `kernel/projection.py` | locked/cold/rebuild/service parity 460 |
| protocol/docs | README, architecture, skill references | human protocol and executable gate agree |
| executable oracle | `tests/test_m1d_*`, v3 fixture observer | manifest 28/28, prior oracle parity |

## 04.4 검증 계획

- Focused: Diagnosis parser/digest/ID, terminal/Decision/artifact binding, pending gate, one-per-chain count, N-1/N closure, support/replication transitions, frontier positive/exclusions/order, idempotent/concurrent append.
- Path parity: all 115 negative rows through locked append, cold reducer, fresh projection rebuild, `ResearchService.replay`; exact `460/460`, all deltas 0. Encodable 113개는 canonical mutation history 832 Events를 물질화하고 lone-surrogate 2개는 hashing/Event/append 전에 fail-closed한다.
- Gate/service: literal history+operation+request 37행, accept 7/reject 30, every row full final state/digest/head; compatibility-parent canonical-unreachable 1축은 M1-C injected regression에서 보존한다.
- Race: duplicate Diagnosis; terminal-Diagnosis vs next registration; threshold-closing Diagnosis vs closed-class registration; Diagnosis vs successor generation. Each forced schedule has literal outcome.
- Compatibility: actual frozen v1 corpus and M1-C oracle execution, v1 bytes/head/shape unchanged, replay byte-preserving.
- Full: explicit Python 3.12 `pytest -q`; `ruff check src tests`; `uvx ty check src`; `git diff --check`.
- Independent review: schema/count policy와 state/service/projection/CLI를 교차 검토하고, progress critic과 7-pass auditor가 actual product observer·chronology·claims를 재검증한다.

## 04.5 결과 vs 가설

구현 전이므로 모든 product evidence response와 measured result는 `PENDING`이다. 첫 independent pre-spec review는 full-artifact attacks, idempotency/stop/successor 충돌, ClassState/frontier/literal-history holes를 찾아 **FAIL**했다. 두 번째 fixture review는 active-nonterminal/closed-class/stop/retry/race literal coverage를, 세 번째 narrow review는 permissive Decision·Result·Artifact 비교와 history-rehash dependency를 찾아 다시 **FAIL**했다. 부분 evidence/transition 감사가 당시 범위에서 PASS했지만, 네 번째 Q1–Q8 전체 policy review는 threshold/cap hardcode, narrative authority, pending·stop ordering cardinality, pre-derived gate/race input, compatibility expected 일부 누락을 찾아 다시 **FAIL**했다. 다섯 번째 fresh review도 individual evidence fields, non-empty all-passed gates, generic/alias terminal, non-UNTRUSTED stop, support predicate 분리, limit/cap/budget parameterization, retry status allowlist, semantic selector leakage를 찾아 **FAIL**했다. Product code를 시작하지 않고 criterion/fixture만 수정했고 이전 manifest seal은 모두 checkpoint 자격이 없다. Sixth exact snapshot은 supporting hash 7/7, manifest raw `950096a8f1b4c4c46f42329d1ee77a16d741c678eba6108544280b01031f0a97`, public `sha256_json` `6f72ec9fc9ece754e40c1be6598e50eeddd9cc053338ebc2ce97a1e9872136ea`에서 fresh Q1–Q8 **전부 PASS**했다. 상세 trail은 [`04-m1-d-diagnosis-class-frontier.critic.md`](04-m1-d-diagnosis-class-frontier.critic.md)에 보존한다. 이제 이 exact docs+fixture checkpoint 뒤에만 구현하며, 구현 뒤 exact frozen oracle 관찰만 기록한다.

## 04.6 시스템 영향 분석 ★

- 이전: terminal failure가 Proposal에 연결되지만 다음 registration을 막는 typed diagnosis가 없고 class threshold/frontier는 사람의 기억에 의존한다.
- 목표 이후: every terminal은 exact Diagnosis로 닫히고, kernel-derived ClassState가 class closure와 deterministic supported frontier를 replay한다.
- 가능해질 것: M1-E context v3가 pending/class/frontier를 신뢰해 노출하고, M2 Claim이 exact Diagnosis/ClassState origin을 참조한다.
- 계속 불가능: 좋은 interpretation 자동 생성, registered-control classification, 실제 dataset 독립성/통계적 재현성 증명, cross-project memory, autonomous loop, deployment/trading authority.
- 외부 관찰: `run-once → diagnose → study-status/replay → next registration`에서 pending release, class/support/count, frontier가 exact 보인다.

### 04.6.4 마일스톤 진척 청구 ★

**영향 받은 M_i.j**: `M1-D` · **계획 라벨**: _CLOSE CANDIDATE_

| conjunct | 현재 | close gate |
|---|---|---|
| terminal evidence-bound Diagnosis schema/replay PASS | ⬜ | canonical 18 + negative 115, exact event/artifact/observation refs, four paths 460 |
| diagnosis 전 다음 v2 registration 100% 차단 | ⬜ | terminal-pending 23 + generic STATUS_CHANGED 1, first/retry/successor + races, all reject deltas 0 |
| conclusive threshold class closure transition PASS | ⬜ | configured limits 2·3·4의 N-1/N, post-close count/support, immutable closure evidence, closed-class gate |
| invalid/control/inconclusive count 규칙 PASS | ⬜ | taxonomy 26/26; diagnostic와 agent `is_control:true` label은 scientific, baseline/golden만 outside registration control |
| frontier가 closed/incompatible/non-scientific 100% 제외 | ⬜ | exclusions 20 axes/21 subcases + positive 5→ordered 3 + caps 1·2·3·4·7 |

다섯 conjunct와 critic/auditor가 모두 PASS하기 전 M1-D를 닫지 않는다. Parent M1은 M1-E까지 open이다.

### 04.6.5 종착지 비전 갱신 ★

- 계획 Delta: pipeline §8.4 Study inference의 terminal→Diagnosis→ClassState→frontier를 executable canonical transition으로 구체화한다.
- 성공 시 NS2는 `2/6→5/6`, NS3는 `1/4→3/4`까지가 최대다. Complete legacy isolation과 Claim은 M1-E/M2에 남는다.
- Pipeline Stage 3은 모든 M1-D gate PASS 뒤에만 `△→○`를 청구한다. Autonomous learning/community나 NS6 효과를 청구하지 않는다.
- §8 endpoint, M-chain, unseen NS6 gate, live migration/product multi-agent 경계는 유지한다.

### 04.6.6 의도-실행 정합 ★

**계획 라벨**: _MATCH CANDIDATE_ — 실패를 durable state와 next-choice input으로 바꾸되 agent narrative에 closure 권한을 주지 않는다. 이는 사용자가 승인한 “실패를 지식으로 바꾸는 자율 연구 시스템” 방향의 scientific-state 단계이며 Program memory/자율성의 완성 청구는 아니다.

### 04.6.7 Claim Mode ★

**현재 라벨**: _CONFIRMATORY CANDIDATE_. 구현 전 기준선은 `a5f232d`다. Phase/critic/v3 fixture만 포함한 pre-spec checkpoint, supporting raw SHA, manifest raw/sorted-compact SHA, independent critic PASS가 첫 product/result-bearing commit보다 앞서야 한다. Commit/tree/parent/time과 digest는 checkpoint 뒤 기록한다.

최초 full-policy-review 후보 supporting raw SHA-256 — **SUPERSEDED; 현재 seal 아님**:

- contract `58d3c416c9ce98c336fe888bccf19859a6e5c789d85306b93492a7cabd0a30f3`
- terminal `086755ac1eed648ef38c2f09e661b5ddc7d38793ef9d9930218870986112565b`
- valid Diagnosis `de28f540ce70c7c6ccc03affd8f33caf02473863c794c56221be4635765c98f7`
- negative matrix `8c76d9dd096b5bf9014550830b8e12d3dd6f0e8bd56be99be31e9543ceaadb2b`
- transition `291f22290c16f3c293a0687a512d92e5e6a39ad7821d4a1bc9a119677ce60bc1`
- frontier `a11b2434fc76925870f64e586a49f6f0d77af9be3318fe6fca6e845ef917600d`
- compatibility `4f3f79cc593a51b5f1f33b3501f966496bc91f37cde33f2f745f26518c64b597`
- manifest raw `5b5af6da72dfea896d79e09f8c56b64586f0789a07575d044be960638ef39664`; sorted-compact `d5ecb65a7fdd3232a2e459ad4cb2d2c81b0d6ba0de440da69a0302e2672c322b`

Fifth full-policy-review snapshot supporting raw SHA-256 — **REVIEWED FAIL; checkpoint seal 아님**:

- contract `58d3c416c9ce98c336fe888bccf19859a6e5c789d85306b93492a7cabd0a30f3`
- terminal `086755ac1eed648ef38c2f09e661b5ddc7d38793ef9d9930218870986112565b`
- valid Diagnosis `de28f540ce70c7c6ccc03affd8f33caf02473863c794c56221be4635765c98f7`
- negative matrix `06a3d667729d5de810b37e34e32a7305999b7da340349a24642789391692f5e2`
- transition `8311b101ced44d75e8e4ccde902d58abcdb9b06edf199987731d010084145e4a`
- frontier `e7f6af8ab68ffdaf9519330eb31807d726c694da190d7eeb79fd19829ac20ab3`
- compatibility `4f3f79cc593a51b5f1f33b3501f966496bc91f37cde33f2f745f26518c64b597`
- manifest raw `c45d9157c671ca3b84747d671431048c94bf4121c89434a0750f2c26bc7d5547`; sorted-compact/public `sha256_json` `0d056d193a3a70cad032986dccc14ca4e662b3cf57d3f482b990e1a2b1b54f44`

Targeted evidence/frontier/transition auditors는 각각 당시 final bytes를 PASS했지만 fresh
Q1–Q8 review가 permissive implementation holes를 찾아 이 snapshot을 FAIL했다. 수정된 새
supporting hashes와 manifest seal을 별도 추가하고 fresh reviewer가 전부 PASS해야 pre-spec
checkpoint를 만든다.

Sixth full-policy-review candidate supporting raw SHA-256 — **FRESH Q1–Q8 PASS; checkpoint commit pending**:

- contract `58d3c416c9ce98c336fe888bccf19859a6e5c789d85306b93492a7cabd0a30f3`
- terminal `e3623748815bdba58feb399a1dab55399917e80e11894eb981572af9a08cc20f`
- valid Diagnosis `3c9394d0ee2ccc06b6e21dbca403dfc6b4e0e3264ffc43e13cc39c5673462336`
- negative matrix `112a77493182354637ece0dd405dcca8a4093aee876f75af58f1bde437ae4fb4`
- transition `e526f2c2aab968cdd1d0777719ecf992216ac9469864354b4b51586987a15951`
- frontier `66c34953a9f2e0259e4be3c00fe24c92e8213685fff3f00f02ba93e97fa75cc5`
- compatibility `4f3f79cc593a51b5f1f33b3501f966496bc91f37cde33f2f745f26518c64b597`
- manifest raw `950096a8f1b4c4c46f42329d1ee77a16d741c678eba6108544280b01031f0a97`; public `sha256_json` `6f72ec9fc9ece754e40c1be6598e50eeddd9cc053338ebc2ce97a1e9872136ea`

이 candidate는 fifth-review 결함을 individual binding 14축, generic/alias terminal 13축,
non-empty passed gates, limit 4, post-close replicated support, cap 5개, 독립 budget dimensions,
status-allowlist-free retry positives와 selector-free literal observers로 보강했다. Fresh Q1–Q8
review는 전부 PASS했다. 이 exact bytes를 docs+fixture-only checkpoint로 commit하기 전까지는
product implementation을 시작하지 않는다.

Oracle expected나 criterion을 구현/관찰 뒤 고치면 이전 결과를 `RESULT-INVALID`로 제외하고 correction-only checkpoint를 만든 뒤 M1-D 전체를 `EXPLORATORY`로 강등한다. Chronology를 이용해 confirmatory 자격을 복원하지 않는다.

### 04.6.8 Requirement-Result Divergence ★

- `REQUIREMENT-WRONG`: control/conclusive/frontier가 사용자 목표를 잘못 대리하거나 M1-D conjunct를 측정하지 못함 → 구현 중단, 필요 시 Rule 9 retrospective.
- `RESULT-INVALID`: wrong runtime, fixture inheritance/subset, observer self-echo, production path 미실행, race 미강제, replay/live 불일치, implementation bug → 결과 제외, 같은 frozen criterion으로 재측정.
- `GENUINE-FINDING`: independent minimal reproduction에서 existing event/projection/terminal semantics와 fixed contract가 근본 충돌 → M1-D open, EXPLORATORY 재명세.
- 어느 분류든 manifest 28/Diagnosis 115/four-path 460/full state·gate·race/count taxonomy/frontier exclusion/order/parity의 새 frozen denominator와 exact 불일치가 있으면 CLOSE를 차단한다.

## 04.7 §북극성 갱신 계획

- NS1: v1/M1-C parity와 Diagnosis authority/race/replay fail-closed evidence를 보강한다. 전체 release protocol-attack gate는 open이다.
- NS2: Diagnosis gate, class closure, semantic frontier가 모두 PASS할 때만 `2/6→5/6`. Complete legacy isolation은 M1-E다.
- NS3: typed Diagnosis와 derived ClassState가 exact origin/digest로 replay될 때만 `1/4→3/4`. Claim은 M2다.

## 04.8 §pipeline 매핑 영향

- 구현/검증 성공 뒤 pipeline §8.4 current state, §8.5 cycle delta, §10 단계 평가를 함께 갱신한다. M1-D 전에는 Stage 3 `△`를 유지한다.

## 04.9 비관 재채점 — 이 phase 자체

- Exact Diagnosis는 해석의 품질이나 인과 타당성을 증명하지 않는다. Agent narrative는 search/retrieval input일 뿐 kernel disposition이 아니다.
- `REJECTED` count는 candidate/class under current certified evaluation에 대한 bounded evidence이지 우주의 보편적 falsification이 아니다.
- Hard-gate failure는 negative Diagnosis로 보존하되 M1-D pure reducer에서는 count하지 않는다. Certified gate-definition snapshot을 generation에 replay 가능하게 결박하기 전에는 self-consistent gate row만으로 class closure를 허용하지 않는다.
- Scope manifest identity는 실제 sample 독립성이나 statistical replication을 증명하지 않는다.
- Supported-only frontier ordering은 deterministic policy이지 learned optimal ranking이 아니다. NS6 unseen choice accuracy가 실제 효과를 판정한다.
- Registered control은 현 schema에서 지원하지 않는다. 임의 inference로 gap을 숨기지 않는다.
- Actual usage settlement/study lifetime ceiling은 M1-B limitation, holdout policy는 후속 범위다.

## 04.10 다음 1행동

- exact PASS verdict와 v3 fixture 8개를 docs+fixture-only pre-spec checkpoint로 commit한다.
- checkpoint provenance를 별도 문서 commit에 기록한 뒤 Diagnosis product implementation을 시작한다.
