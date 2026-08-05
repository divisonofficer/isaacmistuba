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
from mitsuba_converter.material_pipeline.bsdf_contract import (
    apply_contract_to_subtree, force_analytic as _force_analytic_subtree,
)

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
    integrator: str = "path",
    drop_dielectric: bool = False,
    nir_flash: bool = False,
    nir_flash_half_m: float = 0.015,
    force_analytic: bool = True,
    polarized: bool = True,
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

    # Optionally REMOVE every dielectric (glass) object. A bright compact NIR flash makes
    # smooth dielectrics a high-risk caustic (firefly) source; this materializes a
    # "glass-free scenario" (glass assets not restored) whose observation is inherently
    # cleaner. A shape is glass if it references a top-level bsdf whose subtree contains a
    # dielectric (covers `dielectric` refs and blends-with-dielectric); emitter shapes
    # (area lights, the flash) are never dropped.
    dropped_dielectric = 0
    if drop_dielectric:
        _DT = {"dielectric", "roughdielectric", "thindielectric"}
        diel_ids = {b.get("id") for b in root.findall("bsdf")
                    if any(x.get("type") in _DT for x in b.iter("bsdf"))}
        diel_ids.discard(None)
        for sh in list(root.findall("shape")):
            if sh.find("emitter") is not None:
                continue
            is_diel = (any(x.get("type") in _DT for x in sh.iter("bsdf"))
                       or any(r.get("id") in diel_ids for r in sh.iter("ref")))
            if is_diel:
                root.remove(sh)
                dropped_dielectric += 1

    # A Stokes carrier: the unified runner reads S0..S3 from one render.
    #   integrator="path"   → global-illumination OBSERVATION pass (max_depth 8 so
    #                         multi-surface glass transmits; a low depth renders bottles
    #                         as opaque black). Fireflies/indirect are legitimate here —
    #                         this is what the sensor actually records.
    #   integrator="direct" → direct-illumination-only pass. No indirect paths at all, so
    #                         the flash-only response is firefly-free BY CONSTRUCTION — the
    #                         clean specular-recovery GT. (max_depth is ignored by `direct`.)
    for integ in root.findall("integrator"):
        root.remove(integ)
    inner_type = "direct" if integrator == "direct" else "path"
    if polarized:                                     # Stokes carrier: RGB/NIR + DoP/AoLP
        top_integ = ET.Element("integrator", {"type": "stokes"})
        inner = ET.SubElement(top_integ, "integrator", {"type": inner_type})
    else:                                             # no-polar: plain integrator, RGB/NIR only
        top_integ = inner = ET.Element("integrator", {"type": inner_type})
    if inner_type == "path":
        ET.SubElement(inner, "integer", {"name": "max_depth", "value": str(int(max_depth))})
    root.insert(0, top_integ)

    # rig NIR headlamp — a FINITE-AREA emitter (real LED/diffuser has size; an
    # infinitesimal `point` delta produces subpixel-specular / caustic fireflies that spp
    # barely removes). A camera-mounted rectangle (half-size ~1.5cm) whose emitting +Z
    # face points into the scene; band-gated by the runner (radiance 0 in visible, on in
    # NIR) and its to_world moved to the camera per view. One-sided → the camera behind it
    # does not see the emitter.
    if nir_flash:
        sh = ET.SubElement(root, "shape", {"type": "rectangle", "id": "nir_flash"})
        tr = ET.SubElement(sh, "transform", {"name": "to_world"})
        ET.SubElement(tr, "scale", {"value": f"{float(nir_flash_half_m):.5f}"})
        em = ET.SubElement(sh, "emitter", {"type": "area"})
        ET.SubElement(em, "rgb", {"name": "radiance", "value": "0 0 0"})  # off (visible)

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

        mid = bsdf2mat.get(bid)
        canon = mat_by_id.get(mid) if mid else None
        oc = canon.get("optical_class") if canon else None

        # pure analytic (3 BSDFs): measured pBRDF → pplastic, smooth conductor →
        # roughconductor — measured is an optional polar-accuracy anchor, not the default.
        if force_analytic:
            measured += _force_analytic_subtree(vis, canon) > 0
            _force_analytic_subtree(nir, canon)
        else:
            if _ensure_measured_bsdf_wavelength(vis, target_nm=_VISIBLE_NM):
                measured += 1
            _ensure_measured_bsdf_wavelength(nir, target_nm=band)

        # RENDER contract (material_contract §4): source-faithful conductor (base_color
        # once, no metal-preset double-multiply) + microfacet alpha = r². Applied to the
        # band carrier only; render_scene.xml stays the source-r GT for property maps.
        cc, ca = apply_contract_to_subtree(vis, tex_dir=nir_dir.parent / "roughness_sq")
        apply_contract_to_subtree(nir, tex_dir=nir_dir.parent / "roughness_sq")
        contract_conductors += cc; contract_alpha += ca

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
        "band": band, "integrator": inner_type, "dropped_dielectric": dropped_dielectric,
        "materials_wrapped": wrapped, "nir_albedo_swapped": nir_swapped,
        "metal_glass_fresnel_kept": metal_glass, "unresolved": unresolved,
        "measured_bsdf_banded": measured, "nir_flash": bool(nir_flash),
        "contract_conductors_source_faithful": contract_conductors // 2,
        "contract_alpha_r2": contract_alpha // 2,
        "force_analytic": bool(force_analytic), "polarized": bool(polarized),
        "xml": str(out_path), "nir_dir": str(nir_dir),
    }
    (out_path.parent / "band_build.json").write_text(json.dumps(summary, indent=2))
    return summary
