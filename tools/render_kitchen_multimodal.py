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
from mitsuba_converter.nir_reflectance import pseudo_nir_albedo  # noqa: E402
from robomituba_bridge import AssistLightSpec  # noqa: E402

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


def make_pseudo_nir_maps(xml_path: Path, out_dir: Path, blur: float = 0.8) -> dict[str, str]:
    """For every base_color.png referenced as albedo, write a grayscale pseudo-NIR
    map (nir = max(rgb,1-rgb)*[.229,.587,.114]) and return {orig -> pseudo}.

    A light Gaussian `blur` is applied AFTER the pseudo transform: the pseudo V-curve
    is steepest at mid-gray, so it amplifies a matte wall's sub-pixel albedo micro-
    variation into salt-and-pepper speckle that reads as render noise (it is NOT —
    spp 128 and 4096 are pixel-identical). A ~0.8px blur removes that amplified micro-
    noise while preserving real texture structure. Set blur=0 to keep it raw."""
    from PIL import ImageFilter
    out_dir.mkdir(parents=True, exist_ok=True)
    root = ET.parse(xml_path).getroot()
    mapping: dict[str, str] = {}
    for s in _iter_basecolor_filenames(root):
        src = s.get("value")
        if src in mapping:
            continue
        dst = str(out_dir / (Path(src).stem + ".nirpseudo.png"))
        if not Path(dst).is_file():
            rgb = np.asarray(Image.open(src).convert("RGB"), np.float32) / 255.0
            # sRGB->linear for the pseudo formula, then back to 8-bit linear-ish gray
            lin = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
            nir = pseudo_nir_albedo(lin)
            img = Image.fromarray((np.clip(nir, 0, 1) * 255).astype(np.uint8))
            if blur > 0:
                img = img.filter(ImageFilter.GaussianBlur(radius=float(blur)))
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


def render_group(scene_xml, cam, fov, mods, cfg, assist=None, tex_cap: int | None = None):
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
                                 assist_light=assist).results
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
    ap.add_argument("--spp", type=int, default=96)
    ap.add_argument("--nir-spp", type=int, default=512,
                    help="higher spp for the active-NIR flash pass (small area flash + "
                         "distance falloff is noisier than passive/emitter passes)")
    ap.add_argument("--fov", type=float, default=60.0)
    ap.add_argument("--out", default="dev_report/images/kitchen_multimodal_2026-07-31")
    ap.add_argument("--groups", nargs="*",
                    default=["passive", "active_nir", "polar", "mapviz"])
    a = ap.parse_args()

    S = REPO / a.dataset / "scenes" / a.scene_id
    xml = S / "render_scene.xml"
    graph = json.loads((S / "viewpoint_graph.json").read_text())
    out = REPO / a.out
    out.mkdir(parents=True, exist_ok=True)
    tmp = out / "_variants"

    cfg = RenderConfig(); cfg.width = a.width; cfg.height = a.height; cfg.spp = a.spp
    cfg_nir = RenderConfig(); cfg_nir.width = a.width; cfg_nir.height = a.height; cfg_nir.spp = a.nir_spp
    assist_flat = AssistLightSpec(mode="camera_aligned_rect", distance_m=0.18, size_world=[5.0, 3.6],
                                  spectrum_mode="mask_proxy", polarized=False,
                                  polarizer_angle_deg=0.0, extras={"radiance": 120.0})
    assist_pol = AssistLightSpec(mode="camera_aligned_rect", distance_m=0.18, size_world=[5.0, 3.6],
                                 spectrum_mode="mask_proxy", polarized=True,
                                 polarizer_angle_deg=0.0, extras={"radiance": 120.0})

    # pseudo-NIR variant XML (albedo -> pseudo-NIR grayscale) built once
    pseudo_xml = None
    if "active_nir" in a.groups:
        swaps = make_pseudo_nir_maps(xml, tmp / "nir_maps")
        pseudo_xml = write_variant_xml(xml, tmp / "scene_pseudonir.xml", swaps)
        print(f"[pseudo-nir] {len(swaps)} albedo maps -> pseudo-NIR")

    vps = pick_viewpoints(graph, a.views)
    # merge with any prior manifest so a partial --groups re-run keeps earlier images
    prior_imgs: dict[str, dict] = {}
    mpath = out / "manifest.json"
    if mpath.is_file():
        try:
            for v in json.loads(mpath.read_text()).get("views", []):
                prior_imgs[v["node_id"]] = dict(v.get("images", {}))
        except Exception:
            pass
    manifest = {"scene_id": a.scene_id, "views": [], "groups": a.groups,
                "spp": a.spp, "nir_spp": a.nir_spp, "size": [a.width, a.height]}
    for vi, vp in enumerate(vps):
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
            r = render_group(pseudo_xml, cam, a.fov, ["active_nir_intensity"], cfg_nir, assist_flat, tex_cap=256)
            save_png(r["active_nir_intensity"].array, out / f"vp{vi}_{nid}_nir.png", "gray")
            rec["images"]["nir_active_pseudo"] = f"vp{vi}_{nid}_nir.png"
            print("  [active] nir (pseudo albedo)", flush=True)

        if "polar" in a.groups:
            r = render_group(xml, cam, a.fov, ["dop", "aolp"], cfg, assist_pol, tex_cap=256)
            save_png(r["dop"].array, out / f"vp{vi}_{nid}_dop.png", "dop")
            save_png(r["aolp"].array, out / f"vp{vi}_{nid}_aolp.png", "aolp")
            rec["images"]["dop"] = f"vp{vi}_{nid}_dop.png"
            rec["images"]["aolp"] = f"vp{vi}_{nid}_aolp.png"
            print("  [polar] dop, aolp", flush=True)

        if "mapviz" in a.groups:
            for ch, mode in (("normal", "gray"), ("roughness", "gray"), ("metallic", "gray")):
                vx = write_mapviz_xml(xml, tmp / f"scene_map_{ch}.xml", ch)
                if vx is None:
                    continue
                r = render_group(vx, cam, a.fov, ["albedo"], cfg, tex_cap=None)
                save_png(r["albedo"].array, out / f"vp{vi}_{nid}_map_{ch}.png", "map")
                rec["images"][f"map_{ch}"] = f"vp{vi}_{nid}_map_{ch}.png"
            print("  [mapviz] normal, roughness, metallic", flush=True)

        manifest["views"].append(rec)
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2))

    print(f"\nwrote {out}/manifest.json  ({len(manifest['views'])} viewpoints)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
