# Research OS — 작업 기록 (status core)

> Paired with: `docs/research-os-pipeline.md` (방법론 레퍼런스)
> 절별 디테일은 `docs/research-os-status/` 하위 파일 참조.
> 이 문서는 `progress-guidance` 규율에 따라 v0.3~v0.5 개선의 진척과 증거를 추적한다.

---

## ▶ 0. 다음 세션 시작 지점

### 0.1 마지막 갱신

- 날짜: 2026-08-09
- 요약:
  - 사용자가 v0.3 Scientific State → v0.4 Program Memory → v0.5 Autonomous Single-Agent Loop 순서를 승인했다.
  - 구현 전 기준선은 제품 v0.2.0, Python 3.12에서 262 tests + 57 subtests PASS다.
  - Bootstrap critic과 Rule 9 사용자 회고가 PASS했고 checkpoint `e728df9`로 고정됐다.
  - M1-A는 exact evidence semantics·baseline VERIFY·certification lifecycle 사전 명세와 critic 단계다.

### 0.2 현재 운영 상태 (확인 명령 포함)

```bash
cd /Users/bbangjo/research-os
git status --short
uv run --python 3.12 --with pytest --no-project env PYTHONPATH=src pytest -q
rg -n '^version =|__version__' pyproject.toml src/research_os/__init__.py
```

- 기준선 명령 결과: `262 passed, 57 subtests passed in 55.31s`.
- 제품 버전: `0.2.0`.
- 사용자 소유·포함 승인된 기존 수정: `src/research_os/certification.py`, `tests/test_evaluator_certification_unit.py`.

### 0.3 가장 먼저 할 일 (의사결정 트리)

- [ ] **단일 최우선 행동:** M1-A 사전 critic을 생성·응답하고 pre-spec checkpoint를 commit한다.
- 그 다음:
  - pre-spec checkpoint가 성공하면 → M1-A 구현과 집중 검증을 시작한다.
  - critic이 범위/판정 공백을 지적하면 → 구현 전에 phase plan을 먼저 보강한다.

### 0.4 살아있는 산출물 (직전 세션 결과)

| 항목 | 위치 | 상태 | 근거 |
|---|---|---|---|
| v0.2 제품 코드 | `src/research_os/` | 동작 | 위 §0.2 pytest 명령 PASS |
| 기존 전체 테스트 | `tests/` | 동작 | 262 tests + 57 subtests PASS |
| 진행 상태 core | `docs/research-os-status.md` | active | bootstrap `e728df9`, M1-A phase plan |
| 방법론 pipeline core | `docs/research-os-pipeline.md` | active | bootstrap `e728df9` |

### 0.5 알려진 잔여 이슈

- 기존 certification patch는 frozen nested adapter fingerprint를 정규화하지만 `doctor`와 `evaluator-review-subject` CLI lifecycle 회귀가 아직 없다.
- `.venv`/기본 `uv run`이 Python 3.10을 선택할 수 있어 프로젝트 요구사항 Python ≥3.11을 만족하는 명시적 검증 명령이 필요하다.
- v0.2 managed agent skill을 이후 release로 안전하게 upgrade하는 known-release 경로가 없다.
- v0.5 성능 청구는 bootstrap 시점에는 사전 데이터 노출 commit이 없으므로 기본적으로 `EXPLORATORY`이며, 고정 benchmark 결과 후 별도 confirmatory validation이 필요하다.

### 0.6 컨텍스트 복원 순서 (이 문서를 처음 보는 세션)

1. 본 §0
2. §1 사용자 목표
3. §11 한 페이지 요약
4. `docs/research-os-pipeline.md` §8 종착지 시스템 모양
5. `docs/research-os-pipeline.md` §9 마일스톤 체크포인트 체인
6. §2.3 마일스톤 진척
7. §12 북극성 표
8. `docs/research-os-status/`의 가장 최근 phase 파일

### 0.7 동반 문서 (외부 참조)

- `docs/research-os-pipeline.md` — v0.3~v0.5 방법론·종착지·마일스톤 정의
- `/Users/bbangjo/Graph-Engineering-Athropic-Karpathy-Loop.pdf` — Graph Engineering 분석 자료
- `/Users/bbangjo/.codex/attachments/a250e684-1db8-4f52-8b89-627f199e73bf/pasted-text.txt` — Karpathy autoresearch 원문 메모
- `README.md`, `docs/architecture.md`, `docs/agent-usage.md` — 현재 제품 계약

---

## 1. 출발점 — 사용자 목표

### 1.1 현재 운용 상태

- 저장소: `/Users/bbangjo/research-os`, 제품 버전 `0.2.0`, commit `6f36a1b` 기반.
- 구현 크기: `src/research_os`와 `tests` Python 합계 26,822 LOC.
- 검증 기준선: Python 3.12에서 262 tests + 57 subtests PASS.
- 강점: append-only hash-chained event log, disposable projection, artifact CAS, evaluator certification, stale-context와 compatibility gate, fail-closed recovery, `authorized_action=null`.
- 핵심 갭: graph metadata는 `graph_action`과 자유문자열 `scientific_change` 중심이고, terminal 실패를 기계 판독 가능한 diagnosis/class/claim으로 축적해 다음 proposal에 재사용하는 상태가 없다.
- `crypto-new`, `manager`, `BinancePredictionStrategy`가 Research OS를 사용하지만 v0.5까지는 해당 프로젝트를 live migration하지 않고 read-only 호환성만 점검한다.

### 1.2 사용자 진단

> "Research OS는 현재 **실험 무결성·감사·잘못된 승격 방지 시스템**으로는 상당히 잘 작동합니다. 반면 **실패를 지식으로 바꾸고 다음 가설을 더 똑똑하게 생성하는 자율 연구 시스템**, 더 나아가 Graph Engineering이 말하는 연구 공동체에는 아직 미달합니다."

> "이 분석은 맞는 것 같다. 이걸 바탕으로 research-os 개선 방향 분석해보라"

근본 원인: 실행 증거 DAG는 강하지만, study inference와 program claim을 구조화·재사용하는 durable learning state가 없고 과학 규율의 일부가 shared skill 문서에만 존재한다.

### 1.3 외부 컨텍스트 자료 (의사결정 근거)

| 자료 | 위치 |
|---|---|
| Karpathy autoresearch 메모 | `/Users/bbangjo/.codex/attachments/a250e684-1db8-4f52-8b89-627f199e73bf/pasted-text.txt` |
| Graph Engineering 분석 | `/Users/bbangjo/Graph-Engineering-Athropic-Karpathy-Loop.pdf` |
| 현재 제품 아키텍처 | `README.md`, `docs/architecture.md`, `docs/design-provenance.md` |
| 현재 agent 규율 | `docs/agent-usage.md`, packaged `research-os` skill |

핵심 메시지:

- integrity kernel은 교체하지 않고 학습 상태와 자율 루프를 그 위에 쌓는다.
- 실행 DAG, study inference graph, program claim graph를 서로 다른 권위와 replay 경계로 분리한다.
- 다중 에이전트 수보다 durable diagnosis·claim·class state와 fixed-budget 학습 개선을 먼저 증명한다.
- provider-neutral·single-worker·no-deployment 권한 경계를 v0.5에서도 유지한다.

### 1.4 진짜 목표

> **Research OS를 실험 무결성 통제층에서, 실패를 구조화된 지식으로 축적하고 그 지식을 사용해 같은 예산에서 더 정확하고 덜 낭비적으로 다음 가설을 선택하는 provider-neutral 단일 연구자 운영체제로 발전시킨다.**

---

## 2. 의사결정 체인

### 2.1 `crypto-new`의 원래 목표와 Research OS 계보 분리 → **의도된 탐색으로 인정**

사용자가 새로운 전략 발견을 위해 의도적으로 분리했다고 명시했다. 본 개선은 프로젝트별 연구 목표를 다시 통일하지 않고 OS의 학습 능력만 강화한다.

### 2.2 v0.5의 자율성 범위 → **단일 에이전트·provider-neutral loop**

멀티에이전트 연구 공동체, distributed worker, graph/vector DB, embedded LLM SDK는 fixed-budget 단일 agent 개선이 입증된 이후로 미룬다.

### 2.3 마일스톤 진척 (checkpoint chain — Rule 8) ★

> 정적 정의는 `docs/research-os-pipeline.md` §9, 동적 진척만 이 절에서 추적한다.

#### 2.3.1 사용자 verbatim 합의 (Bootstrap step 6.5 인용)

> "위 방향대로 개선해서 v0.5 까지 개선을 진행하고 싶다"

> "추천안 승인 / 로컬 체크포인트 커밋 허용 / 기존 certification 패치 포함"

#### 2.3.2 현재 active checkpoint

- **Active M_i.j**: `M1-A`
- **이 M.j가 닫혀야 다음에 가능해지는 작업**: typed scientific state가 신뢰할 수 있는 delta·gate evidence를 소비할 수 있다.
- **M1 parent close까지 남은 sub**: `M1-A`, `M1-B`, `M1-C`, `M1-D`, `M1-E`.

#### 2.3.3 M 진척 표

| M_i.j | 정의 (요약) | exit conjunct progress | 상태 | closed-by phase | 근거 |
|---|---|---|---|---|---|
| M1-A | Decision/evidence correctness | 0/4 ✅ | active | — | pipeline §9.4 |
| M1-B | Study generation과 누적 budget | 0/4 ✅ | open | — | pipeline §9.4 |
| M1-C | Typed Proposal과 replication identity | 0/4 ✅ | open | — | pipeline §9.4 |
| M1-D | Diagnosis·ClassState·semantic frontier | 0/5 ✅ | open | — | pipeline §9.4 |
| M1-E | Context v3·legacy compatibility·v0.3 release | 0/5 ✅ | open | — | pipeline §9.4 |
| M2-A | ProgramManifest·ProgramLog | 0/4 ✅ | open | — | pipeline §9.4 |
| M2-B | Conditional Claim과 evidence 관계 | 0/5 ✅ | open | — | pipeline §9.4 |
| M2-C | Deterministic retrieval·Context integration | 0/5 ✅ | open | — | pipeline §9.4 |
| M2-D | Knowledge disposition·legacy import·v0.4 release | 0/5 ✅ | open | — | pipeline §9.4 |
| M3-A | Provider-neutral DecisionPacket | 0/4 ✅ | open | — | pipeline §9.4 |
| M3-B | Finite autonomous state machine | 0/6 ✅ | open | — | pipeline §9.4 |
| M3-C | Crash-resume·authority·budget stop | 0/5 ✅ | open | — | pipeline §9.4 |
| M3-D | unseen 36-episode benchmark·compatibility·v0.5 release | 0/8 ✅ | open | — | pipeline §9.4 |

#### 2.3.4 Phase ↔ M_i.j 매핑 (history)

| Phase § | 일자 | 영향 받은 M_i.j | conjunct | advance / close | 비고 |
|---|---|---|---|---|---|
| 00 | 2026-08-09 | M1~M3 정의 | bootstrap | advance | 사용자 마일스톤 승인; 구현 전 |

#### 2.3.5 Gate-bypass 기록

없음. M1 → M2 → M3 prerequisite를 순서대로 닫는다.

### 2.4 로컬 변경·커밋 정책 → **checkpoint commit 허용**

- 사용자는 로컬 checkpoint commit을 허용했으며 push/PR은 별도 승인 없이는 수행하지 않는다.
- 기존 certification patch는 M1-A 범위에 포함한다.
- 각 commit은 해당 phase에서 작성한 파일만 명시적으로 stage해 unrelated 변경을 포함하지 않는다.

---

## 3+. Phase 로그 인덱스

| § | 일자 / 단계 | 디테일 파일 | 한 줄 요약 |
|---|---|---|---|
| 00 | 2026-08-09 / Bootstrap | [`research-os-status/00-bootstrap-retro.md`](research-os-status/00-bootstrap-retro.md) | critic PASS + 사용자 회고로 목표·북극성·종착지·M chain 고정 |
| 01 | 2026-08-09 / M1-A | [`research-os-status/01-2026-08-09-m1-a-evidence-correctness.md`](research-os-status/01-2026-08-09-m1-a-evidence-correctness.md) | 구현 전 evidence correctness 판정·예상 결과 고정 |

---

## 11. 한 페이지 요약 (TL;DR)

- 현재 상태: v0.2.0, 기존 262 tests + 57 subtests PASS, v0.3~v0.5 learning-state surface는 미구현.
- 마지막 phase: Cycle 00 bootstrap closed; Cycle 01 M1-A pre-spec 진행 중.
- 다음 1행동: M1-A 사전 critic과 pre-spec checkpoint를 고정한다.
- 가장 큰 갭: terminal 실패가 evidence-bound diagnosis/class/claim으로 변환되어 다음 proposal을 제한·개선하지 않는다.

---

## 12. 북극성 (Target State) + 갭

### 12.1 북극성 출처

| 자료 | 핵심 메시지 |
|---|---|
| 사용자 §1.2·§1.4 | 실패를 다음 가설 생성에 쓰는 단일 자율 연구 OS |
| Graph Engineering PDF | 연구 산출물을 graph 관계와 공동체적 검증으로 축적; v0.5는 그 전제인 durable state까지 |
| Karpathy autoresearch 메모 | bounded loop와 scalar/evidence feedback의 자율 반복 |
| `docs/architecture.md` | provider-neutral, append-only, replayable, no-authority 경계 유지 |

### 12.2 북극성 — 지표 / 현재 / 갭 / 근거 / 시스템 영향 ★

| 지표 | 북극성 | 현재 (2026-08-09) | 갭 | 근거 | 시스템 영향 |
|---|---|---|---|---|---|
| NS1. 무결성·권한 하위호환 | 기존 262 tests와 모든 신규 suite 100% PASS ∧ versioned `tests/fixtures/protocol_attacks/v1/manifest.json`의 전체 위반 행 차단률 100% ∧ `authorized_action` non-null 0건 ∧ v1 event replay 100% | 기존 262 tests + 57 subtests PASS; versioned attack manifest와 신규 schema/loop attack 행 0개 | manifest·digest·공격 행·replay evidence 필요 | §0.2 pytest 명령; pipeline §7.2 attack manifest 규칙; `README.md` authority contract | 학습 기능이 기존 fail-closed·no-deployment 보장을 약화하지 않는다 |
| NS2. 기계 강제 scientific state | generation/contract·누적 budget·diagnosis gate·class closure·semantic frontier·legacy isolation 6/6 동작 ∧ `tests/fixtures/scientific_state/v1/manifest.json`의 모든 입력 상태/transition/거절 code/closure threshold 판정 일치 | 0/6; 일부는 shared skill 자유문서 규율; transition oracle 없음 | 6 capability + versioned transition oracle | pipeline §2.2의 manifest schema와 향후 fixture digest; `agent.py`, `graph_policy.py` | 실패 후 같은 class를 반복하지 않고 허용된 다음 행동만 실행한다 |
| NS3. Durable learning 객체 | typed Proposal·Diagnosis·ClassState·Claim 4/4가 exact event/artifact evidence와 digest로 replay | 0/4; 범용 Finding만 존재 | 4 typed objects | `src/research_os/memory/findings.py`, `src/research_os/kernel/projection.py` | 실패가 검색 가능한 지식과 class 상태로 남는다 |
| NS4. Program memory 정확도 | versioned `tests/fixtures/program_memory/retrieval-v1.json`의 exact ordered oracle에서 relevant claim recall 100% ∧ contradiction recall 100% ∧ superseded exclusion 100% ∧ shuffled/irrelevant contamination 0% | 0/4; program log/retrieval/oracle 없음 | 4 retrieval criteria + oracle manifest | pipeline §5.2의 분모·empty/tie/scope 규칙과 향후 fixture digest | 다음 proposal이 관련 지식만 근거로 사용하고 오염된 memory를 배제한다 |
| NS5. 단일 자율 루프 완결성 | context→proposal→preflight→run→diagnosis→synthesis→next/stop 7 transition 모두 canonical state로 재개 가능 ∧ closed-class registration 0건 | 0/7; 사람이 외부 agent 대화를 수동 연결 | 7 transitions + resume | `docs/agent-usage.md`; 신규 loop integration suite | 유한 예산 안에서 중단·재개 가능한 provider-neutral 연구 episode를 수행한다 |
| NS6. Fixed-budget 학습 효과 | M3 code freeze 뒤 precommitted generator와 새 256-bit nonce로 만든 unseen acceptance 36 episodes에서 protocol block 100% ∧ evidence-bound conclusion 100% ∧ closed-class retry 0 ∧ next-hypothesis choice accuracy ≥ `min(90%, v0.2+20%p)` ∧ correct terminal decision ≥ `min(90%, v0.2+20%p)` ∧ positive-waste aggregate ≤ v0.2의 70% | comparator·generator·unseen suite 미구현; 측정 전 | oracle/generator/one-shot receipt 구축 + sealed v0.2/v0.5 paired 측정 | pipeline §7의 choice oracle·freeze/nonce/receipt 계약과 향후 `docs/benchmark.md` | terminal 정답뿐 아니라 각 비종결 상태에서 더 나은 다음 class/action을 선택해 동일 예산의 판단 정확도·효율을 높였는지 직접 판별한다 |
| NS7. 기존 프로젝트 read-only 호환성 | `crypto-new`, `manager`, `BinancePredictionStrategy` 각각 (기존 complete event bytes/hash/derived v1 state 무변환 replay 3/3) ∧ (typed schema가 없는 legacy free text 100% `legacy_unstructured`, 자동 typed inference 0건) ∧ (외부 writer/file 변경 0건) | v0.2 상태 감사만 존재; v0.3~v0.5 replay/import 판정 0/3 | replay 3건 + opaque classification 3건 + write audit | 각 프로젝트 `.research-os` read-only snapshot의 before/after hash, replay report, import report | 기존 증거는 실제로 보존하면서 의미가 불명확한 기록만 명시적으로 격리한다 |

> NS6 choice 판정: 모든 non-terminal decision point가 exact 허용/최적 `(hypothesis_class, action)` oracle set을 가지며, 선택이 set 밖이거나 closed/duplicate class를 고르거나 필요한 결정을 건너뛰면 오류다. 분모는 양 arm의 모든 oracle decision point다.
>
> NS6 unseen 판정: generator schema·world family·oracle rule·metric은 구현 전에 commit하고, M3 code freeze 후 새 nonce로 36개 body를 생성한다. receipt는 code commit, generator digest, nonce commitment, suite digest, 두 arm 결과를 묶는다. 결과 노출 뒤 code/policy 변경은 그 receipt를 무효화하며 새 nonce 결과는 다시 `EXPLORATORY`로 취급한다.
>
> NS6 waste 예외 규칙: v0.2 median waste가 0이면 v0.5도 0이어야 하며, 감소율은 v0.2 waste가 양수인 paired episode들의 aggregate rate로 판정한다.

### 12.3 남은 작업 (우선순위)

| # | 작업 | 추정 LOC | 어떤 §북극성 행을 움직이나 | 시스템 영향 (예상) |
|---|---|---|---|---|
| 1 | M1-A evidence correctness + certification patch 완결 | 250~500 | NS1, NS2 | 진단이 소비할 구조화 delta/gate evidence 생성 |
| 2 | M1-B~E Scientific State | 1,500~3,000 | NS1, NS2, NS3, NS5, NS7 | 과학 상태를 문서가 아닌 kernel이 강제 |
| 3 | M2 Program Memory | 1,200~2,500 | NS1, NS3, NS4, NS7 | 실패·조건부 claim을 다음 연구에 재사용 |
| 4 | M3 Autonomous Loop | 1,000~2,200 | NS1, NS5, NS6, NS7 | 단일 agent가 유한 연구 episode를 자동 완결 |

### 12.4 비관 재채점 (latest) ★

| 단계 | 이전 | 현재 (비관) | 사유 | 반례/근거 |
|---|---|---|---|---|
| Integrity kernel | 평가상 우수 | ○ | tokenless legacy path와 unstructured gate가 새 scientific state 보장을 우회할 수 있음 | README의 tokenless compatibility 경계 |
| Scientific State | 문서상 일부 존재 | ✗ | diagnosis/class closure/frontier가 canonical machine state가 아님 | NS2 = 0/6 |
| Program Memory | Finding 존재 | ✗ | project-bound free-form finding은 conditional claim graph가 아님 | NS3 = 0/4, NS4 = 0/4 |
| Autonomous Loop | agent workflow 존재 | ✗ | 외부 대화가 수동으로 각 단계를 이어주며 resume 가능한 loop state가 없음 | NS5 = 0/7 |
| 학습 효과 | 미측정 | ✗ | v0.2 comparator와 pre-fixed benchmark가 없음 | NS6 측정 전 |

---

## 13. 산출 LOC 요약

| Phase | 누적 LOC | 비고 | 검증 산출물 |
|---|---|---|---|
| 00 Bootstrap | 911 doc LOC | 코드 변경 0; status 266 + pipeline 490 + critic 51 + retro 104 lines | pytest 기준선, bootstrap critic PASS, 사용자 retro 승인, commit `e728df9` |
| 01 M1-A | 구현 전 산정 대기 | phase plan/critic 사전 고정 단계 | E1~E9 exact expected outcomes; 실측 전 |

---

## 14. pipeline §매핑 / §종착지 동기화 체크

마지막 동기화 일자: 2026-08-09

- [x] pipeline §10 매핑 표 초기 평가 작성
- [x] status §북극성과 pipeline §8·§10 일관성 확인
- [x] 외부 출처 양 doc 동기화
- [x] 신규 stage 1~7 정의
- [x] 모든 §북극성 행에 `근거` + `시스템 영향` 작성
- [x] pipeline §8.5에 Cycle 00 추가
- [x] pipeline §8.4 비전 vs 현재 초기 상태 작성
- [x] 축소 비전 없음; 의도적 제외는 사용자 승인 범위와 일치
- [x] Bootstrap critic PASS (`docs/research-os-status/00-bootstrap.critic.md`)
- [x] Rule 9 사용자 retrospective 완료 (`docs/research-os-status/00-bootstrap-retro.md`)
