# §10 — M2-D knowledge disposition·legacy import·v0.4 release (2026-08-12)

> Status: **PRE-SPEC — implementation not started; 0/5**
> Previous phase: [§09](09-2026-08-11-m2-c-deterministic-retrieval.md)
> Active milestone: `M2-D`; M3 remains blocked

## 10.0 TL;DR

M2-D는 M2-C retrieval의 모든 returned Claim을 Proposal-bound
`used|rejected|not_applicable` companion record로 exact disposition하고, legacy free text는 typed Claim으로
추론하지 않는 digest-only opaque record로 ProgramLog에 넣는다. 세 외부 프로젝트는 aggregate control-tree
snapshot만 두 번 읽고 writer delta 0을 확인한다. 마지막으로 0.2/0.3 managed upgrade와 v0.4 release를
닫는다. 외부 migration, autonomous loop, product multi-agent는 없다.

## 10.1 Scope, end-state, and authority

- Target은 M2-D five conjunct, M2 parent/v0.4, NS1/NS7과 Program memory/Context release surface다.
- `ProposalKnowledgeDisposition`은 Proposal v1을 바꾸지 않는 immutable companion이다. Proposal
  ID/digest, generation/class/scope, combined Context token, Program head, query/result digests를 exact bind한다.
- 모든 returned active/contradiction Claim ID는 exactly once disposition된다. Entry는 Claim ID/digest,
  retrieval role, exact relation refs, Proposal field refs, bounded rationale를 가진다.
- 모든 신규 surface는 `authorized_action=null`; service/event/deploy/merge/trade 권한은 없다.
- `crypto-new`, `manager`, `BinancePredictionStrategy`는 read-only aggregate snapshot만 허용한다.
  fixture를 저장하는 곳은 이 repo뿐이며 external writer/file 변경, live pilot/migration은 0이다.

## 10.2 Frozen disposition v1 contract

- Top-level exact bindings은 manifest의 ten fields + sorted entries + stable disposition ID/null authority다.
- `used`는 non-empty Proposal field refs를, contradiction `rejected`는 hit의 exact relation refs와 Proposal
  field refs를 요구한다. `not_applicable`는 Proposal refs와 exact reason code를 요구한다.
- Entry claim digest/role/relation set은 M2-C `RetrievalResult`와 canonical exact equality다. Missing,
  duplicate, unknown, stale project/Program/query/result, extra/non-null은 validation 0건/no-write다.
- Validation은 Context validator로 current project token + current ClaimSnapshot에서 retrieval을 다시
  계산한 다음 Proposal/disposition을 검사한다. Narrative는 결론 권한이 아니라 exact refs의 설명이다.

## 10.3 Frozen legacy opaque v1 contract

- `LegacyOpaqueRecord`는 Program/source project/source kind/locator, content SHA-256/size/media type,
  literal `legacy_unstructured`, empty `typed_claim_ids`, null authority를 bind한 stable ID다.
- Append는 caller가 준 bounded bytes의 digest/size와 record를 exact 대조한 뒤 Program head precondition으로
  canonical event를 쓴다. Raw content와 inferred Claim/relations는 저장하지 않는다.
- Rebuildable legacy snapshot은 record만 노출한다. Forgery/duplicate/malformed/non-null은 ProgramLog bytes
  delta 0이다. Actual external project legacy import/migration은 이 phase 범위가 아니다.

## 10.4 Frozen read-only compatibility and release gate

`tests/fixtures/program_memory/v3/m2d-manifest.json`은 disposition 14, legacy 6, external 1, upgrade 1,
release 1의 literal 23 cases를 고정한다. External denominator는 세 이름 exact이며 current aggregate는
`crypto-new 16/956a…`, `manager 28/d689…`, Binance surface absent `0/5ad3…`; verifier가 pre/post exact
동일과 writer delta 0을 요구한다. Absence는 설치나 생성 권한이 아니다.

v0.4 gate는 version surfaces 3개, docs/packaged skill 6개, Python 3.12, full collected floor `676+115`,
recursive authority 0, product multi-agent false를 bind한다. Exact managed `0.2.0`과 sealed
`0.3.0@e120292`만 explicit upgrade로 0.4가 되며 drift/unknown/failure는 no-write recovery다.

## 10.5 Bounded plan and milestone discipline

- Product: `science/knowledge.py`, minimal ProgramLog legacy event/snapshot, installer/release version surfaces.
- Tests: literal 23-case runner, real Proposal+retrieval+Context vertical, legacy no-write/replay, external
  pre/post aggregate snapshots, both managed upgrades, wheel/temp install/single verifier.
- Pre-result cap: product `<=1,400`, tests+fixtures `<=1,450`, docs `<=550`, total `<=3,200`.
- Order: frozen hash/IDs→critic questions→product/tests→focused/adjacent/static→single fresh full/release
  receipt→critic verify→independent seven-pass audit. 두 검증 전 M2/v0.4를 close하지 않는다.

M2-D exit exact AND:

1. Proposal claim disposition three-way validation PASS.
2. used/rejected exact reference audit PASS.
3. legacy free text typed inference 0 + opaque digest import PASS.
4. three external project snapshot match 3/3 + writer delta 0.
5. docs/version 0.4.0 + 0.2/0.3 managed upgrades + full single release gate PASS.

## 10.6 Pessimistic pre-score and claim mode

가장 강한 실패 가정은 “agent가 Claim을 읽었다고 체크박스만 채우고 자유 텍스트 이유로 사후 합리화하며,
legacy 문장을 몰래 typed Claim으로 승격하고, release verifier가 외부 tree를 바꾸거나 absent Binance surface를
설치한다”이다. Exact full-coverage/ref equality, raw-content/typed count 0, actual ProgramLog no-write,
three-tree before/after equality가 이를 반증해야 한다.

Disposition/legacy/release criteria와 expected outcomes는 product/result 전 commit하므로 initial label은
`CONFIRMATORY`다. 현재 external digest는 observed baseline이라 그 절대값 자체는 descriptive이고,
pre/post writer delta 0이 confirmatory gate다. Result-triggered contract 수정은 `PIVOT/MIXED`로 강등한다.

## 10.7 Residual issues

- M3 DecisionPacket/FSM이 disposition을 실제 next proposal/synthesis에 소비하는 것은 M3-A/B다.
- Actual external live pilot/migration은 v0.5 이후다. NS6 unseen learning effect는 여전히 미측정이다.
- Product multi-agent는 NS6 통과 이후다.

## 10.10 Next action

Frozen manifest/pre-spec checkpoint 뒤 independent critic이 최대 8개 closed questions를 생성한다.
그 질문을 commit하기 전 product/test/release implementation을 시작하지 않는다.
