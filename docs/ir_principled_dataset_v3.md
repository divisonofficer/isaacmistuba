# Principled IR Dataset v3: color-separated diffuse transport

New Principled IR renders use `robomituba.ir_principled_dataset.v3` and
`robomituba.ir_principled_artifact_contract.v3`. This changes only newly
created dataset roots; v2 datasets remain immutable and browseable.

## Diffuse artifacts

Cycles provides `Diffuse Direct`, `Diffuse Indirect`, and `Diffuse Color`.
The first two exclude the diffuse BSDF colour, so v3 stores the terms with
their physical roles rather than dividing one by the other:

```text
diffuse_transport_{rgb,nir}/       # float32 EXR: Diffuse Direct + Diffuse Indirect
diffuse_reflectance_{rgb,nir}/     # linear PNG16: Diffuse Color
diffuse_component_{rgb,nir}/       # float32 EXR: reflectance × transport
diffuse_transport_valid_{rgb,nir}/ # binary PNG8
```

For each modality, with `T` transport, `R` reflectance, and `C` component:

```text
T = Diffuse Direct + Diffuse Indirect
R = Diffuse Color
C = R × T
```

`diffuse_transport_valid` is set for finite surface pixels where
`max(R) > 1e-4`; queue-side QC clears non-finite pixels and verifies
`C ≈ R × T` while allowing the documented PNG16 reflectance quantization.
Glossy, transmission, and emission remain excluded from these diffuse terms.

For NIR, the branch is applied before Cycles integration. The artifact contract
records `cycles_path_traced_all_bounces`, the grayscale Rec.709 emitter/world
conversion, and `pseudo_nir_base_color_only`: NIR indirect transport is
recomputed by Cycles, but the reflectance convention is synthetic rather than
a spectral-material claim.

## Legacy v2 adapter

In v2, `diffuse_component` actually denotes legacy diffuse transport and
`diffuse_shading` is a reflectance-normalized diagnostic. The viewer presents
an explicit warning and can derive a virtual corrected component as legacy
transport × legacy reflectance. It never writes that result back to v2.

## InteriorVerse NIR v2

`interiorverse_nir.dataset.v2` retains RGB-derived base transport but adds a
visible-G-buffer, cosine-hemisphere one-bounce correction to passive NIR. It
stores `nir_indirect_ss1` (linear EXR) and `nir_ss1_confidence` (PNG16), with
16 rays/pixel, 48 depth-tested steps/ray, and a 5 m range. The correction is
visible-only; off-screen and unresolved rays contribute zero. CUDA is the
production path, while CPU is a bounded test/fallback path. Per-frame metadata
records the model, settings, confidence statistics, and equal training weight.
