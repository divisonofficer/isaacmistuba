# Ranger Mini 3.0 Asset

Canonical Ranger Mini asset workspace for Isaac/Mitsuba integration.

## Current state

- Canonical runtime path: `/World/RangerMini`
- Axes: `+X forward`, `+Y left`, `+Z up`
- Runtime metadata is stored on the root prim under `robomituba:*`
- `ranger_mini_v3.usda` is a visual/sensor-anchor assembly wrapper only
- `ranger_mini_with_profile.usda` is the current canonical visual source exported from Blender
- PhysX wheel drive must use a separate Isaac URDF-imported or physics-authored USD

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

- Official Gazebo xacro/meshes are used as the source for Isaac URDF Importer
- Final visual source of truth remains `Blender source + exported USD`
- Photoreal lookdev is built on top of the visual subtree
- Physics articulation, collisions, masses, and wheel drives live in a separate generated USD
- Runtime conversion of the visual USD into a PhysX articulation is intentionally unsupported

## Pipeline constraints

- Visual geometry must remain exportable through the existing
  `USD -> snapshot/job -> OBJ fallback` pipeline
- Collision/debug prims must stay out of render snapshots
- Existing `base_link`, 8 joints, and `robomituba:*` runtime state contract must remain stable

## Isaac PhysX authoring workflow

1. Generate the Isaac URDF input package:

   ```bash
   python3 assets/robots/ranger_mini_v3/tools/prepare_isaac_urdf.py
   ```

2. In Isaac Sim, import:

   ```text
   assets/robots/ranger_mini_v3/isaac_urdf/ranger_mini_v3.urdf
   ```

3. Import it as a mobile articulation. Keep the base unfixed, use convex/cylinder
   collisions, and save the resulting USD as:

   ```text
   assets/robots/ranger_mini_v3/isaac_physx/ranger_mini_v3_physx.usd
   ```

4. Mount RGB/NIR/polarization/LiDAR sensors on the generated PhysX robot or wrap it
   with a sensor rig. The visual drag-drop asset remains available for rendering and
   sensor placement, but it is not the wheel-drive simulation asset.

5. Drag `RangerMiniPhysX.usda` from the RoboMitsuba Isaac browser folder after the
   generated PhysX USD exists. The extension control path validates that asset and
   drives it through Isaac `ArticulationAction`, not by editing USD drive attributes.
