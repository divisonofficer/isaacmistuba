"""Stage 1 — canonicalize raw slots into provenance-tagged PBR parameters.

Pure data (no image reads, no Mitsuba): turns each Tier-0 slot into a
`CanonicalMaterial` whose every parameter is stamped with WHERE it came from and
WHETHER it is real. The semantics encode the material-model truths the old harness
faked with constants:

  * Lambertian `diffuse` has NO microfacet roughness      -> roughness undefined, valid=0
  * smooth `dielectric`/`conductor` are delta-specular    -> roughness/alpha = 0 (derived)
  * microfacet alpha is `r^2`, NOT `r`                     -> derived, formula recorded
  * a `conductor` is metallic regardless of a leaked       -> metallic = 1 (derived from BSDF)
    metallicFactor=0
  * `.blend` authoring scalars are authoritative over       -> metallic/roughness prefer
    exported glTF factors                                     authoring when no texture

Spectral parameters (NIR reflectance, IOR, eta/k) are intentionally NOT set here —
they are measured priors and belong to stage 2 (`spectral`). Only the structural PBR
parameters are canonicalized in this stage.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from robomituba_bridge import CanonicalMaterial, MaterialParameter

# analytic_strategy -> (has_microfacet_lobe, is_conductor, is_smooth_specular, is_diffuse)
_FAMILY = {
    "pplastic":        (True,  False, False, False),
    "roughplastic":    (True,  False, False, False),
    "roughconductor":  (True,  True,  False, False),
    "conductor":       (False, True,  True,  False),
    "roughdielectric": (True,  False, False, False),
    "dielectric":      (False, False, True,  False),
    "thindielectric":  (False, False, True,  False),
    "diffuse":         (False, False, False, True),
}


def _first(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


def _base_color(slot: Mapping[str, Any]) -> MaterialParameter:
    ex = slot["extracted"]
    if ex.get("base_color_texture_ref"):
        return MaterialParameter(source="baked", path=ex["base_color_texture_ref"])
    auth = slot["authoring"].get("base_color_factor")
    if auth is not None:
        return MaterialParameter(source="blend_authored", value=list(auth))
    if ex.get("base_color_factor") is not None:
        return MaterialParameter(source="glb_factor", value=list(ex["base_color_factor"]))
    return MaterialParameter.undefined("no base color texture or factor in source asset")


def _roughness_perceptual(slot, has_micro, smooth_spec, diffuse) -> MaterialParameter:
    if diffuse:
        return MaterialParameter.undefined("Lambertian BSDF has no microfacet roughness")
    if smooth_spec:
        return MaterialParameter(source="derived", value=0.0,
                                 formula="smooth delta-specular => roughness 0")
    if not has_micro:  # e.g. measured_polarized: roughness encoded in the pBRDF itself
        return MaterialParameter.undefined("roughness encoded in measured pBRDF, not a scalar")
    ex = slot["extracted"]
    # Prefer an already-unpacked roughness texture; a packed metallic_roughness is the
    # glTF G channel and needs extraction (flagged for stage 4 to unpack).
    if ex.get("roughness_texture_ref"):
        return MaterialParameter(source="baked", path=ex["roughness_texture_ref"],
                                 note="perceptual roughness r (Cycles/glTF convention)")
    if ex.get("metallic_roughness_texture_ref"):
        return MaterialParameter(source="baked", path=ex["metallic_roughness_texture_ref"],
                                 note="packed ORM — roughness is G channel, unpack before use")
    auth = slot["authoring"].get("roughness")
    if auth is not None:
        return MaterialParameter(source="blend_authored", value=float(auth),
                                 note="perceptual roughness r")
    if ex.get("roughness_factor") is not None:
        return MaterialParameter(source="glb_factor", value=float(ex["roughness_factor"]))
    return MaterialParameter.undefined("no roughness texture or scalar in source asset")


def _microfacet_alpha(rough: MaterialParameter, has_micro, smooth_spec) -> MaterialParameter:
    if smooth_spec:
        return MaterialParameter(source="derived", value=0.0,
                                 formula="smooth delta-specular => alpha 0")
    if not has_micro or not rough.valid:
        return MaterialParameter.undefined("no perceptual roughness to convert")
    if rough.path is not None:  # per-texel conversion happens at render time
        return MaterialParameter(source="derived", valid=True,
                                 formula="alpha = r^2 (per-texel from roughness map)",
                                 note=f"from {rough.path}")
    return MaterialParameter(source="derived", value=float(rough.value) ** 2,
                             formula="alpha = r^2")


def _metallic(slot, is_conductor, optical_class) -> MaterialParameter:
    if is_conductor or optical_class == "metal":
        return MaterialParameter(source="derived", value=1.0,
                                 formula="conductor BSDF => metallic 1 (overrides leaked factor)")
    # .blend authoring metallic is the AUTHORITY. Blender's glTF export leaks
    # metallicFactor=1.0 AND a fabricated ~1.0 metallic texture onto procedural
    # (non-Principled) materials, so neither the exported factor nor the texture is
    # trusted as a positive metal signal — render_daemon likewise only blends metal
    # when source_metallic>=0.5. A non-conductor with no authored metallic renders as
    # pplastic (non-metal), so it is metallic 0.
    auth = slot["authoring"].get("metallic")
    if auth is not None:
        return MaterialParameter(source="blend_authored", value=float(auth),
                                 note=".blend authority; exported glTF factor/texture not trusted")
    return MaterialParameter(source="derived", value=0.0,
                             note="non-conductor, no authored metallic (glTF factor/texture not trusted)")


def _normal(slot) -> MaterialParameter:
    ex = slot["extracted"]
    if ex.get("normal_texture_ref"):
        return MaterialParameter(source="baked", path=ex["normal_texture_ref"],
                                 note="tangent-space normal map")
    return MaterialParameter.undefined("no normal map; use geometric normal")


def canonicalize_slot(slot: Mapping[str, Any]) -> CanonicalMaterial:
    strategy = (slot.get("analytic_strategy") or "").strip()
    optical_class = slot.get("optical_class")
    has_micro, is_conductor, smooth_spec, diffuse = _FAMILY.get(
        strategy, (True, False, False, False))  # unknown -> treat as microfacet dielectric
    is_measured = strategy.startswith("measured")
    canonical_bsdf = "measured" if is_measured else (strategy or "pplastic")

    rough = _roughness_perceptual(slot, has_micro and not is_measured, smooth_spec, diffuse)
    params = {
        "base_color": _base_color(slot),
        "roughness_perceptual": rough,
        "microfacet_alpha": _microfacet_alpha(rough, has_micro and not is_measured, smooth_spec),
        "metallic": _metallic(slot, is_conductor, optical_class),
        "normal": _normal(slot),
    }
    extras = {}
    if is_measured and slot.get("measured_candidate"):
        extras["measured_candidate"] = slot["measured_candidate"]
    return CanonicalMaterial(
        material_id=slot["material_id"],
        canonical_bsdf=canonical_bsdf,
        source_bsdf=(slot["extracted"].get("source") or "unknown"),
        optical_class=optical_class,
        shape_ids=list(slot.get("shape_ids", [])),
        parameters=params,
        extras=extras,
    )


def canonicalize_materials(slots_doc: Mapping[str, Any]) -> list[CanonicalMaterial]:
    """Canonicalize every slot in a material_slots document (stage-0 output)."""
    return [canonicalize_slot(s) for s in slots_doc.get("materials", [])]
