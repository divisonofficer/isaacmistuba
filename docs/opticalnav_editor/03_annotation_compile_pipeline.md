# Sub Plan 03: Annotation Compile Pipeline

Last updated: 2026-05-27

## Summary

The map editor writes `authoring_map.json`. The backend compiles it into the existing `scene_annotation.json` consumed by traversability, planner, viewpoint graph, episode generation, and validation code.

This keeps the UI simple while preserving current backend compatibility.

## API

Add endpoints to the existing render daemon OpticalNav API:

```text
GET  /api/opticalnav/projects/{project_id}/scenes/{scene_id}/authoring-map
PUT  /api/opticalnav/projects/{project_id}/scenes/{scene_id}/authoring-map
POST /api/opticalnav/projects/{project_id}/scenes/{scene_id}/authoring-map/compile
```

`GET` behavior:

- Return existing `authoring_map.json` if present.
- If absent, return a starter map with scene id, floorplan ref, empty objects, empty regions, default settings.

`PUT` behavior:

- Validate payload.
- Write `authoring_map.json`.
- Return saved payload and validation summary.

`POST compile` behavior:

- Read `authoring_map.json`.
- Convert to `SceneAnnotation`.
- Write `scene_annotation.json`.
- Run existing `validate_scene_annotation`.
- Return scene synchronization status.
- Return summary and project detail.

## Endpoint Acceptance

- `GET` absent map returns a starter map.
- `PUT` valid map writes `authoring_map.json`.
- `PUT` invalid map returns `400` with object or region id, field, and reason.
- `GET` after `PUT` returns the same saved payload.
- `POST compile` writes `scene_annotation.json` and returns compile summary.
- `POST compile` returns whether the edit is dataset-only, render-scene synced, or Isaac synced.

## Scene Sync Status

Compilation updates dataset-side semantics. It does not automatically mean the live Isaac stage has changed.

Every compile response must include a sync payload:

```json
{
  "sync": {
    "dataset": "synced",
    "render_scene": "pending",
    "isaac_stage": "pending",
    "message": "Annotation is updated, but render scene and Isaac stage are not synced yet."
  }
}
```

Allowed values:

- `synced`
- `pending`
- `blocked`
- `unsupported`

Rules:

- `dataset` is `synced` after `scene_annotation.json` is written and validated.
- `render_scene` is `pending` when edited objects are not represented in the render scene state or scene variant.
- `isaac_stage` is `pending` until an explicit future `Sync to Isaac` action updates the live stage.
- Sensor sweep rendering must check `render_scene` and either block or clearly warn that it is rendering the base scene without authoring edits.

Future endpoint, not required for first MVP:

```text
POST /api/opticalnav/projects/{project_id}/scenes/{scene_id}/sync-to-isaac
```

This endpoint will create or update corresponding Isaac prims/material overrides from `authoring_map.json`.

## Compile Rules

`glass_wall`:

- Creates `AnnotatedObject`.
- Adds object id to `transparent_surfaces`.
- Creates `HazardRegion`.
- Creates non-traversable footprint through `TraversableRegion(traversable=false)` or equivalent obstacle geometry.
- Sets `mask_export=true`.

`glass_door`:

- Same as `glass_wall`.
- `hazard_type` defaults to `glass_door`.
- May be instruction candidate.

`mirror_wall`:

- Creates `AnnotatedObject`.
- Adds object id to `reflective_hazards`.
- Creates `HazardRegion`.
- Creates non-traversable footprint unless object explicitly marks passable.

`transparent_partition`:

- Creates `AnnotatedObject`.
- Adds object id to `transparent_surfaces`.
- Creates `HazardRegion`.
- Blocks navigation by default.

`wall`:

- Creates `AnnotatedObject`.
- Creates non-traversable footprint.
- Does not create hazard unless explicitly tagged.

`chair`, `table`, `plant`, `shelf`:

- Creates `AnnotatedObject`.
- Creates optional `Landmark` when `instruction_candidate=true`.
- Creates non-traversable footprint when `blocks_navigation=true`.
- Creates optional goal landmark when `goal_candidate=true`.

`goal` region:

- Creates `GoalRegion`.
- Center is rectangle center.
- Radius is half of the shorter rectangle side unless explicitly provided.

`traversable` region:

- Creates `TraversableRegion(traversable=true)`.

`forbidden` and `obstacle` regions:

- Creates `TraversableRegion(traversable=false)`.

`hazard` region:

- Creates `HazardRegion`.
- Does not block navigation unless `blocks_navigation=true`.

`start` region:

- Stored in annotation metadata for samplers.
- Does not need a current `SceneAnnotation` dataclass field in MVP.

`stop_before` region:

- Stored as metadata and optional goal candidate for `stop_before_glass` scenarios.

## Geometry Conversion

Line geometry:

- Convert to a thin box footprint around the line segment.
- Use object `thickness_m`.
- Store source line in `extras.source_geometry`.

Rectangle geometry:

- Convert directly to annotation box bounds.

Point geometry:

- Convert to small box footprint for blocking objects.
- Default footprint size comes from preset metadata.
- Store exact center in `extras.center`.

## Error Reporting

Compile errors must identify:

- object or region id
- field name
- human-readable reason
- suggested fix when possible

Example:

```json
{
  "ok": false,
  "stage": "compile_annotation",
  "status": "blocked",
  "message": "Authoring map cannot be compiled.",
  "errors": [
    {
      "id": "goal_001",
      "field": "geometry.bounds",
      "reason": "Goal region has zero area.",
      "action": "resize_region"
    }
  ]
}
```

## Acceptance Criteria

- Compile output passes `validate_scene_annotation`.
- Compile errors point to the failing authoring object or region.
- `glass_wall` compiles to transparent surface, hazard region, mask-export object, and non-traversable footprint.
- `goal` rectangle compiles to `GoalRegion`.
- `traversable` rectangle compiles to `TraversableRegion(traversable=true)`.
- Compile response exposes dataset/render-scene/Isaac sync status.
- Sensor sweep cannot silently render unsynced edited objects as if they existed in the scene.
- Existing map build API can consume compiled annotation.
- Existing graph and episode APIs require no schema change.
- Existing CLI remains compatible because `scene_annotation.json` is still canonical for backend generation.
