# §07 — M2-A ProgramManifest·ProgramLog (2026-08-11)

> Status: **ADVANCE — implementation evidence 4/4; critic and progress audit pending**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §2
> Previous phase: [§06](06-2026-08-11-m1-e-release-close.md)
> Pipeline impact: [`docs/research-os-pipeline.md`](../research-os-pipeline.md) §4, §8~§10
> Active milestone: `M2-A` at candidate `4/4`; `CLOSE` requires critic and audit PASS

## 07.0 TL;DR

M1/v0.3의 stable scientific identities를 소비하는 별도 Program memory truth boundary를 구현했다.
ProgramManifest는 StudyContract·generation·evaluation scope·seal을 exact bind하고, ProgramLog는
잠긴 project prefix replay로 Diagnosis와 ClassState가 일치할 때만 origin을 append한다. Frozen
`19/19`, focused `22/22`, fresh full `635+115`가 PASS했다. Claim·relation·retrieval은 M2-B/C에
남으며 critic·audit 전에는 candidate `4/4`만 청구한다.

## 07.1 Scope, anchors, and authority

- Target §북극성: NS1 regression, NS3의 남은 Claim 객체를 가능하게 하는 identity substrate,
  NS4의 canonical program memory boundary. NS3은 Claim 미구현이므로 이 phase만으로 `4/4`가 아니다.
- Target end-state: pipeline §8.4 `Program memory`를 project-bound free-form Finding에서
  `ProgramManifest + ProgramLog + rebuildable ProgramProjection`이라는 별도 truth boundary로 구체화한다.
- Target milestone: pipeline §9.4의 M2-A 네 AND-conjunct. 하나라도 미달이면 `ADVANCE`; 모두
  independent reproduction과 critic/audit를 통과할 때만 `CLOSE`한다.
- Authority: manifest, origin, event, projection의 `authorized_action`은 literal null이다.
  merge/deploy/trade/live operation은 존재하지 않는다.
- External boundary: `crypto-new`, `manager`, `BinancePredictionStrategy`를 읽거나 쓰지 않는다.
  세 프로젝트 read-only compatibility는 M2-D, live migration/pilot은 v0.5 이후다.
- Product multi-agent는 구현하지 않는다. 사용자 승인대로 NS6 통과 이후다.

## 07.2 Frozen schemas and identities

### A1 — ProgramManifest v1

`ProgramManifest`의 exact root는 `program_manifest_schema_version`, `program_id`, `bindings`,
`authorized_action`이다. 각 binding은 다음 M1 identity를 exact bind한다.

1. project ID와 `science_state_schema_version=1`;
2. StudyContract schema version과 canonical digest;
3. generation ID;
4. evaluation-scope schema version, exact `{id, role, manifest_digest}` body와
   `sha256_json({evaluation_scope_schema_version, evaluation_scope})` digest;
5. evaluation-seal digest와 compatibility digest;
6. literal null authority.

Binding은 `(project_id, generation_id, evaluation_scope.id)`로 정렬되고 unique해야 한다.
Unknown/missing/extra key, bool-as-int version, invalid digest/ID, duplicate binding, non-null authority,
binding과 project replay state의 불일치는 program event와 projection을 0건 변경하고 거절한다.

### A2 — ProgramEvent/ProgramLog v1

ProgramEvent canonical envelope는 project Event의 `project_id`가 아니라 다음 exact key를 가진다:
`version`, `sequence`, `program_id`, `event_id`, `event_type`, `occurred_at`, `payload`,
`prev_hash`, `hash`. 첫 event는 `research.program.initialized.v1`, 이후 M2-A event는
`research.program.origin_linked.v1`뿐이다.

- ProgramLog는 별도 path와 explicit `program_id` envelope를 사용한다. Project Event envelope,
  project core event type, mixed program ID는 canonical parse 단계에서 거절한다.
- Writer는 exclusive lock 아래 complete prefix, sequence, duplicate event ID, hash chain을 다시
  확인하고 body fsync 뒤 newline commit marker를 쓴다.
- `expected_head=(sequence, hash)`는 같은 locked region에서 비교한다. 경쟁자는 정확히 하나만
  append하고 stale writer는 `PROGRAM_HEAD_MISMATCH` no-write다.
- Unterminated tail만 recovery할 수 있고 committed corruption은 숨기지 않는다.

### A3 — OriginEvidenceRef v1

Origin ref는 project ID/head, generation/scope, Diagnosis event sequence/hash/id/digest,
derived ClassState id/digest, null authority를 포함하며 이 exact body에서 `origin_id`와 digest를
계산한다. Append는 다음 순서로만 허용된다.

1. project EventLog를 shared lock으로 잡고 complete stream을 verify한다.
2. ref의 head가 current project head와 exact 일치하는지 확인한다.
3. 해당 head prefix를 `reduce_scientific_state`로 replay한다.
4. manifest binding이 contract/generation/scope/seal identity와 exact 일치하는지 확인한다.
5. Diagnosis event identity·Diagnosis ID/digest와 그 head의 derived ClassState ID/digest를 대조한다.
6. project lock을 유지한 채 ProgramLog exclusive append를 수행한다.

단순 ID 존재, latest projection lookup, caller assertion은 evidence가 아니다. Future/stale head,
forged event/hash/digest, 다른 generation/scope/class state, duplicate origin은 no-write다.

### A4 — ProgramProjection v1 and lock order

ProgramProjection은 canonical ProgramLog에서만 재생성 가능한 비권위 cache다. Snapshot은 manifest
digest, program head, ordered origin links, null authority를 materialize한다. Missing, noncanonical,
partial, corrupt, stale projection은 ProgramLog를 locked-read한 결과로 atomic rebuild한다. 반대로
ProgramLog corruption은 projection을 신뢰해 통과시키지 않는다.

전역 lock rank는 `project EventLog shared → ProgramLog exclusive/shared → ProgramProjection`이다.
Projection을 잡은 채 project/program log를 역순으로 요청하는 product path는 만들지 않는다.
Barrier-controlled thread tests가 project append 대 origin append와 same-program-head 경쟁을
timeout 없이 종료하고 정확한 winner/no-write loser를 관찰해야 한다.

## 07.3 Frozen machine-readable cases

`tests/fixtures/program_memory/v1/manifest.json`의 case ID·operation·expected는 이 phase의 고정
분모다. Observer/test는 ID나 expected를 dispatch 입력으로 사용하지 않고 operation별 실제 path를
실행한 뒤 canonical exact equality로 비교한다. Frozen counts:

- manifest boundary 5 cases;
- origin exactness 5 cases;
- log/head/namespace 4 cases;
- projection/recovery/lock order 5 cases;
- total 19 cases, skip/fallback 0.

Fixture input은 M1-D의 `supported` canonical history이고 raw source digest 세 개와 M1 identity
기댓값을 manifest에 고정한다. Frozen valid hashes는 manifest
`3065d242…b1a4`, origin `69c5c832…0a4e`, initialized event `ff53a7dd…f399`, linked event
`5112d50d…0f0b`다.

## 07.4 Bounded implementation plan

- `src/research_os/memory/program.py`: strict dataclasses/parsers, dedicated ProgramEvent envelope,
  ProgramLog, ProgramProjection, ProgramStore와 project-prefix replay validator.
- `src/research_os/errors.py`, `memory/__init__.py`: stable error/export surface만 추가한다.
- `tests/test_m2a_program_memory.py`: frozen 19-case dispatcher, exact bytes/hash, corruption,
  barrier concurrency, no-write observation.
- M2-B의 Claim schema/relations, M2-C retrieval/Context, CLI/service global discovery, legacy import,
  external project fixture는 추가하지 않는다.
- Frozen corrected cap: product `<=1,650` added lines, tests+fixture `<=1,000`, docs `<=450`, total `<=2,750`.
  초과 시 acceptance를 사후 완화하지 않고 PIVOT/EXPLORATORY로 기록한다.
- Pre-result cap correction: dedicated `program_id` canonical envelope를 제공하면서 EventLog의
  hardened descriptor/recovery mechanics만 재사용하고, exact project-prefix validator와 atomic
  projection을 한 module에 둔 product draft가 1,596 added lines임을 LOC 측정에서 확인했다.
  테스트 결과를 실행하기 전에 product cap만 `1,300→1,650`으로 고쳤다. Frozen 19 cases,
  schema/digest recipe, public error, four conjunct, total cap은 바꾸지 않는다.
- Post-result execution PIVOT: 첫 invalid full이 드러낸 historical v0.3 verifier와 상호 재귀
  regression observer를 고치면서 현재 Cycle 07 added LOC가 product+release harness `1,635`,
  tests+fixture `946`, phase+critic docs `276`, total `2,857`이 됐다. 세 category cap은 각각
  `1,650/1,000/450` 안이지만 total `2,750`을 107줄 초과했다. 이 사실은 direct harness
  `11/11`과 corrected original nodes `4/4` 결과 뒤 확인했으므로 사전 고정으로 소급하지 않는다.
  Historical harness correction과 total-cap 실행 의도는 `EXPLORATORY`로 분리하고 total cap만
  `<=3,100`으로 PIVOT한다. M2-A의 frozen schema·19 cases·4 conjunct·error/digest/race 기준과 각
  category cap은 변경하지 않으며, 이 checkpoint 뒤 fresh full만 close 분자로 사용한다.

## 07.5 Verification plan

1. Frozen manifest integrity와 19 literal case IDs를 각각 pytest node로 실행한다.
2. Focused module 전체와 existing EventLog/storage/scientific-state compatibility를 실행한다.
3. 전체 Python 3.12 suite 1회, ruff, ty, `git diff --check`를 M2-A close 전에 실행한다.
4. Recursive authority scan은 M2-A 새 event/ref/projection까지 non-null 0을 요구한다.
5. Independent critic Q1~Q8 DIRECT/LIMITATION 응답 뒤 PASS, 이어 seven-pass auditor PASS가 필요하다.

## 07.6 Milestone and claim discipline

### 07.6.4 M2-A milestone position

**영향 받은 M_i.j**: `M2-A`

**현재 라벨**: `ADVANCE (candidate 4/4; critic/audit pending)`

| Frozen conjunct | 결과 | Reproducible evidence |
|---|---|---|
| Manifest binds stable M1 identities | PASS | frozen manifest cases 1~5; invalid field/version/duplicate/authority mutation `0` |
| Exact Diagnosis/ClassState origin | PASS | cases 6~10; locked prefix replay, forged/scope/stale rejection |
| hash-chain/head precondition | PASS | cases 11~14; distinct envelope, stale loser delta `0`, corruption fail-closed |
| projection recovery + lock order | PASS | cases 15~19; missing/corrupt/stale rebuild and two barrier races |

공통 재현은 `pytest -q tests/test_m2a_program_memory.py`의 `22 passed`와 literal binding+frozen
case command의 `20 passed`다. Product checkpoint는 `b10e1b4`와 export fix `5613591`; prerequisite
M1은 closed이며 gate bypass는 없다.

### 07.6.5 Expected end-state delta

- Before: program memory는 project-bound `GLOBAL` Finding뿐이며 cross-project scientific origin을
  검증하는 별도 canonical stream이 없다.
- After if 4/4: ProgramManifest와 ProgramLog가 별도 canonical truth가 되고 project Diagnosis/
  ClassState prefix를 exact provenance로 link하며 projection은 파괴 후 재구축 가능하다.
- Still missing: conditional Claim semantics, relation reducer, retrieval quality, Context token,
  knowledge disposition, autonomous loop와 unseen benchmark.
- Pipeline §8.2/§8.3의 행동과 제외 범위는 축소하지 않는다.

### 07.6.6 Intent-execution target

Target label은 `PIVOT`: §07.4의 product LOC cap은 첫 test 결과 전에 `1,300→1,650`으로
확대했고, 결과 뒤 발견한 historical harness correction을 포함하기 위해 total cap은
`2,750→3,100`으로 별도 PIVOT했다. Frozen schema, 19 cases, four conjunct와 category cap은
동일하다. 두 correction은 core §2 Decision chain에 동기화한다. Sample, threshold, data source,
semantic scope가 바뀌면 별도 PIVOT entry를 추가한다.

### 07.6.7 Claim mode target

Target은 `MIXED`다. M2-A schema·identity·19-case 기능 분모는 이 문서, critic 질문,
machine-readable manifest의 local checkpoint가 첫 product/test result-bearing commit보다 앞서므로
`CONFIRMATORY`다. 첫 invalid full 뒤 추가한 historical release/recursion harness correction과
post-result total-cap PIVOT은 `EXPLORATORY`다. Expected, denominator, error code, digest recipe,
race winner rule을 결과 뒤 바꾸면 해당 기능 결과는 `RESULT-INVALID`다.

### 07.6.8 Requirement-result divergence

첫 full은 `4 failed, 627 passed, 115 subtests passed in 2507.69s`였다. 네 failure는
`test_release_verifier`의 product-tree check 한 건과 이를 재귀 실행한 M1-C/M1-D 세 건이다.
M2-A focused `22/22`, adjacent `78+4`, ruff/ty는 green이고 traceback의 root cause는 v0.3
historical verifier가 현재 tree를 release commit `e120292`의 37-file seal과 비교한 것이다.
분류는 **RESULT-INVALID / HARNESS**다. v0.3 manifest/tree digest를 현재 M2 tree로 덮어쓰지 않는다.

Fresh-result 전 correction acceptance를 다음과 같이 고정한다. v0.3 static gate는 durable receipt의
schema/kind/release/result, full implementation commit, manifest와 receipt의 exact tree equality,
`git` object 존재, 그 commit에서 재계산한 Python tree의 `37 / 52cbf8…277d` equality를 모두 요구한다.
현재 tree가 달라도 historical static check는 sealed commit으로 PASS하지만, full v0.3 `verify()`는
HEAD가 sealed commit과 다르면 새 receipt를 재발행하지 못하고 fail-closed한다. Manifest와 existing
receipt bytes, M2-A 19-case denominator, four conjunct는 변경하지 않는다. 먼저 direct static test와
네 실패 node를 재현하고, 그 뒤 fresh full만 close 분자로 사용한다.

네 실패 node 재현은 첫 `m1c-regression-floor`가 PASS한 뒤에도 M1-C와 M1-D regression observer가
서로를 경유해 동일 full suite를 최대 네 단계로 중첩했고, `1 passed in 1226.29s` 시점에 다음
중복 실행 전에 중단했다. 이 partial 결과도 **RESULT-INVALID / HARNESS**이며 close 분자가 아니다.
속도 correction의 fresh-result 전 acceptance는 다음과 같다. 두 observer가 child pytest를 실행할
때 `test_m1c_manifest_oracle.py`와 `test_m1d_manifest_oracle.py`를 모두 exact 한 번씩 제외하고,
top-level full suite에서는 두 파일을 그대로 실행한다. 따라서 child는 자기참조 meta-oracle만
제외하고 제품·일반 회귀 전체를 실행하며, 각 observer의 floor count·ruff·ty·diff 및 fail-closed
판정은 유지한다. 두 direct harness test가 child command/environment의 양쪽 ignore를 증명해야 하며,
environment flag로 결과를 skip하거나 합성 PASS하지 않는다. 이 correction 뒤 네 원 failure node와
fresh top-level full을 다시 실행한다.

Correction 결과는 historical verifier/harness direct `11 passed`, 원 failure nodes
`4 passed in 848.50s`다. Final close numerator는 checkpoint `9c76aa3`의 Python 3.12 fresh full
`635 passed, 115 subtests passed in 1193.85s`; prior invalid/partial 결과는 포함하지 않는다.
`ruff check src tests scripts`, `ty check src`, `git diff --check`가 PASS했고 manifest·origin·두
ProgramEvent·ProgramSnapshot recursive scan의 `authorized_action` 12개는 non-null `0`이다.

## 07.7 Expected north-star movement

- NS1: 새 program surface가 기존 EventLog/M1 compatibility와 authority를 약화하지 않을 때 유지.
- NS3: Claim은 여전히 없으므로 `3/4` 유지; M2-B를 가능하게 하는 provenance substrate만 생긴다.
- NS4: M2-A alone은 retrieval target을 측정하지 않으므로 `0/4` 유지. ProgramLog boundary는
  denominator 밖의 prerequisite evidence로만 기록한다.

## 07.8 Expected pipeline mapping impact

Program memory stage는 `✗`에서 곧바로 `○`가 아니다. M2-A 4/4이면 separate truth boundary가 생겨
`△`로만 이동할 후보가 된다. Claim/retrieval이 없으면 더 높은 등급을 청구하지 않는다.

## 07.9 Pessimistic pre-score

별도 log가 생겨도 failure knowledge를 재사용하는 시스템은 아니다. Origin link가 정확해도 Claim
quality나 retrieval relevance는 측정하지 않는다. EventLog와 유사한 storage mechanics를 재사용하는
만큼 별도 envelope·mixed-stream rejection이 없으면 project-log proxy에 불과하다는 critic 가정을 둔다.

## 07.10 Next action

Saved critic Q1~Q8을 independent verify mode로 판정하고, PASS 뒤 status/pipeline 동기화와 seven-pass
progress audit를 수행한다. 둘 다 PASS할 때만 M2-A를 CLOSE하고 M2-B pre-spec으로 이동한다.
