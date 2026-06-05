# Sub Plan 05: User-Friendly Readiness Flow

Last updated: 2026-05-27

## Summary

The editor must guide the user through prerequisites. The current UI has too many buttons visible at once, which makes it hard to know what to do next. The readiness flow replaces that with one current blocker and one primary action.

Design principle:

```text
One current blocker.
One primary action.
Details visible on demand.
Every error maps to a fix.
```

## Pipeline States

Allowed states:

- `not_started`
- `needs_input`
- `ready`
- `running`
- `done`
- `blocked`
- `failed`

Each pipeline step has:

- id
- label
- status
- requirements
- outputs
- next action
- blocked reason

Pipeline steps:

- `project`
- `scene`
- `authoring_map`
- `annotation`
- `traversable_map`
- `viewpoint_graph`
- `sensor_sweep`
- `episodes`
- `render`
- `validation`
- `export`

## Step Outputs

- `project`: dataset root and `dataset.json`
- `scene`: scene directory and base scene reference
- `authoring_map`: `authoring_map.json`
- `annotation`: compiled `scene_annotation.json`
- `traversable_map`: `traversable_grid.npy`
- `viewpoint_graph`: `viewpoint_graph.json`
- `sensor_sweep`: render-ready config or structured blocked report
- `episodes`: split files and episode JSON
- `render`: cached observation bundle refs
- `validation`: validation report
- `export`: zip or package artifact

## Primary Action Logic

The UI derives the primary action in this order:

1. no project -> `Create Project`
2. no scene -> `Add Scene`
3. no authoring map -> `Create Map Overlay`
4. authoring map dirty or annotation missing -> `Compile Annotation`
5. no traversable map -> `Build Traversable Map`
6. no viewpoint graph -> `Build Viewpoint Graph`
7. no sensor config -> `Configure Sensor Sweep`
8. edited scene not render-synced -> `Sync Render Scene`
9. no episodes -> `Generate Episodes`
10. observations missing -> `Render Missing Observations`
11. validation missing -> `Validate Dataset`
12. validation passed -> `Export Dataset`

Secondary actions are still available in the relevant step panel, but they are not visually promoted.

## Requirement Display

For each current step, show requirements as a checklist:

Example for viewpoint graph:

```text
Step Requirements

✓ Scene annotation
✓ Traversable map
✓ Robot profile
✕ Viewpoint graph
○ Sensor sweep plan
○ Episodes
```

Each failed requirement includes:

- reason
- fix action
- target tab or editor element

Sensor sweep requirements must include scene synchronization:

```text
Step Requirements

✓ Viewpoint graph
✓ Selected modalities
✕ Isaac scene state
✕ Camera spec
✕ Edited scene synced to render backend
○ Live Isaac stage synced
```

Live Isaac stage sync is informational in v0.2. Render-scene sync is blocking for sensor sweep unless the user explicitly chooses the advanced base-scene render path.

## Error Translation

Backend structured precondition payloads should be rendered as user-facing blocker cards.

Backend payload:

```json
{
  "ok": false,
  "stage": "render",
  "status": "blocked",
  "message": "Rendering is not ready.",
  "missing": [
    {
      "key": "scene_state",
      "label": "Isaac scene state",
      "reason": "No synced scene state is attached to this dataset.",
      "action": "configure_render_inputs"
    }
  ],
  "next_action": {
    "id": "configure_sensor_sweep",
    "label": "Configure Sensor Sweep"
  }
}
```

UI display:

```text
Rendering is blocked

Missing:
  - Isaac scene state

Recommended action:
  Configure Sensor Sweep
```

Raw payloads should be available only in the bottom panel advanced log.

## Button Rules

- Disabled buttons must explain why.
- Dangerous or premature buttons should not be primary.
- Export should not be promoted before validation passes.
- Render should not call the backend if local prerequisites are obviously missing.
- If an API returns a structured blocked response, keep the user on the relevant step and show the missing requirements.

## Bottom and Right Panels

Right panel:

- current step requirements
- selected object inspector
- missing prerequisites
- suggested fix actions

Bottom panel:

- recent API calls
- validation errors
- render batch progress
- graph build summary
- raw error payloads under Advanced

## Acceptance Criteria

- The top area always shows one current blocker.
- The top area always shows one primary action.
- `Viewpoint graph missing` is clickable and moves to the graph step.
- Render config missing becomes a checklist, not raw JSON error.
- Unsynced edited scene state becomes a checklist item, not a hidden rendering mismatch.
- Export is not promoted before validation passes.
- Disabled actions expose the reason in the UI.
- The bottom panel records request, success, blocked, and failed events.
- Raw API payload is only shown in an Advanced log area.
