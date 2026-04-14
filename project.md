# robomituba Project Brief

Last updated: 2026-04-01

This file is the quick onboarding brief for future agents working in this repo.
Treat it as the current working summary unless newer code or artifacts clearly supersede it.

## Goal

- Canonical short-term goal: connect NVIDIA Isaac Sim to Mitsuba so that scene state and material edits authored in Isaac can be rendered in Mitsuba.
- Canonical first deliverable: `Isaac Sim 상의 현재 로봇 재현 + 1차 RGB 데이터셋 handoff`.
- Canonical bridge goal after that: use Isaac Sim as the source of robot state, pose, time, and scene edits, then hand off the matching scene/material/light/sensor state to Mitsuba for research-grade optical rendering.
- Long-term research direction: polarization and NIR observation for transparent-obstacle safety evaluation in glass-door indoor scenes.
- Fastest near-term engineering target inside this repo: stabilize a narrow single-scene bridge path before expanding to full-scene coverage.

## Scope Guardrails

- Do not describe this project as a generic full-scene simulator or a universal renderer bridge.
- Isaac Sim and Mitsuba are tools, not the research end goal.
- The core problem is validating state-dependent optical observations for robot safety in transparent-obstacle scenes.
- For now, prefer one representative glass-door or dining/interior scene with a minimal material set over broad asset coverage.
- Initial collaboration is RGB-first. Polarization and NIR are staged expansions, not the first milestone.

## Current Verdict

- Narrow curated path: partially proven.
- Reusable end-to-end committed pipeline: not done yet.
- Do not describe the committed converter as material-aware, light-aware, camera-aware, or instancer-aware.

## Useful Paths

- Project root: `/jarvis/project/robomituba`
- Main converter package: `modules/mitsuba_converter`
- MooreLane USD asset: `assets/moorelane/Intel_mooreLane_v1_2_0/Intel_mooreLane/USD/MooreLane_ASWF_0621_fullComposition.usda`
- Existing Mitsuba build noted in progress log: `/home/jinnyeong/robomituba-build/mitsuba3`
- Project tracking page: `https://www.notion.so/2fee09c820b781a899acf0d042aaf554`
- External planning docs used to clarify scope:
  - `/home/jinnyeong/codex_workspace/2026NRF/조인트_프로젝트_매니지먼트_플랜.md`
  - `/home/jinnyeong/codex_workspace/2026NRF/지원서_초안.md`
  - `/home/jinnyeong/codex_workspace/2026NRF/연구스토리_정리.md`

## Canonical Project Definition

The clearest current definition comes from the 2026NRF planning documents:

- Short-term execution path:
  1. Reproduce the current robot and sensor setup in Isaac Sim.
  2. Build and hand off an RGB dataset for a navigation/VLA baseline.
  3. In parallel, build the Isaac Sim -> Mitsuba bridge.
  4. Extend the bridge toward polarization and NIR observations later.

- Research-level requirement:
  - Isaac Sim generates robot state, time, collision, and sensor placement.
  - Mitsuba generates optical observations for the same state on the same time index.

- Minimal scene information that must eventually survive the bridge:
  - geometry
  - materials
  - lights
  - cameras / sensor definitions
  - pose / time / frame identity

## Preferred Bridge Architecture

Treat Isaac Sim as the scene-authoring and state-authority side, and Mitsuba as a sidecar renderer.

Recommended logical flow:

1. Isaac Sim authors or edits a USD stage.
2. A bridge layer snapshots the current stage for a chosen frame or time index.
3. The bridge exports a compact scene package:
   - geometry references
   - material metadata
   - light metadata
   - camera / sensor metadata
   - frame/time/pose metadata
4. Mitsuba consumes that package and renders the requested observation.

Important design choice:

- Do not start by trying to replace Isaac Sim’s viewport renderer.
- Start with an offline or batch sidecar render path that takes a stage snapshot and produces Mitsuba outputs for a selected frame.

## Isaac Sim Integration Notes

Official Isaac Sim docs confirm a few implementation assumptions that matter here:

- The current USD stage can be accessed via `isaacsim.core.utils.stage.get_current_stage()`.
- Isaac Sim’s higher-level material APIs support fetching and applying visual materials such as `PreviewSurface`, `OmniPBR`, and `OmniGlass`.
- USD material authoring and binding are stored through `UsdShade` and `UsdShade.MaterialBindingAPI`.

What this means for this repo:

- The bridge should treat USD and `UsdShade` as the stable interchange layer.
- Isaac-specific wrappers are useful for detecting common material classes, but the exported bridge format should not depend exclusively on those wrappers.
- Material extraction should read bound USD materials and shader inputs in a way that survives both authored USD and Isaac-side edits.

## Committed Reusable Path

These files are the actual reusable converter path currently committed in the repo:

- `modules/mitsuba_converter/src/mitsuba_converter/pipeline.py`
- `modules/mitsuba_converter/src/mitsuba_converter/usd_loader.py`
- `modules/mitsuba_converter/src/mitsuba_converter/mitsuba_builder.py`
- `modules/mitsuba_converter/src/mitsuba_converter/render.py`
- `modules/mitsuba_converter/src/mitsuba_converter/types.py`

What that path currently does:

- `pipeline.py` wires `UsdSceneLoader.load()` into `MitsubaSceneBuilder.build()`.
- `usd_loader.py` extracts only `UsdGeom.Mesh`, triangulates faces with a simple fan strategy, and stops after 20 meshes.
- `mitsuba_builder.py` builds a fixed-camera scene with a constant emitter and per-mesh diffuse BSDFs.
- `render.py` renders Mitsuba scene dicts and can convert EXR to PNG, but it does not add missing scene semantics.
- `types.py` still has TODO coverage for point instancers, materials, lights, and cameras.

The package README still describes the MVP as diffuse-first:

- `modules/mitsuba_converter/README.md`

## What Is Already Working Experimentally

There is newer exploratory work beyond the committed converter path.

- `modules/mitsuba_converter/src/mitsuba_converter/usd_export_obj_mtl.py`
  - Exports world-space OBJ+MTL.
  - Preserves UVs and normals.
  - Groups geometry by bound material.
  - Extracts base-color textures from `USDPreviewSurface` / `UsdUVTexture` when available.

- `out/moorelane_cameras/cameras.json`
  - Camera extraction exists.
  - Current artifact shows 21 cameras parsed from the MooreLane USD.

- `out/moorelane_lights/lights_report.json`
  - Light extraction exists.
  - Current artifact shows 52 USD lights discovered.

- `out/moorelane_dining_textured_split/materials.json`
  - Dining-room experiment exported 6 textured material groups into separate OBJ files.

- `out/moorelane_dining_textured_split_render_principled/scene.xml`
  - A generated Mitsuba scene already uses Mitsuba `principled` BSDFs.

- `out/moorelane_dining_interior_lit_cam03/scene.xml`
- `out/moorelane_dining_interior_lit_cam03/meta.json`
  - Interior-lit render exists with an extracted dining-room camera, 8 rect lights, 4 sphere lights, and an HDRI envmap.

## Where To Start Modifying

If the actual product goal is "edit materials in Isaac Sim, then render in Mitsuba", the first place to work is not the renderer wrapper. It is the scene handoff contract.

Recommended implementation order:

1. Define a real bridge IR.
   - Extend `types.py` beyond meshes.
   - Add explicit records for materials, lights, cameras, instances, and frame metadata.
   - Add scene identity fields such as `scene_id`, `frame_id`, `timestamp`, `meters_per_unit`, and `up_axis`.

2. Split loading into two layers.
   - Keep a low-level USD/Isaac scene snapshot loader.
   - Keep a separate Mitsuba scene builder that only consumes the bridge IR.
   - Avoid mixing USD traversal logic directly into Mitsuba emission logic.

3. Implement material extraction before broad geometry expansion.
   - First support the smallest useful material set for the target scenario:
     - glass
     - metal frame
     - diffuse wall
     - floor
     - dark plastic
   - Map these into Mitsuba-native BSDFs such as `dielectric`, `roughdielectric`, `conductor`, `principled`, `diffuse`, and `twosided` when needed.

4. Add camera and light extraction to the committed path.
   - The repo already has artifacts proving those extractors exist conceptually.
   - Promote them into supported code before tackling full-scene instancing.

5. Add one narrow end-to-end command.
   - Example target flow:
     - Isaac/USD stage -> bridge snapshot directory -> Mitsuba scene -> render outputs
   - Verify it on one representative indoor scene, not the full 740-mesh MooreLane scene.

## Concrete Code Starting Points

- `modules/mitsuba_converter/src/mitsuba_converter/types.py`
  - First file to change.
  - This is where the project needs a real bridge IR instead of `SceneIR(meshes=...)`.

- `modules/mitsuba_converter/src/mitsuba_converter/usd_loader.py`
  - Second file to change.
  - Turn this from a minimal mesh loader into a scene snapshot loader or split it into dedicated extractors.

- `modules/mitsuba_converter/src/mitsuba_converter/mitsuba_builder.py`
  - Third file to change.
  - Keep it focused on mapping bridge IR into Mitsuba scene structure.
  - Do not let it become responsible for USD traversal details.

- `modules/mitsuba_converter/src/mitsuba_converter/cli.py`
  - Add a narrow bridge-oriented command rather than only `convert` and `render`.

- `modules/mitsuba_converter/src/mitsuba_converter/usd_export_obj_mtl.py`
  - Reuse ideas here for textured/material-aware export, but do not let OBJ/MTL become the only long-term interchange if the bridge needs richer optical metadata.

## Immediate Next Engineering Task

The single highest-leverage next task is:

- define and implement a stable "scene snapshot" format for one Isaac/ USD frame that includes material, light, camera, and pose metadata.

Without that snapshot contract, every later step stays fragile.
With it, both RGB-first baseline rendering and later polarization / NIR expansion have a common foundation.

## Key Gaps And Blockers

- The committed CLI path still emits fixed-camera diffuse scenes, not the principled/material-aware scenes demonstrated in experiments.
- Material coverage is incomplete even in the curated dining-room audit.
  - `out/moorelane_dining_materials/report.json` reports 17 materials missing diffuse textures, 18 missing roughness textures, and 17 missing normal textures out of 23 scoped materials.
- Full-scene coverage is still rough.
  - `out/moorelane_full_export/plan_report.json` reports 740 meshes, 207 materials, and 230 meshes with no material assignment.
  - `out/moorelane_full_export/export_stats.json` reports 205 materials actually exported in the artifact set.
- `PointInstancer` support is still not part of the committed IR or pipeline.

## Recommended Next Move

Promote the dining-room experimental path into a supported command path first.

Suggested order:

1. USD subtree export to grouped OBJ+MTL.
2. Reuse the extracted camera and light data.
3. Generate a Mitsuba scene with `principled` or `twosided` BSDFs from that exported data.
4. Wrap the narrow path in a committed CLI flow with a stable output contract and a small verification test.

Defer full-scene instancing support and long-tail material handling until that narrow path is stable.

## Evidence Files To Read First

If you are picking this project up cold, read these before making claims about current capability:

- `modules/mitsuba_converter/README.md`
- `modules/mitsuba_converter/src/mitsuba_converter/usd_loader.py`
- `modules/mitsuba_converter/src/mitsuba_converter/mitsuba_builder.py`
- `modules/mitsuba_converter/src/mitsuba_converter/usd_export_obj_mtl.py`
- `notes/progress_2026-02-13_moorelane_mitsuba.md`
- `out/moorelane_cameras/cameras.json`
- `out/moorelane_lights/lights_report.json`
- `out/moorelane_dining_textured_split/materials.json`
- `out/moorelane_dining_materials/report.json`
- `out/moorelane_full_export/plan_report.json`
- `out/moorelane_full_export/export_stats.json`
- `/home/jinnyeong/codex_workspace/2026NRF/조인트_프로젝트_매니지먼트_플랜.md`
- `/home/jinnyeong/codex_workspace/2026NRF/지원서_초안.md`
- `/home/jinnyeong/codex_workspace/2026NRF/연구스토리_정리.md`

## Working Assumptions

- The experiments are good proof-of-direction, but they are not yet the same thing as a reusable supported pipeline.
- If a future change claims full MVP completion, verify it against the committed converter code, not only against files under `out/`.
- The 2026-02-13 progress note still matches the repo surprisingly well; use it as historical context, but prefer current code when they conflict.
