# Critic — Phase 08 (2026-08-11) — M2-B Conditional Claims

영향: NS1 무결성·권한 하위호환, NS3 Durable learning 객체.

## Q1 [end-state-positioning]

NS3 `3/4→4/4` 증거와 NS4 `0/4` 제한이 과대평가 없이 구분되는가? **DIRECT.** `529283c`는
immutable Claim, six typed edges, four measured reducers를 canonical ProgramLog에서 replay한다.
동일 Claim bytes의 effective state만 달라지며 NS3은 audit 전 candidate, NS4는 `0/4`다.

## Q2 [milestone-positioning]

다섯 exit conjunct가 모두 독립 증거를 가져야만 CLOSE하는가? **DIRECT.** Phase §08.9가 frozen
case/direct replay를 연결하며 critic/audit 중 하나라도 무효면 `ADVANCE — candidate 5/5`로 남는다.

## Q3 [proxy-vs-real]

조건부 지식을 입증하는 counterfactual은 무엇인가? **DIRECT.** Cases 13~16과 mixed precedence는
동일 body를 active/contested/superseded/replicated로 derive한다. Cases 17~18, 20~25는 invalid
relation/scope를 actual writer no-write한다.

## Q4 [boundary]

전체 strict schema와 null authority가 write 0으로 강제되는가? **DIRECT.** Frozen 1~5와 strict
Snapshot forgery test는 exact key/version/ID/digest, initial `active/observed`, bounded text를 검사하고
recursive scan은 `10/0 non-null`이다.

## Q5 [external-validation]

locked prefix가 complete evidence와 ordered artifacts를 검증하는가? **DIRECT.** `append_claim`과
`audit_claims`는 Origin/Diagnosis/terminal/artifact/class/scope/seal/compatibility를 exact replay한다.
Cases 6~12 및 real two-artifact omission/addition/substitution/reverse가 모두 writer no-write다.

## Q6 [counterfactual]

혼합 precedence, immutable supersession, invalid graph rejection이 deterministic한가? **DIRECT.** Four
reducers는 `superseded > contested > active`, `replicated > observed`; cases 17~21과 parser는 원본
bytes/digest 불변 및 duplicate/unknown/self/second-successor/cycle log delta 0을 증명한다.

## Q7 [sample-dependence]

replication independence를 한 축씩 반증하는가? **DIRECT.** Case 16은 real M1 positive control이고
`dbd7caa`는 wrong-role, same-scope/different-origin, same-origin/different-scope admission, class mismatch를
actual writer no-write로 분리한다. Row-level manifest 중복은 upstream disjointness에 의존한다.

## Q8 [claim-mode-discipline]

Frozen chronology/denominator/cap을 모두 지키는가? **DIRECT.** `5659c67` pre-spec → `cf20578` critic →
`529283c` product → `0418269` correction pre-spec → `dbd7caa` witness다. First `6F/26P`는 보존했고
final `25/25`, focused `37`, M2-A+B `59`, adjacent `96`, full `672+115`; frozen diff/skip/fallback은 0이다.
Original 25는 CONFIRMATORY, critic extras는 EXPLORATORY이며 chronology가 깨지면 청구를 철회한다.

## Verify Attempt 1 — FAIL

| Q | Verdict | Defect |
|---|---|---|
| Q1 | PASS | Claim/relation replay와 NS4 `0/4` 제한은 정확함 |
| Q2 | FAIL | Q5/Q7 evidence defect로 five-conjunct close가 아직 불성립 |
| Q3 | FAIL | cases 22~24가 pure reducer + constant `relation_delta=0` |
| Q4 | PASS | strict parser/snapshot/authority boundary 확인 |
| Q5 | FAIL | real multi-artifact external-prefix reorder witness 없음 |
| Q6 | PASS | immutable supersession/mixed precedence/error boundary 확인 |
| Q7 | FAIL | noncanonical response label과 one-factor independence matrix 누락 |
| Q8 | PASS | chronology/frozen denominator/LOC/worktree 확인 |

**VERDICT: FAIL.** Severity-1 correction은 actual ProgramStore no-write scope cases, real M1
two-artifact omission/addition/substitution/reorder, wrong-role/same-scope-different-origin/
same-origin-different-scope/class one-factor replication witnesses다. Attempt 1은 삭제하거나 PASS로
덮어쓰지 않는다.

## Verify Attempt 2 — FAIL

Exact cutoff: `dc21ecf` (correction pre-spec `0418269` → test-only witness `dbd7caa` →
candidate evidence `dc21ecf`). Attempt 1 FAIL은 위에 그대로 보존한다.

| Q | Verdict | Independent evidence |
|---|---|---|
| Q1 | PASS | canonical Claim/six typed edges/four reducers를 유지하고 NS4는 `0/4`로 유지 |
| Q2 | PASS | frozen five-conjunct mapping과 `ADVANCE`; 기존 acceptance 약화 없음 |
| Q3 | PASS | cases 22~24가 actual `ProgramStore.append_relation`을 호출하고 log bytes/relation count unchanged를 측정; focused `37/37` |
| Q4 | PASS | strict Claim/Snapshot replay와 recursive `authorized_action=null` 경계 유지 |
| Q5 | PASS | real locked M1 replication Diagnosis의 two-artifact set으로 omission/addition/substitution/literal reverse를 모두 `append_claim` no-write로 재현 |
| Q6 | PASS | immutable supersession, mixed precedence, prospective stable Claim error/committed corruption `IntegrityError` 경계 유지 |
| Q7 | PASS | case 16 positive control + wrong-role/same-scope-different-origin/same-origin-different-scope admission/class mismatch one-factor writer witnesses; response label은 단일 `DIRECT` |
| Q8 | FAIL | chronology, frozen 25 diff 0, MIXED mode, `672+115` evidence, external snapshot `3/3` unchanged는 일치하지만 unchanged total LOC cap은 불일치 |

Reproduction: focused `37 passed`; M2-A+B `59 passed`; collection `672`; frozen manifest
`5659c67..dc21ecf` diff 0; correction pre-spec 이후 product diff 0; 외부 snapshot은 v0.3
receipt와 exact 일치; cutoff worktree는 검증 전 clean이었다. Full `672+115` receipt은
`dbd7caa` 이후 product/test 변경 0과 current collection `672`로 chronology/plausibility를 확인했다.

Blocking defect: `c1a1851..dc21ecf` gross additions은 product `1,463`, tests+fixture
`1,241`, docs `426`(phase `257` + critic `133` + status core `24` + pipeline `12`), total
`3,130`이다. Category caps `1,500/1,250/500`은 통과하지만 correction pre-spec이 유지한
total cap `3,100`을 30줄 초과한다. Core docs를 제외한 `3,094`는 cap의 `docs`를
임의로 축소한 계산이므로 PASS 근거가 아니다.

**VERDICT: FAIL.** Q8/total-cap defect를 해소하고 동일 closed Q1~Q8로 재검증해야 한다.
