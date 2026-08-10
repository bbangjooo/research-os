# §05 — M1-E usable Context v3 vertical slice (2026-08-11)

> Status: **PRE-SPEC FROZEN — implementation pending**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §2
> Prerequisite: M1-D checkpoint `f570f92`, five conjunct `5/5`, independent audit PASS
> Claim mode: **CONFIRMATORY candidate** for this fresh vertical-slice acceptance only

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
