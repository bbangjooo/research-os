# Critic — Phase 04 (2026-08-10) — m1-d-diagnosis-class-frontier

> Status: **FINAL CORRECTED VERIFY PASS — M1-D EXPLORATORY; independent progress audit PASS**

영향 §북극성 행: NS1, NS2, NS3

## Q1 [measurement-gap] — Diagnosis schema와 evidence binding이 exact·replay-safe한가?

**First review: FAIL.** Full artifact equality를 문서에 선언했지만 omission/extra/empty/order attacks가 없어 subset-accepting implementation을 잡지 못했다. 동일 Diagnosis 재제출의 idempotent service success와 duplicate persisted event replay failure도 race oracle에서 충돌했다. Terminal corpus의 `decision`은 actual `Decision.to_dict()` 9 fields가 아니라 quantitative subset이었다.

Revision response: terminal corpus는 exact 9-field Decision으로 고정하고, artifact full-set negative를 추가한다. Public service의 concurrent identical request는 success 2/event 1/idempotent reuse 1/error 0이며, canonical history에 Diagnosis event가 둘 존재하는 corruption만 replay `DIAGNOSIS_ALREADY_RECORDED`다.

**Response:** _DIRECT_ — final negative four paths `460/460`, exact 10-field observation,
Artifact/Decision/Result binding, extra-key와 bool-number corruption witnesses, direct service
idempotency/replay tests가 PASS했다. Phase §04.5 final evidence와 `tests/test_m1d_state.py`,
`tests/test_m1d_service_cli.py`가 근거다.

## Q2 [proxy-vs-real] — Control과 conclusive rejection 정의가 authority를 탈취하지 않는가?

**First review: PASS.** Baseline/golden만 registration 밖 control이고 diagnostic scope는 scientific이다. `HARD_CONSTRAINT_FAILED`는 certified gate-definition snapshot이 replay 가능해질 때까지 negative Diagnosis로만 보존하고 class count는 0이다.

**Response:** _DIRECT_ — taxonomy `26/26`의 positive 7/zero 19와 direct margin/gate
single-axis counterfactual이 kernel truth만 count함을 재현했다. Agent narrative와
`is_control:true`는 disposition authority가 아니다.

## Q3 [boundary] — Pending, stop, successor generation 정책이 deadlock·laundering 없이 일관적인가?

**First review: FAIL.** `STUDY_STOPPED`를 Diagnosis validation보다 앞세우면 UNTRUSTED terminal이 자신에게 필요한 Diagnosis를 영구 차단한다. Budget/all-classes stop이 genuinely changed successor까지 막는 정책은 M1-B의 frozen generation-local budget/change-control contract와 충돌했다.

Revision response: stop은 active-generation registration/retry/frontier만 막고 required Diagnosis append에는 적용하지 않는다. Pending과 active nonterminal이 해소되면 M1-B exact predecessor/change reason/new sealed contract를 만족하는 successor를 허용하며, unchanged/stale/missing-reason rules는 그대로 유지한다.

**Response:** _DIRECT_ — pending `23/23`, gate `37/37`, successor reset 3행과 direct
recovery/preflight/race tests가 stopped Diagnosis append, active-nonterminal priority와 genuine
successor를 exact 검증했다.

## Q4 [counterfactual] — ClassState transition과 support predicate가 total·deterministic한가?

**First review: FAIL.** Evidence partition 문구가 class-local이 아니었고, full-state oracle이 empty/conclusive만 다뤄 provisional/replicated/inconclusive/mixed partition을 증명하지 못했다. Supported predicate도 positive margin과 zero failed gates를 요구하지 않았으며 unsupported-parent counterfactual이 부족했다.

Revision response: partition을 hypothesis-class-local exhaustive union으로 고치고 네 추가 full literal states를 고정한다. Shared support predicate는 exact terminal+Decision, verified primary improvement, positive margin, zero failed hard/support gates, no top-level error, active/latest/open/diagnosed conjunction이다. Invalid/undiagnosed/superseded/incompatible/closed/generic parent negatives를 추가한다.

**Response:** _DIRECT_ — full states `54/54`, limits 2·3·4 N-1/N/post-close,
immutable closure origin과 replicated support persistence가 exact replay되고 closed registration은
거절된다.

## Q5 [end-state-positioning] — Semantic frontier와 stop projection을 raw evidence에서 독립 파생하는가?

**First review: FAIL.** Positive oracle가 pre-derived `eligible_nodes`를 입력으로 받아 eligibility/maturity를 시험하지 않았고 successful child가 소비해야 할 parent가 pool에 없어 exclusion이 vacuous했다. Stop case도 precomputed reason을 주입했다.

Revision response: raw typed terminal/Decision/Diagnosis/class/scope evidence pool에서 support, maturity, child consumption, actions를 파생한다. Consumed parent를 pool에 포함하고 direct/failed-direct/grandchild/unrelated counterfactual을 고정한다. Stop은 UNTRUSTED terminal 전후 Diagnosis, budget ledger, closed ClassState에서 파생한다.

**Response:** _DIRECT_ — 20 exclusion axes/21 subcases, membership-derived corruption witness,
positive 5→ordered 3, caps 1·2·3·4·7과 retry allowlist-free positives가 PASS했다. 이는 pipeline
§8.4 Study inference를 `△→○`로 구체화하며 §8.2 행동을 제거하지 않는다.

## Q6 [claim-mode-discipline] — Oracle이 hidden scenario나 expected self-echo 없이 실행 가능한가?

**First review: FAIL.** Required manifest가 없고 transition input이 scenario labels여서 support code가 hidden histories를 만들 여지가 있었다.

Revision response: transition input은 ordered literal event histories로 바꾸고 expected state는 계속 full literal로 유지한다. Manifest 28 operations는 `{operation,input}`만 observer에 전달하고 `id`/`expected` access와 literal case dispatch를 금지한다.

**Response:** _DIRECT_ — declarative-only observer schema, selector-free operation+input dispatch,
literal `26/23/54/37/7`, expected-corruption witnesses와 correction fixed point가 PASS했다.
Post-implementation correction이므로 phase §04.6.7은 EXPLORATORY로 고정했고 invalid 결과를
북극성 evidence에서 제외했다.

## Q7 [external-validation] — Compatibility와 null authority가 보존되는가?

**First review: conditional PASS.** Frozen v1/M1-C parity, context v2/branch-conclusion v1 무변경, generic Finding 비추론, recursive null authority 경계는 위 schema/state defects가 닫히는 조건에서 적절하다.

**Response:** _DIRECT_ — M1-C exact `20/20`, v2 final seals, four public state paths × 19
keys, M1-D recursive authority non-null 0과 single regression floor를 별도로 재현했다.

## Q8 [milestone-positioning] — Claim chronology와 M1-D 다섯 conjunct가 정당한가?

**First review: FAIL.** Manifest/seal/product observer가 없고 위 oracle holes가 남아 independent pre-spec PASS나 confirmatory checkpoint를 청구할 수 없었다.

Revision gate: revised phase + all supporting fixtures + manifest raw/sorted-compact seal에 대해 independent critic이 Q1–Q8 전부 PASS해야 docs/fixture-only pre-spec commit을 만든다. 그 commit이 첫 product/result-bearing commit보다 앞서지 않으면 M1-D는 `EXPLORATORY`로 강등한다.

**Response:** _DIRECT_ — historical invalid measurements는 철회했고 final claim은
EXPLORATORY다. Pipeline §9.4 M1-D의 다섯 conjunct가 phase §04.6.4에 각각 exact evidence와
함께 `CLOSE`로 매핑되며 M1-C prerequisite는 closed다. Single floor는 `real 598.21s`, tests
`>=442`, subtests `>=111`, ruff/ty/diff PASS다.

## Re-review

**Second fixture review: FAIL.** Evidence corpus 재작성은 canonical Event `49/49`, history `9/9`, ArtifactRecord `4/4`, exact Diagnosis `5/5`, negative `63×4=252`와 독립 감사 PASS로 첫 결함을 닫았다. 그러나 transition oracle은 다음 직접 증거가 빠져 있었다: active typed nonterminal successor 차단, closed-class first/retry 및 all-classes global priority, `BUDGET_EXHAUSTED`·`ALL_CLASSES_CLOSED` literal stop state, explicit conclusive conjunction, non-empty retry frontier, 초기 다섯 race의 canonical pre/final history. Schedule label과 pre-derived predicate만으로는 hidden setup과 permissive reducer를 잡지 못하므로 product implementation은 계속 금지한다.

Revision response: transition denominator를 보존하지 않고 늘린다. 위 stop/gate/retry 상태를 full literal history/state로 추가하고, countable positive는 every predicate를 명시하며, 일곱 race 모두 canonical precondition history·serialized operation event/no-write·full final state/head/digest를 가진다. 이 수정과 manifest seal 뒤 Q1–Q8 independent re-review가 전부 PASS해야 한다.

**Third narrow fixture review: FAIL.** Repaired transition은 `12/14/27/7`로 확대됐지만 successor 두 race request가 expected에만 남은 self-echo와, evidence matrix가 permissive Decision/Result/Artifact attribute·owner 구현을 잡지 못하는 gap이 발견됐다. ArtifactRecord history mutation 다섯 건은 pre-terminal event rehash 뒤 `terminal_evidence`를 갱신하지 않아 intended artifact axis보다 terminal hash mismatch가 먼저 나는 dependency defect도 있었다.

Final revision response: race schedule 14행 전부를 literal `{operation,request}`로 만들고 string row를 0으로 고정했다. Evidence matrix는 Decision 3, terminal authority 1, ResultEnvelope 2, same-digest ArtifactRef attribute 5, nested ArtifactRef 2, ArtifactRecord 5, gate order/duplicate 2를 더해 `83×4=332`로 확대하고 모든 dependency를 canonical rehash했다. Evidence와 transition의 별도 final-byte auditor는 각각 PASS했다. Manifest는 28 unique operation, supporting raw SHA 7개, request-only observer/expected stripping을 고정했다.

**Fourth full policy review: FAIL.** 최초 manifest raw SHA
`5b5af6da72dfea896d79e09f8c56b64586f0789a07575d044be960638ef39664`를
대상으로 한 Q1–Q8 재검토에서 chronology와 기존 canonical corpus 자체는 재현됐지만,
다음 bad implementation들이 oracle을 통과할 수 있음이 확인됐다.

- Q1: `ArtifactRecord.role`/metadata exactness, same-experiment different-body service
  rejection, trimmed Unicode scalar와 literal boolean parser가 완전히 관찰되지 않았다.
- Q2: conclusive conjunction의 single-axis flips와 narrative/kernel-truth 불일치가 없어
  agent `failure_type`/`recommendation`을 authority로 쓰는 reducer가 통과할 수 있었다.
- Q3: pending/untrusted/stop ordering의 cardinality가 1이었고, 모든 terminal status의
  pending, budget/all-closed successor, active-nonterminal 및 retry precedence 일부가
  pre-derived flag에 의존했다.
- Q4: limit 3의 N-1/N, count가 closure 뒤에도 증가하는 transition, closed+supported와
  positive/negative orthogonality, provisional-but-no-unused-replication-scope가 빠졌다.
- Q5: contract frontier cap parameterization, support predicate single flips, retry 전용
  Diagnosis/generation/compatibility/retryable/class-local exclusions가 빠졌다.
- Q6: race input이 `pre_state`/digest를 받았고 gate matrix도 literal history/request가
  아니라 derived flags를 입력으로 받아 self-echo 구현이 통과할 수 있었다.
- Q7: compatibility oracle expected 23개 중 manifest가 15개만 exact 비교했다.
- Q8: Git chronology는 깨끗했지만 Q1–Q7 때문에 five-conjunct coverage와
  confirmatory checkpoint 자격은 성립하지 않았다.

감사 도중 supporting fixture가 수정돼 최초 manifest는 현재 workspace bytes를 더 이상
seal하지 않는다. 위 결함을 raw history/counterfactual로 수정하고 새 supporting hash와
manifest raw/sorted-compact seal을 만든 뒤 Q1–Q8 전체를 fresh review한다. 그 PASS 전에는
product implementation을 시작하지 않는다.

Q1 repair evidence: negative matrix를 기존 90개를 보존한 채 trimmed/non-trimmed
interpretation·falsifier 4개, escaped lone-surrogate pre-hash 2개, bool/int literal 경계
5개를 더한 `101×4=404`로 확대했다. Encodable 99개 mutation history의 734 Event는
독립 materialization/hash-chain 감사를 통과했고 surrogate 2개는 hash/ID/Event/append
attempt 0을 요구한다. Final-byte auditor는 raw
`06a3d667729d5de810b37e34e32a7305999b7da340349a24642789391692f5e2`를
PASS했다. 이 targeted PASS는 새 manifest 전체 Q1–Q8 PASS를 대신하지 않는다.

Pre-spec reachability correction: canonical active-generation history만으로는
`PROPOSAL_PARENT_COMPATIBILITY_MISMATCH` parent row를 만들 수 없다. Active typed
registration은 active seal compatibility와 exact해야 하고 successor generation은 registration
set을 reset하므로 predecessor parent는 먼저 `PROPOSAL_PARENT_MISMATCH`다. Corrupt history나
expected-fed parent view를 executable evidence로 위장하지 않고, M1-D literal matrix에서는
predecessor mismatch를 관찰하며 compatibility code는 기존 M1-C injected-state defense-in-depth
regression에서 보존한다. Final critic은 이 reachability correction과 metadata를 검토해야 한다.

Q5 repair evidence: raw frontier를 sealed cap 2 counterfactual, shared support predicate
single-flip 6축, retry 전용 5축(닫힌 class 포함), failed replication으로 모든 preregistered
scope가 소진된 open/provisional ClassState, 양수 잔여 elapsed/cost가 다음 reservation보다
작은 budget stop까지 확대했다. Main 12 raw node의 supported 7/consumed 2/semantic leaf 5와
5→3 order는 유지되고 cap 2는 같은 eligible 5에서 exact 2를 반환한다. Final-byte raw
`e7f6af8ab68ffdaf9519330eb31807d726c694da190d7eeb79fd19829ac20ab3`,
20 exclusion axes/21 subcases, stop 6, declared observer hash 15/15를 독립 감사했다. 이
targeted PASS 역시 새 manifest 전체 fresh review를 대신하지 않는다.

Transition final-byte 분할 감사 중 fixture 값은 일치했지만 재현 규칙의 표현 결함 두 개를
찾았다. 저장소는 public RFC-8785-style `sha256_json`과 Event/stable-ID용 kernel compact
canonical encoder를 구분하므로, ClassState digest와 모든 pre/post/final state digest가 전자를
사용한다고 phase에 명시했다. 또한 public append/replay/projection/observer는 참조 여부와
무관하게 전체 loose Mapping history를 exact Event parse + hash-chain verify한 뒤 reducer에
전달하도록 고정했다. Frozen transition bytes와 expected 값은 바꾸지 않았으며, 독립 재계산
532 Event hash, 81 Diagnosis digest/ID, 128 ClassState digest/ID, 110 typed identity,
57 state digest가 모두 일치했다. 이는 targeted cryptographic PASS이며 semantic/Q1–Q8 전체
PASS를 대신하지 않는다.

Transition reseal correction: 최초 분할 감사에서 supported replication 성공 요청의
`budget_debit.attempts`가 fixture backfill 중 2로 오염되어 appended payload의 1과 불일치한
실제 oracle defect를 발견했다. Product code/result 전이므로 해당 expected를 관찰 결과에
맞춘 것이 아니라 요청을 sealed contract의 single-attempt debit 1로 고치고 event/hash/state를
재계산했다. 거절 parent의 malformed lower-axis `attempts=2` precedence input은 그대로다.
새 raw `8311b101ced44d75e8e4ccde902d58abcdb9b06edf199987731d010084145e4a`,
public `sha256_json` `26f9fb7f4657e6059162104f2d0e21d89c66cd0d9e35e137f66785b235e8ebba`
exact bytes에 대한 fresh independent audit는 PASS했다: cases 90 = full 20/terminal 9/
taxonomy 24/gate 30/race 7, Event 532/532, full state digest 64/64, ClassState 128/128,
contextual binding 83/83, recursive authority null 1,354/1,354, gate accepted/rejected 5/25,
race operation row 14/14 literal object. 이 역시 최종 manifest Q1–Q8 review를 대신하지 않는다.

## Fifth full-policy review — FAIL

Manifest raw `c45d9157c671ca3b84747d671431048c94bf4121c89434a0750f2c26bc7d5547`,
sorted-compact/public digest
`0d056d193a3a70cad032986dccc14ca4e662b3cf57d3f482b990e1a2b1b54f44`,
transition raw `8311b101ced44d75e8e4ccde902d58abcdb9b06edf199987731d010084145e4a`
exact snapshot에 대한 fresh independent critic은 Q7만 PASS하고 Q1–Q6/Q8을 FAIL했다.
Chronology/product diff 0, supporting raw hash 7/7, strict JSON 8/8, compatibility expected
23/23, authority null은 모두 재현됐으나 다음 permissive implementation이 살아남았다.

- Q1: Decision `status/reason_code/primary_metric`, observation의 나머지 quantitative/bool/gate,
  artifact evidence의 `artifact_id/digest/event_id/event_hash`를 각각 무시하는 validator.
- Q2/Q4: non-empty all-passed gate를 거부하고 empty gate만 count/support하는 reducer.
- Q3: generic `COMPLETED`만 terminal로 보고 나머지 generic/alias를 무시하거나, stopped
  Diagnosis append exemption을 UNTRUSTED에만 적용하는 service. Minimal STATUS_CHANGED의
  normalized/default observation도 미정이었다.
- Q4: configured class limit을 3으로 cap하고 replicated support를 후속 negative에서 낮추는
  reducer. 문서의 class-open shared predicate와 post-close support expected도 서로 충돌했다.
- Q5: frontier cap 2/3만 특수 처리하고, elapsed+cost가 동시에 부족할 때만 budget stop하며,
  retryable status를 TIMED_OUT/INFRA_FAILED로 allowlist하는 reducer.
- Q6: manifest selector/gate ID/race scenario label을 읽어 raw history/product 실행 없이 aggregate
  expected를 반환하는 observer. Race verb도 scenario 의미를 노출했다.

추가 adversarial review는 direct margin-zero taxonomy, limit 4 이상, elapsed-only/cost-only/
reservation equality, pure budget/all-closed pending precedence와 Diagnosis append, stopped+pending
successor, `INSUFFICIENT_EVIDENCE`/`CANCELLED` retry positives를 보강하도록 요구했다. 이전
snapshot은 checkpoint seal이 아니다. Product code는 계속 0변경이며, union defect를 raw literal
counterexample로 고친 새 supporting/manifest bytes에 대해 Q1–Q8 전부 fresh PASS해야 한다.

## Sixth full-policy candidate — awaiting fresh review

Fifth-review의 permissive survivors를 다음 raw counterexample로 닫았다.

- Q1: 기존 101 negative를 보존하고 Decision 3, observation 7,
  ArtifactEvidenceRef 4의 individual single-axis binding attack을 추가했다. 합계는
  `115×4=460`, encodable mutation 113, materialized Event 832, pre-hash surrogate 2다.
- Q2: direct margin-zero positive count와 non-empty all-passed hard/support gate의 count/support
  positive를 추가했다. Taxonomy는 26행(positive 7, zero 19)이다.
- Q3: generic canonical status 6, alias 7, RUNNING nonterminal control 1을 literal history로
  추가했다. Missing observation defaults와 normalized status를 exact 고정하고 UNTRUSTED뿐 아니라
  budget/all-classes stop 중에도 required Diagnosis append가 성공하는 gate를 포함했다.
- Q4: support base predicate에서 lifecycle을 분리하고 execution parent만 class-open을 더한다.
  Configured limit 4 boundary 3행, post-close support 2행, replicated support persistence 3행,
  post-close successful replication 1행을 full state로 고정했다.
- Q5: cap `1,2,3,4,7`, attempt/retry limits 각각 5개, elapsed-only/cost-only/positive-shortfall/
  equality budget cases, `INSUFFICIENT_EVIDENCE`와 `CANCELLED` retry positives를 추가했다.
  Candidate-scope는 terminal outcome과 무관하게 registration 시점에 소비하며 retry는 새 pair를
  만들지 않는 action derivation 두 건을 고정했다.
- Q6: manifest input의 `gate_ids`, race selector, required operation 목록을 제거했다. 28개
  case는 28개 operation으로 전체 literal fixture를 관찰하며, frontier literal observer input/hash
  46행과 race display-ID/label rename invariance 7행을 포함한다.
- Q7: 기존 compatibility expected 23/23와 recursive authority null을 유지했다.
- Q8: baseline `a5f232d` 이후 tracked product diff는 0이고, 현재 candidate는 문서와 v3 fixture만
  포함한다. Fresh PASS와 checkpoint 전에는 product implementation을 시작하지 않는다.

Candidate seal:

- supporting raw: contract
  `58d3c416c9ce98c336fe888bccf19859a6e5c789d85306b93492a7cabd0a30f3`, terminal
  `e3623748815bdba58feb399a1dab55399917e80e11894eb981572af9a08cc20f`, valid Diagnosis
  `3c9394d0ee2ccc06b6e21dbca403dfc6b4e0e3264ffc43e13cc39c5673462336`, negative
  `112a77493182354637ece0dd405dcca8a4093aee876f75af58f1bde437ae4fb4`, transition
  `e526f2c2aab968cdd1d0777719ecf992216ac9469864354b4b51586987a15951`, frontier
  `66c34953a9f2e0259e4be3c00fe24c92e8213685fff3f00f02ba93e97fa75cc5`, compatibility
  `4f3f79cc593a51b5f1f33b3501f966496bc91f37cde33f2f745f26518c64b597`.
- manifest raw
  `950096a8f1b4c4c46f42329d1ee77a16d741c678eba6108544280b01031f0a97`, public
  `sha256_json` `6f72ec9fc9ece754e40c1be6598e50eeddd9cc053338ebc2ce97a1e9872136ea`.

이 절은 repair response이지 verdict가 아니다. 아래 fresh reviewer가 Q1–Q8을 전부 독립
재현해 PASS할 때만 status와 checkpoint 자격을 갱신한다.

## Sixth full-policy review — PASS

Fresh independent critic은 exact manifest raw
`950096a8f1b4c4c46f42329d1ee77a16d741c678eba6108544280b01031f0a97`, public
`sha256_json` `6f72ec9fc9ece754e40c1be6598e50eeddd9cc053338ebc2ce97a1e9872136ea`
snapshot을 재계산하고 Q1–Q8 전부 PASS했다.

| Q | verdict | independent evidence |
|---|---|---|
| Q1 | PASS | strict JSON 8/8, terminal 23/119 Events, valid Diagnosis 18/112 extended Events, negative 115에서 Decision 3·observation 10·ArtifactEvidenceRef 4 individual axes, encodable 113/832 Events + surrogate 2 |
| Q2 | PASS | taxonomy 26/26 = positive 7/zero 19; direct margin 0, non-empty all-passed hard/support gates, diagnostic/control/narrative counterfactual 포함 |
| Q3 | PASS | canonical terminal 14 + alias 7 + RUNNING control, literal gates 37에서 UNTRUSTED/budget/all-closed stopped Diagnosis와 pending/stop/successor precedence 재현 |
| Q4 | PASS | full states 54/54, ClassState 108, configured limits 2·3·4와 limit-4 N−1/N/N+1, post-close support/replication/persistence 재현 |
| Q5 | PASS | raw 12→supported 7→consumed 2→leaves 5→selected 3; caps 1/2/3/4/7, independent/equality budget, INSUFFICIENT_EVIDENCE/CANCELLED retry, registration-time scope consumption 재도출 |
| Q6 | PASS | dispatched input 221개에서 semantic selector leakage 0, 28 cases/28 operations, frontier observer hashes 46/46, race rename hashes 7/7와 10 success/4 failure/9 append |
| Q7 | PASS | compatibility 23/23, supporting raw seal 7/7, recursive `authorized_action` 3,129 keys/non-null 0 |
| Q8 | PASS | HEAD `a5f232d`, tracked product diff 0, diff-check PASS; full run의 non-interrupted 441 tests+111 subtests와 외부 SIGTERM된 sole nested harness clean rerun 1/1로 frozen snapshot 442/442 composite PASS, ruff/ty PASS; five conjunct direct coverage |

**Overall verdict: PASS.** Exact defect는 없다. 이 snapshot은 docs+fixture-only pre-spec
checkpoint 자격이 있으며, 그 checkpoint commit이 생성되기 전에는 product implementation을
시작하지 않는다. 최초 full run의 sole failure는 제품 assertion이 아니라 검증 중 잘못 종료한
nested regression subprocess의 return code `-15`였고, 같은 exact case를 간섭 없이 재실행해
`1 passed in 256.08s`를 얻었다. 이 provenance를 숨기거나 단일-command 442 PASS로 표현하지
않는다.

Checkpoint realized: commit `091af241524e8ebdba657bc29758c5234fd9d501`, parent
`a5f232d4e44d3b5aa04ae36990db5230f3c1a4e1`, tree
`fc342a8443ea96b458b9f83753db6545db98287f`, time
`2026-08-10T22:53:51+09:00`. 이 checkpoint는 phase/critic docs와 v3 JSON fixture만
포함하고 product source/test implementation은 0이다. 이후 product result가 oracle defect를
드러내면 expected를 관찰 결과에 맞추지 않고 `RESULT-INVALID`/correction chronology를 적용한다.

## Post-checkpoint implementation discovery — RESULT-INVALID

첫 product reducer replay는 frozen full states 50/54를 byte-for-byte 일치시켰지만 다음 literal
contradiction을 발견했다. 이는 expected state 차이가 아니라 canonical input이 기존 frozen
parser/identity를 통과하지 못하는 prerequisite defect다.

- `retry-frontier-latest-chain-full-state`: 두 Diagnosis body가 phase와 parser의 exact enum
  `mechanism|implementation|evidence|constraint|operational|supported` 밖
  `failure_type="execution"`을 사용해 `DIAGNOSIS_INVALID`다.
- `class-b-limit-four-n-minus-one-open`, `class-b-limit-four-exact-threshold-close`,
  `class-b-limit-four-post-close-n-plus-one-preserves-origin`: contract digest는
  `e9078daf…`로 바뀌었지만 generation ID는 이전 `generation_5d412…`다. Existing M1-B
  `generation_id(project, null, contract.digest, seal.digest)`의 canonical 결과는
  `generation_1dcfe94c2c8299219dbf218d2b3f1f60`이므로 `STUDY_GENERATION_INVALID`다.
- Gate census 중 `superseded-parent-attempt-not-supported`도 forbidden `execution` enum을,
  `stopped-all-classes-closed-allows-required-diagnosis` history는 등록된
  `base_allclosed_development` 대신 undeclared `base_m1d_development` baseline ID를 사용해
  terminal/Diagnosis gate 전에 `STUDY_SCOPE_BASELINE_REQUIRED`가 난다.

기존 Diagnosis parser와 M1-B generation identity로 root가 독립 재현했다. Fixture는 아직
수정하지 않았다. 분류는 `RESULT-INVALID`, claim mode는 `EXPLORATORY`이며, 전체 literal census와
minimal dependency rehash/re-ID correction-only checkpoint, 새 manifest/supporting seal, fresh
Q1–Q8 PASS 전까지 기존 sixth PASS는 result-bearing 권한이 없다. Product semantic output을
expected에 복사하거나 parser/identity를 약화하는 수정은 금지한다.

## Post-correction live-observer audit — RESULT-INVALID

Prerequisite fixture correction 뒤 실행한 anti-vacuity review는 기존 manifest `35/35`를
result-bearing evidence로 인정하지 않았다.

1. compatibility observer가 M1-C 20 operation 중 2개만 실행하고 나머지를 literal zero로
   채웠다.
2. transition observer가 request digest catalog에서 expected event identity/time/hash/output을
   선택해 accepted gate 7행과 race 7행의 독립 실행을 오염시켰다.
3. full state, gate/race final state/digest/head와 inner expected mutation을 실제 비교하지 않아
   corrupt expected가 그대로 통과했다.
4. terminal-pending 23행이 dispatch됐다는 count만 있고 reducer 실행은 0이었다.
5. frontier exclusion은 axis label로 count를 올렸을 뿐 해당 node가 실제 output에서 제외됐는지
   증명하지 않았다.

Catalog를 제거한 mismatch census는 accepted gate 7/7와 race 7/7의 arbitrary event
ID/timestamp/hash/head mismatch, Diagnosis append가 state에 남는 gate 3행의 state/digest mismatch,
successor gate 3행의 budget-reset delta mismatch를 재현했다. Rejected gate 30행에는 exact
path/details expected가 없어 stable error metadata claim도 관찰할 수 없다.

**Verdict: FAIL / RESULT-INVALID.** Input/pre-head-derived deterministic entropy/clock,
stdlib-only expected rebuild, all 23 pending executions, all inner exact comparisons and
counterfactual expected corruption tests를 고정한 새 transition/manifest seal이 필요하다.
Product output이나 expected catalog를 correction source로 쓰면 FAIL이다.

## Second-correction candidate — awaiting fresh verdict

Correction은 input/pre-head-only event entropy, exact gate error metadata, structural successor
budget reset, all gate/race state/head/delta를 stdlib-only script로 재생성했다. Full-state 54행의
normative expected는 exact state와 중복되던 78종 summary key를 제거하고 네 core key plus
separate full literal state로 축소했다. Counting 26행은 byte-for-byte 유지했다.

- transition raw:
  `28d9c2d7ac42432aea36562a916ec2c5bae07c4b07a4581cd7276c571328e24f`
- manifest raw:
  `e0eb0ea0083100397762f217b8f0470bc08c551e14f5420ba7240fab9062abe2`
- manifest public:
  `f6328c23f586d856ec57ecbf32f516f124f40cd3fffccededf65e673573f4aa7`
- executed transition rows: `26/23/54/37/7`; gate `37/37`, race `7/7`
- corruption/dispatch witnesses: `3/3`; transition manifest bindings `12/12`
- product focused: `110 passed, 4 subtests`; ruff/ty/diff PASS

Rejected gate 30행 중 duplicate Diagnosis만 `$.experiment_id` path가 contract-defined이고,
나머지 29 path는 under-specified 상태를 숨기지 않고 exact null로 고정했다. Details는 literal
input/state에서 독립 파생한다. 이 snapshot은 fresh anti-vacuity audit와 regression floor 전인
candidate이며 아직 PASS/CLOSE가 아니다.

### First anti-vacuity verdict — FAIL, repaired

Audit은 regression-child에서 actual M1-C `20/20`과 regression floor를 literal PASS로 바꾸는
두 fail-open guard, correction `--check`가 counting 26/terminal 23 expected corruption을
허용하는 결함, pending aggregate가 row equality가 아닌 census였던 결함을 재현했다.
두 guard를 제거하고 child-env counterfactual을 추가했으며, correction check가 두 domain의
semantic corruption을 거부하도록 보강했다. Pending aggregate는 independently derived pending
ID tuple을 23행 모두 비교하고 one-row mutation에서 `22/23`으로 실패한다.

Focused repair `5/5` 뒤 당시 intermediate manifest seal은 raw
`0f9be9397ac4ef8ff2ef47193d7d3d446f48f077f9412721b199c4e3b805ab83`, public
`5d0119f7fab7da5c7f8bc30b3582ba412a19f5babd8796f2dc3ac1e628ec0a47`다. 이전
`e0eb…`/`f632…` candidate는 FAIL provenance일 뿐 final seal이 아니다. Fresh audit와 floor
PASS 전까지 verdict는 계속 FAIL/open이다.

## Final corrected implementation verification — PASS candidate

이 절은 기존 closed Q1–Q8 질문에 대한 최종 verify response다. 새 질문을 만들지 않았다.
Current bytes는 v3 manifest raw `10e037678f49397a14b9f75bc0d8913da7a8f8ed8af8607b2c6f4751892e1718`,
public `c34efc9aeb5af9d83bd7325bc95cd948b4ba04de4ca7b773404a15100d28af78`,
transition raw `92551a101bfbdbf96c92673750335a70ccd5d1bf422dc7fd80df4feeae9e3c54`다.
Progress-critic verify는 session의 새 agent 생성 금지 때문에 root가 분리된 read-only pass로
수행했으며, 독립성 경계는 simulated다. Final cycle close는 별도 agent의 7-pass auditor가
판정한다.

| Q | response | current direct evidence |
|---|---|---|
| Q1 exact Diagnosis/evidence | **DIRECT** | exact 10-field observation, event/artifact/Decision/Result binding, negative four paths `460/460`, extra-key와 bool-number corruption reject, direct service/replay tests PASS |
| Q2 control/conclusive authority | **DIRECT** | taxonomy `26/26` = positive 7/zero 19; kernel disposition ignores narrative/control label and binds quantitative/gate truth |
| Q3 pending/stop/successor | **DIRECT** | pending `23/23`, gate `37/37`, successor reset 3행, stopped Diagnosis append와 active-nonterminal ordering, recovery re-gating direct tests PASS |
| Q4 ClassState/support | **DIRECT** | full state `54/54`, limits 2·3·4 N-1/N/post-close, immutable closure origin, replicated support persistence and closed registration reject |
| Q5 frontier/stop | **DIRECT** | 20 exclusion axes/21 subcases, membership-derived witness, positive 5→ordered 3, caps 1·2·3·4·7, retry eligibility without terminal allowlist |
| Q6 anti-self-echo | **DIRECT** | selector-free operation+input dispatch, observer declarative-only schema, `26/23/54/37/7` literal execution, corruption witnesses, correction fixed point PASS |
| Q7 compatibility/authority | **DIRECT** | M1-C exact `20/20`, v2 current seals, four public state paths × 19 keys, recursive non-null authority 0, M1-D bounded manifest PASS |
| Q8 chronology/five conjuncts | **DIRECT** | historical invalid results excluded and claim downgraded EXPLORATORY; five product conjuncts 5/5; single floor PASS `real 598.21s`, tests `>=442`, subtests `>=111`, ruff/ty/diff PASS |

Fresh four-pass anti-vacuity auditor와 narrow recursion auditor가 각각 PASS했고 product review의
actionable P0/P1/P2는 0건이다. Bounded manifest는 `56 passed, 2 deselected`, 제외된 두 row는
compatibility exact `20/20`과 단일 actual floor로 따로 증명됐다. Duplicate broad attempt는
중단 provenance로만 남기고 결과 증거에서 제외했다.

**Progress critic verify verdict: PASS (simulated independence).** Q1–Q8 응답은 모두 DIRECT이며
LIMITATION/OUT-OF-SCOPE escape는 없다. 이 verdict는 discipline auditor PASS를 대신하지 않는다.
