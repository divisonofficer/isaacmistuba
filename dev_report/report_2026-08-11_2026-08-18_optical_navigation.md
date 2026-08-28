# Optical Navigation 개발 보고서

기간: 2026-08-11 ~ 2026-08-18  
작성일: 2026-08-18  
범위: OpticalNav 장면 생성·그래프·렌더링·export·운영 산출물 관리

## 요약

이번 기간에는 OpticalNav를 단순한 viewpoint 렌더 스크립트가 아니라, 장면 생성 규칙부터 graph 생성, 다중 GPU 렌더 큐, modality 상태 표시, export 및 산출물 보존까지 연결된 데이터셋 제작 흐름으로 확장했다.

주요 결과는 다음과 같다.

- Modern Office 장면을 결정적으로 생성하고, 일반 사무실과 structural-glass 변형을 구분할 수 있는 wizard·room program·graph audit을 추가했다.
- Render daemon에 batch/sharding/resume 상태를 강화하고, flash/spectral/spatial-PBR 경로를 OpticalNav 렌더 흐름에 연결했다.
- Web UI와 exporter가 렌더 상태 및 modality를 표시하도록 갱신했다.
- OpticalNav 프로젝트의 `scenes`, `episodes`, `splits`, `exports`, `render_ledger.sqlite3`를 핵심 보존 대상으로 식별하고, `out/` 정리 시 역참조 기반 판정 기준을 정리했다.

## 작업 내역

### 1. Modern Office 장면 생성 규칙 및 wizard

관련 커밋: `37cd36d` (`feat(office): Modern Office OpticalNav 생성 규칙과 wizard를 추가한다`)

- 결정적 floorplan 및 room program 생성 규칙을 추가했다.
- 기본 Modern Office 스타일과 structural-glass 스타일을 분리했다.
- Infinigen 생성 wizard에 안전한 import/export 보조 기능과 content policy/호환성 계층을 추가했다.
- Structural glass 사용 여부와 graph 품질을 점검하는 audit 스크립트를 추가했다.
- scene metadata가 생성 규칙과 graph-build 옵션을 보존하도록 `navigation_dataset`의 scene sync·graph pipeline·sensor sweep을 확장했다.
- wizard/export layout, floorplan, import 호환성, content policy, graph audit에 대한 회귀 테스트를 추가했다.

이 변경으로 동일한 입력 설정에서 재현 가능한 office scene을 만들고, 유리 파티션이 포함된 장면을 OpticalNav graph 데이터와 함께 검증할 수 있는 기반을 마련했다.

### 2. OpticalNav render daemon 및 멀티 GPU 운영

관련 커밋: `f31a03f` (`feat(renderer): OpticalNav daemon 다중 GPU 렌더와 UI 상태를 강화한다`)

- daemon의 batch summary, GPU sharding, resume 동작을 보강했다.
- flash/spectral 처리와 spatial PBR 렌더 경로를 확장했다.
- `navigation_dataset` exporter가 새 render 상태와 modality를 전달하도록 갱신했다.
- OpticalNav Web UI의 dataset 화면, batch helper, render service, rail sensor/scene 탭에서 큐·배치·센서 상태를 표시하도록 조정했다.
- OptiX 7 render queue launcher와 kitchen multimodal/unified harness를 새 상태 계약에 맞췄다.
- batch summary, sharding, spectral flash, spatial PBR, versioned artifact에 대한 daemon 회귀 테스트를 추가·갱신했다.

결과적으로 장시간 viewpoint × heading 렌더에서 작업 분할과 재개 상태를 추적할 수 있고, RGB 외 modality를 UI와 export 단계에서 잃지 않도록 연결했다.

### 3. OpticalNav 산출물 정리 기준

관련 문서: [`out_cleanup_inventory_2026-08-18.md`](../docs/out_cleanup_inventory_2026-08-18.md)

- `out/`을 OpticalNav 핵심 데이터, Infinigen import/staging, 렌더·export 결과, 실험·cache·scratch로 분류했다.
- `out/opticalnav/opticalnav-v0.2/`의 `dataset.json`, `scenes`, `episodes`, `splits`, `exports`, `render_ledger.sqlite3`는 코드와 직접 연결된 핵심 보존 대상으로 정리했다.
- `authoring_map → import`, `scene → authoring_map`, `dataset.json → scene`, `export manifest → source`, `ledger → batch` 역참조를 삭제 전 검증 계약으로 정의했다.
- `.retired`, `.backup`, `.staging`, debug/smoke, 재생성 가능한 cache는 참조 및 실행 상태 확인 후 archive/delete 후보로 분류했다.
- OpticalNav scene의 OBJ/MTL/GLB를 단순 확장자 기준으로 삭제하지 않도록 했다. fallback 참조와 재현성 계약을 먼저 확인해야 한다.

이번 조사는 삭제를 수행하지 않은 읽기 전용 inventory다.

## 기간 중 연관 작업

`7ddb6bc`와 `2e39ad3`의 IR/Principled RGB-Active-NIR 파이프라인은 OpticalNav scene·import·camera pose·material pipeline을 재사용하는 인접 작업이다. 데이터셋의 주된 목적은 IR이므로 본 보고서의 핵심 기능 목록에서는 분리했지만, OpticalNav 장면 자산과 렌더 인프라의 품질·재사용성에 영향을 주는 기반 작업으로 기록한다.

## 현재 상태

### 커밋 완료

- Modern Office 생성 규칙 및 wizard
- graph/scene metadata 연동과 audit
- daemon batch/sharding/resume 및 modality 상태 강화
- Web UI/exporter/launcher/test 갱신
- `out/` OpticalNav 산출물 inventory 및 보존 기준

### 미커밋 작업 트리

현재 작업 트리에는 OpticalNav wizard/exporter, Web UI export 화면, daemon, compact bundle/custom JSON exporter, structural PBR 품질 검사 및 관련 테스트의 수정이 남아 있다. 이 변경들은 후속 검증·정리 후 별도 커밋 대상으로 취급하며, 본 보고서에서는 완료된 기능과 구분한다.

## 다음 단계

1. OpticalNav wizard/exporter와 daemon 관련 미커밋 변경을 테스트하고 의도별 커밋으로 분리한다.
2. Modern Office 샘플을 실제 생성해 floorplan seed, room program, structural-glass audit, graph 결과를 함께 확인한다.
3. 다중 GPU queue에서 shard 재개와 batch summary가 실제 job ledger 및 export manifest와 일치하는지 검증한다.
4. `out/` 정리는 먼저 역참조 목록과 active lock/process를 만든 뒤, archive 후보부터 이동식 보관 방식으로 처리한다.
5. OpticalNav export에 포함되는 이미지·graph·grid·episode·metadata의 버전 계약을 문서화한다.

## 근거 및 한계

- 저장소 커밋 이력에서 2026-08-11~18에 확인된 OpticalNav 직접 변경은 주로 2026-08-18의 `37cd36d`, `f31a03f`다.
- 작업공간에 남은 Codex 세션 원문은 현재 실행 환경에서 직접 열람할 수 없어, 채팅에서 확인된 `out/` 조사 맥락과 저장소 변경 이력을 기준으로 작성했다.
- 이번 작성에서는 전체 테스트 실행이나 렌더 재실행을 수행하지 않았다. 따라서 “기능 구현/변경 완료”와 “실제 GPU 렌더 검증 완료”를 구분한다.
