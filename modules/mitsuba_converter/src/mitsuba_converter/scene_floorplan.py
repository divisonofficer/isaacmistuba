from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont


RGBA = Tuple[int, int, int, int]


@dataclass(frozen=True)
class CameraOverlay:
    label: str
    origin: Sequence[float]
    target: Sequence[float]
    fov_deg: float
    color: Tuple[int, int, int]
    fill_rgba: RGBA | None = None


@dataclass(frozen=True)
class LightOverlay:
    label: str
    position: Sequence[float]
    color: Tuple[int, int, int] = (245, 186, 77)


def _classify_obj(name: str) -> str:
    lower = name.lower()
    if "roof" in lower:
        return "roof"
    if "floor" in lower or "woodfloors" in lower:
        return "floor"
    if any(
        token in lower
        for token in [
            "wall",
            "yakisugi",
            "beam",
            "framing",
            "sheetmetal",
            "blackalum",
            "glass",
            "frontdoor",
        ]
    ):
        return "shell"
    return "furniture"


def _parse_scene_obj_paths(scene_path: Path) -> List[Path]:
    root = ET.parse(scene_path).getroot()
    obj_paths: List[Path] = []
    for shape in root.findall("shape"):
        if shape.get("type") != "obj":
            continue
        for child in shape:
            if child.tag == "string" and child.get("name") == "filename":
                obj_paths.append(Path(child.get("value")))
                break
    return obj_paths


def _load_vertices(obj_path: Path) -> np.ndarray:
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


def _convex_hull(points: np.ndarray) -> np.ndarray:
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

    return np.vstack((lower[:-1], upper[:-1]))


def _build_masks(scene_path: Path, *, size: int, margin: int):
    obj_paths = _parse_scene_obj_paths(scene_path)
    vertex_sets: dict[str, np.ndarray] = {}
    per_category: dict[str, list[str]] = {"floor": [], "shell": [], "furniture": [], "roof": []}
    x_min = math.inf
    x_max = -math.inf
    z_min = math.inf
    z_max = -math.inf

    for obj_path in obj_paths:
        verts = _load_vertices(obj_path)
        if verts.size == 0:
            continue
        vertex_sets[obj_path.name] = verts
        x_min = min(x_min, float(np.min(verts[:, 0])))
        x_max = max(x_max, float(np.max(verts[:, 0])))
        z_min = min(z_min, float(np.min(verts[:, 2])))
        z_max = max(z_max, float(np.max(verts[:, 2])))
        per_category[_classify_obj(obj_path.name)].append(obj_path.name)

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
    roof_hulls_world: List[dict[str, object]] = []

    for name, verts in vertex_sets.items():
        category = _classify_obj(name)
        px, py = world_to_pixel(verts[:, 0], verts[:, 2])
        linear = py * size + px
        counts = np.bincount(linear, minlength=size * size).reshape((size, size))
        masks_np[category] |= (counts > 0).astype(np.uint8) * 255
        if category == "roof":
            hull = _convex_hull(verts[:, [0, 2]])
            roof_hulls_world.append({"name": name, "points_xz": hull.tolist()})

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
        "roof_hulls_world": roof_hulls_world,
    }

    return {
        "floor": floor,
        "shell": shell,
        "furniture": furniture,
        "roof_outline": roof_outline,
    }, metadata


def _alpha_overlay(base: Image.Image, mask: Image.Image, color: RGBA) -> Image.Image:
    overlay = Image.new("RGBA", base.size, color)
    overlay.putalpha(mask)
    return Image.alpha_composite(base, overlay)


def _world_mapper(metadata: dict[str, object]):
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


def _draw_arrow(draw: ImageDraw.ImageDraw, start: Tuple[float, float], end: Tuple[float, float], color: Tuple[int, int, int], width: int) -> None:
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


def _draw_camera(draw: ImageDraw.ImageDraw, mapper, camera: CameraOverlay, font: ImageFont.ImageFont) -> None:
    origin = mapper(camera.origin)
    target = mapper(camera.target)
    radius = 9 if camera.fill_rgba is not None else 7
    if camera.fill_rgba is not None:
        dx = target[0] - origin[0]
        dy = target[1] - origin[1]
        length = math.hypot(dx, dy)
        if length > 1e-6:
            ux = dx / length
            uy = dy / length
            reach = max(120.0, length * 1.8)
            half = math.radians(camera.fov_deg * 0.5)
            c = math.cos(half)
            s = math.sin(half)
            left = (ux * c - uy * s, ux * s + uy * c)
            right = (ux * c + uy * s, -ux * s + uy * c)
            wedge = [
                origin,
                (origin[0] + left[0] * reach, origin[1] + left[1] * reach),
                (origin[0] + right[0] * reach, origin[1] + right[1] * reach),
            ]
            draw.polygon(wedge, outline=camera.color, fill=camera.fill_rgba)
    draw.ellipse(
        [origin[0] - radius, origin[1] - radius, origin[0] + radius, origin[1] + radius],
        fill=camera.color,
        outline=(255, 255, 255),
        width=2,
    )
    _draw_arrow(draw, origin, target, color=camera.color, width=4 if camera.fill_rgba is not None else 3)
    draw.text((origin[0] + 14, origin[1] - 18), camera.label, fill=camera.color, font=font)


def _draw_light(draw: ImageDraw.ImageDraw, mapper, light: LightOverlay, font: ImageFont.ImageFont) -> None:
    pos = mapper(light.position)
    radius = 6
    draw.ellipse(
        [pos[0] - radius, pos[1] - radius, pos[0] + radius, pos[1] + radius],
        fill=light.color,
        outline=(255, 255, 255),
        width=1,
    )
    draw.text((pos[0] + 10, pos[1] - 14), light.label, fill=light.color, font=font)


def _draw_roof_hulls(draw: ImageDraw.ImageDraw, mapper, metadata: dict[str, object]) -> None:
    for hull_info in metadata.get("roof_hulls_world", []):
        points = [mapper((x, 0.0, z)) for x, z in hull_info["points_xz"]]
        if len(points) < 3:
            continue
        draw.line(points + [points[0]], fill=(35, 135, 190, 255), width=4)


def _add_legend(
    image: Image.Image,
    *,
    include_request_camera: bool,
    include_snapshot_cameras: bool,
    include_lights: bool,
    title: str,
    font: ImageFont.ImageFont,
) -> None:
    draw = ImageDraw.Draw(image, "RGBA")
    entries = [
        ("Floor footprint", (221, 214, 201)),
        ("Walls / shell", (96, 105, 116)),
        ("Furniture", (50, 60, 74)),
        ("Roof outline", (38, 132, 184)),
    ]
    if include_request_camera:
        entries.append(("Latest request camera", (230, 126, 34)))
    if include_snapshot_cameras:
        entries.append(("Snapshot cameras", (46, 134, 193)))
    if include_lights:
        entries.append(("Snapshot lights", (245, 186, 77)))

    box_w = 360
    box_h = 56 + len(entries) * 28
    x0 = image.size[0] - box_w - 38
    y0 = 38
    draw.rounded_rectangle(
        [x0, y0, x0 + box_w, y0 + box_h],
        radius=18,
        fill=(255, 255, 255, 218),
        outline=(80, 80, 80, 255),
        width=2,
    )
    draw.text((x0 + 20, y0 + 16), title, fill=(30, 30, 30), font=font)

    y = y0 + 52
    for text, color in entries:
        draw.rounded_rectangle([x0 + 20, y, x0 + 44, y + 24], radius=6, fill=color + (255,), outline=(255, 255, 255, 255))
        draw.text((x0 + 58, y + 2), text, fill=(32, 32, 32), font=font)
        y += 28


def render_scene_floorplan(
    *,
    scene_path: str | Path,
    output_path: str | Path,
    metadata_path: str | Path | None = None,
    request_cameras: Sequence[CameraOverlay] = (),
    snapshot_cameras: Sequence[CameraOverlay] = (),
    snapshot_lights: Sequence[LightOverlay] = (),
    size: int = 1600,
    margin: int = 96,
    title: str = "Top-Down Scene Plan",
) -> dict[str, object]:
    scene = Path(scene_path)
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    masks, metadata = _build_masks(scene, size=size, margin=margin)
    metadata["request_cameras"] = [camera.label for camera in request_cameras]
    metadata["snapshot_cameras"] = [camera.label for camera in snapshot_cameras]
    metadata["snapshot_lights"] = [light.label for light in snapshot_lights]

    base = Image.new("RGBA", (size, size), (247, 245, 239, 255))
    base = _alpha_overlay(base, masks["floor"], (224, 216, 202, 170))
    base = _alpha_overlay(base, masks["shell"], (100, 108, 118, 180))
    base = _alpha_overlay(base, masks["furniture"], (44, 52, 63, 220))

    mapper = _world_mapper(metadata)
    draw = ImageDraw.Draw(base, "RGBA")
    font = ImageFont.load_default()

    _draw_roof_hulls(draw, mapper, metadata)
    for light in snapshot_lights:
        _draw_light(draw, mapper, light, font)
    for camera in snapshot_cameras:
        _draw_camera(draw, mapper, camera, font)
    for camera in request_cameras:
        _draw_camera(draw, mapper, camera, font)

    _add_legend(
        base,
        include_request_camera=bool(request_cameras),
        include_snapshot_cameras=bool(snapshot_cameras),
        include_lights=bool(snapshot_lights),
        title=title,
        font=font,
    )

    base.save(output)
    metadata_payload = {
        **metadata,
        "output_path": str(output),
        "title": title,
    }
    if metadata_path is not None:
        metadata_file = Path(metadata_path)
        metadata_file.parent.mkdir(parents=True, exist_ok=True)
        metadata_file.write_text(json.dumps(metadata_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return metadata_payload
