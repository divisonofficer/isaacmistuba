# Isaac Sim Guide (EN)

This guide is for the practical workflow:

1. Open Isaac Sim
2. Load a saved scene or open a new USD scene
3. Inspect or edit materials in Isaac
4. Connect the scene to the Robomituba daemon
5. Click `Render Current View`

This is now a hybrid workflow:

- use Isaac directly if you are comfortable there
- use the daemon control plane if you want scene registration, render readiness checks, and remote action buttons
- Isaac remains the live scene authority for transforms, viewport state, and sensor placement

The goal is simple:

- Isaac Sim is the source of truth for live scene state
- Robomituba/Mitsuba renders high-quality RGB, depth, polarization, and NIR sidecar observations

## One-line Helper Version

If you want the shortest Python workflow inside Isaac, the intended helper layer is:

- `connect_daemon()`
- `daemon.load_scene(...)`
- `daemon.connect_scene_session(...)`
- `daemon.sync_scene_state(...)`
- `daemon.render_current_view(...)`
- `daemon.open_capture(...)`

## Quick Guide

If you want the shortest practical flow, use the daemon object style:

1. Open Isaac Sim
2. Create one client with `daemon = connect_daemon()`
3. Load a saved scene with `daemon.load_scene(scene_id="...")`, or open a new USD path once
4. Place the robot and move the robot or scene objects to the state you want
5. Define one sensor, or use the current viewport as a temporary sensor
6. Call `daemon.connect_scene_session(...)`
7. Call `daemon.sync_scene_state(...)`
8. Call `daemon.render_current_view(...)`
9. Call `daemon.open_capture(...)`

That is the core operator loop:

`connect daemon -> load scene -> arrange robot/state -> define sensor -> render -> open result`

## 1. Start the Control Plane

In WSL/Linux:

```bash
bash /jarvis/project/robomituba/apps/run_control_plane_dev.sh
```

Open:

```text
http://127.0.0.1:8765/
```

The `Isaac Guide` page in the control plane mirrors the core steps below.

## 1.5. Preferred Windows Isaac Launcher

The preferred Windows startup path is the true extension launcher, not just Script Editor snippets.

Example file in this repo:

- `/jarvis/project/robomituba/apps/isaac_extension/isaac-sim-robomituba.example.bat`

Recommended Windows-side contents:

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

This launcher:

- makes `isaac_extension`, `robomituba_bridge`, and `mitsuba_converter` importable
- syncs the shared `isaac_extension` folder into local `extsUser\isaac_extension`
- adds the local extension search path
- auto-enables `isaac_extension`

Important note:

- UNC paths work for many cases, but texture streaming is often more stable from a mapped drive or local SSD mirror

Important path rule:

- commands run in WSL/Linux use `/jarvis/project/robomituba/...`
- code pasted into Isaac Script Editor on Windows should use `\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\...`

## 2. Open a Scene in Isaac Sim

The recommended v2 mental model is:

- the daemon keeps a reusable scene catalog
- Isaac asks the daemon which scene profiles exist
- Isaac opens a scene with one helper call

In practice, start with:

```python
import sys
sys.path.insert(0, r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\apps")
from isaac_extension import connect_daemon

daemon = connect_daemon()
print([scene["scene_id"] for scene in daemon.list_scenes()])
```

You usually have two entry paths.

### MooreLane quick start

If you want to open the default MooreLane scene immediately, use this exact path:

```python
import sys
sys.path.insert(0, r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\apps")
from isaac_extension import connect_daemon

daemon = connect_daemon()

daemon.load_scene(
    usd_path=r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\assets\moorelane\Intel_mooreLane_v1_2_0\Intel_mooreLane\USD\MooreLane_ASWF_0623.usda"
)
```

This is an `open only` path.
You do not need daemon scene-catalog registration yet.
It is the fastest way to get the USD scene into Isaac.

### Option A. Open a previously saved scene profile

Use this when the control plane already knows a named scene with:

- `usd_stage_path`
- `mitsuba_scene_ref`
- `shape_map_ref`

Then Isaac only needs:

```python
daemon.load_scene(scene_id="moorelane")
```

This is the preferred path because the same `scene_id` can later be used for session connect and render.

Typical GUI flow:

1. Launch Isaac Sim
2. `File -> Open`
3. Select the saved USD scene
4. Wait for the stage to finish loading
5. Move the viewport and confirm that the expected objects/cameras are visible

Use this path when:

- the scene layout is already authored
- you want reproducible camera placement
- you want to keep working from an existing checkpoint

### Option B. Open a new USD scene path

Use this when you want to start from a source USD environment that has not yet been prepared as a saved Isaac scene.

Then Isaac only needs:

```python
daemon.load_scene(usd_path=r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\assets\...\scene.usda")
```

Typical flow:

1. Launch Isaac Sim
2. Create a new empty stage if needed
3. `File -> Open` and choose the source USD environment
4. Save it under your own working path if you plan to keep edits
5. Reposition the viewport and inspect the scene hierarchy

Use this path when:

- you are exploring a new environment
- you want to create a new camera setup
- you are still deciding which scene version to render

## 2.5. Place the Robot and Move the Scene

After the scene is open, the usual authoring loop in Isaac is:

1. place the robot in the scene
2. move the base, links, or joints into the state you want
3. move props or dynamic objects if needed
4. check the current view from the sensor or viewport

The important point is that Isaac stays responsible for the live state.
Robomituba does not replace that editing loop. It reads the current state and renders from it.

## 2.6. Define a Sensor

For v1, think in two levels:

- permanent sensors you may register explicitly
- the current viewport, which is the fastest way to request a test render

Recommended starting point:

1. move the Isaac viewport to the shot you want
2. treat the current viewport as the first sensor
3. once the workflow is stable, register named sensors and reuse them

This keeps the first render request very simple.

## 3. Material Editing in Isaac Sim

For v1, material editing is intentionally simple:

- Isaac materials are for authoring and visual inspection
- Mitsuba rendering uses explicit BSDF preset overrides
- the extension UI lets you assign Mitsuba-side presets to selected prims

Recommended workflow:

1. Open the scene in Isaac
2. Identify the prim you want to modify
3. Use Isaac’s normal material/property UI to inspect the object
4. In the Robomituba extension panel, assign a Mitsuba preset override if needed

Current preset-style overrides include examples such as:

- `diffuse`
- `roughplastic`
- `roughconductor`
- `pplastic`
- `glossy_black_lacquer`
- `mirror_black_enamel`

Important note:

- v1 does **not** translate arbitrary USD materials into Mitsuba materials at capture time
- instead, the daemon patches the base Mitsuba XML with explicit preset overrides

That means:

- Isaac is still where you decide *which object* should behave differently
- the exact Mitsuba BSDF is chosen through the extension / patch pipeline

## 4. Prepare the Base Mitsuba Scene and Shape Map

Before one-click capture works, the daemon needs:

- a base Mitsuba scene XML
- an explicit `shape_map.json`

The shape map is the bridge between:

- USD `prim_path`
- Mitsuba `shape_id[]`

Example export:

```bash
python3 /jarvis/project/robomituba/apps/isaac_standalone/export_snapshot.py \
  --usd /path/to/stage.usda \
  --snapshot-dir /jarvis/project/robomituba/out/manual_snapshot \
  --mitsuba-scene /jarvis/project/robomituba/out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.xml
```

This writes:

- `scene_snapshot.json`
- `shape_map.json`

### MooreLane render registration example

If you want later calls such as:

```python
daemon.load_scene(scene_id="moorelane")
daemon.connect_scene_session("moorelane")
daemon.render_current_view("moorelane")
```

to work directly, register the scene once:

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

Important:

- scene open only is possible without registration
- full render-session connect requires both `mitsuba_scene_ref` and `shape_map_ref`
- if `shape_map_ref` does not exist yet, generate it first with the export flow above

## 5. Preferred Object-style Workflow

Make sure Isaac can import from:

```text
\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\apps
```

Then the intended workflow is:

```python
import omni.usd
import sys
sys.path.insert(0, r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\apps")
from isaac_extension import connect_daemon

daemon = connect_daemon()
daemon.load_scene(scene_id="moorelane")

stage = omni.usd.get_context().get_stage()

# place robot, move joints, adjust props, choose your view
daemon.connect_scene_session("moorelane")
daemon.sync_scene_state(stage, "moorelane")
result = daemon.render_current_view("moorelane", submit_mode="blocking")
print(result["manifest_path"])
daemon.open_capture(scene_id="moorelane")
```

What each call means:

1. `connect_daemon()`
   - creates one reusable client object
   - URL can come from the default, from `ROBOMITUBA_DAEMON_URL`, or from an explicit argument
2. `daemon.load_scene(...)`
   - opens the USD stage in Isaac
   - this does not render yet
3. `daemon.connect_scene_session(...)`
   - opens one active Mitsuba session for the selected scene profile
4. `daemon.sync_scene_state(...)`
   - pushes the current Isaac transforms and optional BSDF overrides
5. `daemon.render_current_view(...)`
   - captures the current viewport as the working sensor and asks Mitsuba to render it
6. `daemon.open_capture(...)`
   - opens the latest preview artifact for quick inspection

## 6. Extension Panel Workflow

If you prefer the UI instead of the Script Editor, the extension panel mirrors the same object-style flow.

Use it in this order:

1. choose a scene from the daemon catalog
2. click `Load Scene`
3. move the robot / scene in Isaac
4. click `Connect Session`
5. click `Sync Session`
6. click `Render Current View`
7. click `Open Latest Capture`

The panel still exposes manual refs as a fallback, but the preferred path is:

`scene dropdown -> load -> connect -> sync -> render`

## 7. One-click Capture Flow

The new default flow is session-based.

What happens internally:

1. `daemon.connect_scene_session(...)`
   - opens one active Isaac scene session in the daemon
2. `daemon.sync_scene_state(...)`
   - sends current object transforms
   - sends current material override selections
   - registers current viewport as a sensor
3. `daemon.render_current_view(...)`
   - sends a simple capture request against the active session
   - returns the rendered observation bundle

So in practice the user experience becomes:

`connect once -> sync when scene changes -> click render`

## 7. Where Results Go

Rendered bundles are written under:

```text
out/bridge_jobs/<job_id>/observations/<frame_id>/
```

Typical outputs include:

- `rgb`
- `depth`
- `active_nir_intensity`
- `s1`
- `s2`
- `dop`
- `aolp`
- `manifest.json`

## 8. Troubleshooting

### The extension cannot talk to the daemon

Check:

- the daemon is running in WSL
- `http://127.0.0.1:8765/health` responds
- Isaac can reach that URL from Windows

### Render Current View fails immediately

Check:

- `shape_map_ref` exists
- `mitsuba_scene_ref` exists
- you opened the session first with `daemon.connect_scene_session(...)`

### Materials do not change in Mitsuba output

Check:

- the correct prim is selected in the extension panel
- the prim exists in `shape_map.json`
- the override preset is not `none`

### GPU render does not start

Check in WSL:

```bash
export LD_LIBRARY_PATH=/usr/lib/wsl/lib:$LD_LIBRARY_PATH
```

and confirm your Mitsuba/OptiX runtime is healthy before launching the daemon.

## 9. Recommended First Demo

If you are just getting started:

1. Open MooreLane in Isaac
2. Start the control plane
3. Connect the scene with a known base XML + shape map
4. Sync session
5. Move the Isaac viewport
6. Click `Render Current View`
7. Open the resulting manifest and preview images from the control plane
If you prefer the shortest import surface inside Script Editor, this also works:

```python
import sys
sys.path.insert(0, r"\\jarvis.postech.ac.kr\workspace\jinnyeong\project\robomituba\apps")
from robomituba_isaac import connect_daemon
```
