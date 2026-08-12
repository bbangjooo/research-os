# Critic — Phase 14 (2026-08-12) — m3-d-unseen-release

영향 §북극성 행: NS1. 무결성·권한 하위호환, NS6. Fixed-budget 학습 효과, NS7. 기존 프로젝트 read-only 호환성

## Q1 [proxy-vs-real]
NS6의 “실패 지식을 써서 더 나은 다음 가설을 선택한다”가 generator의 `observable_v0.5_signal`을 정답 키처럼 읽는 새 규칙 엔진 proxy가 아님을, 여섯 family 각각에서 해당 v0.5-only ClassState·relation/status·retrieval reason·disposition·recovery-head를 한 요소씩 제거·ID-permute·모순화하면 동일 selector의 선택 또는 gate가 반드시 바뀌고 무관한 필드 변형에는 불변이며 그 인과가 실제 public Context/Program/Autonomy 직렬화에 귀속되는 material-ablation `6/6`으로 어떻게 입증할 것인가?

**Response: LIMITATION.** `src/research_os/meta_evaluation.py:465-601` does not consume a public object emitted by
`ResearchService`/`ProgramStore`/`FiniteAutonomyLoop`; it synthesizes a v0.5-shaped context directly from the
generator's `public_signal`. `tests/test_m3d_meta_evaluation.py:208-239` removes one broad section from only the first
decision of each episode and requires merely one changed candidate per family. It does not execute the required
remove/ID-permute/contradict matrix for all six rows per family, and the public-boundary manifest points to unrelated
historical tests instead of driving these generated episodes through the actual serialization boundaries. The current
evidence therefore cannot distinguish material Research OS learning-state use from an answer-shaped proxy.

## Q2 [counterfactual]
`6f36a1b`의 실제 Context v2가 `graph.recent/frontier/retryable`, compatibility와 proposal contract를 제공하는데 manifest가 이를 다섯 visible field로 축약해 v0.2를 인위적으로 약화하지 않았음을, byte-fixed v0.2 builder·packaged skill·fixture SHA와 완전한 historical field mapping, 양 arm의 동일 candidate bytes/budget/order/tie-break trace, 공통 교집합 context에서 선택이 byte-for-byte 같은 symmetry test, 그리고 v0.2에는 v0.5 typed field가 0건임을 어떤 executable arm-fidelity matrix로 보일 것인가?

**Response: LIMITATION.** The generator manifest and tests bind commit `6f36a1b`, the historical agent/skill SHA, and
the complete Context v2 field names, but the executed arm calls the current imported `build_agent_context` through
`src/research_os/meta_evaluation.py:422-463`. It never executes the byte-fixed historical builder or packaged skill;
the latter has no causal role in selection. Candidate/budget/denominator symmetry is tested, but no executable
historical-arm fidelity matrix proves that the newly written deterministic selector represents v0.2 behavior rather
than a current synthetic approximation.

## Q3 [overfitting]
manifest의 `canonical_tie_break`에 있는 `oracle_rank_if_visible`와 family별 answer-shaped signal이 hidden truth를 우회 누출하지 않음을, selector 입력과 reachable object/call graph에서 `hidden_world`·`oracle_choices`·`oracle_terminal`·`minimum_attempts` 및 그 digest/alias가 재귀적으로 0이고 candidate ID·배열 순서·action priority도 oracle rank와 무상관이며, class/action/ID를 nonce 기반 bijection으로 재라벨·순열해도 oracle-equivalent 결과가 보존되는 anti-gaming test로 어떻게 증명할 것인가?

**Response: LIMITATION.** Recursive forbidden-key scans and the relabel test exclude the literal hidden field names,
but the generator creates `public_signal`, target class/action, and `oracle_choices` from the same seeded point, after
which `_v05_context` translates that signal into the exact typed target used by `_typed_target`. The relabel test
changes candidate IDs, public target, and oracle together; it does not permute semantic actions/action priority or
test aliases/digests/value correlations in a separately isolated oracle process/call graph. Thus literal-name
non-reachability is demonstrated, but answer-shaped leakage/gaming is not ruled out.

## Q4 [sample-dependence]
36 body와 12 race schedule이 유리한 nonce를 골라 다시 뽑은 표본이 아님을, code/product/policy/generator/oracle/metric/attack/release bytes와 v0.2 fixture를 먼저 한 clean commit으로 freeze한 뒤 repo 밖 독립 custody process가 `secrets.token_hex(32)`를 정확히 한 번 호출한 transcript를 남기고, 어느 arm도 시작하기 전에 nonce commitment·36-body suite digest·12-schedule digest·환경·arm order를 불변 seal하며, 공개한 raw nonce로 제3자가 exact bytes를 재생성하고 실패/무효 receipt를 덮어쓰거나 다른 nonce로 재시도하지 못함을 어떤 chronology와 executable receipt invariant로 입증할 것인가?

**Response: LIMITATION.** `scripts/prepare_m3d_acceptance.py:49` contains one `secrets.token_hex(32)` call per process,
but the AST test proves only that source-level count. The script generates the suite before creating a fresh external
temporary custody directory at line 72 and leaves no durable reservation/append-only commitment that prevents the
operator from invoking the script repeatedly and selecting one favorable bundle. Custody metadata and bundle are
also co-produced by the same process. This is not an independently enforceable one-draw chronology.

## Q5 [measurement-gap]
choice와 waste gate가 arm별 경로 길이 차이로 분모를 줄이거나 0/0으로 통과하지 않음을, body가 사전 결정한 모든 required non-terminal oracle decision point를 양 arm의 공통 분모로 두고 조기 terminal·생략 결정을 남은 오류로 계상하며, episode/family/aggregate의 exact integer numerator·denominator와 closed-class retry를 재산출하고, v0.2 positive-waste 합이 0일 때 자동 FAIL/REQUIREMENT-WRONG으로 보내며 baseline-zero episode별 v0.5=0과 `min(90%, v0.2+20%p)`가 v0.2>90%에서 regression을 “개선”으로 승인하지 않는 anti-vacuity oracle로 어떻게 보일 것인가?

**Response: LIMITATION.** Common fixed denominators, baseline-zero checks, and positive v0.2-waste anti-vacuity exist,
but `compare_arms` at `src/research_os/meta_evaluation.py:867-868` uses
`min(0.90, v0.2 + 0.20)` without a non-regression conjunct. A v0.2 score above 90% can therefore be replaced by a 90%
v0.5 score and still pass. In addition, `run_arm` iterates all pre-generated decision points regardless of the chosen
action; choices do not drive the state transition, so omitted/early-terminal behavior is not measured as a real
trajectory error and waste is only selected action-label counts minus the body's fixed minimum.

## Q6 [boundary]
현재 없는 `tests/fixtures/protocol_attacks/v1/manifest.json`을 nonce 전에 literal unique ID·surface/schema·malformed input·stable code·Project/Program/Autonomy no-write로 freeze해 모든 행을 fallback 없이 한 번씩 실행하고, 동시에 여섯 family 각각을 pure simulator가 아닌 actual `ResearchService`·`ProgramStore`·`FiniteAutonomyLoop` 또는 명시적으로 정당화된 nearest public boundary로 통과시켜 hidden oracle 밖의 실제 terminal/evidence/ref를 검사함을 어떤 attack-denominator SHA/handler 표와 public-boundary E2E `6/6` 매핑으로 입증할 것인가?

**Response: LIMITATION.** The 24 literal rows execute, but
`tests/fixtures/protocol_attacks/v1/manifest.json` declares the existing M3-A manifest as its source contract and
`tests/test_m3d_protocol_attacks.py:10,49` imports and reuses M3-A's `CASE_HANDLERS`; this conflicts with §14.5's
explicit prohibition on retroactively treating M3-A's rejection count as the missing M3-D manifest. The test's empty
`autonomy-sentinel.jsonl` is not the actual controller `AutonomyLog`. The six-family public-boundary manifest maps to
eight older M1/M2/M3 tests, not six representative generated M3-D episodes executed end-to-end through the named
public services with actual terminal/evidence/ref checked against an external oracle.

## Q7 [end-state-positioning]
Compatibility를 synthetic-only에서 actual read-only `3/3`으로 올릴 근거가 공집합·편의 선택이 아님을, 현재 지정 경로의 event 행 수가 crypto-new `1`, manager `15`, Binance nested path `0`인데 Binance의 다른 기존 nested path에는 `32`행이 있다는 사전 관측 아래 각 프로젝트의 non-vacuous replay event와 opaque source를 결과 전에 어떤 결정 규칙으로 고정하고, raw event bytes/hash/derived v1 state와 `legacy_unstructured` 분류를 temp-only로 `3/3` 재현하면서 모든 외부 file/directory bytes·mode·symlink target 및 SQLite/WAL/lock surface의 pre/post delta `0`이고 adapter/skill install/live migration 호출도 `0`임을 어떻게 증명할 것인가?

**Response: DIRECT.** The precommitted external manifest deterministically selects eventful roots with `1`, `15`, and
`32` canonical events. `tests/test_m3d_external_compatibility.py` opens regular source files read-only with
`O_NOFOLLOW`, snapshots bytes/modes/symlink targets (including SQLite/WAL/lock surfaces), reconstructs event bytes,
hash chain/head and derived scientific state in temporary copies, and classifies opaque records as
`legacy_unstructured` with zero typed Claim IDs and no raw storage. Independent execution passed `4/4`; source-tree
pre/post deltas were zero and no adapter, installer, or migration path was invoked.

## Q8 [milestone-positioning]
현재 `verify_release.py`가 v0.4 manifest와 sealed commit만 허용하는 상태에서 post-result code edit로 unseen receipt를 사후 끼워 넣지 않고 M3-D `CLOSE 8/8`을 만들기 위해, nonce 전에 v0.5 verifier·receipt schema/path·0.5.0 version/docs/packaged skill/lock·exact managed `0.2/0.3/0.4→0.5` upgrade/rollback·wheel/install·full-suite floor를 모두 freeze하고 이후 생성되는 한 receipt를 검증기가 byte 변경 없이 결합하며, 어느 quality/protocol/compatibility/release conjunct miss도 `GENUINE-FINDING`으로 release를 차단하고 runner 오염은 `RESULT-INVALID`, oracle/metric 결함은 `REQUIREMENT-WRONG` correction으로 보내고 critic+audit 전에는 multi-agent·M3 close·v0.5 claim을 금지함을 어떤 single-gate chronology와 conjunction receipt로 입증할 것인가?

**Response: LIMITATION.** Version/docs/install and pre-nonce manifest hashes are present, but the single release
verifier is not executable to completion as frozen. `scripts/verify_v05_release.py:218-230` runs the entire
`tests/test_m3d_release_gate.py` file, whose independent result is `9 passed`, then requires the parsed count to equal
`7`. The acceptance/release verifier therefore deterministically rejects a healthy release-gate test run before it
can issue the one conjunction receipt. Post-nonce correction would change a frozen relevant byte and invalidate the
cycle, so the current checkpoint cannot establish v0.5.

## Verify Attempt 1 — 2026-08-12

**VERDICT: FAIL**

Clean checkpoint inspected: `0fa3a6c449cd17201c8760be6a5bb1eacebbd0be`.

### Blocking findings

1. **Proxy-vs-real / materiality (Q1):** the v0.5 arm consumes a generator-authored answer-shaped surrogate, and
   neither the required per-family ablation matrix nor generated-episode public-boundary E2E exists.
2. **Historical counterfactual (Q2):** historical bytes are hash-bound but not executed; the arm is a newly authored
   deterministic approximation over current code.
3. **Leakage/gaming (Q3):** literal forbidden-key scans pass, but public target and oracle are co-generated and the
   relabel test changes them in lockstep, leaving semantic leakage and priority gaming unexcluded.
4. **One-draw custody (Q4):** one nonce call is enforced only per invocation; repeated pre-selection invocations are
   not prevented or independently recorded.
5. **Measurement (Q5):** a v0.2 score above 90% may regress to 90% and pass, while selections do not control the
   simulated trajectory.
6. **Protocol/public boundary (Q6):** M3-A handlers are repackaged despite §14.5, and the public-boundary set is a
   collection of older unit/integration nodes rather than generated-episode E2E `6/6`.
7. **Single release gate (Q8):** the verifier requires `7` passes from a file that currently and correctly reports
   `9`, making the frozen acceptance path deterministically fail.

Q7 is independently verified DIRECT: all three selected external projects are non-vacuous and the strict read-only
replay/opaque/no-write checks pass.

### Reproduction evidence

- `.venv/bin/pytest -q tests/test_m3d_meta_evaluation.py` -> `13 passed in 3.93s`
- `.venv/bin/pytest -q tests/test_m3d_protocol_attacks.py` -> `25 passed in 2.96s` (one contract test plus 24 rows)
- `.venv/bin/pytest -q tests/test_m3d_external_compatibility.py` -> `4 passed in 0.32s`
- `.venv/bin/pytest -q tests/test_m3d_release_gate.py` -> `9 passed in 0.47s`, contradicting the verifier's exact-7
  invariant
- Public-boundary manifest node IDs -> `8 passed in 4.70s`, but the semantic E2E limitation above remains
- Combined focused suite -> `51 passed in 7.20s`
- Targeted Ruff and `ty` checks -> PASS

### Custody confirmation

At review time there was **no acceptance nonce, acceptance body, race body, pre-arm seal, custody transcript, or final
receipt** in the repository. Only the three pre-nonce manifests existed under
`tests/fixtures/meta_evaluation/v1/`. This review did not run either acceptance preparation/runner script and did not
create a nonce, body, seal, transcript, or receipt.

The phase remains pre-unseen. Fixing any frozen product/generator/oracle/metric/attack/release byte requires a new
clean pre-nonce checkpoint and a fresh independently enforceable custody cycle before acceptance may run.

## Verify Attempt 2 — 2026-08-12

**VERDICT: FAIL**

Clean checkpoint inspected: `20b35a5778d8c224092b93a5b1175800a5040c5d`.

### Closed-question resolution

| Q | Attempt 2 result | Independent evidence |
|---:|---|---|
| Q1 | **DIRECT** | `ClassState.to_dict()`, `retrieve_claims`, `ProposalKnowledgeDisposition.to_dict()`, `AutonomyEpisodeState.to_dict()`, and Context v3 are the actual typed public renderers in `src/research_os/meta_evaluation.py:658-986`. The material test exercises all six episodes in every family under remove, class-ID permutation, and contradiction and requires exact `6/6` for every family/mutation; irrelevant context remains invariant. Six generated-family boundary nodes and the exact terminal-reference negative test pass. |
| Q2 | **DIRECT** | `_historical_v02_context_batch` obtains `6f36a1b` with `git archive` and executes that checkout's Context v2 builder in an isolated subprocess. The current builder is monkeypatched to fail in the fidelity test without affecting the historical arm. Historical agent/skill SHAs are exact, the complete Context v2 shape is asserted, and the common selector refuses a non-bound historical skill-policy digest. Candidate bytes, budgets, required denominators, and common context intersection are symmetric. |
| Q3 | **DIRECT** | Public rendering does not call `_oracle_choice`; mutating every oracle choice leaves selector bytes identical. Recursive hidden/oracle key checks, class/candidate-ID bijection, candidate-array reversal, and reversed action priority preserve oracle-equivalent v0.5 results. |
| Q4 | **LIMITATION — blocks PASS** | The new fixed external path, `O_EXCL` reservation, one source-level nonce call, second-live-invocation rejection, and pre-arm external reservation are improvements. However `scripts/m3d_custodian.py:41-65` creates the checkpoint directory and reservation file, `fsync`s only the file, and calls `secrets.token_hex(32)` before `fsync`ing the containing directory at lines 88-92. Neither the new checkpoint-directory entry in its parent nor the reservation entry in the checkpoint directory is made crash-durable before the draw. A power/filesystem crash can therefore lose the supposedly durable pre-nonce reservation and permit a second draw. `tests/test_m3d_release_gate.py:185-205` proves only immediate same-filesystem visibility and a second live call; it does not establish crash durability. |
| Q5 | **DIRECT** | `run_arm` now closes the selected trajectory on a wrong choice and charges all later body-fixed decisions as omitted errors; wrong executed experiments are waste. `compare_arms` retains equal fixed denominators, positive-baseline anti-vacuity and per-episode zero rules, and now applies `max(v0.2, min(90%, v0.2+20%p))`. The explicit above-90% regression test passes. |
| Q6 | **DIRECT** | M3-D owns a literal 24-entry `ATTACK_HANDLERS` table and no longer imports M3-A's handler table. All 24 rows re-execute and snapshot actual ProjectLog, ProgramLog, and `AutonomyEpisodeLog` bytes. The public-boundary manifest now contains exactly six generated-family nodes using the typed nearest public boundaries; all six pass. |
| Q7 | **DIRECT** | The unchanged precommitted roots contain `1/15/32` events. Independent focused execution again passed external replay, opaque classification, and strict bytes/modes/symlink-target no-write checks `4/4`; no adapter, installer, or migration path ran. |
| Q8 | **DIRECT for the corrected pre-unseen harness** | The verifier constructs only the seven literal upgrade node IDs. Independent execution returned `7 passed`; release-manifest binding tests pass, and `pytest --collect-only -q` reports exactly `921 tests collected`. The same clean checkpoint records the completed main run as `921 passed, 115 subtests passed`; per parent direction that 20-minute suite was not redundantly rerun. Version/docs/wheel/full remain one release-verifier conjunction, while the final unseen receipt remains deliberately absent. |

### Blocking finding

Q4 still does not meet its own durable one-draw chronology. The required ordering is:

1. create the deterministic checkpoint directory and `draw-reservation.json` with exclusive semantics;
2. `fsync` the reservation file;
3. `fsync` the checkpoint directory so the reservation directory entry is durable;
4. `fsync` the custody parent so the checkpoint-directory entry is durable;
5. only then call `secrets.token_hex(32)`.

The frozen candidate performs steps 3-4 only after drawing and writing the nonce transcript. Correcting this relevant
custody byte requires another clean pre-nonce checkpoint and critic re-verification. No acceptance draw may start from
`20b35a5`.

### Disclosed subcap assessment

The subcap miss is accurately disclosed rather than hidden or rebaselined. From `7b00e0b..20b35a5`, independent
`git diff --numstat` classification reproduces benchmark/generator/release scripts `2,341/1,800`, tests+fixtures
`1,677/2,400`, and inclusive churn `4,555/6,000`. Treating the first number as a
`GENUINE-FINDING`/EXPLORATORY engineering subtarget miss while keeping the inclusive cap and all eight release gates
unchanged is consistent with the precommitted contract. It neither repairs nor compounds the Q4 release blocker.

### Reproduction evidence

- M3-D focused suite: `63 passed in 19.04s`
- Adjacent M3-A/B/C: `142 passed in 162.25s`
- Exact seven managed upgrade/rollback node IDs: `7 passed in 0.70s`
- Full collection: `921 tests collected in 0.21s`
- Recorded clean-checkpoint main run: `921 passed, 115 subtests passed in 1195.61s` (not redundantly rerun)
- Targeted Ruff, `ty`, and `git diff --check`: PASS
- Attempt 2 audit count: questions `8`; DIRECT verified `7`; LIMITATION `1`; failed `1`

### Custody confirmation

At Attempt 2 review time there was **no acceptance nonce, acceptance suite, race suite, checked-in custody transcript,
pre-arm seal, or v0.5 final receipt**. This review did not invoke `scripts.m3d_custodian`, either acceptance script, or
any external custody path, and created no acceptance artifact. The reservation unit test used only a mocked nonce and
pytest temporary directory.

## Verify Attempt 3 — 2026-08-12

**VERDICT: PASS**

Clean checkpoint inspected: `038893137e6f77d60844168103b978e1a60f1d5c`.

### Closed-question resolution

- **Q1-Q3 and Q5-Q7: DIRECT preserved.** A path-by-path `git diff --quiet 20b35a5..0388931` confirms no byte change
  in `src/research_os/meta_evaluation.py`, `src/research_os/service.py`, the generator/public-boundary/external/attack
  manifests, or the M3-D meta-evaluation/protocol/external tests. Attempt 2's independently reproduced evidence
  therefore remains bound to identical frozen bytes.
- **Q8: DIRECT preserved.** `scripts/prepare_m3d_acceptance.py`, `scripts/run_m3d_acceptance.py`, and
  `scripts/verify_v05_release.py` are byte-identical to Attempt 2. The v0.5 release manifest changes only the expected
  hashes for the corrected custodian and release-gate test. Its binding test passes, and the exact seven-node release
  verifier logic is unchanged.
- **Q4: DIRECT.** `scripts/m3d_custodian.py:51-77` exclusively creates the checkpoint directory, exclusively creates
  `draw-reservation.json`, writes and `fsync`s the reservation file, `fsync`s the checkpoint directory, then `fsync`s
  the custody parent before the sole `secrets.token_hex(32)` call. `_safe_parent` also `fsync`s each parent immediately
  when creating a missing custody-path component. The mock test records both required directory syncs before the nonce
  callback and confirms a second draw for the same checkpoint remains blocked without a second nonce call.

All eight closed questions are now DIRECT at the frozen pre-unseen checkpoint. This PASS approves the critic gate for
the pre-unseen harness only; M3-D remains `0/8` until the authorized one-draw acceptance, release receipt, and subsequent
independent progress audit complete.

### Reproduction evidence

- Q4 ordering + second-draw block + release-manifest binding:
  `3 passed in 0.24s`
- Complete `tests/test_m3d_release_gate.py`: `10 passed in 0.41s`
- Targeted Ruff: PASS
- `uvx --offline ty check src`: PASS
- `git diff --check`: PASS
- Frozen-byte comparison from `20b35a5` to `0388931`: only `scripts/m3d_custodian.py` and its Q4 test changed among
  executable Q1-Q8 evidence surfaces; the release manifest contains the corresponding two hash updates.
- Attempt 3 audit count: questions `8`; DIRECT verified `8`; LIMITATION `0`; OUT-OF-SCOPE `0`; failed `0`.

### Custody confirmation

At Attempt 3 review time the five checked-in acceptance artifact paths were absent (`0/5` present): suite, race suite,
custody transcript, pre-arm seal, and v0.5 final receipt. This review did not invoke the real custodian, preparation,
acceptance runner, or any external custody path, and generated no nonce or acceptance artifact. The only custody
execution was the existing unit test with a mocked nonce and pytest-owned temporary directory.

## Verify Attempt 4 — 2026-08-12

**VERDICT: FAIL**

Clean checkpoint inspected: `5a3a3028f009fa6aae38f176bd0bbf0cf7129435`.

### Closed-question resolution

| Q | Attempt 4 result | Independent evidence |
|---:|---|---|
| Q1 | **DIRECT** | The immutable external `acceptance-result.json` still hashes to `9b67285b816648e3225f14b80d186367ca764cbcfe1233cd3318fcb7d92aaf80`, exactly the failure-review value. The external bundle equals the archived prearm/suite/race objects structurally; their canonical suite/race digests are `487a624c…8e37` and `cc61adb0…8f38`, exactly the prearm values. Raw archived suite/race/prearm/custody hashes are `850f0c36…a320`, `05cdb279…040c`, `6f4715f5…fdf0`, and `4b7b1901…dddb`, exactly the four failure-review entries. Nonce commitment, one-call transcript, draw reservation, arm reservation, prearm seal, and arm order agree. The review says `rerun_same_draw=false`; the external result is `FAIL` with authority `null` and both prohibited capabilities `false`. |
| Q2 | **DIRECT** | The external result preserves outer `917 passed, 4 failed, 115 subtests passed`. Its four outer failures all descend from `tests/test_m3d_meta_evaluation.py::test_generator_manifest_is_precommitted_and_has_no_acceptance_body`; at sealed code commit `a0ea755`, line 95 was a post-draw working-tree `glob("*acceptance*")`. The external failure receipt contains no benchmark metrics, and the failure review/phase keep M3-D at `0/8` without inferring quality PASS or FAIL. `RESULT-INVALID` is therefore the correct classification for this runner/chronology defect. |
| Q3 | **DIRECT** | The current canonical test computes a two-element presence tuple for suite/race and requires `len(set(present)) == 1`, so one-body-only state fails. When both bodies exist it loads the current prearm, takes `prearm["code_commit"]`, and invokes `git cat-file -e <commit>:<each canonical path>` for both bodies, requiring both lookups to be absent. When neither body exists it requires the current prearm to be absent. This is the required canonical pair atomicity and sealed-commit check. |
| Q4 | **LIMITATION — blocks PASS** | `test_failed_attempt_archive_proves_post_draw_chronology` passes the renamed archive paths `failed-attempt-1-acceptance-{suite,race}-suite.json` to the helper. The helper therefore checks absence of those **new archive names** at `a0ea755`, not absence of the historical canonical names `acceptance-suite.json` and `acceptance-race-suite.json`. Object inspection makes the non-equivalence concrete: at `604e1d0` both canonical bodies are present while both archive names are absent, so the current archive-path test would accept that path relation even though canonical bodies exist. Direct `git cat-file` inspection independently confirms that the two old canonical paths really are absent at `a0ea755`; the historical fact is true, but the dedicated executable test does not prove that fact. Required fix: keep the archived-file existence checks, but pass a separate pair of historical canonical Git paths to the sealed-commit lookup; then update the bound test hash and obtain a new clean critic checkpoint. |
| Q5 | **DIRECT** | All five current canonical artifact paths are absent: suite, race suite, custody transcript, prearm seal, and final receipt (`0/5`). The external custody parent still contains only the `a0ea755…` directory; its result digest remains the failure-review digest and all external file mtimes precede correction commit `5a3a302`. This review performed read-only inspection only and did not call a custodian or acceptance script. |
| Q6 | **DIRECT** | Blob-by-blob comparison over `a0ea755..5a3a302` is identical for `src/research_os/meta_evaluation.py`, `service.py`, `autonomy/loop.py`, `agent_install.py`, the generator/public-boundary/external/attack manifests, `m3d_custodian.py`, prepare/runner/verifier, and the protocol/external/release tests. Thus product, generator, public renderer/oracle/selector/metric/threshold, historical v0.2 binding, custodian, runner, and verifier bytes did not change. The executable change is restricted to the chronology test plus its release-manifest hash; the remaining changes archive Attempt 1 evidence and synchronize documentation. |
| Q7 | **DIRECT** | The release manifest binds `tests/test_m3d_meta_evaluation.py` to exact SHA-256 `26be2ecb…c207`, which is the current file hash, and its whole pre-nonce binding test passes. Independent reproduction: focused M3-D `64 passed in 18.92s`; full collection `922 tests collected in 0.20s`; Ruff PASS; offline `ty` PASS; `git diff --check` PASS. These green checks do not close Q4 because the bound archived test is semantically pointed at the wrong historical paths. |
| Q8 | **DIRECT** | Current canonical acceptance artifacts are absent and the custody root has no directory for `5a3a302`; only the invalid Attempt 1 `a0ea755…` custody remains. Phase §14.10/§14.15 requires a distinct clean code checkpoint, distinct custody path, new one-time nonce, and a later critic PASS before any new draw. Release manifest, failure result, failure review, and phase keep `product_multi_agent=false`, `live_migration=false`, and `authorized_action=null`; product multi-agent remains after NS6 and live pilot/migration remains post-v0.5. |

### Blocking finding

Q4's archived test proves the absence of paths that did not exist until the archive rename, not the absence of the
two body paths that were canonical at the sealed code commit. The test passes and the underlying `a0ea755` chronology
fact is independently true, but a false-positive witness remains possible because the path sets differ. Attempt 4
therefore cannot authorize a new draw from `5a3a302`.

The minimal correction is test-only: distinguish current archived artifact paths from historical sealed-commit body
paths, assert the former exist and query the latter with `git cat-file`. That correction changes a release-bound byte,
so it requires a new manifest hash, clean checkpoint, and independent critic re-verification. It does not authorize a
same-draw rerun or any product/generator/oracle/metric/custodian/runner/verifier change.

### Reproduction evidence

- Archived/external consistency: external result SHA, bundle equality, raw archive digests, canonical suite/race
  digests, nonce commitment, reservation and authority/capability fields all matched.
- Git-object path matrix at `a0ea755`, `604e1d0`, and `5a3a302`: old canonical bodies are absent/present/absent;
  renamed archive bodies are absent/absent/present.
- Targeted chronology + manifest-binding nodes: `3 passed in 0.10s`.
- Complete M3-D focused suite: `64 passed in 18.92s`.
- Full collection: `922 tests collected in 0.20s`.
- Targeted Ruff, offline `ty`, and `git diff --check`: PASS.
- Attempt 4 audit count: questions `8`; DIRECT verified `7`; LIMITATION `1`; failed `1`.

### Custody confirmation

This review did not invoke `scripts.m3d_custodian`, `scripts/prepare_m3d_acceptance.py`,
`scripts/run_m3d_acceptance.py`, a real nonce source, or any external write. External Attempt 1 custody was read only.
No current suite, race suite, custody transcript, prearm seal, final receipt, new custody directory, or nonce was
created. Acceptance Attempt 1 and critic Attempts 1–3 remain preserved unchanged.
