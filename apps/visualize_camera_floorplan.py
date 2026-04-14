#!/usr/bin/env python3
"""Create a top-down projected scene plan with camera markers."""

from __future__ import annotations

import argparse
import json
import math
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


RGBA = Tuple[int, int, int, int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scene", required=True, type=Path, help="Staged Mitsuba scene XML")
    parser.add_argument("--camera-manifest", required=True, type=Path, help="JSON manifest with base and variant cameras")
    parser.add_argument("--output-dir", required=True, type=Path, help="Output directory")
    parser.add_argument("--size", type=int, default=1800, help="Square canvas size in pixels")
    parser.add_argument("--margin", type=int, default=120, help="Outer border in pixels")
    return parser.parse_args()


def classify_obj(name: str) -> str:
    lower = name.lower()
    if "roof" in lower:
        return "roof"
    if "floor" in lower or "woodfloors" in lower:
        return "floor"
    if any(token in lower for token in [
        "wall",
        "yakisugi",
        "beam",
        "framing",
        "sheetmetal",
        "blackalum",
        "glass",
        "frontdoor",
    ]):
        return "shell"
    return "furniture"


def parse_scene(scene_path: Path) -> Tuple[float, List[Path]]:
    root = ET.parse(scene_path).getroot()
    fov = 60.0
    sensor = root.find("sensor")
    if sensor is not None:
        for child in sensor:
            if child.tag == "float" and child.get("name") == "fov":
                fov = float(child.get("value"))
                break

    obj_paths: List[Path] = []
    for shape in root.findall("shape"):
        if shape.get("type") != "obj":
            continue
        for child in shape:
            if child.tag == "string" and child.get("name") == "filename":
                obj_paths.append(Path(child.get("value")))
                break
    return fov, obj_paths


def load_vertices(obj_path: Path) -> np.ndarray:
    points: List[Tuple[float, float, float]] = []
    with obj_path.open("r", errors="ignore") as handle:
        for line in handle:
            if not line.startswith("v "):
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            points.append((float(parts[1]), float(parts[2]), float(parts[3])))
    if not points:
        return np.zeros((0, 3), dtype=np.float32)
    return np.asarray(points, dtype=np.float32)


def convex_hull(points: np.ndarray) -> np.ndarray:
    if points.shape[0] <= 1:
        return points.copy()
    pts = np.unique(points.astype(np.float64), axis=0)
    if pts.shape[0] <= 2:
        return pts

    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b) -> float:
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower: List[np.ndarray] = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)

    upper: List[np.ndarray] = []
    for p in pts[::-1]:
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)

    hull = np.vstack((lower[:-1], upper[:-1]))
    return hull


def build_masks(
    scene_path: Path,
    size: int,
    margin: int,
) -> Tuple[Dict[str, Image.Image], Dict[str, object]]:
    _, obj_paths = parse_scene(scene_path)
    vertex_sets: Dict[str, np.ndarray] = {}
    per_category: Dict[str, List[str]] = {"floor": [], "shell": [], "furniture": [], "roof": []}
    x_min = math.inf
    x_max = -math.inf
    z_min = math.inf
    z_max = -math.inf

    for obj_path in obj_paths:
        verts = load_vertices(obj_path)
        if verts.size == 0:
            continue
        vertex_sets[obj_path.name] = verts
        x_min = min(x_min, float(np.min(verts[:, 0])))
        x_max = max(x_max, float(np.max(verts[:, 0])))
        z_min = min(z_min, float(np.min(verts[:, 2])))
        z_max = max(z_max, float(np.max(verts[:, 2])))
        per_category[classify_obj(obj_path.name)].append(obj_path.name)

    if not math.isfinite(x_min):
        raise RuntimeError(f"No geometry vertices found in {scene_path}")

    extent_x = x_max - x_min
    extent_z = z_max - z_min
    if extent_x <= 0 or extent_z <= 0:
        raise RuntimeError("Invalid scene extent for top-down projection")

    inner_size = max(size - 2 * margin, 100)
    scale = min(inner_size / extent_x, inner_size / extent_z)
    pad_x = (size - extent_x * scale) * 0.5
    pad_z = (size - extent_z * scale) * 0.5

    def world_to_pixel(x: np.ndarray, z: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        px = np.clip(np.rint((x - x_min) * scale + pad_x).astype(np.int32), 0, size - 1)
        py = np.clip(np.rint((z_max - z) * scale + pad_z).astype(np.int32), 0, size - 1)
        return px, py

    masks_np = {
        "floor": np.zeros((size, size), dtype=np.uint8),
        "shell": np.zeros((size, size), dtype=np.uint8),
        "furniture": np.zeros((size, size), dtype=np.uint8),
        "roof": np.zeros((size, size), dtype=np.uint8),
    }
    object_stats: Dict[str, Dict[str, object]] = {}
    roof_hulls_world: List[Dict[str, object]] = []

    for name, verts in vertex_sets.items():
        category = classify_obj(name)
        px, py = world_to_pixel(verts[:, 0], verts[:, 2])
        linear = py * size + px
        counts = np.bincount(linear, minlength=size * size).reshape((size, size))
        masks_np[category] |= (counts > 0).astype(np.uint8) * 255
        if category == "roof":
            hull = convex_hull(verts[:, [0, 2]])
            roof_hulls_world.append(
                {
                    "name": name,
                    "points_xz": hull.tolist(),
                }
            )
        object_stats[name] = {
            "category": category,
            "vertex_count": int(verts.shape[0]),
            "bounds": {
                "min": [float(np.min(verts[:, 0])), float(np.min(verts[:, 1])), float(np.min(verts[:, 2]))],
                "max": [float(np.max(verts[:, 0])), float(np.max(verts[:, 1])), float(np.max(verts[:, 2]))],
            },
        }

    masks = {name: Image.fromarray(array, mode="L") for name, array in masks_np.items()}

    floor = masks["floor"]
    for _ in range(5):
        floor = floor.filter(ImageFilter.MaxFilter(9))
    floor = floor.filter(ImageFilter.GaussianBlur(2.0)).point(lambda p: 255 if p > 8 else 0)

    shell = masks["shell"]
    for _ in range(2):
        shell = shell.filter(ImageFilter.MaxFilter(7))
    shell = shell.filter(ImageFilter.GaussianBlur(1.2)).point(lambda p: 255 if p > 10 else 0)

    furniture = masks["furniture"]
    furniture = furniture.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(1.0)).point(
        lambda p: 255 if p > 10 else 0
    )

    roof = masks["roof"]
    roof = roof.filter(ImageFilter.MaxFilter(7)).filter(ImageFilter.GaussianBlur(1.0)).point(lambda p: 255 if p > 10 else 0)
    roof_outline = ImageChops.subtract(roof, roof.filter(ImageFilter.MinFilter(7)))

    metadata = {
        "scene": str(scene_path),
        "canvas_size_px": size,
        "margin_px": margin,
        "world_bounds_xz": {
            "x_min": x_min,
            "x_max": x_max,
            "z_min": z_min,
            "z_max": z_max,
        },
        "projection": {
            "scale_px_per_world_unit": scale,
            "pad_x": pad_x,
            "pad_z": pad_z,
        },
        "object_categories": per_category,
        "object_stats": object_stats,
        "roof_hulls_world": roof_hulls_world,
    }

    return {
        "floor": floor,
        "shell": shell,
        "furniture": furniture,
        "roof": roof,
        "roof_outline": roof_outline,
    }, metadata


def alpha_overlay(base: Image.Image, mask: Image.Image, color: RGBA) -> Image.Image:
    overlay = Image.new("RGBA", base.size, color)
    overlay.putalpha(mask)
    return Image.alpha_composite(base, overlay)


def world_mapper(metadata: Dict[str, object]):
    bounds = metadata["world_bounds_xz"]
    projection = metadata["projection"]
    x_min = float(bounds["x_min"])
    z_max = float(bounds["z_max"])
    scale = float(projection["scale_px_per_world_unit"])
    pad_x = float(projection["pad_x"])
    pad_z = float(projection["pad_z"])
    size = int(metadata["canvas_size_px"])

    def mapper(position_xyz: Iterable[float]) -> Tuple[float, float]:
        x, _, z = list(position_xyz)
        px = (x - x_min) * scale + pad_x
        py = (z_max - z) * scale + pad_z
        return float(np.clip(px, 0, size - 1)), float(np.clip(py, 0, size - 1))

    return mapper


def draw_arrow(draw: ImageDraw.ImageDraw, start: Tuple[float, float], end: Tuple[float, float], color: Tuple[int, int, int], width: int) -> None:
    draw.line([start, end], fill=color, width=width)
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    length = math.hypot(dx, dy)
    if length < 1e-6:
        return
    ux = dx / length
    uy = dy / length
    wing = max(10, width * 3)
    left = (end[0] - ux * wing - uy * wing * 0.55, end[1] - uy * wing + ux * wing * 0.55)
    right = (end[0] - ux * wing + uy * wing * 0.55, end[1] - uy * wing - ux * wing * 0.55)
    draw.polygon([end, left, right], fill=color)


def draw_camera(
    draw: ImageDraw.ImageDraw,
    mapper,
    camera: Dict[str, object],
    fov_deg: float,
    label: str,
    color: Tuple[int, int, int],
    fill_rgba: RGBA | None,
    font: ImageFont.ImageFont,
) -> None:
    origin = mapper(camera["origin"])
    target = mapper(camera["target"])
    radius = 9 if fill_rgba is not None else 7
    if fill_rgba is not None:
        dx = target[0] - origin[0]
        dy = target[1] - origin[1]
        length = math.hypot(dx, dy)
        if length > 1e-6:
            ux = dx / length
            uy = dy / length
            reach = max(120.0, length * 1.8)
            half = math.radians(fov_deg * 0.5)
            c = math.cos(half)
            s = math.sin(half)
            left = (ux * c - uy * s, ux * s + uy * c)
            right = (ux * c + uy * s, -ux * s + uy * c)
            wedge = [
                origin,
                (origin[0] + left[0] * reach, origin[1] + left[1] * reach),
                (origin[0] + right[0] * reach, origin[1] + right[1] * reach),
            ]
            draw.polygon(wedge, outline=color, fill=fill_rgba)
    draw.ellipse(
        [origin[0] - radius, origin[1] - radius, origin[0] + radius, origin[1] + radius],
        fill=color,
        outline=(255, 255, 255),
        width=2,
    )
    draw_arrow(draw, origin, target, color=color, width=4 if fill_rgba is not None else 3)
    text_pos = (origin[0] + 14, origin[1] - 18)
    draw.text(text_pos, label, fill=color, font=font)


def add_legend(image: Image.Image, include_variants: bool, font: ImageFont.ImageFont) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    box_w = 360
    box_h = 196 if include_variants else 152
    x0 = image.size[0] - box_w - 38
    y0 = 38
    draw.rounded_rectangle([x0, y0, x0 + box_w, y0 + box_h], radius=18, fill=(255, 255, 255, 218), outline=(80, 80, 80, 255), width=2)
    draw.text((x0 + 20, y0 + 16), "Top-Down Scene Plan", fill=(30, 30, 30), font=font)

    entries = [
        ("Floor footprint", (221, 214, 201)),
        ("Walls / shell", (96, 105, 116)),
        ("Furniture", (50, 60, 74)),
        ("Roof outline", (38, 132, 184)),
        ("Base camera", (230, 126, 34)),
    ]
    if include_variants:
        entries.append(("Variant cameras", (46, 134, 193)))

    y = y0 + 52
    for text, color in entries:
        draw.rounded_rectangle([x0 + 20, y, x0 + 44, y + 24], radius=6, fill=color + (255,), outline=(255, 255, 255, 255))
        draw.text((x0 + 58, y + 2), text, fill=(32, 32, 32), font=font)
        y += 28


def draw_roof_hulls(draw: ImageDraw.ImageDraw, mapper, metadata: Dict[str, object]) -> None:
    for hull_info in metadata.get("roof_hulls_world", []):
        points = [mapper((x, 0.0, z)) for x, z in hull_info["points_xz"]]
        if len(points) < 3:
            continue
        draw.line(points + [points[0]], fill=(35, 135, 190, 255), width=4)


def render_plan(
    masks: Dict[str, Image.Image],
    manifest: Dict[str, object],
    metadata: Dict[str, object],
    fov_deg: float,
    include_variants: bool,
) -> Image.Image:
    base = Image.new("RGBA", (metadata["canvas_size_px"], metadata["canvas_size_px"]), (247, 245, 239, 255))
    base = alpha_overlay(base, masks["floor"], (224, 216, 202, 170))
    base = alpha_overlay(base, masks["shell"], (100, 108, 118, 180))
    base = alpha_overlay(base, masks["furniture"], (44, 52, 63, 220))
    mapper = world_mapper(metadata)
    draw = ImageDraw.Draw(base, "RGBA")
    font = ImageFont.load_default()
    draw_roof_hulls(draw, mapper, metadata)

    base_camera = {
        "origin": manifest["base_camera"]["origin"],
        "target": manifest["base_camera"]["target"],
    }
    draw_camera(
        draw,
        mapper,
        base_camera,
        fov_deg=fov_deg,
        label="base",
        color=(230, 126, 34),
        fill_rgba=(230, 126, 34, 50),
        font=font,
    )

    if include_variants:
        label_map = {
            "cam_left": "L",
            "cam_right": "R",
            "cam_back": "B",
            "cam_right_oblique": "O",
        }
        for variant in manifest["variants"]:
            draw_camera(
                draw,
                mapper,
                variant,
                fov_deg=fov_deg,
                label=label_map.get(variant["name"], variant["name"]),
                color=(46, 134, 193),
                fill_rgba=None,
                font=font,
            )

    add_legend(base, include_variants=include_variants, font=font)
    return base


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    fov_deg, _ = parse_scene(args.scene)
    masks, metadata = build_masks(args.scene, size=args.size, margin=args.margin)
    manifest = json.loads(args.camera_manifest.read_text())
    metadata["camera_manifest"] = str(args.camera_manifest)
    metadata["sensor_horizontal_fov_deg"] = fov_deg
    metadata["base_camera"] = manifest["base_camera"]
    metadata["variants"] = manifest["variants"]

    base_only = render_plan(masks, manifest, metadata, fov_deg=fov_deg, include_variants=False)
    all_cameras = render_plan(masks, manifest, metadata, fov_deg=fov_deg, include_variants=True)

    base_only_path = args.output_dir / "scene_topdown_base_camera.png"
    all_cameras_path = args.output_dir / "scene_topdown_all_cameras.png"
    metadata_path = args.output_dir / "scene_topdown_metadata.json"

    base_only.save(base_only_path)
    all_cameras.save(all_cameras_path)
    metadata_path.write_text(json.dumps(metadata, indent=2))

    print(
        json.dumps(
            {
                "base_only": str(base_only_path),
                "all_cameras": str(all_cameras_path),
                "metadata": str(metadata_path),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
