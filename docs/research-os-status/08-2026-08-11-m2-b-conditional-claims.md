# §08 — M2-B Conditional Claim·evidence relations (2026-08-11)

> Status: **CORRECTION — candidate evidence 5/5; critic Attempts 1–2 FAIL; audit not started**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §2
> Previous phase: [§07](07-2026-08-11-m2-a-program-manifest-log.md)
> Pipeline impact: [`docs/research-os-pipeline.md`](../research-os-pipeline.md) §4, §8~§10
> Active milestone: `M2-B` at candidate `5/5`; CLOSE requires critic and independent audit

## 08.0 TL;DR

M2-B는 exact Diagnosis/terminal/artifacts/class/scope/seal/compatibility에 bind한 immutable
`active/observed` Claim을 기록한다. `contested/superseded/replicated`는 relation reducer가 파생하며
scope/seal/compatibility/replication independence 위반은 no-write다. Initial checkpoint `529283c`의
`25/25`, focused `33`, adjacent `97`, full `668+115`는 candidate일 뿐 CLOSE/v0.4가 아니다.

## 08.1 Scope, end state, and authority

- Target은 NS3 Claim/관계와 NS1 authority; five conjunct와 critic/audit 전부 PASS해야 CLOSE한다.
- Statement는 bounded synthesis assertion, initial maturity는 `observed`; semantic quality는 relation,
  replication, M3 benchmark가 판정한다.
- 모든 신규 surface는 `authorized_action=null`; merge/deploy/trade/live는 없다. 외부 세 프로젝트는
  M2-D read-only 전까지 건드리지 않으며 live migration은 v0.5 이후, multi-agent는 NS6 이후다.

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

Evidence v1은 linked Origin ID/digest, Diagnosis event sequence/ID/hash와 body ID/digest, terminal
experiment/event/hash, artifact evidence **전체 ordered set**, seal/compatibility digest, null authority다.

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

- `supports`는 edge만, `contradicts`는 target `contested`, `supersedes`는 target `superseded`,
  `replicates`는 양쪽 `replicated`; `derived_from/applies_to`는 typed edge만 기록한다.
- Precedence는 `superseded > contested > active`, `replicated > observed`; Claim bytes/digest는 불변이다.

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

- Chronology: `5659c67` denominator → `cf20578` critic → `529283c` product. First focused `6F/26P`는
  frozen semantics 변경 없이 prospective error wrapping과 missing `retry_of`를 교정해 `33P`가 됐다.
- M2-A combined `55`, adjacent `97`, ruff/ty/diff, full `668+115` PASS; frozen diff 0, authority
  `10/0 non-null`, external snapshots `3/3` exact다.

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

## 08.12 Critic Attempt 2 FAIL and documentation compaction pre-spec

Attempt 2는 Q1~Q7 PASS, Q8 FAIL이다. `c1a1851..dc21ecf` gross additions가 product `1,463`,
tests+fixture `1,241`, docs `426`, total `3,130/3,100`임을 독립 critic이 확인했다. Correction은
product/test/fixture/frozen 25/acceptance/full evidence를 바꾸지 않고 phase/critic의 중복 설명만
압축한다. Q1~Q8, 두 FAIL chronology, MIXED claim mode, cap PIVOT, external/no-authority 경계는 모두
보존한다. 최종 acceptance는 docs gross `<=396`, total `<=3,100`; focused/hash/diff를 재확인하고
Attempt 3가 PASS하기 전 audit을 시작하지 않는다. Documentation-only라 full suite는 재실행하지 않는다.

## 08.13 Audit Attempt 1 FAIL and correction pre-spec

Audit `517bbd7`은 paired-core stale state/PIVOT 누락, cases 17/18/20/21/25의 exact log-byte no-write
미측정, adjacent `96` command 부재로 FAIL했다. Correction은 frozen IDs/expected와 product semantics를
바꾸지 않는다. Five operations는 pre/post ProgramLog bytes와 relation count를 실제 측정하고, paired
status/pipeline은 Attempt 3 PASS·candidate/audit pending·`PIVOT/MIXED`·final LOC를 동기화하며 정확한
adjacent command를 기록한다. Audit ledger를 포함해 docs/total cap `500/3,100`을 유지하도록 중복
phase prose를 압축한다. Focused/adjacent/hash/static을 재현하고 independent re-audit 전 CLOSE하지 않는다.
