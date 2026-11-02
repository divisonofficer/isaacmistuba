"""Render fixed camera poses of an adapted lit blend on the CPU, deterministically, so two blends can be compared pixel by pixel.

    blender --background ADAPTED.blend --python cpu_view_render.py -- --views views.json --out-dir DIR [--width 360 --height 270 --spp 24]

views.json: [{"name": "hover0", "camera_to_world": [[4x4, Blender: -Z forward, +Y up]], "hfov_deg": 63.2}, ...]
Fixed seed, no adaptive sampling, no denoiser, no compositor: the Combined pass of the same scene gives the same pixels, whatever the
thread count. Not the production path (that refuses the CPU on purpose); it only has to show that two blends render alike.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import bpy  # type: ignore
from mathutils import Matrix  # type: ignore


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser()
    ap.add_argument("--views", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--width", type=int, default=360)
    ap.add_argument("--height", type=int, default=270)
    ap.add_argument("--spp", type=int, default=24)
    ap.add_argument("--threads", type=int, default=8)
    a = ap.parse_args(argv)
    scene = bpy.context.scene
    cam = scene.camera or next(o for o in scene.objects if o.type == "CAMERA")
    scene.camera = cam
    scene.render.engine = "CYCLES"
    c = scene.cycles
    c.device, c.samples, c.seed = "CPU", a.spp, 0
    c.use_animated_seed = c.use_adaptive_sampling = c.use_denoising = False
    scene.use_nodes = False
    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = a.width, a.height, 100
    r.threads_mode, r.threads = "FIXED", a.threads
    r.use_persistent_data = False
    r.image_settings.file_format, r.image_settings.color_depth, r.image_settings.color_mode = "OPEN_EXR", "32", "RGB"
    os.makedirs(a.out_dir, exist_ok=True)
    timing = {}
    for v in json.load(open(a.views)):
        cam.matrix_world = Matrix(v["camera_to_world"])
        cam.data.sensor_fit = "HORIZONTAL"
        cam.data.angle_x = math.radians(v["hfov_deg"])
        r.filepath = os.path.join(a.out_dir, v["name"] + ".exr")
        t = time.time()
        bpy.ops.render.render(write_still=True)
        timing[v["name"]] = round(time.time() - t, 1)
    print("CPUVIEWS " + json.dumps({"blend": bpy.data.filepath, "views": timing, "spp": a.spp, "size": [a.width, a.height]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
