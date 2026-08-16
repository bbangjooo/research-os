# Research OS controlled frame-transition 개선 설계·구현 명세

> 상태: 구현 명세
> 실행 방식: 일반 Codex 코드 작업
> 적용 경계: opt-in outer control plane
> 비권한 원칙: 모든 `authorized_action`은 literal `null`

## 1. 목적

Research OS v0.5의 확증 커널을 그대로 보존하면서, 기존 연구 프레임이 소진된
경우에만 경쟁 프레임을 비교하고 격리 검증한 뒤 compatibility-separated successor
generation으로 채택할 수 있는 통제 경로를 추가한다.

이 기능은 LLM에 창의성이나 “점프 능력”을 설치하지 않는다. 사람, LLM 또는
도메인 도구가 만든 새 후보를 입력으로 받아 다음을 통제한다.

- 프레임 고착을 evidence-bound하게 판정한다.
- 서로 실질적으로 다른 rival frame을 비교한다.
- 결과를 보기 전에 discriminator를 고정한다.
- 추천 후보를 비정규 격리 pilot에서 검증한다.
- 추천, pilot 허가, pilot pass, 독립 검토, deterministic policy adoption을 서로
  다른 receipt로 둔다.
- 모든 조건이 현재 digest에 맞을 때만 기존 `open-generation` 경로로 successor를
  정확히 하나 연다.

## 2. 점프 생성과 프레임 전환

점프 생성은 현재 후보 공간 밖의 representation, mechanism, objective 또는
ontology를 발명하는 일이다. Research OS가 이 발생을 보장할 수는 없다.

프레임 전환은 후보가 주어졌을 때 기존 프레임의 소진 여부를 확인하고, rival과
falsifier를 비교해 기각·보류·격리 검증·채택 중 하나를 안전하게 선택하는 일이다.
이번 개선은 두 번째 문제만 다룬다.

변경은 다음과 같이 분류한다.

| 등급 | 의미 | 경로 |
| --- | --- | --- |
| J0 | 같은 프레임의 parameter/settings 변경 | 기존 inner loop |
| J1 | 같은 class의 mechanism/model/feature 변경 | 기존 inner loop |
| J2 | schema, representation, class, universe 변경 | outer inquiry |
| J3 | objective, evaluator, metric, ontology 변경 | outer inquiry |
| AMBIGUOUS_MATERIAL | broad/unknown pointer 또는 복합 의미 변경 | fail-closed outer inquiry |

파일명 변경이나 서술상의 relabeling으로 J2/J3를 J0/J1로 낮출 수 없어야 한다.

## 3. 현재 시스템의 한계와 재사용할 seam

v0.5는 다음 기반을 이미 제공한다.

- `EventLog`: project-bound append-only canonical truth
- `ProjectionStore`: 재구축 가능한 SQLite query projection
- `ScientificState`: generation, budget, terminal Diagnosis의 replay-derived state
- `ProgramLog`: compatibility와 provenance가 결속된 과학 기억
- `AutonomyLog`: orchestration-only state
- `ResearchService.open_generation`: active/terminal/Diagnosis, evaluator certification,
  compatibility, changed-contract/seal 및 동시 writer를 검사하는 successor 경로

그러나 frame, rival frame, pilot-only authority, post-pass adoption review 및
deterministic `POLICY_ADOPTION`은 현재 public contract에 없다.

이를 해결하기 위해 기존 과학 reducer나 SQLite schema를 확장하지 않는다. 같은
`EventLog`에 `research.frame_transition_*.v1` namespaced extension event를 추가하고,
별도의 pure reducer가 outer lifecycle만 재생한다. 기존 scientific reducer와
ProgramLog consumer는 이 이벤트를 읽지 않으므로 기본 v0.5 동작과 canonical memory가
오염되지 않는다.

## 4. 상태 전이

```text
Gate A
├─ NO_BUILD / UNSTABLE_RUBRIC
│  └─ 제품 successor 0, 정상 종료
└─ GO
   └─ J2/J3/AMBIGUOUS intake
      └─ >=2 exhaustion signals + >=2 rival frames + frozen discriminator
         ├─ ABSTAIN
         │  └─ GO_NO_ADOPTION, pilot/adoption request 0, successor 0
         ├─ REJECT
         │  └─ GO_NO_ADOPTION, pilot/adoption request 0, successor 0
         └─ RECOMMEND_FOR_PILOT
            └─ distinct PILOT_ONLY authorization
               └─ isolated three-arm pilot
                  ├─ KILL_B1/B2/B3/B4
                  │  └─ GO_NO_ADOPTION, successor 0
                  └─ PASS_FOR_ADOPTION
                     └─ fresh independent review
                        ├─ REJECT
                        │  └─ GO_NO_ADOPTION, successor 0
                        └─ APPROVE
                           └─ distinct deterministic POLICY_ADOPTION
                              └─ separate frame-transition-activate
                                 └─ current open-generation preflight
                                    └─ GO_ADOPTION, successor exactly 1
```

`RECOMMEND_FOR_PILOT`, `PILOT_ONLY`, `PASS_FOR_ADOPTION`, `APPROVE`,
`POLICY_ADOPTION`은 서로 대체하거나 재사용할 수 없다. `PASS_FOR_ADOPTION`은
오직 fresh adoption review 자격이고, `APPROVE`는 Gate A에 미리 결속된
`research-os.controlled-frame-transition.policy.v1` 정책을 deterministic하게 적용할
자격일 뿐이다. 이 정책은 exact activation binding을 요구하고 external authority를
항상 false로 둔다.

## 5. Gate A

실제 사용 전 Gate A receipt는 다음을 모두 결속해야 한다.

- 실제 provider output 20–50건과 정확히 같은 sample/actual-output count
- corpus manifest와 provider revision
- privacy/retention policy
- J0–J3 rubric과 rubric 안정성
- label owner, review owner, 별도 independent reviewer
- recurrent J2/J3 count와 결과 선행 recurrence threshold
- `policy_id` = `research-os.controlled-frame-transition.policy.v1`과 그 exact
  `policy_digest`
- evidence digest

결과는 reducer가 결정한다.

- rubric이 불안정하면 `UNSTABLE_RUBRIC`
- recurrence가 threshold 미만이면 `NO_BUILD`
- 안정된 rubric에서 threshold 이상이면 `GO`

이 저장소 구현 작업은 실제 provider output을 만들거나 independent review를
합성하지 않으며 Gate A GO를 꾸미지 않는다. synthetic test는 계약 검증일 뿐 제품
채택 증거가 아니다.

단일 Gate receipt는 threshold와 결과를 같은 시점에 정규화해 기록한다. 따라서
`rubric_digest`와 `evidence_digest`가 결과 관찰 전에 외부에서 사전등록된 원본을
가리킨다는 사실과 review role ID의 운영상 독립성은 별도 증거 체계로 확인해야
한다. 이 구현은 그 주장을 위조 방지 digest로 결속하지만 외부 사실 자체를
인증하지 않는다. 반면 policy adoption 단계는 human ratifier identity를 받거나
인증하지 않는다.

## 6. Inquiry와 memory authority

단일 실패 신호가 새 프레임을 승인하지 못한다. inquiry에는 서로 다른 종류의
exhaustion signal이 최소 두 개 필요하다. 신호 예시는 repeated failure, unresolved
anomaly, assumption conflict, class closure다.

현재 generation과 compatibility에 정확히 맞는 evidence만 `canonical` lane을
선언할 수 있다. cross-frame, incompatible 또는 analogy evidence는 `advisory`다.
advisory evidence는 기존 registration, validation, promotion, sealing 또는
successor open의 입력이 되지 않는다. frame-transition extension event도 기존
ProgramLog에 자동 투입하지 않는다.

각 inquiry에는 최소 두 rival이 필요하며 각 rival은 assumptions, mechanism 또는
representation, predictions, falsifiers, uncertainty를 가진다. discriminator는
pilot/result 접근 전에 고정한다.

## 7. 격리 pilot

`RECOMMEND_FOR_PILOT`은 candidate/change/coverage/isolation digest와 pilot plan을
동시에 고정한다. pilot plan은 다음 세 arm을 정확히 사용한다.

1. `llm_only`
2. `llm_tools_memory`
3. `llm_research_os`

세 arm은 같은 task, provider revision, per-arm budget, primary metric을 사용한다.
결과 전에 minimum unique effect, critical false-promotion cap, privacy/retention,
resource cap과 teardown policy를 고정한다.

결과 우선순위는 다음과 같다.

1. v0.5 invariant/authority regression: `KILL_B4`
2. privacy/resource cap 초과: `KILL_B3`
3. false-promotion cap 초과: `KILL_B1`
4. best simpler baseline 대비 minimum unique value 미달: `KILL_B2`
5. 그 외: `PASS_FOR_ADOPTION`

어떤 pilot 결과도 durable successor를 쓰지 않는다.

## 8. Adoption과 successor

PASS 뒤 review는 exact current candidate, change, coverage, pilot receipt, source tree,
predecessor generation, proposed `StudyContract` digest를 새로 결속한다. reviewer는
maker, pilot authorizer, pilot evaluator와 달라야 한다.

Gate A는 `policy_id` = `research-os.controlled-frame-transition.policy.v1`과 그 exact
`policy_digest`로 이 단계의 built-in deterministic adoption policy를 미리 고정한다.
이 정책의 eligibility는 `PASS_FOR_ADOPTION`, fresh independent `APPROVE`, exact
activation binding이며 external authority는 false다. review `APPROVE` 뒤
`frame-transition-adopt-policy <inquiry-id>`는 caller가 제공한 판단을 받지 않고
literal `POLICY_ADOPTION`을 기록한다. 이 명령은 inquiry ID만 받으며, human ratifier
identity나 ratification JSON/file을 받지 않는다. policy receipt가 직접 담는
policy/review/candidate/contract/compatibility/expiry/evidence binding은 canonical
review와 Gate에서 파생된다. source tree와 predecessor는 정확한
`review_receipt_digest`를 통해 간접 결속되며 policy receipt에 직접 중복되지
않는다. 특히 `evidence_digest`는 fixed `policy_digest`와 canonical
pilot/review/candidate/contract/compatibility digest로 deterministic하게 계산되며
caller는 evidence field를 제공하지 않는다. policy receipt의 만료 시각은
review와 정확히 같다.

reviewer는 successor가 열리기 전까지 자신이 발급한 review를 revoke할 수 있다.
policy adoption 뒤라도 review가 revoke되면 파생 receipt는 activation authority를
잃는다. missing, stale, mismatched, expired, reused 또는 revoked chain은
fail-closed다.

유효한 policy adoption 후에도 successor를 직접 쓰지 않는다. 기존
`ResearchService.open_generation`을 호출해 다음을 재사용한다.

- active predecessor와 pending Diagnosis/active experiment 검사
- current evaluator certification과 evaluation seal
- unchanged reset 차단
- contract/seal change와 compatibility binding
- concurrent writer 재계산
- replay/recovery와 `authorized_action: null`

controlled change reason은 inquiry와 policy-adoption digest를 결속한다. outer
reducer는 그 exact generation event만 해당 inquiry의 유일한 durable writer로
인정한다.

## 9. Public 사용 경로

구현은 기존 명령을 바꾸지 않고 opt-in 명령을 추가한다.

```text
research-os --project <project> frame-transition-gate-a gate-a.json
research-os --project <project> frame-transition-open inquiry.json
research-os --project <project> frame-transition-decide decision.json
research-os --project <project> frame-transition-authorize-pilot authorization.json
research-os --project <project> frame-transition-record-pilot pilot-result.json
research-os --project <project> frame-transition-review review.json
research-os --project <project> frame-transition-adopt-policy <inquiry-id>
research-os --project <project> frame-transition-revoke revocation.json
research-os --project <project> frame-transition-activate <inquiry-id> successor-contract.json
research-os --project <project> frame-transition-status [--inquiry <id>]
```

동등한 Python API도 제공한다. successor를 선택하지 않은 기존 연구는 기존
`open-generation`, `run-once`, `agent-context` 흐름과 event shape를 그대로 사용한다.
기존 generation은 소급 migration하지 않고 기본 generation도 자동 변경하지 않는다.

review JSON은 private temporary directory처럼 project source tree 밖에 둔다.
policy adoption에는 입력 JSON/file이 없다. adoption review는 당시 전체 source-tree
digest를 결속하고 activation lock에서 다시 비교하므로, review 뒤 project tree 안에
control-input 파일을 새로 쓰거나 어떤 파일이든 변경하면 review와 그로부터 파생된
policy adoption은 의도대로 stale 처리된다.

autonomous agent는 current independent `APPROVE` 뒤
`frame-transition-adopt-policy`를 호출하고 이어서 `frame-transition-activate`를
호출할 수 있다. 이는 명시적인 inquiry 하나에 한정된 두 단계 호출이며 generalized
background workflow engine, scheduler 또는 외부 행동 권한이 아니다.

## 10. 구현 파일

- `src/research_os/frame_transition.py`: strict contracts, pure planner/reducer,
  classification, fixed-policy adoption, receipt binding, state projection
- `src/research_os/frame_transition_service.py`: EventLog append/replay, native API,
  existing `open_generation` activation bridge
- `src/research_os/cli.py`: opt-in command parsing/dispatch
- `tests/test_frame_transition.py`: state, authority, pilot, replay tests
- `tests/test_frame_transition_service_cli.py`: service/CLI/activation smoke tests
- `README.md`: native 사용 예시와 non-adoption 경계

`science/state.py`, ProgramLog, AutonomyLog 또는 SQLite schema 변경은 acceptance에
필요하지 않으므로 하지 않는다.

## 11. Acceptance criteria

- J0/J1/J2/J3 positive, boundary, ambiguous, broad-pointer, relabeling downgrade 차단
- Gate A `GO`, `NO_BUILD`, `UNSTABLE_RUBRIC`의 deterministic mapping
- ABSTAIN/REJECT/RECOMMEND의 정확한 request/state/writer mapping
- single-signal, non-substantive rival, post-result discriminator 거부
- canonical/advisory evidence lane과 incompatible canonical claim 거부
- missing, stale, mismatched, reused, expired, revoked 및 maker-issued authority 거부
- recommendation과 PASS가 adoption으로 승격되지 않음
- KILL_B1/B2/B3/B4와 PASS의 deterministic pilot 결과
- Gate A가 fixed `research-os.controlled-frame-transition.policy.v1`의 `policy_id`와
  exact `policy_digest`를 prebind함
- built-in policy가 PASS, independent APPROVE, exact activation binding을 요구하고
  external authority를 false로 유지함
- policy adoption이 inquiry ID 외 입력, human ratifier identity 또는 caller-authored
  file 없이 canonical Gate/current `APPROVE` review에서 직접 receipt binding을
  파생하고 source tree/predecessor를 exact review digest로 간접 결속함
- policy receipt의 `evidence_digest`가 fixed policy와 canonical
  pilot/review/candidate/contract/compatibility digest에서 파생되고 caller evidence를
  받지 않음
- policy receipt 만료가 review 만료와 동일하고 reviewer의 pre-successor review
  revocation이 activation을 차단함
- pre-policy-adoption durable successor write 0
- valid chain에서 controlled successor exactly 1
- concurrent activation이 writer cardinality를 늘리지 않음
- live state와 cold replay가 같은 결과/오류를 반환
- 모든 controlled payload와 결과의 recursive `authorized_action`이 null
- extension event 전후 기존 scientific state와 ProgramLog behavior가 동일
- 기존 focused/full regression 통과

## 12. 명시적 비목표와 중단 조건

- actual provider 출력이나 independent review를 수집·합성하지 않는다.
- common truth ledger, universal world model, swarm, UI 또는 generalized workflow
  engine을 추가하지 않는다.
- active generation의 evaluator, metric 또는 ontology를 제자리에서 수정하지 않는다.
- 외부 행동, 배포, 거래, 자본 배분 권한을 부여하지 않는다.
- 실제 Gate A가 `NO_BUILD`/`UNSTABLE_RUBRIC`이면 inquiry와 제품 successor를 만들지
  않는 것이 정상 완료다.
- pilot/review가 non-pass이면 successor 0건인 `GO_NO_ADOPTION`이 정상 완료다.
- pilot의 `max_critical_false_promotions`는 세 arm의 합계에 적용한다.
- pilot authority revocation은 미사용 receipt의 발급자만 기록할 수 있다. review는
  reviewer가 successor open 전까지 revoke할 수 있고, 이는 파생된 policy adoption도
  무효화한다. 이미 열린 successor는 소급 취소하지 않는다.
- 이 opt-in extension은 새 binary의 controlled API 경로에서 강제된다. 기존 v0.5
  binary와 변경하지 않은 관리용 `open-generation`은 extension event를 해석하지
  않으므로 downgrade-resistant constitution을 주장하지 않는다. 다만 reserved
  controlled change reason은 exact binding 없이 새 binary의 `open-generation`에서
  사용할 수 없다.

이번 구현의 입증 가능한 주장은 다음으로 제한한다.

> 후보와 적법한 evidence가 주어졌을 때 Research OS가 프레임 고착을 분류하고,
> 비교·기각·격리 검증·통제된 successor 채택 경로를 fail-closed로 실행할 수 있다.
