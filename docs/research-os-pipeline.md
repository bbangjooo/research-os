# Research OS 파이프라인 — 학습 & 코딩 레퍼런스

> Paired with: `docs/research-os-status.md` (작업 기록)
> 이 문서는 v0.3~v0.5의 방법론, projected end-state, 마일스톤 정의를 고정한다.

---

## 0. 전체 흐름 한눈에

```text
1. Evidence semantics          │ 평가 결과를 구조화하고 방향·gate slack을 보존
2. Study generation           │ 연구 계약과 누적 budget을 canonical state로 강제
3. Study inference graph      │ Proposal·Diagnosis·ClassState로 실패를 학습 상태화
4. Program memory             │ 조건부 Claim과 evidence 관계를 append-only로 축적
5. Relevant context v3        │ 지금 필요한 claim·class·frontier만 이유와 함께 검색
6. Autonomous single-agent    │ provider-neutral finite loop를 실행·중단·재개
7. Meta-evaluation & release  │ 동일 예산 비교로 학습 효과와 하위호환을 판정
```

**기억해야 할 ★ 핵심 단계**:

- §2~§3 — 문서 규율을 machine-enforced scientific state로 바꾸지 않으면 memory가 신뢰할 수 없다.
- §4~§5 — durable claim과 relevance retrieval이 없으면 실패가 다음 가설을 개선하지 않는다.
- §7 — node/agent 수가 아니라 fixed-budget correct decision과 waste로 성공을 판정한다.

### MVP-first 권장

1. **v0.3~v0.5는 single local worker** — 기존 workflow lock과 provider-neutral CLI 경계를 유지한다.
2. **ProgramLog는 append-only file + rebuildable projection** — graph/vector DB를 canonical truth로 도입하지 않는다.
3. **다중 agent 진입 gate** — 제품 multi-agent는 NS6 fixed-budget benchmark를 통과한 이후에만 검토한다. v0.5 안에서는 single local worker를 유지한다.

### MVP / Full 활성표 (over-engineering 방지)

| § | v0.3~v0.5 MVP | 후속 Full |
|---|---|---|
| 1~3 | 단일 project/generation의 typed scientific state | independent holdout custodian·고급 uncertainty |
| 4~5 | deterministic tag/scope/relation retrieval | 필요가 측정된 뒤 vector/graph retrieval 보조 |
| 6 | provider port + single worker state machine | 역할 분리·lease·bounded concurrency |
| 7 | 36 deterministic episodes + 대표 E2E | prospective external holdout·multi-agent ablation |

### 목표 도달 메커니즘 ★

1. **정직한 evidence** (§1): veto 여부와 무관하게 delta와 gate 부족량을 남긴다.
2. **강제된 연구 계약** (§2): generation, budget, hypothesis class, 허용 transition을 kernel이 검사한다.
3. **실패의 typed state화** (§3): terminal evidence를 diagnosis와 class 상태로 변환한다.
4. **조건부 지식 축적** (§4): claim이 적용 범위·증거·반박·대체 관계를 가진다.
5. **관련 지식 재사용** (§5): proposal이 어떤 지식을 왜 사용/기각했는지 추적한다.
6. **유한 자율 루프** (§6): provider의 출력은 비신뢰 packet이며 kernel preflight 뒤에만 실행된다.
7. **비교 가능한 효과 측정** (§7): 동일 후보 언어·실험 budget에서 정확도와 낭비를 비교한다.

현재 상태 (Cycle 02 closed — implementation evidence, progress critic, independent auditor PASS):

- 1번 ✅/○ — directional delta, constitution-owned typed gate/slack, baseline/candidate verify 대칭과 nested/flat certification lifecycle이 구현·검증됐다.
- 2번 ○ — checkpoint `df2c900`에서 canonical StudyContract·evaluation-sealed generation·replayable cumulative reservation ledger·locked overrun gate가 구현됐다. executable manifest `29/29`, focused `81+37`; 단, generation별 non-refundable reservation이지 actual usage telemetry나 study lifetime cap은 아니며 successor 반복 증액을 막지 않는다.
- 3번 ❌ — 자유문자열 graph metadata와 Finding만 있고 typed diagnosis/class reducer가 없다.
- 4번 ❌ — project-bound Finding은 cross-project conditional Program Claim이 아니다.
- 5번 ❌ — context v2는 최근 leaf/finding 중심이고 M1-B generation/ledger도 직접 노출하지 않으며 retrieval reason·supersession이 없다.
- 6번 ❌ — 외부 agent가 수동으로 단계를 잇고 canonical loop resume state가 없다.
- 7번 ❌ — 전체 regression은 `371 passed, 104 subtests`로 갱신됐지만 v0.2 comparator와 precommitted unseen learning episode suite는 없다.

---

## 1. Evidence semantics

### 1.1 무엇을 하는 단계인가

Evaluator의 관측값을 kernel 소유 gate 정의와 결합해 metric delta, threshold margin, signed/normalized slack을 항상 남긴다. hard veto가 최종 status를 지배하더라도 “효과 없음”과 “효과는 있으나 제약 위반”을 구분한다.

### 1.2 좋은 입력의 신호 / 봐야 할 메트릭

- maximize/minimize 모두 방향 보정 delta가 존재한다.
- gate는 unique ID, role(`support|hard`), operator(`gte|lte`), finite observed/threshold, unit/scale을 가진다.
- baseline과 candidate가 동일한 adapter verify 경계를 통과한다.
- legacy arbitrary constraint는 읽되 새 v2 generation에서는 typed gate를 요구한다.

### 1.3 자주 하는 실수 (함정)

- hard constraint를 delta보다 먼저 평가해 diagnosis 정보를 잃는 것.
- evaluator가 threshold/pass를 소유하게 해 kernel 재계산을 불가능하게 하는 것.
- execution repeat를 scientific replication이나 새 adaptive hypothesis로 세는 것.
- 기존 certification patch의 direct API만 테스트하고 `doctor`/review-subject CLI JSON 경계를 빠뜨리는 것.

### 1.4 코드 관점

- 구현 seam: `src/research_os/contracts/results.py`, `src/research_os/config.py`, `src/research_os/policy.py`, `src/research_os/service.py`.
- 새 contract는 project candidate JSON과 분리한다.
- M1-A에서 기존 flat certificate와 nested immutable fingerprint lifecycle을 함께 회귀했고, M1-B까지 Python 3.12 전체 `371 tests + 104 subtests`가 통과했다.

---

## 2. Study generation과 cumulative budget

### 2.1 무엇을 하는 단계인가

Machine-readable `StudyContract`가 generation identity, compatibility/evaluation seal, hypothesis classes, intervention surface, evaluation scopes, frontier, stop/change-control policy와 attempts/retries/elapsed/cost budget을 고정한다.

### 2.2 좋은 입력의 신호 / 봐야 할 메트릭

- canonical contract digest와 generation ID가 context·proposal·events에 결합된다.
- registration append의 locked precondition 안에서 누적 budget을 다시 합산하고 원자적으로 reserve한다.
- invalid/infra/control도 실행·비용 budget은 소비하지만 conclusive class rejection count에서는 제외한다.
- cost limit이 없는 경우 `null`로 명시하며 측정되지 않은 비용을 0으로 추정하지 않는다.
- `tests/fixtures/scientific_state/v1/manifest.json`이 여섯 capability별 initial state, submitted transition, expected next state 또는 stable rejection code, class closure threshold, budget delta를 행 단위로 고정한다. 독립 판정은 manifest 전체 행의 exact match 수/전체 행으로 계산하고 manifest SHA-256을 phase evidence에 기록한다.

### 2.3 자주 하는 실수 (함정)

- preflight 외부에서 budget만 확인해 TOCTOU를 만드는 것.
- brief 전체를 study plan으로 계속 사용해 hypothesis 변경마다 evaluator certificate까지 회전시키는 것.
- 새 session/branch로 search-family counter를 초기화하는 것.
- tokenless path가 v2 generation state를 우회하게 두는 것.

### 2.4 코드 관점

- 구현 seam: `src/research_os/science/contracts.py`, `science/state.py`, `service.py`, `kernel/{ids,projection}.py`, `cli.py`.
- Event envelope v1과 기존 lines는 수정하지 않고 versioned namespaced payload/event를 사용한다.
- evaluation seal, study generation digest, program ID를 직교 identity로 유지한다.
- M1-B checkpoint `df2c900`에서 contract/generation/ledger/locked race의 executable manifest `29/29`, focused `81+37`, full `371+104`가 통과했다.
- 현재 budget은 generation별 non-refundable reserved allocation이다. actual elapsed/cost settlement, study-lifetime ceiling, successor 반복 증액 방지, context v2 노출은 아직 없다.

---

## 3. Study inference graph

### 3.1 무엇을 하는 단계인가

기존 execution DAG 옆에 Proposal→Experiment evidence→Diagnosis→ClassState transition을 replay한다. terminal 이후 diagnosis가 기록되기 전에는 다음 proposal/registration이 불가하며 conclusive threshold를 충족한 class는 실제로 닫힌다.

### 3.2 좋은 입력의 신호 / 봐야 할 메트릭

- Proposal: class, mechanism, predicted effect, falsifier, parent/action, intervention fields, evaluation scope, knowledge basis.
- Diagnosis: exact experiment/event/artifact refs, delta/slack, observation vs interpretation, failure type, falsifier, recommendation.
- ClassState: open/provisional/replication-required/replicated/falsified/inconclusive/closed와 transition evidence.
- semantic frontier: open + compatible + scientifically eligible node만 반환.

### 3.3 자주 하는 실수 (함정)

- diagnosis를 새 experiment node나 adapter operation으로 만드는 것.
- branch conclusion Finding만 쓰고 class state를 실제로 닫지 않는 것.
- invalid/control node를 scientific rejection이나 frontier에 포함하는 것.
- true replication에서 frozen candidate digest를 바꾸도록 강제하는 것.

### 3.4 코드 관점

- 기존 seam: `graph_policy.py`, `agent.py`, `service.py`, `kernel/events.py`.
- namespaced event를 기존 SQLite가 무시해도 별도 strict reducer가 live sync와 replay 모두에서 검증해야 한다.
- scientific replication identity에 preregistered `evaluation_scope_id`를 추가하고 retry와 분리한다.
- context v2/branch conclusion v1 exact replay를 보존하고 v3/v2 payload를 별도로 추가한다.

---

## 4. Program memory

### 4.1 무엇을 하는 단계인가

Project-bound execution log를 억지로 global memory로 쓰지 않고 별도 `ProgramManifest`와 append-only `ProgramLog`를 둔다. Claim은 bounded statement, applicability scope, maturity/status, evidence refs, limitations와 관계를 가진다.

### 4.2 좋은 입력의 신호 / 봐야 할 메트릭

- evidence ref가 origin project ID, event ID/hash/head, compatibility, evaluation seal, artifact digest를 정확히 가리킨다.
- relation은 `supports`, `contradicts`, `supersedes`, `replicates`, `derived_from`, `applies_to`로 제한·검증한다.
- Claim은 수정하지 않고 새 Claim이 supersede한다.
- project/program lock 순서와 expected-head가 deadlock·stale write를 막는다.

### 4.3 자주 하는 실수 (함정)

- 기존 `GLOBAL` finding을 진짜 cross-project memory로 오해하는 것.
- 과거 free text를 LLM으로 자동 파싱해 사실처럼 import하는 것.
- incompatible evaluation seal·overlapping holdout scope를 숨기는 것.
- interpretation이 terminal evidence보다 높은 권위를 갖는 것.

### 4.4 코드 관점

- 새 seam: `src/research_os/memory/program.py`, `claims.py`.
- ProgramLog도 canonical JSON, hash chain, append precondition, rebuildable projection 원칙을 따른다.
- legacy import는 원문 digest와 origin만 가진 `legacy_unstructured` record로 격리한다.

---

## 5. Relevant context v3

### 5.1 무엇을 하는 단계인가

최근 N개 raw history 대신 현재 phase, 허용 transition, budget, open/closed class, pending diagnosis, semantic frontier, 관련 claims/contradictions/limitations와 retrieval reason을 bounded packet으로 제공한다.

### 5.2 좋은 입력의 신호 / 봐야 할 메트릭

- deterministic key: program/class/tags/failure signature/scope/relation/status.
- superseded claim은 active context에서 제외되고 contradiction은 함께 노출된다.
- context token은 event head뿐 아니라 generation digest와 program head/hash를 묶는다.
- Proposal은 참조 claim별 `used|rejected|not_applicable` disposition을 남긴다.
- `tests/fixtures/program_memory/retrieval-v1.json`이 query, program/class/scope/status/relations, candidate claim IDs, exact ordered expected active IDs와 expected contradiction/superseded/irrelevant sets를 고정한다.
- 정렬은 manifest가 지정한 `(relation_priority, scope_specificity, status_priority, claim_id)` canonical key를 따르고, relevant/contradiction recall의 분모는 각 expected set 크기다. superseded exclusion 분모는 candidate set의 superseded IDs, contamination 분모는 returned IDs이며 expected-empty query는 exact empty result일 때만 PASS한다.

### 5.3 자주 하는 실수 (함정)

- vector similarity를 canonical relevance truth로 사용하는 것.
- 관련 없는 오래된 result를 token budget이 허용한다는 이유로 포함하는 것.
- retrieval manifest 없이 agent가 임의로 기억을 골랐다고 주장하는 것.
- shuffled/irrelevant memory가 있어도 오염 저항을 측정하지 않는 것.

### 5.4 코드 관점

- 기존 `build_agent_context()`를 v2와 공존하는 versioned builder로 확장한다.
- `memory/retrieval.py`는 순수 결정론 reducer/query로 시작한다.
- packet digest와 read set을 registration 직전 재검증한다.

---

## 6. Autonomous single-agent loop

### 6.1 무엇을 하는 단계인가

외부 provider가 비신뢰 `DecisionPacket`을 반환하고 Research OS가 이를 preflight한 뒤 하나의 finite 연구 episode를 context→proposal→run→diagnosis→synthesis→next/stop으로 진행한다. OS core는 LLM API를 직접 호출하지 않는다.

### 6.2 좋은 입력의 신호 / 봐야 할 메트릭

- provider port는 JSON stdin/stdout 또는 Python Protocol로 주입 가능하다.
- 각 transition은 idempotent하며 crash 후 canonical state에서 다음 미완료 step을 계산한다.
- experiment/invalid proposal/provider call/token·time budget이 모두 finite하다.
- evaluator만 workspace execution을 수행하며 모든 output에 `authorized_action=null`이 유지된다.

### 6.3 자주 하는 실수 (함정)

- provider에게 `ResearchService`나 event append 권한을 직접 주는 것.
- invalid proposal을 attempt budget에서 완전히 제외해 무한 생성하는 것.
- same closed class parameter tweak를 새 hypothesis로 세는 것.
- loop completion을 proposal/node 수나 wall-clock throughput으로 평가하는 것.

### 6.4 코드 관점

- 새 seam: `src/research_os/autonomy/protocol.py`, `loop.py`.
- 기존 serialized workflow lock을 유지한다.
- incomplete provider call/packet/preflight/experiment/diagnosis/synthesis 상태를 event-derived resume로 복구한다.

---

## 7. Meta-evaluation, compatibility, release

### 7.1 무엇을 하는 단계인가

고정된 hidden-ground-truth synthetic suite에서 v0.2와 v0.5를 동일 후보 언어·experiment budget으로 paired 비교한다. pure simulator 36 episodes와 대표 ResearchService E2E를 분리한다.

### 7.2 좋은 입력의 신호 / 봐야 할 메트릭

- 6 family × 6 episodes: mechanism/replication, falsification/closure, gate conflict, invalid/retry/budget, memory relation/contamination, crash/drift/exhaustion.
- attack universe는 `tests/fixtures/protocol_attacks/v1/manifest.json`의 전체 행으로 고정한다. 각 행은 surface/schema version, initial state, malformed or forbidden input, expected stable rejection code, expected no-write invariant를 가지며 차단률 분모는 manifest 전체 위반 행이다. manifest SHA-256과 재현 명령을 phase evidence에 기록한다.
- acceptance generator manifest에 StudyContract family, initial context generator, hidden world transition generator, 모든 non-terminal 상태의 exact 허용/최적 `(hypothesis_class, action)` oracle set, diagnosis/terminal oracle, minimum/wasted attempts, metric formula를 구현 전 commit한다.
- M3 code checkpoint를 freeze한 뒤 repo 밖 임시 custody 경계에서 새 256-bit nonce를 생성하고 36 unseen episode body를 만든다. 두 arm 시작 전 code commit·generator digest·nonce commitment·suite digest를 seal하고, 한 receipt에 두 arm 결과를 결합한다. 결과 노출 후 code/policy 변경은 receipt를 무효화한다.
- next-hypothesis choice accuracy의 분모는 모든 non-terminal oracle decision point다. 선택이 oracle set 밖이거나 closed/duplicate class이거나 required decision을 생략하면 오류다.
- protocol block rate, evidence-bound conclusion, closed-class retry, next-hypothesis choice accuracy, correct terminal decision, wasted attempt를 사전 정의한다.
- `crypto-new`, `manager`, `BinancePredictionStrategy`는 read-only snapshot으로 replay/import 판정만 한다.

### 7.3 자주 하는 실수 (함정)

- v0.2 arm에 v0.5 memory/context를 누출하는 것.
- baseline waste=0 episode에 감소율을 억지로 계산하는 것.
- 구현 후 유리한 episode/threshold를 추가하고 confirmatory라고 부르는 것.
- code release version, event schema, adapter wire, context schema를 모두 “v1/v2” 하나로 혼동하는 것.

### 7.4 코드 관점

- comparator는 commit `6f36a1b`의 context v2 + packaged skill을 byte-fixed fixture로 둔다.
- 제품 release는 `pyproject.toml`, `src/research_os/__init__.py`, `uv.lock`, packaged skill/docs를 동기화한다.
- managed prior release의 exact manifest를 검증하는 0.2→0.3→0.4→0.5와 0.2→0.5 safe upgrade를 제공한다.
- M1-B까지 Python 3.12 regression `371 passed, 104 subtests`와 authority/legacy/race 회귀는 통과했지만, 이는 NS6 learning benchmark를 대신하지 않는다.

---

## 8. 종착지 시스템 모양 (Projected End-State) ★

### 8.1 종착지 시스템 도해

```text
External provider
      │ DecisionPacket (untrusted, authorized_action=null)
      ▼
Context v3 ──▶ Proposal preflight ──▶ Existing integrity/evaluator kernel
    ▲                    │                         │
    │                    │                         ▼
Program Claim Graph ◀─ Synthesis ◀─ Diagnosis ◀─ Terminal Evidence DAG
    │                                  │
    └──── relevance + contradictions ──┘

Canonical truth boundaries:
  Project EventLog  -> execution DAG + study inference reducer
  ProgramLog        -> conditional claim graph
  SQLite/indexes    -> rebuildable projections only
```

### 8.2 종착지에서 가능해진 행동 (관찰 가능)

- 사용자가 versioned StudyContract와 finite generation budget으로 연구를 시작할 수 있다.
- 시스템이 허용되지 않은 transition, budget overrun, closed-class proposal을 등록 전에 차단한다.
- agent가 terminal evidence마다 구조화된 diagnosis를 남기고 class를 열거나 닫을 수 있다.
- agent가 다음 proposal에서 관련 claim·contradiction·limitation을 검색 이유와 함께 볼 수 있다.
- 운영자가 어떤 prior knowledge를 proposal이 사용·기각했는지 exact evidence까지 감사할 수 있다.
- 외부 provider 하나가 유한 자율 연구 episode를 실행하고 crash 후 canonical state에서 재개할 수 있다.
- 운영자가 v0.2 대비 판단 정확도와 wasted attempts를 동일 budget benchmark로 비교할 수 있다.
- 운영자가 각 non-terminal 상태에서 v0.5가 v0.2보다 올바른 다음 hypothesis class/action을 더 자주 선택하는지 직접 비교할 수 있다.
- 기존 세 프로젝트 log를 재작성하지 않고 replay하거나 `legacy_unstructured`로 명시적으로 격리할 수 있다.

### 8.3 종착지에 없는 것 (의도적 제외)

- ✗ 다중 agent community·다수결·role swarm·제품 multi-agent — **NS6 통과 이후**에만 검토하며 v0.5 범위에서는 제외한다.
- ✗ distributed workers·lease scheduler·parallel adaptive children — 현재 single-worker 안전성 유지.
- ✗ graph/vector DB를 canonical truth로 사용 — append-only log + reducer로 충분한지 먼저 측정.
- ✗ Research OS core의 특정 LLM SDK/API key/session 소유 — provider-neutral 경계를 유지.
- ✗ 자동 merge·deploy·model release·capital allocation·live trade — 모든 연구 산출물은 `authorized_action=null`.
- ✗ legacy free text의 자동 의미 추론 — 원문 그대로 opaque import만 허용.
- ✗ 세 외부 프로젝트 live migration — v0.5에서는 read-only compatibility report까지만.

### 8.4 비전 vs 현재 — 갭 요약

| 영역 | 종착지 모습 | 현재 모습 | latest delta |
|---|---|---|---|
| Evidence semantics | 방향 보정 delta와 typed gate/slack이 veto와 무관하게 남음 | M1-A 구현: directional delta/margin, typed gate/slack, baseline/candidate VERIFY 대칭 | Cycle 01 구체화·검증 |
| Study control | StudyContract와 cumulative budget이 atomic registration을 지배 | M1-B 구현: canonical contract/evaluation-sealed generation, replayable ledger, locked registration reservation; `29/29` exact. 단, generation별 non-refundable reservation이며 actual usage telemetry·study-lifetime cap·successor 반복 증액 방지는 없음 | Cycle 02 구체화·검증 |
| Study inference | typed Proposal·Diagnosis·ClassState와 semantic frontier | graph action + free-text scientific change + leaf frontier | 추가 |
| Program memory | conditional Claim graph가 exact origin evidence를 참조 | project-bound generic Finding | 추가 |
| Context | v3가 budget/class/pending diagnosis/relevant claim/reason을 제공 | bounded v2 packet, recent leaf/finding 중심; active generation/reservation ledger 직접 노출 없음 | Cycle 02 limitation 명시 |
| Autonomy | provider-neutral finite state machine이 stop/resume | 외부 대화가 수동으로 단계를 연결 | 추가 |
| Meta-evaluation | post-freeze unseen 36 episodes와 choice oracle로 v0.2/v0.5 paired comparison | full regression `371+104`는 PASS; learning benchmark/comparator/oracle/generator는 없음 | Cycle 02 regression evidence 보강; learning 효과는 미측정 |
| Compatibility/authority | v1 logs 무변환, legacy 격리, authority null 유지 | nested/flat certification lifecycle + M1-B legacy bytes/ID/projection parity, changed surfaces key `8/8`·non-null `0` PASS; 전체 v1 migration/release gate는 미정 | Cycle 02 evidence 보강 |

### 8.5 비전 변경 이력 ★

| Cycle | 일자 | 변경 분류 | 변경 내용 | Trigger |
|---|---|---|---|---|
| 00 | 2026-08-09 | 추가·구체화 | integrity kernel 위에 study inference, program memory, provider-neutral loop와 fixed-budget 판정 종착지를 정의 | 사용자 v0.5 승인과 기존 프로젝트 분석 |
| 01 | 2026-08-10 | 구체화·검증 | Evidence semantics를 typed delta/gate/slack·VERIFY 대칭으로 구현하고 Compatibility/authority의 nested/flat lifecycle·null scan evidence를 보강 | M1-A E1~E9 exact, checkpoint `ed76067` |
| 02 | 2026-08-10 | 구체화·검증 | Study control을 canonical StudyContract·generation·atomic cumulative reservation으로 구현하고 per-generation/non-refundable·no-telemetry·no-lifetime-cap·repeat-increase limitations를 유지; Context와 Meta-evaluation의 남은 갭도 재명시 | M1-B manifest `29/29`, focused `81+37`, full `371+104`, checkpoint `df2c900`; progress critic + independent auditor PASS |

---

## 9. 마일스톤 체크포인트 체인 (Milestone Checkpoint Chain) ★

### 9.0 사용자 verbatim 합의 (Bootstrap step 6.5 인용)

> "위 방향대로 개선해서 v0.5 까지 개선을 진행하고 싶다"

> "추천안 승인 / 로컬 체크포인트 커밋 허용 / 기존 certification 패치 포함"

> "회고 승인 / unseen synthetic benchmark를 v0.5 release gate로 인정 / 실제 프로젝트 live pilot·migration은 v0.5 이후 / multi-agent는 NS6 통과 이후"

### 9.1 M chain 도해

```text
[v0.2.0] ─→ M1 / v0.3 Scientific State ─→ M2 / v0.4 Program Memory
                                             │
                                             └─→ M3 / v0.5 Autonomous Single-Agent Loop
                                                      │
                                                      └─→ [§8 종착지]
```

### 9.2 M_i 정의 표

| M_i | 이름 / 한 줄 정의 | exit criterion conjunction (AND) | prerequisite | §8.4 영역 coverage |
|---|---|---|---|---|
| M1 | v0.3 Scientific State — evidence와 연구 transition을 machine-enforced state로 만든다 | (M1-A~E 전부 closed) ∧ (NS1 신규 M1 suite 100% PASS) ∧ (NS2 6/6) ∧ (NS3 Proposal/Diagnosis/ClassState 3/3 replay) ∧ (기존 262 tests + 57 subtests PASS) ∧ (제품 version 0.3.0) | N/A | Evidence semantics, Study control, Study inference, Context, Compatibility/authority |
| M2 | v0.4 Program Memory — evidence-bound conditional claim을 program 단위로 축적·검색한다 | (M2-A~D 전부 closed) ∧ (NS3 4/4) ∧ (NS4 4/4 exact) ∧ (legacy opaque import tests PASS) ∧ (기존+신규 전체 suite PASS) ∧ (제품 version 0.4.0) | M1-E가 StudyContract/generation/evaluation-scope/Diagnosis/ClassState의 stable version·digest·replay identity를 닫아야 ProgramManifest가 그 identity를 canonical하게 bind하고 ProgramLog가 evidence ref를 검증할 수 있다. 범용 hash-chain utility는 이미 EventLog에 있으므로 M2-A를 선행 구현할 독립 가치가 없고, M1 전 착수하면 unstable identity에 format을 고정하게 된다 | Program memory, Context, Compatibility/authority |
| M3 | v0.5 Autonomous Single-Agent Loop — durable state를 소비하는 finite provider-neutral loop와 효과 판정을 완성한다 | (M3-A~D 전부 closed) ∧ (NS5 7/7) ∧ (NS6 여섯 정량 gate 모두 충족) ∧ (NS7의 replay 3/3 + opaque classification 3/3 + writer diff 0) ∧ (기존+신규 전체 suite PASS) ∧ (제품 version 0.5.0) | M2-D가 ProgramSnapshot/head token, deterministic retrieval manifest, Claim disposition과 synthesis writeback contract를 stable하게 닫아야 DecisionPacket/FSM의 read/write set을 정의할 수 있다. memory를 소비하지 않는 generic provider/FSM은 §1.4 목표가 아닌 기반 코드이므로 M3 진척으로 세지 않는다 | Context, Autonomy, Meta-evaluation, Compatibility/authority |

### 9.3 M_i ↔ §8.4 영역 cross-tab

| §8.4 영역 | M1 | M2 | M3 | cover 종합 |
|---|---|---|---|---|
| Evidence semantics | full | — | regression | M1+M3 |
| Study control | full | regression | regression | M1+M2+M3 |
| Study inference | full | evidence consumer | regression | M1+M2+M3 |
| Program memory | prerequisite | full | consumer | M1+M2+M3 |
| Context | scientific v3 | program v3 | loop packet | M1+M2+M3 |
| Autonomy | transition prerequisite | memory prerequisite | full | M1+M2+M3 |
| Meta-evaluation | instrumentation | transfer fixtures | full | M1+M2+M3 |
| Compatibility/authority | v1/v2 boundary | opaque import | 3-project/release proof | M1+M2+M3 |

### 9.4 Sub-checkpoint partitioning

#### M1 — v0.3 Scientific State

| M_i.j | 이름 | exit conjunct (AND) | parallel 가능? | 비고 |
|---|---|---|---|---|
| M1-A | Decision/evidence correctness | (veto 전 maximize/minimize delta·margin tests PASS) ∧ (typed `gte/lte`, hard/support, signed/normalized slack fail-closed tests PASS) ∧ (baseline verify 대칭 tests PASS) ∧ (nested certification `doctor→review-subject→certify→inspect` CLI lifecycle + flat legacy replay PASS) | ✓ | 승인된 dirty patch 포함 |
| M1-B | Study generation과 누적 budget | (canonical StudyContract schema/digest tests PASS) ∧ (generation open/replay tests PASS) ∧ (attempt/retry/elapsed/cost ledger 산술 tests PASS) ∧ (locked append에서 budget overrun 100% 거절·TOCTOU race tests PASS) | ✓ | evaluation seal과 generation digest 분리 |
| M1-C | Typed Proposal과 replication identity | (Proposal schema/preflight tests PASS) ∧ (candidate payload와 orchestration metadata 분리) ∧ (`evaluation_scope_id` identity/replay tests PASS) ∧ (same frozen candidate + new preregistered scope만 replication 허용; retry/reuse/changed candidate 거절 tests PASS) | 부분 | M1-B generation identity 소비 |
| M1-D | Diagnosis·ClassState·semantic frontier | (terminal evidence-bound Diagnosis schema/replay PASS) ∧ (diagnosis 전 다음 v2 registration 100% 차단) ∧ (conclusive threshold class closure transition PASS) ∧ (invalid/control/inconclusive count 규칙 PASS) ∧ (semantic frontier가 closed/incompatible/non-scientific node 100% 제외) | ✗ | M1-B/C 이후 |
| M1-E | Context v3·legacy compatibility·v0.3 release | (context v3에 generation/budget/class/pending diagnosis/frontier 포함) ∧ (v1 event/context v2/branch conclusion v1 fixture 무변환 replay PASS) ∧ (v2 tokenless write는 legacy 격리 또는 핵심 gate 적용) ∧ (managed v0.2→v0.3 skill upgrade/rollback PASS) ∧ (docs/version 0.3.0 sync + full suite PASS) | ✗ | M1 release gate |

#### M2 — v0.4 Program Memory

| M_i.j | 이름 | exit conjunct (AND) | parallel 가능? | 비고 |
|---|---|---|---|---|
| M2-A | ProgramManifest·ProgramLog | (manifest가 M1의 stable StudyContract/generation/evaluation-scope schema version과 digest를 bind) ∧ (ProgramLog evidence ref가 M1 Diagnosis/ClassState origin을 exact 검증) ∧ (append-only hash-chain/head precondition PASS) ∧ (rebuildable projection/recovery + project/program lock-order concurrency PASS) | ✗ | M1-E stable identity가 기술적 전제인 별도 canonical boundary |
| M2-B | Conditional Claim과 관계 | (Claim applicability/status/maturity schema PASS) ∧ (exact origin event/hash/artifact/evaluation seal 검증 PASS) ∧ (supports/contradicts/supersedes/replicates 관계 reducer PASS) ∧ (immutable supersession PASS) ∧ (incompatible/overlapping scope fail-closed PASS) | 부분 | M2-A 소비 |
| M2-C | Deterministic retrieval·Context integration | (NS4 relevant recall 100%) ∧ (contradiction recall 100%) ∧ (superseded exclusion 100%) ∧ (irrelevant contamination 0%) ∧ (context v3 retrieval manifest와 program head token stale-check PASS) | ✗ | M2-B 이후 |
| M2-D | Knowledge disposition·legacy import·v0.4 release | (Proposal claim disposition `used/rejected/not_applicable` 검증 PASS) ∧ (사용·기각 근거 exact ref 감사 PASS) ∧ (legacy free text 자동 추론 0건 + opaque digest import PASS) ∧ (세 프로젝트 read-only snapshot fixture 생성·writer 변경 0건) ∧ (docs/version 0.4.0 + prior managed upgrade + full suite PASS) | ✗ | M2 release gate |

#### M3 — v0.5 Autonomous Single-Agent Loop

| M_i.j | 이름 | exit conjunct (AND) | parallel 가능? | 비고 |
|---|---|---|---|---|
| M3-A | Provider-neutral DecisionPacket | (versioned packet이 M2 ProgramSnapshot/head, retrieved Claim IDs/reasons, knowledge disposition을 필수 bind) ∧ (JSON subprocess와 Python Protocol provider conformance PASS) ∧ (provider의 direct service/event authority 0) ∧ (malformed/stale/non-null-authority packet 100% 거절) | ✗ | M2-D context/program contract가 기술적 전제; LLM SDK 없음 |
| M3-B | Finite autonomous state machine | (context→proposal→preflight→run→diagnosis→synthesis→next/stop transitions 7/7 PASS) ∧ (각 next proposal이 M2 retrieval을 읽고 synthesis가 evidence-bound Claim/ClassState를 write back) ∧ (각 transition idempotency PASS) ∧ (closed-class experiment registration 0) ∧ (experiment/provider/invalid/token/time budget exhaustion deterministic stop PASS) ∧ (evaluation은 sealed service만 호출하고 terminal summary가 exact evidence refs를 가짐) | ✗ | M3-A + M2 소비 |
| M3-C | Crash-resume·authority·budget stop | (각 미완료 step crash injection 후 canonical resume PASS) ∧ (duplicate terminal/diagnosis/claim append 0) ∧ (stale generation/program head fail-closed PASS) ∧ (`authorized_action=null` all packet/context/event/claim tests PASS) ∧ (deploy/merge/trade operation surface 0) | ✗ | M3-B 이후 |
| M3-D | Benchmark·compatibility·v0.5 release | (precommitted generator + post-freeze nonce/receipt로 unseen 36 episode suite seal) ∧ (protocol block 100%) ∧ (evidence-bound conclusion 100%) ∧ (closed-class retry 0) ∧ (next-hypothesis choice accuracy ≥ `min(90%, v0.2+20%p)`) ∧ (correct terminal decision ≥ `min(90%, v0.2+20%p)`) ∧ (positive-waste aggregate ≤ v0.2의 70%; baseline-zero 예외 준수) ∧ (NS7 replay 3/3 + opaque classification 3/3 + writer diff 0 + docs/version 0.5.0 + 0.2→0.5 upgrade + full suite PASS) | ✗ | 최종 release gate; 결과 노출 뒤 변경 시 receipt 무효 |

### 9.5 M chain 정의 변경 이력

| Cycle | 일자 | 변경 분류 | 변경 내용 | Trigger | Rule 9 retrospective 파일 |
|---|---|---|---|---|---|
| 00 | 2026-08-09 | 추가 | M1 v0.3 → M2 v0.4 → M3 v0.5와 sub-checkpoint/exit conjunction 첫 정의 | Bootstrap step 6.5 사용자 합의 | `docs/research-os-status/00-bootstrap-retro.md` |

---

## 10. 이 프로젝트가 위 틀에 얼마나 부합하는가

총평: v0.2 기반의 integrity·audit·replay와 M1-A/B evidence/study control은 강해졌지만 typed learning state 이후 단계는 대부분 미구현이다. 따라서 기존 kernel과 M1-B canonical generation 경계를 보존하면서 §3→§7을 순서대로 추가한다.

### 10.1 단계별 평가

| 단계 | 부합도 | 구현 위치 / 한계 | 근거 |
|---|---|---|---|
| 1. Evidence semantics | ○ | `results.py`, `config.py`, `policy.py`, `service.py`; typed gates·delta/margin·VERIFY 대칭 구현, metric 의미 타당성은 후속 scope/diagnosis 대상 | M1-A E1~E9; M1-B 포함 full `371 tests + 104 subtests` PASS |
| 2. Study generation | ○ | `science/{contracts,state}.py`, `service.py`, `kernel/{ids,projection}.py`; canonical contract/generation/replay와 locked cumulative reservation 구현. generation별 non-refundable reservation이며 actual telemetry·study lifetime cap·successor 반복 증액 방지는 없음 | M1-B executable manifest `29/29`, focused `81+37`, checkpoint `df2c900` |
| 3. Study inference | ✗ | free-text metadata/leaf frontier, typed diagnosis/class 없음 | `graph_policy.py`, `agent.py`, `service.py` |
| 4. Program memory | ✗ | project-bound Finding만 존재 | `memory/findings.py` |
| 5. Relevant context v3 | ✗ | context v2 bounded snapshot만 존재하고 M1-B generation/reservation ledger를 agent packet에 직접 노출하지 않음 | `agent.py`, `docs/agent-usage.md`; M1-E 범위 |
| 6. Autonomous single-agent | ✗ | provider-neutral CLI는 있으나 canonical loop state 없음 | `docs/architecture.md` |
| 7. Meta-evaluation/release | ✗ | 전체 regression·legacy/authority/race 회귀는 갱신됐지만 learning comparator/generator/unseen benchmark는 없음 | `371 tests + 104 subtests` PASS; NS6 측정 전 |

범례: ◎ 우수 / ○ 양호 / △ 부분 / ✗ 미구현

### 10.2 가장 잘된 부분 (학습 시 참고할 가치)

1. **Canonical integrity** — EventLog hash chain, exact envelope, CAS artifact, fail-closed replay/recovery.
2. **Authority boundary** — research evidence가 merge/deploy/trade를 승인하지 않고 `authorized_action=null`을 유지한다.
3. **Provider-neutral seam** — CLI/adapter process boundary 덕분에 v0.5 loop도 특정 LLM SDK 없이 추가 가능하다.

### 10.3 메꿔야 할 갭 (이 문서 기준)

1. Study control은 canonical generation별 reservation까지 왔지만 actual usage settlement·study-lifetime ceiling·successor 반복 증액 방지와 context v3 노출이 없다.
2. terminal evidence가 Proposal/Diagnosis/ClassState/Claim으로 연결되지 않는다.
3. relevant memory retrieval과 knowledge disposition이 없다.
4. autonomous loop와 fixed-budget unseen learning benchmark가 없다. 제품 multi-agent는 이 NS6 gate 통과 이후까지 명시적으로 유예한다.

### 10.4 한 문장 요약

> Research OS v0.2의 신뢰 가능한 실행·감사 kernel과 M1-B canonical generation 위에, 남은 v0.3 과학 상태, v0.4 program memory, v0.5의 측정 가능한 단일 자율 연구 loop를 순서대로 올리고 제품 multi-agent는 NS6 이후로 남긴다.

---

## 동기화 알림 ★

매 cycle:

- status §12와 본 §8.4·§10을 함께 갱신한다.
- 본 §8.5에 cycle delta를 추가한다.
- phase가 정확히 하나의 active M_i.j와 exit conjunct를 advance/close한다.
- M chain 정의를 바꾸면 §9.5와 Rule 9 user-interactive retrospective를 갱신한다.
- 측정 청구는 pre-spec commit 증거가 없으면 `EXPLORATORY`로 쓴다.

---

## 부록 A. Research OS 코드 작성 체크리스트

```text
□ event envelope v1과 과거 complete line을 수정하지 않았는가
□ 새 canonical reducer가 live path와 replay path 모두에서 동일하게 검증되는가
□ SQLite/index는 rebuildable cache이고 독립 권위가 없는가
□ provider/candidate payload가 event append나 service 권한을 얻지 않는가
□ expected-head·digest·compatibility/generation/program binding을 commit 직전 재검증하는가
□ 모든 실패가 fail-closed terminal 또는 명시적 pending state로 남는가
□ 기존 flat/v1 fixture와 새 typed fixture가 모두 통과하는가
□ 모든 research payload의 authorized_action이 null인가
```

## 부록 B. Scientific claim 체크리스트

```text
□ observation과 interpretation이 분리되어 있는가
□ claim이 exact terminal event/hash/artifact를 참조하는가
□ applicability universe/regime/scope/evaluation seal이 명시되는가
□ adaptive development, replication, holdout maturity를 혼동하지 않는가
□ invalid/infra/control을 scientific rejection으로 세지 않는가
□ superseded claim을 삭제·덮어쓰지 않는가
□ exploratory 결과를 confirmatory 언어로 쓰지 않는가
```

## 부록 C. Version taxonomy

| 버전 종류 | 예시 | 독립성 원칙 |
|---|---|---|
| 제품 release | 0.3.0, 0.4.0, 0.5.0 | milestone close와 일치 |
| event envelope | v1 | 기존 log 무변환 유지 |
| adapter wire | v1 또는 호환 확장 | project integration 경계 |
| Study/Claim/Packet schema | 각 versioned integer | payload별 독립 evolution |
| agent context | v2, v3 | v2 replay/reader 유지 |
