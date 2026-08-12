# M1-E usable Context v3 pre-spec critic

> Status: **IMPLEMENTATION VERIFY PASS; independent progress audit PASS**
> Scope: §05 vertical slice only; M1-E release close는 포함하지 않음

## Q1 [proxy-vs-real]

Context v3가 M1-D truth를 복사한 shadow state를 만드는가?

**Response: DIRECT.** `ScientificState.to_dict()`의 replay-derived generation/budget/
Diagnosis/ClassState/frontier를 그대로 노출하고, agent builder에서 class를 재계산하지
않는다.

## Q2 [boundary]

Template이 agent interpretation을 kernel fact로 세탁하거나 실행 권한을 만드는가?

**Response: DIRECT.** Exact evidence/observation만 kernel이 채우고 interpretation,
failure type, falsifier, recommendation은 invalid sentinel로 남겨 agent가 명시적으로 작성한다.
Template과 final Diagnosis의 `authorized_action`은 null이다.

## Q3 [compatibility]

Context v3를 추가하면 context v2와 branch-conclusion v1이 바뀐는가?

**Response: DIRECT.** 기존 builder를 보존하고 CLI/service의 explicit
`schema_version=3`로만 v3 wrapper를 선택한다. Snapshot/token schema v2와
branch-conclusion metadata는 이 slice에서 변경하지 않는다.

## Q4 [failure semantics]

어느 pending experiment을 authoring할지 모호하거나 이미 닫힌 대상을 재진단할 수
있는가?

**Response: DIRECT.** 생략은 pending exact 1개일 때만 허용한다. 명시 ID도 active
typed terminal + pending이어야 하며 그 외에는 stable no-write error다.

## Q5 [end-state-positioning]

이 slice를 근거로 v0.3/M1-E close를 과대 청구하는가?

**Response: DIRECT.** §05는 context authoring conjunct의 first vertical slice만 증명한다.
tokenless legacy isolation, skill upgrade/rollback, version/docs/full regression은 open으로 남긴다.

## Q6 [complexity]

M1-D의 oracle 폭증을 반복하는가?

**Response: DIRECT.** 새 graph reducer·manifest·shadow oracle를 만들지 않고, 하나의
disposable history E2E와 작은 negative/parity test만 추가한다. 추가 예산은 1,200 lines
이하다.

## Verdict

**PASS (simulated independence).** 현 session의 새 subagent 생성 금지 때문에 root가
별도 read-only critic pass로 작성했다. Acceptance 1~6 전부 DIRECT이며
criterion 약화나 M1-E close 조기 청구는 없다.

Implementation verify evidence는 vertical `4 PASS`, final compatibility
`127 + 23 subtests`, disposable demo, ruff/ty/diff PASS다. Context v2 default
shape와 snapshot/token version 2는 보존됐고 v3는 opt-in이다. Template은 four
sentinel 외 exact kernel fields를 fixture Diagnosis와 일치시켰고, fill→diagnose→refresh에서
pending `1→0`을 재현했다. V3은 canonical snapshot을 temp EventLog/projection에
replay해 cold call에서도 project event/projection byte diff 0을 만족했다. Q1~Q6 final
response는 모두 **DIRECT / PASS**다.

Chronology verify는 pre-spec `38446f18…` at `03:31:58+09:00` → first
result-bearing `7fcfd100…` at `03:48:51+09:00`의 exact parent relation을 확인했다.
라벨은 vertical slice에 한해 **CONFIRMATORY**이며 M1-E는 `ADVANCE 1/5`,
prerequisite M1-D는 closed, parent M1은 open이다. First harness setup result는
`RESULT-INVALID`로 제외했고 corrected product acceptance는 변경하지 않았다.
