# §03 — M1-C Typed Proposal and Scientific Replication (2026-08-10)

> Status: **IMPLEMENTATION GATE PASS — E1~E15 exact, close critic/auditor pending, claim mode EXPLORATORY**
> Core: [`docs/research-os-status.md`](../research-os-status.md) §02
> 직전 phase: [`§02 M1-B`](02-2026-08-10-m1-b-study-generation-budget.md)
> Pipeline 영향: [`docs/research-os-pipeline.md`](../research-os-pipeline.md) §3, §8.4 Scientific state, §9.4 M1-C
> 구현 전 기준선: commit `cd1a3c6`, Python 3.12에서 `371 passed, 104 subtests passed`

## 03.0 한 단락 요약 (TL;DR)

M1-C는 candidate JSON에 연구 의도를 섞지 않고, StudyContract v2에서만 exact typed `Proposal`을 experiment registration의 sibling evidence로 원자 저장한다. Proposal은 generation·candidate digest·hypothesis class·한 evaluation scope·falsifiable prediction·declared intervention을 결박한다. kernel이 보장하는 scientific replication identity는 terminal parent의 **동일 frozen candidate**를 **다른 preregistered replication scope**에 처음 전달한 attempt-1 transition이다. scope는 라벨이 아니라 baseline workspace, adapter `materialize/run/evaluate/verify` request, experiment identity, projection/replay에 모두 들어간다. 실제 dataset 독립성은 certified adapter의 책임이며 M1-C kernel claim에 포함하지 않는다. StudyContract v1·기존 graph metadata·legacy event bytes/API는 exact 유지한다. 목표 §북극성은 NS1·NS3, 목표 종착지 delta는 §8.4 Scientific state의 Proposal/scope/replication 구체화, 목표 checkpoint는 M1-C 네 conjunct 전부 `CLOSE`다.

## 03.1 왜 이 작업을 하나

- 목표 §북극성:
  - **NS1 무결성·권한 하위호환** — v1 contract와 기존 event/ID/projection/API shape를 변경하지 않고, v2 Proposal·scope forgery와 replay drift를 fail-closed한다.
  - **NS3 Durable learning 객체** — 네 typed object 중 Proposal 하나를 canonical event evidence로 만든다. replication은 Proposal의 evidence identity 규칙이며 NS3의 별도 객체로 중복 계산하지 않는다.
- Trigger: M1-B는 generation·budget을 강제하지만, `graph_action`/`scientific_change`는 free text이고 evaluation scope는 contract에만 존재한다. 현재 `replicate`도 candidate 변경을 요구해 과학적 replication 의미와 반대다.
- 선택한 seam: `StudyContract.schema_version == 2`가 typed path를 활성화한다. 하나의 `EXPERIMENT_REGISTERED` payload 안에 candidate digest와 complete Proposal bundle을 넣어 proposal-only orphan event를 만들지 않는다.
- 범위 경계: terminal Diagnosis·ClassState/frontier는 M1-D, context v3/legacy isolation은 M1-E, Program memory는 M2, autonomous FSM·unseen effectiveness benchmark는 M3다.
- 사용자 승인 경계: unseen synthetic benchmark가 v0.5 release gate다. 세 실제 프로젝트 live pilot·migration은 v0.5 이후이며 그 전에는 read-only다. 제품 multi-agent는 NS6 통과 이후다.
- 이 phase는 active `M1-C` 네 conjunct만 닫으며 M-chain/criterion 의미를 바꾸지 않는다. Rule 9는 적용하지 않는다.

### 03.1.1 activation과 StudyContract v2

1. StudyContract v1 parser/digest/generation/event/replay 의미는 byte-for-byte 유지한다. v1 active generation은 Proposal을 받지 않으며 제공 시 `PROPOSAL_CONTRACT_VERSION_REQUIRED`다.
2. v2는 v1과 같은 exact top-level/nested shape를 쓰고 `schema_version=2`만 허용한다. 추가로 evaluation scope `manifest_digest`가 scope 사이에서 unique여야 한다. 같은 실제 평가를 다른 ID로 위장하는 alias를 막는다.
3. v2 generation open은 adapter `describe.capabilities`에 literal `evaluation_scope_v1`이 있어야 하며 없으면 event delta 0과 `STUDY_SCOPE_CAPABILITY_REQUIRED`다.
4. contract의 `intervention_surface.candidate_schema_digest`는 현재 certified project candidate schema의 canonical digest와 같아야 한다. mismatch는 event delta 0과 `STUDY_CANDIDATE_SCHEMA_MISMATCH`다.
5. v2 contract fixture raw SHA-256는 `43108703cba7b8feaad967b4c7d5db17f97ed0de2a3bb9b249a312cf2d4f8403`, normalized digest는 `7f66d3bc702d112197de6649cf7555b5a086f43768723dc346ad150a8bf9e184`, fixed generation ID는 `generation_060e0d7cee268537dbf49de5fb9b5d54`다.

### 03.1.2 canonical Proposal v1

Proposal exact fields는 다음 12개다. unknown/missing key, required null, untrimmed/empty text, Unicode surrogate, unsupported enum, invalid ID/digest/RFC-6901 pointer, duplicate pointer, oversized narrative, non-null authority를 `PROPOSAL_INVALID`로 거절한다.

| field | exact contract |
|---|---|
| `proposal_schema_version` | literal safe integer `1` |
| `generation_id` | exact active generation namespaced ID |
| `candidate_digest` | lowercase SHA-256 of candidate JSON |
| `hypothesis_class_id` | non-empty trimmed declared class ID |
| `action` | `explore | exploit | ablate | replicate` |
| `mechanism` | non-empty trimmed Unicode scalar text, UTF-8 길이 `≤ 16,384` bytes |
| `predicted_effect` | non-empty trimmed Unicode scalar text, UTF-8 길이 `≤ 16,384` bytes |
| `falsifier` | non-empty trimmed Unicode scalar text, UTF-8 길이 `≤ 16,384` bytes |
| `parent_experiment_id` | `null` or valid experiment ID |
| `evaluation_scope_id` | non-empty trimmed scope ID |
| `intervention_json_pointers` | unique canonical-sorted RFC-6901 pointers; empty allowed only by semantic rule |
| `authorized_action` | required literal `null` |

- 각 narrative의 exact boundary `16,384` bytes는 허용하고 `16,385` bytes는 거절한다. 범용 `repeat_text` generator로 multibyte `é×8192 = 16,384 bytes` positive와 `é×8193 = 16,386 bytes`, ASCII `x×16385` negatives를 모두 고정해 code-point 계산 구현을 배제한다.
- Canonical `to_dict()`를 `sha256_json`한 값이 `proposal_digest`; `proposal_id = stable_id("proposal", project_id, proposal_digest)`다.
- explore fixture raw/digest/ID는 각각 `5932b1dcd39bdd1d88fb67a14f5a8de3cc7df0264368aa0ec5a9dfd37b79598b`, `edc12b16a1f6419c575d44a5be47352e24d49570533939ed09726fa6e493ba09`, `proposal_202fd99acdfc63371bff7e748e3d758d`다.
- replication fixture raw/digest/ID는 각각 `bd829aa2b1e1ff7af14e9a9b7f6da976b9c3565765c8b09a6efe86bf5fa900a5`, `e83e7e5639fb3350972190d14b799d8f27c966809966d6a834ef13e7635d10b8`, `proposal_9e0889d18ae1a62227b0563f733b000b`다.
- `run-once --proposal <json>`는 legacy `--parent/--graph-action/--scientific-change`와 상호 배타적이다. retry는 새 Proposal을 받지 않고 원 registration의 exact Proposal/scope를 상속한다.
- registration은 sibling `proposal`, `proposal_digest`, `proposal_id`, `evaluation_scope_id`와 기존 flat `parent_id`를 가진다. flat parent는 Proposal parent와 exact 같아야 한다. Proposal을 candidate JSON 안에 넣거나 typed path에서 새 flat graph metadata를 만들지 않는다.
- authority는 Proposal input/registration을 포함한 모든 변경 service/CLI result에서 top-level key가 존재하고 값은 항상 `null`이다.

### 03.1.3 semantic preflight와 atomic registration

Proposal transition의 I/O-free semantic validator는 side effect 전 preflight와 `EventLog.append(precondition=...)`가 공급한 locked events에서 동일하게 실행한다. 이 validator 자체는 projection/log/adapter에 재진입하지 않는다. 다만 기존 composed registration precondition은 certification/evaluation-seal 확인을 위해 `_doctor_snapshot`을 호출할 수 있으므로, 전체 callback이 I/O-free라고 청구하지 않는다.

- 공통: Proposal generation/candidate digest/class/scope/parent가 active contract, computed candidate, persisted parent와 exact 일치해야 한다.
- `explore`: parent는 null; scope role은 development 또는 diagnostic; declared pointers는 1개 이상, allowed surface 안, `max_changes` 이하다.
- `exploit`/`ablate`: terminal same-generation/same-compatibility parent가 필수; candidate는 parent와 달라야 하며 declared pointers는 1개 이상, allowed surface 안, `max_changes` 이하다.
- `exploit`/`ablate`의 declared pointer tuple은 parent와 child candidate의 **실제 canonical diff tuple과 exact equality**여야 한다. object는 key union을 재귀 비교하고 add/remove member는 그 member pointer를 emit한다. scalar·type·array 차이는 현재 node pointer를 emit하며 array는 atomic이다. RFC-6901 `~`/`/` escape 뒤 canonical sort한다. 예컨대 `{x:2,y:1}→{x:2,y:2}`의 observed tuple은 exact `["/y"]`이며 declared `["/x"]`는 `PROPOSAL_INTERVENTION_MISMATCH`다.
- iterative action은 holdout/replication role에서 실행할 수 없다. holdout은 M1-C proposal path의 iterative/replication 어느 쪽에도 소비하지 않는다.
- first attempt의 scientific uniqueness key는 `(project_id, generation_id, candidate_digest, evaluation_scope_id)`다. parent/action/attempt는 key가 아니다.
- projection/reducer는 registration의 candidate digest, Proposal digest/ID, experiment ID를 canonical body에서 재계산해 forged direct event를 fail-closed한다.
- 같은 uniqueness key를 두 worker가 경쟁하면 winner 1, `PROPOSAL_EVALUATION_SCOPE_REUSED` 1, registration/budget delta 1이어야 한다.

### 03.1.4 scope-bound baseline, adapter, identity

- v2 baseline은 `--evaluation-scope-id`가 필수이고 typed run은 baseline을 자동 생성하지 않는다. unknown scope, holdout scope, scope 없는 v2 baseline, scope가 있는 v1/no-generation baseline은 모두 event delta 0으로 거절한다. v1의 unscoped 자동-baseline 의미는 그대로 유지한다.
- scope role/manifest full object를 adapter `baseline`과 그 결과의 `verify` request에 전달한다. baseline event에는 exact `science_state_version`, `generation_id`, `study_contract_digest`, `evaluation_seal_digest`, `evaluation_scope_id`, `evaluation_scope`를 함께 보존한다.
- baseline workspace ID는 기존 0-based repetition 의미를 유지해 `stable_id("baseline", project_id, compatibility_digest, generation_id, evaluation_scope_id, repetition_index)`다. fixture의 첫 repetition(`0`) development/replication-1 IDs는 `base_884a47b6d0b959cb1a077a25407c0ee6`, `base_a15f407510085a86aa5ae078ec652873`다.
- v2 candidate run도 full evaluation-scope object를 adapter `materialize/run/evaluate/verify` request에 전달한다. candidate JSON은 그대로라 Proposal/orchestration key 수가 0이다.
- typed run은 same-generation, same-compatibility, same-scope의 trusted baseline만 허용한다. unscoped 또는 wrong-scope baseline은 `STUDY_SCOPE_BASELINE_REQUIRED`다.
- v2 experiment ID는 scope가 있을 때 `stable_id("experiment", project_id, generation_id, compatibility_digest, parent_id, candidate_digest, evaluation_scope_id, attempt)`다. scope가 null인 기존 component sequence는 호출하지 않아 legacy ID를 보존한다.
- projection은 nullable `evaluation_scope_id` column/index를 additive migration한다. null이면 decoded API key를 생략해 기존 projection canonical digest가 달라지지 않는다.
- fixture explore/explore-retry/replication-1/replication-1-retry/replication-2 ID는 각각 `exp_14dab599bb9be91cbac8751a5c0da192`, `exp_536ca19ec4feb680afd4e58f95ffb4d9`, `exp_6de5a6123dad0a28f3bb630f11db9af4`, `exp_af80ae6bf6acc4b7d0a604f1683daf86`, `exp_3c757d5fc62c10a52b741759acdf377b`다.

### 03.1.5 scientific replication과 retry

`action=replicate`의 attempt 1은 다음을 모두 만족할 때만 새 scientific replication이다.

1. parent가 terminal이고 same generation·same compatibility다.
2. candidate digest가 parent candidate digest와 exact 같다.
3. hypothesis class가 parent의 persisted Proposal class와 같다.
4. target scope는 preregistered `role=replication`이고 parent scope와 다르다.
5. target scope manifest는 parent scope manifest와 다르다(v2 unique manifest invariant 포함).
6. `(project, generation, candidate, target scope)`가 어떤 first attempt에서도 사용되지 않았다.
7. replication Proposal의 intervention pointers는 exact empty다.

실패한 replication의 retry는 새 replication이 아니다. 새 Proposal/scope를 제출할 수 없고 원 Proposal ID/digest/scope를 exact 상속하며 attempt만 증가한다. 따라서 `replication_count`는 first-attempt valid replicate registration만 센다. retry가 새 Proposal을 제출하면 `PROPOSAL_RETRY_FORBIDDEN`, persisted retry가 scope/Proposal을 바꾸면 replay `PROPOSAL_RETRY_MISMATCH`다.

### 03.1.6 사전 예상 결과와 immutable oracle

Versioned oracle은 `tests/fixtures/scientific_state/v2/manifest.json`의 20 unique cases다. supporting fixture 8개(자기 자신인 manifest 제외)의 raw digest를 고정한다. Proposal negative matrix는 25/25 `PROPOSAL_INVALID`를 요구하고, 별도 positive node는 multibyte narrative exact 16,384 UTF-8 bytes를 허용한다. transition matrix는 generic data-only scenario DSL 53 cases이며, 각 case가 concrete scenario/input/mutation/expected stable code와 canonical event·generation·baseline·registration·attempt·retry delta 0을 선언한다. case ID는 pytest 표시 외에 interpreter input으로 전달하지 않으며, direct-forgery·semantic-diff·partial-bundle·mutated-retry 18 cases는 locked append/cold reducer/projection rebuild/service replay 네 path, 총 72 path matches를 요구한다. manifest raw/canonical digest는 §03.6.7에 고정한다.

v1 compatibility corpus는 project `fixture-m1c-v1-compat`의 8 events—initialize, v1 generation, attempt 1 registration, `TIMED_OUT`, matching outcome finding, attempt 2 retry, `INVALID_EXPERIMENT`, matching outcome finding—를 고정한다. raw SHA/head는 `9624d76d3d95c02b50fb4f4aeecff97de4bb7e86333ec5630b0aedf42b2f4c13` / `c70c0e8dbdc17e108357c44582a49497bf451675eda837cb1deed9b03f0221dc`다. science/projection/study-status/replay canonical digests는 각각 `caf38dffc747818dd1d04e80e3bf65e69dd76d18532deb6f35a64ac02ccb5942`, `a7efa9d03083f3c865633fa08258630bada7376c6add9d9d6c5864349d0e8439`, `0bf1f7557e1655c0e59873923845d82d088341f92a3a7098934c8c65a740da99`, `ba6e97c9993c6c2bdfd3482c50b4f9ed9ee4eeb2d7cad185c07739bf7ecd088f`이며 service replay 뒤 bytes/head 불변을 요구한다.

| ID | manifest case | expected decisive result |
|---|---|---|
| E1 | fixture-integrity | supporting fixture `8/8`, Proposal negative `25`, transition negative `53`, manifest `20`, raw digest exact |
| E2 | v2-contract-generation | v2 digest/generation/scope order exact; unique scope manifests; capability required |
| E3 | legacy-v1-and-m1b-parity | fixed 8-event generation→registration→finding→retry→finding corpus; bytes/head/state/projection/service/API exact; replay byte-preserving; M1-B 29/29 |
| E4 | Proposal canonical/order/schema | 두 Proposal digest/ID, pointer canonical order, multibyte 16,384-byte positive boundary, negative `25/25` one code; manifest 5 nodes |
| E5 | transition-negative-matrix | semantic/replay/baseline/capability/schema negatives `53/53`, four-path matches `72`, all deltas 0, case-ID dispatch 0 |
| E6 | scope-bound-baselines | 0-based workspace IDs exact; baseline+verify scope binding 2/2; exact event shape; no typed auto baseline; v1/v2/no-generation/holdout negatives |
| E7 | valid-explore-lifecycle | exact 21-key atomic registration, four typed siblings complete, proposal-only event 0, candidate typed key 0, budget +1 |
| E8 | valid-frozen-candidate-replication | candidate same, scope changed, replication count 1, exact IDs |
| E9 | retry-inherits-proposal-not-replication | explore와 failed replication retry 두 valid nodes; Proposal/scope inherited; retry는 replication count를 늘리지 않음 |
| E10 | evaluation-scope-identity-axis | three scopes produce three exact IDs; legacy ID exact |
| E11 | candidate-orchestration-separation | candidate keys `[x,y]`; Proposal keys 0; four adapter operations carry exact scope object |
| E12 | live-cold-rebuild-proposal-parity | same events produce 4 equal paths and exact counts/state; sync/rebuild는 full scientific reduce 후 SQL apply |
| E13 | concurrent-evaluation-scope-reuse | winner/reject/event/budget `1/1/1/1`, stable reuse code |
| E14 | proposal-authority-null-surfaces | nine surfaces key 9/9, recursive/top-level non-null 0 |
| E15 | m1c-regression-floor | existing `371+104` minimum, ruff/ty/diff PASS |

Manifest의 20 unique case node 전체 observed dict가 expected dict와 exact equality여야 한다. E4는 다섯 node, E9는 두 node, 나머지는 각 한 node라 표 E1~E15와 manifest 20개가 대응한다. 어느 digest/ID/code/count/request body/API shape/race ratio나 regression이 다르면 M1-C CLOSE를 차단하고 §03.6.8 분류 후 재측정한다.

## 03.2 무엇을 만들 계획인가

| 작업 | 위치 | 예상 검증 산출물 |
|---|---|---|
| contract v2 + strict Proposal | `science/contracts.py`, 신규 `science/proposals.py`, `errors.py` | canonical/negative matrix/digest unit tests |
| semantic reducer + locked precondition | `science/state.py`, `service.py`, `graph_policy.py` seam | transition matrix, retry/replay/race tests |
| scope identity + projection migration | `kernel/ids.py`, `kernel/projection.py` | fixed ID, forged ID, v1 API/projection parity |
| scope-bound adapter/baseline lifecycle | `service.py`, `cli.py`, protocol docs/examples | exact request capture + real service E2E |
| executable oracle | `tests/test_m1c_*`, fixture manifest observer | 20/20 full observed/expected comparison |

## 03.3 검증 계획

- Focused: contract/Proposal pure parser, manifest observer, actual service scope binding, baseline/run/retry lifecycle, direct malformed replay, additive projection migration, forced concurrent reuse.
- Full: explicit Python 3.12 `pytest -q`; `ruff check`; `ty check src`; `git diff --check`.
- Counterfactual: missing v2 Proposal, Proposal on v1, duplicate scope manifest, missing adapter capability, schema mismatch, exact UTF-8 boundary + 25 structural negatives, 53 semantic/replay negatives, actual candidate diff mismatch on pure preflight and all four replay paths, same candidate non-replication, changed candidate replication, same/reused scope, wrong baseline, forged candidate/Proposal/IDs, four single-missing partial typed bundles, retry mutation.
- Path parity: append 직후 live state, fresh cold reducer, projection rebuild, service replay의 Proposal count·replication count·used pair·active generation을 exact 비교한다. projection `sync/rebuild`는 먼저 전체 scientific sequence를 reduce하고 성공한 state만 SQL에 apply한다. history 없이 typed row를 직접 apply하는 경로는 fail-closed한다.
- Independent review: Proposal/contract와 identity/projection을 교차 검토하고, actual service/adapter/race evidence가 pure observer만 재구현하지 않았는지 별도 확인한다.

## 03.4 결과 vs 가설

제품 구현을 시작한 뒤 generic transition observer가 선언된 `extends` deep-merge 의미로 15개 scenario를 전수 해석했고, 5개 child `expected_state`가 parent의 이미 지난 상태를 상속한다는 모순을 발견했다. 예를 들어 `v1-open-baseline`은 실제 v1 generation이 열렸는데 parent의 `active_generation_id=null`을 상속했고, `rep1-terminal`/`rep12-terminal`은 새 baseline·registration·terminal list를 명시하지 않아 이전 list를 상속했다. 이는 제품 결과가 아니라 oracle data 결함이므로 당시 transition/manifest 측정을 전부 제외했다.

정정은 선언된 범용 해석 규칙을 약화하지 않는다. `expected_state`를 replacement/부분 assertion으로 바꾸지 않고 5개 scenario에 실제 generation ID, baseline scope list, registration IDs, terminal IDs를 명시해 deep-merge 뒤에도 full state가 exact하도록 했다. 동시에 fixture가 이미 요구한 두 `control_assertions`가 named production observer를 실제 호출하도록 harness gate를 강화한다. 정정 뒤 E1~E15 전체를 처음부터 재측정하며, 결과는 exploratory evidence로만 기록한다.

corrected checkpoint 뒤 재측정 결과 E1~E15는 전부 exact 일치했다. Frozen manifest operation은 `20/20`, skip 0이며 Proposal structural negative는 `25/25`, transition negative는 `53/53`, direct locked-append/cold-reducer/projection-rebuild/service-replay path는 `72/72`다. supporting DSL/control/case-ID 독립성 검사는 `6/6`이고, v1 8-event bytes/head와 science/projection/status/replay digest 및 M1-B `29/29` parity도 그대로다. Positive lifecycle observer는 실제 `ResearchService`, reducer, projection, CLI와 toy adapter를 사용했으며 합성 success payload로 결과를 만들지 않았다.

최종 Python 3.12 전체 suite는 `442 passed, 111 subtests passed`, skip 0이다. `ruff check src tests`, `ty check src`, `git diff --check`도 모두 PASS했다. 같은-scope forced race는 두 실제 private `_run_once` lifecycle을 append 경계에서 동기화해 winner 1, stable rejection 1, registration/budget delta 1을 얻었고 내부적으로 terminal 1, winner stage 4, cleanup 1, residual workspace 0을 확인했다. append 직후 `KeyboardInterrupt` 회귀는 registration 1과 `CANCELLED` terminal 1을 확인했다. corrected oracle 이후의 두 concurrency 수정 전 부분 결과는 최종 수치에 포함하지 않았다.

## 03.5 발견된 부수 이슈

구현 전 탐색에서 scope가 contract digest 밖에서는 전혀 소비되지 않고, 기존 `replicate`가 candidate 변경을 요구하며, projection이 persisted candidate hash/experiment ID를 재계산하지 않는 seam을 발견했다. 이는 M1-C 요구 자체이며 결과로 선점하지 않는다.

구현 중 독립 oracle 감사가 두 가지 harness/oracle 결함을 발견했다. (1) 5개 scenario의 partial-looking `expected_state`가 선언상 deep-merge되어 stale parent leaf를 유지했고, (2) `DocumentResolver`가 frozen fixture의 `control_assertions`를 실행하지 않았으며 baseline derive도 실제 service observer가 아닌 합성 payload builder였다. 둘 다 `RESULT-INVALID`로 분류한다. 제품 코드를 fixture에 맞춰 우회하지 않고 원 결과를 폐기했으며, corrected oracle과 실제 production-observer control을 새 checkpoint로 고정한 뒤 전량 재측정한다.

corrected oracle 아래 통합 중에도 두 concurrency 결함을 별도 최소 재현으로 발견했다. 첫째, 여러 process가 빈 SQLite projection을 동시에 초기화하면 additive migration과 forensic recovery가 겹칠 수 있었다. disposable cache의 모든 initialize/recover/sync/rebuild를 sidecar `flock`으로 직렬화하고 migration/index 교체를 `BEGIN IMMEDIATE`로 묶었으며, 8-worker cold initializer와 반복 stress를 회귀로 추가했다. 둘째, 동일 typed Proposal의 deterministic experiment ID가 충돌할 때 registration loser가 winner의 같은 experiment ID event를 자기 commit으로 오인해 winner를 terminalize/cleanup할 수 있었다. 호출자별 고유 registration event ID를 append 전에 생성해 exact event ID로만 durable commit ownership을 복구하게 했고, append-return 직후 `KeyboardInterrupt`와 실제 `_run_once` two-worker scope race를 모두 고정했다. 전자는 registration 1 + `CANCELLED` terminal 1, 후자는 winner lifecycle 1 + loser adapter call 0을 요구한다. 두 결함 아래의 부분 측정은 결과에서 제외하고 수정 뒤 전량 재측정한다.

## 03.6 시스템 영향 분석 ★

- 이전: free-text graph action은 연구 의도를 완전하게 증명하지 못하고, replication은 candidate-change 규칙에 걸리며, scope는 실행 identity가 아니다.
- 목표 이후: v2 experiment는 generation/candidate/class/scope/falsifier를 canonical Proposal로 남기며 frozen candidate + new preregistered scope만 replication으로 센다.
- 가능해질 것: M1-D가 terminal evidence를 exact Proposal/class/scope에 연결해 Diagnosis와 ClassState를 갱신한다.
- 계속 불가능: typed Proposal 없이 v2 registration, scope-label-only 실행, reused scope를 새 replication으로 계산, retry를 replication 수로 부풀리기, Proposal에 deployment authority 부여.
- 외부 관찰: `open-generation(v2) → baseline --evaluation-scope-id → run-once --proposal → retry/replicate → study-status/replay`에서 exact scope/Proposal/replication state가 보인다.

## 03.6.4 마일스톤 진척 청구 ★

**영향 받은 M_i.j**: `M1-C` · **계획 라벨**: _IMPLEMENTATION GATE PASS / CLOSE PENDING_

| conjunct | 현재 | close gate |
|---|---|---|
| Proposal schema/preflight tests PASS | ✅ | E4/E5 + actual service preflight; `25/25`, `53/53`, `72/72` |
| candidate payload와 orchestration metadata 분리 | ✅ | E11 candidate exact + four-operation adapter request capture |
| `evaluation_scope_id` identity/replay tests PASS | ✅ | E3/E6/E7/E10/E12 + additive projection migration |
| frozen candidate + new preregistered scope만 replication; retry/reuse/change 거절 | ✅ | E5/E8/E9/E13; forced `_run_once` race winner/reject `1/1` |

네 conjunct와 implementation evidence gate는 모두 ✅다. progress critic·독립 7-pass auditor가 PASS하기 전에는 M1-C를 닫지 않는다. parent M1은 M1-D/E가 남으므로 계속 open이다.

## 03.6.5 종착지 비전 갱신 ★

- 계획 Delta: pipeline §8.4 Scientific state의 Proposal/scope/replication current-state를 executable canonical transition으로 구체화한다.
- §8 endpoint, NS/M criterion, unseen NS6 release gate, live migration/multi-agent 경계는 유지한다.
- 구현·검증 성공 뒤에만 pipeline §8.4·§8.5·§10과 status core를 동기화한다.

## 03.6.6 의도-실행 정합 ★

**계획 라벨**: _MATCH CANDIDATE_ — “실패를 지식으로 바꾸는 loop”의 바로 앞 prerequisite인 falsifiable Proposal과 genuine replication identity를 추가하며, 무결성 kernel을 약화하거나 autonomous/memory 성과를 선청구하지 않는다.

## 03.6.7 Claim Mode ★

**현재 라벨**: _EXPLORATORY_. 구현 전 기준선은 `cd1a3c6`이다. 최초 docs+fixture-only pre-spec checkpoint는 `40bb3e06d16ff09ea2807e61eba4a8367a09f43a` (`2026-08-10T05:01:30+09:00`, tree `6d8f4f7978265622d32b0b1c1bfa8ba51c2688e4`, parent `cd1a3c6ae965cdfd6209025f088a2d92129039e4`)이며 phase/critic 2개와 v2 fixture 9개만 포함했다. 최초 manifest raw `bc00f9648a5c663856c1ba19aa3f9aece48d422b565ca47b3a3c2fa01bea06ea` / sorted-compact `2cd22cc0d230fbd36e7dd37c7d9fe83c1d4358e05b66d54342c116157a2107af`는 제품 구현 전에 고정됐지만, 구현 시작 뒤 observer가 위 expected-state 상속 모순과 미실행 control assertion을 발견했다.

사전 규칙대로 M1-C 전체를 confirmatory에서 exploratory로 강등한다. corrected transition raw는 `1e9e8e60a18dfe0d610a4928ecb90933204d43c53796e00d253343093ed96dd0`, corrected manifest raw/sorted-compact는 `4b9c216ea7a6bcbd8aec00a2224e4c41c349c038ea4b1d7c7fafcc8721e31b1d` / `75d7e1e568f3d42463184544e4b396c6f68cd1ae91fc3d5026dffda8454dca67`이다. 정정 시점까지 product/result-bearing commit은 없었지만 구현이 이미 시작됐으므로 chronology를 이용해 confirmatory 자격을 복원하지 않는다. correction checkpoint 뒤 oracle digest를 다시 바꾸면 해당 결과도 폐기하고 별도 재명세한다.

독립 correction re-review PASS 뒤 정정 사양만 commit `575711fa7d11303340fd695ffcaa19e0a9270644` (`2026-08-10T05:43:02+09:00`, tree `709dc93db23ce42f2f265f78f57016ed6e4c27ca`, parent `5ab51f10ffcbb8f6e79d92b0935f977f03094305`)에 고정했다. 이 commit은 phase/critic과 transition/manifest fixture 네 파일만 포함하며 product source나 result-bearing test implementation은 포함하지 않는다.

## 03.6.8 Requirement-Result Divergence ★

- `REQUIREMENT-WRONG`: scope capability나 frozen-candidate replication criterion이 사용자 목표의 연구 의미를 잘못 대리하거나 M1-C criterion이 end-state delta를 측정하지 못함 → correction/필요시 Rule 9.
- `RESULT-INVALID`: wrong runtime, adapter request 미관찰, race 미발생, test observer가 service를 재구현, replay/live 불일치, implementation bug, oracle drift → 결과 제외·같은 pre-spec으로 재측정.
- `GENUINE-FINDING`: 독립 최소 재현에서도 기존 legacy/projection/adapter 의미가 예상과 다르거나 scope-bound execution이 현재 protocol과 근본 충돌 → M1-C open 유지, EXPLORATORY + 재명세.
- 어느 분류든 E1~E15 exact 불일치가 있으면 M1-C CLOSE를 차단한다.

**발생 기록 (`2026-08-10T05:31:52+09:00`)**: scenario inheritance contradiction과 control observer 미실행을 `RESULT-INVALID`로 판정했다. 최초 oracle 아래 얻은 transition/manifest 관찰값은 evidence에서 제외한다. 요구 의미—deep-merge된 full expected state와 실제 production observer control—는 유지·강화하며, corrected checkpoint 후 E1~E15를 전량 재측정한다. 이 correction 때문에 성공하더라도 M1-C evidence claim은 `EXPLORATORY`다.

## 03.7 §북극성 갱신 계획

- NS1: v1 bytes/ID/projection/API exact와 v2 forged/replay/race fail-closed를 보강했다. 전체 release protocol-attack gate는 open이다.
- NS2: 정의된 여섯 capability에는 Proposal/replication이 없으므로 `2/6` 그대로다. Diagnosis gate/class closure/semantic frontier/complete legacy isolation은 M1-D/E까지 open이다.
- NS3: typed Proposal이 executable oracle과 함께 canonical replay되어 `0/4 → 1/4`다. Diagnosis·ClassState·Claim 세 객체는 M1-D/M2까지 open이다.

## 03.8 §pipeline 매핑 영향

- pipeline Stage 3 Study inference를 `✗ → △`로만 올릴 근거가 생겼다. Proposal/replication identity는 생겼지만 Diagnosis/ClassState/frontier가 없으므로 `○`를 청구하지 않는다. endpoint와 milestone chain 의미 변경은 없다.

## 03.9 비관 재채점 — 이 phase 자체

- Proposal이 falsifiable 문장을 강제해도 좋은 가설·새 전략을 자동 생성하지 않는다.
- scope manifest digest와 adapter binding은 평가 정체성을 보존하지만 dataset의 과학적 품질·독립성을 증명하지 않는다.
- same candidate/new scope는 replication의 필요조건이지 통계적 재현 성공을 뜻하지 않는다.
- holdout 소비 정책·terminal Diagnosis·class closure·memory writeback은 아직 없다.
- actual usage settlement·study lifetime cap은 M1-B limitation으로 남는다.
- context v2는 Proposal/scope/ledger를 직접 노출하지 않으며 M1-E까지 agent UX가 불완전하다.

## 03.10 다음 1행동

- 구현 checkpoint를 고정하고 Q1~Q8 progress critic response를 `DIRECT`/`LIMITATION`으로 판정한다.
- status core/pipeline을 evidence와 동기화한 뒤 독립 7-pass audit로 M1-C CLOSE 여부를 판정한다.
