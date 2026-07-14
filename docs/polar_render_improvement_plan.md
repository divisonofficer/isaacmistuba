# Polar Render Improvement Plan

Date: 2026-07-09
Status: Implemented on 2026-07-13. The final implementation supersedes the earlier fallback-policy proposal below.

## Final Implementation Decision

- Polar rendering uses the same material-policy staging as RGB; only the Mitsuba integrator and polarized variant differ.
- Polar requests no longer promote `analytic_only` to `analytic_priority`. Explicit measured scopes remain shared request settings for every sensor.
- Automatic `pplastic` material fallback scenes and retry renders were removed. Weak or invalid Stokes output is preserved and reported through quality metadata.
- Legacy saved requests containing `polar_fallback_mode` remain loadable, but the retired key is ignored.
- The original P2/P3 text is retained below as historical diagnosis, not current behavior.

## Current Failure Summary

Recent polar camera renders are not failing because `polar_cam` is fundamentally broken. The observed stall is caused by a `polar_fallback` scene load entering Mitsuba/OptiX compilation and never returning.

Observed state:

- Active daemon: `127.0.0.1:8766`
- Stage: `loading_scene`
- Blocking worker: GPU 2, PID `2742693`
- Blocking job: `opticalnav-infinigen_kr_20260625-perturbed-vp_000001-h_030-6e9395e3-polar`
- Blocking sub-step: `compiling_optix`
- Scene load concurrency: `ROBOMITUBA_SCENE_LOAD_CONCURRENCY=1`
- Held slot: `/tmp/robomituba_scene_load_slots/slot_0`
- Other polar workers are waiting at `waiting_scene_load_slot`

Likely trigger:

1. Current request omits `measured_scope`.
2. Runtime/web UI default is now `analytic_only`.
3. The original polar pass produces weak Stokes S1/S2.
4. Weak signal triggers `polar_fallback`.
5. The fallback scene is large and expensive to compile.
6. `mi.load_file()` hangs inside OptiX compilation.
7. The worker remains alive, so PID-based stale-slot cleanup does not release the scene-load slot.
8. The entire polar queue backs up.

Prior successful evidence for the same job:

- Date: 2026-06-29
- `selected_polar_scene: polar`
- `fallback_used: false`
- `measured_scope: analytic_priority`
- `load_scene_s: 8.86`
- `render_s: 53.30`

## Goals

- Prevent polar rendering from hanging indefinitely.
- Preserve useful polar outputs even when fallback is weak, slow, or unavailable.
- Make large OpticalNav polar sweeps resumable and observable.
- Keep changes scoped to render reliability and polar fallback policy.

## Non-Goals

- No Mitsuba C++ plugin rebuild unless a later canary proves it is required.
- No broad renderer refactor.
- No OpticalNav dataset schema redesign.
- No destructive cleanup of existing render outputs without explicit approval.

## Phase P0: Immediate Recovery

Objective: unblock the current queue and establish a safe canary.

Planned actions:

1. Stop or restart the stuck 8766 render daemon and preview workers.
2. Remove stale scene-load slot files only after the owning worker is stopped.
3. Run one canary polar job:
   - Scene: `infinigen_kr_20260625`
   - Job family: perturbed polar
   - Candidate: `vp_000001-h_030`
   - Settings: `measured_scope=analytic_priority`, `max_measured_bsdfs=3`
4. Confirm:
   - no `polar_fallback` hang
   - scene load completes in a bounded time
   - output manifest and polar artifacts are written
   - `render_timing.json` records `fallback_used=false` or a bounded fallback result

Approval needed before action: yes.

## Phase P1: Hang Prevention

Objective: ensure a single stuck worker cannot block the full polar queue for hours.

Planned changes:

1. Add a scene-load watchdog for render workers.
   - Detect `loading_scene` duration above a configured threshold.
   - Suggested default: 10-15 minutes for GPU scene load.
   - Mark job as `gpu_scene_load_timeout`.
   - Restart the worker process.

2. Add scene-load slot heartbeat.
   - Current stale cleanup only checks whether the holder PID is alive.
   - Add `heartbeat_at` to `holder.json`.
   - Treat the slot as stale if the holder heartbeat is too old.

3. Make parent cleanup authoritative.
   - If the daemon kills/restarts a worker, it should remove any slot held by that worker.
   - This prevents `waiting_scene_load_slot` from persisting after worker intervention.

4. Improve stuck job visibility.
   - Show current `sub_step`, elapsed time, slot holder PID, GPU index, and job id.
   - Keep this available through daemon health/system endpoints.

Approval needed before implementation: yes.

## Phase P2: Polar Fallback Policy

Objective: avoid unnecessary fallback renders for weak-but-valid polarization.

Planned changes:

1. Do not automatically fallback on weak S1/S2 alone.
   - Weak polarization can be a physically valid result for ambient analytic scenes.
   - Keep weak signal as metadata/warning instead of forcing `polar_fallback`.

2. Use fallback primarily for invalid results.
   - Trigger fallback for NaN/Inf, low finite ratio, or excessive invalid pixels.
   - Keep current invalid checks, but revisit thresholds after canary runs.

3. Preserve original polar output if fallback fails or times out.
   - Save original Stokes products.
   - Record:
     - `fallback_attempted=true`
     - `fallback_used=false`
     - `fallback_failed_reason`
     - `original_polar_preserved=true`

4. Make fallback policy configurable.
   - Suggested env/settings:
     - `ROBOMITUBA_POLAR_FALLBACK_MODE=invalid_only|weak_or_invalid|disabled`
   - Suggested default for large sweeps: `invalid_only`.

Approval needed before implementation: yes.

## Phase P3: Sweep Defaults

Objective: make polar sweeps use settings that match the proven successful path.

Planned changes:

1. For polar sensor sweeps, explicitly set:
   - `measured_scope=analytic_priority`
   - `max_measured_bsdfs=3`

2. Keep RGB/NIR default path lightweight.
   - `analytic_only` can remain the global/default path for non-polar previews.

3. In web UI, make polar measured scope visible.
   - Avoid silent omission of `measured_scope` for polar render requests.
   - Keep the user-facing default aligned with the render backend policy.

Approval needed before implementation: yes.

## Phase P4: Performance and Quality

Objective: reduce compile cost and improve observability for large scenes.

Planned changes:

1. Strengthen resident base-scene reuse for ambient polar renders.
   - Reuse the same base Stokes scene when only the camera/viewpoint changes.

2. Lightweight fallback scenes.
   - For fallback-only rescue, consider stripping normal maps or high-cardinality texture nodes.
   - Keep analytic BSDFs simple.

3. Complexity guardrails.
   - If staged scene exceeds thresholds such as:
     - high mesh count
     - high texture count
     - high BSDF count
   - Run a low-cost canary or skip fallback with metadata rather than compiling blindly.

4. Improve API responsiveness.
   - Paginate `/api/render-jobs`.
   - Keep queue summary fast even with 1000+ pending/running jobs.

Approval needed before implementation: yes.

## Proposed Implementation Order

1. P0 recovery and canary only.
2. P1 watchdog and slot heartbeat.
3. P2 fallback policy changes.
4. P3 polar sweep defaults.
5. P4 performance and UI/API refinements.

## Verification Plan

Canary checks:

- Run one polar canary job.
- Confirm `job_status.json` reaches `succeeded` or bounded `failed`, never indefinite `running`.
- Confirm no scene-load slot remains held after completion/failure.
- Confirm `render_progress.log` does not remain at `loading_scene` beyond watchdog threshold.

Regression checks:

- Run existing Python tests for `mitsuba_converter` where feasible.
- Add focused tests for:
  - weak polarization does not force fallback in `invalid_only` mode
  - invalid polarization still attempts fallback
  - fallback timeout preserves original polar products
  - scene-load slot stale heartbeat cleanup

Operational checks:

- `GET /health` should remain fast.
- Large queue status should remain inspectable.
- Worker restart should not leave stale slot directories.

## Open Questions

- Should `analytic_priority` become the default only for polar sweeps, or should web UI expose it as the recommended polar preset?
- What watchdog timeout is acceptable for production scenes: 10, 15, or 30 minutes?
- Should existing successful polar outputs be skipped by default during reruns?
- Should fallback be disabled entirely for dataset sweeps unless explicitly requested?
