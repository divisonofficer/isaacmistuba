# Isaac Sim 가이드 (KR)

이 문서는 아래 흐름을 실제로 따라가기 위한 친절한 작업 가이드입니다.

1. Isaac Sim 실행
2. 저장된 scene을 불러오거나 새 USD scene 열기
3. Isaac 안에서 재질/오브젝트 상태 확인
4. Robomituba daemon과 연결
5. `Render Current View` 한 번으로 Mitsuba 렌더 실행

지금은 하이브리드 흐름으로 생각하면 가장 자연스럽습니다.

- Isaac에 익숙하면 Isaac 안에서 바로 제어
- Isaac이 낯설면 daemon control plane에서 scene 등록, render readiness 확인, 원격 액션 버튼 사용
- live transform, viewport, sensor placement의 source of truth는 계속 Isaac

핵심 개념은 간단합니다.

- Isaac Sim은 현재 scene 상태의 source of truth
- Robomituba/Mitsuba는 고품질 RGB, depth, polarization, NIR 관측을 만드는 sidecar renderer

## 한 줄 Helper 버전

Isaac 안에서 가장 짧게 쓰고 싶다면, 의도된 helper 층은 아래입니다.

- `connect_daemon()`
- `daemon.load_scene(...)`
- `daemon.connect_scene_session(...)`
- `daemon.sync_scene_state(...)`
- `daemon.render_current_view(...)`
- `daemon.open_capture(...)`

## 퀵 가이드

가장 짧은 실사용 흐름은 이제 daemon 객체 중심으로 보면 됩니다.

1. Isaac Sim 실행
2. `daemon = connect_daemon()` 으로 client 객체 하나 만들기
3. `daemon.load_scene(scene_id="...")` 또는 새 USD 경로로 scene 열기
4. 로봇을 배치하고, 로봇이나 오브젝트를 원하는 상태로 움직이기
5. 센서를 하나 정의하거나, 우선 현재 viewport를 임시 sensor로 사용하기
6. `daemon.connect_scene_session(...)`
7. `daemon.sync_scene_state(...)`
8. `daemon.render_current_view(...)`
9. `daemon.open_capture(...)`

즉 핵심 operator loop는:

`daemon 연결 -> scene 불러오기 -> 로봇/오브젝트 상태 정리 -> 센서 정의 -> 렌더 -> 결과 열기`

## 1. 먼저 Control Plane 실행

WSL/Linux에서:

```bash
bash /jarvis/project/robomituba/apps/run_control_plane_dev.sh
```

브라우저에서:

```text
http://127.0.0.1:8765/
```

여기서 `Isaac Guide` 페이지를 열면 아래 절차를 웹 UI 안에서도 다시 볼 수 있습니다.

## 1.5. 권장 Windows Isaac 실행기

권장되는 Windows 시작 경로는 Script Editor 스니펫만 쓰는 방식보다, true extension launcher로 Isaac을 실행하는 것입니다.

repo 안의 예시 파일:

- `/jarvis/project/robomituba/apps/isaac_extension/isaac-sim-robomituba.example.bat`

권장 Windows-side 내용:

```bat
@echo off
setlocal

set "SCRIPT_DIR=%~dp0"
set "ROBOMITUBA_ROOT=\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba"
set "ROBOMITUBA_APPS=%ROBOMITUBA_ROOT%\apps"
set "ROBOMITUBA_BRIDGE_SRC=%ROBOMITUBA_ROOT%\modules\robomituba_bridge\src"
set "ROBOMITUBA_CONVERTER_SRC=%ROBOMITUBA_ROOT%\modules\mitsuba_converter\src"

set "PYTHONPATH=%ROBOMITUBA_APPS%;%ROBOMITUBA_BRIDGE_SRC%;%ROBOMITUBA_CONVERTER_SRC%;%PYTHONPATH%"

call "%SCRIPT_DIR%isaac-sim.bat" ^
  --ext-folder "%ROBOMITUBA_APPS%" ^
  --enable isaac_extension ^
  --/app/python/extraPaths/0="%ROBOMITUBA_APPS%" ^
  --/app/python/extraPaths/1="%ROBOMITUBA_BRIDGE_SRC%" ^
  --/app/python/extraPaths/2="%ROBOMITUBA_CONVERTER_SRC%" ^
  %*
```

이 실행기는:

- `isaac_extension`, `robomituba_bridge`, `mitsuba_converter` import를 가능하게 하고
- shared repo의 `isaac_extension` 폴더를 로컬 `extsUser\isaac_extension` 으로 동기화하고
- 로컬 extension search path를 추가하고
- `isaac_extension` 패널을 자동으로 활성화합니다

중요한 점:

- UNC 경로도 쓸 수 있지만, 텍스처 스트리밍은 mapped drive나 로컬 SSD mirror 쪽이 더 안정적일 수 있습니다

중요한 경로 규칙:

- WSL/Linux에서 실행하는 명령은 `/jarvis/project/robomituba/...` 경로를 사용합니다
- Windows의 Isaac Script Editor에 붙여넣는 코드는 `\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\...` 경로를 사용해야 합니다

## 2. Isaac Sim에서 Scene 열기

권장하는 v2 사고방식은 이렇습니다.

- daemon이 재사용 가능한 scene catalog를 들고 있음
- Isaac은 daemon에게 어떤 scene profile이 있는지 물어봄
- Isaac은 helper 한 줄로 scene을 엶

실전에서는 먼저 이렇게 시작하면 됩니다.

```python
import sys
sys.path.insert(0, r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\apps")
from isaac_extension import connect_daemon

daemon = connect_daemon()
print([scene["scene_id"] for scene in daemon.list_scenes()])
```

보통 두 가지 시작 방법이 있습니다.

### MooreLane 빠른 시작

기본 MooreLane scene을 바로 열고 싶다면 아래 경로를 그대로 쓰면 됩니다.

```python
import sys
sys.path.insert(0, r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\apps")
from isaac_extension import connect_daemon

daemon = connect_daemon()

daemon.load_scene(
    usd_path=r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\assets\moorelane\Intel_mooreLane_v1_2_0\Intel_mooreLane\USD\MooreLane_ASWF_0623.usda"
)
```

이건 `open only` 경로입니다.
즉 daemon scene catalog 등록 없이도 우선 Isaac에서 USD scene을 여는 데는 충분합니다.

### 옵션 A. 저장된 scene profile 불러오기

control plane이 이미 다음 정보를 알고 있는 scene이라면 이 경로가 가장 편합니다.

- `usd_stage_path`
- `mitsuba_scene_ref`
- `shape_map_ref`

이 경우 Isaac에서는 그냥:

```python
daemon.load_scene(scene_id="moorelane")
```

처럼 한 줄로 엽니다.

이 방식이 좋은 이유는, 같은 `scene_id`를 그대로 세션 연결과 렌더까지 이어서 쓸 수 있기 때문입니다.

일반적인 GUI 순서:

1. Isaac Sim 실행
2. `File -> Open`
3. 저장된 USD scene 선택
4. stage 로딩 완료까지 기다리기
5. viewport를 움직여서 예상한 오브젝트/카메라가 잘 보이는지 확인

이 방법이 좋은 경우:

- 이미 작업 중인 scene checkpoint가 있음
- 같은 장면 구성을 반복해서 써야 함
- 재현 가능한 카메라 위치를 유지하고 싶음

### 옵션 B. 새 USD scene 경로 열기

처음 보는 환경이거나, 아직 작업용 scene으로 저장해두지 않은 USD 환경을 바로 열고 싶을 때 쓰는 방법입니다.

이 경우엔:

```python
daemon.load_scene(usd_path=r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\assets\...\scene.usda")
```

처럼 직접 USD 경로를 넘기면 됩니다.

일반적인 순서:

1. Isaac Sim 실행
2. 필요하면 새 빈 stage 생성
3. `File -> Open`으로 source USD 환경 열기
4. 계속 수정할 계획이면 내 작업 경로로 다시 저장
5. viewport를 움직이며 scene hierarchy와 배치를 확인

이 방법이 좋은 경우:

- 새로운 environment를 처음 탐색 중임
- 카메라 위치를 새로 잡고 싶음
- 어떤 scene 버전을 쓸지 아직 정리 중임

## 2.5. 로봇 배치와 scene 상태 정리

scene을 열고 난 뒤의 일반적인 Isaac 작업 흐름은 보통 이렇습니다.

1. 로봇을 scene 안에 배치
2. base, link, joint를 원하는 상태로 이동
3. 필요하면 props나 동적 오브젝트 위치도 조정
4. sensor 또는 viewport에서 지금 구도가 맞는지 확인

중요한 점은, live state 편집의 주체는 여전히 Isaac이라는 것입니다.
Robomituba는 이 편집 루프를 대체하지 않고, 현재 상태를 읽어서 렌더합니다.

## 2.6. 센서 정의

v1에서는 센서를 두 수준으로 생각하면 편합니다.

- 명시적으로 등록해 두는 sensor
- 가장 빠른 테스트용인 현재 viewport

처음엔 이렇게 시작하는 걸 추천합니다.

1. Isaac viewport를 원하는 구도로 이동
2. 현재 viewport를 첫 번째 sensor처럼 사용
3. 흐름이 안정되면 이름 있는 sensor를 등록해서 재사용

이렇게 하면 첫 번째 렌더 요청이 훨씬 단순해집니다.

## 3. Isaac Sim에서 재질 수정은 어떻게 생각하면 되나

v1에서는 재질 흐름을 일부러 단순하게 가져갑니다.

- Isaac 재질은 authoring과 시각적 확인용
- Mitsuba 렌더는 explicit BSDF preset override를 사용
- extension UI에서 prim별로 Mitsuba용 preset을 선택해 daemon에 전달

추천 작업 흐름:

1. Isaac에서 scene 열기
2. 바꾸고 싶은 prim 찾기
3. Isaac의 기본 property/material UI로 현재 상태 확인
4. Robomituba extension panel에서 필요한 Mitsuba preset override 선택

현재 preset 예시:

- `diffuse`
- `roughplastic`
- `roughconductor`
- `pplastic`
- `glossy_black_lacquer`
- `mirror_black_enamel`

중요한 점:

- v1은 임의의 USD material을 실시간으로 Mitsuba material로 완전 번역하지 않습니다
- 대신 base Mitsuba XML에 preset override patch를 적용하는 방식입니다

즉 실제 의미는 이렇습니다.

- Isaac에서는 “어느 오브젝트를 다르게 다룰지”를 결정
- Mitsuba에서는 “그 오브젝트를 어떤 BSDF로 렌더할지”를 preset으로 선택

## 4. Base Mitsuba Scene과 Shape Map 준비

원클릭 capture가 동작하려면 daemon이 아래 두 파일을 알아야 합니다.

- base Mitsuba `scene.xml`
- explicit `shape_map.json`

`shape_map.json`은 다음 둘을 연결하는 핵심 파일입니다.

- USD의 `prim_path`
- Mitsuba의 `shape_id[]`

예시 export:

```bash
python3 /jarvis/project/robomituba/apps/isaac_standalone/export_snapshot.py \
  --usd /path/to/stage.usda \
  --snapshot-dir /jarvis/project/robomituba/out/manual_snapshot \
  --mitsuba-scene /jarvis/project/robomituba/out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.xml
```

이렇게 하면 snapshot 디렉토리에 보통 아래가 같이 생깁니다.

- `scene_snapshot.json`
- `shape_map.json`

### MooreLane 렌더 등록 예시

이후 아래처럼:

```python
daemon.load_scene(scene_id="moorelane")
daemon.connect_scene_session("moorelane")
daemon.render_current_view("moorelane")
```

형태로 바로 쓰고 싶다면 scene을 한 번 등록해두면 됩니다.

```python
import sys
sys.path.insert(0, r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\apps")
from isaac_extension import connect_daemon

daemon = connect_daemon()

daemon.register_scene(
    scene_id="moorelane",
    usd_stage_path=r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\assets\moorelane\Intel_mooreLane_v1_2_0\Intel_mooreLane\USD\MooreLane_ASWF_0623.usda",
    mitsuba_scene_ref="out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.xml",
    shape_map_ref="out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.shape_map.json",
)
```

중요한 점:

- scene 열기만 하는 것은 등록 없이도 가능합니다
- full render session connect를 하려면 `mitsuba_scene_ref` 와 `shape_map_ref` 가 둘 다 필요합니다
- `shape_map_ref` 가 아직 없다면, 위 export 절차로 먼저 생성해야 합니다

## 5. 권장 객체 기반 워크플로우

Isaac이 아래 경로를 import 가능해야 합니다.

```text
\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\apps
```

그 다음 권장 흐름은 이렇습니다.

```python
import omni.usd
import sys
sys.path.insert(0, r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\apps")
from isaac_extension import connect_daemon

daemon = connect_daemon()
daemon.load_scene(scene_id="moorelane")

stage = omni.usd.get_context().get_stage()

# 로봇 배치, 조인트 이동, prop 정리, 구도 설정
daemon.connect_scene_session("moorelane")
daemon.sync_scene_state(stage, "moorelane")
result = daemon.render_current_view("moorelane", submit_mode="blocking")
print(result["manifest_path"])
daemon.open_capture(scene_id="moorelane")
```

각 호출의 의미는 이렇게 보면 됩니다.

1. `connect_daemon()`
   - 재사용 가능한 client 객체 하나를 만듭니다
   - URL은 기본값, `ROBOMITUBA_DAEMON_URL`, 또는 명시 인자에서 올 수 있습니다
2. `daemon.load_scene(...)`
   - Isaac에서 USD stage를 엽니다
   - 아직 렌더는 하지 않습니다
3. `daemon.connect_scene_session(...)`
   - 선택한 scene profile에 대해 active Mitsuba session을 엽니다
4. `daemon.sync_scene_state(...)`
   - 현재 Isaac transform과 optional BSDF override를 daemon으로 보냅니다
5. `daemon.render_current_view(...)`
   - 현재 viewport를 작업용 sensor로 간주하고 Mitsuba 렌더를 요청합니다
6. `daemon.open_capture(...)`
   - 최신 preview artifact를 바로 열어 빠르게 확인합니다

## 6. Extension Panel 워크플로우

Script Editor 대신 UI를 선호하면, extension panel도 같은 객체 기반 흐름을 그대로 따라갑니다.

사용 순서는:

1. daemon catalog에서 scene 선택
2. `Load Scene`
3. Isaac에서 로봇 / scene 상태 정리
4. `Connect Session`
5. `Sync Session`
6. `Render Current View`
7. `Open Latest Capture`

panel 안에는 manual refs 입력도 fallback으로 남아 있지만, 기본 경로는:

`scene dropdown -> load -> connect -> sync -> render`

입니다.

## 7. 원클릭 Capture 흐름

새 기본 경로는 session 기반입니다.

내부적으로는:

1. `daemon.connect_scene_session(...)`
   - daemon 안에 active Isaac scene session 하나를 엽니다
2. `daemon.sync_scene_state(...)`
   - 현재 object transform 반영
   - 현재 material override 반영
   - 현재 viewport를 sensor로 등록
3. `daemon.render_current_view(...)`
   - active session 기준으로 capture 요청
   - observation bundle 반환

즉 실제 사용자 감각은:

`처음 한 번 연결 -> scene 바뀌면 sync -> 렌더 버튼 한 번`

## 7. 결과는 어디에 저장되나

완성된 렌더 결과는 보통 여기로 저장됩니다.

```text
out/bridge_jobs/<job_id>/observations/<frame_id>/
```

대표 산출물:

- `rgb`
- `depth`
- `active_nir_intensity`
- `s1`
- `s2`
- `dop`
- `aolp`
- `manifest.json`

## 8. 문제 해결

### extension이 daemon과 통신하지 못함

확인할 것:

- daemon이 WSL에서 실행 중인지
- `http://127.0.0.1:8765/health` 가 응답하는지
- Windows의 Isaac에서 해당 URL에 접근 가능한지

### Render Current View가 바로 실패함

확인할 것:

- `shape_map_ref` 파일이 실제로 존재하는지
- `mitsuba_scene_ref` 파일이 존재하는지
- 먼저 `daemon.connect_scene_session(...)` 또는 `Connect Session`을 수행했는지

### Mitsuba 출력에서 재질이 안 바뀜

확인할 것:

- extension panel에서 올바른 prim을 선택했는지
- 해당 prim이 `shape_map.json`에 존재하는지
- override preset이 `none`이 아닌지

### GPU 렌더가 안 시작됨

WSL에서 확인:

```bash
export LD_LIBRARY_PATH=/usr/lib/wsl/lib:$LD_LIBRARY_PATH
```

그리고 daemon 실행 전에 Mitsuba/OptiX 런타임이 정상인지 같이 확인하는 것이 좋습니다.

## 9. 처음 해볼 추천 데모

처음 시작할 때는 아래 순서가 가장 안정적입니다.

1. Isaac에서 MooreLane scene 열기
2. control plane 실행
3. base XML + shape map으로 scene 연결
4. session sync
5. Isaac viewport 이동
6. `Render Current View` 클릭
7. control plane에서 manifest와 preview 이미지 확인
Script Editor에서 가장 짧게 쓰고 싶다면 아래처럼 써도 됩니다.

```python
import sys
sys.path.insert(0, r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\apps")
from robomituba_isaac import connect_daemon
```
