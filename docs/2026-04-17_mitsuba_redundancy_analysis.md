## Mitsuba Redundancy Analysis

Date: 2026-04-17

### Question

Once a scene is already loaded into Mitsuba, can we avoid repeating non-GPU work for every `render_current_view` request when the user is mostly moving the camera inside the same scene?

### Short Answer

Yes. The current pipeline already keeps some useful state in memory on the daemon side, but it still repeats several expensive CPU / I/O steps on almost every render:

1. Isaac-side full-stage snapshot capture
2. Daemon-side full scene override serialization
3. Mitsuba XML parse + patch + write for every pass
4. Mitsuba `mi.load_file()` for every pass

The biggest savings are likely to come from:

1. turning full-stage sync into dirty-prim sync
2. keeping a resident per-scene render state in the daemon
3. replacing staged XML-per-pass workflows with cached scene templates or cached resident Mitsuba scenes

### What Is Already Reused

#### 1. Active Isaac session is already kept in daemon memory

The daemon holds an in-memory `_IsaacActiveSession` with:

- `scene_id`
- `mitsuba_scene_ref`
- `shape_map_ref`
- `prim_to_shape_ids`
- `objects`
- `material_overrides`
- `sensors`
- `selected_prim_paths`

Relevant code:

- `RenderDaemon._open_isaac_session()` in `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`
- `RenderDaemon._update_isaac_state()` in `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`
- `RenderDaemon._update_isaac_materials()` in `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`

This means the daemon already has a place where incremental state could live.

#### 2. Scene catalog and shape map are reused

`open_isaac_session()` loads the shape map once and stores `prim_to_shape_ids` in the active session.

That is good: shape lookup does not need to be rebuilt during each render.

#### 3. Some daemon request-handler caches already exist

The daemon has TTL caches for:

- job status
- bundle manifests
- session inventory

It also tracks `scene_cache_stats`, but that is telemetry only right now, not a real resident Mitsuba scene cache.

Relevant code:

- `RenderDaemon.__init__()` in `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`

### Where Redundant Work Still Happens

#### A. Every sync captures the whole stage, not just changed objects

`capture_state_patch()` calls `extract_snapshot(stage, ...)`, and `extract_snapshot()` traverses the whole USD stage:

- all renderable meshes
- all cameras
- all lights
- material bindings
- transforms

Relevant code:

- `capture_state_patch()` in `apps/isaac_extension/stage_capture.py`
- `extract_snapshot()` in `apps/isaac_standalone/_stage_bridge.py`

This is the first big repeated cost. Even if one cabinet moved, the current patch generation still scans the full stage and serializes all mesh transforms again.

#### B. `render_current_view_from_daemon()` still rebuilds session context every render

The current render path does:

1. `connect_scene_session_from_daemon()`
2. `sync_scene_state_to_daemon()`
3. `register_isaac_sensors(...)`
4. `capture_isaac_view(...)`

Relevant code:

- `render_current_view_from_daemon()` in `apps/isaac_extension/daemon_client.py`

Inside that chain:

- `connect_scene_session_from_daemon()` always calls `open_isaac_session(...)`
- `sync_scene_state_to_daemon()` again calls `connect_scene_session_from_daemon(...)`

So even when the same scene is already open and unchanged, the control flow still re-opens the logical session and then uploads a full state patch.

This is not the heaviest cost in the whole system, but it is a clear place where repeated orchestration can be reduced.

#### C. Every render request serializes all tracked transforms into `scene_override`

When a render request is built from the active Isaac session, the daemon creates:

- `bsdf_overrides`
- `transform_overrides`

for every tracked object in the session.

Relevant code:

- `RenderDaemon._render_request_from_active_isaac_session()` in `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`

Today this does:

- `transform_overrides = { prim_path: obj.transform for ... in session.objects.items() }`

That means the payload for a single-frame camera move still contains the full transform dictionary of the whole synchronized scene.

#### D. Mitsuba XML is reparsed and rewritten for every pass

Each render branch does:

1. `_parse_scene(scene_path)`
2. mutate integrator / sensor / overrides
3. `_write_scene(...)`

Relevant code:

- `_stage_path_scene()` in `modules/mitsuba_converter/src/mitsuba_converter/multimodal.py`
- `_stage_aov_scene()`
- `_stage_diffuse_override_scene()`
- `_stage_stokes_scene()`
- `_stage_target_mask_scene()`

This means even before ray tracing starts, the system is doing repeated XML parse + DOM mutation + disk write work for every pass.

#### E. Mitsuba `mi.load_file()` happens for every pass

`_render_scene()` does:

1. `mi.set_variant(...)`
2. `scene = mi.load_file(str(scene_path))`
3. `mi.render(scene, spp=...)`

Relevant code:

- `_render_scene()` in `modules/mitsuba_converter/src/mitsuba_converter/multimodal.py`

And because each pass gets its own staged XML path, this means:

- ambient RGB branch reloads scene
- AOV branch reloads scene
- target mask branch reloads scene
- mirror depth branch reloads scene
- polar branch reloads scene

So today there is effectively no scene residency at the Mitsuba scene-object level.

### What This Means In Practice

For the common workflow "same scene, same materials, same objects, only camera moves":

the system still repeats:

- full USD traversal in Isaac
- full transform override upload
- XML parsing and scene staging
- Mitsuba scene loading

For the workflow "same scene, one or two object transforms/materials changed":

the system still behaves much closer to "whole scene changed" than to "small delta changed".

### Highest-Value Optimization Opportunities

#### 1. Add a fast path for already-open active sessions

Current behavior:

- render path always goes through `connect_scene_session_from_daemon()`

Better behavior:

- if daemon active session already matches `scene_id`, `mitsuba_scene_ref`, and `shape_map_ref`
- skip `open_isaac_session()`

Expected gain:

- less orchestration churn
- less session reset risk
- cleaner semantics for "connect once, render many"

#### 2. Split sync into `camera-only`, `selection-only`, `material-only`, and `object-delta`

Current behavior:

- `sync_scene_state_to_daemon()` uses `capture_state_patch()` which is full-stage extraction

Better behavior:

- keep existing full sync for initial connect
- add incremental endpoints for:
  - camera pose only
  - selected prims only
  - changed material overrides only
  - changed object transforms only

Expected gain:

- avoids full stage traversal on small edits
- drastically reduces payload size for camera motion and local object edits

#### 3. Keep daemon-side resident scene override state and send only deltas

Current behavior:

- every render request includes all `transform_overrides`

Better behavior:

- daemon maintains authoritative session override state
- render request carries:
  - camera spec
  - requested modalities
  - small delta or revision id

Expected gain:

- much smaller render-request payload
- less repeated serialization
- cleaner separation between "session state" and "per-frame request"

#### 4. Cache parsed XML templates per branch

Current behavior:

- `_parse_scene()` runs for each staged branch

Better behavior:

- cache parsed base DOM or prebuilt branch template keyed by:
  - `mitsuba_scene_ref`
  - branch kind (`rgb`, `aov`, `polar`, `mask`, etc.)
  - variant / branch policy

Then per frame:

- clone cached template
- only update sensor and dirty shape overrides

Expected gain:

- avoids repeated XML file parsing
- reduces CPU overhead even before true resident Mitsuba caching

This is a relatively low-risk intermediate step.

#### 5. Move toward resident Mitsuba scenes per scene/branch

Current behavior:

- `mi.load_file()` on every pass

Potential future design:

- daemon worker keeps a resident loaded Mitsuba scene per:
  - `scene_ref`
  - branch kind
  - variant
- camera moves update only sensor parameters
- small object/material edits update only changed parameters

Expected gain:

- biggest reduction in repeated non-GPU setup cost
- also best chance to reduce repeated resource setup before rendering

Important caveat:

- this likely needs a clean parameter update strategy and careful thread ownership
- current async queue worker model is actually a good fit, because queued jobs already run in one daemon worker thread
- blocking render paths currently use ad-hoc thread pools, which would make resident scene sharing trickier unless they are also routed through the queue

### Recommended Roadmap

#### Phase 1: Low-risk wins

1. Add fast path: reuse active Isaac session instead of reopening it each render
2. Add `camera_only` render path that skips full state capture
3. Add dirty flags / revision counters so unchanged state is not re-uploaded
4. Cache parsed XML templates before calling `mi.load_file()`

#### Phase 2: Real incremental sync

1. Add transform-delta patch endpoint
2. Add material-delta patch endpoint
3. Stop sending full `transform_overrides` on every render
4. Build daemon-side session revision model

#### Phase 3: Resident Mitsuba scene cache

1. Keep per-scene loaded scene objects alive in daemon worker
2. Update camera / changed objects in place
3. Route blocking render requests through the same worker/cache model

### How To Measure Whether It Works

The project already records useful timing fields:

- `load_scene_s`
- `render_s`
- `total_s`

Relevant code:

- `_render_scene()` in `modules/mitsuba_converter/src/mitsuba_converter/multimodal.py`
- `render_timestep_bundle()` in `modules/mitsuba_converter/src/mitsuba_converter/observation_bridge.py`

That means the optimization loop should be:

1. baseline repeated same-scene renders
2. measure `load_scene_s` and `total_s`
3. add one optimization layer
4. compare per-branch timing logs

The first target metric should be:

- repeated same-scene camera-move renders should show a strong drop in `load_scene_s`

### Bottom Line

There is definitely meaningful room to cut repeated work outside the GPU stage.

The two clearest bottlenecks in the current code are:

1. full-stage snapshot extraction on sync
2. per-pass Mitsuba scene restaging + `mi.load_file()`

If we only choose one big direction, the highest leverage path is:

- keep session state resident in daemon
- move from full-scene sync to delta sync
- then add resident Mitsuba scene reuse on the daemon worker

