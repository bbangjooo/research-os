# Critic — Phase 13 (2026-08-12) — m3-c-crash-resume

영향 §북극성 행: NS5. 단일 자율 루프 완결성, NS1. 무결성·권한 하위호환

## Q1 [proxy-vs-real]
`resume-*-call-started`가 deterministic fixture의 재호출 성공을 exactly-once recovery로 오인하지 않도록, 호출마다 다른 packet을 반환하는 nondeterministic provider에서 output 반환 후 capture 전 crash와 capture 후 crash를 분리해 전자는 reservation 재충전 없이 한 번만 재호출되어 canonical truth가 하나만 남고 후자는 절대 재호출되지 않으며 외부 billing exactly-once는 청구하지 않음을 어떻게 증명할 것인가?

**Response: DIRECT.**
`test_m3c_nondeterministic_provider_capture_boundary` uses a provider whose Diagnosis/Claim changes on every call.
The four exploratory rows crash both kinds before and after durable capture: pre-capture restarts invoke once under
the original reservation; post-capture restarts invoke zero times; all five truth-owner semantic counts remain one.
Receipt `exploratory_witnesses.nondeterministic_provider_capture_boundary` records `4/4`. As §13.7 states, a crash
before local capture can repeat an external bill; external billing exactly-once is explicitly not claimed.

## Q2 [measurement-gap]
Frozen crash denominator `13`이 보호하기 쉬운 checkpoint 목록이 아니라 실제 side-effect/commit seam의 완전한 분할임을, provider-return→capture, service registration→terminal, terminal→disposition/link, Diagnosis→origin/link, Claim→synthesis-link, next/stop derive→append 각각에 대해 process-death 후 새 service/store/loop 인스턴스가 같은 raw logs를 여는 매핑표로 보이고 특히 registration은 있으나 terminal은 없는 service 중간 상태를 누락하지 않았음을 어떻게 입증할 것인가?

**Response: DIRECT.**
The 13 manifest checkpoints map literally to provider start/capture, experiment start, terminal, disposition,
Diagnosis, origin, Claim, next and stop seams through `_CrashLoop`; every case constructs a new service, ProgramStore,
provider and loop over the same raw logs. The critic-driven
`test_m3c_service_registration_without_terminal_recovers_publicly` additionally kills the actual ResearchService
immediately after `EXPERIMENT_REGISTERED`; cold public recovery creates exactly one
`RECOVERED_INTERRUPTED_RUN` terminal and the episode completes. Thus the frozen denominator is unchanged while the
unrepresented internal service seam is an explicit exploratory completeness witness.

## Q3 [counterfactual]
복구 성공이 경쟁 writer가 없는 우연한 순서 때문이 아님을, captured synthesis·started experiment·truth-owner reuse의 lookup과 append 사이에 Project generation 또는 Program head를 한 단계 진전시키는 one-factor race를 주입해 stored old head를 current head로 세탁하지 않고 `AUTONOMY_RECOVERY_STALE` 또는 `AUTONOMY_RECOVERY_EVIDENCE_INVALID`, provider/service 추가 호출 0, Project/Program write delta `0/0`, semantic truth count 각 1을 재현할 수 있는가?

**Response: DIRECT.**
Frozen stale rows inject one factor each after the persisted cutpoint: proposal Program head, experiment generation,
recovered registration projection binding, or captured-synthesis Program head. `test_m3c_frozen_case` observes exact
`AUTONOMY_RECOVERY_STALE`/`AUTONOMY_RECOVERY_EVIDENCE_INVALID`, provider/service call zero where applicable, and
post-mutation Project/Program delta `0/0`. Exact Claim recovery is accepted only when its event is the immediate
successor of the stored request head and is still the current head; it cannot launder a later writer.
The Attempt 1 correction adds `test_m3c_lookup_to_append_race_fails_closed_without_controller_write`: a callback
advances Project generation or Program head after recovery lookup but before service/disposition/Claim append.
All three rows return `AUTONOMY_RECOVERY_STALE`, make zero restarted provider/service calls, make zero controller
writes after the competing writer, and preserve all existing terminal/disposition/Diagnosis/origin/Claim counts.

## Q4 [boundary]
NS1의 authority·forbidden-operation 0이 문자열 키 검색이나 고정 상수 proxy가 아님을, captured output·state·Context·packet·Diagnosis·synthesis·Claim의 adversarial nested non-null authority를 실제 parser/reducer가 거절하고 public exports와 controller/provider의 reachable runtime call graph에서 alias·`getattr`·injected object를 포함한 service/store/log/path/callable 및 deploy/merge/trade 실행 경로가 0임을 어떤 executable evidence로 보일 것인가?

**Response: LIMITATION.**
Frozen authority rows recursively scan Context, DecisionPacket, every Autonomy event, Diagnosis request, synthesis
request/packet, and Claim; all non-null counts are zero. The exploratory adversarial test forges nested authority in
three actual parsers and `provider_output_captured`, proving rejection before log-byte change. Forbidden rows parse
the controller AST for direct/name/`getattr` calls and public exports; an injected provider exposing callable
`deploy`, `merge`, and `trade` then completes an episode with counters `0/0/0`. This proves the three prohibited
controller operations, but not capability isolation from a hostile in-process Python provider: the test provider
itself retains a ProgramStore to construct fixtures. §13.7 therefore limits the claim to cooperative provider code;
service/store/log/path sandboxing is not claimed by M3-C.

## Q5 [end-state-positioning]
§8.4 Autonomy를 finite-but-incomplete에서 canonical cold-restart 가능 episode로 실제 구체화하되 외부 provider billing exactly-once·distributed consensus·학습 품질은 여전히 불가능한 것으로 남기고 Context/Program memory와 NS6/NS7의 rating을 올리지 않았음을 §13.6.5와 pipeline §8.5 Cycle 13의 전후 행동·세 truth-owner 경계·잔여 갭으로 어떻게 동기화할 것인가?

**Response: DIRECT.**
§13.6.5 records the before/after behavior and keeps Context/Program ratings fixed: Autonomy moves from committed-only
replay to canonical cold restart across AutonomyLog orchestration, ProjectLog scientific truth, and ProgramLog memory
truth. §13.7 preserves external billing, distributed consensus and learning-quality gaps. Pipeline §8.5 now records
Cycle 13 as `구체화·검증 (MIXED correction)`: only Autonomy crash recovery moves; Context/Program and NS6/NS7 do not.
The paired status remains `ADVANCE`, critic correction active, and M3-D blocked until re-verification and audit.

## Q6 [milestone-positioning]
M3-C를 `CLOSE`하려면 frozen 31개 literal ID가 fallback 없이 각각 실행되어 actual cold reopen `13/13`, terminal/disposition/Diagnosis/origin/Claim semantic count 각 1, stale `4/4` no-write, recursive authority `6/6`, reachable forbidden callable `3/3`을 동시에 만족하고 M3-B prerequisite와 두 independent gate를 통과해야 하는데 §13.6.4는 이를 어떤 handler·command·receipt 행에 일대일 매핑하며 그 전까지 M3-D를 어떻게 차단할 것인가?

**Response: DIRECT.**
`tests/test_m3c_crash_resume.py` has one literal handler per manifest group and asserts all 31 unique IDs, exact group
denominators and raw manifest SHA. Receipt frozen rows map `13/13`, duplicate `5/5`, stale `4/4`, authority `6/6`,
forbidden `3/3`; corrected focused is `41` and adjacent M3-A/B/C is `142`. The M3-B prerequisite is `08327ad`.
Receipt records critic Attempt 1 FAIL and audit pending; phase/status use the valid `ADVANCE` label, keep M3-D blocked,
and contain no M3-D data.

## Q7 [claim-mode-discipline]
Frozen 31·cutpoint 정의·stale code·LOC cap을 `CONFIRMATORY`로 청구하려면 pre-spec `22190bf`가 첫 product/data commit보다 이르고 manifest SHA/bytes가 그대로임을 어떤 git 명령과 timestamp로 증명하며, M3-B footprint `2,043` retain 결정에 대한 M3-C product `<=900`, tests `<=1,400`, inclusive `<=2,800` 후속 결과와 critic/result 뒤 추가된 witness 또는 cap miss를 §13.6.7에서 어떤 `EXPLORATORY` 행으로 분리해 필요시 `MIXED`로 강등할 것인가?

**Response: DIRECT.**
`git show -s --format='%H %cI' 22190bf 5291945 7394246` proves `06:14:30` pre-spec and `06:16:37` critic questions
precede first product/data at `06:37:22`; `shasum -a 256` remains `c3752c…65e27c7b`. Corrected product churn is
`294+59=353 <=900`; tests+fixture `778+51=829 <=1,400`; current inclusive before audit is `1,644 <=2,800`.
§13.6.7 labels
the frozen 31/caps CONFIRMATORY and the three critic-driven witness families EXPLORATORY, so the phase is `MIXED`.

## Q8 [divergence-diagnosis]
사전 예상 `31/31`, M3-C `5/5`, duplicate truth 0, stale `4/4`, authority·forbidden callable 0 또는 세 LOC cap 중 하나라도 어긋나면 §13.6.8에서 fixture/runner 오염만 `RESULT-INVALID`로 철회·재측정하고, cutpoint·recovery 요구 자체의 결함은 `REQUIREMENT-WRONG` correction phase로, nondeterminism·race·footprint의 유효한 예상 밖 동작은 `GENUINE-FINDING`/EXPLORATORY holdout으로 보내는 판정 증거와 자동 후속 행동은 무엇인가?

**Response: DIRECT.**
§13.6.8 classifies the Attempt 1 lookup→append witness gap and boundary error translation as
`GENUINE-FINDING`/EXPLORATORY; the frozen denominator and requirement remain unchanged. Future fixture/runner
contamination requires `RESULT-INVALID` withdrawal and rerun; a faulty recovery requirement requires a new frozen
`REQUIREMENT-WRONG` correction phase. No category is silently rebaselined, and the correction blocks close until
re-verification and audit.

## Verify Attempt 1 — 2026-08-12

**VERDICT: FAIL**

### Unaddressed questions (each blocks PASS)

- **Q1 [proxy-vs-real] — invalid response annotation.** `DIRECT + LIMITATION` is not one of the three permitted
  annotations (`DIRECT`, `LIMITATION`, `OUT-OF-SCOPE`). The executable evidence itself matched: the focused suite
  passed `38/38`, and `test_m3c_nondeterministic_provider_capture_boundary` covers all four diagnosis/synthesis ×
  pre/post-capture rows. Required fix: use one valid annotation. If the local exactly-once claim is retained and the
  external-billing boundary remains explicitly residual, `DIRECT` is the supported annotation.
- **Q3 [counterfactual] — DIRECT evidence does not reproduce the question's demanded interleaving.** The four frozen
  stale cases mutate Program generation/head after the crash but before the new loop starts recovery
  (`tests/test_m3c_crash_resume.py:413-435`). None injects a competing write *between recovery lookup and guarded
  append*. The expected-head production guard is relevant code, but it is not the claimed executable one-factor race
  witness. Required fix: add a deterministic lookup→append interleaving witness with the requested stable error,
  zero additional provider/service calls, `0/0` post-mutation Project/Program writes, and unchanged semantic truth
  counts; alternatively answer `LIMITATION` and link an exact §13.7 residual.
- **Q4 [boundary] — invalid response annotation and incomplete DIRECT surface.** `DIRECT + LIMITATION` is not a
  permitted single annotation. The tests verify recursive authority rejection, AST/public-export absence for the
  three named operations, and injected `deploy/merge/trade` counters `0/0/0`; they do not establish zero reachable
  `service/store/log/path/callable` capability across a hostile provider. In fact the test provider retains
  `self.store` (`tests/test_m3b_finite_autonomy.py:265-278`), consistent with §13.7's cooperative-provider
  limitation. Required fix: answer `LIMITATION` with the existing residual (or supply the broader executable
  capability-isolation evidence before answering `DIRECT`).
- **Q5 [end-state-positioning] — pipeline Cycle 13 row is absent.** §13.6.5 is present and preserves the named
  exclusions, but `docs/research-os-pipeline.md` §8.5 ends at Cycle 12. The response promises a future sync; verify
  mode requires the current cycle row now. Required fix: append the Cycle 13 §8.5 row and make its delta, three
  truth-owner boundary, unchanged Context/Program/NS6/NS7 ratings, and residual gaps agree with §13.6.5.
- **Q6 [milestone-positioning] — invalid milestone label.** §13.6.4 says `CLOSE CANDIDATE`, while verify mode accepts
  only `ADVANCE` or `CLOSE`. The same section and receipt say critic/audit are pending, so `CLOSE` is premature even
  though frozen engineering evidence is `5/5`; M3-B prerequisite `08327ad` and M3-D blocking are correctly recorded.
  Required fix: label the current claim `ADVANCE` until both independent gates pass, while retaining the five-conjunct
  evidence and M3-D block.

### Verified responses

- **Q2:** matched. The 13 literal frozen cutpoints use cold service/store/provider/loop reopening, and the separate
  actual-`ResearchService` registration-without-terminal witness is present and passed.
- **Q7:** matched. `22190bf` (`2026-08-12T06:14:30+09:00`) and `5291945`
  (`06:16:37+09:00`) precede `7394246` (`06:37:22+09:00`); manifest SHA is
  `c3752c811e44cebd7c542a3653ee19c8c5d2b2b7c1daf11a9a11b23565e27c7b` and is unchanged. Product churn is
  `254+59=313`; tests+fixture are `657+51=708`; the reported inclusive pre-receipt total is `1,283`.
- **Q8:** matched. §13.6.8 exists, says final divergence is `해당 없음`, and specifies the required automatic action
  for each future divergence branch without using an invalid result to advance a claim.

### Independent reproduction

- `.venv/bin/pytest -q tests/test_m3c_crash_resume.py` → `38 passed in 67.87s`.
- `.venv/bin/pytest -q tests/test_m3b_finite_autonomy.py tests/test_m3c_crash_resume.py` →
  `98 passed in 155.59s`.
- `shasum -a 256 tests/fixtures/autonomy/v1/m3c-manifest.json` → exact frozen SHA above.
- `git diff --exit-code 22190bf..9398129 -- tests/fixtures/autonomy/v1/m3c-manifest.json` → exit `0`.
- `git diff --numstat 22190bf..7394246 -- src/research_os/autonomy/loop.py` → `254 59`.
- `wc -l tests/fixtures/autonomy/v1/m3c-manifest.json tests/test_m3c_crash_resume.py` → `51 + 657 = 708`.

### Gate audit trail

- Questions: `8` | verified: `Q2,Q7,Q8` | failed: `Q1,Q3,Q4,Q5,Q6`.
- 3-cycle LIMITATION escalation: none; the two compound annotations are invalid annotations, not accepted
  `LIMITATION` responses.
- End-state: §13.6.5 present `Y` | pipeline §8.5 Cycle 13 present `N` | vision-loosening trigger `N/A`.
- Claim mode: `MIXED` | pre-spec timestamp < first-data timestamp `Y` | frozen manifest unchanged `Y`.
- Divergence: `해당 없음` | branch-action mapping present `Y`.
- Milestone: M3-C exists `Y` | M3-B prerequisite closed `Y` | valid `ADVANCE/CLOSE` label `N` |
  M3-D bypass `N`.

M3-C remains open. Do not start M3-D until a corrected closed-set re-verification returns `PASS` and the independent
audit also passes.
