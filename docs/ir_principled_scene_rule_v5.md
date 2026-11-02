# Scene generation rule v5: object-orbiting cameras and per-fixture lighting

Plan schema `robomituba.ir_principled_render_plan.v5`, pose universe
`object_orbit_6dof_v1`, illumination pairing policy `variation_subset_v3`.

This replaces the navigation graph as the camera universe and gives lighting its
own axis. Earlier versions remain immutable: v1-v4 plans take byte-identical
code paths, and their `render_plan_digest` is pinned by
`test_legacy_plan_digests_are_frozen`.

## The rule

One scene produces:

| | count | lighting |
|---|---|---|
| base poses | **50-100** (`BASE_POSE_RANGE`) | `reference_neutral_v1` only |
| variation subset | **10** of those (`variation_pose_count`) | every one of the **5** other conditions |

Total frames = `N + 10 x 5`. Measured: living room 92 + 50 = **142**, apartment
100 + 50 = **150**, bathroom 56 + 50 = **106**.

The subset is chosen one-per-anchor first, then filled by farthest-point
sampling. Ten frames of a single object under five lightings say less about
lighting than ten different objects do, and the anchors are where a scene keeps
its material variety.

Every variation condition covers the *same* ten poses, and all six frames of a
pose share one `pair_id`. So lighting varies against a fixed camera and is not
confounded with viewpoint. This is what `variation_subset_v3` adds over
`reference_subset_v2`, which *partitions* base poses across the variations and
therefore never sees one pose under two lightings.

## Cameras

Poses are placed on a ring around an object and aimed at it, so pitch follows
from the geometry instead of being a near-constant. The graph sampler offered
floor positions and one fixed yaw sweep, so frames faced whatever the heading
happened to hit -- often a bare wall -- and the distance to whatever was in view
was uncontrolled.

- **Working distance 1.0-2.0 m**, measured as the true eye-to-object distance,
  not the ground radius. Active NIR irradiance falls as `1/r^2`, so this is a
  precondition for the specular cue the dataset exists to capture, not a
  framing preference. In a room too small to hold the band the standoff is
  fitted down to `MIN_FITTED_RADIUS_M` (0.75 m) rather than losing the scene.
- **Camera elevation -30 to +55 deg relative to the anchor**, sampled directly.
  Deriving it from an absolute eye height instead made the reachable angle
  depend on the anchor's height and left whole scenes one-sided.
- **Frame fill 0.04-0.30** of frame *area*, solved against the anchor's
  bounding sphere. A large object is met from the far end of the band and a
  small one from the near end. Anchors wider than `MAX_EXTENT_M` (1.2 m) are
  dropped: they cannot be framed from 1-2 m, and the standoff is the constraint
  that may not give.
- **Two orbits per anchor**, each committing to one radius and elevation and
  varying only azimuth, splitting the feasible elevation band between them.
  One orbit per anchor did not supply the 50-pose floor.
- **Field of view 60 deg.** Framing is held constant across FOV because the
  sampler solves standoff for a fill target, so FOV only matters once the
  1-2 m clamp binds -- which is precisely what happens in a small room at a
  narrow FOV. Pose yield at 40/50/60/70 deg: bathroom 14/28/**56**/56, living
  room 90/95/**92**/90, apartment 352/339/**329**/314. Below 60 the smallest
  rooms cannot reach the 50-pose floor.
- Capture kinds are `orbit` (ordered arc, 0.07-0.33 m between neighbours) and
  `sparse_tuple` (wide baseline, >= 90 deg azimuth span).

Free space is checked without the graph: object footprints are extruded to
their real vertical span and tested at the camera's actual height, so a pose
above a table is admitted where a robot-height traversability grid rejects it.
Room bounds come from the floor slab, not the navigation regions -- those are
inset by the robot radius, and objects sit against the walls navigation keeps
clear of.

## Lighting

Bank `configs/ir_lighting/illumination_diversity_v2.json`, schema
`robomituba.ir_illumination_bank.v2`, contract
`illumination-fixture-diversity-v2`: one `reference_neutral_v1` plus five
variations over `ceiling`, `lamp`, `accent` and `ambient_fill` fixture groups.

The plan carries a fixture sampler *specification*, never a resolved fixture
list: `view_plan` runs before `principled_prepare`, so at plan time no prepared
blend exists and the scene's fixtures are unknown. The worker resolves the
subset from `(recipe spec, rig_digest, scene_id)` by per-fixture hash, so
adding or removing one fixture cannot flip another's on/off state.

`portal` is deliberately outside the fixture groups: `_set_environment` runs
after `_set_lighting` and unconditionally rewrites every portal energy, so a
portal mask would be silently overwritten.

**In the NIR band, colour temperature collapses to luminance.** On/off and
energy scale affect both bands; colour is an RGB-only variation that reaches
NIR as a brightness change -- a 2700 K fixture measures luminance 0.52 against
0.96 for 6500 K, so a colour-only condition is roughly half as bright in NIR,
not NIR-invariant. Any claim that NIR improved a material estimate has to
control for that.

## Immutability

Three digests hold published datasets: `worker_sha256`,
`material_contract_digest`, `render_plan_digest`. Every change here is gated so
that with the new flags off the pipeline is byte-identical:

- `_camera_key` branches on `pose_id`, which only free poses carry.
- The legacy `pair_id` string is untouched; `_illumination_recipe` was
  extracted with byte-identical output for v2.
- `variation_pose_count` and `variation_condition_count` appear in the
  illumination block only under `variation_subset_v3`.
