# §05 — M1-E usable Context v3 vertical slice (2026-08-11)

> Status: **VERTICAL SLICE COMPLETE — CONFIRMATORY / independent audit PASS**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §2
> Prerequisite: M1-D checkpoint `f570f92`, five conjunct `5/5`, independent audit PASS
> Claim mode: **CONFIRMATORY** for this fresh vertical-slice acceptance only

## 05.0 TL;DR

M1-E 전체 release gate를 한 번에 만들지 않고, 사용자가 즉시 실행해 볼 수 있는
한 경로를 먼저 고정한다. `agent-context --schema-version 3`이 M1-D scientific
state를 노출하고, `diagnosis-template`이 exact evidence field를 자동 작성하며,
agent는 네 개 해석 field만 채워 `diagnose`한다. 완료 후 context v3에서 pending
제거와 ClassState/frontier 변화를 바로 확인한다.

## 05.1 Scope and authority

- 포함: opt-in Context v3, Diagnosis authoring template, disposable local example,
  v2 byte/shape parity, focused CLI/service tests.
- 제외: M1-E의 tokenless legacy write 정책, managed skill upgrade/rollback,
  version 0.3.0, full release regression. 이 vertical slice는 M1-E를 닫지 않는다.
- 외부 `crypto-new`, `manager`, `BinancePredictionStrategy`는 계속 read-only이다.
- template/context는 event, projection, project source를 쓰지 않고
  `authorized_action` authority를 추가하지 않는다.

## 05.2 Frozen acceptance

1. `agent-context --schema-version 3`은 packet `schema_version=3`과 exact
   `science` object를 반환한다. 그 object에 active generation, budget,
   `pending_diagnosis_experiment_ids`, `class_states`, `study_stop`,
   `semantic_frontier`, `retry_frontier`가 모두 있다.
2. 기존 `build_agent_context()`와 `agent-context --schema-version 2`의 canonical
   output은 M1-D checkpoint 대비 변하지 않는다.
3. pending terminal이 하나면 `diagnosis-template`은 generation/Proposal/scope,
   terminal event ID/hash, canonical artifact full set, kernel-derived observation을 채운
   direct Diagnosis body를 반환한다. 해석용 네 field에만 fail-closed
   `REPLACE_ME` sentinel이 남는다.
4. pending이 0개이거나 2개 이상이면 experiment ID 생략을 stable code로
   거절한다. unknown, nonterminal, already-diagnosed ID도 no-write로 거절한다.
5. frozen disposable history에서 template의 네 field를 채운 Diagnosis가
   public `diagnose`를 PASS하고, 다음 Context v3에 pending이 제거되며
   ClassState/frontier가 reducer output과 exact match한다.
6. context/template 호출 전후 canonical event bytes, projection bytes, project writer
   diff는 `0`이다. Packet 크기는 기존 2 MiB cap을 계속 적용한다.

## 05.3 Small implementation seam

- `science/state.py`: existing replay truth로 exact Diagnosis skeleton을 만드는 pure helper.
- `agent.py`: v2 builder를 수정하지 않고 v3 wrapper를 추가.
- `service.py`, `cli.py`: `schema_version` opt-in과 read-only `diagnosis-template`.
- tests: 하나의 disposable history vertical slice + negative 4개 + v2 parity.

Product code보다 큰 manifest/oracle는 추가하지 않는다. 이 slice의 추가
예산은 source+test+doc `1,200` lines 이하다.

## 05.4 Verification and milestone effect

- Focused: v3 builder/service/CLI, template exactness/no-write, fill→diagnose→refresh E2E.
- Compatibility: existing agent interface/context v2 and M1-D direct service tests.
- Static: ruff, ty, `git diff --check`.
- Milestone: M1-E context conjunct의 usable vertical slice만 증명한다.
  legacy/upgrade/version/full-suite conjunct가 남으므로 M1-E와 parent M1은 open이다.
- Requirement divergence: acceptance를 구현 후 바꾸면 기존 결과를
  `RESULT-INVALID`로 제외하고 이 slice를 EXPLORATORY로 낮춘다.

## 05.5 Next action

Critic의 Q1~Q6을 답한 뒤 이 acceptance 그대로 focused test를 먼저 작성하고
제품을 구현한다.

## 05.6 Implementation result

- Pre-spec checkpoint: `38446f1` (product source/test change 0).
- `build_agent_context_v3()`는 기존 v2 packet shape을 소비하고
  `ScientificState.to_dict()`를 `science`로 노출한다. Service는 canonical event snapshot을
  temp EventLog/projection에 exact replay해 project event/cache를 쓰지 않는다. Pending이 있으면 run/propose
  action 대신 `AUTHOR_PENDING_DIAGNOSIS`만 노출하고, stop 후에도 run action을 노출하지 않는다.
- `build_diagnosis_template()`과 `ResearchService.diagnosis_template()`이 exact terminal,
  Proposal/scope, artifact full set, Decision observation을 read-only로 채운다. 네 agent
  field는 invalid `REPLACE_ME` sentinel이라 미작성 body는 `diagnose`를 통과할 수 없다.
- CLI는 opt-in `agent-context --schema-version 3`과 `diagnosis-template
  [--experiment ID]`를 제공한다. Context v2/default snapshot/token/branch conclusion schema는
  변경하지 않았다.
- `examples/m1e_context_v3_demo.py`는 temp project에서
  context→template→fill→diagnose→refresh를 실행하고 종료 시 전체를 삭제한다.
- Product checkpoint `7fcfd10`의 source delta는 pre-spec `38446f1` 대비
  `+365/-8`; 전체 commit은 11 files `+686/-8`이다. 예산 1,200 lines 이하를
  유지했다.

### 05.6.4 Milestone progress claim ★

**영향 받은 M_i.j**: `M1-E`

**라벨**: `ADVANCE`

**Prerequisite gate state**: M1-D `closed` at `f570f92`; parent M1은 open.

| M1-E conjunct | 이전 | 이번 phase 후 | 근거 |
|---|---|---|---|
| context v3에 generation/budget/class/pending/frontier 포함 | ❌ | ✅ | vertical `4/4`; exact `ScientificState.to_dict()`; cold writer diff 0 |
| v1 event/context v2/branch conclusion v1 무변환 replay | 부분 | 오픈 | bounded v2/token tests는 PASS했지만 release fixture 전체는 미측정 |
| v2 tokenless write legacy 격리/핵심 gate | ❌ | ❌ | 이 slice의 명시적 제외 |
| managed v0.2→v0.3 skill upgrade/rollback | ❌ | ❌ | 이 slice의 명시적 제외 |
| docs/version 0.3.0 + full suite | ❌ | ❌ | version은 0.2.0; full release regression 미수행 |

따라서 M1-E는 `1/5 ADVANCE`이고 `CLOSE`가 아니다. Parent M1·M2 prerequisite를
건너뛰지 않았다.

### 05.6.5 End-state vision update ★

**Delta classification**: `구체화·검증`

- **Before snapshot**: M1-D state는 replay 가능했지만 context v2에 pending,
  ClassState, semantic/retry frontier가 없고 exact Diagnosis authoring을 수작업했다.
- **After snapshot**: opt-in v3가 같은 reducer object를 직접 노출하고, template이
  kernel field를 채운 뒤 four agent judgment field를 모두 교체해야 append가 가능하다.
- **Touched end-state**: pipeline §8.4 Context `✗→△`; Stage 3 Study inference와
  M1-D meaning은 변경 없음.
- **Preserved gaps**: Program Claim/retrieval reason, autonomous FSM, unseen NS6,
  default v3/legacy/upgrade/release, live migration, product multi-agent.
- **Vision loosening**: 없음.

### 05.6.6 Intent-execution alignment ★

**라벨**: `MATCH`

- **Intent summary**: 사용자가 먼저 실행할 수 있는
  context→template→diagnose→refresh 한 경로를 만든다.
- **Execution summary**: opt-in v3, exact fail-closed template, public CLI, disposable
  temp-project demo와 compatibility/no-write tests만 구현했다.
- **Match basis**: §05.2 six acceptance를 약화하지 않았고 M1-E release,
  외부 project writes, autonomous/multi-agent를 추가 청구하지 않았다.

### 05.6.7 Claim mode and chronology ★

**라벨**: `CONFIRMATORY`

| artifact | exact identity | time / role |
|---|---|---|
| pre-spec | `38446f18b2910b35df6819d7d725cf17c08bde22` | `2026-08-11T03:31:58+09:00`; tree `dace995951ca1c9316454e57d29fcd4248b45ab8`; product/test change 0 |
| first result-bearing checkpoint | `7fcfd100f7aa3a37900d6ac1a554d30bc8c62677` | `2026-08-11T03:48:51+09:00`; parent exact pre-spec; tree `41f4fb01bd3145007a6fe0ca5d6c21a99c84903c` |

Pre-spec가 first product/test commit보다 16분 53초 앞서고 frozen acceptance 1~6은
변경되지 않았다. Final focused evidence는 implementation checkpoint를 대상으로
`127 passed, 23 subtests`, ruff/ty/diff PASS이다. 이 CONFIRMATORY 라벨은
vertical-slice acceptance에만 적용하며 M1-E/v0.3 release나 NS6 효과를 청구하지 않는다.

### 05.6.8 Requirement-result divergence ★

**Accepted classification**: `RESULT-INVALID` (first harness setup measurement only) →
corrected remeasurement PASS.

- First red run 4건은 missing API에 도달하기 전 test helper의
  `ResearchService.replay()`가 frozen synthetic baseline에 product provenance 검증을 적용해
  실패한 setup result였다. Product criterion의 성공/실패를 관찰하지 못했으므로
  final evidence에서 제외한다.
- Helper를 projection-only fixture setup으로 교정한 뒤 같은 event history와 같은
  acceptance를 실행했다. Product에서는 cold v3가 temp replay로 no-write를 직접
  만족하도록 구현했다.
- `REQUIREMENT-WRONG` 또는 `GENUINE-FINDING`은 없으며 claim 강등/소급 변경도 없다.

### 05.6.9 Residual issues ★

- V3 read-only snapshot은 현 preview에서 history O(n) temp replay이다.
- Context v2가 아직 default이고 v3는 recovery를 쓰지 않으므로 stale/incomplete run은
  후속 command의 기존 recovery에서 token refresh를 요구할 수 있다.
- Demo는 frozen synthetic temp project이지 외부 세 project live pilot이 아니다.
- M1-E 남은 4 conjunct, full suite, v0.3 release, NS5/NS6, Program Memory는 전부 open이다.
- M chain 정의/의미 변경이 없으므로 Rule 9 retrospective trigger는 없다.

## 05.7 Verification result

| evidence | result |
|---|---|
| frozen vertical slice | `4 passed` |
| final context v2/token/M1-D/skill compatibility bundle | `127 passed, 23 subtests` |
| disposable example | PASS; pending `1→0`, ClassState/retry frontier visible |
| static | ruff PASS, offline ty PASS, `git diff --check` PASS |
| writer/authority | cold v3/template project event+projection byte diff 0; temp projection only; authority null |

Exact compatibility command (workspace root `/Users/bbangjo/research-os`, Python 3.12 venv):

```bash
.venv/bin/python -m pytest -q \
  tests/test_m1e_usable_context.py \
  tests/test_agent_interface.py \
  tests/test_agent_scientific_control.py \
  tests/test_cli_extensions.py \
  tests/test_m1d_diagnoses.py \
  tests/test_m1d_state.py \
  tests/test_m1d_service_cli.py \
  tests/test_skill_policy.py
```

Suite list는 위 여덟 파일 전체이며 결과는 `127 passed, 23 subtests passed in
70.89s`다. Static command은 `.venv/bin/ruff check` on changed source/test/example,
`uvx --offline ty check src`, `git diff --check`이다.

Acceptance 1~6은 모두 PASS했다. Existing context v2의 recovery/outcome-finding
semantics은 그대로두되, opt-in v3는 recovery를 실행하지 않고 canonical snapshot을
temp projection에만 replay한다. Cold v3 호출 전후 project event/projection bytes가 exact
일치했고 temp directory는 호출 종료 시 삭제됐다. 현 preview의 비용은
history에 대한 O(n) temp replay이며, 성능 최적화는 정확성/무작성 후속이다.

## 05.8 Progress classification

- **End-state delta**: `구체화·검증`. Pipeline Context를 `✗→△`로 진전시킨다.
- **Milestone**: M1-E first conjunct `1/5`; M1-E/M1은 계속 open.
- **Intent alignment**: `MATCH`. Context v3와 authoring/example만 구현했고 legacy/
  upgrade/version/full release를 close로 청구하지 않는다.
- **Claim mode**: `CONFIRMATORY`; exact chronology는 §05.6.7.
- **Requirement-result divergence**: first setup measurement `RESULT-INVALID` 제외 후
  corrected remeasurement PASS; 상세는 §05.6.8.
- **External boundary**: 세 project read-only, live pilot/migration 없음, multi-agent 없음.

## 05.9 Next action

Product/test는 `7fcfd10`에 checkpointed됐고 independent 7-pass progress audit도
Severity-1 0으로 PASS했다. 다음은 M1-E의 남은 tokenless v2 write legacy isolation,
managed v0.2→v0.3 skill upgrade/rollback, docs/version 0.3.0과 full suite를 작은
단위로 진행한다.

## 05.10 Corrected remeasurement plan ★

1. **Excluded result**: first harness setup 4 FAIL은 product surface를 관찰하지 못한
   `RESULT-INVALID`로 final numerator/denominator에서 제외한다.
2. **Frozen requirement**: §05.2 acceptance 1~6, source/test/doc 1,200-line cap,
   opt-in v3/default-v2 경계를 변경하지 않는다.
3. **Correction boundary**: synthetic canonical event는 그대로두고 test setup만
   service-level baseline revalidation에서 rebuildable projection materialization으로 바꿘다.
4. **Remeasurement**: vertical 4 tests로 exact state/template/no-write/fill E2E를 측정하고,
   §05.7의 exact eight-file command로 v2/token/M1-D/skill compatibility를 재측정한다.
5. **Reject condition**: any pending/class/frontier mismatch, unedited sentinel accept,
   project writer diff, v2 shape drift, authority non-null, focused failure면 RESULT-INVALID를
   유지하고 ADVANCE/CONFIRMATORY 청구를 철회한다.
6. **Completion**: corrected vertical `4/4`, combined `127+23`, demo/ruff/ty/diff PASS로
   remeasurement를 완료했다.
