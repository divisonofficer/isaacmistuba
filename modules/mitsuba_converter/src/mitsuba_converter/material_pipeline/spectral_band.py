"""Stage 2/3 — build a discrete-band (visible+NIR) Stokes carrier scene.

Wraps EVERY material of a scene into a ``blendbsdf(weight, __vis, __nir)`` so ONE
resident scene, loaded once under ``cuda_ad_rgb_polarized``, serves both bands: flip
the per-material ``weight`` (0 = visible, 1 = NIR) via ``mi.traverse`` params — no
reload — and render Stokes to get RGB / NIR intensity + DoP / AoLP together
(the unified pipeline `tools/debug_render_rig.py` / `benchmark_band_sweep.py` drive it).

The ``__nir`` sub-BSDF carries this session's NIR-albedo work: for an opaque-dielectric
(``albedo_channel``) material its ``diffuse_reflectance`` is replaced with the HYBRID
NIR albedo (``nir_reflectance.synthesize_nir_texture`` — class-prior μ_c + relative
local-contrast structure transfer), so NIR is a real reflectance band, not a base-color
swap + white flash. Metals keep their conductor Fresnel and glass its dielectric Fresnel
(their optics are ~band-invariant in an RGB-approx variant), so the meaningful visible↔NIR
difference lands where it physically belongs — diffuse reflectance.

Input is the scene's ``render_scene.xml`` + ``material_canonical.json`` (any scene), so
the unified band renderer becomes usable on arbitrary scenes, not one hand-built scene.
"""
from __future__ import annotations

import copy
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Mapping, Optional

import numpy as np
from PIL import Image

from mitsuba_converter.nir_reflectance import (
    physical_material_for, nir_reflectance, synthesize_nir_texture,
)
from mitsuba_converter.multimodal import _ensure_measured_bsdf_wavelength
from mitsuba_converter.material_pipeline.bsdf_contract import apply_contract_to_subtree

_VISIBLE_NM = 542   # representative visible band for measured pBRDF staging (matches RGB render)


def _scene_dir(scene: Path) -> Path:
    return scene.parent if scene.is_file() else scene


def _bsdf_to_material(scene_dir: Path) -> dict[str, str]:
    """bsdf id -> material_id, via xml_scene_index (shape->bsdf_ref) + policy
    (shape->material_id). First shape that uses a bsdf wins (shared across shapes)."""
    idx = json.loads((scene_dir / "xml_scene_index.json").read_text())
    pol = json.loads((scene_dir / "render_scene_material_policy.json").read_text())
    sh2mat = {sp["shape_id"]: sp.get("material_id")
              for sp in pol.get("shape_policies", []) if sp.get("shape_id")}
    out: dict[str, str] = {}
    for sh in idx.get("shapes", []):
        ref, mid = sh.get("bsdf_ref"), sh2mat.get(sh.get("shape_id"))
        if ref and mid:
            out.setdefault(ref, mid)
    return out


def _srgb_to_linear(a: np.ndarray) -> np.ndarray:
    return np.where(a <= 0.04045, a / 12.92, ((a + 0.055) / 1.055) ** 2.4)


def _nir_albedo_png(base_color_path: str, pmat: str, band: int, out_dir: Path) -> Optional[str]:
    """Synthesize (and cache) the hybrid NIR albedo map for a base-color texture."""
    src = Path(base_color_path)
    if not src.is_file():
        return None
    dst = out_dir / f"{src.stem}.nir{band}_hybrid.png"
    if not dst.is_file():
        rgb = _srgb_to_linear(np.asarray(Image.open(src).convert("RGB"), np.float32) / 255.0)
        nir = synthesize_nir_texture(rgb, pmat, band)
        if nir is None:
            return None
        out_dir.mkdir(parents=True, exist_ok=True)
        Image.fromarray((np.clip(nir, 0, 1) * 255).astype(np.uint8)).save(dst)
    return str(dst)


def _swap_diffuse_to_nir(nir_bsdf: ET.Element, pmat: str, band: int, nir_dir: Path) -> bool:
    """In a copied BSDF subtree, replace the diffuse_reflectance base-color bitmap with
    the hybrid NIR albedo map. Returns True if a swap happened."""
    swapped = False
    for tex in nir_bsdf.iter("texture"):
        if tex.get("name") != "diffuse_reflectance":
            continue
        for s in tex.findall("string"):
            v = s.get("value", "")
            if s.get("name") == "filename" and v.endswith("_base_color.png"):
                nir_png = _nir_albedo_png(v, pmat, band, nir_dir)
                if nir_png:
                    s.set("value", nir_png)
                    swapped = True
    return swapped


def build_band_scene(
    scene: Path,
    canonical: Mapping[str, Any],
    out_path: Path,
    *,
    band: int = 854,
    nir_dir: Optional[Path] = None,
    max_depth: int = 8,
    nir_flash: bool = False,
) -> dict:
    """Write a band carrier scene next to (or at) out_path. Returns a build summary.

    ``nir_flash`` adds a rig-mounted point emitter ``id="nir_flash"`` (a headlamp) that
    the runner band-gates: OFF (intensity 0) in the visible band so RGB stays passive,
    ON in the NIR band so NIR shows the active illumination — an active-NIR light that
    only the NIR band sees, from ONE weight-flip scene. Its ``position`` is moved to the
    camera per view via mi.traverse."""
    scene = Path(scene)
    scene_xml = scene if scene.is_file() else scene / "render_scene.xml"
    scene_dir = _scene_dir(scene)
    nir_dir = nir_dir or (scene_dir / f"nir_band_{band}")
    bsdf2mat = _bsdf_to_material(scene_dir)
    mat_by_id = {m["material_id"]: m for m in canonical.get("materials", [])}

    tree = ET.parse(scene_xml)
    root = tree.getroot()

    # A Stokes carrier: the unified runner reads S0..S3 from one render. max_depth 8 so
    # multi-surface glass transmits (a low depth renders bottles as opaque black).
    for integ in root.findall("integrator"):
        root.remove(integ)
    stokes = ET.Element("integrator", {"type": "stokes"})
    path = ET.SubElement(stokes, "integrator", {"type": "path"})
    ET.SubElement(path, "integer", {"name": "max_depth", "value": str(int(max_depth))})
    root.insert(0, stokes)

    # rig NIR headlamp — band-gated by the runner (0 in visible, on in NIR).
    if nir_flash:
        em = ET.SubElement(root, "emitter", {"type": "point", "id": "nir_flash"})
        ET.SubElement(em, "rgb", {"name": "intensity", "value": "0 0 0"})  # off (visible)
        ET.SubElement(em, "point", {"name": "position", "x": "0", "y": "1.2", "z": "0"})

    wrapped = nir_swapped = metal_glass = unresolved = measured = 0
    contract_conductors = contract_alpha = 0

    for b in root.findall("bsdf"):
        bid = b.get("id")
        if not bid:
            continue
        orig_type = b.get("type")
        orig_children = list(b)

        # __vis = the original material verbatim
        vis = ET.Element("bsdf", {"type": orig_type, "id": f"{bid}__vis"})
        for c in orig_children:
            vis.append(c)

        # __nir = a copy whose diffuse albedo becomes the hybrid NIR reflectance
        nir = ET.Element("bsdf", {"type": orig_type, "id": f"{bid}__nir"})
        for c in orig_children:
            nir.append(copy.deepcopy(c))

        # measured_polarized (single-band pBRDF) needs a concrete wavelength to load in
        # the RGB-approx variant; give each band its own so measured metals are a REAL
        # spectral band pair (visible 542 vs nir 854 channel slice), not identical.
        if _ensure_measured_bsdf_wavelength(vis, target_nm=_VISIBLE_NM):
            measured += 1
        _ensure_measured_bsdf_wavelength(nir, target_nm=band)

        # RENDER contract (material_contract §4): source-faithful conductor (base_color
        # once, no metal-preset double-multiply) + microfacet alpha = r². Applied to the
        # band carrier only; render_scene.xml stays the source-r GT for property maps.
        cc, ca = apply_contract_to_subtree(vis, tex_dir=nir_dir.parent / "roughness_sq")
        apply_contract_to_subtree(nir, tex_dir=nir_dir.parent / "roughness_sq")
        contract_conductors += cc; contract_alpha += ca

        mid = bsdf2mat.get(bid)
        canon = mat_by_id.get(mid) if mid else None
        oc = canon.get("optical_class") if canon else None
        pmat, _ = physical_material_for(mid, oc) if mid else (None, None)
        info = nir_reflectance(pmat, band) if pmat else {"albedo_channel": False}
        if pmat and info.get("albedo_channel") and _swap_diffuse_to_nir(nir, pmat, band, nir_dir):
            nir_swapped += 1
        elif not (info.get("albedo_channel")):
            metal_glass += 1   # conductor/dielectric: NIR ~= visible (Fresnel kept)
        else:
            unresolved += 1

        # reset the shared bsdf id into a band-selecting blendbsdf
        for c in list(b):
            b.remove(c)
        b.set("type", "blendbsdf")
        ET.SubElement(b, "float", {"name": "weight", "value": "0"})  # 0 = visible band
        b.append(vis)
        b.append(nir)
        wrapped += 1

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_path, encoding="unicode")
    summary = {
        "band": band, "materials_wrapped": wrapped, "nir_albedo_swapped": nir_swapped,
        "metal_glass_fresnel_kept": metal_glass, "unresolved": unresolved,
        "measured_bsdf_banded": measured, "nir_flash": bool(nir_flash),
        "contract_conductors_source_faithful": contract_conductors // 2,
        "contract_alpha_r2": contract_alpha // 2,
        "xml": str(out_path), "nir_dir": str(nir_dir),
    }
    (out_path.parent / "band_build.json").write_text(json.dumps(summary, indent=2))
    return summary
