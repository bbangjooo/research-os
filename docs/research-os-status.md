# Research OS — 작업 기록 (status core)

> Paired with: `docs/research-os-pipeline.md` (방법론 레퍼런스)
> 절별 디테일은 `docs/research-os-status/` 하위 파일 참조.
> 이 문서는 `progress-guidance` 규율에 따라 v0.3~v0.5 개선의 진척과 증거를 추적한다.

---

## ▶ 0. 다음 세션 시작 지점

### 0.1 마지막 갱신

- 날짜: 2026-08-11
- 요약:
  - 사용자가 v0.3 Scientific State → v0.4 Program Memory → v0.5 Autonomous Single-Agent Loop 순서를 승인했다.
  - 구현 전 기준선은 제품 v0.2.0, Python 3.12에서 262 tests + 57 subtests PASS다.
  - 당시 dirty-working-tree 기준선은 tag `research-os-m1a-working-tree-baseline` / commit `50c4957`로 복구·보존되어 별도 checkout에서 `262/57`이 재현된다.
  - Bootstrap critic과 Rule 9 사용자 회고가 PASS했고 checkpoint `e728df9`로 고정됐다.
  - M1-A의 typed evidence semantics·baseline VERIFY 대칭·certification lifecycle이 checkpoint `ed76067`에 구현됐다.
  - M1-A close 당시 전체 회귀는 `290 passed, 67 subtests`; 두 독립 구현 재검토, progress critic, 7-pass progress auditor가 PASS했다.
  - M1-B의 canonical `StudyContract`·generation replay·누적 reservation ledger·locked budget gate가 implementation checkpoint `df2c900`에 구현됐다.
  - M1-B executable manifest는 `29/29` exact, focused suite는 `81 passed, 37 subtests`, 전체 회귀는 `371 passed, 104 subtests`다. 네 exit conjunct, progress critic, 독립 7-pass auditor가 모두 PASS해 M1-B를 닫고 M1-C를 활성화했다.
  - M1-C의 StudyContract v2·typed Proposal·scope-bound baseline/identity·frozen-candidate replication이 implementation checkpoint `a783a88`에 구현됐다.
  - Corrected exploratory manifest `20/20`, transition `53/53`, four replay paths `72/72`, 전체 `442 passed, 111 subtests`와 progress critic Q1~Q8 `DIRECT`/PASS를 확인했다. Test-only checkpoints `6bc3905`, `6a35790`, `2e14096`이 cold projection race와 actual v1 service/CLI/M1-B parity를 보강했다.
  - 독립 7-pass auditor가 full manifest `27 passed`, collection 442, focused trust/race 5, ruff/ty/diff와 chronology·북극성·M-chain·limitation을 PASS해 M1-C를 닫고 M1-D를 활성화했다.
  - M1-D는 exact evidence-bound Diagnosis, pending gate, derived ClassState/class closure와 semantic/retry frontier를 구현했다. 두 차례 oracle `RESULT-INVALID`를 철회하고 canonical equality·anti-vacuity correction을 거친 final transition `92551a…c54`, manifest raw/public `10e037…1718`/`c34efc…f78`를 고정했다.
  - Final corrected evidence는 transition `26/23/54/37/7`, negative path `460/460`, M1-C exact `20/20`, M1-D bounded manifest `56 PASS`, direct `67 PASS`, single regression floor tests `>=442`/subtests `>=111`와 ruff/ty/diff PASS다. Five product conjuncts 5/5, critic, independent 7-pass progress audit가 모두 PASS해 M1-D를 `CLOSE`했다.
  - M1-D audited integration은 local checkpoint `f570f92`로 고정했다. M1-E는 Context v3 + Diagnosis template + disposable example vertical slice를 §05에 pre-spec했다.
  - M1-E vertical slice는 opt-in Context v3, fail-closed Diagnosis template, temp-project demo를 구현했다. Vertical `4 PASS`, final compatibility `127+23`, ruff/ty/diff가 PASS했다. Pre-spec `38446f1` 뒤 first result checkpoint `7fcfd10`으로 CONFIRMATORY chronology를 고정했다.

### 0.2 현재 운영 상태 (확인 명령 포함)

```bash
cd /Users/bbangjo/research-os
git status --short
uv run --python 3.12 --with pytest --no-project env PYTHONPATH=src pytest -q
rg -n '^version =|__version__' pyproject.toml src/research_os/__init__.py
```

- M1-D corrected composite result: collection 589; full floor가 M1-D manifest를 제외한 531-test 범위를 PASS하고 기존 floor `442+111` 이상을 충족했다. M1-D manifest는 bounded `56 PASS` + compatibility exact `20/20` + single floor PASS로 나눠 증명했다.
- M1-D direct state/service/CLI `67 PASS`; transition literal `26/23/54/37/7`; negative path `460/460`; correction fixed point PASS.
- 제품 버전: `0.2.0`.
- 승인된 기존 certification 수정은 M1-A checkpoint `ed76067`에 포함됐다.
- canonical StudyContract/generation/budget은 M1-B `df2c900`, typed Proposal/scope/replication은 M1-C `a783a88`과 후속 test-only checkpoints에 포함됐다. M1-D Diagnosis/ClassState/frontier는 `f570f92`에 포함됐다.

### 0.3 가장 먼저 할 일 (의사결정 트리)

- [ ] **단일 최우선 행동:** §06 frozen acceptance에 따라 M1-E의 legacy isolation,
  managed 0.2→0.3 upgrade/rollback, version/full release conjunct를 닫는다.

### 0.4 살아있는 산출물 (직전 세션 결과)

| 항목 | 위치 | 상태 | 근거 |
|---|---|---|---|
| v0.2 제품 + M1-A/B/C + M1-D | `src/research_os/` | M1-D closed/checkpointed | M1-D exact Diagnosis/ClassState/frontier; `f570f92`; independent audit PASS |
| 기존+M1-D 테스트 | `tests/` | 동작 | collection 589; composite floor/bounded rows PASS; transition `26/23/54/37/7`; negative `460/460` |
| 진행 상태 core | `docs/research-os-status.md` | active | M1-D 5/5 closed/audited; M1-E active |
| M1-E vertical slice | `docs/research-os-status/05-2026-08-11-m1-e-usable-context.md` | complete; independent audit PASS | opt-in Context v3 + Diagnosis template + disposable example PASS |
| M1-E release close pre-spec | `docs/research-os-status/06-2026-08-11-m1-e-release-close.md` | frozen; implementation pending | five-conjunct acceptance + release manifest + critic Q1~Q8 |
| 방법론 pipeline core | `docs/research-os-pipeline.md` | active | Cycle 04 closed; Cycle 05 active |

### 0.5 알려진 잔여 이슈

- candidate-only `VERIFY`를 구현한 외부 adapter는 baseline VERIFY 추가에 change-control이 필요하며, 실제 호환성은 v0.5 이후 pilot 전 별도 판정한다.
- `.venv`/기본 `uv run`이 Python 3.10을 선택할 수 있어 프로젝트 요구사항 Python ≥3.11을 만족하는 명시적 검증 명령이 필요하다.
- v0.2 managed agent skill을 이후 release로 안전하게 upgrade하는 known-release 경로가 없다.
- v0.5 성능 청구는 bootstrap 시점에는 사전 데이터 노출 commit이 없으므로 기본적으로 `EXPLORATORY`이며, 고정 benchmark 결과 후 별도 confirmatory validation이 필요하다.
- M1-B budget은 **generation별 non-refundable reservation**이다. 실제 elapsed/cost 사용량 telemetry나 settlement가 아니며 study lifetime cap도 아니다.
- 새 evaluation-sealed successor generation이 새 budget을 열 수 있고 반복 증액 자체를 막는 lifetime governance는 아직 없다.
- context v2는 active generation과 reservation ledger를 agent packet에 직접 노출하지 않는다. 이 UX/authority binding은 M1-E context v3 범위다.
- M1-C scope binding은 scope identity와 adapter request delivery를 증명하지만 adapter가 manifest를 실제 dataset 선택에 올바르게 소비했는지, dataset 독립성이나 통계적 재현 성공은 증명하지 않는다.
- M1-C의 exact 21-key registration은 tokenless E7 shape다. Context-token path는 기존 token/snapshot sibling을 추가하면서 typed Proposal four-bundle 완전성을 유지한다.

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
- 구현 크기: `src/research_os`와 `tests` Python 합계 40,954 LOC (M1-C latest reviewed checkpoint `2e14096`).
- 검증 기준선: 보존 tag `research-os-m1a-working-tree-baseline`에서 Python 3.12 `262 tests + 57 subtests` PASS.
- 강점: append-only hash-chained event log, disposable projection, artifact CAS, evaluator certification, stale-context와 compatibility gate, fail-closed recovery, `authorized_action=null`, canonical StudyContract/generation/budget과 typed Proposal/scope/replication identity.
- 핵심 갭: Proposal은 canonical해졌지만 terminal 실패를 기계 판독 가능한 Diagnosis/ClassState/Claim으로 축적해 다음 proposal class/frontier를 제한·개선하는 상태는 아직 없다.
- `crypto-new`, `manager`, `BinancePredictionStrategy`가 Research OS를 사용하지만 v0.5까지는 해당 프로젝트를 live migration하지 않고 read-only 호환성만 점검한다. 실제 live pilot·migration은 v0.5 이후다.

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
- 다중 에이전트 수보다 durable diagnosis·claim·class state와 fixed-budget 학습 개선을 먼저 증명한다. **제품 multi-agent는 NS6 통과 이후로 명시적으로 유예한다.**
- provider-neutral·single-worker·no-deployment 권한 경계를 v0.5에서도 유지한다.

### 1.4 진짜 목표

> **Research OS를 실험 무결성 통제층에서, 실패를 구조화된 지식으로 축적하고 그 지식을 사용해 같은 예산에서 더 정확하고 덜 낭비적으로 다음 가설을 선택하는 provider-neutral 단일 연구자 운영체제로 발전시킨다.**

---

## 2. 의사결정 체인

### 2.1 `crypto-new`의 원래 목표와 Research OS 계보 분리 → **의도된 탐색으로 인정**

사용자가 새로운 전략 발견을 위해 의도적으로 분리했다고 명시했다. 본 개선은 프로젝트별 연구 목표를 다시 통일하지 않고 OS의 학습 능력만 강화한다.

### 2.2 v0.5의 자율성 범위 → **단일 에이전트·provider-neutral loop**

멀티에이전트 연구 공동체와 **제품 multi-agent**, distributed worker, graph/vector DB, embedded LLM SDK는 fixed-budget 단일 agent 개선의 NS6 gate가 통과된 이후로 미룬다. 실제 프로젝트 live pilot·migration도 v0.5 이후다.

> "회고 승인 / unseen synthetic benchmark를 v0.5 release gate로 인정 / 실제 프로젝트 live pilot·migration은 v0.5 이후 / multi-agent는 NS6 통과 이후"

### 2.3 마일스톤 진척 (checkpoint chain — Rule 8) ★

> 정적 정의는 `docs/research-os-pipeline.md` §9, 동적 진척만 이 절에서 추적한다.

#### 2.3.1 사용자 verbatim 합의 (Bootstrap step 6.5 인용)

> "위 방향대로 개선해서 v0.5 까지 개선을 진행하고 싶다"

> "추천안 승인 / 로컬 체크포인트 커밋 허용 / 기존 certification 패치 포함"

> "회고 승인 / unseen synthetic benchmark를 v0.5 release gate로 인정 / 실제 프로젝트 live pilot·migration은 v0.5 이후 / multi-agent는 NS6 통과 이후"

#### 2.3.2 현재 active checkpoint

- **Active M_i.j**: `M1-E`
- **직전 close가 가능하게 한 작업**: M1-D가 terminal evidence-bound Diagnosis, derived ClassState와 semantic/retry frontier를 canonical state로 만들고 five conjunct 5/5를 충족했다.
- **현재 close audit**: M1-D progress critic과 independent 7-pass progress audit PASS. M1-E vertical slice critic과 independent 7-pass progress audit PASS.
- **이 M.j가 닫혀야 다음에 가능해지는 작업**: ProgramManifest가 stable M1 identity를 bind하고 M2 ProgramLog가 Diagnosis/ClassState origin을 exact 검증할 수 있다.
- **M1 parent close까지 남은 sub**: `M1-E`.

#### 2.3.3 M 진척 표

| M_i.j | 정의 (요약) | exit conjunct progress | 상태 | closed-by phase | 근거 |
|---|---|---|---|---|---|
| M1-A | Decision/evidence correctness | 4/4 ✅ | closed | 01 | phase §01.3~§01.6.4 |
| M1-B | Study generation과 누적 budget | 4/4 ✅ | closed | 02 | phase §02.4~§02.6.4; manifest `29/29`; checkpoint `df2c900`; critic + auditor PASS |
| M1-C | Typed Proposal과 replication identity | 4/4 ✅ | closed | 03 | phase §03.4~§03.6.4; manifest `20/20`; critic + auditor PASS |
| M1-D | Diagnosis·ClassState·semantic frontier | 5/5 ✅ | closed | 04 | phase §04.5~§04.6.4; transition `26/23/54/37/7`; negative `460/460`; critic + auditor PASS |
| M1-E | Context v3·legacy compatibility·v0.3 release | 1/5 ✅ | active | — | phase §05 Context v3/template/demo와 independent audit PASS |
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
| 01 | 2026-08-10 | M1-A | 4/4 | close | E1~E9 exact; `290+67`; critic + auditor PASS |
| 02 | 2026-08-10 | M1-B | 4/4 | close | manifest `29/29`; focused `81+37`; full `371+104`; checkpoint `df2c900`; critic + auditor PASS |
| 03 | 2026-08-10 | M1-C | 4/4 | close | manifest `20/20`; transition/direct `53/72`; full `442+111`; critic + auditor PASS |
| 04 | 2026-08-10~11 | M1-D | 5/5 | close | final corrected manifest/transition, direct `67`, bounded `56`, compatibility `20/20`, single floor PASS; auditor PASS |
| 05 | 2026-08-11 | M1-E | 1/5 | advance | opt-in v3 + template + disposable E2E PASS; M1-E close는 아님 |

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
| 01 | 2026-08-09~10 / M1-A | [`research-os-status/01-2026-08-09-m1-a-evidence-correctness.md`](research-os-status/01-2026-08-09-m1-a-evidence-correctness.md) | typed gate·baseline VERIFY·certification lifecycle 4/4 close |
| 02 | 2026-08-10 / M1-B | [`research-os-status/02-2026-08-10-m1-b-study-generation-budget.md`](research-os-status/02-2026-08-10-m1-b-study-generation-budget.md) | StudyContract·generation·atomic reservation 4/4; critic + independent auditor PASS |
| 03 | 2026-08-10 / M1-C | [`research-os-status/03-2026-08-10-m1-c-typed-proposal-replication.md`](research-os-status/03-2026-08-10-m1-c-typed-proposal-replication.md) | typed Proposal·scope-bound identity·replication 4/4; critic + independent auditor PASS |
| 04 | 2026-08-10~11 / M1-D | [`research-os-status/04-2026-08-10-m1-d-diagnosis-class-frontier.md`](research-os-status/04-2026-08-10-m1-d-diagnosis-class-frontier.md) | Diagnosis·ClassState·frontier 5/5 closed; corrected oracle + critic + auditor PASS |
| 05 | 2026-08-11 / M1-E vertical slice | [`research-os-status/05-2026-08-11-m1-e-usable-context.md`](research-os-status/05-2026-08-11-m1-e-usable-context.md) | Context v3 + Diagnosis template + disposable E2E; independent audit PASS |

---

## 11. 한 페이지 요약 (TL;DR)

- 현재 상태: 제품 version은 아직 v0.2.0; M1-D는 `f570f92`에 closed/checkpointed됐고 M1-E opt-in Context v3/template/demo가 focused PASS했다. M1-E는 1/5 active다.
- 마지막 측정: transition `26/23/54/37/7`, negative `460/460`, direct `67`, bounded manifest `56`, compatibility `20/20`, single regression floor tests `>=442`/subtests `>=111`, ruff/ty/diff PASS. Historical invalid oracle 결과는 제외했다.
- 다음 1행동: M1-E tokenless legacy isolation → managed upgrade/rollback → v0.3 release 남은 conjunct.
- 가장 큰 갭: opt-in v3/template/example은 usable하지만 context v2가 아직 default이고 legacy isolation·managed upgrade·v0.3 release가 남았다. Claim/program memory와 autonomous loop는 M2/M3에 남아 있다.

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

| 지표 | 북극성 | 현재 (2026-08-11) | 갭 | 근거 | 시스템 영향 |
|---|---|---|---|---|---|
| NS1. 무결성·권한 하위호환 | 기존 262 tests와 모든 신규 suite 100% PASS ∧ versioned `tests/fixtures/protocol_attacks/v1/manifest.json`의 전체 위반 행 차단률 100% ∧ `authorized_action` non-null 0건 ∧ v1 event replay 100% | M1-D collection 589 composite evidence; M1-E focused `127+23`; v3/template cold writer diff 0, authority null; M1-C exact `20/20` | 전체 protocol-attack manifest·release replay evidence 필요 | §0.2; phases §04.5, §05.6~.7; first result `7fcfd10`; `README.md` authority contract | Context/template가 기존 fail-closed·no-deployment 보장을 약화하지 않는다 |
| NS2. 기계 강제 scientific state | generation/contract·누적 budget·diagnosis gate·class closure·semantic frontier·legacy isolation 6/6 동작 ∧ `tests/fixtures/scientific_state/v1/manifest.json`의 모든 입력 상태/transition/거절 code/closure threshold 판정 일치 | **5/6 (`2→5/6`)**; 기존 5 capability + opt-in v3/template에서 pending→diagnose→state refresh usable; denominator advance는 없음 | complete legacy isolation 1 capability | phases §02, §04, §05; M1-D `26/23/54/37/7`, negative `460/460`; M1-E vertical `4/4` | kernel state가 agent에게 exact 노출되고 template이 수작업 evidence 오류를 차단한다 |
| NS3. Durable learning 객체 | typed Proposal·Diagnosis·ClassState·Claim 4/4가 exact event/artifact evidence와 digest로 replay | **3/4 (`1→3/4`)**; Proposal/Diagnosis/ClassState exact replay + Context v3 direct exposure; denominator advance는 없음 | Claim 1 typed object | phases §03~§05; `science/{proposals,diagnoses,state}.py`; v3 exact state equality | durable object가 대화 요약이 아닌 authoring/context의 canonical 입력이 된다 |
| NS4. Program memory 정확도 | versioned `tests/fixtures/program_memory/retrieval-v1.json`의 exact ordered oracle에서 relevant claim recall 100% ∧ contradiction recall 100% ∧ superseded exclusion 100% ∧ shuffled/irrelevant contamination 0% | 0/4; program log/retrieval/oracle 없음 | 4 retrieval criteria + oracle manifest | pipeline §5.2의 분모·empty/tie/scope 규칙과 향후 fixture digest | 다음 proposal이 관련 지식만 근거로 사용하고 오염된 memory를 배제한다 |
| NS5. 단일 자율 루프 완결성 | context→proposal→preflight→run→diagnosis→synthesis→next/stop 7 transition 모두 canonical state로 재개 가능 ∧ closed-class registration 0건 | 0/7; context→template→diagnose→refresh 수동 vertical slice는 usable하지만 canonical FSM/resume가 아님 | 7 transitions + resume | phase §05 demo; `docs/agent-usage.md`; vertical `4/4` | agent 수작업은 줄었지만 자율 완결성 분모를 조기 증가시키지 않는다 |
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
| 1 | M1-E Context v3·legacy·v0.3 release | 500~1,200 | NS1, NS2, NS3, NS5, NS7 | M1-D state를 agent가 실제 작성·소비하고 legacy를 격리 |
| 2 | M2 Program Memory | 1,200~2,500 | NS1, NS3, NS4, NS7 | 실패·조건부 claim을 다음 연구에 재사용 |
| 3 | M3 Autonomous Loop | 1,000~2,200 | NS1, NS5, NS6, NS7 | 단일 agent가 유한 연구 episode를 자동 완결 |

### 12.4 비관 재채점 (latest) ★

| 단계 | 이전 | 현재 (비관) | 사유 | 반례/근거 |
|---|---|---|---|---|
| Integrity kernel | 평가상 우수 | ○ | **새 stricter reviewer assumption**: product뿐 아니라 observer/fixture도 adversarial audit 대상이다. 이 기준에서 두 초기 green은 무효였고 final composite는 PASS했지만 단일 589-run evidence와 전체 release manifest는 없음 | phases §01~§04; anti-vacuity FAIL→repair→PASS; collection 589 composite PASS; authority non-null 0 |
| Evidence semantics | arbitrary constraint 중심 | ○ | directional delta·typed slack·verify symmetry 구현; 외부 metric 의미는 아직 contract 밖 | phase §01 E1~E9 |
| Scientific State | 문서상 일부 존재 | ○ | Diagnosis/ClassState/frontier까지 executable이지만 result는 post-implementation correction 때문에 EXPLORATORY이고 complete legacy isolation·actual telemetry·lifetime cap은 없음 | NS2 = 5/6; NS3 = 3/4; transition `26/23/54/37/7`; negative `460/460` |
| Relevant Context | recent v2 packet | △ | **새 stricter reviewer assumption**: context는 cold project-writer diff 0, exact fail-closed authoring, default/upgrade/release까지 있어야 ○다. opt-in v3/template/demo는 PASS했지만 뒤 세 조건과 Claim/retrieval reason이 없어 △로 제한한다 | phase §05; M1-E 1/5; `127+23`; checkpoint `7fcfd10` |
| Program Memory | Finding 존재 | ✗ | Diagnosis/ClassState는 생겼지만 project-bound free-form Finding은 conditional Claim graph가 아님 | NS3 = 3/4, NS4 = 0/4 |
| Autonomous Loop | agent workflow 존재 | ✗ | 외부 대화가 수동으로 각 단계를 이어주며 resume 가능한 loop state가 없음 | NS5 = 0/7 |
| 학습 효과 | 미측정 | ✗ | collection 589 composite regression은 PASS했지만 v0.2 comparator와 pre-fixed unseen learning benchmark가 없음 | NS6 측정 전 |

---

## 13. 산출 LOC 요약

| Phase | 누적 LOC | 비고 | 검증 산출물 |
|---|---|---|---|
| 00 Bootstrap | 911 doc LOC | 코드 변경 0; status 266 + pipeline 490 + critic 51 + retro 104 lines | pytest 기준선, bootstrap critic PASS, 사용자 retro 승인, commit `e728df9` |
| 01 M1-A | implementation `+2429/-64` + phase close docs | 18 implementation files; Python 총 LOC `29,037` | baseline `262+57`, focused `65+16`, full `290+67`, critic + auditor PASS |
| 02 M1-B | implementation `+6002/-29` | 27 files; Python 총 LOC `34,005` | checkpoint `df2c900`; manifest `29/29`; focused `81+37`; full `371+104`; critic + auditor PASS |
| 03 M1-C | implementation `+7068/-233` + test evidence follow-ups | 21 implementation files; Python 총 LOC `40,954` | checkpoints `a783a88`~`2e14096`; manifest `20/20`; transition/direct `53/72`; full `442+111`; critic + auditor PASS |
| 04 M1-D | cycle base `a5f232d` 대비 tracked `+126,150/-331` + untracked support `9,955` lines (`git diff --numstat a5f232d`; untracked `wc -l`) | product core보다 frozen JSON fixtures/observer/correction harness가 압도적으로 커진 과잉설계 비용을 명시; `state.py` 3,171 lines, oracle 2,724, rebuild script 2,256 | final transition `92551a…c54`; `26/23/54/37/7`; negative `460/460`; direct `67`; bounded `56`; compatibility `20/20`; floor PASS; auditor PASS |
| 05 M1-E vertical | pre-spec `38446f1` → product `7fcfd10`: source `+365/-8`, commit 11 files `+686/-8` | 1,200-line cap 이하; 신규 manifest/graph reducer 없음; temp replay O(n) limitation 명시 | vertical `4`; final focused/compatibility `127+23`; demo/ruff/ty/diff와 independent audit PASS |

---

## 14. pipeline §매핑 / §종착지 동기화 체크

마지막 동기화 일자: 2026-08-11

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
- [x] Cycle 01 M1-A에서 status §12와 pipeline §8.4·§8.5·§10 동기화
- [x] M chain 의미 변경 없음; 추가 Rule 9 retrospective 불필요
- [x] Cycle 01 progress critic + independent 7-pass auditor 최종 PASS
- [x] Cycle 02 M1-B current state·NS2 `0→2/6`·§8.4·§8.5·§10 동기화
- [x] Cycle 02에서도 M chain 정의/의미 변경 없음; M1-B 4/4 close와 M1-C active만 동적 갱신
- [x] Cycle 02 progress critic 최종 verdict — **PASS**
- [x] Cycle 02 independent 7-pass auditor 최종 verdict — **PASS** (`research-os-status/02-m1-b-study-generation-budget.audit.md`)
- [x] Cycle 03 M1-C current state·NS3 `0→1/4`·pipeline Stage 3 `✗→△` 동기화
- [x] Cycle 03에서도 M chain 정의/의미 변경 없음; M1-C 4/4 close와 M1-D active만 동적 갱신
- [x] Cycle 03 progress critic Q1~Q8 `DIRECT`, final verdict — **PASS**
- [x] Cycle 03 independent 7-pass auditor final verdict — **PASS** (`research-os-status/03-m1-c-typed-proposal-replication.audit.md`)
- [x] Cycle 04 status §12와 pipeline §8.4·§8.5·§10을 M1-D close candidate로 동기화
- [x] Cycle 04에서도 M chain 정의/의미 변경 없음; Rule 9 retrospective 재실행 불필요
- [x] Cycle 04 progress critic Q1~Q8 `DIRECT`, simulated verify verdict — **PASS**
- [x] Cycle 04 independent 7-pass auditor final verdict — **PASS** (`research-os-status/04-m1-d-diagnosis-class-frontier.audit.md`)
- [x] Cycle 05 M1-E vertical slice pre-spec/critic + implementation verify — **PASS**
- [x] Cycle 05 independent 7-pass auditor final verdict — **PASS** (`research-os-status/05-m1-e-usable-context.audit.md`)
