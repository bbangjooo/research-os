# Progress audit — Phase 12 M3-B
## Attempt 1 — FAIL

S1: stale Python LOC; inconsistent inclusive LOC; stale critic sequencing; no stricter Cycle 12 rescore assumption.
S2: five `ty` diagnostics; footprint finding lacked retain/trim/rebaseline follow-up.
Evidence reproduced: focused `60`, adjacent `125`, correction `9`, service `12/45`, manifest `43/43`, ruff PASS;
actual service/source reconciliation/tamper/post-terminal behavior real. Then-current cycle `3,848/3,900`.
## Attempt 2 — FAIL
S1: `7cd7c4f` mislabeled as correction; MIXED per-row table absent; `e60b5dd` type fix attributed to `f53e37c`.
No S2; engineering/static exact; reproducibility `22/24`, then-current `3,890/3,900`.
## Attempt 3 — FAIL
S1: actual docs/total `473`/`3,900`, not `463`/`3,890`; next action stale. Prior S1s PASS; no S2.
## Attempt 4 — PASS
S1/S2 `0/0`; reproducibility `29/29`; exact final `3,900/3,900`; M3-B closed, M3-C active.
