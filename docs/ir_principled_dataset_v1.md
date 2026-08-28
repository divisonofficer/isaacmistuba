# Opaque Principled RGB–Active-NIR Dataset v1

This pipeline is independent of the OpticalNav Mitsuba render daemon. It uses
the verified IR geometry profile only as immutable Stage-1 geometry/PBR input;
Blender 4.2/Cycles is the authority for RGB, synthetic active NIR, and raw PBR
AOVs.

## Stage 2: prepare an immutable Principled scene

```bash
python3 apps/prepare_ir_principled_scene.py \
  --geometry-profile-dir out/ir_dataset/kitchen_structural_specular_lod/ir_geometry \
  --out out/ir_principled/kitchen_stage2_realistic_v1
```

The command never overwrites an existing directory. Reuse is allowed only when
the source blend, Stage-1 unit states, semantic replacements, and compiler
contract match exactly. The default Stage-0 calibration is 40 W and records a
100x RGB-phone-flash luminance reference target. The reference ratio and Cycles
energy are both metadata; the ratio must not be inferred from watts alone.

Stage 2 also replaces high-variance point/spot emitters with a realistic,
room-fixed ceiling fill rig. Each traversable room receives 1–4 downward
rectangular area lights covering approximately 12 percent of its floor area,
clamped to 0.8–2.2 m per panel and placed 10 cm below the detected ceiling. The
default panel power is 30 W with a neutral-warm linear color `(1, 0.93, 0.82)`.
Fixture meshes remain visible, while invalid or small point/spot light objects
are disabled. The entire policy and source-light audit are recorded under
`ambient_fill_rig` in `principled_material_contract.json`.

For Stage-0 calibration only, power can be adjusted without rebuilding Stage 2:

```bash
--ambient-fill-energy-scale 0.5   # effective 15 W/panel
--ambient-fill-energy-scale 2.0   # effective 60 W/panel
```

The scale participates in the dataset fingerprint. Full production renders
should use a fixed value (normally `1.0`) for every frame.

## Stage 0: render and inspect

```bash
python3 apps/render_ir_principled_dataset_queue.py \
  --scene-dir out/opticalnav/opticalnav-v0.2/scenes/infinigen_single_room_kitchen_20260730__ir_semantic_lod_v1 \
  --prepared-scene-dir out/ir_principled/kitchen_stage2_realistic_v1 \
  --out out/ir_principled/kitchen_stage0 \
  --viewpoints vp_000002@90 \
  --width 256 --height 192 --rgb-spp 16 --nir-spp 16 \
  --gpu-indices 0 --workers 1 --qc-components

python3 apps/make_ir_principled_qc_sheet.py \
  --dataset out/ir_principled/kitchen_stage0 \
  --material-contract out/ir_principled/kitchen_stage2_realistic_v1/principled_material_contract.json \
  --frame vp_000002__h_090 \
  --out out/ir_principled/kitchen_stage0/qc_sheet.png
```

The formula shortcut ablation uses the same prepared blend and a separate
dataset root:

```bash
python3 apps/render_ir_principled_dataset_queue.py \
  --scene-dir out/opticalnav/opticalnav-v0.2/scenes/infinigen_single_room_kitchen_20260730__ir_semantic_lod_v1 \
  --prepared-scene-dir out/ir_principled/kitchen_stage2_realistic_v1 \
  --out out/ir_principled/kitchen_stage0_luminance \
  --viewpoints vp_000002@90 --nir-formula luminance_matched_v1 \
  --width 256 --height 192 --rgb-spp 16 --nir-spp 16 \
  --gpu-indices 0 --workers 1 --qc-components
```

## Full rolling render

```bash
python3 apps/render_ir_principled_dataset_queue.py \
  --scene-dir out/opticalnav/opticalnav-v0.2/scenes/infinigen_single_room_kitchen_20260730__ir_semantic_lod_v1 \
  --prepared-scene-dir out/ir_principled/kitchen_stage2_realistic_v1 \
  --out out/ir_principled/kitchen_rgb_active_nir_v1 \
  --width 684 --height 512 --rgb-spp 4000 --nir-spp 2000 \
  --gpu-indices 0,1,2,3,4,5,6,7 --workers 8
```

Each GPU owns one persistent Blender process. Workers claim individual frames
from a shared rolling queue; there are no chunk directories. A frame is
resumable only after its modality files and fingerprinted `frames/*.json` are
complete. The run returns status 2 when the non-semantic fallback pixel ratio
exceeds 5 percent.

Public observations are `rgb/*.exr` and `nir_active/*.exr`. Raw shader
parameters, geometry data, IDs, and validity masks use modality-first
directories documented by `artifact_contract.json`. Light-group flash images
are emitted only with `--qc-components`.

## Legacy v2 RGB/NIR diffuse diagnostic

This section documents the historical v2 output only. Existing datasets remain
immutable and viewers label these artifacts as legacy semantics. New renders
use the v3 transport contract in [ir_principled_dataset_v3.md](ir_principled_dataset_v3.md).

Both existing renders also enable Cycles `Diffuse Direct`, `Diffuse Indirect`,
and `Diffuse Color` passes. No third render is required. The dataset publishes:

```text
diffuse_component_rgb/       diffuse_component_nir/       # float32 EXR
diffuse_reflectance_rgb/     diffuse_reflectance_nir/     # linear PNG16
diffuse_shading_rgb/         diffuse_shading_nir/         # float32 EXR
diffuse_shading_valid_rgb/   diffuse_shading_valid_nir/   # binary PNG8
```

The exact contract is

```text
component   = Cycles Diffuse Direct + Cycles Diffuse Indirect
reflectance = Cycles Diffuse Color
shading     = component / max_per_channel(reflectance, 1e-4)
```

Thus `reflectance * shading` reconstructs only the diffuse component, not the
full Combined observation. Glossy/specular transport is intentionally excluded
so highlights are not forced into albedo or diffuse shading. The valid mask is
false where every reflectance channel is at or below `1e-4`, including fully
metallic or black diffuse lobes.
