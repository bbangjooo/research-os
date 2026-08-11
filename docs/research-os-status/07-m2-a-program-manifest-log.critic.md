# Critic — Phase 07 (2026-08-11) — m2-a-program-manifest-log

영향 §북극성 행: NS1 무결성·권한 하위호환, NS3 Durable learning 객체, NS4 Program memory 정확도

## Q1 [end-state-positioning]

§8.4의 Program memory 행이 project-bound Finding 상태에서 별도 canonical ProgramManifest·ProgramLog 경계로 실제 이동했음을 어떤 before/after 산출물과 재현 명령으로 보이며, Claim·retrieval은 미구현으로 남기고 외부 live write 및 product multi-agent 제외를 그대로 보존했는가?

**Response:**

DIRECT. Before는 `memory/findings.py`의 project-bound Finding뿐이었다. After는 checkpoint
`b10e1b4`의 `memory/program.py`와 frozen manifest이며 `22/22`, literal+cases `20/20`, fresh
full `635+115`가 별도 envelope/log/projection을 재현한다. Claim/retrieval, 외부 live write,
product multi-agent surface는 없고 recursive authority는 `12/0 non-null`이다.

## Q2 [milestone-positioning]

M2-A를 CLOSE하려면 네 exit conjunct 각각이 독립된 재현 근거로 PASS해야 하는데, manifest identity binding·exact origin validation·hash-chain/head precondition·projection recovery/lock-order를 §07.6.4에서 빠짐없이 4/4로 증명하고 하나라도 미달이면 ADVANCE로 강등하는가?

**Response:**

DIRECT. Phase §07.6.4가 manifest, origin, log/head, projection/lock-order를 각각 PASS로 묶고
corrected cases `5+5+4+5=19/19`와 focused `22/22`를 제시한다. 한 행이라도 critic/audit에서
무효면 현재 candidate를 CLOSE하지 않고 ADVANCE로 되돌린다.

## Q3 [proxy-vs-real]

재사용한 EventLog 엔진 위 ProgramLog가 단지 `project_id=program_*`인 project-log proxy가 아니라 별도 canonical truth boundary라는 것을, canonical envelope의 명시적 program identity/schema와 project event·project envelope·혼합 stream의 fail-closed 거부로 증명하는가?

**Response:**

DIRECT. `ProgramEvent`는 exact `program_id` envelope와 program-only event types/path를 사용한다.
`test_program_event_envelope_is_distinct_from_project_event`와 frozen
`program-project-envelope-mixing`이 project envelope/event 및 mixed stream을 fail-closed한다.

## Q4 [boundary]

ProgramManifest가 science-state version, StudyContract schema/digest, generation ID, evaluation-scope version/body digest, evaluation seal 및 compatibility를 모두 exact bind하며 각 필드의 누락·변조·중복·unknown version과 non-null authority가 ProgramLog·projection mutation 0으로 거부되는가?

**Response:**

DIRECT. Frozen manifest cases 1~5와 parser/validator가 science/contract/generation/scope/seal/
compatibility identity를 exact bind한다. Forged digest, duplicate, unknown version, non-null
authority는 event/projection delta `0`; strict parser가 missing/extra/bool-as-int도 거절한다.

## Q5 [measurement-gap]

OriginEvidenceRef 검증이 단순 ID 조회가 아니라 잠긴 project EventLog의 지정 head prefix를 replay해 동일 head의 Diagnosis event sequence/hash/id/digest와 derived ClassState id/digest를 모두 대조하며 forged·future·stale·다른 generation/scope 참조를 no-write로 차단하는가?

**Response:**

DIRECT. `ProgramStore.append_origin`은 project shared lock에서 current head를 확인하고 prefix를
`reduce_scientific_state`로 replay해 Diagnosis event/hash/id/digest와 derived ClassState
id/digest를 대조한다. Frozen origin cases 6~10이 forged/scope/stale를 no-write로 거절한다.

## Q6 [counterfactual]

project-log shared → program-log exclusive → projection 순서를 실제 barrier-controlled 경쟁 실행으로 강제했을 때 project append와 program origin append가 deadlock 없이 선형화되고, stale project/program head 경쟁에서는 정확히 한 결과만 commit되며 loser의 log·projection delta가 0인가?

**Response:**

DIRECT. Both race cases are barrier-controlled. Corrected same-head case stages both writers at the
real append boundary, passes `50/50`, and thread-attributed writes prove winner 1, loser log/projection
writes `0/0`; project shared→program exclusive→projection ordering remains deadlock-free.

## Q7 [boundary]

ProgramProjection이 비권위 파생물임을 corrupted·missing·부분 갱신 projection에서 canonical ProgramLog의 동일 head와 exact state로 재구축하는 recovery로 증명하고, 반대로 ProgramLog hash-chain 손상은 projection으로 은폐하지 않고 fail-closed하는가?

**Response:**

DIRECT. Cases 15~17이 missing/corrupt/stale projection을 canonical log의 동일 head/origin으로
재구축한다. `program-committed-hash-corruption`은 projection fallback 없이 IntegrityError다.

## Q8 [claim-mode-discipline]

새 schema·identity·reject 기준과 각 frozen case의 expected outcome을 첫 구현·테스트 결과 노출 전에 machine-readable manifest와 pre-spec commit으로 고정해 CONFIRMATORY chronology를 증명할 수 있는가, 그렇지 않다면 §07.6.7을 EXPLORATORY로 명시하고 close 언어를 제한하는가?

**Response:**

DIRECT. Core schema와 18 unchanged cases는 `d635c61/eaf1294→b10e1b4`라 CONFIRMATORY다.
Historical harness/total-cap과 critic 뒤 strengthened race expected는 EXPLORATORY이며
`704fcb8→5d02fd0→635+115` chronology를 가진다. Prior race/full을 무효화하고 phase 전체를
MIXED로 제한했으므로 결과 뒤 기준 강화를 소급하지 않는다.
