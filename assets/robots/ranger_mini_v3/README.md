# Ranger Mini 3.0 Asset

Canonical Ranger Mini asset workspace for Isaac/Mitsuba integration.

## Current state

- Canonical runtime path: `/World/RangerMini`
- Axes: `+X forward`, `+Y left`, `+Z up`
- Runtime metadata is stored on the root prim under `robomituba:*`
- Physics/control still use the existing articulation/joint contract
- `ranger_mini_v3.usda` is the runtime assembly wrapper
- `ranger_mini_with_profile.usda` is the current canonical visual source exported from Blender

## Official mesh acquisition

The most promising public source for the Ranger Mini 3.0 body mesh is AgileX's
`ugv_gazebo_sim` repository, specifically:

- `ranger_mini/ranger_mini_v3/meshes/ranger_base.zip`
- `ranger_mini/ranger_mini_v3/meshes/steering_wheel.dae`
- `ranger_mini/ranger_mini_v3/meshes/wheel_v3.dae`
- `ranger_mini/ranger_mini_v3/urdf/ranger_mini.xacro`

Repo-local reference material and validation artifacts live under:

- `reference/agilex_ugv_gazebo_sim/`
- `tools/fetch_official_mesh.py`
- `tools/validate_official_mesh.py`

Current validation status: the official Gazebo mesh is usable as a shape/reference base,
but not yet treated as the final photoreal asset. The large body mesh is delivered through
`ranger_base.zip`, while the raw `ranger_base.dae` path in GitHub is an LFS pointer.

## Planned authoring direction

- Official Gazebo mesh is used as reference/base geometry input
- Final source of truth remains `Blender source + exported USD`
- Photoreal lookdev is built on top of a cleaned-up visual subtree
- Collision/debug geometry remains separate from renderable visual geometry
- The current assembly wrapper references the Blender-exported `ranger_mini_with_profile.usda`
  and adds runtime metadata, colliders, masses, and wheel/steer joints on top

## Pipeline constraints

- Visual geometry must remain exportable through the existing
  `USD -> snapshot/job -> OBJ fallback` pipeline
- Collision/debug prims must stay out of render snapshots
- Existing `base_link`, 8 joints, and `robomituba:*` runtime state contract must remain stable
