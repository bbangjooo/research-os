# Progress audit — Phase 12 M3-B

## Attempt 1 — FAIL

Severity-1 findings:
1. Status §1.1 Python LOC `64,344` is stale; the documented command returns `67,674`.
2. The `3,729` inclusive estimate is internally inconsistent; the complete audited cycle is `3,848/3,900`.
3. Phase §12.6.4/§12.10 still says critic pending although critic Attempt 2 is PASS.
4. Cycle 12's pessimistic score has neither a downgrade nor a newly stricter reviewer assumption.
Severity-2 findings:
- `uvx --offline ty check src` reports five new M3-B diagnostics.
- The product-footprint `GENUINE-FINDING` lacks a §12.10 retain/trim/rebaseline follow-up.

Engineering evidence reproduced: focused `60`, adjacent `125`, correction `9`, actual-service slice
`12 passed, 45 deselected`, ruff PASS, manifest `43/43` with exact groups and unchanged hashes. Actual
`ResearchService`, canonical ProjectLog/ProgramLog reconciliation, tamper rejection, and the seven-case
post-terminal matrix are real. Product churn is `2,029`, tests/fixture `1,384`, and the pre-audit paired
cycle is `3,848/3,900`. M3-B is not close-eligible and M3-C remains blocked pending correction and re-audit.
## Attempt 2 — FAIL
- Status mislabels failure-record commit `7cd7c4f` as the correction; actual correction is `e60b5dd`.
- §12.6.7 `MIXED` is prose-only, not the required per-row CONFIRMATORY/EXPLORATORY table.
- The prose also attributes `e60b5dd`'s type-contract correction to `f53e37c`. No S2 findings.
- Engineering and prior fixes reproduced: `60/125/9/12`, ruff/ty PASS, exact `3,890/3,900`; 22/24 matched.

## Attempt 3 — FAIL
Exact docs are `473` and `3,900/3,900`, not `463`/`3,890`; next-action text is stale. Prior S1s PASS; no S2.
## Attempt 4 — PENDING
Awaiting final independent re-audit; M3-C remains blocked.
