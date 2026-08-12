# §09 — M2-C deterministic retrieval·Context integration (2026-08-11)

> Status: **COMPLETE — 5/5; critic + independent seven-pass audit PASS**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §2
> Previous phase: [§08](08-2026-08-11-m2-b-conditional-claims.md)
> Pipeline impact: [`docs/research-os-pipeline.md`](../research-os-pipeline.md) §5, §8~§10
> Closed milestone: `M2-C`; next active `M2-D`

## 09.0 TL;DR

M2-C는 audited `ClaimSnapshot`을 변경하지 않는 순수 결정론 query/reducer와 opt-in Context v3
memory binding을 구현했다. Frozen oracle은 `100/100/100/0`, real ProgramStore vertical과 stale
no-write, full `676+115`, critic Q1~Q8이 PASS했다. Disposition, legacy import, release bump,
autonomous loop는 이 phase에 없고 independent audit 전에는 close하지 않는다.

## 09.1 End-state delta and authority

- 이동 목표는 NS4 `0/4→4/4`, M2-C `0/5→5/5`, end-state Context/Program-memory 행의
  “retrieval 없음” 제거다. M2-C만으로 M2/v0.4를 close하지 않는다.
- ProgramLog/Claim은 canonical이고 retrieval/Context는 rebuildable read projection이다. Query나 packet은
  Claim status, relation, evidence를 수정하지 않는다.
- 모든 신규 query/result/context surface는 `authorized_action=null`; merge/deploy/trade/live operation은
  없다. 외부 세 프로젝트는 읽거나 쓰지 않으며, live migration은 v0.5 이후, product multi-agent는
  NS6 이후라는 사용자 경계를 보존한다.

## 09.2 Frozen retrieval v1 contract

### C1 — Exact query and candidate relevance

Query는 schema version/ID, exact Program ID/head, hypothesis class, compatibility digest, current scope,
non-empty sorted unique Claim kinds, optional exact Diagnosis digest, requested relation types, limit, null
authority를 bind한다. `program/class/compatibility/kind`는 exact filter이며 optional Diagnosis digest가
있으면 exact evidence key다. 자유 텍스트 similarity, vector score, fixture case ID dispatch는 없다.

Scope는 knowledge transfer를 막는 filter가 아니라 deterministic specificity다: exact
`id+role+manifest=0`, same role `=1`, cross role `=2`. M2-B가 relation endpoint의 class/seal/
compatibility를 이미 fail-closed하므로 direct relation expansion은 canonical graph만 소비한다.

### C2 — Status, relation expansion, and exact ordering

- Base-relevant `active|contested` Claim은 active result 후보이고 `superseded`는 결과에서 제외된다.
- requested `contradicts` edge의 target이 base-relevant이면 non-superseded source를 contradiction result로
  함께 노출하며 active result와 중복하지 않는다.
- Hit은 Claim ID/digest, statement, limitations, applicability, effective status/maturity, relation role,
  deterministic reasons와 order key를 보존한다.
- Canonical order는 frozen `(relation_priority, scope_specificity, status_priority, claim_id)`이며
  active와 contradiction 목록 각각 exact하다. 입력 order와 관계없이 같은 result/manifest digest다.
- Limit truncation은 명시하고 oracle query는 denominator를 자르지 않는 limit을 고정한다. Empty query는
  exact empty active/contradiction일 때만 PASS다.

### C3 — Context v3 memory binding and stale check

기존 Context v3는 memory argument가 없으면 byte-for-byte 동일하다. Opt-in binding은 strict retrieval
result를 `memory` section에 넣고 nested snapshot을 v3로 올려 이전 project token, Program ID/head,
query/result manifest digest를 bind한 새 `context_token`을 계산한다. Validator는 current project token,
current `ClaimSnapshot.program_head`, query/result digest 중 하나라도 다르면 fail-closed한다.

M2-C의 combined token은 read-only Context contract다. Proposal의 claim disposition과 registration 직전
project+Program double-head validation은 M2-D에서 이 token을 소비하며 닫는다. 따라서 기존 service write
path를 우회하거나 tokenless authority를 만들지 않는다.

## 09.3 Frozen machine-readable denominator

`tests/fixtures/program_memory/retrieval-v1.json`은 one Program head, ten candidate Claim IDs와 exact
class/compatibility/scope/kind/Diagnosis/status/maturity, three typed relations, four query/candidate orders,
ordered expected active/contradiction IDs와 expected superseded/irrelevant sets를 고정한다.

| Query | Purpose | Expected active / contradiction / superseded / irrelevant |
|---|---|---:|
| `broad-class-scope` | class/kind/scope ranking + all exclusions | `5 / 1 / 1 / 3` |
| `exact-diagnosis-with-contradiction` | exact evidence key + relation expansion | `1 / 1 / 0 / 8` |
| `expected-empty` | empty-result exactness | `0 / 0 / 0 / 10` |
| `shuffled-broad-class-scope` | input-order invariance | `5 / 1 / 1 / 3` |

NS4 산술은 query별 exact sets를 합친다. Relevant/contradiction recall 분모는 respective expected set,
superseded exclusion은 expected superseded IDs가 returned되지 않은 비율, contamination은 returned IDs 중
expected irrelevant 교집합 비율이다. 각 query의 ordered list exact equality와 expected-empty도 별도 gate다.

## 09.4 Bounded implementation and verification plan

- Product: `memory/retrieval.py`, minimal `memory/__init__.py` export, opt-in `agent.py` Context binding only.
- Tests: frozen oracle runner, strict query/result mutations, real M2-B `ProgramStore.claim_snapshot()`
  integration, shuffle/tie/empty/limit, combined token one-factor stale matrix, legacy Context exact equality,
  recursive null-authority/no-write.
- Pre-result cap: product additions `<=900`, tests+fixture `<=1,150`, docs `<=500`, total `<=2,550`.
  초과 시 acceptance를 완화하지 않고 결과 전 re-scope 또는 결과 뒤 PIVOT로 기록한다.
- Verification order: fixture hash/IDs → oracle exact output/metrics → focused module → M2-A/B + M1-E
  adjacent → ruff/ty/diff → authority/no-write → full suite one checkpoint → independent critic verify →
  seven-pass progress audit.

## 09.5 Milestone exit and claim discipline

M2-C exit는 다음 exact AND다:

1. NS4 relevant recall `100%`.
2. contradiction recall `100%`.
3. superseded exclusion `100%`.
4. shuffled/irrelevant contamination `0%`와 exact-empty/order PASS.
5. Context v3 retrieval manifest + Program head token stale-check PASS.

Fixture와 pre-spec을 product/result보다 먼저 commit하므로 initial mode는 `CONFIRMATORY`다. Critic이
새 witness를 요구하면 frozen denominator/semantics를 바꾸지 않는 test-only correction은
`EXPLORATORY`; result-triggered contract 변경은 `PIVOT/MIXED`로 기록한다. Critic PASS와 independent
audit PASS 전에는 M2-C를 close하거나 M2-D를 시작하지 않는다.

## 09.6 Pessimistic pre-score and limitation

가장 강한 실패 가정은 “fixture ID를 그대로 반환하는 hard-coded selector이고, Context token은 실제
Program 변화와 무관하다”이다. 반증하려면 같은 typed reducer가 real `ClaimSnapshot`과 shuffled corpus를
처리하고, wrong class/compatibility/kind와 superseded가 결과에 0건이며, direct contradiction만 reason과
함께 노출되고, Program head/query/result/project token의 one-factor mutation 각각이 no-write stale
failure가 되어야 한다.

M2-C가 PASS해도 retrieved Claim을 다음 Proposal이 실제 사용·기각한 이유와 legacy opaque import,
v0.4 release는 M2-D에 남는다. 실패 지식이 다음 가설의 품질을 높인다는 효과 주장은 M3 unseen
benchmark 전에는 하지 않는다.

### 09.6.1 Result chronology and receipt

Pre-spec `e6de927`→critic questions `e002076`→first product/result `bc0b79a` 순서다. Frozen SHA-256
`dd638d…d81`과 `git diff e6de927 -- retrieval-v1.json`은 0이다. Receipt command는 네 query의
TP/FN/irrelevant FP/superseded leak를 공개하며 totals `11/11`, `3/3`, leak `0/2`, FP `0/14`와 exact
order/empty/shuffle를 PASS한다.

### 09.6.2 Verification evidence

- `pytest -q tests/test_m2c_deterministic_retrieval.py` → `4 passed`.
- M2-C+B+A+M1-E/agent adjacent → `87 passed, 3 subtests`.
- Python 3.12 fresh full → `676 passed, 115 subtests` in `505.01s`; ruff/ty/diff PASS.
- Real vertical은 actual `ProgramStore.append_claim/append_relation`→rebuild→retrieval→Context v3를
  실행한다. Canonical Claim append 뒤 old token과 project/query/result/token one-factor mutations는
  모두 `StaleAgentContextError`, verifier 전후 ProgramLog bytes delta `0`이다.

### 09.6.3 Bounded scope

Gross additions는 product `684/900`, tests+fixture `921/1,150`, docs pre-verify `183/500`, total
`1,788/2,550`이다. Product는 retrieval/opt-in Context binding뿐이며 disposition/release/loop는 0이다.

## 09.6.4 Milestone positioning — CLOSE

Prerequisite gate: `M2-B closed` (status §2.3.3, phase §08 audit PASS).

| M2-C conjunct | 이전 | 이번 phase 후 | 근거 |
|---|---:|---:|---|
| relevant recall | 0% | 100% audited | receipt `11/11` |
| contradiction recall | 0% | 100% audited | receipt `3/3` |
| superseded exclusion | 미구현 | 100% audited | leak `0/2` |
| contamination + order/empty/shuffle | 미구현 | 0% + PASS audited | FP `0/14`; four exact query rows |
| Context retrieval/Program-head stale | 미구현 | PASS audited | real vertical + five stale/no-write paths |

Product evidence 5/5, critic Q1~Q8, independent seven-pass audit이 모두 PASS해 `CLOSE`한다.
M2 parent는 M2-D 전이므로 open이며 이제 M2-D만 active다.

## 09.6.5 End-state delta

Delta classification: **구체화·검증**.

- Before: Program memory는 audited Claim graph까지였지만 retrieval이 없었고 Context v3에는
  relevant Claim/reason/Program head가 없었다.
- After: canonical ProgramLog→ClaimSnapshot→relevance/contradiction reducer와 opt-in exact
  Claim/limitation/reason/manifest + Program-head-bound Context read packet이 있다.
- 삭제/완화된 종착지 항목은 없다.

## 09.6.6 Intent-execution reconciliation — MATCH

- 의도: frozen exact oracle의 네 NS4 수치와 Program-head-bound Context stale-check만 구현·측정한다.
- 실행: public reducer, real ProgramStore vertical, opt-in Context binding, oracle/stale/full evidence만
  추가했고 disposition/release/loop는 추가하지 않았다.
- 근거: pre-spec 범위와 `bc0b79a` product diff가 일치하며 criteria/result-triggered 변경은 0이다.

## 09.6.7 Claim mode — CONFIRMATORY

- Pre-spec commit: `e6de927` (`2026-08-11 23:32:05 +0900`).
- 첫 data/product commit: `bc0b79a` (`2026-08-11 23:44:00 +0900`).
- Frozen fixture/filter/order/expected sets diff: 0 bytes. Result-triggered criteria 변경도 0이다.

## 09.6.8 Divergence diagnosis — 해당 없음

해당 없음 — 사유: 예상 exact four-query `100/100/100/0`, stale matrix, legacy no-memory equality,
null authority/no-write가
모두 일치했다. 불일치 시 contract/분모 오류는 `REQUIREMENT-WRONG`, 재현·측정 오염은
`RESULT-INVALID`, 예상 밖 실제 동작은 `GENUINE-FINDING`+EXPLORATORY holdout을 발동한다.

## 09.7 North-Star update

NS4는 audited `4/4`; NS1 신규 surface full regression도 PASS다. 이 phase는 retrieval quality와
read-only Context binding만 close하며 disposition/v0.4는 청구하지 않는다.

## 09.9 Residual issues

- Retrieved Claim disposition/legacy opaque import/v0.4 release는 M2-D다.
- Context binding은 opt-in read contract다. Registration 직전 double-head/disposition 소비는 M2-D다.
- 다음 가설 품질 개선 효과는 unseen NS6 전에는 미측정이다.

## 09.10 Next action

Critic Q1~Q8과 independent seven-pass audit이 PASS했다. 다음 cycle은 M2-D disposition·legacy
opaque import·read-only compatibility·v0.4 release pre-spec을 result 전에 고정한다.
