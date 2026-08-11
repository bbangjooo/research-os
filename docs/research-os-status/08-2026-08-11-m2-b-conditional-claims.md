# §08 — M2-B Conditional Claim·evidence relations (2026-08-11)

> Status: **CORRECTION — candidate evidence 5/5; critic Attempt 1 FAIL; audit not started**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §2
> Previous phase: [§07](07-2026-08-11-m2-a-program-manifest-log.md)
> Pipeline impact: [`docs/research-os-pipeline.md`](../research-os-pipeline.md) §4, §8~§10
> Active milestone: `M2-B` at candidate `5/5`; CLOSE requires critic and independent audit

## 08.0 TL;DR

M2-A의 exact origin을 자유 텍스트 결론으로 바로 승격하지 않는다. M2-B는 한 Claim을 한
Diagnosis origin, terminal/artifact evidence, hypothesis class, evaluation scope, seal과 compatibility에
exact bind한 immutable `active/observed` 객체로 기록한다. `contested`, `superseded`, `replicated`는
원본 Claim을 수정하지 않고 canonical relation event의 reducer가 파생한다. 이름만 다른 동일
manifest scope, 다른 evaluation seal/compatibility, 같은 origin을 replication으로 포장하는 관계는
no-write로 거절한다.

Implementation checkpoint `529283c`에서 frozen `25/25`, focused+direct `33/33`, M2-A 포함
`55/55`, adjacent `97/97`, fresh full `668 passed, 115 subtests`가 PASS했다. 이 수치는 critic/audit
전 candidate evidence이며 M2-B CLOSE나 v0.4 release를 뜻하지 않는다.

## 08.1 Scope, end state, and authority

- Target §북극성: NS3 Durable learning object의 Claim/관계 conjunct와 NS1 authority regression.
- Target milestone: pipeline §9.4 M2-B의 다섯 AND-conjunct. 한 항목이라도 독립 검증에 실패하면
  `ADVANCE`; 전부 critic과 audit까지 PASS해야 `CLOSE`한다.
- Claim은 evidence가 가리키는 Diagnosis의 의미를 자동 증명하지 않는다. 원문 statement는 bounded
  synthesis assertion이며 초기 maturity는 항상 `observed`다. exact evidence는 출처와 조건을
  증명하고, semantic quality는 relation/replication과 이후 M3 benchmark가 판정한다.
- 모든 Claim, applicability, evidence, relation, derived snapshot의 `authorized_action`은 literal
  null이다. merge/deploy/trade/live operation은 추가하지 않는다.
- 외부 세 프로젝트를 읽거나 쓰지 않는다. read-only compatibility는 M2-D, live pilot/migration은
  v0.5 이후다. 제품 multi-agent는 NS6 이후다.

## 08.2 Frozen Claim v1 contract

### B1 — Claim body and bounded statement

Claim exact root는 `claim_schema_version`, `claim_id`, `statement`, `applicability`, `evidence`,
`claim_status`, `claim_maturity`, `limitations`, `authorized_action`이다.

- `statement.kind`는 `effect|constraint|failure_mode|invariance` 중 하나다.
- `statement.summary`와 `statement.falsifier`는 trimmed Unicode scalar text이고 각각 UTF-8
  4,096 byte 이하이다.
- limitations는 1~8개의 unique trimmed text이며 각 2,048 byte 이하이다.
- 새 Claim의 stored status/maturity는 literal `active/observed`뿐이다. caller가 `contested`,
  `superseded`, `replicated`를 미리 쓰면 `CLAIM_INVALID`다.
- `claim_id`는 statement, applicability, evidence, stored status/maturity, limitations의 canonical
  body에서 `stable_id("claim", ...)`로 계산한다. Claim digest는 exact full body SHA-256이다.
- missing/extra key, bool-as-int version, unknown enum, duplicate evidence/limitation, invalid ID/digest,
  non-null authority는 event/snapshot mutation 0으로 거절한다.

### B2 — Applicability and exact evidence

Applicability v1은 project/generation/hypothesis class와 exact evaluation scope
`{id, role, manifest_digest}`, scope digest, evaluation-seal digest, compatibility digest, null
authority를 가진다. 이 값은 ProgramManifest binding과 Diagnosis body에 exact 일치해야 한다.

Evidence v1은 다음을 모두 포함한다.

1. linked `origin_id`와 full origin digest;
2. Diagnosis event sequence/id/hash와 Diagnosis id/digest;
3. canonical terminal evidence experiment/event/hash;
4. Diagnosis에 기록된 artifact evidence의 **전체 ordered set**;
5. evaluation-seal digest, compatibility digest, null authority.

`ProgramStore.append_claim`은 project EventLog shared lock 아래 Origin의 지정 head prefix를 replay하고,
linked origin/manifest/applicability와 Diagnosis event/body, terminal/artifact evidence 전체를 비교한 뒤
project lock을 유지한 채 expected ProgramLog head로 append한다. Subset artifact 선택, stale projection
lookup, caller assertion은 evidence가 아니다. Project가 origin 이후 진전했어도 referenced prefix가
그대로면 허용하되, prefix corruption·forgery는 no-write다.

### B3 — Claim relation and reducer

Relation v1 exact root는 `claim_relation_schema_version`, `relation_id`, `relation_type`,
`source_claim_id`, `target_claim_id`, `rationale`, `authorized_action`이다. Allowed types는
`supports|contradicts|supersedes|replicates|derived_from|applies_to`이고, M2-B의 measured state
reducers는 앞의 네 종류다. Relation은 source와 target이 서로 다른 prior canonical Claim이어야
하며 `(type, source, target)` triple은 unique다.

- `supports`: target의 support edge를 추가하고 status/maturity는 바꾸지 않는다.
- `contradicts`: target effective status를 `contested`로 만든다.
- `supersedes`: target effective status를 `superseded`로 만들고 source를 successor로 기록한다.
- `replicates`: source와 target effective maturity를 `replicated`로 만든다.
- status precedence는 `superseded > contested > active`; maturity는 `replicated > observed`다.
- `derived_from`과 `applies_to`는 typed edge만 기록하고 M2-B status/maturity를 바꾸지 않는다.
- source/target Claim의 canonical bytes와 digest는 relation 뒤에도 byte-for-byte 동일하다.

### B4 — Supersession and scope fail-closed rules

- supersession target은 현재 active/non-superseded여야 하고 successor는 정확히 하나다. 이미
  superseded된 Claim의 재-supersession, superseded Claim을 source로 쓰는 edge, self-edge, cycle은
  `CLAIM_SUPERSESSION_INVALID` 또는 structural relation error로 no-write다.
- 관계 양쪽은 같은 hypothesis class, evaluation-seal digest, compatibility digest여야 한다.
  하나라도 다르면 `CLAIM_SCOPE_INCOMPATIBLE`다. M2-B v1은 의미적 cross-class/cross-seal 추론을
  자동 허용하지 않는다.
- exact scope identity `(project_id, generation_id, scope.id)`가 다르면서 scope manifest digest가
  같으면 이름만 바꾼 데이터 overlap으로 보고 `CLAIM_SCOPE_OVERLAP`이다.
- `replicates`는 source scope role이 `replication`, source/target origin이 다르고 exact scope identity와
  manifest digest도 달라야 한다. 같은 origin/scope는 `CLAIM_REPLICATION_NOT_INDEPENDENT`다.
- holdout도 같은 규칙을 적용한다. 이 검사는 manifest identity overlap을 증명하지만, 서로 다른
  manifest 내부 row-level 중복까지 증명하지는 못한다. 그 경우 upstream manifest producer가
  disjointness를 보증해야 한다는 LIMITATION을 유지한다.

## 08.3 Canonical storage and projection boundary

- ProgramLog v1에 `research.program.claim_recorded.v1`과
  `research.program.claim_related.v1` event type을 추가한다. Claim/relation payload와 digest는 strict
  parse되고, replay reducer가 origin 선행, Claim 선행, relation invariants를 매번 재검증한다.
- M2-A ProgramProjection v1은 origin cache로 유지하되 current ProgramLog head를 따라 rebuild한다.
  Claim graph는 같은 canonical ProgramLog에서 deterministic `ClaimSnapshot v1`로 재생성한다.
  별도 authoritative DB나 mutable Claim row를 만들지 않는다.
- Append lock rank는 그대로 `project EventLog shared → ProgramLog exclusive → projection`이다.
  relation append는 project log를 쓰지 않는다.
- ProgramLog corruption을 Claim snapshot으로 은폐하지 않고, snapshot/cache는 canonical log를
  대신하지 않는다.

## 08.4 Frozen machine-readable denominator

`tests/fixtures/program_memory/v2/claims-manifest.json`의 25 case ID·operation·expected가 고정
분모다. Operation 구현은 case ID/expected/hidden scenario/fallback으로 dispatch하지 않고 literal
operation별 실제 parser/store/reducer path를 실행한 뒤 canonical exact equality로 비교한다.

| Family | Count | Acceptance focus |
|---|---:|---|
| Claim schema/status/maturity | 5 | exact keys/version, bounded initial state |
| exact origin/event/artifact/seal | 7 | one valid append + six no-write forgeries |
| four relation reducers | 6 | four state transitions + duplicate/unknown fail-closed |
| immutable supersession | 3 | original bytes/digest unchanged, fork/cycle rejected |
| incompatible/overlapping scope | 4 | seal, compatibility, manifest overlap, same-origin replication |
| **Total** | **25** | skip/fallback 0 |

The compatible non-overlap replication success is the `relation-replicates-reducer` case. Tests construct
an additional canonical replication-scope Diagnosis under the already frozen M1 contract; it is not a fake
Claim-only stub. The original development Claim remains bound to the M1-D supported history and artifact.

## 08.5 Bounded implementation and verification plan

- Product: new `memory/claims.py`, minimal ProgramLog/ProgramStore integration in `memory/program.py`,
  exports only. No retrieval, Context integration, disposition, CLI, autonomous loop, or external adapter.
- Tests: one frozen 25-case module plus direct immutability/replay/authority tests; adjacent M2-A/M1-D and
  ProgramLog/storage tests.
- Pre-result cap: product additions `<=1,500`, tests+fixture `<=1,100`, docs `<=500`, total `<=3,100`.
  초과 시 acceptance를 완화하지 않고 결과 노출 전 re-scope 또는 결과 뒤 PIVOT로 기록한다.
- Verification order: frozen source/hash/IDs → 25 literal cases → focused module → adjacent suites →
  ruff/ty/diff → authority recursive scan → full suite one checkpoint only → independent critic →
  seven-pass progress audit.

## 08.6 Milestone and claim discipline

**영향 받은 M_i.j**: `M2-B`

**현재 라벨**: `ADVANCE — candidate 5/5; critic/audit pending`

| Frozen conjunct | Pre-result acceptance |
|---|---|
| Claim applicability/status/maturity schema | cases 1~5 + exact valid identity |
| exact origin event/hash/artifact/evaluation seal | cases 6~12 + project-prefix audit |
| four relation reducers | cases 13~18 + deterministic replay |
| immutable supersession | cases 15, 19~21 + unchanged Claim bytes/digest |
| incompatible/overlapping scope fail-closed | cases 22~25 + valid independent replication case 16 |

Target intent-execution label은 `CONFIRM`; claim mode target은 `CONFIRMATORY`다. 이 phase spec,
machine-readable denominator, exact schema/ID recipe, error codes, scope rules가 첫 product implementation
및 test result보다 앞서야 한다. 결과 뒤 case/threshold/semantics를 바꾸면 기존 결과를 무효화하고
PIVOT/EXPLORATORY chronology를 별도로 기록한다.

## 08.7 Pessimistic pre-score and limitation

가장 강한 실패 가정은 “hash가 정확한 자유 텍스트를 추가했을 뿐, 실패 지식을 재사용할 수 있는
조건부 Claim이 아니다”이다. 반증하려면 relation 전후 Claim bytes가 불변이고, contradiction,
supersession, replication이 scope/evidence 조건에 따라 deterministic derived state를 바꾸며,
forgery/overlap이 canonical log에 0건 쓰이는 것을 보여야 한다.

M2-B가 PASS해도 retrieval precision/recall, context stale token, knowledge use/reject disposition은
M2-C/D에 남는다. 따라서 M2-B alone으로 Program memory를 complete 또는 v0.4로 청구하지 않는다.

## 08.8 Result chronology and divergence

- Pre-spec/frozen denominator: `5659c67`; independent critic Q1~Q8: `cf20578`; product/test
  implementation: `529283c`. Product code와 첫 observer result는 두 pre-result commits보다 뒤다.
- 첫 focused 실행은 `6 failed, 26 passed`였다. Five frozen semantics나 expected를 바꾸지 않았다.
  다섯 relation no-write path가 prospective `ProgramMemoryError`를 committed-log corruption용
  `IntegrityError`로 포장한 writer boundary와, canonical replication history helper의 필수
  `retry_of` 인자 누락이 원인이었다.
- Correction은 existing committed stream semantic failure는 `IntegrityError`, prospective append
  rejection은 stable Claim error/no-write로 구분하고 helper에 `retry_of=None`을 명시했다.
- Corrected frozen+direct는 `33 passed in 0.98s`, M2-A combined는 `55 passed`, adjacent M1-C/M1-D/
  storage는 `97 passed`, ruff/ty/diff는 PASS했다.
- Q4 pre-spec의 strict ClaimSnapshot replay boundary를 완성한 뒤 final focused denominator는
  그대로 25이며 direct strict-snapshot test만 추가됐다. Frozen case/operation/expected 변경은 0이다.
- Fresh full은 Python 3.12에서 `668 passed, 115 subtests passed in 1216.61s (0:20:16)`다.
  Claim graph recursive authority는 `10` values / non-null `0`; 세 외부 control-tree snapshot은
  v0.3 receipt와 `3/3` exact 동일하다.

## 08.9 Candidate conjunct evidence

| Frozen conjunct | Candidate result | Reproducible evidence |
|---|---|---|
| Claim applicability/status/maturity | PASS | cases 1~5; strict ID/digest and Snapshot parser |
| exact origin/event/artifact/seal | PASS | cases 6~12; omission/addition/reorder/substitution direct no-write |
| four relation reducers | PASS | cases 13~18; mixed precedence direct replay |
| immutable supersession | PASS | cases 15, 19~21; original bytes/digest unchanged |
| scope fail-closed | PASS | cases 16, 22~25; canonical replication history + one-factor rejects |

Measured code volume from `cf20578` is product additions `1,463`, tests+fixture `976`, docs through
critic `249`, total `2,688`; all pre-result category and total caps pass. Claim mode remains
`CONFIRMATORY`: schema, 25 denominator, error codes, scope rules and strict snapshot requirement were
precommitted. The failed first run and its implementation corrections are preserved rather than counted.

## 08.10 Critic Attempt 1 FAIL and correction pre-spec

Independent critic은 `6327b54`를 Q1~Q8로 검증해 Q1/Q4/Q6/Q8 PASS, Q2/Q3/Q5/Q7 FAIL을 냈다.
Product semantic defect보다 evidence witness의 약함이 원인이다.

1. Frozen scope cases 22~24가 pure reducer 결과 뒤 `relation_delta=0`을 상수 반환해 actual
   `ProgramStore.append_relation` no-write를 증명하지 않았다.
2. Artifact reorder direct test는 real two-artifact ordered set을 뒤집은 것이 아니라 forged second
   artifact를 추가한 뒤 parser reject를 관찰했다.
3. Same-origin replication case는 same scope도 동시에 같아 one-factor counterfactual이 아니었다.
   Wrong-role, same-scope/different-origin, same-origin/different-scope, class mismatch witness가 없다.
4. Q7 응답 label `DIRECT with LIMITATION`은 허용된 단일 label 형식이 아니다.

Correction acceptance는 frozen 25 case ID/operation/expected, schema, product semantics와 full threshold를
바꾸지 않는다. Cases 22~24 operation은 canonical ProgramLog에 strict synthetic endpoint Claims를
admit한 뒤 **actual** `ProgramStore.append_relation`을 호출하고 log bytes/relation count가 unchanged임을
측정한다. External Claim admission은 case 6~12의 real locked M1 prefix와 별도로 유지한다.

Canonical replication history에는 terminal 전에 서로 다른 두 artifact record와 일치하는 result
artifacts를 추가한다. 그 Diagnosis에서 만든 valid two-artifact Claim을 기준으로 omission, addition,
substitution, literal reversed order 네 요청을 각각 `ProgramStore.append_claim`에 보내 log/projection/
Claim count delta 0을 측정한다. Replication one-factor direct matrix는 wrong source role,
same-scope/different-origin, same-origin/different-scope Claim admission, class mismatch를 각각 단일 축으로
바꿔 fail-closed한다. Valid case 16은 unchanged positive control이다.

Critic 뒤 늘어난 counterfactual 때문에 tests+fixture cap만 `<=1,100→<=1,250`으로 PIVOT한다. Product
`<=1,500`, docs `<=500`, total `<=3,100`은 유지한다. 이 correction evidence는 result-triggered이므로
phase claim mode를 `MIXED`로 바꾸며 original 25 cases는 CONFIRMATORY, critic-driven extra witnesses는
EXPLORATORY다.

## 08.11 Next action

Correction pre-spec checkpoint 뒤 test-only witness checkpoint `dbd7caa`를 만들었다. Frozen case
ID/operation/expected와 product code 변경은 0이다. Cases 22~24는 actual canonical
`ProgramStore.append_relation`을 호출해 log bytes와 relation count unchanged를 측정한다. Real
two-artifact replication Diagnosis에서 네 artifact mutation을 `append_claim` no-write로 재현했고,
wrong-role/same-scope-different-origin/same-origin-different-scope/class mismatch도 각각 actual writer
반례로 분리했다.

Correction focused는 `37 passed`, M2-A+B는 `59 passed`, adjacent M2-A/M1-D/storage는 `96 passed`,
ruff/ty/diff는 PASS했다. Tests+fixture는 `1,241/1,250`; product `1,463/1,500`; 현재 docs 포함 total은
`3,100` 이하라 correction cap을 통과한다. Original 25는 CONFIRMATORY, critic-driven 8 direct cases는
EXPLORATORY인 MIXED mode를 유지한다.

Correction checkpoint fresh full은 Python 3.12에서 `672 passed, 115 subtests passed in 1163.13s
(0:19:23)`로 PASS했고, 외부 세 control-tree snapshot은 v0.3 receipt와 `3/3` exact 동일하다. 이제
Q1~Q8 critic Attempt 2를 실행한다. Attempt 2가 PASS하기 전에는 progress audit을 시작하지 않는다.
