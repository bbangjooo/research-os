# §08 — M2-B Conditional Claim·evidence relations (2026-08-11)

> Status: **CORRECTION — candidate 5/5; critic PASS; audit Attempt 1 FAIL, re-audit pending**
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

Exact root는 schema version/ID, statement, applicability, evidence, stored status/maturity,
limitations, null authority다. Kind는 `effect|constraint|failure_mode|invariance`; summary/falsifier는
각 4,096 UTF-8 bytes, 1~8 unique limitations는 각 2,048 bytes다. Initial state는 literal
`active/observed`; ID/digest는 canonical full body에서 계산하고 모든 malformed/extra/non-null 입력은
mutation 0으로 `CLAIM_INVALID`다.

### B2 — Applicability and exact evidence

Applicability는 project/generation/class, exact scope `{id,role,manifest_digest}`, scope/seal/compatibility
digests와 null authority이며 manifest/Diagnosis와 exact 일치한다. Evidence는 Origin, Diagnosis event/body,
terminal, artifact **전체 ordered set**, seal/compatibility를 담는다. `append_claim`은 project shared lock
아래 referenced prefix 전체를 replay한 뒤 expected ProgramLog head에 append한다. Prefix가 보존된 이후
진전은 허용하지만 subset/stale assertion/corruption/forgery는 no-write다.

### B3 — Claim relation and reducer

Relation exact root는 schema/ID/type/source/target/rationale/null authority; types는
`supports|contradicts|supersedes|replicates|derived_from|applies_to`, prior distinct endpoints와 unique
triple을 요구한다. 앞의 four reducers는 edge/`contested`/`superseded`/양쪽 `replicated`를 파생한다.
Precedence는 `superseded>contested>active`, `replicated>observed`; Claim bytes/digest는 불변이다.

### B4 — Supersession and scope fail-closed rules

- Supersession은 active target/one successor만 허용하고 re-edge/self/cycle은 no-write다.
- Endpoints는 same class/seal/compatibility여야 하며 distinct identity+same manifest는 overlap이다.
- Replication은 source role `replication`, distinct origin/scope/manifest를 요구한다. Holdout도 동일하며
  서로 다른 manifest 내부 row-level disjointness는 upstream producer 책임이라는 limitation을 유지한다.

## 08.3 Canonical storage and projection boundary

- ProgramLog에 strict `claim_recorded.v1/claim_related.v1`을 추가하고 origin/Claim 선행과 relation을
  replay 때마다 검증한다. ClaimSnapshot은 canonical log에서 rebuild하며 authoritative mutable row는 없다.
- Lock rank는 `project shared→ProgramLog exclusive→projection`; cache는 corruption을 은폐하지 않는다.

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

Replication positive control은 frozen M1 contract에 canonical replication Diagnosis를 추가하는
`relation-replicates-reducer`이며 original development Claim은 M1-D evidence에 bound한다.

## 08.5 Bounded implementation and verification plan

- Product는 `memory/claims.py`와 minimal ProgramLog integration만; retrieval/Context/disposition/loop는 없다.
- Tests는 frozen 25 + direct invariants + adjacent M2-A/M1-D/storage다.
- Pre-result cap: product additions `<=1,500`, tests+fixture `<=1,100`, docs `<=500`, total `<=3,100`.
  초과 시 acceptance를 완화하지 않고 결과 노출 전 re-scope 또는 결과 뒤 PIVOT로 기록한다.
- Verification order: frozen source/hash/IDs → 25 literal cases → focused module → adjacent suites →
  ruff/ty/diff → authority recursive scan → full suite one checkpoint only → independent critic →
  seven-pass progress audit.

## 08.6 Milestone and claim discipline

영향은 `M2-B`; 현재 `ADVANCE — candidate 5/5, critic PASS, re-audit pending`이다. Initial target은
CONFIRMATORY였으나 result-triggered witness/cap correction 뒤 allowed intent-execution label은 `PIVOT`,
claim mode는 original frozen 25 CONFIRMATORY + critic/audit extras EXPLORATORY의 `MIXED`다.

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

Attempt 1은 Q2/Q3/Q5/Q7 FAIL: cases 22~24가 reducer 상수 delta였고 real two-artifact reverse,
replication one-factor matrix, single Q7 label이 없었다. Frozen 25/semantics를 유지한 채 actual
`append_relation` log/count no-write, real two-artifact four mutations, wrong-role/same-scope/
same-origin-different-scope/class witnesses와 case 16 positive control로 교정했다.

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

Correction focused `37`, M2-A+B `59`, ruff/ty/diff PASS다. Adjacent `96` exact command는 `.venv/bin/pytest -q tests/test_m2a_program_memory.py tests/test_m1d_diagnoses.py tests/test_m1d_state.py tests/test_storage_hardening.py`다. Tests+fixture는 `1,242/1,250`; original 25 CONFIRMATORY와 critic
extras EXPLORATORY의 MIXED mode를 유지한다.

Correction checkpoint fresh full은 Python 3.12에서 `672 passed, 115 subtests passed in 1163.13s
(0:19:23)`로 PASS했고, 외부 세 control-tree snapshot은 v0.3 receipt와 `3/3` exact 동일하다. 이제
Q1~Q8 critic Attempt 2를 실행한다. Attempt 2가 PASS하기 전에는 progress audit을 시작하지 않는다.

## 08.12 Critic Attempt 2 FAIL and documentation compaction pre-spec

Attempt 2는 Q1~Q7 PASS, Q8 FAIL이다. `c1a1851..dc21ecf` gross additions가 product `1,463`,
tests+fixture `1,241`, docs `426`, total `3,130/3,100`임을 독립 critic이 확인했다. Correction은
product/test/fixture/frozen 25/acceptance/full evidence를 바꾸지 않고 phase/critic의 중복 설명만
압축한다. Q1~Q8, 두 FAIL chronology, MIXED claim mode, cap PIVOT, external/no-authority 경계는 모두
보존했다. Documentation-only correction 뒤 Attempt 3는 Q1~Q8 PASS, 당시 final `3,082/3,100`이었다.

## 08.13 Audit Attempt 1 FAIL and correction pre-spec

Audit `517bbd7`은 paired-core stale state/PIVOT 누락, cases 17/18/20/21/25의 exact log-byte no-write
미측정, adjacent `96` command 부재로 FAIL했다. Correction은 frozen IDs/expected와 product semantics를
바꾸지 않는다. Five operations는 pre/post ProgramLog bytes와 relation count를 실제 측정하고, paired
status/pipeline은 Attempt 3 PASS·candidate/audit pending·`PIVOT/MIXED`·final LOC를 동기화하며 정확한
adjacent command를 기록한다. Audit ledger를 포함해 docs/total cap `500/3,100`을 유지하도록 중복
phase prose를 압축한다. Focused/adjacent/hash/static을 재현하고 independent re-audit 전 CLOSE하지 않는다.

Correction `1b1e22f`는 five frozen operations 모두 shared helper로 exact log bytes/relation count를
측정한다. Focused `37`, M2-A+B `59`, exact adjacent `96`, ruff/ty/diff가 PASS했고 frozen expected와
product diff는 0이다. Paired cores는 critic PASS·audit correction·`PIVOT/MIXED` candidate로 동기화했다.
