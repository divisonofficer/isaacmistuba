#!/usr/bin/env python3
"""Fine-grained stage timing for the observations-only IR render pass.

Renders a small handful of viewpoints through the exact same code path as
``apps/render_ir_dataset.py`` (imported directly, not reimplemented) and
records wall-clock timing per stage plus Dr.Jit GPU kernel time (via
``dr.kernel_history``) for each ``mi.render`` call. Used to tell apart
"GPU compute-bound" from "CPU/JIT/sync-bound" frames — see
dev_report/2026-08-07_ir_render_pipeline_profile.json for the last run.

Standalone diagnostic tool: does not touch the live render queue's output
directory, and does not modify render_ir_dataset.py's behavior.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
for module in ("robomituba_bridge", "mitsuba_converter", "navigation_dataset"):
    sys.path.insert(0, str(REPO_ROOT / "modules" / module / "src"))
sys.path.insert(0, str(REPO_ROOT / "apps"))

from mitsuba_converter.material_pipeline import build_band_scene  # noqa: E402
import render_ir_dataset as rid  # noqa: E402


def _render_profiled(scene, params, keys, camera, *, band, spp, seed, dr, mi, args_fov):
    stage = {}
    t0 = time.perf_counter()
    sensor_to_world, light_to_world = rid._render_rig_transforms(
        camera, offset_y_m=-0.10, area_half_m=None,
    )
    t1 = time.perf_counter()
    stage["camera_setup_s"] = t1 - t0

    params[keys["camera"]] = mi.Transform4f(sensor_to_world)
    if keys["fov"]:
        params[keys["fov"]] = float(args_fov)
    for key in keys["weights"]:
        params[key] = mi.Float(band)
    if keys["flash_tw"]:
        params[keys["flash_tw"]] = mi.Transform4f(light_to_world)
    t2 = time.perf_counter()
    stage["params_assign_s"] = t2 - t1

    dr.kernel_history_clear()
    with dr.scoped_set_flag(dr.JitFlag.KernelHistory):
        params.update()
        rid._sync_gpu()
        t3 = time.perf_counter()
        stage["params_update_s"] = t3 - t2

        image_tensor = mi.render(scene, spp=spp, seed=seed)
        rid._sync_gpu()
        t4 = time.perf_counter()
        stage["render_wall_s"] = t4 - t3

        hist = dr.kernel_history()
    kernels = [h for h in hist if str(h.get("type", "")).endswith("JIT") or "JIT" in str(h.get("type", ""))]
    stage["gpu_kernel_ms_total"] = sum(float(h.get("execution_time", 0.0)) for h in hist)
    stage["gpu_kernel_count"] = len(hist)
    stage["gpu_kernel_cache_misses"] = sum(1 for h in hist if not h.get("cache_hit", True))

    image = np.asarray(image_tensor)
    t5 = time.perf_counter()
    stage["device_to_host_s"] = t5 - t4
    stage["total_s"] = t5 - t0
    return image, stage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene-dir", type=Path, required=True)
    parser.add_argument("--viewpoints", required=True, help="comma-separated node@yaw list")
    parser.add_argument("--width", type=int, default=684)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--fov", type=float, default=60.0)
    parser.add_argument("--spp", type=int, default=4000)
    parser.add_argument("--subpixel", type=int, default=1)
    parser.add_argument("--band", type=int, default=854)
    parser.add_argument("--nir-cache-dir", type=Path, required=True)
    parser.add_argument("--scratch", type=Path, required=True)
    parser.add_argument("--gpu-cleanup-every-frame", action="store_true",
                         help="run _free_gpu() after every frame (matches --gpu-cleanup-interval 1)")
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()

    scene_dir = args.scene_dir.resolve()
    canonical = json.loads((scene_dir / "material_canonical.json").read_text())
    graph = json.loads((scene_dir / "viewpoint_graph.json").read_text())
    nodes = {row["node_id"]: row for row in graph["nodes"]}
    views = []
    for spec in args.viewpoints.split(","):
        node_id, sep, yaw_text = spec.strip().partition("@")
        yaw = float(yaw_text) if sep else 0.0
        views.append((node_id, yaw, rid._camera(nodes[node_id], yaw)))

    args.scratch.mkdir(parents=True, exist_ok=True)
    import mitsuba as mi
    import drjit as dr
    mi.set_variant("cuda_ad_spectral")

    passive_xml = args.scratch / "scene_band_passive.xml"
    flash_xml = args.scratch / "scene_band_flash_direct.xml"
    for xml_path, has_flash, flash_only, integrator in (
        (passive_xml, False, False, "path"),
        (flash_xml, True, True, "direct"),
    ):
        build_band_scene(
            scene_dir / "render_scene.xml", canonical, xml_path,
            band=args.band, nir_dir=args.nir_cache_dir,
            nir_flash=has_flash, nir_flash_half_m=0.015,
            nir_flash_initial_radiance=400.0,
            nir_flash_model="spot", nir_flash_beam_width_deg=22.0,
            nir_flash_cutoff_angle_deg=30.0,
            max_depth=8, integrator=integrator, force_analytic=False,
            polarized=False, enforce_bsdf_contract=False, flash_only=flash_only,
        )
        rid._resize_sensor(xml_path, args.width, args.height)

    report = {
        "schema": "robomituba.ir_render_profile.v1",
        "scene_dir": str(scene_dir),
        "config": {
            "width": args.width, "height": args.height, "spp": args.spp,
            "band": args.band, "viewpoint_count": len(views),
        },
        "scene_load_passive_s": None,
        "scene_load_flash_s": None,
        "frames": [],
    }

    def load_scene(xml_path: Path):
        started = time.perf_counter()
        scene = mi.load_file(str(xml_path))
        params = mi.traverse(scene)
        keys = {
            "camera": next(k for k in params.keys() if k.endswith(".to_world") and "nir_flash" not in k),
            "fov": next((k for k in params.keys() if k.endswith(".x_fov")), None),
            "weights": [k for k in params.keys() if rid.WEIGHT_RE.match(k)],
            "flash_tw": next((k for k in params.keys() if "nir_flash" in k and k.endswith(".to_world")), None),
        }
        elapsed = time.perf_counter() - started
        print(f"[profile] loaded {xml_path.name} in {elapsed:.1f}s "
              f"(weight_keys={len(keys['weights'])})", flush=True)
        return scene, params, keys, elapsed

    scene, params, keys, report["scene_load_passive_s"] = load_scene(passive_xml)
    for i, (node_id, yaw, camera) in enumerate(views, 1):
        frame_id = f"{node_id}__h_{int(round(yaw)) % 360:03d}"
        rgb, rgb_stage = _render_profiled(
            scene, params, keys, camera, band=0.0, spp=args.spp, seed=7,
            dr=dr, mi=mi, args_fov=args.fov,
        )
        amb, amb_stage = _render_profiled(
            scene, params, keys, camera, band=1.0, spp=args.spp, seed=7,
            dr=dr, mi=mi, args_fov=args.fov,
        )
        t_clean0 = time.perf_counter()
        if args.gpu_cleanup_every_frame:
            rid._free_gpu()
        cleanup_s = time.perf_counter() - t_clean0
        print(f"[profile-passive] {i}/{len(views)} {frame_id} "
              f"rgb_wall={rgb_stage['total_s']:.2f}s (gpu={rgb_stage['gpu_kernel_ms_total']:.0f}ms) "
              f"amb_wall={amb_stage['total_s']:.2f}s (gpu={amb_stage['gpu_kernel_ms_total']:.0f}ms) "
              f"cleanup={cleanup_s:.2f}s", flush=True)
        report["frames"].append({
            "frame_id": frame_id, "pass": "passive",
            "rgb": rgb_stage, "nir_ambient": amb_stage, "cleanup_s": cleanup_s,
        })
        del rgb, amb
    del scene, params, keys
    rid._free_gpu()

    scene, params, keys, report["scene_load_flash_s"] = load_scene(flash_xml)
    for i, (node_id, yaw, camera) in enumerate(views, 1):
        frame_id = f"{node_id}__h_{int(round(yaw)) % 360:03d}"
        flash, flash_stage = _render_profiled(
            scene, params, keys, camera, band=1.0, spp=args.spp, seed=7,
            dr=dr, mi=mi, args_fov=args.fov,
        )
        t_clean0 = time.perf_counter()
        if args.gpu_cleanup_every_frame:
            rid._free_gpu()
        cleanup_s = time.perf_counter() - t_clean0
        print(f"[profile-flash] {i}/{len(views)} {frame_id} "
              f"flash_wall={flash_stage['total_s']:.2f}s (gpu={flash_stage['gpu_kernel_ms_total']:.0f}ms) "
              f"cleanup={cleanup_s:.2f}s", flush=True)
        report["frames"].append({
            "frame_id": frame_id, "pass": "flash", "flash_direct": flash_stage, "cleanup_s": cleanup_s,
        })
        del flash
    del scene, params, keys
    rid._free_gpu()

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"[profile] wrote {args.out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
