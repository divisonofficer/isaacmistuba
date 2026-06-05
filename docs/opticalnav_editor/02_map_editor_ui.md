# Sub Plan 02: Map Editor UI

Last updated: 2026-05-27

## Summary

The `/datasets` page should become a map-first editor. JSON remains available under Advanced, but the primary workflow is visual placement and inspection on a 2D floorplan.

The UI should answer three user questions at all times:

- What am I editing?
- What is selected?
- What is the next required action?

## Layout

The page is split into four working areas:

```text
Top: project, scene, pipeline status, next action
Left: palette and tools
Center: 2D map editor
Right: selected object inspector and step requirements
Bottom: logs, validation errors, graph/render progress
```

The current tab names should be reduced to:

- `Map Editor`
- `Graph`
- `Scenarios`
- `Render`
- `Export`

`Map Editor` is the default tab.

## Left Palette

Tool modes:

- Select
- Pan
- Place point
- Place line
- Place rectangle
- Delete

Preset groups:

Structure:

- Wall
- Glass Wall
- Glass Door
- Mirror Wall
- Transparent Partition

Objects:

- Chair
- Table
- Plant
- Shelf

Navigation:

- Start Region
- Goal Region
- Hazard Region
- Forbidden Region
- Stop-before Region
- Traversable Region

Clicking a preset activates the matching placement mode.

## Center Map

Base layers:

- scene floorplan from `/api/scenes/{scene_id}/floorplan`
- occupancy map from `/api/scenes/{scene_id}/occupancy-map`

Editable overlays:

- point objects
- line objects
- rectangle regions

Computed overlays:

- traversable grid
- viewpoint graph nodes
- graph edges
- hazard proximity
- selected path preview

Layer toggles:

- floorplan
- occupancy
- objects
- hazards
- traversable
- goals
- viewpoint nodes
- graph edges

## Placement Interactions

Point placement:

- click map to place center
- selected object appears in inspector
- R rotates 90 degrees

Line placement:

- click start point
- move mouse to preview segment
- click end point
- Shift locks to horizontal/vertical
- Esc cancels

Rectangle placement:

- drag from corner to corner
- release confirms
- Esc cancels

Selection:

- click overlay to select
- drag selected overlay to move
- Delete removes selected item
- inspector updates immediately

Pan and zoom:

- wheel zooms at cursor
- middle mouse or pan tool drags map
- coordinates remain stable through floorplan metadata

## MVP Tool Behavior

Glass wall:

- palette click activates line placement.
- first map click stores start point.
- mouse move previews the segment.
- second click creates `glass_wall` object with `clear_glass` defaults.
- created item is immediately selected.

Traversable region:

- palette click activates rectangle placement.
- drag creates rectangle bounds.
- release creates `traversable` region.
- created item is immediately selected.

Goal region:

- palette click activates rectangle placement.
- drag creates rectangle bounds.
- release creates `goal` region.
- created item is immediately selected.

Delete:

- removes selected object or region.
- marks authoring map dirty.

Save:

- calls `PUT /authoring-map`.
- bottom panel records request and result.

## Right Inspector

When nothing is selected:

- show current step requirements
- show missing prerequisites
- show next action explanation

When object or region is selected:

- id
- type
- label
- placement
- geometry summary
- material preset
- navigation flags
- dataset label flags
- suggested tags

Material changes trigger suggestions.

Example:

```text
Changed material to clear_glass.

Suggested tags:
  TransparentSurface
  HazardRegion
  Blocks navigation
  Include in hazard_mask

[Apply Suggested Tags]
```

## Bottom Panel

The bottom panel should be the operational console for the editor:

- save/compile status
- validation errors
- graph build progress
- render batch progress
- latest API calls
- selected failure details

Raw API payloads should be behind an Advanced disclosure.

## Primary Actions

The header shows one primary action derived from readiness state:

- `Create Project`
- `Add Scene`
- `Save Map Overlay`
- `Compile Annotation`
- `Build Traversable Map`
- `Build Viewpoint Graph`
- `Configure Sensor Sweep`
- `Generate Episodes`
- `Render Missing Observations`
- `Validate Dataset`
- `Export Dataset`

Do not show `Export Dataset` as the primary action before validation passes.

## Acceptance Criteria

- JSON editor is not the primary UI.
- User can create a glass wall on canvas.
- User can create a goal region on canvas.
- User can create a traversable region on canvas.
- Selected item appears in the inspector.
- Delete removes selected item.
- Save authoring map calls the real API.
- Compile annotation calls the real API.
- Disabled actions explain the missing prerequisite.
- Existing bottom and right shell panels show useful page-specific state.
