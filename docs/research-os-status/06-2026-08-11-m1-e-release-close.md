# §06 — M1-E v0.3 release close (2026-08-11)

> Status: **PRE-SPEC FROZEN — implementation not started**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §2
> Previous phase: [§05](05-2026-08-11-m1-e-usable-context.md)
> Pipeline impact: [`docs/research-os-pipeline.md`](../research-os-pipeline.md) §5, §7~§10
> Active milestone: `M1-E` at `1/5`; M1-D prerequisite closed

## 06.0 TL;DR

Cycle 05의 usable preview를 release로 닫기 위해 M1-E의 기존 다섯 AND-conjunct를
그대로 재측정한다. Context v3를 default로 올리되 explicit v2와 v1 evidence는
바꾸지 않고, active v2 generation의 tokenless path가 핵심 gate를 우회하지 못함을
증명하며, published `0.2.0` managed skill만 안전하게 `0.3.0`으로 upgrade/rollback한다.

## 06.1 Scope, anchors, and authority

- Target §북극성: NS1, NS2, NS3. NS5는 수동 UX 개선이므로 `0/7` 유지.
- Target end-state: pipeline §8.4 `Context`, `Compatibility/authority` 구체화·검증.
- Target milestone: `M1-E`의 남은 네 conjunct와 Cycle 05 첫 conjunct 재검증;
  모두 PASS할 때만 `CLOSE`한다.
- M chain 정의·분모·threshold는 변경하지 않는다. Rule 9 trigger 없음.
- `crypto-new`, `manager`, `BinancePredictionStrategy`는 read-only 경계만 유지하고
  이번 phase에서 읽거나 쓰지 않는다. Live pilot/migration은 v0.5 이후다.
- 제품 multi-agent는 추가하지 않는다. 모든 연구 산출물의 `authorized_action`은 null이다.

## 06.2 Frozen acceptance

### A1 — Context v3 release default

1. Service와 CLI의 생략 default가 Context schema 3이고 explicit schema 3과 canonical
   exact match한다.
2. Explicit schema 2는 Cycle 05 builder의 12개 exact top-level key, context-token
   snapshot schema 2, packet cap과 authority contract를 보존한다.
3. Default/explicit v3는 같은 reducer state와 Cycle 05 no-project-write invariant를
   보존한다. Context wrapper version 변경이 token/event identity를 다시 쓰지 않는다.

### A2 — v1/v2 compatibility

1. Frozen v1 event bytes는 size `1053`, SHA-256
   `b35e9d74a64c729ceea3c5ca66303a7f4e14043129d4e4686741c5939cf178d6`
   그대로이며 cold replay/projection meaning이 기존 oracle과 exact match한다.
2. Context v2는 explicit opt-in으로 계속 생성되고 CLI/service canonical equality를
   유지한다.
3. Branch conclusion schema v1과 그 event metadata의 context snapshot schema 2를
   그대로 replay한다. 새 default v3 token으로 작성해도 snapshot binding은 v2다.

### A3 — tokenless v2 legacy boundary

`tests/fixtures/releases/v0.3.0/manifest.json`의 7개 case 전부를 실행한다.

- active v2 generation의 registration은 typed Proposal 없이는 no-write
  `PROPOSAL_REQUIRED`다.
- pending Diagnosis는 tokenless registration, retry, successor를 모두 event/budget
  delta 0의 existing stable `DIAGNOSIS_REQUIRED`로 차단한다.
- closed class와 locked budget은 각각 `HYPOTHESIS_CLASS_CLOSED`,
  `BUDGET_ATTEMPTS_EXCEEDED` no-write다.
- generation 이전 legacy registration은 typed Proposal/Diagnosis/ClassState로 자동
  승격되지 않는다. Active v2 generation 안의 valid tokenless registration은 context
  authority를 주장하지 않지만 exact generation/Proposal/scope와 locked gates를 가진다.

### A4 — managed 0.2.0→0.3.0 upgrade/rollback

1. Recognized input은 source commit `6f36a1b`의 managed 0.2.0 tree뿐이다. 다섯 file
   size/digest와 두 directory set은 frozen release manifest와 exact match해야 한다.
2. Normal install은 prior release를 거절하고 `--upgrade`만 허용한다. 성공 record는
   `from_release=0.2.0`, `to_release=0.3.0`, retained `recovery_backup`을 반환한다.
3. Drifted managed tree, unknown release/manifest, local/unmanaged tree는 writer delta
   0으로 거절한다. 기존 exact unmanifested 0.1.0 upgrade는 회귀 없이 보존한다.
4. Frozen six-case matrix가 happy path, drift/unknown no-write, two-target atomic
   rollback, publish-after-kernel-move interruption recovery를 모두 PASS한다.

### A5 — v0.3.0 release gate

1. `pyproject.toml`, `src/research_os/__init__.py`, `uv.lock`, installed package metadata가
   `0.3.0`으로 exact sync한다.
2. README, architecture, agent usage, packaged skill은 Context v3 default, explicit v2,
   tokenless boundary, known 0.2→0.3 upgrade/recovery를 동일하게 설명한다.
3. Python 3.12 full suite는 collection `>=589`, subtests `>=111`, failure 0이다.
   Release manifest의 모든 case가 PASS하고 recursive `authorized_action` non-null은 0이다.
4. Ruff, offline ty, `git diff --check`, built wheel metadata와 packaged resource test가
   모두 PASS한다.

## 06.3 Bounded implementation plan

- `service.py`, `cli.py`: default schema만 3으로 올리고 explicit v2 seam을 유지한다.
- `agent_install.py`: exact known-managed-release classifier와 release-aware recovery label/
  report를 기존 transaction engine에 추가한다.
- Focused release test 하나와 installer upgrade test를 보강한다. 거대한 oracle,
  graph reducer, 새 event schema는 만들지 않는다.
- Frozen change cap: product+tests `<=650` added lines, fixture+docs `<=500` added lines,
  total `<=1,150` added lines. 초과하면 M1-E close를 중단하고 PIVOT 기록을 남긴다.

## 06.4 Verification plan

1. Focused red/green: release manifest, Context default/v2 parity, tokenless seven-case,
   managed prior upgrade/rollback.
2. Compatibility: Cycle 05 `127+23`, prior installer transaction suite, v1 replay and
   branch conclusion tests.
3. Full: exact Python 3.12 environment에서 전체 pytest 1회.
4. Static/build: ruff, ty, diff check, temp wheel build/metadata/resource inspection.
5. Recursive authority scan은 canonical event/context/result surfaces의 non-null을 센다.

## 06.5 Milestone and claim discipline

- M1-E five conjunct를 §06.6.4에서 각각 독립 evidence로 재기록한다. 하나라도
  미달이면 `ADVANCE` 또는 open이고 `CLOSE`가 아니다.
- Parent M1은 M1-E close, NS1 M1 suite, NS2 `6/6`, NS3 `3/3`, 기존 floor,
  version 0.3.0이 모두 동시에 충족될 때만 close한다.
- Claim mode target은 `CONFIRMATORY`. 이 파일, critic 질문, release manifest가 담긴
  pre-spec commit이 first result-bearing commit보다 먼저여야 한다.
- 결과 노출 뒤 acceptance/denominator/failure matrix를 바꾸면 기존 결과는
  `RESULT-INVALID` 또는 `EXPLORATORY`이며 M1-E close를 금지한다.

## 06.6 Expected system delta

- Before: v3는 opt-in preview, 0.2 managed tree는 0.3 installer에 recognized prior로
  정의되지 않았고 release version은 0.2.0이다.
- After if all gates PASS: default Context가 exact scientific state를 제공하고 explicit
  v2/v1 replay가 보존되며, byte-exact 0.2 install만 recoverable 0.3 upgrade를 할 수 있다.
- NS5 autonomous FSM/crash-resume는 생기지 않으므로 `0/7`; Claim/retrieval은 M2,
  autonomous loop/unseen benchmark는 M3에 그대로 남는다.

## 06.7 Next action

이 pre-spec을 local checkpoint로 고정한 뒤 A1~A5를 변경 없이 구현한다.

## 06.8 Pre-result specification correction

- Initial pre-spec `27423b1`은 pending gate의 설명용 code를
  `PENDING_DIAGNOSIS_REQUIRED`로 잘못 적었다. Existing M1-D public contract와 frozen
  transition fixture의 stable code는 `DIAGNOSIS_REQUIRED`다.
- 새 제품/test를 작성하거나 실행하기 전에 manifest와 A3를 기존 code에 맞췄다.
  Case 수 7, no-write 의미, threshold, M1-E conjunct는 변경하지 않았다.
- Corrected pre-spec commit이 이 phase의 controlling pre-spec이다. 이 정정 뒤 code나
  acceptance가 다시 바뀌면 CONFIRMATORY close를 금지한다.
