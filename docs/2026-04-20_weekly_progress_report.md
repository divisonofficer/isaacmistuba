# 2026-04-20 그룹 콜라보레이션 미팅 경과보고

기간: 2026-04-11 ~ 2026-04-19

작성 기준:

- `git` 커밋 이력
- 현재 워킹트리 diff
- `out/control_plane_cache/isaac_command_telemetry.jsonl`
- `out/bridge_jobs/`
- 진행 문서 및 가이드 문서

## 1. 이번 주 한 줄 요약

이번 주에는 `Isaac Sim -> daemon -> Mitsuba` 파이프라인의 기본 골격을 실제로 올리고, MooreLane 대형 씬에서 세션 연결/동기화/렌더를 반복 검증했으며, 후반부에는 같은 씬 반복 렌더의 병목을 줄이기 위한 세션 재사용/부분 동기화/scene cache 계열 최적화까지 구현 단계로 끌고 왔다.

## 2. 핵심 결론

- 4월 14일 기준으로 브리지, 렌더러, daemon, 기본 웹 UI를 포함한 end-to-end 구조가 저장소에 올라왔다.
- 4월 15일~17일에는 MooreLane 실기 기준으로 세션 연결, sync, material override, render current view를 반복 검증했다.
- 4월 17일에는 데몬 대시보드 UI와 Isaac extension 운용성이 크게 확장되었다.
- 현재 워킹트리에는 같은 씬 반복 렌더 최적화와 재질 UX 개선이 대규모로 추가되어 있으며, 실질적으로 이번 주 후반 작업의 중심이었다.
- 4월 11일~13일 구간은 이 저장소 안에서 확인 가능한 커밋 증거가 없었다.

## 3. 날짜별 진행 요약

### 2026-04-14

- `[04.14] init commit`
- 초기 파이프라인 구축 완료
- 포함 범위:
  - Isaac stage capture / standalone export
  - `robomituba_bridge` 계약 패키지
  - Mitsuba multimodal renderer
  - render daemon
  - 기본 control plane UI
- 대표 파일:
  - `apps/render_curated_multimodal.py`
  - `apps/isaac_standalone/_stage_bridge.py`
  - `modules/robomituba_bridge/src/robomituba_bridge/__init__.py`
  - `modules/mitsuba_converter/src/mitsuba_converter/multimodal.py`
  - `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`

### 2026-04-15 ~ 2026-04-16

- MooreLane 대형 씬 실기 검증 및 반복 세션 실행
- 텔레메트리 기준 확인된 내용:
  - `load_scene` 완료
  - `connect_session` 완료
  - `sync_session` 완료
  - `apply_material_override` 완료
  - `render_current_view` 반복 시도
- `out/bridge_jobs/` 아래에 4월 15일, 16일 세션 산출물이 다수 생성됨
- 의미:
  - 단순 코드 작성이 아니라 실제 운용 경로를 반복 실행하며 문제를 찾는 단계까지 진행됨

### 2026-04-17

- `[04.17] 데몬 대시보드 ui`
- 주요 확장:
  - Isaac extension 구조 강화
  - 데몬 대시보드 및 scene detail UI 고도화
  - BRDF 가이드 및 dataset 설정 추가
  - Ranger Mini 관련 자산 및 코드 추가
- 같은 날짜에 최적화 분석/상태 문서 작성:
  - `docs/2026-04-17_mitsuba_redundancy_analysis.md`
  - `docs/2026-04-17_same_scene_render_optimization_status.md`
  - `docs/BRDF_IMPLEMENTATION_GUIDE.md`

### 2026-04-18 ~ 2026-04-19 기준 워킹트리

- 아직 커밋되지 않았지만 큰 폭의 추가 작업이 진행 중
- 핵심 방향:
  - same-scene 반복 렌더 최적화
  - partial sync 정책 정교화
  - render timing telemetry 강화
  - measured material preview 및 dataset 다운로드 UX 보강
  - settings/언어 분리 UI 추가

## 4. 이번 주 완료된 것

### A. end-to-end 파이프라인 골격 구축

- Isaac 상태를 수집하고 bridge 계약 형태로 전달하는 경로를 정리했다.
- daemon이 scene/session/render 요청을 중간에서 orchestration 하는 구조를 올렸다.
- Mitsuba 쪽에서 multimodal rendering RGB/depth/polarization 계열 출력 기반을 만들었다.

### B. 실제 씬 기반 운용 검증

- MooreLane 대형 씬을 대상으로 실제 load/sync/render 경로를 반복 실행했다.
- 텔레메트리 기준으로 대형 씬 메타데이터가 기록되며, `asset_file_count = 2332`, `size_tier = huge`가 확인된다.
- 반복 세션 산출물이 `out/bridge_jobs/` 아래에 남아 있어 실기 실행 흔적이 명확하다.

### C. 데몬 대시보드/운영 UI 확장

- scene detail, jobs, system, isaac guide 등 control plane UI가 크게 확장되었다.
- render 진행률, job 상태, 세션 상태를 사용자 관점에서 볼 수 있는 기반이 정리되었다.

### D. 문서화

- 병목 분석 문서와 최적화 상태 문서를 남겨서, 구현 방향과 현재 구현 범위를 추적 가능하게 만들었다.
- BRDF/편광/NIR 데이터셋 우선순위 문서를 추가해 이후 material ingestion 방향을 정리했다.
- Isaac Sim 가이드 한/영문 문서를 추가해 실제 사용 절차를 정리했다.

## 5. 실기 로그 기준 검증 결과

`out/control_plane_cache/isaac_command_telemetry.jsonl` 집계:

- 총 telemetry row: `1200`
- 날짜별 row 수:
  - `2026-04-15`: `373`
  - `2026-04-16`: `554`
  - `2026-04-17`: `273`
- complete 이벤트 기준:
  - `connect_session`: `20`회 성공
  - `sync_session`: `32`회 성공
  - `load_scene`: `16`회 성공, `1`회 실패
  - `apply_material_override`: `16`회 성공
  - `render_current_view`: `2`회 성공, `14`회 실패
- complete 이벤트 평균 소요시간:
  - `load_scene`: `45.82s`
  - `connect_session`: `8.05s`
  - `sync_session`: `12.09s`
  - `apply_material_override`: `3.19s`
  - `render_current_view`: `170.94s`

해석:

- 씬 로드/세션 연결/동기화/재질 적용은 반복 수행 가능한 수준까지 올라왔다.
- `render_current_view`는 아직 성공률이 낮고, 실제로 same-scene 반복 렌더 최적화가 필요한 상황이었다.
- 후반부 최적화 작업은 이 문제를 줄이기 위한 직접 대응으로 해석할 수 있다.

## 6. 현재 거의 완성된 것으로 보이는 진행 중 작업

### A. same-scene 반복 렌더 최적화

- `multimodal.py`에 다음 계열 캐시/최적화가 들어가 있다.
  - Mitsuba XML parse cache
  - branch template cache
  - resident Mitsuba scene cache
  - staged XML rewrite skip
  - staged scene signature cache
- 의미:
  - 카메라만 바뀌는 반복 렌더에서 CPU-side 중복 작업을 크게 줄이려는 구현이 이미 들어가 있다.

### B. full sync -> partial sync 전환

- `daemon_client.py`, `ui_panel.py`, `render_daemon.py`에 `camera_only`, `material_delta`, `full_resync` 흐름이 반영돼 있다.
- UI dirty flag와 세션 상태를 결합해서 어떤 수준의 sync를 할지 나누는 방향이 보인다.

### C. render telemetry 및 daemon 운영성 강화

- render timing summary, cache hit/miss, pass count 등이 daemon telemetry에 붙기 시작했다.
- blocking render를 queue worker 경로로 합쳐서 경로를 단일화하는 작업이 반영돼 있다.

### D. 재질 UX 개선

- measured material preview 구 렌더 기능이 추가되고 있다.
- dataset별 미다운로드 상태 표시와 auto-download API/UI가 추가되고 있다.
- 파일이 없어도 material ID별 고유 색 roughplastic fallback sphere를 보여 주도록 정리 중이다.

## 7. 이번 주 기준 남아 있는 리스크 / 미완성 지점

- `render_current_view` 성공률이 아직 낮다.
- same-scene 반복 렌더 최적화는 구현이 많이 들어가 있지만, 정량 성능 비교 결과는 아직 별도 표로 정리되지 않았다.
- settings 페이지와 일부 UI는 아직 untracked 상태여서 최종 구조가 확정되진 않았다.
- Ranger Mini 관련 자산 일부는 아직 정리 중이며, 자산 파이프라인과 실기 시나리오 연결은 더 확인이 필요하다.

## 8. 발표용 메시지

이번 주 작업은 단순 UI polish가 아니라, `Isaac Sim과 Mitsuba를 실제로 연결해서 반복 운영 가능한 상태로 끌어올리고`, 그 과정에서 드러난 병목을 `same-scene 반복 렌더 최적화`로 직접 해결하기 시작한 주간으로 정리할 수 있다.

즉 현재 위치는 아래와 같다.

- 파이프라인 골격: 구축 완료
- 실제 씬 기반 연동: 수행 및 로그 확보
- 운영 UI: 크게 확장됨
- 반복 렌더 성능 문제: 원인 분석 완료
- 최적화 구현: 상당 부분 진행
- 최종 안정화/정량 비교: 다음 단계

## 9. 다음 단계 제안

### 바로 다음 우선순위

- same-scene 반복 렌더 전/후 시간 비교 표 만들기
- `render_current_view` 실패 케이스를 유형별로 정리하기
- partial sync 정책이 실제로 full sync 대비 얼마나 이득인지 계측하기
- settings/material UX 변경을 최종 구조로 정리하고 커밋 단위로 묶기

### 4월 20일 미팅에서 공유하면 좋은 포인트

- 이번 주는 “연결”보다 “운용성 확보와 반복 렌더 최적화 진입”에 의미가 있다.
- 이미 MooreLane 실기 로그와 세션 산출물이 있어서, 개념 검토 수준은 넘어섰다.
- 다음 주에는 성능 수치와 안정성 지표를 붙이면 보고 체계가 더 단단해진다.

## 10. 근거 파일

- `git log`
  - `f39f4c0` `[04.14] init commit`
  - `124ae85` `[04.17] 데몬 대시보드 ui`
- 문서
  - `docs/2026-04-17_mitsuba_redundancy_analysis.md`
  - `docs/2026-04-17_same_scene_render_optimization_status.md`
  - `docs/BRDF_IMPLEMENTATION_GUIDE.md`
  - `docs/isaac_sim_guide.ko.md`
- 로그/산출물
  - `out/control_plane_cache/isaac_command_telemetry.jsonl`
  - `out/bridge_jobs/`
- 현재 워킹트리 핵심 파일
  - `apps/isaac_extension/daemon_client.py`
  - `apps/isaac_extension/ui_panel.py`
  - `modules/mitsuba_converter/src/mitsuba_converter/multimodal.py`
  - `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`
  - `modules/mitsuba_converter/src/mitsuba_converter/material_library.py`
  - `modules/mitsuba_converter/src/mitsuba_converter/sphere_preview.py`
  - `modules/mitsuba_converter/src/mitsuba_converter/templates/scene_detail.html`
  - `modules/mitsuba_converter/src/mitsuba_converter/templates/settings.html`
