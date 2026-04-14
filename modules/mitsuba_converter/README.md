# mitsuba_converter

USD 씬을 읽어서 Mitsuba가 렌더 가능한 형태(우선 `mi.load_dict()` 기반)로 변환하는 컨버터 모듈.

이제 legacy USD 직접 변환 경로와 함께 bridge job manifest 기반 렌더 경로를 병행 지원한다.

## 목표(MVP)
- MooreLane 같은 USD에서
  - `UsdGeom.Mesh` 추출
  - `UsdGeom.PointInstancer`(가능하면) 지원
  - 재질은 1차로 단색 diffuse(검정 방지)
- Mitsuba 3 `scalar_rgb` 기준으로 테스트 렌더 1장 생성
- `robomituba_bridge` manifest / snapshot 기준 sidecar render 지원

## 실행(예정)
- `python -m mitsuba_converter.cli --usd <path> --out <out_dir>`
- `python -m mitsuba_converter.cli render-job --manifest out/bridge_jobs/<job_id>/manifest.json`

> Isaac/Mitsuba 동기화(변경 감지)는 2단계로 확장.
