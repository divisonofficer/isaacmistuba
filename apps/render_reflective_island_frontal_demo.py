#!/usr/bin/env python3.10
from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFont


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATHS = [
    REPO_ROOT / "modules" / "mitsuba_converter" / "src",
    REPO_ROOT / "modules" / "robomituba_bridge" / "src",
]
for module_path in reversed(MODULE_PATHS):
    if str(module_path) not in sys.path:
        sys.path.insert(0, str(module_path))

from robomituba_bridge import SceneState, to_repo_relative_posix
from mitsuba_converter import (
    REFLECTIVE_ISLAND_DEPTH_TARGETS,
    build_reflective_island_frontal_candidate_cameras,
    make_reflective_island_demo_request,
    render_modalities,
    select_projected_bbox_candidate,
)
from mitsuba_converter.multimodal import RenderConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a frontal reflective-island demo using scout camera selection.")
    parser.add_argument(
        "--scene",
        type=Path,
        default=REPO_ROOT / "out" / "moorelane_full_cam03_rgb_all" / "scene_curated_shell_furniture_sanitized.xml",
        help="Curated Mitsuba XML scene path.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "out" / "reflective_island_demo_gpu_frontal_v1",
        help="Output root for scout and final renders.",
    )
    parser.add_argument("--variant", default="cuda_ad_spectral")
    parser.add_argument("--scout-width", type=int, default=768)
    parser.add_argument("--scout-height", type=int, default=576)
    parser.add_argument("--scout-spp", type=int, default=1024)
    parser.add_argument("--final-width", type=int, default=1280)
    parser.add_argument("--final-height", type=int, default=960)
    parser.add_argument("--path-spp", type=int, default=16384)
    parser.add_argument("--aov-spp", type=int, default=24)
    parser.add_argument("--polar-spp", type=int, default=2048)
    parser.add_argument("--path-max-depth", type=int, default=5)
    parser.add_argument("--rr-depth", type=int, default=6)
    parser.add_argument("--samples-per-pass", type=int, default=128)
    return parser.parse_args()


def write_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def save_contact_sheet(image_paths: list[Path], labels: list[str], out_path: Path, cols: int = 3) -> None:
    thumbs = [Image.open(path).convert("RGB") for path in image_paths]
    if not thumbs:
        raise RuntimeError("No scout previews to assemble")
    font = ImageFont.load_default()
    thumb_w, thumb_h = thumbs[0].size
    label_h = 26
    rows = math.ceil(len(thumbs) / cols)
    sheet = Image.new("RGB", (cols * thumb_w, rows * (thumb_h + label_h)), (24, 24, 24))
    draw = ImageDraw.Draw(sheet)
    for idx, (img, label) in enumerate(zip(thumbs, labels)):
        x = (idx % cols) * thumb_w
        y = (idx // cols) * (thumb_h + label_h)
        sheet.paste(img, (x, y))
        draw.rectangle([x, y + thumb_h, x + thumb_w, y + thumb_h + label_h], fill=(32, 32, 32))
        draw.text((x + 8, y + thumb_h + 6), label, fill=(240, 240, 240), font=font)
    sheet.save(out_path)


def repo_relative_or_absolute(path: Path) -> str:
    try:
        return to_repo_relative_posix(REPO_ROOT, path.resolve())
    except Exception:
        return str(path.resolve())


def make_scene_state(scene_path: Path, *, frame_id: str) -> SceneState:
    scene_ref = repo_relative_or_absolute(scene_path)
    return SceneState(
        job_id="reflective-island-frontal-v1",
        scene_id="moorelane",
        frame_id=frame_id,
        timestamp=time.strftime("%Y-%m-%dT%H:%M:%S"),
        scene_snapshot_ref=scene_ref,
        mitsuba_scene_ref=scene_ref,
        scene_version="curated_shell_furniture_sanitized",
        illumination_setup="ambient_room",
    )


def render_branch(
    *,
    scene_path: Path,
    camera_spec,
    modalities: list[str],
    out_dir: Path,
    config: RenderConfig,
    scene_override,
    assist_light,
    depth_approx,
    variant: str,
) -> tuple[dict, object]:
    t0 = time.perf_counter()
    result = render_modalities(
        scene_path,
        np.asarray(camera_spec.camera_to_world, dtype=np.float32).reshape(4, 4),
        camera_spec.fov_deg,
        modalities,
        out_dir=out_dir,
        config=config,
        scene_override=scene_override,
        assist_light=assist_light,
        depth_approx=depth_approx,
        variant=variant,
    )
    elapsed = time.perf_counter() - t0
    return {
        "modalities": modalities,
        "elapsed_s": elapsed,
        "results": {name: item.to_record() for name, item in result.results.items()},
        "pass_records": result.pass_records,
    }, result


def main() -> None:
    args = parse_args()
    scene_path = args.scene.resolve()
    output_root = args.output_dir.resolve()
    scout_root = output_root / "scout"
    final_root = output_root / "final"
    scout_root.mkdir(parents=True, exist_ok=True)
    final_root.mkdir(parents=True, exist_ok=True)

    scene_state = make_scene_state(scene_path, frame_id="frame_reflective_frontal")
    base_request = make_reflective_island_demo_request(scene_state, calibration_ref="reflective_island_frontal")
    base_camera = base_request.camera_specs[0]
    scout_base_camera = replace(base_camera, resolution=[args.scout_width, args.scout_height])
    candidates = build_reflective_island_frontal_candidate_cameras(scout_base_camera)
    selected_camera, metrics = select_projected_bbox_candidate(
        scene_path,
        candidates,
        target_shape_filenames=list(REFLECTIVE_ISLAND_DEPTH_TARGETS),
        width=args.scout_width,
        height=args.scout_height,
    )

    scout_config = RenderConfig(
        width=args.scout_width,
        height=args.scout_height,
        path_spp=args.scout_spp,
        aov_spp=4,
        polar_spp=64,
        path_max_depth=args.path_max_depth,
        rr_depth=args.rr_depth,
        samples_per_pass=args.samples_per_pass,
    )

    scout_records: list[dict] = []
    preview_paths: list[Path] = []
    preview_labels: list[str] = []
    for camera in candidates:
        camera_dir = scout_root / camera.camera_id
        camera_dir.mkdir(parents=True, exist_ok=True)
        print(f"[scout] start {camera.camera_id}", flush=True)
        branch_summary, result = render_branch(
            scene_path=scene_path,
            camera_spec=camera,
            modalities=["rgb"],
            out_dir=camera_dir,
            config=scout_config,
            scene_override=base_request.scene_override,
            assist_light=None,
            depth_approx=None,
            variant=args.variant,
        )
        metric = next(item for item in metrics if item["camera_id"] == camera.camera_id)
        record = {
            "camera_id": camera.camera_id,
            "camera_name": camera.name,
            "step_length_m": camera.extras.get("step_length_m"),
            "bbox_metric": metric,
            "rgb_png": result.results["rgb"].artifacts["png"],
            "summary": branch_summary,
        }
        write_json(camera_dir / "scout_summary.json", record)
        scout_records.append(record)
        preview_paths.append(Path(result.results["rgb"].artifacts["png"]))
        preview_labels.append(
            f"{camera.camera_id}  d={metric['bbox_center_distance_px']:.1f}px  area={metric['bbox_area_px']}"
        )
        print(f"[scout] done {camera.camera_id}", flush=True)

    contact_sheet_path = scout_root / "contact_sheet.png"
    save_contact_sheet(preview_paths, preview_labels, contact_sheet_path, cols=3)
    scout_summary = {
        "scene": str(scene_path),
        "selected_camera_id": selected_camera.camera_id,
        "selected_step_length_m": selected_camera.extras.get("step_length_m"),
        "selected_bbox_metric": next(item for item in metrics if item["camera_id"] == selected_camera.camera_id),
        "metrics": metrics,
        "records": scout_records,
        "contact_sheet": str(contact_sheet_path),
    }
    write_json(scout_root / "scout_metrics.json", scout_summary)

    selected_final_camera = replace(selected_camera, resolution=[args.final_width, args.final_height])
    final_request = make_reflective_island_demo_request(
        scene_state,
        calibration_ref="reflective_island_frontal",
        render_settings={
            "width": args.final_width,
            "height": args.final_height,
            "path_spp": args.path_spp,
            "aov_spp": args.aov_spp,
            "polar_spp": args.polar_spp,
            "path_max_depth": args.path_max_depth,
            "rr_depth": args.rr_depth,
            "samples_per_pass": args.samples_per_pass,
        },
        camera_spec=selected_final_camera,
    )

    final_rgb_config = RenderConfig(
        width=args.final_width,
        height=args.final_height,
        path_spp=args.path_spp,
        aov_spp=args.aov_spp,
        polar_spp=args.polar_spp,
        path_max_depth=args.path_max_depth,
        rr_depth=args.rr_depth,
        samples_per_pass=args.samples_per_pass,
    )
    final_polar_config = replace(final_rgb_config, samples_per_pass=None)

    print(f"[final] selected camera {selected_final_camera.camera_id}", flush=True)
    final_summary: dict[str, object] = {
        "scene": str(scene_path),
        "selected_camera": {
            "camera_id": selected_final_camera.camera_id,
            "name": selected_final_camera.name,
            "camera_to_world": list(selected_final_camera.camera_to_world),
            "fov_deg": selected_final_camera.fov_deg,
            "resolution": list(selected_final_camera.resolution or [args.final_width, args.final_height]),
            "extras": dict(selected_final_camera.extras),
        },
        "config": {
            "rgb_depth_active": {
                "width": final_rgb_config.width,
                "height": final_rgb_config.height,
                "path_spp": final_rgb_config.path_spp,
                "aov_spp": final_rgb_config.aov_spp,
                "path_max_depth": final_rgb_config.path_max_depth,
                "rr_depth": final_rgb_config.rr_depth,
                "samples_per_pass": final_rgb_config.samples_per_pass,
            },
            "polar": {
                "width": final_polar_config.width,
                "height": final_polar_config.height,
                "polar_spp": final_polar_config.polar_spp,
                "path_max_depth": final_polar_config.path_max_depth,
                "rr_depth": final_polar_config.rr_depth,
                "samples_per_pass": final_polar_config.samples_per_pass,
            },
        },
        "scout": scout_summary,
        "branches": {},
    }

    branch_specs = [
        ("rgb", ["rgb"], final_rgb_config, None, None),
        ("active_depth_nir", ["sensor_depth_approx", "active_nir_intensity"], final_rgb_config, final_request.assist_light, final_request.depth_approx),
        ("polar", ["polar_rgb_preview", "s1", "s2", "dop", "aolp"], final_polar_config, final_request.assist_light, None),
    ]
    for branch_name, modalities, config, assist_light, depth_approx in branch_specs:
        print(f"[final] start {branch_name}: {modalities}", flush=True)
        branch_dir = final_root
        branch_summary, _result = render_branch(
            scene_path=scene_path,
            camera_spec=selected_final_camera,
            modalities=modalities,
            out_dir=branch_dir,
            config=config,
            scene_override=final_request.scene_override,
            assist_light=assist_light,
            depth_approx=depth_approx,
            variant=args.variant,
        )
        final_summary["branches"][branch_name] = branch_summary
        write_json(final_root / f"{branch_name}_summary.json", branch_summary)
        print(f"[final] done {branch_name}", flush=True)

    write_json(final_root / "render_summary.json", final_summary)
    print(f"[done] outputs -> {final_root}", flush=True)


if __name__ == "__main__":
    main()
