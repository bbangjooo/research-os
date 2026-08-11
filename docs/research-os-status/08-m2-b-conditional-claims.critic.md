# Critic — Phase 08 (2026-08-11) — M2-B Conditional Claims

영향 §북극성 행: NS1 무결성·권한 하위호환, NS3 Durable learning 객체

## Q1 [end-state-positioning]

M2-B가 NS3를 `3/4→4/4`로 만들고 §8.4의 `conditional Claim graph`를 구체화했다는 증거는
무엇이며, NS4 retrieval이 `0/4`인 채로 단순한 “M2-A origin cache + 해시된 자유 텍스트”를
learning memory로 과대평가하지 않는가?

**Response:**

DIRECT. Before M2-B는 M2-A origin cache뿐이었다. After `529283c`는 immutable Claim과 six typed
edges, four measured reducers를 같은 canonical ProgramLog에서 replay한다. Exact same Claim bytes가
active→contested/superseded와 observed→replicated derived state를 가진다. NS3은 candidate `4/4`지만
audit 전 stable advance는 보류하고, NS4 retrieval은 그대로 `0/4`다.

## Q2 [milestone-positioning]

§9.4 M2-B의 다섯 exit conjunct 각각에 독립적인 case/test/replay 근거가 연결되어 전부 `5/5`일
때만 CLOSE하고, 하나라도 실패하면 기준 대체·약화 없이 ADVANCE로 남는가?

**Response:**

DIRECT. Phase §08.9가 다섯 conjunct를 각각 frozen case와 direct replay에 연결한다. Current label은
`ADVANCE — candidate 5/5`; 이 critic이나 뒤 audit에서 한 항목이 무효면 CLOSE하지 않는다.

## Q3 [proxy-vs-real]

§08.7의 최강 반례를 깨려면 동일한 immutable Claim bytes가 관계와 적용 조건에 따라 서로 다른
effective state 또는 no-write rejection을 만든다는 어떤 사전 고정 counterfactual이 “형식화된
문장”이 아니라 조건부 지식임을 입증하는가?

**Response:**

DIRECT. Cases 13~16과 mixed-precedence direct test는 immutable Claim body가 supports에서는 유지,
contradicts에서는 contested, supersedes에서는 superseded, independent replication에서는 replicated가
됨을 보인다. Cases 17~18, 20~25는 duplicate/unknown/supersession/scope 반례를 no-write한다.

## Q4 [boundary]

Claim·applicability·evidence·relation·snapshot 전체에서 exact key/version/ID/digest, 초기
`active/observed`, bounded text와 literal `authorized_action=null`을 재귀 검사하고 missing/extra
key·bool version·unknown enum·파생 상태 선기입·non-null authority가 ProgramLog와 projection에
모두 0건 쓰이는가?

**Response:**

DIRECT. Strict parsers가 Claim/applicability/evidence/relation/ClaimSnapshot의 exact keys, literal v1,
stable IDs/full digests, bounded text, initial active/observed와 derived enums를 검사한다. Frozen 1~5,
strict snapshot forgery direct test와 recursive scan `10/0 non-null`이 product log delta 0/null authority를
재현한다.

## Q5 [external-validation]

현재 M2-A `OriginEvidenceRef`가 terminal/artifact/seal 전체를 직접 담지 않는 상황에서,
`append_claim`이 locked external project prefix를 replay하여 Diagnosis sequence/ID/hash·body digest,
terminal experiment/ID/hash, artifact의 전체 ordered set과 각 ID/digest/event ID/hash, evaluation
seal·compatibility를 비교하며 omission·addition·reorder·substitution도 no-write로 막는다는 사전 고정
검사는 어디에 있는가?

**Response:**

DIRECT. `ProgramStore.append_claim`은 project shared lock 아래 linked Origin head prefix를 replay하고
Diagnosis sequence/id/hash/digest, terminal triple, artifact 전체 ordered set, hypothesis class/scope/seal/
compatibility를 대조한 뒤 ProgramLog append한다. Cases 6~12와 direct omission/addition/reorder/
substitution four tests가 no-write이며 `audit_claims`가 저장 뒤 같은 external replay를 반복한다.

## Q6 [counterfactual]

`supports/contradicts/supersedes/replicates`의 혼합 순서에서도 `superseded > contested > active`와
`replicated > observed`가 deterministic replay되고, supersession 전후 원본 Claim canonical
bytes/digest가 동일하며 second successor·cycle·self/unknown edge가 log delta 0이라는 반증 검사가
있는가?

**Response:**

DIRECT. Four reducers와 mixed precedence가 `superseded > contested > active`,
`replicated > observed`를 deterministic replay한다. Case 19는 원본 canonical bytes/digest 불변,
20~21은 second successor/cycle, relation parser는 self edge, case 18은 unknown, case 17은 duplicate를
log delta 0으로 거절한다.

## Q7 [sample-dependence]

독립 replication 성공과 실패를 한 요소씩 바꾸어 비교해 source role=`replication`, 서로 다른
origin·exact scope identity·manifest digest와 동일 hypothesis class·seal·compatibility를 모두
요구하고, 이름만 다른 동일 manifest·같은 scope의 다른 origin·다른 class/seal/compatibility를 각각
fail-closed하는가?

**Response:**

DIRECT with LIMITATION. Case 16은 frozen M1 contract에 실제 replication baseline/registration/terminal/
Diagnosis를 append하고 두 exact origins를 ProgramStore로 link한다. Same statement/class/seal/compatibility,
source role replication, distinct scope identity/manifest/origin일 때만 PASS한다. Cases 22~25와 direct
class/statement/parser checks가 one-factor failures를 차단한다. 서로 다른 manifest digest 내부의
row-level 중복은 이 layer가 판별하지 못하고 upstream manifest disjointness에 의존한다.

## Q8 [claim-mode-discipline]

Commit `5659c67`이 첫 product implementation·observer result보다 앞서 schema, source hashes, 25 case
IDs/operations/expected를 고정했다는 chronology와, 실제 25/25 literal operation 실행·skip/fallback
0·post-result denominator 변경 0을 함께 증명할 수 있으며 하나라도 깨지면 CONFIRMATORY 청구를
철회하는가?

**Response:**

DIRECT. Chronology는 `5659c67` pre-spec/25 cases → `cf20578` saved critic → `529283c` product/test다.
First result `6 failed, 26 passed`는 폐기하고 기준 변경 없이 writer error boundary/helper를 고쳤다.
Final literal `25/25`, focused+direct `33`, full `668+115`, skip/fallback 0이며 frozen manifest bytes와
25 case ID/operation/expected의 post-result 변경은 0이다. 이 chronology가 깨지면 CONFIRMATORY를
철회한다.

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
