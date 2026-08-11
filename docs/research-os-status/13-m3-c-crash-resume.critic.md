# Critic — Phase 13 (2026-08-12) — m3-c-crash-resume

영향 §북극성 행: NS5. 단일 자율 루프 완결성, NS1. 무결성·권한 하위호환

## Q1 [proxy-vs-real]
`resume-*-call-started`가 deterministic fixture의 재호출 성공을 exactly-once recovery로 오인하지 않도록, 호출마다 다른 packet을 반환하는 nondeterministic provider에서 output 반환 후 capture 전 crash와 capture 후 crash를 분리해 전자는 reservation 재충전 없이 한 번만 재호출되어 canonical truth가 하나만 남고 후자는 절대 재호출되지 않으며 외부 billing exactly-once는 청구하지 않음을 어떻게 증명할 것인가?

**Response:** _<DIRECT | LIMITATION | OUT-OF-SCOPE>_
_<author fills here: evidence (with file/command), or §residual link, or §북극성 mapping rationale>_

## Q2 [measurement-gap]
Frozen crash denominator `13`이 보호하기 쉬운 checkpoint 목록이 아니라 실제 side-effect/commit seam의 완전한 분할임을, provider-return→capture, service registration→terminal, terminal→disposition/link, Diagnosis→origin/link, Claim→synthesis-link, next/stop derive→append 각각에 대해 process-death 후 새 service/store/loop 인스턴스가 같은 raw logs를 여는 매핑표로 보이고 특히 registration은 있으나 terminal은 없는 service 중간 상태를 누락하지 않았음을 어떻게 입증할 것인가?

**Response:** _<DIRECT | LIMITATION | OUT-OF-SCOPE>_
_<author fills here: evidence (with file/command), or §residual link, or §북극성 mapping rationale>_

## Q3 [counterfactual]
복구 성공이 경쟁 writer가 없는 우연한 순서 때문이 아님을, captured synthesis·started experiment·truth-owner reuse의 lookup과 append 사이에 Project generation 또는 Program head를 한 단계 진전시키는 one-factor race를 주입해 stored old head를 current head로 세탁하지 않고 `AUTONOMY_RECOVERY_STALE` 또는 `AUTONOMY_RECOVERY_EVIDENCE_INVALID`, provider/service 추가 호출 0, Project/Program write delta `0/0`, semantic truth count 각 1을 재현할 수 있는가?

**Response:** _<DIRECT | LIMITATION | OUT-OF-SCOPE>_
_<author fills here: evidence (with file/command), or §residual link, or §북극성 mapping rationale>_

## Q4 [boundary]
NS1의 authority·forbidden-operation 0이 문자열 키 검색이나 고정 상수 proxy가 아님을, captured output·state·Context·packet·Diagnosis·synthesis·Claim의 adversarial nested non-null authority를 실제 parser/reducer가 거절하고 public exports와 controller/provider의 reachable runtime call graph에서 alias·`getattr`·injected object를 포함한 service/store/log/path/callable 및 deploy/merge/trade 실행 경로가 0임을 어떤 executable evidence로 보일 것인가?

**Response:** _<DIRECT | LIMITATION | OUT-OF-SCOPE>_
_<author fills here: evidence (with file/command), or §residual link, or §북극성 mapping rationale>_

## Q5 [end-state-positioning]
§8.4 Autonomy를 finite-but-incomplete에서 canonical cold-restart 가능 episode로 실제 구체화하되 외부 provider billing exactly-once·distributed consensus·학습 품질은 여전히 불가능한 것으로 남기고 Context/Program memory와 NS6/NS7의 rating을 올리지 않았음을 §13.6.5와 pipeline §8.5 Cycle 13의 전후 행동·세 truth-owner 경계·잔여 갭으로 어떻게 동기화할 것인가?

**Response:** _<DIRECT | LIMITATION | OUT-OF-SCOPE>_
_<author fills here: evidence (with file/command), or §residual link, or §북극성 mapping rationale>_

## Q6 [milestone-positioning]
M3-C를 `CLOSE`하려면 frozen 31개 literal ID가 fallback 없이 각각 실행되어 actual cold reopen `13/13`, terminal/disposition/Diagnosis/origin/Claim semantic count 각 1, stale `4/4` no-write, recursive authority `6/6`, reachable forbidden callable `3/3`을 동시에 만족하고 M3-B prerequisite와 두 independent gate를 통과해야 하는데 §13.6.4는 이를 어떤 handler·command·receipt 행에 일대일 매핑하며 그 전까지 M3-D를 어떻게 차단할 것인가?

**Response:** _<DIRECT | LIMITATION | OUT-OF-SCOPE>_
_<author fills here: evidence (with file/command), or §residual link, or §북극성 mapping rationale>_

## Q7 [claim-mode-discipline]
Frozen 31·cutpoint 정의·stale code·LOC cap을 `CONFIRMATORY`로 청구하려면 pre-spec `22190bf`가 첫 product/data commit보다 이르고 manifest SHA/bytes가 그대로임을 어떤 git 명령과 timestamp로 증명하며, M3-B footprint `2,043` retain 결정에 대한 M3-C product `<=900`, tests `<=1,400`, inclusive `<=2,800` 후속 결과와 critic/result 뒤 추가된 witness 또는 cap miss를 §13.6.7에서 어떤 `EXPLORATORY` 행으로 분리해 필요시 `MIXED`로 강등할 것인가?

**Response:** _<DIRECT | LIMITATION | OUT-OF-SCOPE>_
_<author fills here: evidence (with file/command), or §residual link, or §북극성 mapping rationale>_

## Q8 [divergence-diagnosis]
사전 예상 `31/31`, M3-C `5/5`, duplicate truth 0, stale `4/4`, authority·forbidden callable 0 또는 세 LOC cap 중 하나라도 어긋나면 §13.6.8에서 fixture/runner 오염만 `RESULT-INVALID`로 철회·재측정하고, cutpoint·recovery 요구 자체의 결함은 `REQUIREMENT-WRONG` correction phase로, nondeterminism·race·footprint의 유효한 예상 밖 동작은 `GENUINE-FINDING`/EXPLORATORY holdout으로 보내는 판정 증거와 자동 후속 행동은 무엇인가?

**Response:** _<DIRECT | LIMITATION | OUT-OF-SCOPE>_
_<author fills here: evidence (with file/command), or §residual link, or §북극성 mapping rationale>_
