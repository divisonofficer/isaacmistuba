# IR content-aware dataset pipeline v2

New controller submissions use `pipeline_revision=ir-content-aware-v2`. Existing
job snapshots retain their original stage list and remain recoverable.

## Contracts

- `scene_content_audit.json` checks room-specific anchor groups, strongly
  mismatched furniture, repeated asset digests, and duplicate source blends.
- `candidate_visibility.json` is a deterministic, CPU-only visibility probe over
  the navigation graph and authoring-map object bounds. It does not create a
  Blender or Cycles context.
- `render_plan.json` uses the probe to reject empty-corner, wall-only and unsafe
  forward-clearance views. Its target mix is 60% informative, 25% structural
  context and at most 15% sparse negatives. Portal/hazard poses may be protected.
- `quality/dataset_utility_audit.json` gates immutable publish and links all
  three source contracts by digest.

Adaptive camera budgets cap small, medium and large scenes at 240, 320 and 400
poses respectively; the actual count is further limited by passing candidates.
The requested value is a maximum, not a forced count.

## Scene generation provenance

Generation records `logical_seed`, `effective_scene_seed`, `variation_id`,
`content_policy_version`, `anchor_richness`, and `surface_clutter`. The effective
seed is a stable hash of logical seed, room type, variation and policy version.
Surface clutter controls the late floating-object pass independently of the
room anchor program. Repository-owned constraints add desks/chairs/monitors,
meeting furniture, restroom fixtures, or storage anchors for custom Infinigen
room types that upstream 1.19.1 otherwise leaves empty-ish.

Existing datasets under `/bean/ir_dataset` are read-only inputs to audits. The
v2 pipeline never rewrites them.
