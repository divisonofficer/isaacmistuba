"""NIR (854/940 nm) diffuse-reflectance synthesis for analytic BSDFs.

Infinigen assets author only an RGB ``base_color`` (a 3-point visible sample).
NIR diffuse reflectance is an independent 4th channel — vegetation red-edge, dye
transparency, print-ink NIR transparency, skin/subsurface — that **cannot be
recovered from RGB**. The legacy discrete-band path reuses the visible albedo
texture for the NIR clone, which is exactly the ``NIR = f(RGB)`` failure that
dev_report/report_2026-07-02.html warns against.

This module *assigns* NIR reflectance as a new physical property, from a physical
material class prior (``configs/datasets/class_band_reflectance_v1.json``), and
optionally synthesises a spatial single-channel NIR reflectance map that transfers
only a class-controlled fraction of the RGB spatial structure:

    rho_NIR(x) = clip[ mu_c * (1 + alpha_c * (L(x)/median(L) - 1)) , 0, 0.95 ]

Metals / glass have ``albedo_channel = false``: their band behaviour lives in the
Fresnel term (``optical_constants`` eta/k) or transmission, not a diffuse map.

Design + provenance: dev_report/report_2026-07-02.html (research/plan),
report_2026-07-14-discrete-band.html (render mechanism).
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np

_TABLE_PATH = Path(__file__).resolve().parents[4] / "configs/datasets/class_band_reflectance_v1.json"
_LUM = (0.2126, 0.7152, 0.0722)

# shader-name keyword / optical_class -> physical_material class. First match wins.
# NOTE: object semantics (shell/coral/bone) are separated from physical material.
# Decorative Infinigen props are often "shell-shaped plastic/resin", so mineral
# classes are assigned at LOW confidence and can be overridden per-asset.
_SHADER_TO_PMAT = [
    # vegetation (geometry-detail foliage) -> NIR red-edge, do NOT use RGB green
    ("greenery", "vegetation_leaf"), ("succulent", "vegetation_leaf"), ("cactus", "vegetation_leaf"),
    ("monocot", "vegetation_leaf"), ("mushroom", "vegetation_leaf"), ("leaf", "vegetation_leaf"),
    ("stem", "vegetation_leaf"), ("spikes", "vegetation_leaf"), ("plant", "vegetation_leaf"),
    ("moss", "vegetation_leaf"), ("fern", "vegetation_leaf"),
    # skin / subsurface organic
    ("tongue", "skin_like"), ("nose", "skin_like"), ("ear", "skin_like"), ("skin", "skin_like"),
    # mineral / calcite decorations (LOW conf: often painted resin)
    ("mollusk", "shell_calcite"), ("shell", "shell_calcite"), ("clam", "shell_calcite"),
    ("conch", "shell_calcite"), ("auger", "shell_calcite"), ("volute", "shell_calcite"),
    ("mussel", "shell_calcite"), ("scallop", "shell_calcite"), ("nautilus", "shell_calcite"),
    ("coral", "shell_calcite"), ("bone", "shell_calcite"),
    # rock / mineral
    ("boulder", "stone"), ("rock", "stone"), ("mountain", "stone"), ("pebble", "stone"),
    ("marble", "stone"), ("gravel", "stone"),
    ("pinecone", "wood"), ("cone", "wood"),
    # built dielectrics
    ("hardwood", "wood"), ("wood", "wood"), ("shelf", "wood"), ("shelves", "wood"), ("bookcase", "wood"),
    ("ceramic", "ceramic"), ("porcelain", "ceramic"), ("vase", "ceramic"), ("tile", "ceramic"),
    ("plaster", "plaster"), ("wall", "plaster"), ("basic_bsdf", "plaster"),
    ("concrete", "concrete"),
    ("knit", "dyed_fabric"), ("sofa", "dyed_fabric"), ("fabric", "dyed_fabric"),
    ("rug", "dyed_fabric"), ("lampshade", "dyed_fabric"), ("cloth", "dyed_fabric"),
    ("text", "printed_surface"), ("art", "printed_surface"), ("print", "printed_surface"),
    ("poster", "printed_surface"), ("label", "printed_surface"),
    ("rubber", "rubber"), ("tire", "rubber"),
    ("soil", "soil"), ("dirt", "soil"), ("mud", "soil"), ("sand", "soil"),
    ("wax", "wax"), ("candle", "wax"),
    ("sand_", "soil"), ("speckle", "stone"),
    ("acrylic", "unpainted_plastic"), ("plastic", "unpainted_plastic"), ("cable", "unpainted_plastic"),
    ("paint", "painted_plastic_dark"),
    # glass / metal (albedo not the knob)
    ("glass", "clear_glass"), ("window", "clear_glass"), ("bulb", "clear_glass"), ("lamp_bulb", "clear_glass"),
    ("frost", "frosted_glass"), ("matte_glass", "frosted_glass"),
    ("chrome", "bare_metal"), ("steel", "bare_metal"), ("iron", "bare_metal"), ("brushed_metal", "bare_metal"),
    ("gold", "bare_metal"), ("brass", "bare_metal"), ("copper", "bare_metal"), ("silver", "bare_metal"),
    ("alumin", "bare_metal"), ("metal", "bare_metal"), ("mirror", "bare_metal"),
]

_OPTICAL_CLASS_TO_PMAT = {
    "glass": "clear_glass",
    "metal_aluminum": "bare_metal", "metal_gold": "bare_metal", "metal_steel": "bare_metal", "mirror": "bare_metal",
}
_LOW_CONF_PMAT = {"shell_calcite", "skin_like", "printed_surface"}


@lru_cache(maxsize=1)
def _table(path: str | None = None) -> dict:
    p = Path(path) if path else _TABLE_PATH
    return json.loads(p.read_text())


def nir_material_mode() -> str:
    """legacy = reuse RGB albedo (old behaviour); class_band_v1 = this module."""
    m = (os.environ.get("ROBOMITUBA_NIR_MATERIAL_MODE") or "legacy").strip().lower()
    return m if m in ("legacy", "class_band_v1") else "legacy"


def physical_material_for(shader_name: str | None, optical_class: str | None = None) -> tuple[str, str]:
    """Map (shader_name, optical_class) -> (physical_material, confidence).

    optical_class is a strong prior for glass/metal; shader keywords resolve the
    dielectric physical material. Unknown -> optical_class-based fallback bucket.
    """
    oc = (optical_class or "").strip().lower()
    if oc in _OPTICAL_CLASS_TO_PMAT:
        return _OPTICAL_CLASS_TO_PMAT[oc], "high"
    n = (shader_name or "").lower()
    for key, pmat in _SHADER_TO_PMAT:
        if key in n:
            conf = "low" if pmat in _LOW_CONF_PMAT else "medium"
            return pmat, conf
    # fallback bucket by optical_class family
    if oc.startswith("metal"):
        return "unknown_metal", "low"
    if oc == "glass":
        return "unknown_glass", "low"
    return "unknown_dielectric", "low"


def _class_entry(pmat: str) -> dict:
    t = _table()
    if pmat in t["classes"]:
        return t["classes"][pmat]
    return t["fallback"].get(pmat, t["fallback"]["unknown_dielectric"])


def nir_reflectance(pmat: str, band: int = 854) -> dict:
    """Effective NIR diffuse reflectance prior for a physical material class.

    Returns {mean, min, max, albedo_channel, rgb_structure_weight, roughness,
    tier, confidence}. If albedo_channel is False (metal/glass) the caller must
    use the Fresnel/transmission path, not a diffuse map.
    """
    e = _class_entry(pmat)
    key = f"rho_{band}"
    rho = e.get(key) or e.get("rho_854") or {"mean": 0.45}
    return {
        "physical_material": pmat, "band": band,
        "mean": float(rho.get("mean", 0.45)),
        "min": float(rho.get("min", rho.get("mean", 0.45))),
        "max": float(rho.get("max", rho.get("mean", 0.45))),
        "albedo_channel": bool(e.get("albedo_channel", True)),
        "rgb_structure_weight": float(e.get("rgb_structure_weight", 0.3)),
        "roughness": float(e.get("roughness", 0.35)),
        "tier": e.get("tier", "prior"), "confidence": e.get("confidence", "low"),
        "note": e.get("note", ""),
    }


def synthesize_nir_texture(rgb_albedo_linear: np.ndarray, pmat: str, band: int = 854,
                           alpha_override: float | None = None) -> Optional[np.ndarray]:
    """Synthesise a single-channel LINEAR NIR reflectance map from an RGB albedo.

    rho_NIR(x) = clip[ mu * (1 + alpha * (L(x)/median(L) - 1)), 0, 0.95 ]
    Only a class-controlled fraction (alpha=rgb_structure_weight) of the RGB
    spatial structure is transferred, so vegetation etc. do NOT become f(RGB).
    Returns None for metal/glass (albedo_channel False) — those are not diffuse.
    Input albedo must be LINEAR (not sRGB) in [0,1]. Output is (H,W) float32.
    """
    info = nir_reflectance(pmat, band)
    if not info["albedo_channel"]:
        return None
    rgb = np.asarray(rgb_albedo_linear, np.float32)
    L = rgb @ np.array(_LUM, np.float32) if rgb.ndim == 3 else rgb.astype(np.float32)
    med = float(np.median(L[L > 1e-4])) if np.any(L > 1e-4) else 1.0
    med = max(med, 1e-4)
    alpha = info["rgb_structure_weight"] if alpha_override is None else float(alpha_override)
    rho = info["mean"] * (1.0 + alpha * (L / med - 1.0))
    return np.clip(rho, 0.0, 0.95).astype(np.float32)


def nir_scalar_reflectance(shader_name: str | None, optical_class: str | None = None,
                           band: int = 854) -> Optional[float]:
    """Convenience: class-mean NIR reflectance for a material (None if metal/glass)."""
    pmat, _ = physical_material_for(shader_name, optical_class)
    info = nir_reflectance(pmat, band)
    return info["mean"] if info["albedo_channel"] else None
