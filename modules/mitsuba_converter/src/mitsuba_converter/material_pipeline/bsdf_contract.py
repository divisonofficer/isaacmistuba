"""Enforce the canonical BSDF contract on a render_scene.xml (in place or to a copy).

Two fixes the daemon's scene builder does not yet apply (see material_contract.md §4):

  #1  roughconductor = SOURCE-FAITHFUL.  The builder emits a *named* metal preset
      (`<string material="Al">`) AND a `specular_reflectance = base_color` multiplier,
      i.e. Fresnel(Al) × base_color — the base colour is applied on top of an already-
      near-total aluminium reflectance, over-darkening dark metals (the black-cup bug).
      The `.blend` intent (Principled metallic) is that base_color IS the metal's
      reflectance/F0. So drop the preset and make the conductor a near-perfect reflector
      (eta≈0, k≈1 ⇒ Fresnel≈1) tinted ONCE by `specular_reflectance = base_color`.

  #2  microfacet alpha = r².  Blender Principled roughness r maps to GGX α = r²; the
      builder injects r straight into `alpha`, so materials render too rough/blurry.
      Square the roughness: a scalar alpha → alpha²; an alpha *texture* → a cached
      squared copy of the image (linear-space).

Both are pure XML/texture transforms (no variant/plugin change), so they are device
independent — no Mitsuba rebuild.
"""
from __future__ import annotations

import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

_MICROFACET = {"pplastic", "roughplastic", "roughconductor", "roughdielectric"}


def _square_roughness_png(path: str, out_dir: Path) -> Optional[str]:
    src = Path(path)
    if not src.is_file():
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / f"{src.stem}.sq{src.suffix}"
    if not dst.is_file():
        a = np.asarray(Image.open(src)).astype(np.float32) / 255.0
        Image.fromarray((np.clip(a * a, 0, 1) * 255).astype(np.uint8)).save(dst)
    return str(dst)


def _alpha_to_r2(bsdf: ET.Element, tex_dir: Path) -> None:
    """Square the `alpha` param (scalar or texture) of one microfacet bsdf element."""
    for fl in bsdf.findall("float"):
        if fl.get("name") == "alpha":
            try:
                fl.set("value", f"{float(fl.get('value')) ** 2:.6f}")
            except (TypeError, ValueError):
                pass
    for tex in bsdf.findall("texture"):
        if tex.get("name") != "alpha":
            continue
        for s in tex.findall("string"):
            if s.get("name") == "filename":
                sq = _square_roughness_png(s.get("value", ""), tex_dir)
                if sq:
                    s.set("value", sq)


def _source_faithful_conductor(bsdf: ET.Element) -> None:
    """Drop the metal preset and make the conductor a near-perfect reflector tinted once
    by specular_reflectance (= base_color). Fresnel(eta≈0,k≈1)≈1 so R ≈ base_color."""
    for s in list(bsdf.findall("string")):
        if s.get("name") == "material":
            bsdf.remove(s)
    # remove any pre-existing eta/k, then set the neutral reflector
    for tag in ("rgb", "spectrum", "float"):
        for e in list(bsdf.findall(tag)):
            if e.get("name") in ("eta", "k"):
                bsdf.remove(e)
    bsdf.insert(0, ET.Element("rgb", {"name": "k", "value": "1 1 1"}))
    bsdf.insert(0, ET.Element("rgb", {"name": "eta", "value": "0.0001 0.0001 0.0001"}))


def apply_contract_to_subtree(elem: ET.Element, tex_dir: Path) -> tuple[int, int]:
    """Apply #1 (source-faithful conductor) + #2 (alpha=r²) to every bsdf under `elem`.
    Use this on a band-carrier __vis/__nir subtree so the RENDER honours the contract
    while the untouched render_scene.xml stays the source-r GT for property maps."""
    n_c = n_a = 0
    for b in elem.iter("bsdf"):
        bt = b.get("type")
        if bt in _MICROFACET:
            _alpha_to_r2(b, tex_dir); n_a += 1
        if bt in ("roughconductor", "conductor"):
            _source_faithful_conductor(b); n_c += 1
    return n_c, n_a


def apply_bsdf_contract(scene_xml: Path, out_xml: Optional[Path] = None,
                        tex_dir: Optional[Path] = None) -> dict:
    """Rewrite scene_xml enforcing #1 (source-faithful conductor) and #2 (alpha=r²).
    Writes to out_xml (default: in place). Returns a summary."""
    scene_xml = Path(scene_xml)
    out_xml = Path(out_xml) if out_xml else scene_xml
    tex_dir = tex_dir or (scene_xml.parent / "roughness_sq")
    tree = ET.parse(scene_xml)
    root = tree.getroot()
    conductors = squared = 0
    for bsdf in root.iter("bsdf"):
        bt = bsdf.get("type")
        if bt in _MICROFACET:
            before = ET.tostring(bsdf)
            _alpha_to_r2(bsdf, tex_dir)
            if ET.tostring(bsdf) != before:
                squared += 1
        if bt in ("roughconductor", "conductor"):
            _source_faithful_conductor(bsdf)
            conductors += 1
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_xml, encoding="unicode")
    return {"conductors_source_faithful": conductors, "alpha_squared": squared,
            "xml": str(out_xml), "tex_dir": str(tex_dir)}
