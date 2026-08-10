# Critic — Phase 06 (2026-08-11) — m1-e-release-close

영향 §북극성 행: NS1, NS2, NS3, NS5

## Q1 [milestone-positioning]

Cycle 05의 첫 conjunct를 재검증하고 §9.4 M1-E의 기존 5개 AND-conjunct를
재정의·삭제 없이 모두 독립 증거로 충족할 때만 `CLOSE`하며, 하나라도 실패하면
M1-E를 open으로 유지하도록 §06.6.4에 고정했는가?

**Response:**

DIRECT after correction. §06.6.4가 five conjunct를 유지하고 explicit decision을 `ADVANCE
(5/5 verified; independent re-audit pending)`로 고정한다. Re-audit PASS 전에는 CLOSE가 아니다.

## Q2 [boundary]

NS2·NS3에 대해 active v2-generation의 모든 tokenless
registration·retry·successor write path가 Proposal, pending Diagnosis, class closure,
locked budget gate를 우회하지 못하고 거절 시 event·budget delta가 0이며,
pre-generation legacy record는 typed state로 자동 승격되지 않음을 하나의 고정
manifest가 증명하는가?

**Response:**

FAIL on second re-audit. `path`가 manifest에 선언됐지만 dispatcher가 소비하지 않았고 legacy
replay가 Proposal/Diagnosis/ClassState promotion zero를 직접 노출하지 않았다. Next correction은
executed source operation을 normalized path와 exact bind하고 typed registration/proposal/diagnosis/
class-state count 0을 manifest expected로 비교한다.

## Q3 [measurement-gap]

NS1의 하위호환 청구는 default Context v3와 explicit v3의 exact 일치뿐 아니라
explicit Context v2, context-token/snapshot v2, branch conclusion v1, v1 event의
CLI·service·cold-replay bytes와 digest가 사전 동결 fixture 그대로임을 측정하는가?

**Response:**

DIRECT. §06.6.2와 §06.6.4가 default v3=explicit v3, explicit Context v2, snapshot v2,
branch conclusion v1, frozen v1 bytes/digest와 cold replay를 분리해 기록한다. Initial full은
legacy observer가 explicit v2를 누락해 RESULT-INVALID였고 `888cd96` 뒤 새 full이 PASS했다.

## Q4 [boundary]

Compatibility/authority 영역의 upgrade manifest는 byte-exact managed 0.2.0 tree만
0.3.0으로 바꾸고 drifted·unknown·unmanaged tree는 writer delta 0으로 거절하며,
각 transactional failure 지점에서 원본 tree와 recovery state를 exact 복구함을 모두
포함하는가?

**Response:**

DIRECT. Frozen six-case installer matrix와 source commit `6f36a1b`의 five-file/two-directory
signature만 recognized prior다. Actual published bytes로 two-target upgrade와 backup 2를
확인했고 drift rejection writer delta는 0이다. Unknown/unmanaged도 no-write이며 기존 0.1
path와 transaction recovery tests가 full suite에 포함됐다.

## Q5 [external-validation]

NS1 release gate는 `pyproject.toml`, `__version__`, `uv.lock`, package metadata와
문서의 0.3.0 동기화, 전체 Python 3.12 suite, release manifest, recursive
`authorized_action=null`을 단일 fail-closed 검증으로 묶어 stale lockfile·누락
suite·부분 문서 sync가 green이 되지 못하게 하는가?

**Response:**

FAIL on second re-audit. No-bypass/full/authority/wheel binding은 PASS했지만 docs exact 0.3.0을
강제하지 않았고 external policy는 absolute-string scan, multi-agent policy는 keyword scan뿐이었다.
Next correction은 four docs exact 0.3.0, 세 sibling project `.research-os` pre/post byte snapshot,
reviewed product Python tree exact file-count/digest를 manifest에서 소비한다.

## Q6 [end-state-positioning]

이번 phase의 §06.6.5는 Context와 Compatibility/authority의 before/after만
구체화하되 Claim/retrieval reason은 M2에 남기고, 세 외부 프로젝트의 live
migration과 제품 multi-agent를 계속 제외하며, 이를 숨기려고 §8.2 행동이나 §8.3
경계를 축소하지 않는가?

**Response:**

DIRECT. §06.6.5는 Context와 Compatibility/authority의 before/after만 구체화하고
Claim/retrieval은 M2에 남긴다. 외부 프로젝트 접근 0, live migration 유예, 제품 multi-agent
0/NS6 이후 조건을 그대로 유지한다. §8.2/§8.3 경계를 축소하지 않는다.

## Q7 [proxy-vs-real]

NS5는 Context v3 default와 수동 diagnosis 경로가 편해져도 canonical
FSM·crash-resume 7개 transition을 만들지 않으므로 계속 `0/7`이며, 이 UX 개선을
autonomous-loop 진척으로 대리 청구하지 않는가?

**Response:**

DIRECT. §06.6.9가 NS5를 `0/7`로 유지하며 finite FSM과 crash-resume 부재를 limitation으로
명시한다. Context/Diagnosis UX를 autonomy 분자로 세지 않는다.

## Q8 [claim-mode-discipline]

Acceptance, fixture denominator, upgrade failure matrix, release-manifest 판정값을
구현·테스트 결과 전에 pre-spec commit으로 고정하고 first-data commit과 timestamp를
남기며, 결과 노출 후 어느 기준이라도 바뀌면 해당 결과를 `RESULT-INVALID` 또는
`EXPLORATORY`로 낮추고 M1-E `CLOSE`를 금지하는가?

**Response:**

DIRECT after correction. §06.6.7은 explicit `CONFIRMATORY`이고 correction pre-spec `3eaba21`이
implementation `1aa9c58`의 direct parent다. 그 이전 A3/A5 aggregate 결과는 제외하고 clean
implementation에서 처음 얻은 single receipt만 분자로 사용한다.
