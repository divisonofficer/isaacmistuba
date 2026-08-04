#!/usr/bin/env python3
"""Kitchen QA via the UNIFIED discrete-band Stokes carrier.

Replaces the old 3-separate-passes harness (RGB passive · pseudo-NIR-albedo-swap flash ·
polar) with the unified pipeline: ONE band carrier scene (material_pipeline.spectral_band
wraps every material into blendbsdf(weight, __vis, __nir)) is loaded once under
cuda_ad_rgb_polarized; per viewpoint we flip the per-material band weight (0 = visible,
1 = NIR) via mi.traverse params — no reload — and render Stokes, giving RGB, NIR and
DoP/AoLP for both bands from the SAME BSDF + physical params (only the diffuse albedo
differs per band: __nir carries the hybrid NIR reflectance). Metals/glass keep their
Fresnel, and both bands share the same passive lighting + max_depth 8, so glass transmits
and metal reflects consistently — no flash / max_depth artifacts.

    LD_LIBRARY_PATH=/home/jinnyeong/driver-dist:/usr/lib/wsl/lib \
    PYTHONPATH=build/mitsuba3-optix7/python python tools/render_kitchen_unified.py
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
for m in ("robomituba_bridge", "mitsuba_converter", "navigation_dataset"):
    sys.path.insert(0, str(REPO / "modules" / m / "src"))
sys.path.insert(0, str(REPO / "tools"))

from render_kitchen_multimodal import cam_for, EYE_H, aolp_to_rgb, save_png  # noqa: E402
from mitsuba_converter.multimodal import camera_to_world_to_lookat  # noqa: E402
from mitsuba_converter.material_pipeline.spectral_band import build_band_scene  # noqa: E402

SCENES = REPO / "out/opticalnav/opticalnav-v0.2/scenes"
VARIANT = "cuda_ad_rgb_polarized"
_LUM = np.array([0.2126, 0.7152, 0.0722], np.float32)
WEIGHT_RE = re.compile(r"^.*\.weight\.value$")
BAND_WEIGHT = {"visible": 0.0, "nir": 1.0}


def stokes(arr: np.ndarray) -> dict:
    s0_rgb = arr[:, :, 3:6].astype(np.float32)
    S0 = np.clip((s0_rgb * _LUM).sum(2), 1e-8, None)
    S1 = (arr[:, :, 6:9] * _LUM).sum(2)
    S2 = (arr[:, :, 9:12] * _LUM).sum(2)
    dolp = np.clip(np.sqrt(S1 * S1 + S2 * S2) / S0, 0, 1)
    aolp = np.degrees(0.5 * np.arctan2(S2, S1))
    return {"s0_rgb": s0_rgb, "S0": S0, "dolp": dolp.astype(np.float32),
            "aolp": np.nan_to_num(aolp).astype(np.float32)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-id", default="infinigen_single_room_kitchen_20260730")
    ap.add_argument("--viewpoints", default="vp_000005@180,vp_000009@180,vp_000016@240,vp_000012@180")
    ap.add_argument("--out", default="dev_report/images/kitchen_multimodal_2026-07-31")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fov", type=float, default=60.0)
    ap.add_argument("--spp", type=int, default=256)
    ap.add_argument("--band", type=int, default=854)
    ap.add_argument("--rebuild", action="store_true", help="rebuild the band carrier scene")
    ap.add_argument("--index-base", type=int, default=0)
    a = ap.parse_args()

    import mitsuba as mi
    mi.set_variant(VARIANT)

    scene_dir = SCENES / a.scene_id
    band_xml = scene_dir / "scene_band.xml"
    if a.rebuild or not band_xml.is_file():
        canonical = json.loads((scene_dir / "material_canonical.json").read_text())
        summ = build_band_scene(scene_dir / "render_scene.xml", canonical, band_xml, band=a.band)
        print(f"[band] built {band_xml.name}: {json.dumps(summ)}", flush=True)

    graph = json.loads((scene_dir / "viewpoint_graph.json").read_text())
    byid = {n["node_id"]: n for n in graph["nodes"]}
    out = REPO / a.out
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    scene = mi.load_file(str(band_xml))
    params = mi.traverse(scene)
    wkeys = [k for k in params.keys() if WEIGHT_RE.match(k)]
    cam_key = next(k for k in params.keys() if k.endswith(".to_world"))
    fov_key = next((k for k in params.keys() if k.endswith(".x_fov")), None)
    print(f"[band] loaded {time.time()-t0:.1f}s · {len(wkeys)} band weights · cam={cam_key}", flush=True)

    for k, spec in enumerate(a.viewpoints.split(",")):
        nid, _, yaw_s = spec.partition("@")
        nid = nid.strip(); yaw = math.radians(float(yaw_s or 0))
        node = byid[nid]
        px, py, _z = node["position"]
        target = (float(px) + math.sin(yaw), EYE_H * 0.9, float(py) + math.cos(yaw))
        cam = cam_for(node, target)
        # cam_for is the render_modalities intermediate (matrix[:,2] = -forward); convert
        # to a Mitsuba sensor to_world via look_at, else the camera faces backward.
        o, t, u = camera_to_world_to_lookat(cam)
        params[cam_key] = mi.Transform4f(
            mi.ScalarTransform4f().look_at(origin=list(o), target=list(t), up=list(u)).matrix)
        if fov_key:
            params[fov_key] = float(a.fov)
        vi = a.index_base + k
        rec = {}
        for band in ("visible", "nir"):
            for wk in wkeys:
                params[wk] = mi.Float(BAND_WEIGHT[band])
            params.update()
            img = np.array(mi.render(scene, spp=a.spp, seed=7))
            m = stokes(img)
            if band == "visible":
                save_png(m["s0_rgb"], out / f"vp{vi}_{nid}_rgb.png", "linear_gamma")
                rec["rgb"] = m["s0_rgb"]
            else:
                v = m["S0"]; vn = np.clip(v / max(np.percentile(v, 99), 1e-6), 0, 1)
                Image.fromarray((vn ** (1 / 2.2) * 255).astype(np.uint8)).save(out / f"vp{vi}_{nid}_nir.png")
                # polarization from the NIR band (active-sensing DoP/AoLP)
                save_png(m["dolp"], out / f"vp{vi}_{nid}_dop.png", "dop")
                Image.fromarray((aolp_to_rgb(m["aolp"], m["dolp"]) * 255).astype(np.uint8)).save(
                    out / f"vp{vi}_{nid}_aolp.png")
            print(f"  [vp{vi} {nid} {band:7s}] S0 mean {m['S0'].mean():.3f} "
                  f"DoP {m['dolp'][m['S0']>0.05*m['S0'].max()].mean():.3f}", flush=True)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
