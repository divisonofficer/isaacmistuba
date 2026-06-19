#!/usr/bin/env python3.10
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATHS = [
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
]
for module_path in reversed(MODULE_PATHS):
    if str(module_path) not in sys.path:
        sys.path.insert(0, str(module_path))

from mitsuba_converter.multimodal import (  # noqa: E402
    RenderConfig,
    extract_camera_from_scene,
    now_iso,
    read_json,
    render_modalities,
    write_json,
)


REQUESTED_MODALITIES = [
    "rgb",
    "depth",
    "albedo",
    "direct_light_map",
    "indirect_light_map",
    "diffuse_map",
    "specular_map",
    "polar_rgb_preview",
    "dop",
    "aolp",
    "s1",
    "s2",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render multimodal pass sets for selected candidate cameras.")
    parser.add_argument("--task", choices=["orchestrate"], default="orchestrate")
    parser.add_argument("--candidate-manifest", default="/jarvis/project/robomituba/out/moorelane_green_arrow_candidates_4096_selected/candidate_manifest.json")
    parser.add_argument("--output-dir", default="/jarvis/project/robomituba/out/moorelane_green_arrow_candidates_multimodal")
    parser.add_argument("--names", default=None, help="Comma-separated subset of candidate names")
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--path-spp", type=int, default=4096)
    parser.add_argument("--aov-spp", type=int, default=16)
    parser.add_argument("--polar-spp", type=int, default=256)
    parser.add_argument("--path-max-depth", type=int, default=6)
    parser.add_argument("--direct-max-depth", type=int, default=2)
    parser.add_argument("--rr-depth", type=int, default=8)
    parser.add_argument("--samples-per-pass", type=int, default=0)
    parser.add_argument("--polar-scale-threshold", type=float, default=1e-4)
    return parser


def build_render_config(args: argparse.Namespace) -> RenderConfig:
    return RenderConfig(
        width=args.width,
        height=args.height,
        path_spp=args.path_spp,
        aov_spp=args.aov_spp,
        polar_spp=args.polar_spp,
        path_max_depth=args.path_max_depth,
        direct_max_depth=args.direct_max_depth,
        rr_depth=args.rr_depth,
        samples_per_pass=args.samples_per_pass if args.samples_per_pass > 0 else None,
        polar_scale_threshold=args.polar_scale_threshold,
        artifact_stems={
            "rgb": "path_total",
            "direct_light_map": "direct_light_map",
            "diffuse_map": "diffuse_map",
        },
        scene_filenames={
            "rgb": "scene_path_total.xml",
            "direct_light_map": "scene_direct_light_map.xml",
            "diffuse_map": "scene_diffuse_map.xml",
            "aov": "scene_aov.xml",
            "polar": "scene_polar.xml",
            "polar_fallback": "scene_polar_fallback.xml",
        },
    )


def orchestrate(args: argparse.Namespace) -> None:
    manifest = read_json(Path(args.candidate_manifest))
    candidates = manifest["candidates"]
    if args.names:
        wanted = {name.strip() for name in args.names.split(",") if name.strip()}
        candidates = [item for item in candidates if item["name"] in wanted]
    if not candidates:
        raise RuntimeError("No candidate cameras selected")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    config = build_render_config(args)

    summary = {
        "start_time": now_iso(),
        "source_manifest": str(Path(args.candidate_manifest).resolve()),
        "config": {
            "width": config.width,
            "height": config.height,
            "path_spp": config.path_spp,
            "aov_spp": config.aov_spp,
            "polar_spp": config.polar_spp,
            "path_max_depth": config.path_max_depth,
            "direct_max_depth": config.direct_max_depth,
            "rr_depth": config.rr_depth,
            "samples_per_pass": config.samples_per_pass,
        },
        "definitions": {},
        "cameras": {},
    }

    total_start = time.perf_counter()
    log(f"[parent] selected cameras: {', '.join(item['name'] for item in candidates)}")
    log(f"[parent] output_dir={output_dir}")

    for candidate in candidates:
        camera_name = candidate["name"]
        source_scene = Path(candidate["outputs"]["xml"]).resolve()
        camera_dir = output_dir / camera_name
        camera_dir.mkdir(parents=True, exist_ok=True)
        camera_to_world, fov_deg = extract_camera_from_scene(source_scene)

        log(f"[parent] camera={camera_name} source_scene={source_scene}")
        camera_start = time.perf_counter()
        render_result = render_modalities(
            source_scene,
            camera_to_world,
            fov_deg,
            REQUESTED_MODALITIES,
            out_dir=camera_dir,
            config=config,
        )

        timing_total = camera_dir / "timing_path_total.json"
        timing_direct = camera_dir / "timing_direct_light_map.json"
        timing_diffuse = camera_dir / "timing_diffuse_map.json"
        timing_aov = camera_dir / "timing_aov.json"
        timing_polar = camera_dir / "timing_polarization.json"

        write_json(timing_total, render_result.pass_records["rgb"])
        write_json(timing_direct, render_result.pass_records["direct_light_map"])
        write_json(timing_diffuse, render_result.pass_records["diffuse_map"])
        write_json(timing_aov, render_result.pass_records["aov"])
        write_json(timing_polar, render_result.pass_records["polarization"])

        camera_summary = {
            "camera": candidate,
            "source_scene": str(source_scene),
            "staged_scenes": render_result.scene["staged_scenes"],
            "path_total": render_result.pass_records["rgb"],
            "direct_light_map": render_result.pass_records["direct_light_map"],
            "diffuse_map": render_result.pass_records["diffuse_map"],
            "aov": render_result.pass_records["aov"],
            "polarization": render_result.pass_records["polarization"],
            "derived": render_result.pass_records.get("derived", {}),
            "polarization_material_mode": render_result.scene["polarization_material_mode"],
            "total_camera_pipeline_s": time.perf_counter() - camera_start,
            "result_record": render_result.to_record(),
        }

        write_json(camera_dir / "camera_multimodal_summary.json", camera_summary)
        summary["definitions"] = render_result.definitions
        summary["cameras"][camera_name] = camera_summary
        log(f"[parent] camera={camera_name} done total_camera_pipeline_s={camera_summary['total_camera_pipeline_s']:.2f}")

    summary["total_pipeline_s"] = time.perf_counter() - total_start
    write_json(output_dir / "selected_cameras_multimodal_summary.json", summary)
    log(f"[parent] all done total_pipeline_s={summary['total_pipeline_s']:.2f}")


def main() -> None:
    args = build_parser().parse_args()
    orchestrate(args)


if __name__ == "__main__":
    main()
