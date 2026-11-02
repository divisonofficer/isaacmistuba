#!/usr/bin/env python3
"""Render K yaw headings through Mitsuba's ``batch`` sensor.

This is an isolated correctness/throughput gate for the OptiX7 polarized
renderer. It never writes an OpticalNav observation or touches a daemon. The
input scene must be an already staged Stokes XML, and the supplied request is
used solely for one camera pose. The result film is split along X into K
ordinary ``H x W x 15`` Stokes tensors before reporting statistics.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np


def _normalize_mat4_storage(matrix: np.ndarray) -> np.ndarray:
    """Accept OpticalNav's legacy row-translation or Mitsuba column storage."""
    result = np.asarray(matrix, dtype=np.float64).reshape(4, 4)
    last_column = float(np.linalg.norm(result[:3, 3]))
    last_row = float(np.linalg.norm(result[3, :3]))
    if last_row > max(1e-5, last_column * 2.0):
        result = result.T
    return result


def _yaw_pose(camera_to_world: np.ndarray, degrees: float) -> np.ndarray:
    """Yaw a camera in place around OpticalNav's world-Y vertical axis."""
    radians = np.deg2rad(float(degrees))
    c, s = float(np.cos(radians)), float(np.sin(radians))
    yaw = np.array(((c, 0.0, s), (0.0, 1.0, 0.0), (-s, 0.0, c)), dtype=np.float64)
    result = np.array(camera_to_world, dtype=np.float64, copy=True)
    result[:3, :3] = yaw @ result[:3, :3]
    return result


def stage_batch_scene(
    source_scene: Path,
    output_scene: Path,
    *,
    camera_to_world: np.ndarray,
    batch_size: int,
    width: int,
    height: int,
    fov_deg: float,
) -> None:
    """Convert the first scene sensor to a batch parent with yawed children."""
    if batch_size < 2:
        raise ValueError("batch_size must be >= 2; this benchmark is for the batch-sensor path")
    from mitsuba_converter.polar_heading_batch import stage_ambient_stokes_heading_batch

    stage_ambient_stokes_heading_batch(
        source_scene,
        output_scene,
        camera_to_worlds=[
            _yaw_pose(camera_to_world, 360.0 * index / batch_size)
            for index in range(batch_size)
        ],
        width=width,
        height=height,
        fov_deg=fov_deg,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scene", type=Path, help="Immutable staged Stokes XML")
    parser.add_argument("request", type=Path, help="Saved request providing camera_to_world")
    parser.add_argument("--batch-size", type=int, choices=(2, 4, 6), required=True)
    parser.add_argument(
        "--variant",
        choices=("cuda_rgb_polarized", "cuda_ad_rgb_polarized"),
        default="cuda_ad_rgb_polarized",
        help="Mitsuba polarized CUDA variant to exercise (default: AD production candidate).",
    )
    parser.add_argument("--spp", type=int, default=64)
    parser.add_argument("--width", type=int, default=512)
    parser.add_argument("--height", type=int, default=512)
    parser.add_argument("--seed", type=int, default=17011)
    parser.add_argument("--repeats", type=int, default=1,
                        help="Number of in-process renders; output statistics use the final one")
    parser.add_argument("--out-scene", type=Path, required=True)
    parser.add_argument("--save-array", type=Path,
                        help="Optional .npy destination for the final H x (K*W) x 15 tensor")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be >= 1")

    payload = json.loads(args.request.read_text(encoding="utf-8"))
    cameras = list(payload.get("camera_specs") or ())
    if not cameras:
        raise RuntimeError("request has no camera_specs")
    camera = next((item for item in cameras if item.get("camera_id") == "polar_cam"), cameras[0])
    camera_to_world = _normalize_mat4_storage(camera["camera_to_world"])
    stage_batch_scene(
        args.scene.resolve(), args.out_scene.resolve(), camera_to_world=camera_to_world,
        batch_size=args.batch_size, width=args.width, height=args.height,
        fov_deg=float(camera.get("fov_deg", 60.0)),
    )

    import drjit as dr
    import mitsuba as mi

    mi.set_variant(args.variant)
    scene = mi.load_file(str(args.out_scene.resolve()))
    elapsed_samples: list[float] = []
    image = None
    for _ in range(args.repeats):
        dr.sync_thread()
        started = time.perf_counter()
        image = mi.render(scene, spp=args.spp, seed=args.seed)
        dr.eval(image)
        dr.sync_thread()
        elapsed_samples.append(time.perf_counter() - started)
    assert image is not None
    array = np.asarray(image, dtype=np.float32)
    if args.save_array is not None:
        args.save_array.parent.mkdir(parents=True, exist_ok=True)
        np.save(args.save_array, array)
    expected_shape = (args.height, args.width * args.batch_size, 15)
    if tuple(array.shape) != expected_shape:
        raise RuntimeError(f"expected batch film {expected_shape}, got {tuple(array.shape)}")
    strips = np.split(array, args.batch_size, axis=1)
    print(json.dumps({
        "variant": mi.variant(),
        "scene": str(args.scene.resolve()),
        "batch_scene": str(args.out_scene.resolve()),
        "batch_size": args.batch_size,
        "spp": args.spp,
        "elapsed_s": elapsed_samples[-1],
        "elapsed_samples_s": elapsed_samples,
        "shape": list(array.shape),
        "reference_axis": [0.0, 1.0, 0.0],
        "strips": [
            {
                "index": index,
                "shape": list(strip.shape),
                "finite": bool(np.isfinite(strip).all()),
                "mean_s0": float(np.mean(strip[..., 3:6])),
            }
            for index, strip in enumerate(strips)
        ],
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
