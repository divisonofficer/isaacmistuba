# isaac_extension

Isaac Sim에서 현재 stage 상태를 캡처하고, Mitsuba daemon으로 렌더 요청을 보내는 extension helper 모음입니다.

가장 중요한 기본 사용 흐름은 아래입니다.

1. `daemon = connect_daemon()`
2. `daemon.load_scene(...)`
3. 로봇/오브젝트 상태 정리
4. sensor 정의 또는 현재 viewport 사용
5. `daemon.connect_scene_session(...)`
6. `daemon.sync_scene_state(...)`
7. `daemon.render_current_view(...)`
8. `daemon.open_capture(...)`

즉 사용자 입장에서는:

`daemon 연결 -> scene 열기 -> 상태 맞추기 -> 센서 정하기 -> 현재 위치에서 렌더 -> 결과 열기`

권장 helper는 아래입니다.

- `connect_daemon()`
- `daemon.load_scene(...)`
- `daemon.connect_scene_session(...)`
- `daemon.sync_scene_state(...)`
- `daemon.render_current_view(...)`
- `daemon.open_capture(...)`

구성:

- `extension.py`
  - Omniverse extension entrypoint
- `ui_panel.py`
  - session setup, BSDF override, modality, one-click current-view render
- `stage_capture.py`
  - active viewport camera, state patch, sensor spec, session payload 생성
- `daemon_client.py`
  - session open/update/register/capture
  - legacy blocking `/isaac/render`
  - legacy async `/isaac/render/submit`
  - `/jobs/{job_id}` polling helper

전제:

- `mitsuba_scene_ref`는 이미 존재하는 base `scene.xml` 이어야 합니다.
- `shape_map_ref`는 base scene의 explicit prim↔shape mapping JSON 이어야 합니다.
- daemon은 WSL/Linux 쪽에서 실행 중이어야 합니다.
- `scene_id="moorelane"` 같은 one-line render는 daemon catalog에 scene이 등록되어 있고, 실제 `shape_map_ref` 파일이 디스크에 존재할 때만 됩니다.

권장 Windows 시작 경로:

- 가능하면 Script Editor 수동 import보다 `true extension` 실행기를 먼저 씁니다.
- 바로 실행 가능한 wrapper: [launch_isaac_with_robomituba.bat](/jarvis/project/robomituba/apps/isaac_extension/launch_isaac_with_robomituba.bat)
- 예시 파일: [isaac-sim-robomituba.example.bat](/jarvis/project/robomituba/apps/isaac_extension/isaac-sim-robomituba.example.bat)
- 이 실행기는:
  - `apps`
  - `robomituba_bridge/src`
  - `mitsuba_converter/src`
  를 Python path에 추가하고, shared repo의 `isaac_extension` 폴더를 로컬 `extsUser\isaac_extension` 으로 동기화한 뒤 `isaac_extension` 패널을 자동 활성화합니다.
- 기본값으로 `C:\isaac_sim_win\isaac-sim.bat` 를 찾고, 필요하면 `ISAAC_SIM_ROOT` 또는 `ISAAC_SIM_BAT` 환경 변수로 덮어쓸 수 있습니다.
- 텍스처 로딩 안정성을 위해 가능하면 UNC 대신 mapped drive 또는 로컬 mirror를 씁니다.
- 가장 추천하는 설정은 예를 들어 아래처럼 Windows repo root를 먼저 잡는 것입니다.

```bat
set ROBOMITUBA_WINDOWS_REPO_ROOT=J:\project\robomituba
```

- 그러면 launcher와 Python helper가 모두 같은 Windows-side repo root를 우선 사용합니다.

하이브리드 UX:

- Isaac에 익숙한 사용자는 Isaac panel과 Script Editor helper로 직접 제어합니다.
- Isaac에 익숙하지 않은 사용자는 daemon control plane의 scene/remote action UI로 `Load Scene`, `Connect`, `Sync`, `Render Current View`를 보낼 수 있습니다.
- live transform, viewport, sensor placement의 source of truth는 계속 Isaac입니다.

권장 흐름:

1. `apps/isaac_standalone/export_snapshot.py --mitsuba-scene ...` 로 `shape_map.json` 생성
2. control plane scene catalog에 scene profile을 등록하거나, UI dropdown에서 기존 profile 선택
3. `Load Scene`
4. scene 상태가 바뀌면 `Connect Session` 후 `Sync Session`
5. 현재 viewport 기준으로 `Render Current View`
6. `Open Latest Capture`
7. 또는 control plane의 remote action 버튼으로 같은 load/connect/sync/render 흐름을 Isaac에 요청

더 자세한 설명:

- [docs/isaac_sim_guide.en.md](/jarvis/project/robomituba/docs/isaac_sim_guide.en.md)
- [docs/isaac_sim_guide.ko.md](/jarvis/project/robomituba/docs/isaac_sim_guide.ko.md)

Script Editor에서 가장 안전한 시작 import:

```python
import sys
import os
sys.path.insert(0, os.path.join(os.environ.get("ROBOMITUBA_WINDOWS_REPO_ROOT", r"J:\project\robomituba"), "apps"))
from isaac_extension import connect_daemon
```

또는 더 짧게:

```python
import sys
import os
sys.path.insert(0, os.path.join(os.environ.get("ROBOMITUBA_WINDOWS_REPO_ROOT", r"J:\project\robomituba"), "apps"))
from robomituba_isaac import connect_daemon
```
