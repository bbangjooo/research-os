# Cycle 14 Rule 9 retrospective — M3-D non-regression threshold

> Status: **PENDING USER VERDICT**
> Trigger: final progress audit Attempt 1 drift/whitewash finding
> Scope: M3-D choice and terminal thresholds only

## Amendment

Original M3-D target:

`score(v0.5) >= min(90%, score(v0.2) + 20 percentage points)`

Strengthened pre-result target:

`score(v0.5) >= max(score(v0.2), min(90%, score(v0.2) + 20 percentage points))`

This prevents v0.5 from regressing when v0.2 already exceeds 90%. It was specified in correction checkpoint
`e23c089` and implemented at `20b35a5`, before either acceptance nonce/body/result. It did not change the episode
count/families, candidate language, arms, protocol/evidence/retry/waste/compatibility gates, authority boundary,
single-agent scope, or post-v0.5 live-pilot/migration exclusion.

## Coverage / sufficiency / faithfulness

- **Coverage:** still measures the approved “same budget, more accurate and less wasteful” goal; no goal object was
  added or removed.
- **Sufficiency:** it closes a loophole in the existing accuracy conjunct rather than adding a new milestone.
- **Faithfulness:** non-regression is stricter and closer to the natural intent than permitting a stronger baseline
  to deteriorate to 90%. Synthetic-only and read-only compatibility limitations remain unchanged.
- **Chronology:** pre-result strengthening; no threshold was relaxed after observing either draw.

## User verdict requested

Please approve or reject this exact governance correction:

> “M3-D의 choice/terminal release threshold를
> `max(v0.2, min(90%, v0.2+20%p))`로 강화한 변경을 승인한다. 이는 baseline >90%에서의 퇴행을
> 금지하며, 기존 v0.5 scope·synthetic-only claim·post-v0.5 live pilot/migration·multi-agent 경계를 바꾸지 않는다.”

Until an explicit verdict is recorded, M3-D stays an `8/8` close candidate and parent M3/v0.5 is not closed.
