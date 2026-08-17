# Research OS discovery lane 개선 설계 명세

> 상태: 구현됨 (§18의 1–6단계; 7단계 D2는 §12 측정 게이트 뒤로 보류)
> 적용 경계: opt-in advisory extension (frame-transition seam 재사용)
> 비권한 원칙: 모든 discovery 이벤트와 산출물의 `authorized_action`은 literal `null`

## 1. 목적

Research OS v0.5 + controlled frame-transition은 점프의 **편입**(J2/J3 adoption)을
fail-closed로 통제한다. 그러나 점프의 **발견** — 관찰 축적, anomaly 인지, rival
frame 초안 작성 — 은 여전히 OS 밖의 비정형 활동이다. 그 결과 두 가지 비용이 남는다.

- **기록 비용**: inquiry를 열 때 exhaustion 증거를 소급 수집해야 한다.
- **생성 비용**: 애초에 rival frame 초안이 잘 나오지 않는다.

이 개선은 두 비용을 함께 낮춘다. 발견 레인을 OS의 1급 시민으로 만들고(§5–§7),
그 레인 안에서만 생성 조건을 억제에서 허용으로 뒤집는다(§8–§11).

설계 원리는 **비용 비대칭**이다.

- 발견은 권한을 만들지 않으므로 마찰이 0에 가까워야 한다.
- 편입은 successor generation을 열므로 기존 frame-transition 의식
  (Gate A, rival 비교, 격리 pilot, 독립 리뷰, policy adoption)을 그대로 유지한다.

## 2. 무엇을 할 수 있고 무엇을 할 수 없는가

이 기능은 LLM에 창의성이나 점프 생성 능력을 **설치하지 않는다**. 이유는 공학적
한계가 아니라 정의의 형태다.

- 점프는 현재 프레임에 대해 **부정형으로** 정의된다. J2/J3는 선언된 class 밖,
  선언된 objective 밖이라는 뜻이다.
- 생성기에는 양의 스펙이 필요하다. 그런데 양의 스펙을 쓰는 순간 그 스펙이 정의하는
  공간은 이미 가진 공간이 되고, 그 안의 탐색은 J0/J1로 내려앉는다.
- 검증도 막힌다. 프레임의 가치는 후행적으로만 알려지므로 "점프 능력이 설치되었다"를
  판정할 홀드아웃이 존재하지 않는다.

그러나 부정형 정의에는 뒷면이 있다. **프레임을 명시적으로 들고 있으면 그 여집합은
기계적으로 계산된다.** Research OS는 StudyContract로 hypothesis class, evaluation
scope, compatibility를 선언하고 있고, 이미 unknown class를 fail-closed로 잡아낸다.
즉 OS에는 점프 생성기는 없지만 **점프 검출기는 이미 있다**.

검출기 + 발산 샘플러 + 싼 선별기 = 탐색이다. 이 문서가 설치하는 것은 생성 능력이
아니라 그 탐색이다. 측정 대상도 "점프했는가"가 아니라 **admissible-distinct 초안의
수율**이다. 수율은 ground truth 없이 장부에서 직접 나온다.

## 3. 현재 시스템은 생성을 억제하고 있다

생성 조건은 네 가지이고, 현재 v0.5는 네 가지 모두를 억제 방향으로 걸어 두었다.
이는 확증 커널로서는 올바른 설정이지만, 프레임 초과 후보의 발생률을 구조적으로
0에 가깝게 만든다.

| 조건 | 현재 상태 | 근거 |
| --- | --- | --- |
| 무엇을 보고 생성하나 | exact-class + exact-compatibility 잠금. 다른 class의 claim은 컨텍스트에 들어오지 않는다 | `memory/retrieval.py::_base_match` |
| 무엇을 생성하라고 하나 | 선언된 class 안의 다음 proposal. unknown class는 fail-closed | contract class 폐쇄 |
| 무엇이 살아남나 | baseline 대비 효과 게이트. 프레임 전환 후보는 초기에 항상 진다 | inner loop decision |
| 몇 개를 생성하나 | 예산 안에서 순차 1건 | per-generation budget |

유추는 프레임 전환의 지배적 기제인데 첫 번째 행에서 아키텍처 차원으로 차단되어
있다. **따라서 "점프가 안 나온다"의 원인이 모델 능력 부재인지 컨텍스트 결핍인지
현재로서는 구분 불가능하다.** §8이 이 구분을 가능하게 만든다.

## 4. 재사용할 seam

controlled frame-transition이 검증한 패턴을 그대로 따른다.

- 같은 project-bound append-only `EventLog`에 `research.discovery_*.v1`
  namespaced extension 이벤트를 추가한다.
- 별도의 pure reducer가 discovery lifecycle만 재생한다.
- 기존 scientific reducer, ProgramLog consumer, autonomy 로그는 이 이벤트를 읽지
  않는다. canonical scientific state와 memory는 오염되지 않는다.
- 기존 SQLite schema, `science/state.py`, ProgramLog는 변경하지 않는다.

## 5. 이벤트와 타입

discovery 엔트리는 전부 advisory lane이다. canonical lane 선언은 불가능하며,
registration / validation / promotion / sealing / successor open의 입력이 될 수
없다. 유일한 하류 소비처는 (a) 사람/LLM의 열람, (b) frame-transition inquiry의
exhaustion·rival 증거 인용이다.

```text
research.discovery_note.v1
  kind: observation | anomaly | assumption_conflict | idea | rival_draft
  body: 구조화 텍스트 (아래 스키마)
  refs: 관련 experiment/finding/artifact/diagnosis ID 목록
  digest: body + refs의 content digest
```

kind별 body 최소 스키마:

- `observation` / `anomaly` / `assumption_conflict`: `summary`, `evidence_refs`,
  `open_question`. `evidence_refs`는 **필수이며 비어 있을 수 없다** (§7 참조).
- `idea`: `summary`, `motivating_refs`
- `rival_draft`: frame-transition inquiry의 rival 요구 형식과 **필드 단위로 동일** —
  `rival_id`, `label`, `assumptions`, `mechanism`, `predictions`, `falsifiers`,
  `uncertainty`

`rival_draft`의 필드명은 `frame_transition.py::_RIVAL_KEYS`에서 그대로 가져온다.
초안이 나중에 `frame-transition-open`의 rival 입력으로 **변환 없이** 인용되는 것이
이 설계의 요점이므로, 필드명 불일치는 acceptance criterion 위반으로 다룬다.

## 6. 3-레벨 구성 (기록 레인)

| 레벨 | 내용 | 엔진 변경 |
| --- | --- | --- |
| D0 | 스킬 프로토콜: 세션마다 diagnosis에서 anomaly·가정 충돌을 수확해 discovery 장부에 기록 | 0줄 (SKILL.md만) |
| D1 | `research.discovery_*.v1` extension 이벤트 + 별도 pure reducer + `discovery-note` / `discovery-status` CLI | 소규모 (append + projection) |
| D2 | reducer가 class 폐쇄·반복 실패를 감지하면 agent-context에 discovery prompt 필드 주입 | projection 확장 + Context v3 스키마 변경 |

D1이 핵심이다. D0은 D1의 사용 프로토콜로 흡수되고, D2는 D1 projection 위의 얇은
레이어지만 Context v3 스키마를 건드리므로 §12의 측정 게이트 뒤에 둔다.

## 7. exhaustion 신호와의 연결, 그리고 현재 게이트의 결함

`frame_transition.py::_validate_signals`는 서로 다른 kind의 exhaustion 신호 2개
이상을 요구하고, kind는 정확히 네 가지다: `repeated_failure`, `unresolved_anomaly`,
`assumption_conflict`, `class_closure`.

**현재 실질적으로 사용 가능한 kind는 두 가지뿐이다.** `class_closure`와
`repeated_failure`는 canonical state에서 기계적으로 파생되지만,
`unresolved_anomaly`와 `assumption_conflict`는 세션이 끝나면 사라지는 diagnosis
해석에만 존재한다. 즉 설계된 네 신호 중 절반이 도달 불가능하다. discovery 장부는
이 둘을 복구한다 — 이것이 기록 레인의 가장 큰 실질 효과다.

동시에 게이트에 **수정이 필요한 결함**이 있다. `_validate_signals`는 canonical lane
신호를 하나도 요구하지 않는다. lane이 `advisory`인 신호 2개만으로 inquiry가 열린다.
discovery note는 자기가 쓰는 것이므로, 이 상태로 장부를 추가하면 LLM이 스스로 쓴
note 2건으로 inquiry를 열 수 있다. inquiry 자체는 권한을 만들지 않지만(§14), §1의
"발견은 권한을 만들지 않으므로 마찰 0" 논리는 발견이 어떤 게이트의 입력도 아닐 때만
성립한다.

두 가지를 함께 적용한다.

1. `observation` / `anomaly` / `assumption_conflict` note의 `evidence_refs`를 필수로
   하고, 최소 1개의 canonical experiment / diagnosis ID를 요구한다. 자유 텍스트만으로는
   신호로 인용 가능한 note를 만들 수 없다.
2. `frame-transition-open`에서 canonical lane 신호 최소 1개를 요구한다. advisory
   신호는 canonical 신호를 보강할 수 있을 뿐 단독으로 inquiry를 열지 못한다.

2번은 기존 `frame_transition.py` 검증 강화지만 **blast radius가 0으로 확인되었다.**
현재 `tests/test_frame_transition.py`와 `tests/test_frame_transition_service.py`의
exhaustion 신호 fixture는 모두 `"lane": "canonical"`이며, advisory-only로 inquiry를
여는 통과 케이스가 없다. 강화와 함께 advisory-only 거부를 검증하는 negative 테스트를
새로 추가한다.

읽기 전용 exhaustion projection도 추가한다. canonical state에서 class 폐쇄, 동일
class 연속 REJECTED, 미해결 anomaly note를 집계해 `discovery-status --exhaustion`으로
노출한다. 새 이벤트 없음 — 순수 조회다.

### 7.1 frame-health 해석 패킷 — 판정하지 않는 감지

canonical 신호(`class_closure`, `repeated_failure`)는 전부 **셈하기에 의한 소진**이다.
정체에 의한 소진(열린 class의 margin이 0으로 수렴)과 오류에 의한 소진(프레임 자체가
틀린 carving)은 기계적으로 판정할 수 없고, 판정하려는 시도 자체가 잘못이다 — 그것은
해석이고, 해석은 읽는 쪽의 일이다.

`discovery-status --frame-health`는 판정 없는 증거 패킷을 낸다:

- class별 lifecycle, closure 카운터, **margin 궤적 원시 수열** (experiment ID,
  terminal status, promotion_margin, mechanism 순서대로)
- `study_stop.all_classes_closed` (사전등록 프레임 전체 소진의 최강 canonical 신호)
- 장부에 기록된 open question들
- `interpretation_requests` — 읽는 LLM이 스스로 답해야 하는 세 질문:
  `stagnation`, `assumption_misfit`, `frame_misfit`. 각 질문은 "예"로 판단했을 때
  기록할 note kind를 지시한다.

패킷은 `stagnating: true` 같은 계산된 결론을 절대 싣지 않는다 (테스트로 고정).
LLM이 "예"라고 판단해 note를 기록하면, 그 판단이 canonical ID를 인용한
advisory exhaustion 신호가 된다. 즉 감지 루프는 **OS가 증거를 나르고 LLM이
판단하는** 구조로 닫힌다.

### 7.2 jump dossier — 절벽의 지도

rival_draft는 advisory 자유 텍스트고, 실제 J2/J3는 successor StudyContract +
(대개) 새 candidate schema + 재인증이다. 그 사이의 프로젝트 소유 의무들은 지금까지
어디에도 열거되지 않은 수동 절벽이었다.

`discovery-dossier NOTE_ID`는 draft 하나에 대해 다음을 한 문서로 낸다:

- draft 본문과 fingerprint
- 현재 프레임 사실: 선언된 hypothesis class들, evaluation scope들,
  `intervention_surface` (candidate_schema_digest 포함)
- exhaustion 스냅샷과 inquiry 개설 조건 충족 여부
- `authoring_obligations` — 순서 있는 의무 목록, 각각 소유자 명시:
  successor contract 저작(author), candidate schema 판단(author),
  재인증(independent_reviewer), objective 변경 change-control(independent_reviewer),
  frame-transition inquiry 입력(author), adoption 경계(designated_human)

dossier는 지도이지 승강기가 아니다 — 아무 단계도 수행하지 않고 아무 권한도 만들지
않는다. successor contract는 LLM이 저작하고, 재인증과 ratification의 권한 분리는
그대로 유지된다.

---

## 8. G1 — 유추 검색 레인 (생성 레인, 레버리지 최대)

`memory/retrieval.py::_base_match`는 claim의 `applicability.hypothesis_class_id`와
`compatibility_digest`가 query와 정확히 일치할 것을 요구한다. 그래서 생성 시점의
컨텍스트에는 **다른 class의 재료가 원리적으로 들어오지 못한다.**

`retrieve_claims`는 그대로 두고, 같은 `ClaimSnapshot` 위에 `retrieve_analogies`를
추가한다. 필터를 뒤집어 class 또는 compatibility digest가 **다른** claim을 반환한다.

- 반환 타입은 `RetrievalResult`가 아니라 별도의 `AnalogyResult`다. 이것이 fail-closed의
  구조적 근거다 — `memory/knowledge.py`의 retrieval binding 검증은 `RetrievalQuery`의
  `hypothesis_class_id`가 proposal과 일치하는지를 보므로, 타입이 다르면 canonical
  registration 경로에 **애초에 전달될 수 없다.**
- 모든 hit는 `lane: "advisory"` 및 출처 `source_generation_id` /
  `source_compatibility_digest`를 함께 싣는다. 이 형태는 `_validate_signals`가 이미
  요구하는 필드 구성과 같으므로, 유추 hit를 그대로 advisory 신호로 인용할 수 있다.
- 결과는 canonical 결정 입력이 아니므로 retrieval digest를 program head에 결속하지
  않는다. 다만 재현 가능해야 하므로 자체 digest와 정렬 규칙은 `retrieve_claims`와
  같은 결정적 방식을 따른다.

승격 차단 장치는 새로 만들지 않는다. `frame_transition.py`가 이미
cross-generation / cross-compatibility 증거는 advisory여야 한다고 fail-closed로
강제하고 있다.

## 9. G2 — 잔차형 생성 과제

"창의적으로 제안하라"는 채점 불가능한 넛지다. 대신 점프의 기계적 형태를 과제로
준다: **실패한 class의 공유 불변항을 부정하라.**

`Proposal`은 assumption 목록을 별도 필드로 갖지 않고 `mechanism`,
`predicted_effect`, `falsifier`를 기록한다. 따라서 공유 전제를 직접 계산할 수는
없고, closed class 안에서 REJECTED로 끝난 proposal들의 **mechanism 집합**을 제시해
공유 commitment의 진술을 과제의 일부로 넘긴다.

```text
이 N개 실험이 closed hypothesis class 안에서 실패했다.
[실패한 mechanism 목록과 각각의 falsifier]
이 mechanism들이 공유하는 commitment를 진술하라.
그 commitment가 거짓인 프레임을 제안하라.
```

새 truth를 만들지 않는다 — canonical state 위의 projection 1개다. 넛지가 아니라
**계산된 과제**이므로 과제 자체가 결정적으로 재현된다.

closed class가 없거나 REJECTED 이력이 없으면 해당 class를 생략한다. 빈 과제를
생성하지 않는다.

## 10. G3 — 생성 시점의 발산 강제

`frame_transition.py::_validate_rivals`는 정규화된 `assumptions` + `mechanism`의
sha256 fingerprint로 rival 간 실질 차이를 강제한다. 순서·대소문자·연속 공백을
정규화하므로 relabeling이나 순열로는 통과하지 못한다.

**이 함수를 inquiry 시점에서 생성 시점으로 앞당긴다.** K개 초안을 생성하고,
fingerprint가 충돌하는 초안은 기각하고 재생성한다.

샘플러에서 프레임 초과 후보를 얻는 신뢰 가능한 방법은 "하나를 잘 뽑기"가 아니라
"발산하는 집합을 뽑기"다. 구현은 기존 fingerprint 로직을 공용 헬퍼로 추출해
재사용하는 것이고 새 판정 규칙은 없다.

## 11. G4 — 게이트가 아니라 선별기

프레임 전환 후보가 오늘 죽는 이유는 점진 개선과 **같은 게이트**를 통과해야 하기
때문이다. 초안에는 게이트 대신 선별기만 적용한다.

- 형식이 스키마에 맞는가 (§5의 `rival_draft` 필드 전부)
- `falsifiers`가 비어 있지 않고, 각 항목이 실제로 발화 가능한 관측을 서술하는가
- 기존 초안 전부와 fingerprint가 다른가 (G3)
- canonical ref를 최소 1개 인용하는가

통과하면 장부에 남는다. 그것뿐이다. 사전등록도, 예산도, compatibility 검사도 없다.
**admissibility는 기계적으로 판정하고 가치 판정은 기존 inner loop과 frame-transition
경로로 미룬다.** 이 분리가 비용을 낮추는 핵심이다.

## 12. 수율 측정 — 유일하게 값을 치를 측정, 그것도 공짜

generation마다 다음을 로그한다.

- admissible 초안 개수
- distinct fingerprint 개수
- 초안이 인용한 유추 hit 중 cross-class 비율

별도 study를 열지 않는다. 장부에서 직접 집계되며 `discovery-status --yield`로 조회한다.

이 곡선이 판정 도구다.

- G1 + G2를 켠 뒤에도 admissible-distinct 초안 수가 움직이지 않으면 **G1/G2를 되돌린다.**
- D2(`discovery_prompt` 컨텍스트 주입)는 Context v3 스키마 변경을 요구하므로
  ([`agent.py`가 `schema_version != 3`을 하드 거부한다](../src/research_os/agent.py))
  이 곡선에서 프롬프트 필드 유/무 차이가 확인된 뒤에만 durable하게 만든다.

부수 효과로, 이 곡선은 "이 모델이 애초에 프레임을 초과할 수 있는가"에 대한 가장 싼
답이기도 하다. 능력이 없으면 유추 재료를 넣어도 곡선이 평평하게 나오고, 그 결과가
한 generation 안에 확인된다.

## 13. 스킬 프로토콜 (D0, SKILL.md 추가분)

현재 `SKILL.md`에는 frame-transition 사용 프로토콜이 **한 줄도 없다**. agent 세션
입장에서 그 기능은 존재하지 않는 것과 같다. 아무도 여는 법을 모르는 레인에 장부를
먼저 쌓는 것은 순서가 뒤집힌 것이므로, frame-transition 프로토콜을 함께 작성한다.

- 매 diagnosis 직후: 해석에서 anomaly·가정 충돌이 드러나면 `discovery-note`로
  기록한다. 기록은 research 모드의 inbox-only 규칙의 예외가 아니다 —
  `discovery-note`는 inbox가 아니라 EventLog append이며 프로젝트 파일을 건드리지
  않는다.
- context packet에 `discovery_prompt`가 있으면: research route 세션에서 §9의 잔차
  과제에 따라 `rival_draft` 후보를 0개 이상 생성해 기록한다. 생성 강제는 아니다.
- `rival_draft`가 존재하고 exhaustion 신호 조건(§7: canonical ≥1 포함, 서로 다른
  kind ≥2)이 충족되면: 사용자에게 frame-transition inquiry 개설을 제안한다.
  자동 개설하지 않는다.
- frame-transition 명령 순서와 각 단계의 권한 경계를 명시한다: `gate-a` →
  `open` → `decide` → `authorize-pilot` → `record-pilot` → `review` →
  `adopt-policy` → `activate`. pilot 허가는 채택이 아니며, 각 receipt는 재사용되지
  않는다.
- discovery 엔트리는 어떤 경우에도 canonical 증거로 승격을 주장하지 않는다.

## 14. CLI

기존 명령은 변경하지 않고 opt-in 명령을 추가한다. dispatch는 `cli.py`의
`frame-transition-` prefix 패턴을 따른다.

```text
research-os --project ABS discovery-note note.json
research-os --project ABS discovery-status [--kind KIND] [--limit N]
research-os --project ABS discovery-status --exhaustion
research-os --project ABS discovery-status --residual
research-os --project ABS discovery-status --yield
research-os --project ABS discovery-analogies query.json \
  --program-root ABS_PROGRAM_ROOT --program-id PROGRAM_ID
```

- `discovery-note`: strict JSON 1건을 §5 스키마와 §11 선별기로 검증 후 append.
  성공 시 event ID와 digest를 반환한다. 수정·삭제 명령은 제공하지 않는다
  (append-only; 정정은 새 note로).
- `discovery-status`: replay-derived 장부 조회. kind 필터, 최신 N건, 각 엔트리의
  digest와 refs 포함. `--exhaustion` / `--residual` / `--yield`는 상호 배타적이다.
- `discovery-analogies`: G1 유추 검색. `AnalogyResult`를 반환하며 모든 hit에
  `lane: "advisory"`가 붙는다. ProgramLog는 `ResearchService` 밖에서 소유되므로
  store를 명시적으로 지정한다.

advisory lane은 canonical project state를 부트스트랩하지 않는다. 초기화되지 않은
프로젝트에서는 `doctor`를 먼저 실행해야 한다.

## 15. 명시적 비목표

- 점프/아이디어의 자동 생성 스케줄러를 만들지 않는다.
- Gate A, pilot, 독립 리뷰, policy adoption의 어떤 단계도 간소화하거나 우회하지
  않는다. 편입 비용은 의도된 방화벽이다.
- discovery 이벤트를 ProgramLog나 canonical finding으로 자동 투입하지 않는다.
- 유추 레인을 canonical retrieval에 병합하지 않는다. `retrieve_claims`의 exact-class
  동작은 한 줄도 바뀌지 않는다.
- discovery 장부를 근거로 예산을 증액하거나 closed class를 재개하지 않는다.
- 외부 행동, 배포, 거래, 자본 배분 권한을 부여하지 않는다.
- 창의성이나 점프 생성 능력의 설치를 주장하지 않는다(§2). 주장은 수율 곡선이
  뒷받침하는 범위로 제한한다.

## 16. Acceptance criteria

기록 레인:

- `discovery-note`가 kind별 스키마를 strict 검증하고 위반 시 구조화 오류를 반환
- append-only: 수정/삭제 경로 부재, 동일 body 재기록 시 별개 이벤트
- `discovery-status`가 live state와 cold replay에서 같은 결과를 반환
- exhaustion projection이 canonical state만 읽고 새 durable write를 만들지 않음
- `rival_draft` 스키마가 `frame_transition.py::_RIVAL_KEYS`와 필드 단위로 일치

생성 레인:

- `retrieve_claims`의 반환값이 유추 레인 도입 전후로 동일 (기존 retrieval 테스트 불변)
- `retrieve_analogies`가 query와 같은 class·compatibility의 claim을 반환하지 않음
- `AnalogyResult`가 canonical registration/validation 경로에 전달될 수 없음
  (타입 불일치로 fail-closed, 테스트로 고정)
- 유추 hit를 canonical lane 신호로 선언하려는 시도가 fail-closed
- G3 fingerprint 헬퍼가 frame-transition rival 검증과 동일한 결과를 반환
  (relabeling·순열·공백 변형이 통과하지 못함)
- G4 선별기가 falsifier 없는 초안, fingerprint 중복 초안, canonical ref 없는 초안을 거부

게이트 수정:

- canonical lane 신호 0개인 inquiry 개설이 거부됨
- `evidence_refs`가 빈 note는 exhaustion 신호로 인용 불가

전역:

- 기존 scientific reducer / ProgramLog / autonomy 동작이 discovery 이벤트 전후 동일
  (기존 focused/full regression 통과)
- 모든 discovery 이벤트·응답의 recursive `authorized_action`이 null
- discovery 엔트리를 registration/validation/promotion/successor 입력으로 사용
  시도하면 fail-closed

## 17. 구현 파일 (제안)

- `src/research_os/discovery.py`: contracts, pure reducer, G4 선별기,
  exhaustion / residual / yield projection
- `src/research_os/discovery_service.py`: EventLog append/replay, native API
- `src/research_os/memory/retrieval.py`: `AnalogyQuery`, `AnalogyHit`,
  `AnalogyResult`, `retrieve_analogies` 추가
  (`retrieve_claims`, `_base_match`는 변경하지 않음)
- `src/research_os/frame_transition.py`: `rival_fingerprint` 헬퍼 추출,
  canonical 신호 ≥1 요구
- `src/research_os/cli.py`: `discovery-note`, `discovery-status`, `discovery-analogies` dispatch
- `src/research_os/resources/research-os/SKILL.md`: discovery 프로토콜 +
  frame-transition 사용 프로토콜
- `tests/test_discovery.py`, `tests/test_discovery_service_cli.py`,
  `tests/test_analogy_retrieval.py`

## 18. 구현 순서

레버리지 대비 비용 순이며, 각 단계는 앞 단계 없이도 독립적으로 가치가 있다.

1. **SKILL.md 프로토콜** (§13) — 엔진 0줄. 현재 frame-transition 커버리지가 0이므로
   지금 가장 큰 레버리지다.
2. **D1 장부** (§5, §6) — 이벤트, reducer, `discovery-note` / `discovery-status`.
   `rival_draft` 필드명을 `_RIVAL_KEYS`에 맞춘다.
3. **신호 조건 강화** (§7) — canonical ≥1, `evidence_refs` 필수.
4. **G1 유추 레인** (§8) — 생성 조건 개선의 실질 지점.
5. **G2 잔차 과제 + G3 발산 + G4 선별기** (§9–§11).
6. **수율 곡선** (§12) — 4·5단계의 유지/철회를 이 곡선으로 결정.
7. **D2 컨텍스트 주입** — 6단계에서 효과가 확인된 뒤에만.

## 19. 남은 결정 (구현 세션에서)

- exhaustion 임계의 기본값 (class 폐쇄 1건? 신호 2종?)과 프로젝트별 override 여부
- `discovery_prompt`의 Context v3 스키마 버전 처리 (v3 minor 확장 vs v4).
  `agent.py`가 `schema_version != 3`을 하드 거부하고 bound context snapshot에서도
  같은 검사를 하므로, 필드 추가가 기존 bound token을 무효화하는지 먼저 확인한다.
- `retrieve_analogies`의 기본 반환 폭 (다른 class 전체 vs 인접 scope 우선)과 limit
- 유추 hit 정렬 규칙 — `_scope_specificity`를 재사용할지, cross-class 전용 순위를 둘지
- discovery 장부의 스냅샷/보존 정책 (evaluator-certification처럼 snapshot-excluded로
  둘지, 일반 이벤트처럼 포함할지 — 기본: 일반 이벤트로 포함)
