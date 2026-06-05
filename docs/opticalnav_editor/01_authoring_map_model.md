# Sub Plan 01: Authoring Map Model

Last updated: 2026-05-27

## Summary

`authoring_map.json` is the source of truth for the OpticalNav map editor. It stores UI-friendly 2D objects and regions in world XZ meter coordinates. It is easier to edit than `scene_annotation.json`, but can be compiled into the existing backend schema.

Canonical path:

```text
out/opticalnav/{project_id}/scenes/{scene_id}/authoring_map.json
```

Package export path:

```text
OpticalNav-v0.2/
  scenes/{scene_id}/authoring_map.json
```

## Coordinate Model

- UI displays floorplan canvas coordinates.
- Saved geometry uses world XZ meter coordinates.
- `x` maps to world X.
- `y` in the authoring schema means world Z for navigation map compatibility.
- Yaw is stored in degrees for UI friendliness.
- Height and thickness are stored in meters where relevant.

This keeps the UI compatible with the existing `SceneAnnotation` coordinate system, which currently uses `xy_yaw` for 2D navigation poses.

## Schema

Minimum payload:

```json
{
  "version": "opticalnav-authoring-map-v0.2",
  "scene_id": "glass_corridor_001",
  "unit": "meter",
  "floorplan_ref": "/api/scenes/glass_corridor_001/floorplan",
  "objects": [],
  "regions": [],
  "materials": [],
  "settings": {
    "grid_size_m": 0.25,
    "default_wall_height_m": 2.4,
    "default_wall_thickness_m": 0.08
  },
  "metadata": {}
}
```

Object shape:

```json
{
  "id": "glass_wall_001",
  "type": "glass_wall",
  "label": "glass wall",
  "placement": "line",
  "geometry": {
    "type": "line",
    "start": [1.0, 2.0],
    "end": [4.0, 2.0],
    "height_m": 2.4,
    "thickness_m": 0.04
  },
  "material": "clear_glass",
  "navigation": {
    "blocks_navigation": true,
    "hazard_type": "transparent_obstacle",
    "include_in_hazard_mask": true,
    "instruction_candidate": true,
    "goal_candidate": false
  },
  "source_ref": null,
  "metadata": {}
}
```

Region shape:

```json
{
  "id": "goal_near_table",
  "type": "goal",
  "label": "table goal",
  "placement": "rectangle",
  "geometry": {
    "type": "rectangle",
    "bounds": [3.0, 1.0, 4.0, 2.0]
  },
  "navigation": {
    "blocks_navigation": false,
    "hazard_type": null,
    "include_in_hazard_mask": false,
    "instruction_candidate": true,
    "goal_candidate": true
  },
  "metadata": {}
}
```

## Allowed Types

Object types:

- `wall`
- `glass_wall`
- `glass_door`
- `mirror_wall`
- `transparent_partition`
- `chair`
- `table`
- `plant`
- `shelf`
- `landmark`

Region types:

- `traversable`
- `obstacle`
- `hazard`
- `goal`
- `start`
- `forbidden`
- `stop_before`

Placement types:

- `point`
- `line`
- `rectangle`

Geometry types:

- `point`: `{ "center": [x, y], "yaw_deg": 0 }`
- `line`: `{ "start": [x, y], "end": [x, y], "height_m": 2.4, "thickness_m": 0.08 }`
- `rectangle`: `{ "bounds": [min_x, min_y, max_x, max_y] }`

Material presets:

- `painted_wall`
- `clear_glass`
- `frosted_glass`
- `mirror`
- `wood`
- `fabric`
- `tile`

## Preset Defaults

`glass_wall`:

- placement: `line`
- material: `clear_glass`
- `blocks_navigation`: true
- `hazard_type`: `transparent_obstacle`
- `include_in_hazard_mask`: true
- `instruction_candidate`: true

`mirror_wall`:

- placement: `line`
- material: `mirror`
- `blocks_navigation`: true
- `hazard_type`: `reflective_obstacle`
- `include_in_hazard_mask`: true
- `instruction_candidate`: true

`chair`, `table`, `plant`:

- placement: `point`
- `blocks_navigation`: true
- `goal_candidate`: true
- `instruction_candidate`: true

`goal` region:

- placement: `rectangle`
- `blocks_navigation`: false
- `goal_candidate`: true
- `instruction_candidate`: true

`traversable` region:

- placement: `rectangle`
- `blocks_navigation`: false

`forbidden` region:

- placement: `rectangle`
- `blocks_navigation`: true

## Validation Rules

- `scene_id` must be non-empty.
- Object and region ids must be unique within their list.
- Placement type must match geometry type.
- Line geometry must have positive length.
- Rectangle bounds must have positive area.
- Point geometry must contain at least `[x, y]`.
- Unknown materials are allowed only if listed in `materials`.
- At least one `traversable` region is required before compile.
- At least one `goal` region is required before compile.

## Implementation Target

Add:

```text
modules/navigation_dataset/src/navigation_dataset/authoring_map.py
```

Required symbols:

- `AuthoringMap`
- `AuthoringObject`
- `AuthoringRegion`
- `AuthoringGeometry`
- `AuthoringNavigationFlags`
- `AuthoringMaterial`
- `starter_authoring_map(scene_id, floorplan_ref=None)`
- `validate_authoring_map(payload_or_model)`
- `load_authoring_map(path)`
- `save_authoring_map(path, map)`

The module should be pure Python plus standard library dataclasses. It should not depend on Svelte, render daemon state, or Mitsuba.

## First Test Fixtures

Valid minimum map:

- one `glass_wall` line
- one `traversable` rectangle
- one `goal` rectangle

Invalid fixtures:

- duplicate object id
- zero-length line
- zero-area rectangle
- unknown placement type
- no traversable region at compile-readiness check
- no goal region at compile-readiness check

## Acceptance Criteria

- `authoring_map.json` can round-trip through API load/save.
- A map containing one `glass_wall`, one `goal` region, and one `traversable` region is valid.
- Geometry is stored in world coordinates, not canvas pixels.
- The structure is understandable without knowing the backend `SceneAnnotation` dataclasses.
- Compile can produce existing `scene_annotation.json` without changing downstream map, graph, or episode code.
- Existing OpticalNav CLI remains unaffected until compile commands are explicitly added.
