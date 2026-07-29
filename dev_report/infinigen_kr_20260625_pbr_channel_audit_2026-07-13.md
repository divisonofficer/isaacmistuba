# Infinigen kr_20260625 PBR channel extraction audit

## Snapshot reconciliation (authoritative interpretation)

The original source audit is shared by all snapshots, but the manifests are not interchangeable:

| Snapshot | Texture mode A/R/M/N | GLB/UV result | Interpretation |
|---|---:|---|---|
| backup.20260713T100746 | 203 / 161 / 81 / 88 | empty GLB 34, degenerate UV 39 | latest texture-count backup; not a valid GLB contract |
| current kr_20260625 | 193 / 151 / 81 / 93 | GLB 242/242, UV 242/242 | geometry contract fixed, but linked bake validation is absent and 63 units collapse under covered-UV audit |
| staging.20260713T105100-2067801 | 40 units committed | latest exporter | strict run stopped at CellShelfFactory(6182579).spawn_asset(4231825) because linked roughness baked constant |

The per-object source audit remains: 433 mesh records, 242 exporter-renderable units, 191 placeholder duplicates; source material normal inputs are absent. The source variation bitmask over the 242 units is ----=53, -R--=14, -RM-=6, A---=51, AR--=43, ARM-=75. This means metallic texture is unnecessary for most units because an unlinked factor is the correct representation.

On the current valid-GLB audit, 40/242 units have four texture records, but only 24/242 have all four channels spatial on covered texels. The other 218 units have at least one factor/N/A or a flat, collapsed, or unresolved texture. At least one linked channel collapses on 63 units, so file existence is not a valid success criterion.

Current valid-GLB four-map fidelity by source group:

| Group | Units | Result |
|---|---:|---|
| G1 standard PBR/constants | 17 | 17 exact candidates |
| G2 bakeable procedural PBR | 53 | 38 bake-equivalent candidates, 15 unsupported |
| G3 displacement-dependent | 79 | 54 severely lossy, 25 unsupported |
| G4 transmission/glass | 6 | 3 severely lossy, 3 unsupported |
| G5 nonstandard/layered | 87 | 67 severely lossy, 20 unsupported |

The final answer to the three questions is therefore:

1. Rasterization: many channels can be baked, but not every linked channel is guaranteed to produce a valid covered spatial texture. UV coverage, nested closure evaluation, and analytic/layered materials create strict exceptions.
2. Appearance reconstruction: ARMN alone is insufficient for displacement, transmission/IOR, emission, volume, coat, sheen, anisotropy, and layered closures.
3. Real-time approximation: feasible per unit, but only with exact, bake-equivalent, acceptable approximation, severely lossy, or unsupported labels. A four-file set with constant-rasterized or geometry-derived channels must not be counted as four source-varying material channels.

Authoritative JSON artifacts:

- out/infinigen_audits/kr_20260625_original_pbr_audit.json
- out/infinigen_audits/kr_20260625_covered_uv_pbr_audit_new.json
- out/infinigen_audits/kr_20260625_covered_uv_pbr_audit_backup100746.json

- Date: 2026-07-13
- Scene: `infinigen_kr_20260625`
- Export: `out/infinigen_imports/kr_20260625/scene_manifest.json`
- Contract: v2, 242 renderable units
- Status: **Stage 1 geometry/UV/normal recovery passed, but non-normal linked-bake validation is incomplete. Stage 2/sync/render remain blocked.**

## Executive summary

The raw manifest counts are:

| Channel | Texture | Constant | Not applicable |
|---|---:|---:|---:|
| Base color / albedo | 203 | 39 | 0 |
| Roughness | 161 | 81 | 0 |
| Metallic | 81 | 161 | 0 |
| Normal | 88 | 0 | 154 |

These counts do **not** mean that extraction failed whenever a channel is not a texture.

- A Blender Principled input that is genuinely unlinked is correctly represented as a glTF factor/manifest constant.
- A normal bake that is flat is correctly discarded as `not_applicable`.
- Ten helper/structure meshes have no material slot and therefore use explicit default factors with no normal.
- Only linked or multi-material spatial inputs are supposed to become textures.

However, a pixel audit found a separate correctness bug: 39 units have at least one linked albedo, roughness, or metallic texture that is all-black or full-image constant. The current strict validator only checks that the PNG exists. It therefore reports `pbr.status=ok` even when a linked bake has collapsed. This violates the v2 plan's strict contract.

## Why each channel is not a texture on all 242 units

### Base color: 203 texture, 39 constant

The 39 constants are intentional factor cases:

- 29 units have material slots, but all discovered nested Principled Base Color inputs are unlinked constants.
- 10 units have no material slot and use the explicit default `[0.6, 0.6, 0.6]`.

The 203 texture records came from linked or spatially distinct material inputs. Pixel validation shows:

- 167 have non-zero pixel variation in the whole atlas.
- 31 are all black.
- 5 are full-image constant.

Thus only the 39 manifest constants are explained by design. The 36 collapsed linked textures are not acceptable evidence of successful extraction.

### Roughness: 161 texture, 81 constant

The 81 constants are intentional factor cases:

- 71 units resolve to unlinked Principled Roughness factors.
- 10 no-material units use the explicit default `0.6`.

Of the 161 linked texture records:

- 147 have non-zero whole-atlas variation.
- 3 are all black.
- 11 are full-image constant.

The 14 collapsed linked textures require exporter correction or an explicit semantic reclassification; they must not silently pass strict validation.

### Metallic: 81 texture, 161 constant

The 161 constants are mostly expected:

- 151 material-bearing units resolve to unlinked factors, predominantly `0.0`; several analytic metal parts correctly use `1.0`.
- 10 no-material units use `0.0`.

Of the 81 linked/multi-material texture records:

- 78 have non-zero whole-atlas variation.
- 2 are all black.
- 1 is full-image constant.

A constant factor remains valid only when the source socket was unlinked. A texture produced from a linked source that collapses to a constant is a strict failure under the selected contract.

### Normal: 88 texture, 154 not applicable

Normal now follows the intended bake-first contract:

- All 232 material-bearing units were normal-baked.
- 88 passed a coverage-aware central 1–99 percentile spatial variation threshold of 0.02.
- 144 were flat after bake and their PNGs were deleted.
- 10 no-material units were never normal-baked and are `not_applicable`.
- No normal is recorded as a constant.
- At a stronger maximum percentile-range threshold of 0.1, 59 maps remain, which is consistent with the previous estimate of roughly 56 materially varying normal maps.

Normal recovery is therefore no longer the blocker.

## Unit texture combinations

| Texture channels present | Units |
|---|---:|
| albedo + roughness | 47 |
| albedo + roughness + metallic | 43 |
| albedo + roughness + metallic + normal | 38 |
| none | 31 |
| albedo only | 26 |
| albedo + roughness + normal | 25 |
| albedo + normal | 24 |
| roughness only | 7 |
| roughness + normal | 1 |

This distribution is expected to be heterogeneous because constants and N/A are valid outcomes. Requiring four PNGs for every object would duplicate scalar factors, create meaningless flat normal maps, and conflict with the self-contained glTF PBR contract.

## Root cause of the collapsed non-normal textures

The current exporter has asymmetric validation:

- Normal uses a post-bake pixel validator and deletes flat results.
- Albedo uses the Cycles `DIFFUSE` bake pass.
- Roughness uses the Cycles `ROUGHNESS` bake pass.
- Metallic uses a nested Principled-to-Emission substitution.
- Strict PBR validation only rejects a linked channel when no texture path was produced; it does not validate the texture's covered-pixel range.

The built-in DIFFUSE/ROUGHNESS passes do not reliably expose values through every Infinigen nested group, glass/refraction route, or mixed material graph. They can write a PNG successfully while producing black. The same gap permits a linked graph or forced multi-material bake to produce a full-image constant and still pass.

The whole-image min/max audit used here is conservative. A production validator must use a separately baked UV coverage mask so that black atlas background is not mistaken for material variation.

Relevant implementation locations:

- `tools/infinigen/blender_export_scene.py:475` — albedo bake
- `tools/infinigen/blender_export_scene.py:540` — normal pixel validation
- `tools/infinigen/blender_export_scene.py:696` — roughness bake
- `tools/infinigen/blender_export_scene.py:703` — metallic bake
- `tools/infinigen/blender_export_scene.py:839` — nested Principled input contract
- `tools/infinigen/blender_export_scene.py:1276` — current file-existence-only linked check

## Required fix before Stage 2

1. Generalize the nested Principled-to-Emission bake helper for Base Color, Roughness, and Metallic instead of relying on DIFFUSE/ROUGHNESS passes.
2. Bake or generate a per-unit UV coverage mask and validate only covered texels.
3. Store `bake_validation` for all four channels: covered sample count, robust percentile range, black/constant/spatial result, and threshold.
4. In strict mode:
   - fail linked channels with no covered samples;
   - fail linked channels that are black or robustly constant;
   - permit a constant only when the original socket was unlinked;
   - permit normal N/A only after a verified flat bake or when the unit has no material.
5. Re-run Stage 1 only, audit again, and require zero linked-collapse units before Stage 2.
6. Keep sync and RGB/polarization rendering blocked until this gate passes.

## Current verified successes

- GLB present: 242/242
- fallback OBJ present: 242/242
- UV valid: 242/242
- missing referenced texture files: 0
- normal constant records: 0
- spatial normal maps: 88
- flat normal maps discarded: 144
- GLB/PBR unit tests: 6 passed
- Blender long-run instability is isolated by chunked Stage 1 export with atomic manifest merge and resumable staging.

## Linked texture collapse appendix

There are 39 unique affected units: 19 metal, 11 diffuse, 8 glass, and 1 mirror.

- `BalloonFactory(7351594).spawn_asset(9790325)` — metal_aluminum — base_color:black, roughness:black
- `Cube.002` — metal_aluminum — base_color:black
- `Cube.003` — metal_aluminum — base_color:black
- `Cube.004` — metal_aluminum — base_color:black
- `Cube.005` — metal_aluminum — base_color:black
- `Cube.006` — metal_aluminum — base_color:black
- `GlassPanelDoorFactory(5853611).spawn_asset(0)` — metal_aluminum — base_color:black
- `GlassPanelDoorFactory(5853611).spawn_asset(1)` — metal_aluminum — base_color:black
- `GlassPanelDoorFactory(5853611).spawn_asset(3)` — metal_aluminum — base_color:black
- `GlassPanelDoorFactory(5853611).spawn_asset(4)` — metal_aluminum — base_color:black
- `GlassPanelDoorFactory(5853611).spawn_asset(5)` — metal_aluminum — base_color:black
- `HardwareFactory(8245182).spawn_asset(4422616)` — metal_aluminum — metallic:constant
- `JarFactory(3231562).spawn_asset(527553)` — glass — base_color:black
- `MirrorFactory(884242).spawn_asset(6121807)` — mirror — base_color:black, roughness:black
- `NatureShelfTrinketsFactory(2353833).spawn_asset(4524435)` — diffuse — base_color:constant, roughness:constant
- `NatureShelfTrinketsFactory(4221758).spawn_asset(9547199)` — diffuse — base_color:constant, roughness:constant
- `NatureShelfTrinketsFactory(4844736).spawn_asset(8605560)` — diffuse — base_color:constant, roughness:constant
- `NatureShelfTrinketsFactory(5471316).spawn_asset(344466)` — diffuse — base_color:constant, roughness:constant
- `NatureShelfTrinketsFactory(6251345).spawn_asset(4288383)` — diffuse — base_color:black, roughness:black
- `NatureShelfTrinketsFactory(6736818).spawn_asset(9147745)` — diffuse — base_color:constant, roughness:constant
- `OvenFactory(2648629).spawn_asset(4187647)` — metal_aluminum — base_color:black
- `PanelDoorFactory(4622038).spawn_asset(2)` — diffuse — metallic:black
- `Plane.001` — metal_aluminum — base_color:black
- `Plane.002` — glass — base_color:black, roughness:constant
- `Plane.003` — metal_aluminum — base_color:black
- `Plane.004` — glass — base_color:black, roughness:constant
- `Plane.005` — metal_aluminum — base_color:black
- `Plane.006` — glass — base_color:black, roughness:constant
- `Plane.007` — metal_aluminum — base_color:black
- `Plane.008` — glass — base_color:black, roughness:constant
- `Plane.009` — metal_aluminum — base_color:black
- `Plane.010` — glass — base_color:black, roughness:constant
- `Plane.012` — glass — base_color:black, roughness:constant
- `PlateFactory(9597174).spawn_asset(1375567)` — diffuse — base_color:black
- `PlateFactory(9597174).spawn_asset(4706358)` — diffuse — base_color:black
- `PlateFactory(9597174).spawn_asset(5794906)` — diffuse — base_color:black
- `SinkFactory(7637489).spawn_asset(0)` — metal_aluminum — base_color:black
- `StandingSinkFactory(335794).spawn_asset(4727617)` — diffuse — metallic:black
- `VaseFactory(2983453).spawn_asset(0)` — glass — base_color:black

## No-material units

These ten units correctly use explicit factors and normal N/A:

- `Cube.001`
- `NatureShelfTrinketsFactory(120620).spawn_asset(7953580)`
- `NatureShelfTrinketsFactory(3198458).spawn_asset(2814515)`
- `bathroom_0/0.exterior`
- `bedroom_0/0.exterior`
- `bedroom_0/1.exterior`
- `dining-room_0/0.exterior`
- `hallway_0/0.exterior`
- `kitchen_0/0.exterior`
- `living-room_0/0.exterior`
