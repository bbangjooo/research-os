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

현재 상태 (Cycle 14 M3-D provisional CLOSE 8/8; Acceptance Attempt 2/release verifier, Rule 9,
amended-foundation critic Q1~Q8 PASS; parent M3/v0.5는 corrected re-audit 전까지 open):

- 1번 ✅/○ — directional delta, constitution-owned typed gate/slack, baseline/candidate verify 대칭과 nested/flat certification lifecycle이 구현·검증됐다.
- 2번 ○ — checkpoint `df2c900`에서 canonical StudyContract·evaluation-sealed generation·replayable cumulative reservation ledger·locked overrun gate가 구현됐다. executable manifest `29/29`, focused `81+37`; 단, generation별 non-refundable reservation이지 actual usage telemetry나 study lifetime cap은 아니며 successor 반복 증액을 막지 않는다.
- 3번 ○ — exact terminal-bound Diagnosis, pending gate, derived ClassState/immutable closure, semantic/retry frontier가 canonical reducer/service/replay에서 동작한다. Final transition `26/23/54/37/7`, negative path `460/460`, five conjunct `5/5`를 충족했다. Diagnosis narrative의 인과 타당성과 learned ranking은 아직 증명하지 않았다.
- 4번 ○ — ProgramManifest/Log, immutable Claim/relation, deterministic retrieval 4/4에 registered
  Proposal-bound disposition과 digest-only legacy replay를 추가했다. Corrected actual durable
  three-way `1/1`, frozen `23/23`, full `713+115`, critic와 corrected audit가 PASS했다.
- 5번 ○ — default Context v3/explicit v2를 보존하면서 exact Claim/reason/contradiction과 Program head가
  actual loop의 다음 Context·DecisionPacket으로 재소비된다. Synthetic learning effect는 M3-D에서 PASS했다.
- 6번 △ — M3-B finite loop 위에 M3-C frozen crash-resume `13/13`, duplicate/stale/authority/forbidden
  five-conjunct `31/31`이 구현됐다. Critic Attempt 1의 lookup→append race gap은 exploratory `3/3`으로
  교정했고 critic Attempt 2와 corrected audit Attempt 2가 PASS해 M3-C를 닫았다.
- 7번 ○ — Attempt 1 `RESULT-INVALID`와 critic Attempt 4 FAIL은 보존됐다. Attempt 5 PASS 뒤 distinct
  code checkpoint/new nonce의 Attempt 2가 choice `96/96`, terminal/evidence `36/36`, retry/waste `0`,
  protocol `24/24`, external `3/3`, full `922+115`, wheel 0.5.0으로 8/8 PASS했고 release verifier가 exact
  재현했다. Final audit Attempt 1의 governance FAIL을 교정했으며 amended-foundation critic과 corrected
  re-audit만 남는다.

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
- M1-A에서 기존 flat certificate와 nested immutable fingerprint lifecycle을 함께 회귀했고, M1-C까지 Python 3.12 전체 `442 tests + 111 subtests`가 통과했다.

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
- M1-C corrected exploratory checkpoint에서 Proposal/scope/replication identity manifest `20/20`, transition `53/53`, locked/cold/rebuild/service direct paths `72/72`가 통과했다. Scope claim은 adapter request delivery identity이며 실제 dataset 독립성·통계적 재현 성공은 포함하지 않는다.

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
- M3 code checkpoint를 freeze한 뒤 `~/.research-os-custody/m3d-v05/<code-commit>`을 원자적으로
  `reserved-before-nonce`로 만든 다음 새 256-bit nonce를 정확히 한 번 생성한다. 두 arm 시작 전
  code/generator/v0.2/nonce/suite/race digest를 seal하고 별도 `reserved-before-arms`를 원자적으로 남긴 뒤,
  외부 immutable result와 repository receipt에 두 arm 결과를 결합한다.
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
- M1-C까지 Python 3.12 regression `442 passed, 111 subtests`와 authority/legacy/race 회귀는 통과했지만, 이는 NS6 learning benchmark를 대신하지 않는다.
- Cycle 14의 sealed receipt는 v0.5 choice `96/96`, terminal/evidence `36/36`, waste `0`과 v0.2
  `1/96`, `0/36`, waste `36`을 기록한다. 이는 six-family synthetic transfer 증거이며 open-domain creativity나
  actual strategy profitability 주장이 아니다.

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
| Study inference | typed Proposal·Diagnosis·ClassState와 semantic frontier | M1-D: exact terminal-bound Diagnosis, pending gate, derived ClassState/immutable closure, semantic/retry frontier가 canonical replay. Interpretation 품질·registered-control·learned ranking은 증명하지 않음 | Cycle 04 `△→○`; transition `26/23/54/37/7`, negative `460/460`, five conjunct 5/5 |
| Program memory | conditional Claim graph가 exact origin evidence를 참조 | Claim graph/retrieval 위에 registered Proposal-bound disposition과 digest-only legacy opaque event가 canonical ProgramLog에 저장·replay됨; M2 closed | Cycle 10 frozen `23/23`; corrected actual three-way `1/1`; full `713+115`; critic + audit PASS |
| Context | v3가 budget/class/pending diagnosis/relevant claim/reason을 제공 | exact retrieval/disposition read set을 finite loop의 next Context/DecisionPacket이 current Program head에서 재소비 | Cycle 12 next-packet witness; focused `60`; critic + audit PASS |
| Autonomy | provider-neutral finite state machine이 stop/resume | three verified logs에서 cold crash-resume `13/13`; duplicate/stale/authority/forbidden `31/31`; lookup→append race `3/3`; independent gates PASS | Cycle 13 `CLOSE`; critic + corrected audit PASS |
| Meta-evaluation | post-freeze unseen 36 episodes와 choice oracle로 v0.2/v0.5 paired comparison | Attempt 2 36 episodes: choice `96/96`, terminal/evidence `36/36`, retry/waste `0`; release verifier exact reproduction | Cycle 14 `△→○`; receipt `95e7eb…5387`; foundation critic PASS; re-audit pending |
| Compatibility/authority | v1 logs 무변환, legacy 격리, authority null 유지 | 0.5.0, actual replay/opaque/no-write `3/3`, writer delta 0, authority null, full `922+115`, wheel/install PASS | M3-D provisional close; parent M3 open; live migration post-v0.5; re-audit pending |

### 8.5 비전 변경 이력 ★

| Cycle | 일자 | 변경 분류 | 변경 내용 | Trigger |
|---|---|---|---|---|
| 00 | 2026-08-09 | 추가·구체화 | integrity kernel 위에 study inference, program memory, provider-neutral loop와 fixed-budget 판정 종착지를 정의 | 사용자 v0.5 승인과 기존 프로젝트 분석 |
| 01 | 2026-08-10 | 구체화·검증 | Evidence semantics를 typed delta/gate/slack·VERIFY 대칭으로 구현하고 Compatibility/authority의 nested/flat lifecycle·null scan evidence를 보강 | M1-A E1~E9 exact, checkpoint `ed76067` |
| 02 | 2026-08-10 | 구체화·검증 | Study control을 canonical StudyContract·generation·atomic cumulative reservation으로 구현하고 per-generation/non-refundable·no-telemetry·no-lifetime-cap·repeat-increase limitations를 유지; Context와 Meta-evaluation의 남은 갭도 재명시 | M1-B manifest `29/29`, focused `81+37`, full `371+104`, checkpoint `df2c900`; progress critic + independent auditor PASS |
| 03 | 2026-08-10 | 구체화·검증 | Study inference에 typed Proposal·scope-bound identity·frozen-candidate replication을 추가하고 v1 service/CLI parity, exact-event ownership과 cold projection race를 보강; Diagnosis/ClassState/frontier와 adapter semantic-consumption limitation은 유지 | M1-C manifest `20/20`, transition/direct `53/72`, full `442+111`, checkpoints `a783a88`~`2e14096`; progress critic + independent auditor PASS |
| 04 | 2026-08-11 | 구체화·검증 | Study inference를 terminal-bound Diagnosis→derived ClassState→semantic/retry frontier까지 구현했다. 두 oracle `RESULT-INVALID`를 철회하고 canonical equality·anti-vacuity·recursion correction으로 재측정했으며, interpretation 품질·registered control·learned ranking limitation은 유지했다 | final seals `10e037…1718`/`92551a…c54`; transition `26/23/54/37/7`; negative `460/460`; direct `67`; bounded `56`; compatibility `20/20`; single floor PASS; progress critic + independent auditor PASS |
| 05 | 2026-08-11 | 구체화·검증 | M1-D state를 opt-in Context v3에 직접 노출하고 exact evidence를 채우는 fail-closed Diagnosis template과 disposable temp-project E2E를 추가했다. Context v2/default token은 보존했고 M1-E release는 청구하지 않았다 | pre-spec `38446f1`; product `7fcfd10`; vertical `4`; final compatibility `127+23`; demo/ruff/ty/diff PASS; independent 7-pass audit PASS |
| 06 | 2026-08-11 | 구체화·검증 | Progress audit의 installer case-ID 미소비를 structured six literal nodes와 receipt binding으로 보정하고 M1을 닫았다 | `b70a98f→e120292`; `609+115`; installer `6/6`; critic + auditor PASS; M1 close |
| 07 | 2026-08-11 | 구체화·검증 | ProgramManifest/Log origin boundary와 projection을 구현하고 critic의 race gap을 barrier·loser writes `0/0`으로 보정했다; Claim/retrieval은 유지 | `d635c61→b10e1b4→704fcb8→5d02fd0`; corrected `22`, race `50/50`, fresh `635+115`; critic + corrected audit PASS; M2-A close |
| 08 | 2026-08-11 | PIVOT·close | Immutable Claim/evidence/relation을 구현하고 critic·audit no-write gaps를 actual writer 측정으로 보강; retrieval은 유지 | `5659c67→529283c→dbd7caa→1b1e22f`; `25`, focused `37`, full `672+115`; critic + corrected audit PASS |
| 09 | 2026-08-11 | 구체화·검증 | ProgramLog→ClaimSnapshot→deterministic retrieval→opt-in Context v3 read path를 구현; disposition은 유지 | `e6de927→e002076→bc0b79a`; receipt `100/100/100/0`; full `676+115`; critic + independent audit PASS; M2-C close |
| 10 | 2026-08-12 | 구체화·검증 (PIVOT correction) | Proposal-bound disposition과 legacy opaque event를 구체화; Attempt 1이 durable three-way를 proxy로 과장해 receipt를 철회하고 actual two-scope append/cold-replay witness로 보정; actual external replay와 M3 loop는 유지 | `4b0d0a1→f5d55ad→9dbb413→f1ab646`; corrected `713+115`, durable `1/1`; critic + corrected audit PASS; M2 close |
| 11 | 2026-08-12 | 구체화·검증 (PIVOT correction) | 비신뢰 provider output을 current Program/Context/retrieval/Proposal에 검증하는 DecisionPacket seam을 추가; historical v0.4 HEAD-bound verifier Attempt 1은 철회·checkpoint-bound correction; FSM/NS5는 유지 | `50ee73d→eb289c4→42c7557`; frozen `32/32`, full `757+115`; critic + corrected audit PASS; M3-A close, M3-B active |
| 12 | 2026-08-12 | 구체화·검증 (`MIXED` correction) | single-provider finite episode와 three-log truth-owner 경계를 구현했다. Critic/audit 결함은 source reconciliation·actual service·type/schema sync로 보정했다. Crash resume·unseen quality는 유지한다 | frozen `43/43`, focused/adjacent `60/125`; critic + audit Attempt 4 PASS; M3-B close, M3-C active |
| 13 | 2026-08-12 | 구체화·검증 (`MIXED` correction, `CLOSE`) | AutonomyLog orchestration·ProjectLog scientific truth·ProgramLog memory truth에서 crash cold-resume를 구현했다. Context/Program rating과 NS6/NS7은 유지하며 외부 billing exactly-once·hostile-provider sandbox·distributed consensus·learning quality는 미청구다 | frozen `31/31`; lookup→append `3/3`; critic + corrected audit PASS; M3-C close, M3-D active |
| 14 | 2026-08-12 | PIVOT correction (`MIXED`, provisional `CLOSE`) | Attempt 1 `RESULT-INVALID`와 Attempt 4 FAIL을 보존하고 sealed canonical-path chronology를 교정했다. Attempt 5 PASS 뒤 distinct new-nonce Attempt 2와 single release verifier가 precommitted eight-conjunct gate를 통과했다 | choice `96/96`, terminal/evidence `36/36`, waste/retry `0`; protocol `24/24`; external `3/3`; full `922+115` twice; audit Attempt 1 FAIL; Rule 9 + foundation critic PASS; re-audit pending |
| 14.5 | 2026-08-12 | 구체화·governance correction (`docs-only`) | M3-D non-regression threshold의 M-chain 변경을 정식 correction/Rule 9 기록으로 고정; §8.2 행동·§8.3 제외·§8.4 영역은 변경 없음 | 사용자 verbatim “승인”; bootstrap critic PASS; re-audit Attempt 2 LOC-only FAIL preserved |

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
| M3-C | Crash-resume·authority·budget stop | (각 미완료 step crash injection 후 canonical resume PASS) ∧ (duplicate terminal/diagnosis/claim append 0) ∧ (stale generation/program head fail-closed PASS) ∧ (`authorized_action=null` all packet/context/event/claim tests PASS) ∧ (deploy/merge/trade operation surface 0) | ✅ | phase 13 close |
| M3-D | Benchmark·compatibility·v0.5 release | (precommitted generator + post-freeze nonce/receipt로 unseen 36 episode suite seal) ∧ (protocol block 100%) ∧ (evidence-bound conclusion 100%) ∧ (closed-class retry 0) ∧ (next-hypothesis choice accuracy ≥ `max(v0.2,min(90%,v0.2+20%p))`) ∧ (correct terminal decision ≥ 동일 non-regression threshold) ∧ (positive-waste aggregate ≤ v0.2의 70%; baseline-zero 예외 준수) ∧ (NS7 replay 3/3 + opaque classification 3/3 + writer diff 0 + docs/version 0.5.0 + 0.2→0.5 upgrade + full suite PASS) | ✗ | 최종 release gate; 결과 노출 뒤 변경 시 receipt 무효 |

### 9.5 M chain 정의 변경 이력

| Cycle | 일자 | 변경 분류 | 변경 내용 | Trigger | Rule 9 retrospective 파일 |
|---|---|---|---|---|---|
| 00 | 2026-08-09 | 추가 | M1 v0.3 → M2 v0.4 → M3 v0.5와 sub-checkpoint/exit conjunction 첫 정의 | Bootstrap step 6.5 사용자 합의 | `docs/research-os-status/00-bootstrap-retro.md` |
| 14 | 2026-08-12 | 강화 (`RULE 9 APPROVED`) | M3-D choice/terminal threshold를 `min(90%, baseline+20%p)`에서 `max(baseline, min(90%, baseline+20%p))`로 강화; baseline >90%에서도 회귀 금지 | pre-unseen critic Attempt 1 Q5; acceptance nonce/result 전 `e23c089→20b35a5`; 사용자 verbatim “승인” | `docs/research-os-status/14.5-correction-non-regression.md` |

---

## 10. 이 프로젝트가 위 틀에 얼마나 부합하는가

총평: v0.3 integrity·audit·replay와 M1-A/B study control, M1-C Proposal identity,
M1-D Diagnosis/ClassState/frontier 위에 default Context v3, tokenless legacy boundary, exact
managed upgrade와 structured six-case release evidence가 `5/5`로 독립 감사 PASS해 M1/v0.3을
닫았다. M2-A `4/4`, M2-B Claim/relation `5/5`, M2-C retrieval `5/5`는 closed했고,
M2-D disposition/legacy/v0.4 evidence도 corrected 5/5, critic, audit PASS로 닫혀 parent M2가
closed다. M3-A DecisionPacket과 M3-B finite loop도 independent gates를 통과해 closed다.
M3-C crash-resume `5/5`는 critic과 corrected audit PASS로 닫혔다. M3-D Attempt 1은 chronology root test
때문에 `RESULT-INVALID`였고 재실행하지 않았다. Historical canonical-path correction은 critic Attempt 5를
PASS했고 distinct new-nonce Attempt 2와 release verifier가 8/8 PASS했다. Rule 9와 amended-foundation critic도
PASS했으며 corrected progress re-audit만 남았다.

### 10.1 단계별 평가

| 단계 | 부합도 | 구현 위치 / 한계 | 근거 |
|---|---|---|---|
| 1. Evidence semantics | ○ | `results.py`, `config.py`, `policy.py`, `service.py`; typed gates·delta/margin·VERIFY 대칭 구현, metric 의미 타당성은 adapter/diagnosis 후속 대상 | M1-A E1~E9; M1-C 포함 full `442 tests + 111 subtests` PASS |
| 2. Study generation | ○ | `science/{contracts,state}.py`, `service.py`, `kernel/{ids,projection}.py`; canonical contract/generation/replay와 locked cumulative reservation 구현. generation별 non-refundable reservation이며 actual telemetry·study lifetime cap·successor 반복 증액 방지는 없음 | M1-B executable manifest `29/29`, focused `81+37`, checkpoint `df2c900` |
| 3. Study inference | ○ | `science/{proposals,diagnoses,state}.py`, `service.py`; Proposal/Diagnosis/ClassState/frontier/Claim replay는 동작하나 interpretation quality·learned ranking은 없음 | NS3 audited `4/4`; M2-B closed |
| 4. Program memory | ○ | `memory/{program,claims,retrieval,knowledge}.py`; Claim graph/retrieval 4/4 + registered Proposal disposition + legacy opaque cold replay; M3 consumer는 open | phases §09~§10; corrected `713+115`, durable `1/1`, critic PASS |
| 5. Relevant context v3 | ○ | exact Claim/reason/manifest/Program-head/disposition을 finite loop가 next Context/DecisionPacket에서 재소비 | phase §12 corrected focused `60`; critic + audit PASS |
| 6. Autonomous single-agent | ○ | finite episode와 cold crash-resume가 independent gates를 통과; hostile provider sandbox는 미청구 limitation | M3-C frozen `31/31`; race `3/3`; critic + audit PASS |
| 7. Meta-evaluation/release | ○ | sealed unseen 36 episodes, public serializers, archived v0.2, crash-durable custody, immutable receipt와 single verifier PASS; synthetic-only limitation 유지 | Attempt 2 8/8; `922+115` twice; receipt `95e7eb…5387`; foundation critic PASS; re-audit pending |

범례: ◎ 우수 / ○ 양호 / △ 부분 / ✗ 미구현

### 10.2 가장 잘된 부분 (학습 시 참고할 가치)

1. **Canonical integrity** — EventLog hash chain, exact envelope, CAS artifact, fail-closed replay/recovery.
2. **Authority boundary** — research evidence가 merge/deploy/trade를 승인하지 않고 `authorized_action=null`을 유지한다.
3. **Provider-neutral seam** — CLI/adapter process boundary 덕분에 v0.5 loop도 특정 LLM SDK 없이 추가 가능하다.

### 10.3 메꿔야 할 갭 (이 문서 기준)

1. Study control은 canonical generation별 reservation까지 왔지만 actual usage settlement·study-lifetime ceiling·successor 반복 증액 방지가 없다.
2. Historical floor 상호 재귀는 차단했지만 세 self-oracle child 때문에 full suite가 약 20분이다.
3. M3-A packet은 memory read set을 검증하고 closed됐지만, FSM이 이를 next action으로 소비하는 것은
   아직 없다.
4. sealed synthetic learning effect는 PASS했지만 actual project live efficacy/profitability는 아직 측정하지
   않았다. 제품 multi-agent는 이제 검토 자격만 생겼을 뿐 구현되지 않았고, live pilot/migration과 함께
   별도 post-v0.5 단계다.

### 10.4 한 문장 요약

> Research OS v0.3의 신뢰 가능한 실행·감사·scientific state 위에 v0.4 program memory와
> v0.5의 측정 가능한 단일 자율 연구 loop를 순서대로 올리고 제품 multi-agent는 NS6 이후로 남긴다.

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
