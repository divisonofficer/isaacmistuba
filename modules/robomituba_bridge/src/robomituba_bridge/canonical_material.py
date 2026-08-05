"""Provenance-tagged canonical material contract.

The pipeline that turns Infinigen/Cycles materials into Mitsuba BSDFs mixes values
of very different trust: a *baked* texture, a *derived* conversion (r -> alpha^2), a
measured *prior* (NIR reflectance, conductor eta/k), and pure *heuristics*. For
inverse-rendering ground truth these must not be flattened into one number — the
consumer has to know, per parameter, WHERE the value came from and WHETHER it is a
real measurement or a placeholder.

`CanonicalMaterial` carries one `MaterialParameter` per PBR parameter, each stamped
with a provenance `source`, a `tier`, a `valid` flag and (for priors) a `confidence`.
A parameter that cannot be derived is emitted with ``valid=False`` and NO fabricated
number — the absence is the signal, surfaced downstream as a valid-mask rather than a
plausible-looking grey value.

This module is pure-Python (no numpy/Mitsuba) so it can live in the dependency-free
bridge and be imported from either side of the pipeline.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping, Optional, Sequence

# Provenance tiers (see docs/material_contract.md).
TIER_BAKED = 0        # texture/scalar preserved straight from the source asset
TIER_DERIVED = 1      # deterministic conversion of a Tier-0 value (formula recorded)
TIER_PRIOR = 2        # measured/class prior (carries a confidence)
TIER_HEURISTIC = 3    # convenience guess — EXCLUDED from ground truth (valid stays False)

_SOURCE_TIER = {
    "baked": TIER_BAKED,
    "blend_authored": TIER_BAKED,
    "glb_factor": TIER_BAKED,
    "obj_mtl": TIER_BAKED,
    "derived": TIER_DERIVED,
    "prior": TIER_PRIOR,
    "class_prior": TIER_PRIOR,
    "measured": TIER_PRIOR,
    "heuristic": TIER_HEURISTIC,
    "undefined": TIER_HEURISTIC,
}


def tier_for_source(source: str) -> int:
    """Map a provenance source string to its trust tier. A ``prefix:detail`` source
    (e.g. ``prior:optical_constants``) is keyed on the prefix."""
    key = source.split(":", 1)[0]
    return _SOURCE_TIER.get(key, TIER_HEURISTIC)


@dataclass
class MaterialParameter:
    """One PBR parameter (e.g. base_color, microfacet_alpha) with provenance.

    Exactly one of ``path`` (a texture on disk) or ``value`` (a scalar/vector) is the
    payload; both are None when ``valid`` is False (the value could not be derived).
    """
    source: str                         # e.g. "baked", "derived", "prior:optical_constants"
    valid: bool = True
    path: Optional[str] = None          # texture file (repo-relative), when spatially varying
    value: Any = None                   # scalar or [r,g,b] / [x,y,z], when uniform
    confidence: Optional[float] = None  # for prior/heuristic sources, in [0,1]
    formula: Optional[str] = None       # for derived sources, e.g. "alpha = r^2"
    note: Optional[str] = None

    @property
    def tier(self) -> int:
        return tier_for_source(self.source)

    @classmethod
    def undefined(cls, note: str) -> "MaterialParameter":
        """A parameter the material's BSDF simply does not define (e.g. microfacet
        roughness on a Lambertian). No number is invented; valid is False."""
        return cls(source="undefined", valid=False, note=note)

    def to_payload(self) -> dict:
        out: dict = {"source": self.source, "tier": self.tier, "valid": self.valid}
        if self.path is not None:
            out["path"] = self.path
        if self.value is not None:
            out["value"] = self.value
        if self.confidence is not None:
            out["confidence"] = self.confidence
        if self.formula is not None:
            out["formula"] = self.formula
        if self.note is not None:
            out["note"] = self.note
        return out

    @classmethod
    def from_payload(cls, d: Mapping[str, Any]) -> "MaterialParameter":
        return cls(
            source=d["source"], valid=bool(d.get("valid", True)),
            path=d.get("path"), value=d.get("value"),
            confidence=d.get("confidence"), formula=d.get("formula"), note=d.get("note"),
        )


@dataclass
class CanonicalMaterial:
    """A material reduced to Mitsuba's canonical model, with per-parameter provenance.

    ``canonical_bsdf`` is the Mitsuba family the renderer actually uses
    (pplastic/dielectric/conductor/roughconductor/roughdielectric/diffuse/measured/blend);
    ``parameters`` maps parameter name -> MaterialParameter.
    """
    material_id: str
    canonical_bsdf: str
    source_bsdf: str = "unknown"                 # cycles_principled | glb_pbr | obj_mtl | usd
    optical_class: Optional[str] = None
    shape_ids: Sequence[str] = field(default_factory=list)
    parameters: MutableMapping[str, MaterialParameter] = field(default_factory=dict)
    extras: MutableMapping[str, Any] = field(default_factory=dict)

    def valid_parameters(self) -> dict:
        return {k: p for k, p in self.parameters.items() if p.valid}

    def to_payload(self) -> dict:
        return {
            "material_id": self.material_id,
            "canonical_bsdf": self.canonical_bsdf,
            "source_bsdf": self.source_bsdf,
            "optical_class": self.optical_class,
            "shape_ids": list(self.shape_ids),
            "parameters": {k: p.to_payload() for k, p in self.parameters.items()},
            "extras": dict(self.extras),
        }

    @classmethod
    def from_payload(cls, d: Mapping[str, Any]) -> "CanonicalMaterial":
        return cls(
            material_id=d["material_id"], canonical_bsdf=d["canonical_bsdf"],
            source_bsdf=d.get("source_bsdf", "unknown"), optical_class=d.get("optical_class"),
            shape_ids=list(d.get("shape_ids", [])),
            parameters={k: MaterialParameter.from_payload(v)
                        for k, v in (d.get("parameters") or {}).items()},
            extras=dict(d.get("extras") or {}),
        )


CANONICAL_MATERIAL_SCHEMA_VERSION = "robomituba-material-canonical-v1"


def canonical_document(scene_id: str, materials: Sequence[CanonicalMaterial]) -> dict:
    """Wrap canonical materials into the versioned per-scene document."""
    return {
        "version": CANONICAL_MATERIAL_SCHEMA_VERSION,
        "scene_id": scene_id,
        "materials": [m.to_payload() for m in materials],
    }
