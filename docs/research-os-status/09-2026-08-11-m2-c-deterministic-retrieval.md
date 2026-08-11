# §09 — M2-C deterministic retrieval·Context integration (2026-08-11)

> Status: **PRE-SPEC — implementation not started; 0/5**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §2
> Previous phase: [§08](08-2026-08-11-m2-b-conditional-claims.md)
> Pipeline impact: [`docs/research-os-pipeline.md`](../research-os-pipeline.md) §5, §8~§10
> Active milestone: `M2-C`; `M2-D` remains blocked

## 09.0 TL;DR

M2-C는 audited `ClaimSnapshot`을 변경하지 않는 순수 결정론 query/reducer와 opt-in Context v3
memory binding만 추가한다. Frozen `retrieval-v1.json`의 exact ordered 결과가 relevant/contradiction
recall, superseded exclusion, irrelevant contamination을 판정하며, combined context token은 기존 project
event head token에 exact Program head와 retrieval manifest digest를 결합한다. Disposition, legacy import,
service auto-discovery, release bump, autonomous loop는 이 phase에 없다.

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

## 09.7 Next action

Frozen fixture/pre-spec checkpoint `e6de927` 뒤 독립 critic이 8개 closed questions를 생성했다.
질문은 real ProgramStore vertical path, denominator receipt, relation boundary, canonical Program append
stale, end-state/milestone positioning, chronology, divergence를 고정한다. Critic 질문 checkpoint 뒤
product/test implementation을 시작한다.
