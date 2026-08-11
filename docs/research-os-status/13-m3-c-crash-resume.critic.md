# Critic — Phase 13 (2026-08-12) — m3-c-crash-resume

영향 §북극성 행: NS5 단일 자율 루프 완결성, NS1 무결성·권한 하위호환.

## Questions and final responses

### Q1 [proxy-vs-real]
`resume-*-call-started`가 deterministic fixture의 재호출 성공을 exactly-once recovery로 오인하지 않도록, 호출마다 다른 packet을 반환하는 nondeterministic provider에서 output 반환 후 capture 전 crash와 capture 후 crash를 분리해 전자는 reservation 재충전 없이 한 번만 재호출되어 canonical truth가 하나만 남고 후자는 절대 재호출되지 않으며 외부 billing exactly-once는 청구하지 않음을 어떻게 증명할 것인가?

**Response: DIRECT.** Nondeterministic Diagnosis/Claim의 pre/post-capture 네 행이 각각 restart provider call `1/0`, reservation recharge `0`, semantic truth count `1`을 증명한다. 외부 billing exactly-once는 §13.7의 명시적 limitation이다.

### Q2 [measurement-gap]
Frozen crash denominator `13`이 보호하기 쉬운 checkpoint 목록이 아니라 실제 side-effect/commit seam의 완전한 분할임을, provider-return→capture, service registration→terminal, terminal→disposition/link, Diagnosis→origin/link, Claim→synthesis-link, next/stop derive→append 각각에 대해 process-death 후 새 service/store/loop 인스턴스가 같은 raw logs를 여는 매핑표로 보이고 특히 registration은 있으나 terminal은 없는 service 중간 상태를 누락하지 않았음을 어떻게 입증할 것인가?

**Response: DIRECT.** Frozen 13은 `_CrashLoop`에서 각 seam을 literal ID로 소비하고 같은 raw logs를 새 service/store/provider/loop가 cold-open한다. 별도 actual `ResearchService` witness는 registration 직후 crash를 복구해 `RECOVERED_INTERRUPTED_RUN` terminal 하나를 만든다.

### Q3 [counterfactual]
복구 성공이 경쟁 writer가 없는 우연한 순서 때문이 아님을, captured synthesis·started experiment·truth-owner reuse의 lookup과 append 사이에 Project generation 또는 Program head를 한 단계 진전시키는 one-factor race를 주입해 stored old head를 current head로 세탁하지 않고 `AUTONOMY_RECOVERY_STALE` 또는 `AUTONOMY_RECOVERY_EVIDENCE_INVALID`, provider/service 추가 호출 0, Project/Program write delta `0/0`, semantic truth count 각 1을 재현할 수 있는가?

**Response: DIRECT.** `test_m3c_lookup_to_append_race_fails_closed_without_controller_write`가 experiment lookup→service, disposition lookup→append, Claim lookup→append 사이에 writer를 주입한다. 세 행 모두 `AUTONOMY_RECOVERY_STALE`, restarted provider/service call `0`, post-writer controller delta `0/0`, 기존 truth count 불변이다.

### Q4 [boundary]
NS1의 authority·forbidden-operation 0이 문자열 키 검색이나 고정 상수 proxy가 아님을, captured output·state·Context·packet·Diagnosis·synthesis·Claim의 adversarial nested non-null authority를 실제 parser/reducer가 거절하고 public exports와 controller/provider의 reachable runtime call graph에서 alias·`getattr`·injected object를 포함한 service/store/log/path/callable 및 deploy/merge/trade 실행 경로가 0임을 어떤 executable evidence로 보일 것인가?

**Response: LIMITATION.** Frozen recursive scan, actual parser/capture rejection, AST/public-export 검사와 injected `deploy/merge/trade` counters `0/0/0`은 세 금지 동작을 증명한다. Hostile in-process provider의 service/store/log/path capability isolation은 증명하지 않았고 cooperative provider만 §13.7에서 청구한다.

### Q5 [end-state-positioning]
§8.4 Autonomy를 finite-but-incomplete에서 canonical cold-restart 가능 episode로 실제 구체화하되 외부 provider billing exactly-once·distributed consensus·학습 품질은 여전히 불가능한 것으로 남기고 Context/Program memory와 NS6/NS7의 rating을 올리지 않았음을 §13.6.5와 pipeline §8.5 Cycle 13의 전후 행동·세 truth-owner 경계·잔여 갭으로 어떻게 동기화할 것인가?

**Response: DIRECT.** §13.6.5와 pipeline Cycle 13은 AutonomyLog orchestration, ProjectLog science truth, ProgramLog memory truth의 cold restart만 전진시키며 Context/Program/NS6/NS7 rating은 유지한다. 외부 billing, distributed consensus, hostile-provider sandbox, learning quality는 잔여 갭이다.

### Q6 [milestone-positioning]
M3-C를 `CLOSE`하려면 frozen 31개 literal ID가 fallback 없이 각각 실행되어 actual cold reopen `13/13`, terminal/disposition/Diagnosis/origin/Claim semantic count 각 1, stale `4/4` no-write, recursive authority `6/6`, reachable forbidden callable `3/3`을 동시에 만족하고 M3-B prerequisite와 두 independent gate를 통과해야 하는데 §13.6.4는 이를 어떤 handler·command·receipt 행에 일대일 매핑하며 그 전까지 M3-D를 어떻게 차단할 것인가?

**Response: DIRECT.** Literal handlers와 receipt는 `13+5+4+6+3=31`, focused `41`, adjacent `142`, M3-B prerequisite `08327ad`를 묶는다. Critic Attempt 1 FAIL/Attempt 2 PASS와 audit pending을 보존하고 `ADVANCE`로 M3-D를 막는다.

### Q7 [claim-mode-discipline]
Frozen 31·cutpoint 정의·stale code·LOC cap을 `CONFIRMATORY`로 청구하려면 pre-spec `22190bf`가 첫 product/data commit보다 이르고 manifest SHA/bytes가 그대로임을 어떤 git 명령과 timestamp로 증명하며, M3-B footprint `2,043` retain 결정에 대한 M3-C product `<=900`, tests `<=1,400`, inclusive `<=2,800` 후속 결과와 critic/result 뒤 추가된 witness 또는 cap miss를 §13.6.7에서 어떤 `EXPLORATORY` 행으로 분리해 필요시 `MIXED`로 강등할 것인가?

**Response: DIRECT.** `22190bf`/`5291945`의 `06:14:30`/`06:16:37`은 first product `7394246`의 `06:37:22`보다 이르고 SHA `c3752c…65e27c7b`는 불변이다. Product `353/900`, tests+fixture `829/1,400`; frozen/caps는 CONFIRMATORY, critic-driven witnesses는 EXPLORATORY라 phase는 `MIXED`다.

### Q8 [divergence-diagnosis]
사전 예상 `31/31`, M3-C `5/5`, duplicate truth 0, stale `4/4`, authority·forbidden callable 0 또는 세 LOC cap 중 하나라도 어긋나면 §13.6.8에서 fixture/runner 오염만 `RESULT-INVALID`로 철회·재측정하고, cutpoint·recovery 요구 자체의 결함은 `REQUIREMENT-WRONG` correction phase로, nondeterminism·race·footprint의 유효한 예상 밖 동작은 `GENUINE-FINDING`/EXPLORATORY holdout으로 보내는 판정 증거와 자동 후속 행동은 무엇인가?

**Response: DIRECT.** §13.6.8은 lookup→append gap/error translation을 `GENUINE-FINDING`/EXPLORATORY로 분류한다. Fixture/runner 오염은 `RESULT-INVALID` 철회·재측정, 잘못된 requirement는 새 frozen `REQUIREMENT-WRONG` phase이며 어느 경우도 자동 승격하지 않는다.

## Verify Attempt 1 — 2026-08-12

**VERDICT: FAIL.** 이후 보정으로도 이 역사적 판정은 철회하지 않는다.

| Q | 판정 | blocking defect |
|---|---|---|
| Q1 | FAIL | `DIRECT + LIMITATION` compound label |
| Q2 | PASS | frozen 13 cold-open + actual registration-without-terminal witness |
| Q3 | FAIL | recovery lookup과 append 사이 실제 writer interleaving 부재 |
| Q4 | FAIL | compound label 및 hostile-provider capability-isolation 과청구 |
| Q5 | FAIL | pipeline §8.5 Cycle 13 row 부재 |
| Q6 | FAIL | 허용되지 않은 `CLOSE CANDIDATE` label |
| Q7 | PASS | chronology/SHA/caps/MIXED 근거 일치 |
| Q8 | PASS | 당시 divergence mapping은 있었으나 후속 correction에서 실제 finding으로 갱신 필요 |

Independent reproduction: focused `38 passed in 67.87s`; M3-B/C `98 passed in 155.59s`; manifest SHA exact/diff exit `0`; product `254+59=313`; tests+fixture `657+51=708`. Questions `8`, failed `5`; no accepted repeated LIMITATION; Cycle 13 row `N`, valid milestone label `N`, M3-D bypass `N`. 결론: M3-C open, correction·reverify·audit 필수.

## Verify Attempt 2 — 2026-08-12

**VERDICT: PASS.** Q1~Q8 closed set을 독립 재검증했다.

| Q | annotation | verified evidence |
|---|---|---|
| Q1 | DIRECT | nondeterministic pre/post capture `4/4`; local truth one; external billing excluded |
| Q2 | DIRECT | frozen cold-open + actual service interrupted-registration recovery |
| Q3 | DIRECT | real lookup→service/append interleavings `3/3`, stale/no-call/no-controller-write |
| Q4 | LIMITATION | authority/three forbidden operations proved; hostile-provider sandbox excluded; escalation 없음 |
| Q5 | DIRECT | §13.6.5 + pipeline Cycle 13; only Autonomy delta |
| Q6 | DIRECT | `ADVANCE 5/5`, prerequisite closed, M3-D blocked |
| Q7 | DIRECT | chronology/SHA exact; product `353/900`, test `829/1,400`, MIXED discipline |
| Q8 | DIRECT | race correction is GENUINE-FINDING/EXPLORATORY; frozen requirement unchanged |

Independent reproduction: race `3 passed in 3.28s`; focused `41 passed in 71.61s`; M3-B/C `101 passed in 158.74s`; M3-A `41 passed in 4.50s`, adjacent denominator `142`; frozen diff exit `0`; product `294+59=353`; tests+fixture `778+51=829`.

Gate trail: DIRECT `7`, accepted LIMITATION `1`, failed `0`; no 3-cycle escalation; Cycle 13 row `Y`; claim mode `MIXED`; divergence `GENUINE-FINDING` with affected row EXPLORATORY; current milestone `ADVANCE`; M3-D bypass `N`.

The substantive critic gate passes. M3-C remains `ADVANCE`, not `CLOSE`, until the independent seven-pass audit passes.
