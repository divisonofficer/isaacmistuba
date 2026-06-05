# OpticalNav Navigation Editor Master Plan

Last updated: 2026-05-27

## Summary

OpticalNav should become a navigation-aware map and scenario editor, not a form-based dataset generator. The user should be able to open an existing scene floorplan, place glass walls, mirror surfaces, landmarks, goals, and traversable regions on a 2D map, then generate navigation data through the existing Robomituba rendering and OpticalNav dataset pipeline.

The v0.2 MVP targets a usable 2D authoring workflow on top of existing scene floorplans. It does not attempt to replace Isaac Sim as a full 3D editor.

Core user flow:

```text
Open project
  -> choose scene floorplan
  -> click-to-place navigation-aware objects and regions
  -> save authoring_map.json
  -> compile scene_annotation.json
  -> build traversable map
  -> build viewpoint graph
  -> configure sensor sweep
  -> generate graph episodes
  -> render cached observations
  -> validate and export dataset
```

## Product Definition

OpticalNav is a navigation dataset authoring environment for optical-hazard scenes. It lets users create small targeted synthetic fine-tuning datasets for glass, mirror, transparent partition, and reflective-surface navigation.

The editor should feel closer to a game map editor than a JSON form:

- The map is the primary workspace.
- Objects placed on the map carry navigation and dataset semantics.
- The system explains the current blocker and next required action.
- Render and export remain downstream actions, not the starting point.

## MVP Boundary

Included in v0.2:

- Existing scene floorplan as base layer
- 2D overlay editing
- Click-to-place point, line, and rectangle placement
- Navigation-aware object presets
- Object inspector
- Material and tag suggestions
- `authoring_map.json` as editor source of truth
- Compile to `scene_annotation.json`
- Explicit scene synchronization status so edited navigation objects cannot silently diverge from the Isaac/Mitsuba scene used for rendering
- Existing traversable grid, viewpoint graph, graph episode, render, validate, and export APIs reused
- Render precondition checklist for `scene_state` and `camera_spec`

Not included in v0.2:

- Isaac viewport raycast placement
- Blank 2D map to USD scene generation
- Full 3D object manipulation
- Physics rollout
- Real robot execution
- Real-time photoreal preview
- Large procedural furniture library
- VLN-CE or LeRobot native export

## Scene Synchronization Contract

The editor must never pretend that a 2D authoring edit has already changed the live Isaac stage unless that sync actually happened.

There are three synchronization levels:

1. Dataset-only sync
   - `authoring_map.json` and `scene_annotation.json` are updated.
   - Navigation map, graph, scenarios, and labels use the edited objects.
   - The live Isaac stage is not mutated.
   - UI status: `Dataset labels updated; Isaac scene not synced`.

2. Render-scene sync
   - The render scene state or scene variant used by Mitsuba includes the edited object/material semantics.
   - Sensor sweep rendering can proceed.
   - UI status: `Render scene synced`.

3. Live Isaac sync
   - The Isaac stage receives corresponding prims/material overrides.
   - This is not required for the first v0.2 MVP and is deferred behind an explicit `Sync to Isaac` action.
   - UI status: `Isaac stage synced`.

v0.2 MVP must implement dataset-only sync and must expose render-scene sync as a requirement before sensor sweep rendering. Live Isaac sync can be a later milestone, but the UI must show it as pending rather than implying it is complete.

Required invariant:

```text
No silent divergence:
if authoring_map contains edited objects that are not represented in the render scene state,
render must be blocked or clearly marked as using the unsynced base scene.
```

## Milestones

1. Authoring map model
   - Define `authoring_map.json`.
   - Add load/save API.
   - Add validation and round-trip tests.

2. 2D map editor UI
   - Replace JSON-first editing with a map-first workspace.
   - Add placement modes, layer toggles, and object inspector.

3. Annotation compile pipeline
   - Convert authoring objects and regions into existing `scene_annotation.json`.
   - Preserve compatibility with current map/graph/episode code.

4. Graph, sweep, and episode connection
   - Show graph overlays on the map.
   - Use graph episodes as the default v0.2 generation mode.
   - Keep v0.1 trajectory episodes as compatibility.

5. User-friendly readiness flow
   - Expose one current blocker and one primary action.
   - Convert backend precondition errors into actionable UI requirements.

## Execution Plan

Phase 1: Data model

- Add `modules/navigation_dataset/src/navigation_dataset/authoring_map.py`.
- Implement authoring map dataclasses, validation, load/save helpers, preset defaults, and round-trip tests.
- A map with one `glass_wall`, one `traversable` region, and one `goal` region must validate.

Phase 2: API

- Add `GET/PUT /authoring-map`.
- Add `POST /authoring-map/compile` as a real endpoint, initially allowed to return structured compile blockers until the compiler is implemented.
- `GET` on a missing map must return a starter map.
- `PUT` on an invalid map must return object id, field, and reason.

Phase 3: UI canvas

- Make `/datasets` map-first.
- Add palette, native SVG/canvas placement, selection, inspector, layer toggles, and save action.
- MVP placement must support glass wall line, traversable rectangle, and goal rectangle.

Phase 4: Compile

- Convert `authoring_map.json` to `scene_annotation.json`.
- Wire compile endpoint to existing `validate_scene_annotation`.
- Return sync status: dataset-only, render-scene synced, or Isaac synced.
- Keep JSON annotation editing under Advanced for compatibility.

Phase 5: Map and graph

- Wire `Build Traversable Map`.
- Wire `Build Viewpoint Graph`.
- Display traversable, obstacle, hazard, node, and edge overlays on the map.

Phase 6: Sensor sweep

- Add render precondition checklist.
- Translate missing `scene_state` and `camera_spec` into user-facing requirements.
- Add edited-scene sync requirement so sensor sweep cannot silently render the pre-edit base scene.
- Do not call render endpoints when local prerequisites are clearly missing.

Phase 7: Episodes

- Generate graph-mode episodes from `viewpoint_graph.json`.
- Show split, scenario, path node count, hazard crossing, and observation completeness.

Phase 8: Render/export polish

- Render missing cached graph observations.
- Show failed node/heading rows.
- Validate, evaluate, and export.
- Promote export only after validation passes.

## Recommended Schedule

Day 1-2: Model and API

- `authoring_map.py`
- starter map
- load/save API
- unit tests

Day 3-5: 2D map editor MVP

- map-first layout
- palette
- point/line/rectangle placement
- selection and inspector
- save map

Day 6-7: Compile pipeline

- compile endpoint
- glass wall, mirror wall, wall, goal, traversable conversion
- structured compile errors
- dataset/render/Isaac sync status reporting

Day 8-9: Traversable map and graph overlay

- build traversable map from compiled annotation
- build viewpoint graph
- display nodes, edges, and summary

Day 10-11: Readiness flow

- current blocker
- one primary action
- disabled reasons
- advanced raw logs

Day 12-14: Sensor sweep and graph episodes

- render config checklist
- edited-scene sync checklist
- graph episode generation
- scenario template controls
- episode list

Day 15+: Render cache and export polish

- render missing observations
- failed job list
- validation and export package

## Success Criteria

- A user can create a minimum dataset scene without hand-editing JSON:
  - place one glass wall
  - place one traversable floor region
  - place one goal region
  - compile annotation
  - build map and viewpoint graph
  - generate graph episodes
- The UI always explains why the next step is blocked.
- `scene_state` and `camera_spec` errors are shown as render configuration requirements, not raw API text.
- Edited map objects are never silently treated as synced with Isaac or Mitsuba unless sync status says so.
- Existing OpticalNav CLI and existing backend APIs continue to work.

## Definition of Done

The v0.2 MVP is done when this demo works:

1. Open `/datasets`.
2. Select or create `OpticalNav-v0.2`.
3. Open `glass_corridor_001` floorplan.
4. Draw one Glass Wall as a line.
5. Draw one Traversable Region as a rectangle.
6. Draw one Goal Region as a rectangle.
7. Save Map Overlay.
8. Compile Annotation.
9. Build Traversable Map.
10. Build Viewpoint Graph.
11. Generate Graph Episodes.
12. Enter Sensor Sweep and see missing render config or unsynced render scene as a checklist when absent.
13. Validate/Export stays blocked until prerequisites are satisfied.

## PR Slicing

First PR:

```text
feat(opticalnav): add authoring map model and map editor save API
```

Second PR:

```text
feat(webui): add map-first OpticalNav editor with placement tools
```

Third PR:

```text
feat(opticalnav): compile authoring map into scene annotation
```

Later PRs:

- graph overlay and readiness flow
- sensor sweep checklist and graph episodes
- render cache validation and export polish

## Implementation Notes

- `authoring_map.json` is the UI source of truth.
- `scene_annotation.json` remains the backend generation source of truth.
- Scene synchronization state is first-class UI state. Authoring edits, render scene state, and live Isaac stage must have visible sync status.
- The first editor should use native SVG or canvas interaction. Do not introduce a drawing framework unless native handling becomes a clear blocker.
- Existing floorplan metadata already provides the canvas/world coordinate bridge needed for MVP placement.
