"""Measure warm fixed-SPP Stokes renders from an OpticalNav observation.

The script deliberately keeps one Python/Mitsuba process alive, performs a
warm-up, and then measures the requested SPP values.  It is intended for an
otherwise idle GPU, so a production render queue is never disturbed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np


REPO_ROOT = Path(__file__).resolve().parents[1]
for _path in (
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
    REPO_ROOT / "modules" / "navigation_dataset" / "src",
):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from mitsuba_converter.multimodal import RenderConfig, render_modalities


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path, help="Existing polar observation manifest.json")
    parser.add_argument("--spps", default="512,768,1024", help="Comma-separated fixed SPP values")
    parser.add_argument("--out-dir", type=Path, required=True, help="Scratch output directory")
    return parser.parse_args()


def main() -> None:
    args = _args()
    payload = json.loads(args.manifest.read_text(encoding="utf-8"))
    camera = next(item for item in payload["camera_specs"] if item.get("camera_id") == "polar_cam")
    scene = Path(payload["artifacts"][0]["scene_ref"])
    camera_to_world = np.asarray(camera["camera_to_world"], dtype=np.float64).reshape(4, 4)
    spps = [int(value.strip()) for value in str(args.spps).split(",") if value.strip()]
    if not spps or any(value <= 0 for value in spps):
        raise ValueError("--spps must contain positive integer values")

    rendered: dict[int, dict[str, np.ndarray]] = {}

    def render(label: str, spp: int) -> None:
        started = time.perf_counter()
        result = render_modalities(
            scene,
            camera_to_world,
            float(camera["fov_deg"]),
            ["polar_rgb_preview"],
            out_dir=args.out_dir / f"{label}_{spp}",
            config=RenderConfig(
                width=512,
                height=512,
                polar_spp=spp,
                polar_visualization_policy="raw_stokes_aolp_v1",
                polar_color_mode="rgb_stokes_12",
                polar_transport="physical",
            ),
            variant="cuda_ad_rgb_polarized",
        )
        timing = result.results["polar_rgb_preview"].timing
        npz = args.out_dir / f"{label}_{spp}" / "stokes_data.npz"
        with np.load(npz, allow_pickle=False) as values:
            rendered[spp] = {name: np.asarray(values[name]).copy() for name in ("s0", "s1", "s2", "s3")}
        print(json.dumps({
            "label": label,
            "spp": spp,
            "wall_s": time.perf_counter() - started,
            "render_s": timing.get("render_s"),
            "requested_spp": timing.get("requested_spp"),
            "sensor_sampler_spp": timing.get("sensor_sampler_spp"),
            "load_scene_s": timing.get("load_scene_s"),
            "scene_cache_hit": timing.get("scene_cache_hit"),
            "polar_postprocess_s": timing.get("polar_postprocess_s"),
            "stokes_npz_write_s": timing.get("stokes_npz_write_s"),
            "stokes_sha256": hashlib.sha256(npz.read_bytes()).hexdigest(),
        }), flush=True)

    render("warmup", spps[0])
    for spp in spps:
        render("benchmark", spp)
    reference = rendered[spps[0]]
    for spp in spps[1:]:
        candidate = rendered[spp]
        diffs = [
            np.asarray(reference[name], dtype=np.float64) - np.asarray(candidate[name], dtype=np.float64)
            for name in ("s0", "s1", "s2", "s3")
        ]
        joined = np.concatenate([item.reshape(-1) for item in diffs])
        print(json.dumps({
            "comparison": f"{spps[0]}-{spp}",
            "exact_equal": bool(all(np.array_equal(reference[name], candidate[name]) for name in reference)),
            "max_abs": float(np.max(np.abs(joined))),
            "rmse": float(np.sqrt(np.mean(joined * joined))),
        }), flush=True)


if __name__ == "__main__":
    main()
