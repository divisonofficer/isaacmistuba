# robomituba

Isaac Sim과 Mitsuba를 연결해서, 같은 scene/time/state에 대해 연구용 광학 관측을 렌더하는 실험 저장소입니다.

현재 이 repo의 중심 목표는 다음 두 가지입니다.

- Isaac Sim에서 로봇/카메라/scene state를 관리한다.
- Mitsuba에서 같은 상태에 대한 `RGB / depth / polarization / NIR` 관측을 sidecar 렌더링한다.

즉, Isaac의 viewport를 대체하는 프로젝트가 아니라, **Isaac이 상태의 source of truth**, **Mitsuba가 고품질 optical renderer**가 되는 bridge를 만드는 작업입니다.

## Current Focus

지금 이 repo에서 가장 많이 다루는 경로는 아래입니다.

- MooreLane 계열 USD scene을 Isaac에서 연다.
- 현재 stage나 특정 카메라 상태를 snapshot/export 한다.
- 이미 준비된 Mitsuba base `scene.xml`에 transform/material patch를 적용한다.
- daemon이 multimodal render를 수행하고 observation bundle을 저장한다.

최근 기준으로는 아래 기능이 연결되어 있습니다.

- warm Mitsuba render daemon
- multimodal render API
- observation bundle manifest
- Isaac current view capture helper
- Isaac extension용 blocking / async render submit path
- Isaac session 기반 one-click current-view capture path
- explicit `prim_path -> shape_id[]` shape mapping 경로

## Repo Layout

- [project.md](/jarvis/project/robomituba/project.md)
  - 에이전트/개발용 작업 브리프
- [apps](/jarvis/project/robomituba/apps)
  - 실행 스크립트와 Isaac 관련 entrypoint
- [modules](/jarvis/project/robomituba/modules)
  - `robomituba_bridge`, `mitsuba_converter` 등 핵심 Python 패키지
- [assets](/jarvis/project/robomituba/assets)
  - 원본 scene asset
- [out](/jarvis/project/robomituba/out)
  - 렌더 결과, bridge job, observation bundle, 실험 산출물
- [tests](/jarvis/project/robomituba/tests)
  - 계약 테스트와 smoke 테스트

## Important Subsystems

### 1. Bridge Contract

위치:
- [robomituba_bridge](/jarvis/project/robomituba/modules/robomituba_bridge/src/robomituba_bridge)

역할:
- scene/job/request/manifest 타입 정의
- render request / observation bundle 직렬화
- IsaacStateSnapshot, SceneOverrideSpec, shape mapping payload 관리

핵심 파일:
- [types.py](/jarvis/project/robomituba/modules/robomituba_bridge/src/robomituba_bridge/types.py)
- [io.py](/jarvis/project/robomituba/modules/robomituba_bridge/src/robomituba_bridge/io.py)
- [shape_mapping.py](/jarvis/project/robomituba/modules/robomituba_bridge/src/robomituba_bridge/shape_mapping.py)

### 2. Mitsuba Converter / Renderer

위치:
- [mitsuba_converter](/jarvis/project/robomituba/modules/mitsuba_converter/src/mitsuba_converter)

역할:
- Mitsuba scene staging
- modality별 렌더
- observation bundle 생성
- render daemon / control plane

핵심 파일:
- [multimodal.py](/jarvis/project/robomituba/modules/mitsuba_converter/src/mitsuba_converter/multimodal.py)
- [observation_bridge.py](/jarvis/project/robomituba/modules/mitsuba_converter/src/mitsuba_converter/observation_bridge.py)
- [render_daemon.py](/jarvis/project/robomituba/modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py)

### 3. Isaac Integration

위치:
- [apps/isaac_standalone](/jarvis/project/robomituba/apps/isaac_standalone)
- [apps/isaac_extension](/jarvis/project/robomituba/apps/isaac_extension)

역할:
- USD stage snapshot export
- shape map 생성
- Isaac current viewport capture
- extension UI에서 BSDF override / modality / submit mode 선택
- daemon에 `/isaac/render`, `/isaac/render/submit` 요청

참고:
- [apps/isaac_standalone/README.md](/jarvis/project/robomituba/apps/isaac_standalone/README.md)
- [apps/isaac_extension/README.md](/jarvis/project/robomituba/apps/isaac_extension/README.md)
- [docs/isaac_sim_guide.en.md](/jarvis/project/robomituba/docs/isaac_sim_guide.en.md)
- [docs/isaac_sim_guide.ko.md](/jarvis/project/robomituba/docs/isaac_sim_guide.ko.md)

## Main Workflows

### Control Plane / Daemon 실행

```bash
bash /jarvis/project/robomituba/apps/run_control_plane_dev.sh
```

기본 URL:

```text
http://127.0.0.1:8765/
```

여기서 볼 수 있는 것:

- daemon health
- render queue / jobs
- scene explorer
- floorplan inspector
- result gallery
- Isaac 연결 가이드

### 일반 RenderRequest 기반 queue submit

Isaac current viewport 기준 request를 만들고 daemon queue로 넣는 helper는:

- [isaac_capture_current_view_request.py](/jarvis/project/robomituba/apps/isaac_capture_current_view_request.py)

### Isaac XML patch render

v1 경로는 다음 전제를 둡니다.

- base Mitsuba `scene.xml`은 미리 존재해야 함
- explicit `shape_map.json`도 미리 존재해야 함
- Isaac은 live USD 전체를 Mitsuba로 재수출하지 않고, 현재 state를 patch로 전달함

#### shape map 생성

예:

```bash
python3 /jarvis/project/robomituba/apps/isaac_standalone/export_snapshot.py \
  --usd /path/to/stage.usda \
  --snapshot-dir /jarvis/project/robomituba/out/manual_snapshot \
  --mitsuba-scene /jarvis/project/robomituba/out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.xml
```

이렇게 하면 snapshot 디렉토리에 `shape_map.json`이 함께 생성됩니다.

#### Isaac Extension에서 submit

extension은 다음 정보를 사용합니다.

- `mitsuba_scene_ref`
- `scene_snapshot_ref` optional
- `shape_map_ref`
- 현재 viewport camera
- live prim transform
- UI-selected Mitsuba BSDF override
- modalities
- submit mode (`blocking` / `async`)

### Isaac One-click Session Flow

현재 권장 경로는 session 기반입니다.

사용자 입장에서의 가장 짧은 흐름은:

1. scene 불러오기
2. 로봇/오브젝트 상태 정리
3. 센서 정의 또는 현재 viewport 사용
4. `Connect Scene`
5. `Sync Session`
6. `Render Current View`

더 자세한 step-by-step 문서:

- English: [docs/isaac_sim_guide.en.md](/jarvis/project/robomituba/docs/isaac_sim_guide.en.md)
- 한국어: [docs/isaac_sim_guide.ko.md](/jarvis/project/robomituba/docs/isaac_sim_guide.ko.md)

## Testing

대표 테스트:

```bash
cd /jarvis/project/robomituba
python3 -m unittest tests.contract.test_multimodal_api
python3 -m unittest tests.contract.test_render_daemon
python3 -m unittest tests.contract.test_observation_bridge
```

이번 repo는 계약 테스트 비중이 높습니다.  
특히 아래를 자주 확인하면 좋습니다.

- multimodal staging / derived modality
- daemon API / queue
- observation bundle manifest
- Isaac snapshot / XML patch contract

## Current Assumptions

- source of truth는 Isaac scene state 쪽이다.
- Mitsuba는 sidecar renderer다.
- v1 patch 경로는 `scene_base.xml + explicit shape mapping + state patch`이다.
- material edit는 USD material full translation이 아니라, 우선은 **Mitsuba-side preset override** 중심이다.
- polarization / NIR은 supported path이지만, 여전히 좁은 representative scene 기준으로 다듬는 단계다.

## Read First

처음 들어오면 이 순서로 보는 걸 추천합니다.

1. [project.md](/jarvis/project/robomituba/project.md)
2. [modules/README.md](/jarvis/project/robomituba/modules/README.md)
3. [apps/isaac_standalone/README.md](/jarvis/project/robomituba/apps/isaac_standalone/README.md)
4. [apps/isaac_extension/README.md](/jarvis/project/robomituba/apps/isaac_extension/README.md)
5. [render_daemon.py](/jarvis/project/robomituba/modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py)
6. [multimodal.py](/jarvis/project/robomituba/modules/mitsuba_converter/src/mitsuba_converter/multimodal.py)

## Notes

- `/jarvis/project/robomituba` 밖의 앱이나 서비스는 이 repo의 구현 범위로 간주하지 않습니다.
- control plane, daemon, Isaac helper, renderer는 모두 이 repo 내부에서 닫히는 방향으로 유지합니다.
