# Progress audit — Phase 14 M3-D / v0.5

VERDICT: FAIL

Audit target: clean checkpoint `11f79478b2eb2d6d95a08c2ee4af07e132eb1ba4`.

Severity-1 findings (each blocks PASS):
- [Reproducibility] `docs/research-os-status/14-2026-08-12-m3-d-unseen-release.md:53` — the stated required choice threshold `20.1042%` does not equal the sealed comparator formula: `1/96 + 20 percentage points = 21.041666…%`, which is also the exact receipt value `0.21041666666666667` — required fix: replace the false percentage with `21.0417%` (or the exact fraction/value) everywhere it is claimed, without changing the sealed gate or result.
- [Drift / whitewash] `docs/research-os-status.md:522`; `docs/research-os-pipeline.md:431-437` — Cycle 14 changed the M3-D choice and terminal target from `min(90%, v0.2+20%p)` to the stricter `max(v0.2,min(90%,v0.2+20%p))`, yet status says “M chain definition unchanged” and the M-chain definition-change ledger has no Cycle 14 row — required fix: remove the false unchanged claim, record the pre-result critic trigger and exact amendment in the status Decision chain and pipeline §9.5, and add the Rule 9 retrospective/correction artifact required for a first-class M-chain definition change.

Severity-2 findings (advisory, do not block):
- None.

Four-pass result:
- Schema — PASS. The phase has non-empty scope, built evidence, validation, system impact, and residual issues. Status refreshes §0, North-Star evidence/impact, LOC, pessimistic re-score, and phase index; pipeline re-rates stage 7 with evidence.
- Reproducibility — FAIL. The immutable release evidence reproduces, but the phase's numeric choice-threshold claim is false.
- Drift / whitewash — FAIL. The target was tightened before result exposure, so this is not ship-then-relax; nevertheless the required decision-chain/§9.5/Rule-9 change record is absent and the status contains a contrary claim.
- Linguistic weakness — PASS. Forbidden-language hits occur only in future-work/limitation prose; no evidence/current cell relies on them. The pessimistic re-score preserves the stricter synthetic-transfer limitation, and no progress row is LOC-only.

Independently reproduced evidence:
- Receipt and external result bytes are identical at SHA-256 `95e7eb5f3876cc445dde2fee0a5b91462ce8e2f187f28f32acfffff96c0a5387`; `authorized_action=null`, `product_multi_agent=false`, and `live_migration=false`.
- The eight release conjuncts reproduce: unseen symmetry `36/36`; protocol `24` rows/`25` tests; evidence terminals `36/36`; closed-class retry `0`; choice `96/96` vs `1/96`; terminal `36/36` vs `0/36`; waste `0` vs `36`; external replay/opaque/no-write `3/3/0`, managed upgrades `7/7`, race `12/12`, full suite `922+115`, installed wheel `0.5.0`.
- Prearm seal `ba24712d…5cfef1`, canonical suite digest `6ffa2f…a914`, and race digest `ffcf9b…7213` equal the immutable external bundle. The 36 episodes are `6×6` families and 12 races are `4×3` boundaries.
- Acceptance bodies are absent at sealed code commit `463df30` and first appear at `16c8fa2`; only the receipt is added at `ca69bb9`, and `ca69bb9..11f7947` is docs-only. No product/generator/oracle/metric/custody/verifier byte changed after the valid code checkpoint.
- Attempt 1 remains `RESULT-INVALID`, its external result SHA `9b67285b…aaf80` and all four archive SHAs reproduce, and `rerun_same_draw=false`. Critic history remains Attempt 1 FAIL, 2 FAIL, 3 PASS, 4 FAIL, 5 PASS.
- Safe targeted validation passed `9`; `ruff check src scripts tests` passed; `uvx --offline ty check src` passed. No acceptance, custodian, nonce, prepare, full-suite, or release-verifier command was rerun.
- Pre-audit churn is `4,981/6,000`; after this 34-line audit it is `5,015/6,000`. Generated/evidence JSON is `10/1,200`; phase+critic+receipt+audit is `652/800`.
- Synthetic-only scope, post-v0.5 live pilot/migration, product multi-agent deferral, and null authority are synchronized across the close-candidate artifacts.

Audit trail:
- Reproducibility checks run: 32 | matched: 31 | mismatched: 1 | unrunnable: 0
- Files inspected: status core, pipeline core, Phase 14, critic, receipt, current/Attempt-1 suite/race/prearm/custody artifacts, both external custody bundles/results/reservations/transcripts, generator/release manifests, targeted source/tests, git history
- git range audited: `7b00e0b..11f7947`
- M3-D, parent M3, and v0.5 release close are not permitted by this audit.

## Attempt 2 — corrected seven-pass re-audit

VERDICT: FAIL

Severity-1 findings:
- [Reproducibility] `docs/research-os-status.md:461` — `phase+critic+receipt+audit/correction 750/800` is
  unreproducible. The precommitted category is `316+325+1+34=676`, while adding both correction artifacts gives
  `676+69+47=792`; `750` matches neither convention. Required fix: retain the original category, count this preserved
  audit in its audit component, and report the two correction artifacts separately under the inclusive cap.

Severity-2 findings: none.

Seven-pass trail:
- Schema, Drift/whitewash, Linguistic weakness, Intent-Execution drift, Claim-mode integrity, and
  Milestone-discipline integrity: PASS.
- Reproducibility: FAIL only on the LOC subcount; receipt, custody, chronology, thresholds, inclusive churn and safe
  validation otherwise reproduce.
- Checks `46`: matched `45`, mismatched `1`, unrunnable `0`; safe targeted tests `9`, Ruff and ty PASS.
- Attempt 2 remains CONFIRMATORY; Attempt 1 remains archived `RESULT-INVALID` and was never rerun.
- All eight non-compensating M3-D conjuncts, Rule 9 verbatim “승인”, foundation critic PASS, and parent M3/v0.5
  open-until-audit boundary reproduce.
- No acceptance, custodian, nonce, arm-run, full-suite, or release-verifier command was executed.
- git range audited: `7b00e0b..9bdec8a18ffe0995303f6eed71c0fd1f4148eff0`.
