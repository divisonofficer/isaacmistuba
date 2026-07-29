"""Physically-plausible optical constants for analytic polarimetric BSDFs.

Infinigen materials never author real IOR / metal identity (dev_report 2026-06-30
§7-10): its Principled BSDF has no complex IOR, metals use base_color as F0, and
the target renderer (Cycles) is unpolarized. Since polarization (DoLP/AoLP) is
governed by the Fresnel term -> IOR / complex eta-k, the legacy render path that
hardcodes ``int_ior=1.5`` / ``material="Al"`` for every surface makes the
polarization signal physically meaningless.

This module maps a material's ``optical_class`` (+ shader-name keyword for a finer
dielectric class) to either a dielectric refractive index (pplastic/dielectric
``int_ior``) or a real metal conductor preset (roughconductor/conductor
``material``, from the eta/k spectra shipped in ``build/.../data/ior``).

Coverage (23 scenes / 6312 materials, dev_report §10): dielectric class table
~87%, named metals ~2%, finish-only metals -> preset fallback ~9%.

IOR sources: pixelandpoly.com/ior.html, refractiveindex.info.
"""

from __future__ import annotations

import os

# --- render-mode toggle -----------------------------------------------------
# legacy   = current hardcoded behavior (int_ior=1.5, material="Al") -- DEFAULT
# injected = analytic BSDF with per-material IOR / metal eta-k injected
# measured = force measured_polarized on analytic-eligible surfaces (reference)


def bsdf_mode() -> str:
    m = (os.environ.get("ROBOMITUBA_BSDF_MODE") or "legacy").strip().lower()
    return m if m in ("legacy", "injected", "measured") else "legacy"


def injection_enabled() -> bool:
    return bsdf_mode() in ("injected", "measured")


# --- metals: optical_class -> Mitsuba conductor preset ----------------------
# Presets available in the production build (build/.../data/ior/*.eta,*.k):
# Au, Ag, Al, Cr, Cu, CuO, Ni_palik, ... No Fe/steel spectrum ships, so Cr is a
# stainless-steel stand-in (rough: a metal's polarization signature is sensitive
# to n,k(lambda) -- flagged as a limitation in the report).
_METAL_PRESET_BY_CLASS = {
    "metal_gold": "Au",
    "metal_steel": "Cr",      # stainless stand-in (no Fe preset)
    "metal_aluminum": "Al",
    "mirror": "Ag",
}
DEFAULT_METAL_PRESET = "Al"

_METAL_NAME_KEYWORDS = (
    ("gold", "Au"), ("brass", "Au"), ("chrome", "Cr"), ("mirror", "Ag"),
    ("steel", "Cr"), ("iron", "Cr"), ("copper", "Cu"), ("silver", "Ag"),
    ("nickel", "Ni_palik"), ("galvan", "Ni_palik"), ("alumin", "Al"),
)
# High-confidence classes that pin the metal element regardless of color.
_METAL_STRONG_CLASS = {"metal_gold", "mirror", "metal_steel"}


def _metal_from_name(shader_name: str | None) -> str | None:
    n = (shader_name or "").lower()
    for key, preset in _METAL_NAME_KEYWORDS:
        if key in n:
            return preset
    return None


def metal_from_base_color(base_color) -> str:
    """L2 fallback: in Infinigen's metallic workflow base_color ~= specular F0, so
    the authored tint is a physical prior for *which* real metal to snap to
    (goldish->Au, reddish->Cu, near-neutral bright->Al, warm/dark neutral->Cr).
    Not a ground-truth recovery (Infinigen's metal color is metal_hsv() random) --
    it picks a real metal whose eta-k is consistent with the RGB appearance."""
    try:
        r, g, b = float(base_color[0]), float(base_color[1]), float(base_color[2])
    except Exception:
        return DEFAULT_METAL_PRESET
    mx = max(r, g, b, 1e-6)
    if mx < 1e-3:
        return "Cr"                       # near-black -> steel/chrome
    rn, gn, bn = r / mx, g / mx, b / mx
    if rn > 0.80 and gn > 0.60 and bn < 0.72 and gn >= bn:
        return "Au"                       # yellow (r~g > b)
    if rn > 0.88 and gn < 0.78 and bn < 0.62:
        return "Cu"                       # orange/red (r >> g,b)
    if min(rn, gn, bn) > 0.85:
        return "Al"                       # near-neutral bright -> aluminium
    return "Cr"                           # warm/dark neutral -> steel/chrome


def conductor_material_for(optical_class: str | None, shader_name: str | None = None,
                           base_color=None) -> str:
    # 1) high-confidence class (gold/steel/mirror) pins the element.
    if optical_class in _METAL_STRONG_CLASS:
        return _METAL_PRESET_BY_CLASS[optical_class]
    # 2) explicit element keyword in the material name.
    hit = _metal_from_name(shader_name)
    if hit:
        return hit
    # 3) finish-only / catch-all metal_aluminum: disambiguate by authored color (L2).
    if base_color is not None:
        return metal_from_base_color(base_color)
    if optical_class in _METAL_PRESET_BY_CLASS:
        return _METAL_PRESET_BY_CLASS[optical_class]
    return DEFAULT_METAL_PRESET


# --- dielectrics: class -> refractive index ---------------------------------
_DIELECTRIC_IOR = {
    "glass": 1.50, "water": 1.33, "ice": 1.31, "ceramic": 1.50, "porcelain": 1.50,
    "marble": 1.49, "stone": 1.50, "plastic": 1.49, "acrylic": 1.49, "wood": 1.50,
    "fabric": 1.50, "leather": 1.50, "plaster": 1.50, "paint": 1.50, "paper": 1.50,
    "skin": 1.40, "organic": 1.45, "soil": 1.50, "plant": 1.42, "rubber": 1.52,
    "wax": 1.44, "concrete": 1.50,
}
DEFAULT_DIELECTRIC_IOR = 1.50

# shader-name keyword -> dielectric class (first match wins)
_SHADER_DIELECTRIC = [
    ("glass", "glass"), ("window", "glass"), ("ceramic", "ceramic"), ("vase", "ceramic"),
    ("porcelain", "porcelain"), ("marble", "marble"), ("tile", "ceramic"),
    ("acrylic", "plastic"), ("plastic", "plastic"), ("cable", "plastic"),
    ("hardwood", "wood"), ("wood", "wood"), ("shelves", "wood"),
    ("knit", "fabric"), ("sofa", "fabric"), ("fabric", "fabric"), ("rug", "fabric"),
    ("lampshade", "fabric"), ("leather", "leather"),
    ("plaster", "plaster"), ("wall", "plaster"), ("art", "paint"), ("text", "paint"),
    ("paint", "paint"), ("basic_bsdf", "plaster"),
    ("bone", "organic"), ("tongue", "skin"), ("nose", "skin"), ("ear", "skin"),
    ("mollusk", "organic"), ("coral", "organic"), ("attr", "skin"),
    ("greenery", "plant"), ("succulent", "plant"), ("stem", "plant"),
    ("mushroom", "plant"), ("cactus", "plant"), ("monocot", "plant"),
    ("spikes", "plant"), ("plant", "plant"),
    ("soil", "soil"), ("dirt", "soil"), ("mud", "soil"), ("sand", "soil"),
    ("mountain", "stone"), ("water", "water"), ("wax", "wax"),
    ("lamp_bulb", "glass"), ("bulb", "glass"),
]


def _dielectric_class(shader_name: str | None) -> str | None:
    n = (shader_name or "").lower()
    for key, cls in _SHADER_DIELECTRIC:
        if key in n:
            return cls
    return None


def dielectric_ior_for(optical_class: str | None, shader_name: str | None = None) -> float:
    if optical_class == "glass":
        return _DIELECTRIC_IOR["glass"]
    cls = _dielectric_class(shader_name)
    if cls:
        return _DIELECTRIC_IOR.get(cls, DEFAULT_DIELECTRIC_IOR)
    return DEFAULT_DIELECTRIC_IOR
