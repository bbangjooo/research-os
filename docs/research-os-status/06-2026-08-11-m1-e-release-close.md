# §06 — M1-E v0.3 release close (2026-08-11)

> Status: **PROGRESS AUDIT FAIL — installer executable correction pre-specified**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §2
> Previous phase: [§05](05-2026-08-11-m1-e-usable-context.md)
> Pipeline impact: [`docs/research-os-pipeline.md`](../research-os-pipeline.md) §5, §7~§10
> Active milestone: `M1-E` at `4/5`; installer matrix correction active

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
- `crypto-new`, `manager`, `BinancePredictionStrategy`는 read-only 경계만 유지한다.
  Release verifier가 각 `.research-os` control tree를 pre/post byte snapshot으로 읽지만 writer
  delta는 0이고 live pilot/migration은 v0.5 이후다.
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

`tests/fixtures/releases/v0.3.0/manifest.json`의 7개 structured case 전부를 실행한다.
각 case는 observer, 실제 source case/path, expected public code와 reject event/budget delta를
직접 bind하며, ID 집합이나 code 집합만 비교해서는 PASS할 수 없다.

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
5. 위 네 항목과 release manifest, recursive authority scan, 외부 프로젝트 read-only/no-live
   경계, 제품 multi-agent 부재를 `scripts/verify_release.py` 한 명령이 fail-closed로 실행한다.
   일부 command를 건너뛰는 release mode는 제공하지 않으며 하나라도 실패하면 receipt를
   발행하지 않는다.

## 06.3 Bounded implementation plan

- `service.py`, `cli.py`: default schema만 3으로 올리고 explicit v2 seam을 유지한다.
- `agent_install.py`: exact known-managed-release classifier와 release-aware recovery label/
  report를 기존 transaction engine에 추가한다.
- Focused release test 하나와 installer upgrade test를 보강한다. 거대한 oracle,
  graph reducer, 새 event schema는 만들지 않는다.
- Frozen change cap: product+tests `<=650` added lines, fixture+docs `<=500` added lines,
  total `<=1,150` added lines. 초과하면 M1-E close를 중단하고 PIVOT 기록을 남긴다.
- Second audit에서 실제 filesystem/policy binding 요구가 드러나 original total이 `1,140`에
  도달했으므로 `PIVOT`: correction cap을 product+tests `<=700`, fixture+docs `<=600`, total
  `<=1,350`으로 재동결한다. A1~A5 semantics/threshold는 바꾸지 않는다.
- Progress audit의 structured installer six-case binding은 pre-implementation tracked total을
  `1,344`까지 올렸으므로 두 번째 `PIVOT`: product+tests `<=800`, fixture+docs+README `<=700`,
  release tooling `<=350`, total `<=1,600`으로 재동결한다. A1~A5 semantics, six-case denominator,
  public behavior와 release threshold는 바꾸지 않는다.

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

### 06.6.1 Implementation result and checkpoints

- Controlling corrected pre-spec: `3ca21156f815805f54005eb790b2bf31ceaf48f6`
  (`2026-08-11T04:11:43+09:00`).
- First result-bearing product checkpoint: `d1499b38749c570961c1e36c0a9d090ae80168d0`
  (`2026-08-11T04:22:18+09:00`). Context v3 default, exact managed 0.2
  classifier/transaction report, version/docs/tests를 구현했다.
- Result-triggered test-only correction: `888cd9610e16c4fb610d5a5b3f5b43b40283cc00`
  (`2026-08-11T05:09:53+09:00`). Frozen Context v2 compatibility observer가 새
  default v3를 암묵 호출하던 두 곳을 explicit `schema_version=2`로 고쳤다. 제품,
  fixture denominator, public code, acceptance는 바꾸지 않았다.
- Exact range `27423b1..58b731e`의 added lines는 product+tests `565`,
  fixture+docs+README `388`, release tooling `304`, metadata `2`, total `1,259`다.
  확인 명령은 `git diff --numstat 27423b1..58b731e`이며 PIVOT total cap `1,350` 이하이다.

### 06.6.2 Verification evidence

| Evidence | Corrected result | 판정 |
|---|---:|---|
| Release/default/v2/tokenless/installer focused bundle | fresh executable binding + authority bundle `7 PASS` | PASS |
| Scientific agent compatibility | `17 passed` | PASS |
| Frozen tokenless boundary | structured `7/7`; case-level observer/source/path/code/event+budget delta exact | PASS |
| Frozen installer matrix | 기존 test names는 green이나 manifest case ID가 실행 outcome에 미결합 | **RESULT-INVALID / 0/1** |
| Base suite without recursive M1-C/M1-D meta-oracles (diagnostic) | `508 passed, 115 subtests passed` | PASS |
| Corrected full Python 3.12 suite | single verifier `602 passed, 115 subtests passed` | PASS |
| Static checks | single verifier ruff/ty/diff/clean-tree | PASS |
| Wheel/install | installed metadata `0.3.0`; packaged skill; wheel SHA-256 `cdc451…2ad1` | PASS |
| Authority/live boundary | recursive non-null `0`; three external `.research-os` byte snapshots pre/post exact; reviewed product Python tree `37` files / `52cbf8…277d`; product multi-agent false | PASS |

### 06.6.3 Invalid and diagnostic runs

- 첫 full run은 `3 failed, 594 passed, 115 subtests passed`이므로 release evidence에서
  제외하고 **RESULT-INVALID**로 기록한다. Product/base suite는 `508+115`로 green이었지만
  M1-C/M1-D legacy compatibility observer 두 곳이 Context v2를 명시하지 않아 default v3의
  additive keys를 v2 drift로 오판했다.
- Wheel install 첫 probe는 `install_agent_skill(targets=...)`라는 존재하지 않는 keyword를
  사용해 **RESULT-INVALID / HARNESS**다. 동일 wheel을 documented `target="codex"` API로
  즉시 재실행한 결과 install/manifest/resource가 PASS했다.
- Focused compatibility 재실행 한 번은 동일 meta-oracle이 다시 4단 nested full suite를
  시작한 것을 확인한 뒤 release evidence가 아니므로 `KeyboardInterrupt`로 중단했다.
  판정에는 사용하지 않는다.
- 최초 focused release harness의 fixture group key와 expected code field 오기는 각각
  `cases→gate_cases`, `rejection_code→error_code`로 기존 frozen manifest를 읽도록만 고쳤다.
  Case 수·ID·expected code는 바꾸지 않았고 이전 출력은 **RESULT-INVALID / HARNESS**다.

### 06.6.4 M1-E and parent M1 conjunction

| M1-E frozen conjunct | Direct evidence | 상태 |
|---|---|---|
| Context v3 scientific state | default v3 = explicit v3; explicit v2 exact; cold no-write; focused PASS | PASS |
| v1 event / Context v2 / branch conclusion v1 compatibility | frozen bytes/digest, explicit v2, snapshot v2, full suite PASS | PASS |
| tokenless v2 legacy boundary | structured `7/7` actual outcomes exact; reject event/budget delta 0 | PASS |
| managed 0.2→0.3 upgrade/rollback | product tests green; manifest six IDs가 실행 outcome에 미결합 | FAIL |
| docs/version 0.3.0 + full release | receipt `58b731e`: `602+115`, exact four-doc/version/product-tree/external snapshots, static, clean tree, wheel/temp install | PASS |

Progress audit가 installer `case_ids`가 어느 executable dispatcher에서도 소비되지 않음을
발견했으므로 기존 `6/6` 청구를 **RESULT-INVALID**로 내렸다. 현재 decision은
**ADVANCE (`4/5`; installer executable correction active)**다. Structured six-case manifest와
ID별 actual outcome, single-verifier receipt가 fresh PASS하기 전에는 M1-E/M1을 `CLOSE`하지 않는다.

### 06.6.5 End-state positioning

- **Context after:** 생략 default v3가 generation/budget/pending Diagnosis/ClassState/frontier를
  제공하고 explicit v2는 frozen 12-key compatibility surface로 남는다. Relevant Claim과
  retrieval reason은 여전히 M2 범위다.
- **Compatibility/authority after:** v1 bytes와 branch conclusion v1/snapshot v2는 무변환이고,
  pre-generation legacy는 opaque다. Byte-exact published 0.2만 recoverable 0.3 upgrade가 가능하며
  drift/unknown/local tree는 no-write다. 모든 연구 surface authority는 null이다.
- 세 외부 프로젝트 live pilot/migration은 수행하지 않았고 v0.5 이후로 유지한다. 제품
  multi-agent도 추가하지 않았으며 NS6 이후 조건을 유지한다.

### 06.6.6 Pipeline MATCH / PIVOT

`MATCH`. Pipeline §9.4의 M1-E 다섯 AND-conjunct, §8.2 행동, §8.3 제외 범위,
§8.4 Context/Compatibility 종착지를 축소하거나 재정의하지 않았다. 새 event schema,
graph reducer, provider SDK, autonomous loop를 추가하지 않았다.

### 06.6.7 Claim mode and chronology

**Claim mode: CONFIRMATORY.** Second-correction pre-spec `ff608af` (`07:22:40+09:00`)이 direct
parent인 implementation `58b731e` (`07:26:14+09:00`)보다 먼저다. Case 수·public code·product
semantics·threshold를 바꾸지 않고, 그 clean implementation commit에서 처음 실행한 single
verifier receipt만 second-correction confirmatory evidence로 사용한다. First-correction
`3eaba21→1aa9c58` receipt는 chronology/history이지 현재 Q2/Q5 분자가 아니다.

`3ca2115` corrected pre-spec의 parent/tree/timestamp는
`27423b1` / `3fb3cac…` / `2026-08-11T04:11:43+09:00`이다. First result-bearing
`d1499b3`의 parent가 exact `3ca2115`이고 timestamp는
`2026-08-11T04:22:18+09:00`이다. 따라서 acceptance와 release manifest가 제품 결과보다
먼저 고정됐다. 후속 `888cd96`은 실패 결과를 보고 compatibility test가 explicit v2를
호출하도록 한 test-only correction이며 §06.6.3의 initial full result를 invalidated했다.

### 06.6.8 Result-invalid discipline

Initial full/harness outputs와 critic이 무효화한 A3/A5 aggregate PASS는 close 분자에서 제외한다.
기존 `597+115`는 regression 실행 사실로만 보존하고 A5 single-gate PASS로 대리하지 않는다.
Second-correction pre-spec 뒤 fresh receipt `58b731e`, `602+115`, executed path와 legacy typed-zero,
authority non-null 0, exact product tree, external control-tree no-write, wheel/install 0.3.0만 현재
A3/A5 close evidence다. First receipt `1aa9c58`은 historical correction evidence로만 보존한다.

### 06.6.9 Residuals and north-star movement

- NS1: full M1/release/authority/legacy evidence를 충족했다.
- NS2: legacy isolation을 더해 M1 target `6/6`이다.
- NS3: M1 target Proposal/Diagnosis/ClassState `3/3`; program Claim이 없어 전체 target은
  여전히 `3/4`다.
- NS5: finite FSM/crash-resume를 만들지 않았으므로 `0/7` 유지다.
- NS6/NS7: unseen learning benchmark와 three-project read-only compatibility는 M3/M2-D에
  남는다.
- Test infrastructure limitation: historical M1-C/M1-D floor가 full suite를 최대 네 겹
  중첩해 최종 run이 42분 59초 걸린다. 증거는 유효하지만 이후 cycle latency 부채다.

## 06.7 Next action

Second-correction receipt를 durable하게 고정한 뒤 progress critic과 independent 7-pass audit를
재실행한다. 둘 다 PASS할 때만 M1-E와 parent M1을 close하고 M2-A를 시작한다.

## 06.8 Pre-result specification correction

- Initial pre-spec `27423b1`은 pending gate의 설명용 code를
  `PENDING_DIAGNOSIS_REQUIRED`로 잘못 적었다. Existing M1-D public contract와 frozen
  transition fixture의 stable code는 `DIAGNOSIS_REQUIRED`다.
- 새 제품/test를 작성하거나 실행하기 전에 manifest와 A3를 기존 code에 맞췄다.
  Case 수 7, no-write 의미, threshold, M1-E conjunct는 변경하지 않았다.
- Corrected pre-spec commit이 이 phase의 controlling pre-spec이다. 이 정정 뒤 code나
  acceptance가 다시 바뀌면 CONFIRMATORY close를 금지한다.

## 06.9 Independent critic FAIL and correction pre-spec

- Independent critic verdict: Q1/Q2/Q5/Q8 FAIL, Q3/Q4/Q6/Q7 PASS.
- Q1/Q8의 문서 결함은 §06.6.4의 explicit `ADVANCE`와 §06.6.7의 explicit claim-mode
  label로 바로잡았다.
- Q2는 기존 manifest가 ID/code 집합만 가졌고 네 transition row만 간접 참조했으므로 A3
  PASS를 무효화했다. 새 manifest는 일곱 case 각각의 observer/source/path/expected code와
  event·budget no-write를 구조화한다.
- Q5는 개별 수동 command를 한 표에 모은 것을 단일 release gate로 잘못 청구했으므로 A5
  PASS를 무효화했다. 새 verifier는 version/docs/full thresholds/manifest/recursive authority/
  static/wheel/temp install/policy boundary를 한 fail-closed command로 묶는다.
- 이 section과 structured manifest는 implementation보다 먼저 `3eaba21`에 고정됐다. First
  verifier가 `1aa9c58`에서 PASS했지만 그 receipt는 second re-audit 뒤 historical evidence로
  내려갔고 durable receipt는 second-correction 결과로 교체됐다.
- Second re-audit verdict는 Q1/Q3/Q4/Q6/Q7/Q8 PASS, Q2/Q5 FAIL이다. `path`가 dispatcher에
  미소비였고 legacy typed-object 0을 직접 노출하지 않았으며 docs exact version, 실제 external
  filesystem no-write, equivalent multi-agent drift를 keyword보다 강하게 막지 못했다. 위 manifest
  fields와 PIVOT cap을 다음 implementation/result보다 먼저 local checkpoint에 고정한다.
- Second-correction pre-spec `ff608af` 뒤 implementation `58b731e`가 manifest `path`와 실제
  executed operation을 exact bind하고 legacy Proposal/Diagnosis/ClassState/typed registration
  count `0`을 직접 비교한다. Single verifier는 four docs exact `0.3.0`, reviewed product Python
  tree `37`/`52cbf8…277d`, 세 sibling project `.research-os`의 pre/post exact byte snapshot을
  manifest에서 소비한다. Clean `58b731e`의 fresh verifier는 `602+115`, authority `0`, wheel
  `cdc451…2ad1`로 PASS했고 durable receipt를 교체했다. Independent re-audit은 아직 pending이다.
- Independent re-audit은 Q1~Q5/Q7/Q8과 Q2/Q5 defect closure를 PASS했지만 Q6 문서 두 곳의
  stale “external access 0/read 0” 표현을 FAIL했다. 실제 verifier 정책은 처음부터 read-only
  snapshot + writer delta 0이므로 acceptance/product/result는 바꾸지 않고 위 scope와 critic
  response를 그 사실에 맞게 정정했다. 이 문서 correction 뒤 strict re-audit은 pending이다.
- Strict Q1~Q8 re-audit은 `f379c4c`에서 PASS했다. 후속 independent progress audit은 Schema와
  Q2/Q5 policy seals를 인정했지만 Reproducibility에서 `managed_skill_upgrade.case_ids` 미소비를
  Severity-1로 FAIL했다. 기존 installer `6/6`은 close 분자에서 제외한다.
- Correction acceptance는 구현/결과 전에 이 manifest에 고정한다: exactly six structured
  `id/operation/expected` cases, literal six IDs 각각이 별도 pytest node로 실행되고 actual outcome이
  canonical exact match하며, single verifier가 exact six node를 실행해 `case_ids`와 `passed=6`을
  receipt에 기록한다. 일부 ID skip, unknown/fallback dispatch, aggregate test-name 대리는 FAIL이다.
