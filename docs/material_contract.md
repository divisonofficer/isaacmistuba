# Material provenance contract (`material_canonical.json`)

Inverse-rendering ground truth requires knowing, per parameter, **where a value came
from** and **whether it is real** — not a single flattened number. The material-mapping
pipeline emits `material_canonical.json` next to each scene, where every PBR parameter
is a `MaterialParameter` (`robomituba_bridge/canonical_material.py`) stamped with a
provenance `source`, a trust `tier`, a `valid` flag, and — for priors — a `confidence`.

## Tiers

| tier | meaning | example sources | use as GT? |
|---|---|---|---|
| 0 | baked / authored — preserved from the source asset | `baked` (texture), `blend_authored`, `glb_factor`, `obj_mtl` | yes |
| 1 | derived — deterministic conversion of a Tier-0 value (`formula` recorded) | `derived` (`alpha = r^2`, smooth→0, conductor→metallic 1) | yes |
| 2 | measured / class prior (carries `confidence`) | `prior:*`, `class_prior`, `measured` | with confidence |
| 3 | heuristic / undefined — NOT ground truth | `heuristic`, `undefined` | no — use valid-mask |

**A parameter that cannot be derived is emitted with `valid=false` and no fabricated
number.** The absence is the signal (surfaced downstream as a valid-mask), never a
plausible grey placeholder.

## Canonicalization rules (stage 1)

- Lambertian `diffuse` has **no** microfacet roughness → `roughness_perceptual` /
  `microfacet_alpha` `undefined, valid=false` (not `1.0`).
- Smooth `dielectric`/`conductor` are delta-specular → roughness/alpha `= 0` (derived).
- Microfacet width is `alpha = r^2`, **not** `r` — the builder currently injects `r`
  straight into Mitsuba `alpha` with no conversion (`render_daemon.py:943-946`); the
  canonical `microfacet_alpha` records the correct `r^2` derivation (a separate ticket
  fixes the render-time injection).
- A `conductor`/`roughconductor` is metallic `= 1` regardless of a leaked
  `metallicFactor = 0` (Blender glTF export leaks it on procedural materials).
- `.blend` authoring scalars (`analytic_fallback.roughness/metallic/base_color`) are
  authoritative over exported glTF factors when no texture is present.
- A packed `metallic_roughness` texture is flagged: roughness is the **G** channel and
  must be unpacked before use.
- Spectral parameters (NIR reflectance, IOR, conductor η/k) are **not** set here — they
  are measured priors produced by stage 2 (`spectral`), from
  `configs/datasets/class_band_reflectance_v1.json` and `optical_constants.py`.

## Pipeline stages

```
0 extract      material_slots.json      (Tier-0 raw, repackaged from daemon sidecars)
1 canonicalize material_canonical.json  (this contract)
2 spectral     material_spectral.json   (NIR / IOR / eta-k priors)          [later]
4 render       raw/*.exr + valid masks  (on-demand PBR AOVs; NOT every render)  [later]
```

Run: `python apps/material_pipeline.py {extract|canonicalize} --scene <id|path>`.
Each stage reads the prior artifact and writes its sibling, so intermediate results are
independently inspectable and diffable.

## On-demand PBR maps

geo/shading normal, `material_region_id`, roughness/metallic/albedo AOVs and valid masks
are part of the schema but are **only rendered when inverse-rendering GT is requested**
(`--pbr-maps`), never on every observation render. The lightweight
`material_canonical.json` is always producible without rendering.
