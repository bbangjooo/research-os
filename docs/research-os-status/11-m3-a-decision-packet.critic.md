# Critic — Phase 11 (2026-08-12) — m3-a-decision-packet

영향 §북극성 행: NS1. 무결성·권한 하위호환, NS5. 단일 자율 루프 완결성

범위 메모: M3-A의 비신뢰 provider→DecisionPacket→current-state validation seam만 평가한다. FSM
transition, event persistence, experiment 실행, crash-resume, 학습 효과는 M3-B~D이며 NS5는
이 phase에서 `0/7`을 유지해야 한다.

## Q1 [proxy-vs-real]

실제 M2 `ProgramStore.snapshot()`·ClaimSnapshot·Context v3·retrieval·registered Proposal·disposition에서
packet을 만든 뒤 provider가 모든 내부 digest를 함께 위조한 self-consistent echo는
`DECISION_PACKET_INVALID`, canonical Context나 Program head를 실제 append로 전진시킨 packet은
`DECISION_PACKET_STALE`이 되는 어떤 vertical이 current state 재계산을 증명하는가?

**Response: DIRECT.** `tests/test_m3a_decision_packet.py::_harness` imports M2-D `_real_vertical` and
builds actual ProgramStore/ClaimSnapshot/Context v3/registered Proposal/disposition. Frozen rows
`reject-forged-program-snapshot` and `reject-stale-program-head` respectively reseal a self-consistent forged
snapshot and perform an actual `append_knowledge_disposition`; focused command in the receipt returns `41 PASS`,
with exact invalid/stale codes and post-attempt log bytes equality.

## Q2 [measurement-gap]

Candidate가 bounded canonical body로 정규화되어 그 digest가 Proposal에 exact bind되고, Proposal의
generation/class/scope가 현재 Context scientific state와 Program binding에 active하며 closed class·inactive
generation·wrong scope를 기존 registration preflight와 동일하게 mutation 0으로 거절함을 어떤
dry-run 재현 명령으로 증명할 것인가?

**Response: DIRECT.** `protocol.py::_validate_current_proposal` recomputes candidate digest, active
generation/class/scope/role/intervention and calls the existing registration preflight on current state. Frozen
rows `reject-candidate-digest-mismatch`, `reject-proposal-{generation,class,scope}-mismatch` plus
`test_closed_class_uses_existing_registration_preflight_without_log_mutation` all pass in
`.venv/bin/python -m pytest -q tests/test_m3a_decision_packet.py` → `41 passed`; project/program bytes stay exact.

## Q3 [counterfactual]

Port parity가 같은 parser를 두 번 호출한 대리 검증이 아님을, 실제 Python Protocol provider와 실제
spawned argv subprocess가 byte-identical value-only request를 받아 canonical packet bytes·validator 결과를
일치시키고 duplicate/non-finite JSON·extra stdout·timeout·output overflow에서 exact transport code와
descendant process cleanup을 보이는 증거는 무엇인가?

**Response: DIRECT.** `_provider_parity` invokes an actual Python callback and an actual spawned
`provider_fixture.py` argv process, compares independently recorded canonical request bytes, canonical packet
bytes, and validator objects. Frozen transport rows cover duplicate key, extra stdout, timeout, overflow;
`test_subprocess_nonfinite_json_is_protocol_invalid` adds non-finite JSON and the timeout row verifies the child
PID disappears. All are part of receipt `32/32` and focused `41`.

## Q4 [boundary]

NS1 authority 청구를 위해 `ProviderDecisionRequest`와 Python callback 인자를 재귀 검사해
service/store/log/workspace/path/callable reference 0과 모든 `authorized_action=null`을 확인하고, nested
non-null authority·extra key·bool-number·duplicate JSON을 fail-closed하며 모든
accept/reject/timeout 경로의 ProjectLog·ProgramLog bytes delta 0을 보이되 same-process Python provider
자체는 sandbox가 아니라는 한계를 어디에 명시할 것인가?

**Response: DIRECT.** Frozen `provider-no-direct-capability` recursively scans the callback value and returns
forbidden capability `0`, authority non-null `0`; focused supplemental tests reject nested authority, extra key,
bool-number, duplicate/non-finite JSON, Path/callable and prove recursive immutability. Frozen accept/reject/
timeout handlers compare both log byte strings. The receipt records authority/write `0`; phase §11.1, §11.6.1,
§11.7 explicitly state that same-process Python is not a sandbox.

## Q5 [end-state-positioning]

Pipeline §8.4 Context/Autonomy를 이번 phase가 구체화한다는 청구는 “provider output을 current
canonical state에 대해 검증 가능한 kernel input으로 바꾸다”까지여야 하는데, packet
acceptance가 event·disposition·experiment를 append/run하지 않고 NS5를 `0/7`로 유지하면서도
실제로 새로 가능하게 한 관찰 가능한 행동은 무엇인가?

**Response: DIRECT.** The observable new behavior is exact accept vs `DECISION_PACKET_INVALID` vs
`DECISION_PACKET_STALE` vs transport-code classification for provider output against current canonical state,
with no append/run. Phase §11.6.5 and status NS5 explicitly keep `0/7`; pipeline Context/Autonomy can therefore
be marked “validated provider→preflight seam” only, while event/FSM/run/diagnosis/synthesis remain M3-B/C.

## Q6 [milestone-positioning]

M3-A를 `CLOSE`하려면 frozen 32개 ID가 fallback·상수 PASS 없이 literal operation/result에 전부
소비되고 `8/8`, `24/24`, 네 exit conjunct가 각각 재현 근거를 가져야 하는데,
critic·audit 전 `ADVANCE`를 유지하고 M3-B를 차단하며 이 증거를 NS5 transition 진척으로
세지 않음을 어떤 receipt와 상태표로 판별할 것인가?

**Response: DIRECT.** `m3a-decision-packet-receipt.json` lists all 32 literal IDs and PASS results, aggregates
`8/8`, `24/24`, `4/4`, authority/write 0 and NS5 `0/7`; `CASE_HANDLERS` exact set equality prevents fallback.
Phase §11.6.4 and status §2.3 keep M3-A `ADVANCE`, `closed-by —`, critic/audit pending, and M3-B blocked. Only
both independent gates may change that dynamic row to CLOSE.

## Q7 [claim-mode-discipline]

`CONFIRMATORY` 청구를 유지하려면 pre-spec `50ee73d`와 manifest SHA `a43ba5…47a2`가 첫
product·port 실행·packet 결과보다 앞서고 32 IDs·schema·error classes·threshold·expected outcomes가
이후 0-byte 변경이어야 하는데, 이 chronology/diff를 무엇으로 증명하고 critic/result-triggered
witness나 contract 수정은 어느 행을 `EXPLORATORY` 또는 `PIVOT/MIXED`로 강등할 것인가?

**Response: DIRECT.** Receipt chronology records pre-spec `50ee73d` 02:13, critic `221c7b7` 02:17, first
product `eb289c4` 02:38; `sha256sum` is `a43ba5…47a2` and
`git diff --exit-code 50ee73d -- tests/fixtures/autonomy/v1/m3a-manifest.json` exits 0. Phase §11.6.6~8 and status §2.2.4 label the
result-triggered historical v0.4 gate correction PIVOT/EXPLORATORY while frozen 32 rows remain CONFIRMATORY;
the phase is MIXED.

## Q8 [divergence-diagnosis]

사전 예상 `32/32`, conformance `8/8`, rejection `24/24`, M3-A `4/4`, full `≥713+115`, authority
non-null 0, product multi-agent false 중 하나라도 어긋나거나 stale/invalid code가 뒤바뀐 때 어떤
관측으로 `REQUIREMENT-WRONG`, `RESULT-INVALID`, `GENUINE-FINDING`을 구분하고 각 갈래가
correction phase, 청구 철회·재측정, EXPLORATORY holdout 중 무엇을 자동 발동하는가?

**Response: DIRECT.** Phase §11.6.8 and receipt preserve the only divergence: first full `4 failed,
751+115` is `RESULT-INVALID` because a historical verifier compared current M3 HEAD to the sealed v0.4 tree;
the claim is withdrawn, verifier corrected, and same command remeasured `757+115`. §11.4 already fixes the
decision rule: misaligned criterion triggers `REQUIREMENT-WRONG` + correction phase; demonstrable runner/data
contamination triggers withdrawal/re-measurement; a valid unexpected result triggers `GENUINE-FINDING` +
EXPLORATORY holdout. No frozen M3-A case diverged.

## Independent verify verdict — PASS

- Questions: `8`; DIRECT verified `8`; failed `0`; reproducibility `8/8` matched.
- Focused `41`, release + M3-A `58`, frozen/receipt `32/32`, manifest hash/diff PASS.
- End-state Cycle 11 row, M3-A ADVANCE/prerequisite, MIXED chronology, RESULT-INVALID exclusion PASS.
- Product/test/script diff after measured checkpoint `42c7557`: none.
