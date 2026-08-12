# Research OS — 작업 기록 (status core)

> Paired with: `docs/research-os-pipeline.md` (방법론 레퍼런스)
> 절별 디테일은 `docs/research-os-status/` 하위 파일 참조.
> 이 문서는 `progress-guidance` 규율에 따라 v0.3~v0.5 개선의 진척과 증거를 추적한다.

---

## ▶ 0. 다음 세션 시작 지점

### 0.1 마지막 갱신

- 날짜: 2026-08-12
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
  - M1-E release close는 corrected pre-spec `3ca2115` 뒤 product `d1499b3`에서 default Context v3,
    tokenless legacy boundary, exact managed 0.2→0.3 upgrade/rollback과 version/docs 0.3.0을 구현했다.
    Initial full의 implicit-v3 legacy observer 결과는 RESULT-INVALID로 철회하고 test-only `888cd96`
    뒤 corrected full `597 passed, 115 subtests`, ruff/ty/diff와 wheel/temp install을 PASS했다.
    First correction receipt는 `601+115`였지만 second re-audit이 Q2 path/legacy typed-zero와 Q5
    docs/filesystem/product-tree binding을 FAIL했다. Second-correction pre-spec `ff608af` 뒤
    implementation `58b731e`의 fresh single verifier가 `602+115`, exact executed path/typed-zero,
    product tree와 외부 `.research-os` pre/post no-write, authority 0, wheel/install을 PASS했다.
    Q1~Q8 strict re-audit은 PASS했지만 progress audit이 installer manifest case ID 미소비를
    Severity-1로 FAIL했다. Third pre-spec `b70a98f` 뒤 implementation `e120292`가 structured
    six IDs를 actual outcome과 verifier receipt에 bind했고 fresh single verifier `609+115`,
    installer `6/6`을 PASS했다. Independent critic Q1~Q8과 progress four-pass audit가 PASS해
    M1-E와 parent M1/v0.3을 `CLOSE`했고 M2-A를 활성화했다.
  - M2-A는 separate ProgramManifest/ProgramLog, exact M1 origin replay와 rebuildable projection을
    구현했다. First critic의 same-head race FAIL을 barrier+thread-attributed loser writes `0/0`으로
    보정했고 corrected `22/22`, race `50/50`, fresh full `635+115`, critic과 corrected audit이
    모두 PASS해 M2-A를 CLOSE하고 M2-B를 활성화했다.
  - M2-B immutable Claim/relation은 critic Attempts 1/2와 audit Attempt 1 FAIL을 교정해 critic
    Attempt 3와 independent re-audit PASS로 5/5 CLOSE했다. Frozen `25`, focused `37`, adjacent `96`,
    full `672+115`, authority `10/0`; M2-C retrieval이 active다.
  - M2-C §09 pre-spec과 frozen `retrieval-v1.json`은 product/result 전에 exact four-query oracle,
    ordering, Context v3 Program-head token stale contract를 `e6de927`에 고정했다. 독립 critic의 8개
    closed questions도 저장했다. Product `bc0b79a`는 receipt `100/100/100/0`, real ProgramStore
    vertical/stale no-write, focused `4`, adjacent `87+3`, full `676+115`를 PASS했다. Critic Q1~Q8과
    independent seven-pass audit도 PASS해 M2-C를 CLOSE하고 M2-D를 활성화했다.
  - M2-D는 Proposal-bound three-way knowledge disposition과 digest-only legacy opaque event를
    canonical ProgramLog에 저장·replay하고 exact 0.2/0.3→0.4 upgrade를 구현했다. Attempt 1
    receipt `712+115`는 durable three-way proxy 결함으로 철회했다. Corrected commit `9dbb413`의
    actual two-scope append/cold replay `3/3`, frozen `23/23`, full `713+115`, upgrade `6/6`, authority
    0, external writer delta 0, wheel 0.4.0이 PASS했고 independent critic reverify도 PASS했다.
    Audit Attempt 1의 stale-state/LOC 문서 결함을 교정한 independent re-audit가 23/23,
    Severity-1/2 0으로 PASS해 M2-D/parent M2를 CLOSE하고 M3-A를 활성화했다.
  - M3-A는 current Context/Program/retrieval/Proposal/disposition을 bind하는 DecisionPacket v1과
    Python Protocol/strict JSON subprocess port를 구현했다. Frozen `32/32`(conformance `8/8`,
    rejection `24/24`), focused `41`, adjacent `103`, corrected full `757+115`, authority/write delta 0,
    ruff/ty가 PASS했다. Independent critic Q1~Q8과 corrected seven-pass audit도 PASS해 M3-A를
    CLOSE하고 M3-B를 활성화했다.
  - M3-B finite episode는 frozen `43/43`, corrected focused `60`, adjacent `125`를 PASS했다.
    Critic Attempt 1의 copied-ref/proxy/boundary FAIL을 `f53e37c`에서 canonical three-log reconciliation,
    actual ResearchService E2E, post-terminal retry matrix로 교정했고 Attempt 2 Q1~Q8이 PASS했다.
    Six conjunct `6/6`; audit Attempts 1~3 FAIL을 보존·교정했고 Attempt 4 `29/29` PASS로 M3-B를 닫았다.
  - M3-C crash-resume는 frozen `31/31`과 exploratory nondeterministic/service/authority evidence를 PASS했다.
    Critic Attempt 1은 lookup→append race witness와 상태/응답 규율을 FAIL했고, 실제 interleaving `3/3`을
    교정했다. Critic Attempt 2와 corrected audit Attempt 2가 PASS해 M3-C `5/5`를 닫고 M3-D를 활성화했다.
  - M3-D first release harness `0fa3a6c`는 independent critic Attempt 1에서 proxy/historical-arm/custody/metric/
    boundary/verifier 결함으로 FAIL했다. Pre-data correction은 실제 `ClassState`/retrieval/disposition/autonomy
    serializer, archived v0.2 builder, M3-D-owned attack `24/24`, durable draw+arm reservation, non-regression metric,
    generated boundary `6/6`으로 교체됐다. Corrected focused `63`, adjacent M3-A/B/C `142`, full `921+115`,
    legacy parity `1`과 ruff/ty/diff는 PASS했다. Critic Attempt 2는 Q1~Q3/Q5~Q8 DIRECT, Q4 FAIL이었고,
    nonce 전 reservation-directory/parent fsync를 추가해 교정했다. Attempt 3는 Q1~Q8 DIRECT로 PASS했고,
    release-gate `10/10`과 acceptance artifact `0/5`를 재확인했다. Clean `a0ea755`에서 외부 custody draw를
    정확히 1회 실행했으나 post-draw working tree에서 body absence를 검사한 chronology test 때문에 outer
    full `917 passed, 4 failed, 115 subtests`로 `RESULT-INVALID`였다. 동일 draw는 재실행하지 않고 suite/race/
    prearm/custody/result를 Attempt 1 evidence로 보존했다. sealed code commit에서 body absence를 증명하는
    pre-data correction의 critic Attempt 4는 archive rename 경로를 조회한 Q4 결함으로 FAIL했다. 보존 파일
    경로와 historical canonical Git lookup 경로를 분리한 test-only correction은 새 checkpoint·Attempt 5
    PASS로 닫혔다. Distinct code checkpoint `463df30`/new nonce의 Acceptance Attempt 2는 choice `96/96`,
    terminal/evidence `36/36`, retry `0`, waste `0` 대 v0.2 `36`, protocol `24/24`, external `3/3`, full
    `922+115`, upgrades `7/7`, wheel/install 0.5.0으로 8/8 PASS했다. Receipt `95e7eb…5387`와 clean
    `ca69bb9`의 single release verifier도 exact PASS했다. Final audit Attempt 1은 문서/governance 결함으로
    FAIL했고 Rule 9 “승인”을 기록했다. M3-D close에는 amended-foundation critic과 corrected re-audit가 남았다.

### 0.2 현재 운영 상태 (확인 명령 포함)

```bash
cd /Users/bbangjo/research-os
git status --short
uv run --python 3.12 --with pytest --no-project env PYTHONPATH=src pytest -q
rg -n '^version =|__version__' pyproject.toml src/research_os/__init__.py
```

- M3-A measured checkpoint `42c7557`: frozen `32/32`, focused `41`, adjacent `103`, corrected full
  `757 passed, 115 subtests`, ruff/ty, authority non-null 0, product multi-agent false PASS.
- M3-B correction checkpoint `e60b5dd`: frozen `43/43`, focused `60`, adjacent `125`, actual
  ResearchService/source-log reconciliation/post-terminal bounds, critic PASS, audit Attempt 4 PASS.
- 제품 후보 버전: `0.5.0`; official release close는 amended-foundation critic·corrected audit 전까지 금지된다.
- 승인된 기존 certification 수정은 M1-A checkpoint `ed76067`에 포함됐다.
- canonical StudyContract/generation/budget은 M1-B `df2c900`, typed Proposal/scope/replication은 M1-C `a783a88`과 후속 test-only checkpoints에 포함됐다. M1-D Diagnosis/ClassState/frontier는 `f570f92`에 포함됐다.

### 0.3 가장 먼저 할 일 (의사결정 트리)

- [ ] **단일 최우선 행동:** Rule 9-approved amended M chain을 bootstrap critic에 제출한다. PASS 뒤 같은
      clean docs checkpoint를 independent progress re-audit에 제출한다. Acceptance/release-bound bytes는
      더 바꾸거나 다시 실행하지 않는다.

### 0.4 살아있는 산출물 (직전 세션 결과)

| 항목 | 위치 | 상태 | 근거 |
|---|---|---|---|
| v0.5 제품 candidate + M1~M3 implementation | `src/research_os/` | release close candidate; M3-D 8/8 | finite restartable loop, Program memory, sealed unseen effect |
| 전체 테스트 | `tests/` | PASS | acceptance and fresh verifier each `922+115`; protocol `24/24`; race `12/12` |
| 진행 상태 core | `docs/research-os-status.md` | critic/re-audit pending | M1/M2/M3-A/B/C closed; M3-D 8/8 close candidate; Rule 9 approved |
| M1-E vertical slice | `docs/research-os-status/05-2026-08-11-m1-e-usable-context.md` | complete; independent audit PASS | opt-in Context v3 + Diagnosis template + disposable example PASS |
| M1-E release close | `docs/research-os-status/06-2026-08-11-m1-e-release-close.md` | complete; independent audit PASS | receipt `e120292`; `609+115`; installer `6/6` |
| M2-A Program memory boundary | `docs/research-os-status/07-2026-08-11-m2-a-program-manifest-log.md` | complete; critic + audit PASS | corrected `22`, race `50/50`, full `635+115` |
| M2-B Conditional Claim graph | `docs/research-os-status/08-2026-08-11-m2-b-conditional-claims.md` | complete; critic + corrected audit PASS | frozen `25`, focused `37`, full `672+115` |
| M2-C deterministic retrieval | `docs/research-os-status/09-2026-08-11-m2-c-deterministic-retrieval.md` | complete; critic + audit PASS | `bc0b79a`; full `676+115` |
| M2-D disposition/v0.4 | `docs/research-os-status/10-2026-08-12-m2-d-disposition-v04-release.md` | closed 5/5 | corrected receipt `f1ab646`; critic + corrected audit PASS |
| M3-A DecisionPacket | `docs/research-os-status/11-2026-08-12-m3-a-decision-packet.md` | closed 4/4 | receipt `32/32`; full `757+115`; critic + corrected audit PASS |
| M3-B finite loop | `docs/research-os-status/12-2026-08-12-m3-b-finite-autonomy-loop.md` | closed 6/6 | frozen `43/43`; corrected `60/125`; critic + audit PASS |
| M3-C crash resume | `docs/research-os-status/13-2026-08-12-m3-c-crash-resume.md` | closed 5/5 | frozen `31/31`; critic PASS; corrected audit PASS |
| M3-D unseen/release | `docs/research-os-status/14-2026-08-12-m3-d-unseen-release.md` | close candidate 8/8 | Attempt 1 invalid preserved; Attempt 2 + verifier PASS; audit Attempt 1 FAIL; correction gates pending |
| M3-D Rule 9 correction | `docs/research-os-status/14.5-correction-non-regression.md` | user approved; critic pending | exact proposal에 사용자 verbatim “승인”; docs-only |
| M3-D Attempt 1 failure review | `docs/research-os-status/14-m3-d-attempt-1-failure-review.json` | immutable review evidence | same-draw rerun false; external result SHA recorded; authority null |
| v0.5 release receipt | `docs/research-os-status/v0.5.0-release-receipt.json` | immutable PASS | external exact SHA `95e7eb…5387`; `922+115`; authority null |
| 방법론 pipeline core | `docs/research-os-pipeline.md` | close candidate sync | Cycle 14 M3-D 8/8; Rule 9 approved; critic/re-audit pending |

### 0.5 알려진 잔여 이슈

- candidate-only `VERIFY`를 구현한 외부 adapter는 baseline VERIFY 추가에 change-control이 필요하며, 실제 호환성은 v0.5 이후 pilot 전 별도 판정한다.
- `.venv`/기본 `uv run`이 Python 3.10을 선택할 수 있어 프로젝트 요구사항 Python ≥3.11을 만족하는 명시적 검증 명령이 필요하다.
- M1-C/M1-D historical regression floor의 상호 재귀는 차단했지만 top-level full이 self-oracle
  child suite 세 번을 실행해 약 20분 걸린다. 증거 유효성은 유지되나 latency 부채는 남는다.
- v0.5 성능 청구는 bootstrap 시점에는 사전 데이터 노출 commit이 없으므로 기본적으로 `EXPLORATORY`이며, 고정 benchmark 결과 후 별도 confirmatory validation이 필요하다.
- M1-B budget은 **generation별 non-refundable reservation**이다. 실제 elapsed/cost 사용량 telemetry나 settlement가 아니며 study lifetime cap도 아니다.
- 새 evaluation-sealed successor generation이 새 budget을 열 수 있고 반복 증액 자체를 막는 lifetime governance는 아직 없다.
- Context v3는 M1 scientific state와 opt-in audited Claim/retrieval reason을 노출하고 registered
  Proposal-bound disposition을 ProgramLog에 남긴다. M3-B actual loop가 다음 Context/DecisionPacket에서
  이를 소비한다. Crash resume는 M3-C이며 explicit Context v2는 compatibility surface로 남는다.
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

- 저장소: `/Users/bbangjo/research-os`, 제품 candidate 버전 `0.5.0`; 마지막 closed milestone은 M3-C.
  M3-D는 Acceptance Attempt 2와 release verifier가 8/8 PASS한 close candidate며 final audit만 남았다.
  v0.4 release receipt checkpoint `f1ab646`.
- 구현 크기: `rg --files src tests -g '*.py' | sort | xargs wc -l`의 Python 합계
  67,688 LOC (Cycle 12 audit correction).
- 검증 기준선: 보존 tag `research-os-m1a-working-tree-baseline`에서 Python 3.12 `262 tests + 57 subtests` PASS.
- 강점: append-only hash-chained event log, disposable projection, artifact CAS, evaluator
  certification, stale-context와 compatibility gate, fail-closed recovery, `authorized_action=null`,
  canonical StudyContract/generation/budget, typed Proposal/Diagnosis/ClassState/frontier, audited Claim
  graph/deterministic retrieval, Proposal-bound knowledge disposition, digest-only legacy isolation,
  default Context v3, exact managed 0.2/0.3 upgrade.
- 핵심 갭: v0.5 범위의 구현/측정 갭은 닫혔고 독립 progress audit만 남았다. Live pilot/migration과 제품
  multi-agent는 release 후 별도 작업이다.
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

### 2.2.1 Cycle 07 실행 PIVOT

M2-A product cap은 pre-result `1,300→1,650`, historical verifier correction 포함 total cap은
post-result `2,750→3,100`으로 변경했다. 19-case ID/operation과 네 conjunct는 유지했고 critic 뒤
race expected를 loser writes `0/0`으로 강화했다. Claim은 core CONFIRMATORY + corrections
EXPLORATORY의 `MIXED`다.

### 2.2.2 Cycle 08 실행 PIVOT

Original frozen 25는 CONFIRMATORY다. Critic-driven writer/multi-artifact/one-factor/no-write 보강과
tests+fixture cap `1,100→1,250`은 EXPLORATORY이며 phase 전체 label은 `PIVOT/MIXED`다. Product
`1,500`, docs `500`, total `3,100`과 five conjunct는 유지한다.

### 2.2.3 Cycle 10 실행 PIVOT

- **Trigger:** independent critic Attempt 1이 frozen standalone three-way validator와 actual durable
  two-way vertical을 합쳐 durable three-way로 청구한 proxy-vs-real 측정 결함을 지적했다.
- **Amendment:** Attempt 1 receipt/NS 청구를 철회하고 actual development+diagnostic scope/origin
  Claim 3개를 registered Proposal+validated Context에서 `used|rejected|not_applicable`로 append/cold
  replay하는 test-only witness를 추가했다. Corrected receipt는 이 node를 `1/1`로 별도 bind한다.
- Frozen 23 denominator/threshold, product semantics, external read-only/live-pilot 제외, M chain 정의는
  바꾸지 않았다. Claim mode는 frozen rows CONFIRMATORY + correction witness EXPLORATORY의
  `MIXED`다.

### 2.2.4 Cycle 11 실행 PIVOT

- **Trigger:** M3-A first full에서 historical v0.4 static gate가 current M3 HEAD를 sealed v0.4
  product tree와 비교해 root failure 1건과 nested cascade 3건을 만들었다.
- **Amendment:** v0.4 evidence는 receipt/product checkpoint의 historical tree·version surface에서
  검증하고, later commit에서 historical receipt를 재발행하지 못하게 했다. Attempt 1은
  `RESULT-INVALID`로 철회하고 같은 full command를 재측정했다.
- Frozen M3-A manifest 32 ID/bytes, error class, threshold, packet/provider product와 M chain 정의는
  바꾸지 않았다. Claim mode는 frozen rows CONFIRMATORY + result-triggered correction EXPLORATORY의
  `MIXED`다.

### 2.2.5 Cycle 12 실행 correction

- **Trigger:** M3-B critic Attempt 1이 AutonomyLog copied-ref replay, replay service proxy, post-terminal
  boundary 부족, Cycle 12/LOC claim-mode 누락을 Q3/Q4/Q5/Q6/Q8 FAIL로 지적했다.
- **Amendment:** `f53e37c`가 canonical ProjectLog/ProgramLog reconciliation과 tamper reject, disposable
  actual ResearchService vertical, invalid/transport 반복의 invalid/provider/token/time stop을 추가했다.
- Frozen 43 IDs/bytes와 six conjunct는 바꾸지 않았다. Corrections와 artifact binding, LOC finding은
  EXPLORATORY이며 phase는 `MIXED`; critic PASS, audit Attempts 1~3 corrected, Attempt 4 PASS다.

### 2.2.6 Cycle 14 M3-D target strengthening — Rule 9 approved

- **Trigger:** pre-unseen critic Attempt 1이 기존 `min(90%, baseline+20%p)` 공식을 따르면 baseline이 90%를
  넘을 때 v0.5가 baseline보다 퇴행해도 통과할 수 있음을 지적했다.
- **Amendment:** choice와 terminal 모두 `max(baseline, min(90%, baseline+20%p))`로 강화했다. 36 episodes,
  six families, protocol/evidence/retry/waste/compatibility gates, product scope와 exclusions는 바꾸지 않았다.
- **Chronology:** `e23c089` correction contract와 `20b35a5` implementation에서 어떤 acceptance nonce/body/result
  보다 먼저 변경됐다. 따라서 사후 결과 완화가 아니라 pre-result non-regression guardrail 강화다.
- **Governance correction:** prior “M chain definition unchanged” 표기는 철회한다. Pipeline §9.5와
  `research-os-status/14.5-correction-non-regression.md`에 기록했다. 사용자는 제시된 정확한 amendment에
  **“승인”**이라고 verbatim 응답했다. Amended-foundation critic과 corrected re-audit은 아직 남았다.

### 2.3 마일스톤 진척 (checkpoint chain — Rule 8) ★

> 정적 정의는 `docs/research-os-pipeline.md` §9, 동적 진척만 이 절에서 추적한다.

#### 2.3.1 사용자 verbatim 합의 (Bootstrap step 6.5 인용)

> "위 방향대로 개선해서 v0.5 까지 개선을 진행하고 싶다"

> "추천안 승인 / 로컬 체크포인트 커밋 허용 / 기존 certification 패치 포함"

> "회고 승인 / unseen synthetic benchmark를 v0.5 release gate로 인정 / 실제 프로젝트 live pilot·migration은 v0.5 이후 / multi-agent는 NS6 통과 이후"

#### 2.3.2 현재 active checkpoint

- **Active M_i.j**: `M3-D` (`open`)
- **직전 close가 가능하게 한 작업**: M3-C가 crash-resume/authority `5/5`, critic과 corrected audit를 PASS했다.
- **현재 M3-D 상태**: critic Attempt 5 PASS 뒤 distinct Acceptance Attempt 2와 release verifier가 8/8 PASS했다.
  Attempt 1 `RESULT-INVALID`와 Attempt 4 FAIL은 그대로 보존된다.
- **이 M.j가 닫혀야 다음에 가능해지는 작업**: parent M3/v0.5 release close와 post-v0.5 pilot 계획.
- **현재 close 차단 gate**: amended-foundation bootstrap critic, then corrected independent progress re-audit.
- **M3 parent close까지 남은 sub**: M3-D.

#### 2.3.3 M 진척 표

| M_i.j | 정의 (요약) | exit conjunct progress | 상태 | closed-by phase | 근거 |
|---|---|---|---|---|---|
| M1-A | Decision/evidence correctness | 4/4 ✅ | closed | 01 | phase §01.3~§01.6.4 |
| M1-B | Study generation과 누적 budget | 4/4 ✅ | closed | 02 | phase §02.4~§02.6.4; manifest `29/29`; checkpoint `df2c900`; critic + auditor PASS |
| M1-C | Typed Proposal과 replication identity | 4/4 ✅ | closed | 03 | phase §03.4~§03.6.4; manifest `20/20`; critic + auditor PASS |
| M1-D | Diagnosis·ClassState·semantic frontier | 5/5 ✅ | closed | 04 | phase §04.5~§04.6.4; transition `26/23/54/37/7`; negative `460/460`; critic + auditor PASS |
| M1-E | Context v3·legacy compatibility·v0.3 release | 5/5 ✅ | closed | 06 | `e120292`; `609+115`; installer `6/6`; critic + auditor PASS |
| M2-A | ProgramManifest·ProgramLog | 4/4 ✅ | closed | 07 | corrected critic + audit PASS |
| M2-B | Conditional Claim과 evidence 관계 | 5/5 ✅ | closed | 08 | critic Attempt 3 + corrected audit PASS |
| M2-C | Deterministic retrieval·Context integration | 5/5 ✅ | closed | 09 | critic + independent audit PASS |
| M2-D | Knowledge disposition·legacy import·v0.4 release | 5/5 ✅ | closed | 10 | phase §10.6.4; corrected `713+115`; critic + corrected audit PASS |
| M3-A | Provider-neutral DecisionPacket | 4/4 ✅ | closed | 11 | receipt `32/32`; full `757+115`; critic + corrected audit PASS |
| M3-B | Finite autonomous state machine | 6/6 ✅ | closed | 12 | frozen `43/43`; corrected `60/125`; critic + audit PASS |
| M3-C | Crash-resume·authority·budget stop | 5/5 ✅ | closed | 13 | frozen `31/31`; race `3/3`; critic + corrected audit PASS |
| M3-D | unseen 36-episode benchmark·compatibility·v0.5 release | 8/8 ✅ | close candidate | 14 pending audit | Attempt 2 + release verifier PASS; receipt `95e7eb…5387`; pipeline §9.4 |

#### 2.3.4 Phase ↔ M_i.j 매핑 (history)

| Phase § | 일자 | 영향 받은 M_i.j | conjunct | advance / close | 비고 |
|---|---|---|---|---|---|
| 00 | 2026-08-09 | M1~M3 정의 | bootstrap | advance | 사용자 마일스톤 승인; 구현 전 |
| 01 | 2026-08-10 | M1-A | 4/4 | close | E1~E9 exact; `290+67`; critic + auditor PASS |
| 02 | 2026-08-10 | M1-B | 4/4 | close | manifest `29/29`; focused `81+37`; full `371+104`; checkpoint `df2c900`; critic + auditor PASS |
| 03 | 2026-08-10 | M1-C | 4/4 | close | manifest `20/20`; transition/direct `53/72`; full `442+111`; critic + auditor PASS |
| 04 | 2026-08-10~11 | M1-D | 5/5 | close | final corrected manifest/transition, direct `67`, bounded `56`, compatibility `20/20`, single floor PASS; auditor PASS |
| 05 | 2026-08-11 | M1-E | 1/5 | advance | opt-in v3 + template + disposable E2E PASS; M1-E close는 아님 |
| 06 | 2026-08-11 | M1-E | 5/5 | close | third correction `609+115`; installer `6/6`; critic + auditor PASS; parent M1 closed |
| 07 | 2026-08-11 | M2-A | 4/4 | close | race `50/50`; fresh `635+115`; critic + corrected audit PASS |
| 08 | 2026-08-11 | M2-B | 5/5 | close | critic Attempt 3 + corrected audit PASS; M2-C active |
| 09 | 2026-08-11 | M2-C | 5/5 | close | receipt/full + critic + independent audit PASS; M2-D active |
| 10 | 2026-08-12 | M2-D | 5/5 | close | Attempt 1 withdrawn; corrected `713+115`, durable `1/1`; critic + corrected audit PASS; parent M2 closed, M3-A active |
| 11 | 2026-08-12 | M3-A | 4/4 | close | frozen `32/32`, full `757+115`; critic + corrected audit PASS; M3-B active |
| 12 | 2026-08-12 | M3-B | 6/6 | close | frozen `43/43`; critic PASS; audit FAIL 1~3 preserved, Attempt 4 PASS; M3-C active |
| 13 | 2026-08-12 | M3-C | 5/5 | close | frozen `31/31`; critic FAIL→PASS; audit FAIL→PASS; M3-D active |
| 14 | 2026-08-12 | M3-D | 8/8 | close candidate | Attempts 1 invalid/4 FAIL preserved; Attempt 5, Attempt 2 receipt, verifier PASS; audit Attempt 1 FAIL; correction gates pending |

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
| 06 | 2026-08-11 / M1-E release close | [`research-os-status/06-2026-08-11-m1-e-release-close.md`](research-os-status/06-2026-08-11-m1-e-release-close.md) | M1-E 5/5 + parent M1 closed; critic + progress audit PASS |
| 07 | 2026-08-11 / M2-A | [`research-os-status/07-2026-08-11-m2-a-program-manifest-log.md`](research-os-status/07-2026-08-11-m2-a-program-manifest-log.md) | ProgramManifest/Log 4/4 closed; critic + corrected audit PASS |
| 08 | 2026-08-11 / M2-B | [`research-os-status/08-2026-08-11-m2-b-conditional-claims.md`](research-os-status/08-2026-08-11-m2-b-conditional-claims.md) | Claim/relation 5/5 closed; critic + corrected audit PASS |
| 09 | 2026-08-11 / M2-C | [`research-os-status/09-2026-08-11-m2-c-deterministic-retrieval.md`](research-os-status/09-2026-08-11-m2-c-deterministic-retrieval.md) | deterministic retrieval/Context 5/5 closed; critic + audit PASS |
| 10 | 2026-08-12 / M2-D | [`research-os-status/10-2026-08-12-m2-d-disposition-v04-release.md`](research-os-status/10-2026-08-12-m2-d-disposition-v04-release.md) | corrected disposition/legacy/read-only v0.4 closed 5/5; critic + re-audit PASS |
| 11 | 2026-08-12 / M3-A | [`research-os-status/11-2026-08-12-m3-a-decision-packet.md`](research-os-status/11-2026-08-12-m3-a-decision-packet.md) | DecisionPacket/provider 4/4 closed; critic + corrected audit PASS |
| 12 | 2026-08-12 / M3-B | [`research-os-status/12-2026-08-12-m3-b-finite-autonomy-loop.md`](research-os-status/12-2026-08-12-m3-b-finite-autonomy-loop.md) | finite loop 6/6 closed; critic + audit Attempt 4 PASS; M3-C active |
| 13 | 2026-08-12 / M3-C | [`research-os-status/13-2026-08-12-m3-c-crash-resume.md`](research-os-status/13-2026-08-12-m3-c-crash-resume.md) | crash-resume/authority 5/5 closed; critic + corrected audit PASS; M3-D active |
| 14 | 2026-08-12 / M3-D | [`research-os-status/14-2026-08-12-m3-d-unseen-release.md`](research-os-status/14-2026-08-12-m3-d-unseen-release.md) | Attempt 2 unseen/release 8/8 PASS; audit Attempt 1 FAIL; Rule 9 approved; critic/re-audit pending |
| 14.5 | 2026-08-12 / M3-D correction | [`research-os-status/14.5-correction-non-regression.md`](research-os-status/14.5-correction-non-regression.md) | non-regression M-chain amendment; user verbatim “승인”; docs-only |

---

## 11. 한 페이지 요약 (TL;DR)

- 현재 상태: 제품 candidate version `0.5.0`; M1/M2/M3-A/B/C closed, M3-D 8/8 close candidate이며 Rule 9가 승인됐다.
- 마지막 유효 측정: unseen Attempt 2와 fresh release verifier 모두 full `922+115`; receipt SHA
  `95e7eb…5387`; choice/terminal/evidence `96/96·36/36·36/36`, waste `0`.
- 다음 1행동: amended-foundation critic PASS, 그 뒤 corrected independent progress re-audit.
- 가장 큰 잔여 갭: v0.5 scope 밖의 actual live-project efficacy, multi-agent ablation, full-suite latency.

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

| 지표 | 북극성 | 현재 (2026-08-12) | 갭 | 근거 | 시스템 영향 |
|---|---|---|---|---|---|
| NS1. 무결성·권한 하위호환 | 기존 262 tests와 모든 신규 suite 100% PASS ∧ versioned `tests/fixtures/protocol_attacks/v1/manifest.json`의 전체 위반 행 차단률 100% ∧ `authorized_action` non-null 0건 ∧ v1 event replay 100% | **PASS**: protocol `24/24`, full `922+115` twice, receipt authority null; hostile provider sandbox는 미청구 | final audit | phase §14.17 receipt/verifier | 비신뢰 packet authority와 release 권한은 차단됐다; in-process capability isolation은 별도 limitation |
| NS2. 기계 강제 scientific state | generation/contract·누적 budget·diagnosis gate·class closure·semantic frontier·legacy isolation 6/6 동작 ∧ `tests/fixtures/scientific_state/v1/manifest.json`의 모든 입력 상태/transition/거절 code/closure threshold 판정 일치 | **6/6 (`5→6/6`)**; tokenless frozen `7/7`가 Proposal/Diagnosis/class/budget gate와 pre-generation opaque legacy를 exact 분리 | M1 scope 충족; actual telemetry/lifetime governance는 별도 limitation | phases §02, §04~§06; M1-D `26/23/54/37/7`; M1-E `7/7`, corrected full | kernel state와 legacy boundary가 default agent context/release에서도 기계 강제된다 |
| NS3. Durable learning 객체 | typed Proposal·Diagnosis·ClassState·Claim 4/4가 exact event/artifact evidence와 digest로 replay | audited **4/4** 유지; Proposal-bound disposition과 opaque legacy projection도 cold replay | M3 packet/loop 소비 | phases §08,§10; durable three-way `1/1`; critic PASS | durable object와 사용/기각 결과가 대화 요약이 아닌 canonical program memory로 남는다 |
| NS4. Program memory 정확도 | versioned `tests/fixtures/program_memory/retrieval-v1.json`의 exact ordered oracle에서 relevant claim recall 100% ∧ contradiction recall 100% ∧ superseded exclusion 100% ∧ shuffled/irrelevant contamination 0% | audited **4/4** 유지; exact retrieval→three-way disposition append/cold replay `3/3` | M3 next-hypothesis 선택에 실제 소비 | phases §09~§10; corrected receipt + critic PASS | deterministic retrieval이 관련 지식/반증만 선택하고 그 사용 결과를 감사 가능하게 남긴다 |
| NS5. 단일 자율 루프 완결성 | context→proposal→preflight→run→diagnosis→synthesis→next/stop 7 transition 모두 canonical state로 재개 가능 ∧ closed-class registration 0건 | **closed**: nominal `7/7` + crash-resume `13/13`; five conjunct `31/31`; race `3/3` | 없음; M3-D에서 frozen regression 유지 | phase §13 receipt; critic + corrected audit PASS | canonical cold restart가 independent gates를 통과했다 |
| NS6. Fixed-budget 학습 효과 | M3 code freeze 뒤 precommitted generator와 새 256-bit nonce로 만든 unseen acceptance 36 episodes에서 protocol block 100% ∧ evidence-bound conclusion 100% ∧ closed-class retry 0 ∧ next-hypothesis choice accuracy ≥ `max(v0.2,min(90%,v0.2+20%p))` ∧ correct terminal decision ≥ 동일 non-regression threshold ∧ positive-waste aggregate ≤ v0.2의 70% | **PASS**: v0.5 choice `96/96`, terminal/evidence `36/36`, retry `0`, waste `0`; v0.2 `1/96`, `0/36`, waste `36`; verifier exact reproduction | final audit | phase §14.17; receipt `95e7eb…5387` | synthetic fixed-budget learning effect가 측정됐다; open-domain/live-project efficacy로 일반화하지 않는다 |
| NS7. 기존 프로젝트 read-only 호환성 | `crypto-new`, `manager`, `BinancePredictionStrategy` 각각 (기존 complete event bytes/hash/derived v1 state 무변환 replay 3/3) ∧ (typed schema가 없는 legacy free text 100% `legacy_unstructured`, 자동 typed inference 0건) ∧ (외부 writer/file 변경 0건) | **PASS**: roots `1/15/32` events, replay/opaque/no-write `3/3`, writer delta 0 in acceptance and verifier | final audit | phase §14.17 receipt/runtime | read-only compatibility가 release conjunction에 결합됐다; live migration은 여전히 post-v0.5다 |

> NS6 choice 판정: 모든 non-terminal decision point가 exact 허용/최적 `(hypothesis_class, action)` oracle set을 가지며, 선택이 set 밖이거나 closed/duplicate class를 고르거나 필요한 결정을 건너뛰면 오류다. 분모는 양 arm의 모든 oracle decision point다.
>
> NS6 unseen 판정: generator schema·world family·oracle rule·metric은 구현 전에 commit하고, M3 code freeze 후 새 nonce로 36개 body를 생성한다. receipt는 code commit, generator digest, nonce commitment, suite digest, 두 arm 결과를 묶는다. 결과 노출 뒤 code/policy 변경은 그 receipt를 무효화하며 새 nonce 결과는 다시 `EXPLORATORY`로 취급한다.
>
> NS6 waste 예외 규칙: v0.2 median waste가 0이면 v0.5도 0이어야 하며, 감소율은 v0.2 waste가 양수인 paired episode들의 aggregate rate로 판정한다.

### 12.3 남은 작업 (우선순위)

| # | 작업 | 추정 LOC | 어떤 §북극성 행을 움직이나 | 시스템 영향 (예상) |
|---|---|---|---|---|
| 1 | Independent final progress audit | docs only | NS1, NS6, NS7 | receipt/chronology/M-chain/limitations를 독립 검증하고 M3-D/parent M3 close 판정 |

### 12.4 비관 재채점 (latest) ★

| 단계 | 이전 | 현재 (비관) | 사유 | 반례/근거 |
|---|---|---|---|---|
| Integrity kernel | audit 중 △ | ○ | 새 stricter assumption은 self-consistent provider echo도 신뢰하지 않고 current canonical state를 재계산해야 한다는 것; attack 24/24와 authority/write 0이 independent audit까지 통과했다 | corrected `757+115`; frozen `32/32`; forged snapshot/current-head witnesses; critic + corrected audit PASS |
| Evidence semantics | arbitrary constraint 중심 | ○ | directional delta·typed slack·verify symmetry 구현; 외부 metric 의미는 아직 contract 밖 | phase §01 E1~E9 |
| Scientific State | 문서상 일부 존재 | ○ | Proposal/Diagnosis/ClassState/frontier와 Claim/relation/disposition이 executable. actual telemetry·lifetime cap은 없음 | NS2 = 6/6; NS3 4/4; current full `713+115` |
| Relevant Context | recent v2 packet | ○ | exact Claim/reason/Program head/disposition을 finite loop의 next Context/DecisionPacket이 실제 재소비한다 | phase §12 next-packet witness; corrected `60` |
| Program Memory | Finding 존재 | ○ | audited Claim graph/retrieval 4/4와 legacy opaque/disposition replay. 단, Attempt 1 critic의 stricter assumption인 **actual durable three-way**를 corrected witness 전에는 만족하지 못했다 | Attempt 1 withdrawn; corrected durable `1/1`, frozen `23/23`; critic + corrected audit PASS |
| Autonomous Loop | agent workflow 존재 | ○ | Cycle 13 competing-writer assumption은 actual interleaving `3/3`으로 fail-closed했고 corrected audit까지 PASS했다. Hostile in-process provider sandbox는 별도 limitation이다 | NS5 `31/31`; race `3/3`; focused `41`; adjacent `142`; critic + corrected audit PASS |
| 학습 효과 | 미측정 | ○ | distinct unseen Attempt 2가 choice/terminal/evidence `100%`, retry/waste `0`로 PASS했고 verifier가 exact 재현. Synthetic transfer만 청구 | receipt `95e7eb…5387`; full `922+115` twice |

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
| 06 M1-E release close correction | first `3eaba21→1aa9c58`; second `ff608af→58b731e`; third `b70a98f→e120292` | Rule9 second PIVOT cap total 1,600; nested latency | `609+115`; installer `6/6`; critic + auditor PASS; M1 closed |
| 07 M2-A close | `61adebc..9840208`: product+release `1,635`, tests+fixture `980`, docs `404`, total `3,019` | corrected audit-ledger cutoff; category caps `1,650/1,000/450`, pivoted total cap `3,100` | corrected `22`, race `50/50`, fresh `635+115`; critic + corrected audit PASS |
| 08 M2-B close | product `1,463`; tests+fixture `1,242`; docs `376`; total `3,081` | caps `1,500/1,250/500`, total `3,100`; PIVOT/MIXED | `25`, focused `37`, adjacent `96`, full `672+115`; critic + corrected audit PASS |
| 09 M2-C close | product `684`; tests+fixture `921`; docs `<=500`; total `<2,550` | caps `900/1,150/500`, total `2,550`; CONFIRMATORY | receipt `100/100/100/0`; full `676+115`; critic + audit PASS |
| 10 M2-D v0.4 close | `git diff --numstat 4b0d0a1..f1ab646`: product `1,150`, tests+fixture `1,242`, verifier `398`, other release/docs surfaces `237`; total `3,027/3,200` | frozen rows CONFIRMATORY + critic correction EXPLORATORY = MIXED; external writer/live migration 0 | frozen `23/23`; durable `1/1`; full `713+115`; upgrades `6/6`; critic + corrected audit PASS; parent M2 closed |
| 11 M3-A close | product `1,081/1,100`; M3-A tests+fixtures `744/1,250` (frozen manifest `96` + provider fixture `51` + test `597`); phase+critic+receipt+audit docs `447/450`; result-triggered verifier correction `+119/-52`; paired-core additions `78`; inclusive gross `2,469/2,800` | frozen 32 CONFIRMATORY + historical-gate correction EXPLORATORY = MIXED; product/test/script sealed at `42c7557` | frozen `32/32`; focused `41`; adjacent `103`; full `757+115`; critic + corrected audit PASS |
| 12 M3-B close | product `2,035 additions + 8 deletions = 2,043 churn`; tests+fixture `1,384`; paired+phase evidence `473`; exact inclusive `3,900/3,900` | product subtarget `1,600` miss is GENUINE-FINDING/EXPLORATORY; M3-C follow-up precommitted | frozen `43/43`; focused `60`; adjacent `125`; critic + audit Attempt 4 PASS |
| 13 M3-C close | product `353/900`; tests+fixture `829/1,400`; paired evidence `489`; inclusive `1,671/2,800` | phase+critic+receipt+audit `419/500`; MIXED | frozen `31/31`; race `3/3`; focused `41`; adjacent `142`; critic + corrected audit PASS |
| 14 M3-D close candidate | cycle base `7b00e0b` to Rule 9 approval checkpoint: `5,081 additions + 40 deletions = 5,121/6,000` inclusive; generated acceptance/evidence objects 10/1,200 | implementation subtarget miss remains GENUINE-FINDING/EXPLORATORY; phase+critic+receipt+audit/correction `694/800`; correction is docs-only | Attempt 1 invalid preserved; Attempt 5 PASS; Attempt 2 + verifier `922+115`; audit Attempt 1 FAIL; user verdict “승인”; critic/re-audit pending |

---

## 14. pipeline §매핑 / §종착지 동기화 체크

마지막 동기화 일자: 2026-08-12

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
- [x] Cycle 06 initial implementation/full/static/wheel run — prior regression evidence retained
- [x] Cycle 06 independent critic — **FAIL** (Q1/Q2/Q5/Q8)
- [x] Cycle 06 executable release-gate correction + fresh verification — **PASS**
- [x] Cycle 06 independent progress auditor final verdict — **PASS** (`research-os-status/06-m1-e-release-close.audit.md`)
- [x] Cycle 07 paired core에 M2-A candidate 4/4와 Program Memory `✗→△` 동기화
- [x] Cycle 07 first critic FAIL의 same-head race를 barrier·loser writes `0/0`으로 correction
- [x] Cycle 07 critic Q1~Q8 corrected reverify — **PASS**
- [x] Cycle 07 first independent audit — **FAIL** (LOC/§11/stricter-assumption docs)
- [x] Cycle 07 corrected independent progress re-audit — **PASS** (`research-os-status/07-m2-a-program-manifest-log.audit.md`)
- [x] Cycle 08 critic Attempts 1/2 FAIL과 Attempt 3 PASS chronology 보존
- [x] Cycle 08 `PIVOT/MIXED`, `5/5`, `37/672+115`, paired-core gap 동기화
- [x] Cycle 08 audit Attempt 1 corrections independent re-audit PASS; M2-B closed, M2-C active
- [x] Cycle 09 status §12와 pipeline §8.4·§8.5·§10을 M2-C candidate로 동기화
- [x] Cycle 09 M chain 정의 변경 없음; M2-C progress만 5/5 candidate로 갱신
- [x] Cycle 09 progress critic Q1~Q8 + independent full re-run — **PASS**
- [x] Cycle 09 independent progress audit — **PASS** (`research-os-status/09-m2-c-deterministic-retrieval.audit.md`)
- [x] Cycle 10 Attempt 1 receipt/claim 철회 — critic Q2 proxy-vs-real **FAIL**
- [x] Cycle 10 corrected actual durable three-way + single release `713+115` — critic reverify **PASS**
- [x] Cycle 10 M chain 정의 변경 없음; M2-D candidate→close, M3-A active 동적 진척만 반영
- [x] Cycle 10 independent seven-pass audit Attempt 1 — **FAIL** (stale §1.1/critic state, LOC cutoff mismatch; product evidence reproduced)
- [x] Cycle 10 corrected independent re-audit — **PASS** (`research-os-status/10-m2-d-disposition-v04-release.audit.md`)
- [x] Cycle 10 M2-D/parent M2 close; M3-A active
- [x] Cycle 11 status §12와 pipeline §8.4·§8.5·§10을 M3-A close candidate로 동기화
- [x] Cycle 11 M chain 정의 변경 없음; M3-A progress만 engineering 4/4 ADVANCE로 갱신
- [x] Cycle 11 progress critic Q1~Q8 independent verify — **PASS**
- [x] Cycle 11 independent seven-pass audit Attempt 1 — **FAIL** (cold-start action, Python LOC,
  frozen manifest denominator)
- [x] Cycle 11 corrected independent re-audit — **PASS** (`25/25`, Severity-1/2 0)
- [x] Cycle 11 M3-A close; M3-B active; M chain definition unchanged
- [x] Cycle 12 status §12와 pipeline §8.4·§8.5를 M3-B `6/6` close candidate로 동기화
- [x] Cycle 12 critic Attempt 1 FAIL 보존, correction `f53e37c`, Attempt 2 Q1~Q8 PASS
- [x] Cycle 12 independent seven-pass audit Attempt 1 — **FAIL** (LOC·상태·재평가 정합성)
- [x] Cycle 12 audit Attempt 4 PASS (`29/29`, S1/S2 0); M3-B close, M3-C active
- [x] Cycle 13 M3-C frozen `31/31`; critic Attempt 1 FAIL 보존
- [x] Cycle 13 lookup→append race correction `3/3` + independent critic Attempt 2 PASS
- [x] Cycle 13 independent audit Attempt 1 — **FAIL** (phase index, LOC ledger, intent/execution split, pessimistic re-score)
- [x] Cycle 13 corrected independent audit Attempt 2 — **PASS** (`8/8`, S1/S2 0)
- [x] Cycle 13 M3-C closed; M3-D active
- [x] Cycle 14 critic Attempt 1 FAIL 보존; Q1~Q6/Q8 pre-data correction 구현
- [x] Cycle 14 corrected focused `63`, adjacent `142`, full `921+115`, ruff/ty/diff PASS; nonce/result absent
- [x] Cycle 14 critic Attempt 2 Q4-only FAIL 보존; pre-draw directory/parent fsync correction targeted `2/2`
- [x] Cycle 14 critic Attempt 3 Q1~Q8 DIRECT — **PASS**; acceptance artifacts `0/5`
- [x] Cycle 14 당시 M chain unchanged 표기 — final audit에서 부정확 판정, 철회
- [x] Cycle 14 Acceptance Attempt 1 exactly once — outer `917/4+115`; chronology root defect로 **RESULT-INVALID**
- [x] Cycle 14 동일 draw 재실행 금지; external result와 suite/race/prearm/custody archive 보존
- [x] Cycle 14 historical canonical-path correction focused `64`, collection `922`, ruff/ty/diff PASS
- [x] Cycle 14 independent critic Attempt 4 — **FAIL** (archive name과 sealed canonical lookup path 혼동)
- [x] Cycle 14 historical canonical-path correction + independent critic Attempt 5 PASS
- [x] Cycle 14 Attempt 5 PASS 뒤 distinct new-nonce Acceptance Attempt 2 exactly once — **PASS 8/8**
- [x] Cycle 14 immutable external/repository receipt exact SHA `95e7eb…5387`; authority null
- [x] Cycle 14 fresh single release verifier — exact receipt, full `922+115`, wheel/install 0.5.0 PASS
- [x] Cycle 14 independent final progress audit Attempt 1 — **FAIL** (threshold typo + Rule 9 기록 누락)
- [x] Cycle 14 non-regression strengthening Rule 9 사용자 회고 — verbatim **“승인”** (`research-os-status/14.5-correction-non-regression.md`)
- [ ] Cycle 14 amended-foundation bootstrap critic PASS
- [ ] Cycle 14 corrected independent progress re-audit; PASS 뒤 M3-D/parent M3/v0.5 close
