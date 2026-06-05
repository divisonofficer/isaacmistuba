# Sub Plan 04: Graph, Sweep, and Episode Pipeline

Last updated: 2026-05-27

## Summary

After the authoring map is compiled, the existing OpticalNav backend should generate a navigation dataset through a graph-first workflow:

```text
authoring_map.json
  -> scene_annotation.json
  -> traversable_grid.npy
  -> viewpoint_graph.json
  -> sensor sweep refs
  -> graph episodes
  -> validation/evaluation/export
```

v0.2 defaults to panoramic viewpoint graph mode. v0.1 trajectory mode remains available as compatibility.

## Pipeline Steps

1. Compile authoring map
   - Input: `authoring_map.json`
   - Output: `scene_annotation.json`

2. Build traversable grid
   - Input: `scene_annotation.json`
   - Output: `traversable_grid.npy`, sidecar metadata

3. Build viewpoint graph
   - Input: traversable grid and scene annotation
   - Output: `viewpoint_graph.json`
   - Default headings: 12
   - Default yaw step: 30 degrees

4. Configure sensor sweep
   - Input: scene state, camera spec, scene sync status, modalities
   - Output: render-ready sweep configuration or blocked report

5. Generate graph episodes
   - Input: viewpoint graph and instruction/scenario settings
   - Output: graph-mode episode JSON

6. Render cached observations
   - Input: graph node-heading pairs
   - Output: cached observation bundle refs

7. Validate, evaluate, export
   - Input: dataset package
   - Output: validation report, metrics, zip

## UI Actions

Primary actions by step:

- `Compile Annotation`
- `Build Traversable Map`
- `Build Viewpoint Graph`
- `Configure Sensor Sweep`
- `Generate Episodes`
- `Render Missing Observations`
- `Validate Dataset`
- `Export Dataset`

Only one should be primary at a time.

## Graph Display

The map editor should show graph output as overlays:

- viewpoint nodes
- graph edges
- hazard-crossing edges
- isolated nodes
- selected shortest path
- goal candidate nodes

Summary metrics:

- node count
- edge count
- connected component count
- hazard-edge count
- isolated node count
- goal candidate node count

Graph failures should point back to the map:

- no traversable cells
- disconnected graph
- no goal candidates
- too few valid nodes
- all nodes near hazards

Minimum displayed graph summary:

```text
Nodes: 284
Edges: 912
Connected components: 1
Hazard edges: 12
Isolated nodes: 0
Goal candidate nodes: 32
```

## Sensor Sweep Display

Show:

- heading count
- modality list
- total node-heading jobs
- rendered count
- failed count
- missing count
- last failed node/heading

Missing render config should be displayed as requirements:

- Isaac scene state
- Camera spec
- Sensor rig
- Edited scene sync status
- Selected modalities
- Viewpoint graph

Do not show raw `scene_state` or `camera_spec` error as the primary message.

If `authoring_map.json` has edits that are only dataset-synced, sensor sweep must show:

```text
Render scene is not synced

Your navigation labels include edited objects that are not yet represented in the render scene.

Next action:
  Sync Render Scene or continue with base scene explicitly.
```

Continuing with the base scene must be an explicit advanced action, not the default.

Render job summary should be graph-observation based:

```text
Nodes: 284
Headings: 12
Modalities: 4
Total jobs: 13,632
Rendered: 2,100
Missing: 11,532
Failed: 3
```

## Episode Generation

Default v0.2 mode:

- `navigation_mode`: `viewpoint_graph`
- actions:
  - `move_to_neighbor`
  - `turn_left_30`
  - `turn_right_30`
  - `stop`
- episode references cached graph observations where available

Scenario templates:

- `goal_only`
- `hazard_aware`
- `stop_before_glass`
- `detour`

Episode list should show:

- episode id
- split
- scenario
- path node count
- hazard crossing flag
- observation completeness

## Validation and Export

Validation should check:

- `scene_annotation.json` exists and is valid
- traversable grid exists
- viewpoint graph exists for graph episodes
- split files exist
- episode JSON is valid
- cached observation refs resolve when observations are required

Export should be promoted only after validation passes.

## Acceptance Criteria

- Graph build result appears on the map as node and edge overlays.
- Disconnected graph or no traversable cells errors point back to map layers.
- Graph episode generation uses cached graph path mode by default.
- Sensor sweep blocked state is shown as a checklist.
- Edited scene sync is checked before sensor sweep rendering.
- Failed node/heading rows are visible after render attempts.
- Render API errors are translated into actionable requirements.
- Validation and export remain connected to existing backend endpoints.
- v0.1 episode rendering remains available under Advanced or compatibility controls.
