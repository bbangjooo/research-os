# Kernel — experiment loop

Research OS 2 설계(`docs/research-os2-design.md`)의 Layer 0. bounded·reversible·budgeted hill-climb 실행기이며, 이 저장소에서는 어떤 코드도 이 파일을 수정하지 않는다.

## 단일 소스 규칙

- **Upstream은 `infocz/gos`의 `loop/`다.** 이 디렉토리는 그 vendored 사본이며, 사본의 출처와 digest는 `VENDOR.json`에 고정된다.
- 여기서 엔진을 직접 고치지 않는다. 수정이 필요하면 upstream(gos)에 반영한 뒤 다시 vendoring한다.
- 사용처(이 repo, `~/crypto-new`)는 모두 같은 `VENDOR.json` 스키마를 두며, digest 비교만으로 분기 여부를 판정할 수 있다.

## 구성

| 파일 | 역할 |
| --- | --- |
| `loop/experiment_loop.py` | 엔진 전체 (stdlib + PyYAML, 단일 파일) |
| `loop/template.yaml` | spec 스키마의 source of truth (주석 포함) |
| `tests/test_experiment_loop.py` | 계약 테스트 스위트 — 엔진과 함께만 이동한다 |
| `VENDOR.json` | upstream commit + 파일별 sha256 |

## 갱신 절차

1. upstream에서 세 파일을 복사한다.
2. 테스트를 실행한다: `uv run --with pytest --with pyyaml pytest kernel/tests/ -q`
3. `VENDOR.json`의 commit과 digest를 갱신한다.
