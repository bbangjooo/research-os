# Critic — Phase 09 (2026-08-11) — m2-c-deterministic-retrieval

영향 §북극성 행: NS4. Program memory 정확도, NS1. 무결성·권한 하위호환

## Q1 [proxy-vs-real]
NS4의 exact oracle이 fixture ID dispatch나 인조 `ClaimSnapshot` 대조가 아님을, frozen candidate와 다른 Claim ID를 실제 `ProgramStore.append_claim/append_relation`으로 기록·rebuild한 snapshot도 동일 public reducer가 의미대로 검색하는 재현 명령으로 어떻게 증명할 것인가?

**Response:** _DIRECT_
`test_real_program_vertical_context_and_canonical_head_stale_no_write`가 frozen aliases와 다른 canonical IDs를 actual `append_claim/append_relation`으로 기록·rebuild하고 public `retrieve_claims`에서 active/contradiction을 exact 확인한다; focused `4 PASS`.

## Q2 [measurement-gap]
NS4의 네 수치가 limit 이후의 편리한 부분집합이나 0 분모로 100%가 되지 않도록, 네 query 각각의 expected/returned TP·FN·irrelevant FP·superseded leak 수와 exact order·empty·shuffle 판정을 어떤 단일 machine-readable receipt로 공개할 것인가?

**Response:** _DIRECT_
`uv run --python 3.12 --no-project env PYTHONPATH=src python tests/test_m2c_deterministic_retrieval.py`의 single JSON receipt가 per-query TP/FN/FP/leak/order/empty/shuffle와 totals `11/11`, `3/3`, `0/2`, `0/14`를 출력한다.

## Q3 [boundary]
Contradiction recall 100%가 relation expansion 오염을 숨기지 않도록, 미요청 relation·역방향 edge·base-relevant가 아닌 target·superseded source·중복 endpoint·class/compatibility 불일치를 각각 한 요인만 바꿔 active/contradiction 결과 0건 또는 exact 불변으로 만드는 경계 증거는 무엇인가?

**Response:** _DIRECT_
`test_relation_expansion_boundaries_are_one_factor_and_deduplicated`가 empty requested relations, reverse, irrelevant target, superseded source, duplicate endpoint, class/compatibility mismatch를 각각 바꿔 exact empty/unchanged/deduplicated 결과를 검증한다.

## Q4 [measurement-gap]
NS1 하위호환을 유지하면서 Context v3가 실제 Program head를 bind한다는 것을, 수동 문자열 변조가 아니라 canonical ProgramLog append로 head를 전진시킨 stale case와 project token·query digest·result digest 단일 변이 각각의 fail-closed·log/file no-write, memory 미지정 legacy byte-exact 동일성으로 어떻게 증명할 것인가?

**Response:** _DIRECT_
Real vertical test가 canonical third Claim append로 head를 전진시키고 project/query/result/context token one-factor stale와 각 validator 전후 ProgramLog bytes 동일을 확인한다. `retrieval=None`과 omitted legacy Context는 canonical bytes exact다.

## Q5 [end-state-positioning]
Pipeline §8.4의 `Program memory`와 `Context` 행이 단지 독립 retrieval 함수 추가에 머물지 않고 실제로 “relevance + contradictions”를 제공하도록, canonical ProgramLog→`ClaimSnapshot`→retrieval→Context v3 packet의 한 vertical path에서 exact Claim·contradiction·limitation·reason과 검증 가능한 manifest를 관찰하는 증거는 무엇인가?

**Response:** _DIRECT_
같은 real vertical에서 ProgramLog→ClaimSnapshot→retrieval→`build_agent_context_v3`를 실행해 exact Claim/contradiction/limitations/reasons와 result digest를 packet에서 관찰하고 validator가 canonical recomputation으로 승인한다; phase §09.6.5와 pipeline Cycle 09에 반영했다.

## Q6 [milestone-positioning]
M2-C를 `CLOSE`하려면 §09.6.4에서 다섯 exit conjunct 각각을 독립 재현 근거와 함께 ✅로 만들고 critic·audit PASS 전에는 M2-D를 계속 차단해야 하는데, 네 NS4 산술을 하나로 뭉치거나 disposition·release 증거로 대체하지 않았음을 어떤 표와 명령으로 판별할 것인가?

**Response:** _DIRECT_
Phase §09.6.4가 다섯 conjunct를 `11/11`, `3/3`, `0/2`, `0/14+exact`, stale PASS로 분리한다. 현재 label은 audit 전 `ADVANCE`이고 M2-D blocked이며 critic+audit PASS 뒤에만 `CLOSE`한다.

## Q7 [claim-mode-discipline]
`CONFIRMATORY` 청구를 유지하려면 pre-spec `e6de927`이 첫 product 구현·첫 결과 노출 commit보다 시간상 앞서고 frozen fixture hash·query/filter/order/expected sets가 결과 후 0-byte 변경이어야 하는데, 그 chronology와 diff를 무엇으로 증명하며 critic-driven witness나 contract 수정 발생 시 어느 행을 `EXPLORATORY` 또는 `PIVOT/MIXED`로 강등할 것인가?

**Response:** _DIRECT_
Phase §09.6.7과 `git log`가 `e6de927 23:32:05 < bc0b79a 23:44:00`; frozen SHA `dd638d…d81`, `git diff e6de927 -- retrieval-v1.json` 0을 고정한다. Contract/result-triggered 변경 0이라 CONFIRMATORY이며 발생 시 §09.5 규칙대로 PIVOT/MIXED다.

## Q8 [divergence-diagnosis]
사전 예상인 네 query exact PASS·NS4 `100/100/100/0`·stale matrix PASS·legacy byte-exact·authority non-null 0·no-write 중 하나라도 어긋날 때, 어떤 관측으로 `REQUIREMENT-WRONG`, `RESULT-INVALID`, `GENUINE-FINDING`을 구분하고 각 갈래가 contract correction, 청구 철회·재측정, EXPLORATORY holdout 중 어느 후속 행동을 자동 발동하는가?

**Response:** _DIRECT_
Phase §09.6.8은 관측 일치로 `해당 없음`이며, 불일치 시 contract/분모 오류→REQUIREMENT-WRONG correction, 측정 오염→RESULT-INVALID 철회·재측정, 실제 예상 밖 동작→GENUINE-FINDING+EXPLORATORY holdout을 고정한다.
