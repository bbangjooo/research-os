# §10 — M2-D knowledge disposition·legacy import·v0.4 release (2026-08-12)

> Status: **VERIFY PENDING — corrected release gate PASS; critic reverify + audit pending**
> Previous phase: [§09](09-2026-08-11-m2-c-deterministic-retrieval.md)
> Active milestone: `M2-D`; M3 remains blocked

## 10.0 TL;DR

M2-D는 M2-C retrieval의 모든 returned Claim을 durable Proposal-bound
`used|rejected|not_applicable` companion event로 exact disposition하고, legacy free text를 typed Claim으로
추론하지 않는 digest-only opaque event로 ProgramLog에 넣었다. Attempt 1 gate는 PASS했으나 critic이
valid three-way의 durable real-path 측정을 FAIL했다. 그 receipt와 청구는 철회했다. 두 actual scope/origin의
registered Proposal→Context→ProgramLog cold replay three-way test와 corrected single gate가 PASS했다.
M2-D/M2는 critic reverify와 audit 전까지 open이고 M3-A는 시작하지 않는다.

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

Disposition/legacy/release criteria와 expected outcomes는 product/result 전 commit했으므로 frozen rows는
`CONFIRMATORY`다. External digest의 절대값 자체는 descriptive이고 pre/post writer delta 0만
confirmatory gate다. Critic FAIL 후 추가한 durable three-way witness는 `EXPLORATORY`이므로
phase 전체는 `MIXED`다(§10.6.7).

### 10.6.1 What was built

- `memory/knowledge.py`에 strict `ProposalKnowledgeDisposition`/entry와
  `LegacyOpaqueRecord`/snapshot을 추가했다. Disposition은 returned Claim 전체를 exactly once 덮고
  Claim digest·role·relation·Proposal field ref·reason code·null authority를 canonical equality로 묶는다.
- `memory/program.py`에 `knowledge_disposition_recorded.v1`과 `legacy_opaque_recorded.v1` event,
  reducer/replay, duplicate/stale/no-write, `ProgramStore` append vertical을 추가했다. Replay는 event 직전
  Program prefix에서 retrieval을 다시 계산한다.
- `agent.py` writer는 current project Context v3 token, current Program head/result와 canonical registered
  Proposal을 재검증한 뒤에만 disposition을 append한다. Legacy event는 raw bytes가 아니라 digest/size만
  보존하며 typed Claim/relation을 만들지 않는다.
- v0.4 installer는 sealed exact 0.2/0.3 managed tree만 explicit upgrade하고 drift/unknown/failure를
  no-write/restore한다. `scripts/verify_release.py`는 historical v0.3 proof와 current v0.4 gate를 분리한다.

### 10.6.2 Verification evidence

| Gate | 결과 | 재현 근거 |
|---|---:|---|
| Frozen contract | `23/23 PASS` | `m2d-manifest.json` SHA-256 `b61da8…b2a7`; corrected receipt literal IDs/results |
| Disposition | frozen `14/14` + durable three-way `1/1` | two actual scope/origin Claims + registered Proposal/Context/ProgramStore cold replay |
| Legacy opaque | `6/6 PASS` | adversarial free text append/replay; typed Claim/edge delta 0, raw substring 0 |
| External read-only | `3/3 PASS` | actual sibling paths, frozen bytes/entry baseline independent match, gate 전후 mode/symlink digest exact; Binance surface absent |
| Managed upgrade | `6/6 PASS` | exact 0.2/0.3, drift/unknown no-write, two-target commit/publish failure recovery |
| Full release Attempt 1 | **WITHDRAWN** `712+115` | Q2 proxy-vs-real FAIL; final evidence로 사용하지 않음 |
| Corrected release | **PASS** `713+115` | commit `9dbb413`; durable node `1/1`; focused authority/manifest `37`; wheel 0.4.0 |

Attempt 1 receipt는 checkpoint `ef2d9a2` history에만 남기고 current tree에서 철회했다. Corrected
single gate receipt는 `f1ab646`에 기록했고 saved-receipt test가 exact case/durable/upgrade/product-tree
binding을 재검증한다.

### 10.6.3 Bounded scope

Pre-spec `4b0d0a1` 이후 `git diff --numstat 4b0d0a1..f1ab646`의 gross additions은 product
`1,150/1,400`, tests+fixture `1,242/1,450`, release verifier `398`, docs/receipt `331`;
total `3,121/3,200`이다. External projects에는 file writer가 없었고 live migration·loop·product
multi-agent 코드는 0이다.

## 10.6.4 Milestone positioning — ADVANCE, corrected evidence 5/5

Prerequisite gate는 M2-C close와 independent audit PASS다(status §2.3.3, phase §09).

| M2-D conjunct | 이전 | 현재 evidence | 판정 |
|---|---:|---:|---|
| three-way Proposal disposition | Attempt 1 proxy measurement | corrected actual two-scope append/cold replay + receipt node `1/1` | ✅ |
| used/rejected exact reference audit | 미구현 | digest/role/relation/field one-factor no-write | ✅ |
| legacy inference 0 + opaque digest import | 미구현 | frozen legacy `6/6`, raw/typed delta 0 | ✅ |
| external snapshot 3/3 + writer delta 0 | v0.3 byte-only | v0.4 bytes/mode/symlink pre/post exact | ✅ |
| v0.4 docs/version/upgrade/full gate | Attempt 1 withdrawn | corrected `713+115`, upgrades `6/6`, wheel/version PASS | ✅ |

다섯 product/release conjunct는 corrected evidence 5/5지만 independent critic reverify와 audit이 남아
`ADVANCE`다. Critic과 audit가 모두 PASS한 뒤에만 M2-D와 parent M2를
`CLOSE`하고 M3-A를 active로 바꾼다. NS7 actual external
replay·opaque classification `3/3`은 M3-D exit에 그대로 남으며 synthetic `6/6`으로 대체하지 않는다.

## 10.6.5 End-state delta

Delta classification: **구체화·검증**.

- Before: Program memory는 Claim graph와 deterministic retrieval까지만 있었고 Proposal이 어떤
  지식을 사용·기각했는지 canonical audit trail이 없었다.
- After: registered Proposal + exact Context retrieval을 durable disposition event로 저장/replay하고,
  legacy bytes는 semantic 승격 없이 digest-only opaque event로 격리한다. Context read set이 실제
  Program write companion으로 이어져 M3 DecisionPacket이 소비할 stable boundary가 생겼다.
- 완화·삭제된 종착지 항목은 없다. Actual external replay와 autonomous loop/unseen 효과는 여전히 open이다.

## 10.6.6 Intent-execution reconciliation — PIVOT

- **의도(§10.1~§10.5):** frozen 23-case contract와 actual durable three-way vertical을 하나의
  v0.4 release evidence로 닫는다.
- **실행(§10.6.1~§10.6.4):** product semantics와 frozen denominator는 그대로 구현했지만,
  Attempt 1의 proxy measurement를 철회하고 combined actual witness와 corrected receipt를 추가했다.
- **PIVOT 근거:** critic Q2 FAIL이 trigger이었고, amendment는 test-only actual two-scope
  three-way append/cold replay + receipt node binding이다. Status §2.2.3에 trigger/amendment를 동기화한다.

제품 semantics/manifest/threshold는 바꾸지 않았으며 외부 migration, M3 loop, benchmark, product
multi-agent는 추가하지 않았다.

## 10.6.7 Claim mode — MIXED

Pre-spec은 `4b0d0a17ad1b9e43c741bd334b67e897cfeecd77`
(`2026-08-12 00:29:00 +0900`), 첫 product/data commit은
`f5d55ad11cb6bb2381cf8dd27c0ce9d1bed2a1eb` (`00:44:31 +0900`)이다.

| 청구 row | mode | timestamp/handling evidence |
|---|---|---|
| frozen disposition 14 + legacy 6 + external/upgrade/release criteria | CONFIRMATORY | pre-spec `4b0d0a1` < first data `f5d55ad`; manifest SHA `b61da8…b2a7`; `git diff 4b0d0a1 -- tests/fixtures/program_memory/v3/m2d-manifest.json` 0 bytes |
| external writer delta 0 | CONFIRMATORY | absolute digest는 descriptive; precommitted pre/post bytes·mode·symlink equality만 outcome으로 사용 |
| combined actual two-scope durable three-way witness | EXPLORATORY | Attempt 1 Q2 FAIL 후 추가; frozen denominator/threshold를 바꾸지 않고 corrected receipt에 node `1/1`로 격리 |

Exploratory row는 frozen 14-case의 confirmatory 결과로 합쳐 청구하지 않고 correction witness로만
표시한다. Confirmatory-grade 후속 청구는 independent critic/audit 후에도 frozen rows에만 한정한다.

## 10.6.8 Divergence diagnosis — RESULT-INVALID (Attempt 1)

제품 결과가 예상과 달랐던 것이 아니라 Q2 측정이 standalone three-way와 durable two-way를 합쳐
durable three-way로 청구한 runner coverage 오류였다. 따라서 Attempt 1 receipt/북극성 반영을 철회하고,
actual two-scope Claim retrieval→registered Proposal→Context→append→cold replay test를 추가해 재측정한다.
Contract/분모는 바꾸지 않으므로 REQUIREMENT-WRONG이 아니며, 예상 밖 product 동작도 아니므로
GENUINE-FINDING이 아니다. Invalid Attempt 1 `712+115`는 status §12 북극성 근거에서 제외하고,
corrected commit `9dbb413`의 `713+115`/durable `1/1`만 별도 재측정 결과로 사용한다.

## 10.7 Residual issues

- M3 DecisionPacket/FSM이 disposition을 실제 next proposal/synthesis에 소비하는 것은 M3-A/B다.
- Actual external live pilot/migration은 v0.5 이후다. NS6 unseen learning effect는 여전히 미측정이다.
- Product multi-agent는 NS6 통과 이후다.

## 10.10 Next action

Corrected remeasurement(`9dbb413`, receipt `f1ab646`)과 critic reverify는 PASS했다. Paired
status/pipeline을 candidate 5/5로 동기화한 뒤 independent seven-pass audit을 실행한다. Audit
PASS 뒤에만 M2-D/parent M2를 close하고 M3-A DecisionPacket pre-spec을 연다.
