# Audit — Phase 01 M1-A Evidence Correctness

> Final verdict: **PASS**
> Audited scope: phase §01, critic Q1~Q8, paired status/pipeline cores, commits `c1f1b75` and `ed76067`, preserved baseline tag `research-os-m1a-working-tree-baseline`

## 1차 감사 — FAIL

7-pass progress audit는 18개 재현 항목 중 17개를 재현하고 1개를 거절했다. 문서가 승인된 dirty-working-tree 기준선 `262/57`을 clean bootstrap docs commit `e728df9`에 귀속했지만, clean tree는 `261/54`였고 당시 dirty tree의 immutable ref가 없었다. 그 결과 E9 evidence, full-regression claim mode, M1-A common close oracle가 함께 차단됐다.

## 수리

- Git unreachable object에서 exact dirty tree `b7523f4ff1aa2a986544fcbc73744b76f6984db6`를 복구했다.
- base `6f36a1b`를 parent로 하는 보존 commit `50c495780b6bec6058b7f0ee4393f8217c4ed169`을 만들고 tag `research-os-m1a-working-tree-baseline`을 연결했다.
- `git diff --stat 6f36a1b research-os-m1a-working-tree-baseline`은 승인된 두 파일만 보인다: `src/research_os/certification.py +17/-1`, `tests/test_evaluator_certification_unit.py +76/-1`.
- 별도 detached worktree에서 Python 3.12 full suite를 실행해 `262 passed, 57 subtests passed in 54.66s`를 재현했다.
- phase/status 문서는 clean `e728df9` bootstrap docs checkpoint와 dirty baseline artifact를 분리하고, 1차 E9 evidence를 `RESULT-INVALID`로 제외한 뒤 재측정 결과만 final close evidence로 사용한다.

## 재감사 — PASS

같은 독립 progress auditor가 Schema / Reproducibility / Drift / Linguistic-weakness / Intent-Execution drift / Claim-mode integrity / Milestone-discipline integrity 7개 pass를 다시 수행해 `VERDICT: PASS`를 반환했다.

- E1~E8: 기존 독립 재현 PASS 유지.
- E9: 보존 baseline `262/57`, current full `290/67`, authority non-null `0` 재현.
- Claim mode: certification patch는 EXPLORATORY 유지; typed gate/baseline VERIFY/full regression만 pre-spec 순서에 근거한 CONFIRMATORY candidate.
- Milestone: M1-A 4/4 + common regression oracle 충족; M chain 정의 변경·gate bypass 없음.
- North star: NS1은 부분 진척, NS2는 `0/6` 유지.
- Scope: live external-project migration과 product multi-agent 구현 없음.
