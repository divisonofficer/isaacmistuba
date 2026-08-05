#!/usr/bin/env python3
"""Replace the kitchen report's AOV-based property maps (roughness/metallic/normal/
albedo) with clean primary-ray ray_intersect extractions.

The `aov` integrator on this build injects spp-proportional vertical-stripe artifacts
into every AOV channel (proven on a bare plane: depth is clean at spp=1, comb-striped at
spp=4096). Property maps are not light transport, so they are extracted directly via
scene.ray_intersect() (material_pipeline.dataset_render) — no integrator, no spp, no
stripe. Values/provenance come from material_canonical.json.

Writes vp{i}_{nid}_{albedo,map_roughness,map_metallic,map_normal}.png into the report
image dir, overwriting the striped versions. Other modalities (rgb/nir path renders,
dop/aolp) are left untouched.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image

REPO = Path(__file__).resolve().parents[1]
for m in ("robomituba_bridge", "mitsuba_converter", "navigation_dataset"):
    sys.path.insert(0, str(REPO / "modules" / m / "src"))
sys.path.insert(0, str(REPO / "tools"))

from render_kitchen_multimodal import cam_for, EYE_H            # noqa: E402
from mitsuba_converter.material_pipeline import render_property_maps  # noqa: E402

SCENES = REPO / "out/opticalnav/opticalnav-v0.2/scenes"


def _srgb(lin: np.ndarray) -> np.ndarray:
    return np.clip(lin, 0, 1) ** (1 / 2.2)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scene-id", default="infinigen_single_room_kitchen_20260730")
    ap.add_argument("--viewpoints", default="vp_000005@180,vp_000009@180,vp_000016@240,vp_000012@180")
    ap.add_argument("--out", default="dev_report/images/kitchen_multimodal_2026-07-31")
    ap.add_argument("--width", type=int, default=640)
    ap.add_argument("--height", type=int, default=480)
    ap.add_argument("--fov", type=float, default=60.0)
    ap.add_argument("--subpixel", type=int, default=2)
    ap.add_argument("--index-base", type=int, default=0)
    a = ap.parse_args()

    scene_dir = SCENES / a.scene_id
    xml = scene_dir / "render_scene.xml"
    canonical = json.loads((scene_dir / "material_canonical.json").read_text())
    graph = json.loads((scene_dir / "viewpoint_graph.json").read_text())
    byid = {n["node_id"]: n for n in graph["nodes"]}
    out = REPO / a.out
    out.mkdir(parents=True, exist_ok=True)

    for k, spec in enumerate(a.viewpoints.split(",")):
        nid, _, yaw_s = spec.partition("@")
        nid = nid.strip(); yaw = math.radians(float(yaw_s or 0))
        node = byid[nid]
        px, py, _z = node["position"]
        target = (float(px) + math.sin(yaw), EYE_H * 0.9, float(py) + math.cos(yaw))
        cam = cam_for(node, target)
        vi = a.index_base + k
        print(f"[prop] viewpoint {vi} {nid}@{yaw_s} …", flush=True)
        maps = render_property_maps(str(xml), cam, a.fov, canonical,
                                    width=a.width, height=a.height, subpixel=a.subpixel)
        valid = maps["valid"]
        # albedo (visible base color): linear -> sRGB; invalid -> black
        bc = _srgb(maps["base_color"]) * maps["base_color_valid"][..., None]
        Image.fromarray((bc * 255).astype(np.uint8)).save(out / f"vp{vi}_{nid}_albedo.png")
        # roughness / metallic: gray, meaningful value; invalid -> 0
        for key, pv in (("roughness", "roughness_valid"), ("metallic", "metallic_valid")):
            g = np.clip(maps[key], 0, 1) * maps[pv]
            Image.fromarray((g * 255).astype(np.uint8)).save(out / f"vp{vi}_{nid}_map_{key}.png")
        # normal: world shading normal (n+1)/2; background (no hit) -> neutral 0.5,0.5,1
        n = maps["sh_normal"].copy()
        nn = ((n * 0.5 + 0.5))
        nn[~valid] = [0.5, 0.5, 1.0]
        Image.fromarray((np.clip(nn, 0, 1) * 255).astype(np.uint8)).save(out / f"vp{vi}_{nid}_map_normal.png")
        rc = len(maps["region_legend"])
        print(f"       regions={rc} rough_valid={maps['roughness_valid'].mean():.2f} "
              f"metal_valid={maps['metallic_valid'].mean():.2f}", flush=True)
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
