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

__all__ = [
    "extract_material_slots",
    "load_material_slots",
    "SLOTS_SCHEMA_VERSION",
    "canonicalize_materials",
]
