#!/usr/bin/env python3
"""Multimodal render of an imported OpticalNav scene at viewpoint-graph nodes.

Renders, per selected viewpoint (framed edge->center so the camera looks INTO the
room, not at a near wall), the modality set the kitchen-import experiment needs:

    passive  : rgb, albedo               (ambient only — RGB is a PASSIVE sensor)
    active   : active_nir_intensity      (rig NIR flash — NIR is ACTIVE), using the
                                          CONFIRMED pseudo-NIR albedo convention
    polar    : dop, aolp                 (rig polarized area flash)
    map-viz  : normal, roughness, metallic  (baked PBR maps shown unlit as emitters)

Recipe notes (validated 2026-07-31 on infinigen_single_room_kitchen_20260730):
  * Each modality GROUP is a SEPARATE render_modalities() call. Combining
    active_nir with dop/aolp double-loads the scene and trips a Dr.Jit AD
    "unknown variable" crash — keep them apart.
  * ROBOMITUBA_TEXTURE_MAX_RESOLUTION caps texture memory; the polarized (Stokes)
    variant on a ~10M-tri scene OOMs at full 1024 atlases. 256 fits comfortably.

Env: LD_LIBRARY_PATH=/home/jinnyeong/driver-dist:/usr/lib/wsl/lib
     PYTHONPATH=build/mitsuba3-optix7/python  python=~/miniconda3/envs/openusd_pip/bin/python
     ROBOMITUBA_TEXTURE_MAX_RESOLUTION=256
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
for _m in ("robomituba_bridge", "mitsuba_converter", "navigation_dataset"):
    p = REPO / "modules" / _m / "src"
    if p.is_dir() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

from mitsuba_converter.multimodal import render_modalities, RenderConfig, camera_to_world_from_lookat  # noqa: E402
from mitsuba_converter.nir_reflectance import (  # noqa: E402
    pseudo_nir_albedo, synthesize_nir_texture, physical_material_for, nir_reflectance)
from robomituba_bridge import AssistLightSpec, ActiveLightSpec  # noqa: E402


def _basecolor_to_pmat(scene_dir: Path, xml_path: Path) -> dict[str, str]:
    """Map each base_color texture filename -> physical_material class, resolved from
    the shader NAME (material_id) via nir_reflectance.physical_material_for. Chain:
    basecolor(in a bsdf) -> bsdf_ref -> shape -> material_id(shader) -> physical_material.
    Lets the hybrid NIR use the right class prior (μ_c, β_c) per surface."""
    out: dict[str, str] = {}
    try:
        idx = json.loads((scene_dir / "xml_scene_index.json").read_text())
        pol = json.loads((scene_dir / "render_scene_material_policy.json").read_text())
        sh2mat = {sp["shape_id"]: sp.get("material_id") for sp in pol.get("shape_policies", []) if sp.get("shape_id")}
        bsdf2mat = {}
        for sh in idx.get("shapes", []):
            ref, mid = sh.get("bsdf_ref"), sh2mat.get(sh.get("shape_id"))
            if ref and mid:
                bsdf2mat.setdefault(ref, mid)
        root = ET.parse(xml_path).getroot()
        for b in root.findall("bsdf"):
            mid = bsdf2mat.get(b.get("id"))
            if not mid:
                continue
            pmat, _ = physical_material_for(mid, None)
            for s in b.iter("string"):
                v = s.get("value", "")
                if s.get("name") == "filename" and v.endswith("_base_color.png"):
                    out.setdefault(v, pmat)
    except Exception as exc:  # noqa: BLE001
        print(f"[nir] class resolution failed ({exc}); falling back to pseudo", flush=True)
    return out


def nir_point_light(radiance: float = 400.0) -> ActiveLightSpec:
    """Rig-mounted NIR flash as a POINT (delta) emitter — matches real active-NIR
    hardware and casts crisp inter-object shadows. A delta light's DIRECT illumination
    is analytically connected (NEE) so it carries no area-sampling noise; the only MC
    noise is indirect GI fireflies, tamed by firefly clamp + a low path_max_depth.
    Mounted ~at the camera (headlamp) via base_pose @ mount."""
    return ActiveLightSpec(
        light_id="nir_point", enabled=True, emitter_type="point",
        mount={"xyz_m": [0.0, 0.1, 0.0], "rpy_deg": [0.0, 0.0, 0.0]},
        modalities=["nir"], spectrum_kind="rgb", rgb=[1.0, 1.0, 1.0],
        wavelength_nm=None, radiance=radiance, cutoff_angle_deg=0.0, beam_width_deg=0.0,
        area_size_m=0.1, polarized=False, polarizer_angle_deg=0.0, extras={})

EYE_H = 1.2   # eye height (m); mount in the scene rig is ~1.0, raised for framing


# --------------------------------------------------------------- viewpoints -- #
def pick_viewpoints(graph: dict, k: int) -> list[dict]:
    """Choose k nodes spread across the room; each looks toward the room centroid
    (edge->center) so the camera frames the interior, not a near wall."""
    nodes = graph["nodes"]
    pos = np.array([n["position"] for n in nodes], float)
    cx, cz = pos[:, 0].mean(), pos[:, 1].mean()
    d = ((pos[:, 0] - cx) ** 2 + (pos[:, 1] - cz) ** 2) ** 0.5
    order = list(np.argsort(-d))            # farthest-from-center first
    chosen, seen = [], []
    for i in order:
        p = pos[i]
        if any(((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2) ** 0.5 < 0.8 for q in seen):
            continue                        # spatial spread
        seen.append(p)
        chosen.append({"node": nodes[i], "target": (float(cx), EYE_H * 0.85, float(cz))})
        if len(chosen) >= k:
            break
    return chosen


def cam_for(node: dict, target: tuple) -> np.ndarray:
    px, py, _ = node["position"]
    o = [float(px), EYE_H, float(py)]
    return np.asarray(camera_to_world_from_lookat(o, list(target), [0, 1, 0]).reshape(4, 4), np.float32)


def select_viewpoints_by_preview(xml: Path, graph: dict, k: int, headings=(0, 60, 120, 180, 240, 300),
                                  width=160, height=120, spp=8) -> list[dict]:
    """Pick k (node, heading) framings that actually SHOW the room, not a near wall.
    Renders a cheap RGB preview for each candidate (node × a few headings, reusing the
    resident scene) and scores it by content = spatial std × lit-fraction. A blank wall
    scores low (flat + partly unlit); a view down the room with objects scores high.
    Returns the top-k spatially-diverse winners, each aiming ALONG its best heading."""
    import math as _m
    nodes = graph["nodes"]
    pos = np.array([n["position"] for n in nodes], float)
    cx, cz = pos[:, 0].mean(), pos[:, 1].mean()
    cfg = RenderConfig(); cfg.width = width; cfg.height = height
    cfg.path_spp = spp; cfg.aov_spp = spp
    scored = []
    for n in nodes:
        px, py, _ = n["position"]
        best = None
        for yaw in headings:
            a = _m.radians(yaw)
            o = [float(px), EYE_H, float(py)]
            t = [o[0] + _m.sin(a), EYE_H * 0.9, o[2] + _m.cos(a)]
            try:
                img = np.asarray(render_group(xml, np.asarray(
                    camera_to_world_from_lookat(o, t, [0, 1, 0]).reshape(4, 4), np.float32),
                    60.0, ["rgb"], cfg, tex_cap=None)["rgb"].array)
            except Exception:
                continue
            lit = float((img.mean(-1) > 0.02).mean())
            score = float(img.std()) * lit
            if best is None or score > best[0]:
                best = (score, yaw, tuple(t))
        if best:
            scored.append((best[0], n, best[1], best[2]))
            print(f"  preview {n['node_id']}: best yaw={best[1]} score={best[0]:.4f}", flush=True)
    scored.sort(key=lambda x: -x[0])
    chosen, seen = [], []
    for score, n, yaw, target in scored:
        p = np.array(n["position"][:2])
        if any(np.hypot(*(p - q)) < 1.2 for q in seen):
            continue
        seen.append(p)
        chosen.append({"node": n, "target": target, "yaw": yaw, "score": score})
        if len(chosen) >= k:
            break
    return chosen


# ------------------------------------------------------- material variants --- #
def _iter_basecolor_filenames(root: ET.Element):
    """Yield (string_element) nodes whose value is a *_base_color.png used as a
    diffuse/specular reflectance texture — the visible albedo maps."""
    for tex in root.iter("texture"):
        name = tex.get("name")
        if name not in ("diffuse_reflectance", "specular_reflectance"):
            continue
        for s in tex.findall("string"):
            if s.get("name") == "filename" and str(s.get("value", "")).endswith("_base_color.png"):
                yield s


def make_nir_albedo_maps(xml_path: Path, out_dir: Path, mode: str = "hybrid",
                         blur: float = 1.0) -> dict[str, str]:
    """For every base_color.png referenced as albedo, write a single-channel NIR albedo
    map and return {orig -> nir}. `mode`:
      hybrid  = class prior μ_c + standardised RGB structure (nir_reflectance.
                synthesize_nir_texture); RGB supplies only LOCAL texture, the measured
                class prior sets the mean/range — physical mean + texture, not flat.
                Falls back to pseudo when the surface class can't be resolved or is
                metal/glass (albedo not a diffuse channel).
      pseudo  = max(rgb,1-rgb)·[.229,.587,.114] (RGB heuristic; V-curve amplifies
                mid-gray micro-variation, hence the light blur).
      constant= flat class-prior scalar (physics but no texture)."""
    from PIL import ImageFilter
    out_dir.mkdir(parents=True, exist_ok=True)
    root = ET.parse(xml_path).getroot()
    pmat_by_src = _basecolor_to_pmat(xml_path.parent, xml_path) if mode in ("hybrid", "constant") else {}
    mapping: dict[str, str] = {}
    for s in _iter_basecolor_filenames(root):
        src = s.get("value")
        if src in mapping:
            continue
        dst = str(out_dir / (Path(src).stem + f".nir_{mode}.png"))
        if not Path(dst).is_file():
            rgb = np.asarray(Image.open(src).convert("RGB"), np.float32) / 255.0
            lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)  # sRGB->linear
            nir = None
            pmat = pmat_by_src.get(src)
            if mode in ("hybrid", "constant") and pmat:
                info = nir_reflectance(pmat, 854)
                if info["albedo_channel"]:
                    if mode == "constant":
                        nir = np.full(lin.shape[:2], float(info["mean"]), np.float32)
                    else:
                        nir = synthesize_nir_texture(lin, pmat, 854)
            if nir is None:                                    # unresolved/metal/glass -> pseudo
                nir = pseudo_nir_albedo(lin)
                img = Image.fromarray((np.clip(nir, 0, 1) * 255).astype(np.uint8))
                if blur > 0:
                    img = img.filter(ImageFilter.GaussianBlur(radius=float(blur)))
            else:
                img = Image.fromarray((np.clip(nir, 0, 1) * 255).astype(np.uint8))
            img.save(dst)
        mapping[src] = dst
    return mapping


def write_variant_xml(xml_path: Path, out_path: Path, filename_swaps: dict[str, str]) -> Path:
    """Copy the scene XML swapping texture filenames per `filename_swaps`."""
    tree = ET.parse(xml_path)
    for s in tree.getroot().iter("string"):
        if s.get("name") == "filename" and s.get("value") in filename_swaps:
            s.set("value", filename_swaps[s.get("value")])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_path, encoding="unicode")
    return out_path


def write_mapviz_xml(xml_path: Path, out_path: Path, channel: str) -> Path | None:
    """EXACT map-visualization: every shape becomes a self-emitting `area` light whose
    radiance IS its baked `channel` map, so the render reads back the map value
    UNLIT (occlusion/shading independent — a diffuse+lighting readout darkens interior
    surfaces even where roughness≈0.75). Materials that carry no map for this channel
    fall back to their true flat value, never black:
        roughness -> scalar `alpha` (or 0.5)   normal -> neutral (0.5,0.5,1)
        metallic  -> 1.0 if a pure conductor, else ~0 (tiny epsilon so the area
                     emitter keeps importance-sampling mass; a literal 0 crashes it).
    Returns None if nothing carries this channel."""
    suffix = {"albedo": "_base_color.png", "roughness": "_roughness.png",
              "normal": "_normal.png", "metallic": "_metallic.png"}[channel]
    tree = ET.parse(xml_path)
    root = tree.getroot()
    # bsdf id -> (map filename | None, scalar alpha | None, is_metal)
    info: dict[str, tuple] = {}
    for b in root.findall("bsdf"):
        bid = b.get("id")
        if not bid:
            continue
        fn = None
        for s in b.iter("string"):
            if s.get("name") == "filename" and str(s.get("value", "")).endswith(suffix):
                fn = s.get("value"); break
        alpha = None
        for fl in b.iter("float"):
            if fl.get("name") == "alpha":
                try:
                    alpha = float(fl.get("value"))
                except (TypeError, ValueError):
                    pass
                break
        is_metal = any(x.get("type") in ("conductor", "roughconductor") for x in b.iter("bsdf"))
        info[bid] = (fn, alpha, is_metal)
    for b in list(root.findall("bsdf")):
        root.remove(b)

    def flat_rgb(channel, alpha, is_metal) -> str:
        if channel == "normal":
            return "0.5 0.5 1.0"                       # neutral tangent-space normal
        if channel == "roughness":
            return f"{alpha:.4f} {alpha:.4f} {alpha:.4f}" if alpha is not None else "0.5 0.5 0.5"
        if channel == "metallic":
            return "1 1 1" if is_metal else "0.0 0.0 0.0"
        return "0.0 0.0 0.0"

    # Every shape becomes a plain diffuse whose reflectance IS the map; the render
    # reads it back with the `albedo` AOV (lighting/occlusion independent, and no
    # area emitters -> avoids the OptiX shader-binding-table blow-up that all-emitter
    # scenes hit at 454 lights). Scene emitters are left intact; the AOV ignores them.
    n = 0
    for shape in root.findall("shape"):
        ref = shape.find("ref")
        fn, alpha, is_metal = info.get(ref.get("id"), (None, None, False)) if ref is not None else (None, None, False)
        if ref is not None:
            shape.remove(ref)
        for old in list(shape.findall("emitter")):   # drop area-light shapes' emission
            shape.remove(old)
        bsdf = ET.SubElement(shape, "bsdf", type="diffuse")
        if fn is not None:
            tex = ET.SubElement(bsdf, "texture", attrib={"name": "reflectance", "type": "bitmap"})
            ET.SubElement(tex, "string", attrib={"name": "filename", "value": fn})
            ET.SubElement(tex, "boolean", attrib={"name": "raw", "value": "true"})
            n += 1
        else:
            ET.SubElement(bsdf, "rgb", attrib={"name": "reflectance", "value": flat_rgb(channel, alpha, is_metal)})
    if n == 0:
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree.write(out_path, encoding="unicode")
    return out_path


def render_normal_aov(xml_path: Path, origin, target, fov: float, w: int, h: int, spp: int,
                      out_path: Path) -> None:
    """Render the world-space sh_normal AOV in an ISOLATED subprocess.

    A direct mi.load_file/render mixed with render_modalities in the same long-lived
    process segfaults on the 2nd viewpoint (jit/OptiX state clash), so each normal
    render runs in a fresh interpreter via the `--normal-worker` mode below."""
    import subprocess
    args = [sys.executable, str(Path(__file__).resolve()), "--normal-worker",
            str(xml_path), ",".join(f"{v}" for v in origin), ",".join(f"{v}" for v in target),
            f"{fov}", str(w), str(h), str(spp), str(out_path)]
    subprocess.run(args, check=True, env=os.environ.copy())


def _normal_aov_worker(xml_path: Path, origin, target, fov: float, w: int, h: int, spp: int,
                       out_path: Path) -> None:
    """The actual sh_normal AOV render (runs in the isolated subprocess). EVERY polygon
    shows its real view-appropriate normal — geometric where no normal map, perturbed
    where one exists. measured_polarized BSDFs (need daemon staging to load directly)
    are swapped to diffuse; only geometry + surviving normalmap wrappers matter here."""
    import mitsuba as mi
    mi.set_variant("cuda_ad_rgb_polarized")
    tree = ET.parse(xml_path)
    root = tree.getroot()
    for it in list(root.findall("integrator")):
        root.remove(it)
    aov = ET.Element("integrator", type="aov")
    ET.SubElement(aov, "string", {"name": "aovs", "value": "nn:sh_normal"})
    nested = ET.SubElement(aov, "integrator", type="path")
    ET.SubElement(nested, "integer", {"name": "max_depth", "value": "2"})
    root.insert(0, aov)
    for b in root.iter("bsdf"):
        if str(b.get("type", "")).startswith("measured"):
            for ch in list(b):
                b.remove(ch)
            b.set("type", "diffuse")
    s = root.find("sensor")
    for c in list(s):
        if c.tag == "float" and c.get("name") == "fov":
            c.set("value", f"{fov}")
        if c.tag == "transform":
            for lk in list(c):
                c.remove(lk)
            ET.SubElement(c, "lookat", {"origin": " ".join(f"{v}" for v in origin),
                                        "target": " ".join(f"{v}" for v in target), "up": "0 1 0"})
        if c.tag == "film":
            for f in c.findall("integer"):
                if f.get("name") == "width":
                    f.set("value", str(w))
                if f.get("name") == "height":
                    f.set("value", str(h))
        if c.tag == "sampler":
            for f in c.findall("integer"):
                if f.get("name") == "sample_count":
                    f.set("value", str(spp))
    tmp = out_path.parent / "_variants" / "scene_normal_aov.xml"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tree.write(tmp, encoding="unicode")
    img = np.array(mi.render(mi.load_file(str(tmp))))
    nrm = img[..., -3:]
    nn = nrm / (np.linalg.norm(nrm, axis=-1, keepdims=True) + 1e-9)
    enc = np.clip(nn * 0.5 + 0.5, 0, 1)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((enc * 255).astype(np.uint8)).save(out_path)


# ------------------------------------------------------- AoLP colormap ------ #
def _hsv_to_rgb(h: np.ndarray, s: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Vectorised HSV->RGB (all inputs [0,1], same shape). No matplotlib dependency."""
    i = np.floor(h * 6.0).astype(int)
    f = h * 6.0 - i
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    i = i % 6
    r = np.choose(i, [v, q, p, p, t, v])
    g = np.choose(i, [t, v, v, q, p, p])
    b = np.choose(i, [p, p, t, v, v, q])
    return np.clip(np.stack([r, g, b], axis=-1), 0, 1)


def aolp_to_rgb(aolp_deg: np.ndarray, dop: np.ndarray | None = None) -> np.ndarray:
    """Colorise AoLP for debugging: HUE = polarization angle (cyclic, π-periodic so
    0°≡180°), so distinct angles read as distinct colors instead of a flat gray ramp.
    SATURATION = DoLP (auto-scaled): strongly-polarized pixels are vivid-colored by
    their angle, weakly-polarized ones fade to WHITE (not black — so the angle field
    stays visible even in low-polarization views, while colour still flags where the
    signal is real). VALUE is kept at 1 so nothing blacks out."""
    ang = np.nan_to_num(np.asarray(aolp_deg, np.float32), nan=0.0)   # S0≈0 -> undefined
    ang = np.clip(ang, 0, 180)
    if ang.ndim == 3:
        ang = ang[..., 0]
    h = ang / 180.0
    v = np.ones_like(h)
    if dop is not None:
        d = np.nan_to_num(np.asarray(dop, np.float32), nan=0.0)      # DoLP=0/0 at black px
        if d.ndim == 3:
            d = d[..., 0]
        ref = max(float(np.percentile(d, 98)), 0.05)                 # floor: don't over-amplify
        s = np.clip(d / ref, 0, 1)
    else:
        s = np.ones_like(h)
    return _hsv_to_rgb(h, s, v)


# ------------------------------------------------------------------ render --- #
def _tonemap(a: np.ndarray, mode: str) -> np.ndarray:
    a = np.asarray(a, np.float32)
    if a.ndim == 2:
        a = np.repeat(a[..., None], 3, axis=2)
    a = a[..., :3]
    if mode == "linear_gamma":
        p99 = max(float(np.percentile(a, 99)), 1e-6)
        return np.clip((a / p99), 0, 1) ** (1 / 2.2)
    if mode == "gray":
        p99 = max(float(np.percentile(a, 99)), 1e-6)
        return np.clip(a / p99, 0, 1)
    if mode == "map":      # direct linear readout of a [0,1] map value (no gamma/norm)
        return np.clip(a, 0, 1)
    if mode == "dop":     # red-black
        v = np.clip(a[..., 0:1] if a.shape[2] else a, 0, 1)
        return np.concatenate([v, np.zeros_like(v), np.zeros_like(v)], axis=2)
    if mode == "aolp":    # 0..180 deg -> hue-ish gray
        return np.clip(a / 180.0, 0, 1)
    return np.clip(a, 0, 1)


def save_png(arr: np.ndarray, path: Path, mode: str):
    img = _tonemap(arr, mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((img * 255).astype(np.uint8)).save(path)


def render_group(scene_xml, cam, fov, mods, cfg, assist=None, tex_cap: int | None = None,
                 active_lights=(), base_pose=None):
    """Render one modality group. `tex_cap` (px) is applied ONLY for the memory-heavy
    passes (polarized Stokes / active-NIR): the RGB base-path staging audits texture
    profiles with fail_on_gt_profile and rejects a partially-capped scene (299 refs
    resist downsampling), so passive/map-viz run uncapped (1x RGB memory fits)."""
    key = "ROBOMITUBA_TEXTURE_MAX_RESOLUTION"
    prev = os.environ.get(key)
    if tex_cap:
        os.environ[key] = str(tex_cap)
    else:
        os.environ.pop(key, None)
    try:
        return render_modalities(str(scene_xml), cam, fov, mods, config=cfg, variant="auto",
                                 assist_light=assist, active_lights=active_lights,
                                 base_pose=base_pose).results
    finally:
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-id", default="infinigen_single_room_kitchen_20260730")
    ap.add_argument("--dataset", default="out/opticalnav/opticalnav-v0.2")
    ap.add_argument("--views", type=int, default=3)
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--spp", type=int, default=96,
                    help="path_spp for the RGB/polar path renders (converges fast under "
                         "the scene's own lighting; 256 is already clean).")
    ap.add_argument("--aov-spp", type=int, default=None,
                    help="supersampling for the AOV readouts (visible/NIR albedo, "
                         "roughness/metallic mapviz). Higher = less texture-minification "
                         "aliasing on distant surfaces. Defaults to --spp if unset.")
    ap.add_argument("--nir-spp", type=int, default=4096,
                    help="path_spp for the active-NIR point-flash render — match RGB-grade "
                         "convergence (delta flash + distance falloff is noisier than "
                         "passive/emitter passes, so this is the heaviest pass).")
    ap.add_argument("--fov", type=float, default=60.0)
    ap.add_argument("--out", default="dev_report/images/kitchen_multimodal_2026-07-31")
    ap.add_argument("--groups", nargs="*",
                    default=["passive", "active_nir", "polar", "mapviz"])
    ap.add_argument("--no-auto-select", action="store_true",
                    help="use the geometric farthest-node heuristic instead of the "
                         "content-scored preview selection")
    ap.add_argument("--viewpoints", default=None,
                    help="fixed 'node_id@yaw,node_id@yaw,...' to render EXACTLY these "
                         "framings — skips the preview selection (whose many renders "
                         "destabilise a later polarized pass in the same process).")
    ap.add_argument("--nir-mode", choices=["hybrid", "pseudo", "constant"], default="hybrid",
                    help="NIR albedo policy: hybrid(class prior μ + RGB structure), "
                         "pseudo(RGB heuristic), constant(flat class prior)")
    ap.add_argument("--index-base", type=int, default=0,
                    help="offset for the vp{N} filename index (patch a single view into "
                         "an existing set without renumbering, e.g. --index-base 2).")
    a = ap.parse_args()

    S = REPO / a.dataset / "scenes" / a.scene_id
    xml = S / "render_scene.xml"
    graph = json.loads((S / "viewpoint_graph.json").read_text())
    out = REPO / a.out
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_variants"

    # RenderConfig has NO `spp` field — path_spp(default 4096)/aov_spp(default 16)/
    # polar_spp are separate. Setting `cfg.spp` silently did nothing, so the AOV
    # passes (albedo, nir_albedo, roughness-mapviz) ran at aov_spp=16 and the texture
    # readout ALIASED into salt-and-pepper grain on minified (distant) textures, while
    # RGB was secretly at 4096. Drive all three from --spp so AOVs are anti-aliased.
    aov_spp = a.aov_spp if a.aov_spp is not None else a.spp
    cfg = RenderConfig(); cfg.width = a.width; cfg.height = a.height
    cfg.path_spp = a.spp; cfg.aov_spp = aov_spp; cfg.polar_spp = a.spp
    # NIR point-flash pass: clamp GI fireflies + cap bounce depth so the delta light's
    # clean direct illumination dominates (see nir_point_light docstring).
    cfg_nir = RenderConfig(); cfg_nir.width = a.width; cfg_nir.height = a.height
    cfg_nir.path_spp = a.nir_spp; cfg_nir.aov_spp = a.nir_spp
    cfg_nir.use_firefly_clamp = True; cfg_nir.path_max_depth = 3
    assist_flat = AssistLightSpec(mode="camera_aligned_rect", distance_m=0.18, size_world=[5.0, 3.6],
                                  spectrum_mode="mask_proxy", polarized=False,
                                  polarizer_angle_deg=0.0, extras={"radiance": 120.0})
    assist_pol = AssistLightSpec(mode="camera_aligned_rect", distance_m=0.18, size_world=[5.0, 3.6],
                                 spectrum_mode="mask_proxy", polarized=True,
                                 polarizer_angle_deg=0.0, extras={"radiance": 120.0})

    # pseudo-NIR variant XML (albedo -> pseudo-NIR grayscale) built once
    pseudo_xml = None
    if "active_nir" in a.groups:
        swaps = make_nir_albedo_maps(xml, tmp / f"nir_maps_{a.nir_mode}", mode=a.nir_mode)
        pseudo_xml = write_variant_xml(xml, tmp / f"scene_nir_{a.nir_mode}.xml", swaps)
        print(f"[nir] mode={a.nir_mode}: {len(swaps)} albedo maps -> NIR")

    if a.viewpoints:
        import math as _m
        byid = {n["node_id"]: n for n in graph["nodes"]}
        vps = []
        for spec in a.viewpoints.split(","):
            nid, _, yaw = spec.partition("@")
            n = byid[nid.strip()]; yaw = float(yaw or 0)
            px, py, _z = n["position"]; rad = _m.radians(yaw)
            vps.append({"node": n, "yaw": yaw,
                        "target": (float(px) + _m.sin(rad), EYE_H * 0.9, float(py) + _m.cos(rad))})
    elif a.no_auto_select:
        vps = pick_viewpoints(graph, a.views)
    else:
        print("[select] previewing viewpoints (content-scored)…", flush=True)
        vps = select_viewpoints_by_preview(xml, graph, a.views)
    print("[select] chosen:", [f"{v['node']['node_id']}@yaw{v.get('yaw','?')}" for v in vps], flush=True)
    # merge with prior images so a partial --groups re-run keeps earlier modalities.
    # Scan BOTH the prior manifest AND the images on disk (a crash can truncate the
    # manifest while the image files survive).
    _KIND2KEY = {"rgb": "rgb", "albedo": "albedo", "nir": "nir_active_pseudo", "dop": "dop",
                 "aolp": "aolp", "map_normal": "map_normal", "map_roughness": "map_roughness",
                 "map_metallic": "map_metallic"}
    prior_imgs: dict[str, dict] = {}
    mpath = out / "manifest.json"
    if mpath.is_file():
        try:
            for v in json.loads(mpath.read_text()).get("views", []):
                prior_imgs[v["node_id"]] = dict(v.get("images", {}))
        except Exception:
            pass
    for f in out.glob("vp*_*.png"):
        m = re.match(r"vp\d+_(vp_\d+)_(.+)\.png", f.name)
        if m and m.group(2) in _KIND2KEY:
            prior_imgs.setdefault(m.group(1), {}).setdefault(_KIND2KEY[m.group(2)], f.name)
    manifest = {"scene_id": a.scene_id, "views": [], "groups": a.groups,
                "spp": a.spp, "aov_spp": aov_spp, "nir_spp": a.nir_spp,
                "size": [a.width, a.height]}
    for _i, vp in enumerate(vps):
        vi = a.index_base + _i
        node = vp["node"]; nid = node["node_id"]
        cam = cam_for(node, vp["target"])
        print(f"\n=== viewpoint {vi} {nid} pos={node['position'][:2]} ===", flush=True)
        rec = {"index": vi, "node_id": nid, "position": node["position"],
               "images": dict(prior_imgs.get(nid, {}))}

        if "passive" in a.groups:
            r = render_group(xml, cam, a.fov, ["rgb", "albedo"], cfg, tex_cap=None)
            save_png(r["rgb"].array, out / f"vp{vi}_{nid}_rgb.png", "linear_gamma")
            save_png(r["albedo"].array, out / f"vp{vi}_{nid}_albedo.png", "linear_gamma")
            rec["images"]["rgb"] = f"vp{vi}_{nid}_rgb.png"
            rec["images"]["albedo"] = f"vp{vi}_{nid}_albedo.png"
            print("  [passive] rgb, albedo", flush=True)

        if "active_nir" in a.groups:
            r = render_group(pseudo_xml, cam, a.fov, ["active_nir_intensity"], cfg_nir, tex_cap=256,
                             active_lights=[nir_point_light()], base_pose=cam)   # rig NIR point flash
            save_png(r["active_nir_intensity"].array, out / f"vp{vi}_{nid}_nir.png", "gray")
            rec["images"]["nir_active_pseudo"] = f"vp{vi}_{nid}_nir.png"
            # pseudo-NIR ALBEDO (AOV): the NIR band's diffuse reflectance map itself,
            # shown next to the visible albedo AOV (lighting-independent readout).
            ra = render_group(pseudo_xml, cam, a.fov, ["albedo"], cfg, tex_cap=None)
            save_png(ra["albedo"].array, out / f"vp{vi}_{nid}_nir_albedo.png", "gray")
            rec["images"]["nir_pseudo_albedo"] = f"vp{vi}_{nid}_nir_albedo.png"
            print("  [active] nir (pseudo albedo) + nir albedo AOV", flush=True)

        if "polar" in a.groups:
            r = render_group(xml, cam, a.fov, ["dop", "aolp"], cfg, assist_pol, tex_cap=256)
            save_png(r["dop"].array, out / f"vp{vi}_{nid}_dop.png", "dop")
            # stash raw AoLP+DoLP so the colormap can be re-tuned without re-rendering
            raw = out / "_raw"; raw.mkdir(parents=True, exist_ok=True)
            np.save(raw / f"vp{vi}_{nid}_aolp.npy", np.asarray(r["aolp"].array, np.float32))
            np.save(raw / f"vp{vi}_{nid}_dop.npy", np.asarray(r["dop"].array, np.float32))
            aolp_rgb = aolp_to_rgb(r["aolp"].array, r["dop"].array)   # hue=angle, sat=DoLP
            (out / f"vp{vi}_{nid}_aolp.png").parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray((aolp_rgb * 255).astype(np.uint8)).save(out / f"vp{vi}_{nid}_aolp.png")
            rec["images"]["dop"] = f"vp{vi}_{nid}_dop.png"
            rec["images"]["aolp"] = f"vp{vi}_{nid}_aolp.png"
            print("  [polar] dop, aolp", flush=True)

        if "mapviz" in a.groups:
            # normal: world-space sh_normal AOV (every poly shows its real view normal,
            # geometric where no map, perturbed where a normal map exists).
            px, py, _ = node["position"]
            render_normal_aov(xml, (float(px), EYE_H, float(py)), vp["target"],
                              a.fov, a.width, a.height, max(16, a.spp // 4),
                              out / f"vp{vi}_{nid}_map_normal.png")
            rec["images"]["map_normal"] = f"vp{vi}_{nid}_map_normal.png"
            # roughness/metallic: baked material map read via albedo AOV (true value,
            # no-map -> scalar alpha / 0-or-1).
            for ch in ("roughness", "metallic"):
                vx = write_mapviz_xml(xml, tmp / f"scene_map_{ch}.xml", ch)
                if vx is None:
                    continue
                r = render_group(vx, cam, a.fov, ["albedo"], cfg, tex_cap=None)
                save_png(r["albedo"].array, out / f"vp{vi}_{nid}_map_{ch}.png", "map")
                rec["images"][f"map_{ch}"] = f"vp{vi}_{nid}_map_{ch}.png"
            print("  [mapviz] normal(AOV), roughness, metallic", flush=True)

        manifest["views"].append(rec)
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"\nwrote {out}/manifest.json  ({len(manifest['views'])} viewpoints)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "--normal-worker":
        _xml, _o, _t, _fov, _w, _h, _spp, _out = sys.argv[2:10]
        _normal_aov_worker(Path(_xml), tuple(float(x) for x in _o.split(",")),
                           tuple(float(x) for x in _t.split(",")), float(_fov),
                           int(_w), int(_h), int(_spp), Path(_out))
        raise SystemExit(0)
    raise SystemExit(main())
