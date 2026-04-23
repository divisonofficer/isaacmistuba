## Same-Scene Render Optimization Status

Date: 2026-04-17

### Why This Exists

This document records what has actually been implemented to reduce repeated non-GPU work when rendering the same scene repeatedly from Isaac into Mitsuba.

It complements:

- [2026-04-17_mitsuba_redundancy_analysis.md](/jarvis/project/robomituba/docs/2026-04-17_mitsuba_redundancy_analysis.md)

The analysis document explains where waste existed.

This document explains:

1. what optimizations are now in the code
2. what they change in practice
3. what still remains

### Short Summary

The pipeline is no longer treating every `render_current_view` call like a fresh whole-scene render setup.

The current implementation now includes:

1. same-scene active session reuse
2. `camera_only` / `material_delta` / `full_resync` sync policy
3. blocking render routed through the daemon queue worker
4. Mitsuba XML parse cache
5. Mitsuba branch template cache
6. resident Mitsuba scene cache for repeated `mi.load_file()` reuse
7. staged XML rewrite skip when content is unchanged
8. staged scene signature cache to skip rebuilding the staged XML entirely
9. render timing summary attached to daemon job status and telemetry

### Implemented Optimizations

#### 1. Same-scene session reuse

Implemented in:

- `apps/isaac_extension/daemon_client.py`
- `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`

What changed:

- if the daemon already has an active Isaac session with the same:
  - `scene_id`
  - `mitsuba_scene_ref`
  - `shape_map_ref`
- the session is reused instead of being logically reopened

Why it matters:

- avoids unnecessary `open_isaac_session()` churn
- reduces session reset risk
- makes the flow closer to `connect once, render many`

Daemon session state now tracks:

- `session_revision`
- `state_revision`
- `material_revision`
- `sensor_revision`
- `state_dirty`
- `material_dirty`

#### 2. Sync-mode split: `camera_only`, `material_delta`, `full_resync`

Implemented in:

- `apps/isaac_extension/daemon_client.py`
- `apps/isaac_extension/ui_panel.py`
- `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`

What changed:

- render requests now choose a sync mode before rendering
- if only the camera changed, we skip full state sync
- if only materials changed, we push material patch only
- if stage state is dirty, we do one full resync and then clear dirty flags

Current sync modes:

- `camera_only`
- `material_delta`
- `full_resync`

Why it matters:

- camera motion no longer forces a full stage snapshot upload by default
- material-only edits are lighter than a full state pass

#### 3. Coarse dirty tracking in the Isaac UI

Implemented in:

- `apps/isaac_extension/ui_panel.py`

What changed:

- stage object changes mark `state_dirty`
- material apply actions mark `material_dirty`
- selection changes do not mark scene dirty

Why it matters:

- we stop treating every UI interaction as a whole-scene change
- render path decisions can be made from real dirty context instead of always full-syncing

#### 4. Blocking render now uses the same queue worker path as async render

Implemented in:

- `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`

What changed:

- blocking render no longer bypasses the daemon queue and worker
- it now internally does:
  - submit job
  - wait for job completion

Why it matters:

- one render execution path instead of two
- progress handling, timeout behavior, telemetry, and state persistence are now much more consistent
- future cache logic only has to be correct in one place

#### 5. Mitsuba XML parse cache

Implemented in:

- `modules/mitsuba_converter/src/mitsuba_converter/multimodal.py`

What changed:

- parsed base XML scene trees are cached by source scene path + file stat

Why it matters:

- repeated XML parsing of the same base scene is reduced
- later staging steps start from cached parse results instead of disk parse every time

#### 6. Mitsuba branch template cache

Implemented in:

- `modules/mitsuba_converter/src/mitsuba_converter/multimodal.py`

What changed:

- branch-specific scene templates are cached for repeated use
- examples:
  - path branch
  - aov branch
  - diffuse override branch
  - stokes branch
  - polarized fallback branch

Why it matters:

- repeated integrator skeleton mutation is reduced
- same branch family can start from a cached prepared template instead of mutating from scratch

#### 7. Resident Mitsuba scene cache

Implemented in:

- `modules/mitsuba_converter/src/mitsuba_converter/multimodal.py`

What changed:

- a small resident LRU cache stores Mitsuba scene objects keyed by:
  - staged scene path
  - staged file stat
  - variant

Current behavior:

- same staged XML + same variant can reuse a previously loaded Mitsuba scene
- `mi.load_file()` is skipped on cache hit

Why it matters:

- directly attacks one of the most obvious repeated CPU-side costs
- helps most in same-scene repeated renders with stable staged XML paths

Current limit:

- resident scene cache size is intentionally small (`8`) to keep memory behavior conservative

#### 8. Unchanged staged XML rewrite skip

Implemented in:

- `modules/mitsuba_converter/src/mitsuba_converter/multimodal.py`

What changed:

- if the staged XML text would be identical to what is already on disk, we do not rewrite the file

Why it matters:

- preserves file timestamp when nothing changed
- allows resident Mitsuba scene cache keys to remain valid longer
- prevents needless filesystem churn

#### 9. Staged scene signature cache

Implemented in:

- `modules/mitsuba_converter/src/mitsuba_converter/multimodal.py`

What changed:

- before rebuilding staged XML, the renderer now computes a signature based on:
  - source scene stat
  - branch kind
  - camera parameters
  - scene override
  - assist light
  - branch-specific integrator parameters

- if the signature matches the previous staged result for the same output file:
  - the staging function returns immediately
  - `_scene_template()` is not called again
  - XML mutation is skipped entirely

Why it matters:

- this is stronger than just “don’t rewrite the file”
- it skips staging work before XML serialization even happens

#### 10. Render timing summary attached to job status and telemetry

Implemented in:

- `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`

What changed:

- after render success, the daemon reads the generated timing log and summarizes:
  - `pass_count`
  - `scene_cache_hits`
  - `scene_cache_misses`
  - `scene_cache_hit_ratio`
  - `load_scene_total_s`
  - `render_total_s`
  - `total_s`
  - `tasks`

- this summary is stored in:
  - `job.status.extras["render_timing_summary"]`
- and emitted into render-job telemetry rows

Why it matters:

- optimization impact is now visible in daemon state
- we can measure whether cache work is paying off instead of only assuming it

### Current Practical Effect

Compared to the earlier behavior, the pipeline now does significantly less repeated setup work in the common case:

#### Camera-only movement inside the same scene

Now:

- active session is reused
- full state sync can be skipped
- only sensor/camera sync is required
- staged XML often stays reusable
- Mitsuba scene load can hit resident cache

This is the most improved path so far.

#### Material-only edits

Now:

- material dirty flag can drive `material_delta`
- full state sync is not always needed
- render still benefits from XML/template/scene caching where branch inputs remain stable

#### Exact repeat render with same inputs

Now:

- parsed XML is reused
- branch template is reused
- staged XML rebuild can be skipped
- staged XML rewrite can be skipped
- `mi.load_file()` can be skipped

This is the path where the current optimization stack helps the most.

### What Is Still Not Done

#### 1. True per-prim live delta engine

Current status:

- dirty tracking is still coarse
- once `state_dirty` is raised, the next resync still uses full state extraction

Still missing:

- exact object-level transform delta upload
- exact per-prim geometry/material invalidation

#### 2. Branch-aware invalidation policy

Current status:

- staged scene signature cache is already a strong improvement

Still missing:

- more explicit rules such as:
  - transform-only change invalidates some branches but not others
  - bsdf-only change invalidates shading branches but not geometric masks
  - camera-only change should reuse more branch artifacts where safe

#### 3. Longer-lived resident Mitsuba cache policy

Current status:

- resident scene cache exists
- cache size is conservative

Still missing:

- smarter memory policy
- eviction policy informed by scene size and branch reuse
- explicit diagnostics in the UI

#### 4. UI visibility

Current status:

- daemon job status and telemetry now contain render timing summaries

Still missing:

- direct rendering of these optimization stats in the Current Scene UI
- for example:
  - cache hit ratio
  - total scene load time
  - sync mode used on last render

### Files Touched By This Optimization Work

Primary implementation:

- `apps/isaac_extension/daemon_client.py`
- `apps/isaac_extension/ui_panel.py`
- `modules/mitsuba_converter/src/mitsuba_converter/render_daemon.py`
- `modules/mitsuba_converter/src/mitsuba_converter/multimodal.py`

Primary tests:

- `tests/contract/test_isaac_daemon_client.py`
- `tests/contract/test_render_daemon.py`
- `tests/contract/test_multimodal_api.py`

### Validation Status

Current contract test status after these optimizations:

- `tests.contract.test_multimodal_api`
- `tests.contract.test_isaac_daemon_client`
- `tests.contract.test_render_daemon`

Result:

- `Ran 61 tests ... OK`

### Recommended Next Step

The next most valuable improvement is:

1. expose the optimization summary in the daemon UI

After that:

2. add branch-aware invalidation rules
3. then refine resident Mitsuba cache memory policy

That sequence keeps the work measurable and reduces the risk of “optimizing blindly.”
