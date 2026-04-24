#!/usr/bin/env python3.10
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from render_curated_multimodal import save_rgb_preview, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render candidate camera views from curated scene zones.")
    parser.add_argument("--scene", type=Path, help="Staged scene XML")
    parser.add_argument("--topdown-metadata", type=Path, help="scene_topdown_metadata.json")
    parser.add_argument("--topdown-background", type=Path, help="Topdown PNG to draw candidates on")
    parser.add_argument("--output-dir", type=Path, help="Output directory")
    parser.add_argument("--width", type=int, default=768)
    parser.add_argument("--height", type=int, default=576)
    parser.add_argument("--spp", type=int, default=512)
    parser.add_argument("--samples-per-pass", type=int, default=0)
    parser.add_argument("--integrator", default="direct")
    parser.add_argument("--names", help="Comma-separated subset of candidate names to render")
    parser.add_argument("--child-render", action="store_true")
    parser.add_argument("--scene-xml", type=Path)
    parser.add_argument("--png-out", type=Path)
    parser.add_argument("--exr-out", type=Path)
    parser.add_argument("--timing-out", type=Path)
    parser.add_argument("--record-json", type=Path)
    args = parser.parse_args()
    if args.child_render:
        required = {
            "--scene-xml": args.scene_xml,
            "--png-out": args.png_out,
            "--exr-out": args.exr_out,
            "--timing-out": args.timing_out,
            "--record-json": args.record_json,
        }
    else:
        required = {
            "--scene": args.scene,
            "--topdown-metadata": args.topdown_metadata,
            "--topdown-background": args.topdown_background,
            "--output-dir": args.output_dir,
        }
    missing = [flag for flag, value in required.items() if value is None]
    if missing:
        parser.error(f"missing required arguments: {' '.join(missing)}")
    return args


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sensor_info(scene_path: Path) -> tuple[float, list[float]]:
    root = ET.parse(scene_path).getroot()
    fov = 60.0
    up = [0.0, 1.0, 0.0]
    sensor = root.find("./sensor")
    if sensor is None:
        raise RuntimeError(f"No sensor found in {scene_path}")
    for child in sensor:
        if child.tag == "float" and child.attrib.get("name") == "fov":
            fov = float(child.attrib["value"])
        if child.tag == "transform" and child.attrib.get("name") == "to_world":
            lookat = child.find("./lookat")
            if lookat is not None and "up" in lookat.attrib:
                up = [float(v) for v in lookat.attrib["up"].split(",")]
    return fov, up


def center_of(bounds: dict) -> list[float]:
    return [(bounds["min"][i] + bounds["max"][i]) * 0.5 for i in range(3)]


def build_candidates(metadata: dict) -> list[dict]:
    stats = metadata["object_stats"]

    dining_table = center_of(stats["materials_diningTable_mtl.obj"]["bounds"])
    couch = center_of(stats["materials_newCouch_mtl.obj"]["bounds"])
    living_table = center_of(stats["materials_living_Table_mtl.obj"]["bounds"])
    landing = center_of(stats["materials_studioMat_landing_mtl.obj"]["bounds"])
    sideboard = center_of(stats["materials_sideboard_mtl.obj"]["bounds"])
    cabinets = center_of(stats["materials_cabinetsAlt_mtl.obj"]["bounds"])

    dining_eye = 1.28
    living_eye = -0.28
    stair_eye = 1.18

    return [
        {
            "name": "dining_north",
            "label": "Dining North",
            "room": "dining",
            "origin": [1.55, dining_eye, -4.75],
            "target": [0.15, 0.45, -10.6],
        },
        {
            "name": "dining_west",
            "label": "Dining West",
            "room": "dining",
            "origin": [-2.55, dining_eye, -7.65],
            "target": [4.4, 0.55, -6.45],
        },
        {
            "name": "dining_south",
            "label": "Dining South",
            "room": "dining",
            "origin": [-0.15, dining_eye, -11.45],
            "target": [0.1, 0.65, -4.85],
        },
        {
            "name": "dining_east",
            "label": "Dining East",
            "room": "dining",
            "origin": [3.25, dining_eye, -10.45],
            "target": [-2.45, 0.55, -6.65],
        },
        {
            "name": "kitchen_wing",
            "label": "Kitchen Wing",
            "room": "wing",
            "origin": [8.75, dining_eye, -9.15],
            "target": [0.85, 0.4, -8.2],
        },
        {
            "name": "stairs_left",
            "label": "Stairs Left",
            "room": "stairs",
            "origin": [7.35, stair_eye, -16.55],
            "target": [7.95, 0.15, -12.45],
        },
        {
            "name": "stairs_right",
            "label": "Stairs Right",
            "room": "stairs",
            "origin": [10.25, stair_eye, -16.45],
            "target": [8.55, 0.15, -12.55],
        },
        {
            "name": "living_west",
            "label": "Living West",
            "room": "living",
            "origin": [-3.45, living_eye, -16.05],
            "target": [1.95, -0.95, -15.1],
        },
        {
            "name": "living_south",
            "label": "Living South",
            "room": "living",
            "origin": [-0.55, living_eye, -19.25],
            "target": [0.0, -1.0, -14.95],
        },
        {
            "name": "living_east",
            "label": "Living East",
            "room": "living",
            "origin": [3.35, living_eye, -16.85],
            "target": [-2.0, -0.95, -15.05],
        },
        {
            "name": "wing_gallery",
            "label": "Wing Gallery",
            "room": "wing",
            "origin": [9.25, dining_eye, -6.15],
            "target": [2.1, 0.6, -7.25],
        },
    ]


def world_to_pixel(metadata: dict, xyz: list[float]) -> tuple[float, float]:
    bounds = metadata["world_bounds_xz"]
    projection = metadata["projection"]
    x_min = float(bounds["x_min"])
    z_max = float(bounds["z_max"])
    scale = float(projection["scale_px_per_world_unit"])
    pad_x = float(projection["pad_x"])
    pad_z = float(projection["pad_z"])
    x, _, z = xyz
    px = (x - x_min) * scale + pad_x
    py = (z_max - z) * scale + pad_z
    return px, py


def make_candidate_map(background_path: Path, metadata: dict, candidates: list[dict], out_path: Path) -> None:
    image = Image.open(background_path).convert("RGBA")
    draw = ImageDraw.Draw(image, "RGBA")
    font = ImageFont.load_default()
    for idx, cam in enumerate(candidates, start=1):
        px, py = world_to_pixel(metadata, cam["origin"])
        tx, ty = world_to_pixel(metadata, cam["target"])
        color = (91, 214, 123, 255)
        fill = (91, 214, 123, 72)
        draw.ellipse([px - 11, py - 11, px + 11, py + 11], fill=color, outline=(255, 255, 255, 255), width=2)
        draw.line([px, py, tx, ty], fill=fill, width=4)
        label = str(idx)
        draw.rounded_rectangle([px + 12, py - 14, px + 30, py + 4], radius=6, fill=(255, 255, 255, 232))
        draw.text((px + 17, py - 11), label, fill=(30, 30, 30), font=font)

    legend_x = 32
    legend_y = image.size[1] - 72
    draw.rounded_rectangle([legend_x, legend_y, legend_x + 360, legend_y + 40], radius=12, fill=(255, 255, 255, 220), outline=(90, 90, 90, 255), width=2)
    draw.ellipse([legend_x + 14, legend_y + 10, legend_x + 34, legend_y + 30], fill=(91, 214, 123, 255), outline=(255, 255, 255, 255), width=2)
    draw.text((legend_x + 48, legend_y + 11), "candidate cameras from green-arrow zones", fill=(30, 30, 30), font=font)
    image.save(out_path)


def rewrite_scene_for_camera(
    scene_path: Path,
    out_path: Path,
    *,
    origin: list[float],
    target: list[float],
    up: list[float],
    integrator_type: str,
    spp: int,
    width: int,
    height: int,
    samples_per_pass: int | None,
) -> None:
    root = ET.parse(scene_path).getroot()

    integrator = root.find("./integrator")
    if integrator is None:
        raise RuntimeError("Scene has no integrator")
    integrator.attrib["type"] = integrator_type
    for child in list(integrator):
        integrator.remove(child)
    if samples_per_pass is not None and samples_per_pass > 0:
        ET.SubElement(integrator, "integer", {"name": "samples_per_pass", "value": str(samples_per_pass)})

    sampler = root.find("./sensor/sampler")
    if sampler is None:
        raise RuntimeError("Scene has no sampler")
    sample_count = sampler.find("./integer[@name='sample_count']")
    if sample_count is None:
        sample_count = ET.SubElement(sampler, "integer", {"name": "sample_count"})
    sample_count.attrib["value"] = str(spp)

    film = root.find("./sensor/film")
    if film is not None:
        width_node = film.find("./integer[@name='width']")
        height_node = film.find("./integer[@name='height']")
        if width_node is not None:
            width_node.attrib["value"] = str(width)
        if height_node is not None:
            height_node.attrib["value"] = str(height)

    sensor_tf = root.find("./sensor/transform[@name='to_world']")
    if sensor_tf is None:
        raise RuntimeError("Scene has no sensor transform")
    for child in list(sensor_tf):
        sensor_tf.remove(child)
    ET.SubElement(
        sensor_tf,
        "lookat",
        {
            "origin": ",".join(f"{v:.9f}" for v in origin),
            "target": ",".join(f"{v:.9f}" for v in target),
            "up": ",".join(f"{v:.9f}" for v in up),
        },
    )

    ET.indent(root, space="  ")
    out_path.write_text(ET.tostring(root, encoding="unicode"), encoding="utf-8")


def save_contact_sheet(image_paths: list[Path], labels: list[str], out_path: Path, cols: int = 3) -> None:
    thumbs = [Image.open(path).convert("RGB") for path in image_paths]
    if not thumbs:
        raise RuntimeError("No candidate previews to assemble")
    font = ImageFont.load_default()
    thumb_w, thumb_h = thumbs[0].size
    label_h = 24
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


def render_one(args: argparse.Namespace) -> None:
    import mitsuba as mi

    mi.set_variant("cuda_ad_spectral")
    record = read_json(args.record_json)
    load_start = time.perf_counter()
    scene = mi.load_file(str(args.scene_xml))
    load_s = time.perf_counter() - load_start

    render_start = time.perf_counter()
    image = np.array(mi.render(scene, spp=args.spp), dtype=np.float32)
    render_s = time.perf_counter() - render_start

    rgb = image[:, :, :3] if image.ndim == 3 else np.repeat(image[:, :, None], 3, axis=2)
    mi.util.write_bitmap(str(args.exr_out), rgb)
    preview_info = save_rgb_preview(rgb, args.png_out)

    record["load_scene_s"] = load_s
    record["render_s"] = render_s
    record["total_s"] = load_s + render_s
    record["preview"] = preview_info
    write_json(args.timing_out, record)


def orchestrate(args: argparse.Namespace) -> None:
    args.output_dir.mkdir(parents=True, exist_ok=True)

    metadata = read_json(args.topdown_metadata)
    fov, up = sensor_info(args.scene)
    candidates = build_candidates(metadata)
    if args.names:
        allowed = {name.strip() for name in args.names.split(",") if name.strip()}
        candidates = [cam for cam in candidates if cam["name"] in allowed]

    candidate_map_path = args.output_dir / "candidate_camera_map.png"
    make_candidate_map(args.topdown_background, metadata, candidates, candidate_map_path)

    records: list[dict] = []
    preview_paths: list[Path] = []
    labels: list[str] = []

    for idx, candidate in enumerate(candidates, start=1):
        camera_dir = args.output_dir / candidate["name"]
        camera_dir.mkdir(parents=True, exist_ok=True)
        scene_xml = camera_dir / f"{candidate['name']}.xml"
        exr_path = camera_dir / f"{candidate['name']}.exr"
        png_path = camera_dir / f"{candidate['name']}.png"
        timing_path = camera_dir / "timing.json"
        record_json = camera_dir / "record.json"

        rewrite_scene_for_camera(
            args.scene,
            scene_xml,
            origin=candidate["origin"],
            target=candidate["target"],
            up=up,
            integrator_type=args.integrator,
            spp=args.spp,
            width=args.width,
            height=args.height,
            samples_per_pass=args.samples_per_pass if args.samples_per_pass > 0 else None,
        )

        record = {
            "index": idx,
            "name": candidate["name"],
            "label": candidate["label"],
            "room": candidate["room"],
            "fov_deg": fov,
            "origin": candidate["origin"],
            "target": candidate["target"],
            "spp": args.spp,
            "integrator": args.integrator,
            "outputs": {
                "xml": str(scene_xml),
                "exr": str(exr_path),
                "png": str(png_path),
            },
        }
        write_json(record_json, record)

        cmd = [
            os.environ.get("ROBOMITUBA_PYTHON", sys.executable),
            str(Path(__file__).resolve()),
            "--child-render",
            "--scene-xml",
            str(scene_xml),
            "--png-out",
            str(png_path),
            "--exr-out",
            str(exr_path),
            "--timing-out",
            str(timing_path),
            "--record-json",
            str(record_json),
            "--spp",
            str(args.spp),
        ]
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            record["status"] = "failed"
            record["returncode"] = result.returncode
            write_json(timing_path, record)
            records.append(record)
            continue

        record = read_json(timing_path)
        record["status"] = "ok"
        write_json(timing_path, record)
        records.append(record)
        preview_paths.append(png_path)
        labels.append(f"{idx}. {candidate['name']}")

    contact_sheet_path = args.output_dir / "candidate_contact_sheet.png"
    save_contact_sheet(preview_paths, labels, contact_sheet_path, cols=3)

    manifest = {
        "source_scene": str(args.scene),
        "topdown_metadata": str(args.topdown_metadata),
        "topdown_background": str(args.topdown_background),
        "candidate_map": str(candidate_map_path),
        "spp": args.spp,
        "integrator": args.integrator,
        "width": args.width,
        "height": args.height,
        "samples_per_pass": args.samples_per_pass if args.samples_per_pass > 0 else None,
        "candidates": records,
        "contact_sheet": str(contact_sheet_path),
    }
    write_json(args.output_dir / "candidate_manifest.json", manifest)
    print(json.dumps({
        "candidate_map": str(candidate_map_path),
        "contact_sheet": str(contact_sheet_path),
        "manifest": str(args.output_dir / "candidate_manifest.json"),
        "count": len(records),
    }, indent=2))


def main() -> None:
    args = parse_args()
    if args.child_render:
        render_one(args)
    else:
        orchestrate(args)


if __name__ == "__main__":
    main()
