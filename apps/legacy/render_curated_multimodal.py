#!/usr/bin/env python3.10
from __future__ import annotations

import argparse
import shutil
from pathlib import Path
import sys
import time
import uuid
import xml.etree.ElementTree as ET


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
    render_modalities,
    write_json,
)


def copy_with_rewrite(scene_path: Path, stage_root: Path) -> tuple[Path, dict]:
    start = time.perf_counter()
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.parse(scene_path, parser=parser).getroot()

    files_root = stage_root / "files"
    files_root.mkdir(parents=True, exist_ok=True)

    copied: dict[Path, Path] = {}
    bytes_total = 0
    copy_start = time.perf_counter()
    for node in root.iter("string"):
        if node.attrib.get("name") != "filename" or "value" not in node.attrib:
            continue
        src = Path(node.attrib["value"])
        if not src.is_absolute():
            src = (scene_path.parent / src).resolve()
        if not src.exists():
            raise FileNotFoundError(f"Missing dependency: {src}")

        if src not in copied:
            rel = Path(*src.parts[1:]) if src.is_absolute() else src
            dst = files_root / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            copied[src] = dst
            bytes_total += src.stat().st_size
        node.attrib["value"] = str(copied[src])

    copy_s = time.perf_counter() - copy_start
    staged_scene = stage_root / "scene_staged.xml"
    ET.indent(root, space="  ")
    staged_scene.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")

    return staged_scene, {
        "start_time": now_iso(),
        "file_count": len(copied),
        "bytes_copied": bytes_total,
        "copy_s": copy_s,
        "rewrite_s": time.perf_counter() - start - copy_s,
        "total_s": time.perf_counter() - start,
        "stage_root": str(stage_root),
        "staged_scene": str(staged_scene),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render RGB, depth, and polarization products for a curated Mitsuba scene.")
    parser.add_argument("--task", choices=["orchestrate"], default="orchestrate")
    parser.add_argument("--scene", default="/jarvis/project/robomituba/out/moorelane_full_cam03_rgb_all/scene_curated_shell_furniture_sanitized.xml")
    parser.add_argument("--output-dir", default="/jarvis/project/robomituba/out/moorelane_full_cam03_multimodal_render")
    parser.add_argument("--stage-root", default=None)
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--rgb-spp", type=int, default=256)
    parser.add_argument("--depth-spp", type=int, default=16)
    parser.add_argument("--polar-spp", type=int, default=256)
    parser.add_argument("--samples-per-pass", type=int, default=16)
    parser.add_argument("--polar-scale-threshold", type=float, default=1e-4)
    return parser


def orchestrate(args: argparse.Namespace) -> None:
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    run_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
    total_start = time.perf_counter()
    stage_root = Path(args.stage_root or f"/tmp/robomituba_stage/curated_multimodal_{run_id}")
    stage_root.mkdir(parents=True, exist_ok=True)

    scene_path = Path(args.scene).resolve()
    staged_scene, stage_info = copy_with_rewrite(scene_path, stage_root)
    camera_to_world, fov_deg = extract_camera_from_scene(staged_scene)

    render_result = render_modalities(
        staged_scene,
        camera_to_world,
        fov_deg,
        ["rgb", "depth", "polar_rgb_preview", "dop", "aolp", "s1", "s2"],
        out_dir=output_dir,
        config=RenderConfig(
            width=args.width,
            height=args.height,
            path_spp=args.rgb_spp,
            aov_spp=args.depth_spp,
            polar_spp=args.polar_spp,
            path_max_depth=2,
            direct_max_depth=2,
            samples_per_pass=args.samples_per_pass if args.samples_per_pass > 0 else None,
            polar_scale_threshold=args.polar_scale_threshold,
            artifact_stems={"rgb": "rgb"},
            scene_filenames={
                "rgb": "scene_rgb.xml",
                "aov": "scene_depth.xml",
                "polar": "scene_polar.xml",
            },
        ),
    )

    write_json(output_dir / "timing_rgb.json", render_result.pass_records["rgb"])
    write_json(output_dir / "timing_depth.json", render_result.pass_records["aov"])
    write_json(output_dir / "timing_polar.json", render_result.pass_records["polarization"])

    summary = {
        "start_time": now_iso(),
        "source_scene": str(scene_path),
        "stage": stage_info,
        "config": {
            "width": args.width,
            "height": args.height,
            "rgb_spp": args.rgb_spp,
            "depth_spp": args.depth_spp,
            "polar_spp": args.polar_spp,
            "samples_per_pass": args.samples_per_pass if args.samples_per_pass > 0 else None,
            "polar_scale_threshold": args.polar_scale_threshold,
        },
        "rgb": render_result.pass_records["rgb"],
        "depth": render_result.pass_records["aov"],
        "polarization": render_result.pass_records["polarization"],
        "total_pipeline_s": time.perf_counter() - total_start,
        "staged_scenes": render_result.scene["staged_scenes"],
        "result_record": render_result.to_record(),
    }
    summary["polarization"]["material_mode"] = render_result.scene["polarization_material_mode"]
    write_json(output_dir / "render_timing_summary.json", summary)


def main() -> None:
    args = build_parser().parse_args()
    orchestrate(args)


if __name__ == "__main__":
    main()
