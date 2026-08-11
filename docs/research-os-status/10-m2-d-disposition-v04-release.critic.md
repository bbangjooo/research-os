# Critic — Phase 10 (2026-08-12) — m2-d-disposition-v04-release

영향 §북극성 행: NS1. 무결성·권한 하위호환, NS7. 기존 프로젝트 read-only 호환성

## Q1 [end-state-positioning]
Pipeline §8.4의 Program memory·Context를 실제로 구체화하려면 `ProposalKnowledgeDisposition`이 일회성 validator 반환값이 아니라 canonical Proposal registration과 함께 저장·replay되어 운영자가 사후 감사하고 M3가 소비할 수 있어야 하는데, 어느 log/event·reducer vertical이 그 내구성과 exact Proposal/retrieval binding을 증명하는가?

**Response:** _DIRECT_
`memory/program.py`의 two canonical v1 events와 reducer가 full Proposal/query/disposition을 replay하고
event 직전 Program prefix에서 retrieval을 재계산한다. `test_durable_disposition_replays_and_duplicate_is_no_write`
및 phase §10.6.1~§10.6.2가 append→rebuild→duplicate write 0 vertical을 고정한다.

## Q2 [proxy-vs-real]
Disposition `14/14`가 체크박스 대리 지표가 아님을, actual typed Proposal과 validated Context v3에서 retrieval을 재계산한 뒤 returned active/contradiction Claim 전체를 exactly once 덮고 Claim digest·role·relation·Proposal field refs가 하나라도 틀리면 그럴듯한 rationale가 있어도 registration/log write 0건이 되는 재현 명령으로 어떻게 증명할 것인가?

**Response:** _DIRECT_
Frozen `14/14`는 missing/duplicate/unknown, digest/role/relation/Proposal binding/ref/reason/authority/stale
한 요인마다 ProgramLog bytes delta 0을 검사한다. 여기에
`test_durable_three_way_disposition_replays_from_registered_proposal`이 actual development+diagnostic
scope/origin Claim 3개(active, contradiction, cross-scope)를 validated Context v3에서 재계산하고 canonical
registered Proposal에 `used|rejected|not_applicable`을 append한 뒤 cold `ProgramStore` replay exact 3/3을
검사한다. Corrected release gate는 이 node를 별도 1-pass field로 receipt에 bind한다.

## Q3 [boundary]
NS7의 opaque legacy 경계가 새 Claim으로 누출되지 않도록 Claim처럼 보이는 adversarial free text를 실제 append/replay한 뒤 ProgramLog bytes·legacy projection·Claim/relation snapshot을 함께 검사해 `typed_claim_ids=[]`, typed Claim/edge delta 0, raw substring 저장 0, digest·size만 보존됨을 어떻게 증명할 것인가?

**Response:** _DIRECT_
Frozen case `legacy-free-text-never-inferred`가 Claim처럼 보이는 adversarial bytes를 actual append/replay하고
`typed_claim_ids=[]`, Claim/relation snapshot delta 0, ProgramLog raw substring 0, digest/size exact을 검사한다.
Legacy matrix `6/6`과 strict forged/duplicate/extra/non-null no-write도 receipt에 bind됐다.

## Q4 [external-validation]
NS7 external `3/3`가 frozen fixture를 자기 자신과 비교하는 순환 검증이 아님을, 고정된 실제 `crypto-new`·`manager`·`BinancePredictionStrategy` 경로의 pre-state를 fixture와 독립 비교하고 verifier 전후 bytes·mode·symlink·entry aggregate가 동일하며 absent Binance `.research-os`가 끝까지 생성되지 않음을 어떤 증거로 확인할 것인가?

**Response:** _DIRECT_
`test_external_three_project_snapshot_is_independent_and_read_only`가 실제 sibling absolute paths를 frozen
baseline과 독립 비교한다. Single verifier는 그 뒤 별도 pre/post에서 bytes/entry + mode/symlink aggregate를
exact 비교했다. Receipt는 crypto `16/956a…`, manager `28/d689…`, Binance absent `0/5ad3…`, symlink 0과
metadata digests를 기록하며 Binance surface는 전후 absent다.

## Q5 [measurement-gap]
NS1의 단일 v0.4 release gate가 `full_suite=true` 같은 상수 receipt가 아님을, frozen 23개 case ID와 여섯 upgrade subcase를 각각 실제 outcome에 bind하고 sealed `0.3.0@e120292` 파일 검증·drift/unknown 거절·commit/publish 실패 후 전체 prior tree 복원·wheel temp-install·version/docs/full/authority/multi-agent 판정을 한 실행 receipt로 어떻게 증명할 것인가?

**Response:** _DIRECT_
Attempt 1 receipt는 Q2 결함으로 current tree에서 철회했고 checkpoint `ef2d9a2`에만 보존한다.
Corrected gate가 commit `9dbb413` 기준으로 PASS했고 receipt는 literal 23 IDs/results,
durable-three-way node `1/1`, upgrade six IDs/results, sealed 0.2/0.3 reconstruction, failures 전체 tree 복원,
full `713+115`, authority 0, product multi-agent false, version/docs/product tree, wheel hash와 temp-install
0.4.0을 한 실행에 묶는다. `test_v04_saved_receipt_binds_actual_case_results_and_release_surfaces`가
receipt commit의 product tree를 재계산해 PASS했다.

## Q6 [milestone-positioning]
M2-D와 parent M2를 `CLOSE`하려면 §10.6.4에서 다섯 AND conjunct 각각의 재현 근거와 critic·audit PASS가 필요하지만 NS7의 실제 external replay·opaque classification `3/3`은 M3-D에 남는데, synthetic legacy `6/6`이나 NS3/NS4 유지 회귀로 그 잔여를 숨기지 않고 M3-A만 정확한 M2-D close 뒤 활성화함을 어떤 상태표로 판별할 것인가?

**Response:** _DIRECT_
Phase §10.6.4는 다섯 M2-D conjunct를 각각 ✅ evidence로 분리하지만 critic+audit 전 label을
`ADVANCE`로 유지한다. Status §2.3도 M2-D active/M3-A open 상태를 audit PASS 전 보존한다. NS7 actual
external replay·opaque `3/3`은 §10.7과 M3-D exit에 남아 있으며 synthetic legacy `6/6`으로 대체하지 않는다.

## Q7 [claim-mode-discipline]
`CONFIRMATORY` 청구를 유지하려면 pre-spec `4b0d0a1`이 첫 product·external verification·release 결과보다 앞서고 frozen manifest hash·23 IDs·criteria·expected outcomes가 이후 0-byte 변경이어야 하며 external 절대 digest는 descriptive로만 남아야 하는데, 이 chronology와 diff를 무엇으로 증명하고 result-triggered 보강은 어느 행을 `EXPLORATORY` 또는 `PIVOT/MIXED`로 강등할 것인가?

**Response:** _DIRECT_
Phase §10.6.7과 `git log --reverse 4b0d0a1^..HEAD`는 pre-spec `00:29` < first product `00:44` <
release gate 순서를 보인다. SHA `b61da8…b2a7`과 `git diff 4b0d0a1 -- m2d-manifest.json` 0 bytes를
확인했다. Frozen 23 semantics/threshold와 external delta는 CONFIRMATORY지만, critic FAIL 후
추가한 combined durable three-way witness는 EXPLORATORY correction이므로 전체 행은 `PIVOT/MIXED`로
강등했다. External 절대 digest는 descriptive, pre/post delta만 confirmatory다.

## Q8 [divergence-diagnosis]
예상 `23/23`, disposition `14/14`, legacy `6/6`, external `3/3`·writer delta 0, upgrades `2/2`, full `≥676+115`, authority non-null 0, product multi-agent false, version `0.4.0` 중 하나라도 어긋날 때 어떤 관측으로 `REQUIREMENT-WRONG`, `RESULT-INVALID`, `GENUINE-FINDING`을 구분하고 각 갈래가 correction phase, 청구 철회·재측정, EXPLORATORY holdout 중 무엇을 자동 발동하는가?

**Response:** _DIRECT_
Attempt 1은 예상치가 맞았더라도 standalone three-way와 durable two-way를 합쳐 청구한
runner coverage 결함이어서 `RESULT-INVALID`로 판정했다. 따라서 receipt/북극성 청구를 철회하고
actual combined witness를 추가해 재측정한다. Contract/분모가 의도를 못 잡으면
REQUIREMENT-WRONG→correction, 정상 측정의 예상 밖 실제 동작이면
GENUINE-FINDING→EXPLORATORY holdout으로 별도 분기한다.

## Verify attempt 1 — FAIL

- Q1, Q3–Q8: evidence 정합.
- Q2: frozen standalone validator는 three-way였지만 durable actual registration vertical은
  `used|rejected`만 포함했다. Actual registered Proposal+validated Context+ProgramStore에서 active,
  contradiction, cross-scope Claim을 세 disposition으로 append하고 cold replay하는 증거가 없었다.
- Disposition: Attempt 1 receipt 철회, current M2-D open, combined durable test와 release binding 추가 후
  independent reverify.
