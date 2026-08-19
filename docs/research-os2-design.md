# Research OS 2 — Kernel / OS / Application 재설계

> 상태: **설계 문서** (`EXPLORATORY`)
>
> 작성일: 2026-08-19
>
> 범위: 기존 Research OS(v0.7.0)를 loop 프레임워크를 kernel로 하는 3층 구조로 전면 재작성하는 설계. 이 문서는 설계만 정의하며 code change, 마이그레이션 실행, 기존 v0.5 historical close의 변경을 승인하지 않는다.
>
> 입력 분석: `~/infocz/gos/loop/experiment_loop.py`(1,663줄, 최신), `~/crypto-new/loop/experiment_loop.py`(2026-08-18 vendored 사본), 현행 research-os 전체 구조, `docs/evaluation-driven-research-os.md`(post-v0.5 자기비판).

---

## 0. 설계 한 문장

> **Kernel은 오르기만 하고, OS는 어디를 오를지만 정하고, journal은 얼마나 올랐다고 주장할 수 있는지만 정한다. LLM은 방향 제안과 해석을 파일로만 내고, 그 파일이 없으면 시스템은 구조적으로 멈춘다.**

### 0.1 재설계 결정의 근거

1. **현행 시스템은 과하게 복잡하다.** src+tests 67,688 LOC 중 본질 코어는 3–4k 줄로 추산된다. 나머지는 (a) LLM 행동 순서를 단속하는 상태기계, (b) 자기증명 장치(fixture·receipt·oracle), (c) 중복 실행 경로(run-once + autonomy FSM), (d) git/digest가 공짜로 주는 원시 기능의 재구현이다.
2. **복잡성의 근본 원인은 도메인이 아니라 LLM/비LLM 경계 설계다.** 현행 시스템은 LLM의 판단 시퀀스를 상태기계로 감시한다(receipt, context token, pending obligation, 서명 순서). loop 프레임워크는 산출물만 측정한다(guard, digest, 스칼라). **산출물 검증은 싸고, 행동 순서 단속은 비싸다.** 경계를 바꾸면 같은 불변식을 1/10 규모로 유지할 수 있다.
3. loop은 이미 두 repo(gos 리팩토링, crypto-new 리서치)에서 무수정 이식으로 검증된 domain-free 단일 파일이며, kernel 자격이 실증됐다.

---

## 1. 구조 인식: Kernel / OS / Application

### 1.1 3층 구조

```
┌─ Application (프로젝트 repo) ──────────────────────────────┐
│ contract.toml · evaluator · 데이터 표면 · .journal/        │
├─ OS (outer loop — 런타임: agent 하네스) ───────────────────┤
│ aim    (contract, journal) → spec.yaml        [결정론]     │
│ read   diagnosis/discovery 파일 저작           [LLM]        │
│ steer  status·frame-health·residual projection [결정론]     │
│ jump   residual→rival→dossier→successor 계약   [결정론 도구 │
│                                          + LLM 저작 입력]  │
│ memory claims.jsonl + exact-class retrieval    [결정론]     │
│ seal / verify  journal hash-chain             [결정론]     │
├─ Kernel (inner loop) ──────────────────────────────────────┤
│ loop: bounded·reversible·budgeted hill-climb               │
│ guards · integrity pins · ledger · 결정론 게이트            │
└────────────────────────────────────────────────────────────┘
```

### 1.2 Kernel 위 모든 것은 loop의 조준 장치다

Kernel loop은 **눈먼 실행기**다. spec이 지정한 스칼라 objective를 예산 안에서 정직하게, 되돌림 가능하게 오른다. 방향이 옳은지는 절대 판단하지 못한다. OS 레이어 전부는 kernel이 스스로 물을 수 없는 세 가지 질문에 답하기 위해 존재한다.

1. **이 objective가 옳은 proxy인가?** — aim(등록) + read(진단)
2. **이 frame이 아직 오를 가치가 있는가?** — steer(frame-health, residual)
3. **다음 frame은 무엇인가?** — jump + memory

### 1.3 이중 루프

```
outer loop (OS: 조준, 시간~일 단위, LLM 판단이 파일로 유입)
  aim → [inner loop 실행] → read → steer → (jump) → aim …
        inner loop (kernel: 초~분 단위, 완전 결정론)
          측정 → agent 변이 1회 → guard → commit / revert
```

- **inner loop** = kernel 1 run. 1 iteration = objective 측정 → agent argv 1회 호출 → integrity 재확인 → guard → 재측정 → 개선이면 `git commit`, 아니면 `git reset --hard`. 증명은 loop이 아니라 guard가 담당한다.
- **outer loop의 런타임 = agent 하네스(Claude Code / Codex) 그 자체.** 별도 CLI 제품도, autonomy FSM도 존재하지 않는다. skill 문서가 outer loop의 프로그램이고, 결정론 도구들은 agent가 실행하는 계기(instrument)다.

---

## 2. 설계 헌법

### 2.1 LLM/비LLM 경계 규칙 (5개)

1. **결정론 도구는 LLM을 절대 호출하지 않는다.**
2. **LLM 출력이 시스템에 들어오는 문은 2종뿐이다.** ① worktree 변경(kernel guard가 검사), ② 판단 파일(advisory 데이터, digest 봉인).
3. **판단은 상태 전이가 아니라 파일이다.** 진행을 gate하는 모든 LLM 판단은 "다음 결정론 단계가 소비하는 입력 파일"로 물화된다. 집행은 "입력 파일 없음 / digest 불일치"라는 구조적 불가능이지, 상태기계의 거절이 아니다.
4. **anti-gaming = digest + budget + revert.** 권한·신뢰가 아니다.
5. **판정은 결정론 reducer가 증거에서 계산한다.** LLM은 해석을 쓰고, 도구가 결정을 계산한다.

### 2.2 상태기계 재발 방지 규칙 (4개)

재작성의 최대 함정은 "구조적 집행"으로 시작해 어느새 receipt 엔진을 다시 기르는 것이다. 다음 규칙 위반은 기능이 아니라 설계 버그다.

- **A. 도구 = 순수 함수.** 파일 입력 → 파일 출력 + journal append 최대 1회. 출력 파일 밖의 상태 보유 금지.
- **B. 검증의 참조 허용 범위** = 입력 파일 내용, digest, 순수 reducer에 의한 journal replay. 금지 = "의식이 어디까지 진행됐는지"를 담는 상태/락 파일. **워크플로 상태 = 어떤 파일이 존재하는가, 그것뿐이다.**
- **C. 순서 = 데이터 의존.** 단계 B가 단계 A 뒤여야 한다면, B의 입력에 A의 출력 digest를 포함시킨다. phase enum 금지.
- **D. 냄새 규칙.** 파일 + digest + replay 이상의 기억을 요구하는 검사가 생기면 설계 오류로 간주하고 중단한다.

선택 사항: Research OS 2 자체를 kernel loop 밑에서 개발한다. 모듈 수·LOC를 `non_increasing_number` guard로 걸어 kernel이 자기 OS의 비대를 물리적으로 거부하게 한다.

### 2.3 불변식 이행표

`docs/evaluation-driven-research-os.md` §3.6의 "줄이면 안 되는 것"을 기계가 아니라 구조로 이행한다.

| 불변식 | 구세계 기계 | 신세계 구조 |
| --- | --- | --- |
| 정본 권위 분리 | 3개 로그 + 각자 replay/reducer 기계 | journal(증거) / notes(판단) / ledger(실행) 3파일. 분리는 **소비자 규칙**으로 집행: aim은 (contract, journal)만 읽는다. notes가 spec에 닿는 유일한 경로는 jump 채택 이벤트다 |
| exact provenance + append-only replay | CAS + SQLite projection + 복구 하네스 | hash chain + 모든 이벤트가 입력 파일 digest를 인용 |
| run 중 evaluator 불변성 | certification.py 1,671줄 + drift 무효화 | kernel integrity pin + 결정론 게이트(이미 kernel 내장, 신규 코드 0) |
| stale context 차단 | context_token 발급/검증 | **원천 소멸** — 모든 컨텍스트를 매번 파일에서 결정론적으로 조립(loop의 stateless agent 패턴). 토큰이 지킬 상태 자체가 없다 |
| deterministic hard gate + budget stop | service.py 내 예산 기계 | inner = kernel budget. outer = aim이 journal replay로 generation 예산을 계산하고 소진 시 spec 생성을 거부 |
| `authorized_action = null` | 모든 응답에 null 필드 + 검증 | **필드 자체 부재.** 외부 행동(배포·트레이딩·릴리스)을 표현할 스키마가 없다. 단속할 문이 없는 것이 최강의 단속이다 |

---

## 3. 파일 계약

인터페이스는 CLI가 아니라 파일 + 계기 + skill이다.

| 파일 | 쓰는 자 | 읽는 자 | 권위 |
| --- | --- | --- | --- |
| `contract.toml` | 사람/agent 저작. successor는 jump 도구만 | aim, steer | frame 정의. run 중 kernel integrity pin 대상 |
| `spec.yaml` | **aim 도구만** (contract + journal에서 생성) | kernel | kernel 입력. 손저작 금지 |
| `.journal/events.jsonl` | **seal 도구만** (hash-chain append) | 모든 계기 | **유일 정본.** agent가 직접 append하는 경로가 없다 |
| `notes.jsonl` | agent가 note 도구 경유 (형식 검열 + ref digest 검증) | steer, jump | advisory. 권한 0 |
| `claims.jsonl` | memory 도구 | aim(컨텍스트 조립 시) | advisory retrieval |
| kernel `ledger.jsonl` / `summary.json` | kernel | seal | 실행 원격측정. run 종료 후 journal에 봉인 |
| diagnosis / rival draft / dossier / 승인 파일 | agent(LLM) 저작 | 해당 소비 도구 | 소비 도구의 입력 재료. digest로 인용될 때만 효력 |

우회 방어: agent가 봉인된 것을 수정하면 replay에서 chain/digest가 깨진다. 단속이 아니라 변조 증거다.

---

## 4. 계기(도구) 명세

모든 계기는 §2.2 규칙 A(순수 함수)를 따른다. 예상 규모는 구현 목표치다.

| 계기 | 입력 | 출력 | 규모 |
| --- | --- | --- | --- |
| `loop` (kernel) | spec.yaml, worktree | commits, ledger, summary | ~1.7k (gos 최신본 vendoring, 테스트 1.7k 동반) |
| `journal` (seal/verify/replay) | 봉인 대상 파일들 + journal | append 1회 / 검증 리포트 | ~0.6k |
| `aim` | contract.toml, journal, (직전 run seal digest, 직전 diagnosis digest) | spec.yaml | ~0.7k |
| `steer` (projections) | journal, notes | status / frame-health / residual / dossier JSON | ~0.6k |
| `jump` | dossier·successor contract·독립 리뷰·human 승인 파일 4개의 digest | 채택 이벤트 1개 (원자 append) + successor contract 확정 | ~0.4k |
| `memory` | journal, diagnosis 파일 | claims.jsonl append, retrieval 결과 | ~0.4k |
| `note` | agent 저작 note | notes.jsonl append (검열 통과 시) | ~0.3k |

합계 **~4.7k 줄** + 동급 테스트. 현행 67k의 약 7%.

계기별 핵심 거부 규칙(fail-closed):

- `aim`: 직전 run의 seal 이벤트 digest가 없으면 거부. 직전 run의 diagnosis 파일 digest가 없으면 거부. generation 예산(journal replay로 계산) 소진 시 거부.
- `jump`: 4개 입력 파일 중 하나라도 없거나 digest 불일치면 이벤트를 만들 수 없다. FSM·receipt 재사용 검사 불필요 — 채택은 원자 이벤트 1개다.
- `note`: signal-bearing note(anomaly, assumption_conflict 등)는 evidence ref digest 없이는 거부.
- `seal`: 봉인 대상 파일 부재 시 거부. journal truncated tail은 append 전 복구(kernel ledger와 동일 패턴).

---

## 5. Outer loop 사이클 (SKILL.md = 이 프로그램)

1. `verify` (journal replay + digest 검사) → `status` projection이 다음 필요 입력을 지시한다.
2. 미봉인 diagnosis가 있으면: diagnosis 파일 저작 → `seal`.
3. `aim` → spec.yaml. (예산 소진 / diagnosis 누락 시 거부되고, 거부 사유가 곧 다음 할 일이다.)
4. kernel `loop run spec.yaml`.
5. `seal` — summary.json + ledger.jsonl + trials.jsonl의 digest를 journal에 봉인.
6. read: diagnosis + discovery note 저작 → seal.
7. steer: frame-health projection을 읽고 interpretation request에 note로 답한다.
8. frame 소진 판정 시 jump 차선: residual → rival draft → dossier → successor contract → 채택 seal.
9. 반복.

모든 화살표는 결정론 도구이거나 LLM 저작 파일이다. 둘 다인 것은 없다.

세션 crash/중단 처리: 새 세션이 `verify` → `status`를 실행하면 journal replay가 봉인된 것과 미결인 것을 정확히 알려준다. resume = 상태 읽기이며, FSM은 0줄이다.

---

## 6. LLM / 비LLM 경계 최종표

| | LLM (agent) | 결정론 도구 |
| --- | --- | --- |
| 한다 | 의도, 가설, diagnosis 텍스트, note, rival draft, contract 초안, 해석 답변, kernel iteration 내부의 변이 | 측정, spec 생성, 봉인, 투영, 검증, 예산 계산, 거부 |
| 절대 안 한다 | journal append, 예산 계산, spec 방출, 채택 유효성 판정 | LLM 호출 |

---

## 7. 통계 규율: proxy 면허와 다중검정

kernel의 본질적 한계 — noisy objective에 대한 hill-climbing은 backtest 과적합 기계다(N iteration = 같은 holdout N회 조회). 이 한계를 다루는 책임은 OS의 aim 레이어가 소유한다.

- 모든 spec은 **proxy 면허**를 명기한다: contract의 어느 조항이 이 objective를 proxy로 허가하는지.
- 모든 spec은 trial 예산을 generation 예산에서 인출한다. 예산 = 다중검정 계약이다.
- run 종료 시 kernel ledger + evaluator 캐시의 `trials.jsonl`(agent가 iteration 안에서 실행한 평가까지 잡는 정직한 분모 — crypto-new `af_eval.py` 패턴의 표준화)을 함께 봉인한다. `aim`은 이 봉인 없이 다음 spec을 만들지 않는다.
- **holdout 물리적 부재**를 설계 원칙으로 승격한다: 평가 데이터 표면은 contract에 선언하되, OS와 kernel은 holdout에 접근할 수 없다.
- 노이즈 입구 차단: kernel의 stage entry 결정론 게이트(objective 2회 측정 일치)가 nondeterministic objective를 거부한다. 본질적으로 noisy한 지표는 contract가 결정론 proxy(고정 seed, 동결 샘플, content-addressed 캐시)를 정의해야 하며, proxy-진실 간극의 수용 여부는 read 레이어의 diagnosis 파일로 남는 LLM 판단이다.

---

## 8. 리스크 해소 대장

| # | 리스크 | 해소 |
| --- | --- | --- |
| R1 | post-v0.5 자기비판 문서의 처방(동결)과 충돌 | 진단(증명 장치 비대)은 공유. §3.6 불변식을 §2.3 이행표대로 기계가 아니라 구조로 보존. 불변식 보존이 재작성의 정당화 조건이다 |
| R2 | v0.5 역사 증거 상실 | 새 repo(clean v1.0), 구 repo 동결 아카이브. 이관은 journal 부트스트랩 이벤트가 구 EventLog head digest를 인용하는 혈통 다리 1개. application이 alpha-factory 하나뿐인 지금이 유일하게 싼 시점 |
| R3 | 경화(hardening) 유실 | 기존 75 테스트 모듈에서 행위 불변식 채굴. 공격 테스트(symlink, truncated tail, digest 우회, replay 분기)를 새 스위트의 뼈대로 포팅. 신규 코드는 자기 공격 테스트와 함께만 착륙 |
| R4 | 상태기계 재발 | §2.2 규칙 A–D. 위반은 설계 버그 |
| R5 | noisy objective / 다중검정 | §7. 통계 소유권을 aim에 명시 배정, trials 분모 봉인 강제, holdout 물리 부재 |
| R6 | 유실 기능 | 아래 §9 |
| R7 | agent 자체가 outer loop 런타임 — 진단 생략, 순서 무시 | 생략해서 얻을 것이 없는 구조: 도구 fail-closed(§4), journal 변조는 chain이 증거화, skill이 세션 시작 verify 의무화 |

## 9. 유실 기능 처리

| 구세계 기능 | 처리 |
| --- | --- |
| mid-stage resume | 불필요로 수용 — kernel stage 재진입은 멱등(이미 target이면 agent 호출 0회), outer 단위는 run |
| PILOT_ONLY 격리 상태 | **git이 대체하며 더 강함** — pilot = worktree/branch + pilot contract의 spec. 채택은 pilot summary digest를 요구 |
| Context v3 staleness token | 원천 소멸(§2.3) — 매 iteration 결정론 조립 |
| autonomy crash-resume FSM | journal replay가 곧 resume(§5). FSM 0줄 |
| SQLite projection | 정본이 아니므로 삭제. 필요 시 journal에서 재생성하는 일회성 도구 |
| certification 기계 | integrity pin + 결정론 게이트로 환원 |
| workspace manager | git worktree + kernel revert로 환원 |
| adapter 8-op 프로토콜 | 축소 — kernel은 argv 스칼라/exit-code만 요구. describe/fingerprint = digest, materialize/cleanup = git. `af_eval.py` 패턴이 표준 브리지 |
| agent_install 관리 트리 | skill 폴더 복사로 환원 |
| 독립 리뷰어 증명 | 정직한 한계 유지 — 별도 세션/모델 라우트 저작 + 선언 기록(구세계도 선언이었음) |
| interpretation_requests 패턴 | **생존** — LLM 판단을 인용 가능한 신호로 바꾸는 seam으로서 steer projection에 유지 |
| diagnosis 의무 | **생존** — 집행 방식만 구조적으로 전환(aim의 거부 규칙) |
| note kinds + 검열 규칙 | **생존** — note 도구로 이식 |
| StudyContract / constitution 개념 | **생존** — contract.toml과 aim의 입력으로 |

---

## 10. 마이그레이션 개요

1. **kernel 단일 소스화.** gos 최신본(1,663줄: `non_increasing_number`, `tolerance`, `ratchet`, objective 결정론 게이트 포함)을 기준으로 vendoring 또는 패키지화. 1,674줄 계약 테스트 스위트 동반. crypto-new의 구본(1,577줄, 테스트 없음) 교체.
2. **새 repo 부트스트랩.** journal + aim + seal의 최소 수직 슬라이스.
3. **alpha-factory 1 run 재현.** 기존 leadlag spec을 새 파일 계약으로 번역해 outer loop 1 사이클 완주.
4. **구 repo 동결.** 부트스트랩 이벤트에 구 EventLog head digest 인용.
5. 이후 steer / jump / memory / note를 계기 단위로 추가. 각 계기는 독립 착륙 가능(§2.2 규칙 A 덕분).

## 11. 비범위

- 배포·릴리스·자본 배분·라이브 트레이딩 등 외부 행동 일체(스키마 자체가 없음).
- multi-agent / swarm — 별도 DEFER 유지.
- LLM judge의 promotion 관여 — post-v0.5 Gate 체계(`docs/evaluation-driven-research-os.md`)의 결론을 계승하며, 이 설계와 독립적으로 gate를 통과해야 한다.
- 기존 v0.5 historical receipts의 변경 — 동결 보존.
