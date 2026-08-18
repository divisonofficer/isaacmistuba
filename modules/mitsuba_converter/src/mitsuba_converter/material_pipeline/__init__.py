"""Procedural, provenance-tiered material-mapping pipeline.

Splits the material path (previously tangled inside a single render harness) into
independently-runnable stages, each writing an inspectable artifact next to the
scene so intermediate results can be debugged and diffed:

    stage 0  extract      -> material_slots.json      (Tier-0 raw, repackaged from
                                                        the daemon's existing sidecars)
    stage 1  canonicalize -> material_canonical.json  (per-parameter provenance/valid)
    stage 2  spectral     -> material_spectral.json   (NIR / eta-k priors)      [later]
    stage 4  render       -> raw/*.exr + valid masks  (on-demand PBR AOVs)      [later]

This package deliberately depends only on stdlib + robomituba_bridge (the canonical
material contract). Rendering-heavy stages import Mitsuba lazily.
"""
from .extract import extract_material_slots, load_material_slots, SLOTS_SCHEMA_VERSION
from .canonicalize import canonicalize_materials
from .ir_effective_scene import (
    ALL_SURFACES_DOMAIN,
    IR_SCENE_DOMAIN_SCHEMA,
    OPAQUE_PBR_DOMAIN,
    SPECULAR_MASKED_PBR_DOMAIN,
    STRUCTURAL_SPECULAR_PBR_DOMAIN,
    uses_specular_semantic_masks,
    SUPPORTED_SURFACE_DOMAINS,
    materialize_ir_effective_scene,
    source_scene_digest,
    validate_ir_effective_scene,
)

__all__ = [
    "extract_material_slots",
    "load_material_slots",
    "SLOTS_SCHEMA_VERSION",
    "canonicalize_materials",
    "ALL_SURFACES_DOMAIN",
    "IR_SCENE_DOMAIN_SCHEMA",
    "OPAQUE_PBR_DOMAIN",
    "SPECULAR_MASKED_PBR_DOMAIN",
    "STRUCTURAL_SPECULAR_PBR_DOMAIN",
    "uses_specular_semantic_masks",
    "SUPPORTED_SURFACE_DOMAINS",
    "materialize_ir_effective_scene",
    "source_scene_digest",
    "validate_ir_effective_scene",
    "render_property_maps",
    "build_band_scene",
]


def __getattr__(name):  # lazy: these import mitsuba/multimodal, keep it optional
    if name == "render_property_maps":
        from .dataset_render import render_property_maps
        return render_property_maps
    if name == "build_band_scene":
        from .spectral_band import build_band_scene
        return build_band_scene
    raise AttributeError(name)
