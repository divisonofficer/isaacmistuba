from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from .scene_annotations import HazardRegion, SceneAnnotation, TraversableRegion


@dataclass(frozen=True)
class GridSpec:
    origin: list[float]
    resolution: float
    width: int
    height: int
    scene_id: str


@dataclass
class TraversabilityGrid:
    spec: GridSpec
    traversable: np.ndarray
    hazard: np.ndarray

    def to_nav_graph(self) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        for y in range(self.spec.height):
            for x in range(self.spec.width):
                if not self.traversable[y, x]:
                    continue
                node_id = f"{x},{y}"
                wx, wy = cell_to_world(self.spec, x, y)
                nodes.append({"id": node_id, "cell": [x, y], "world": [wx, wy], "hazard": bool(self.hazard[y, x])})
                for nx, ny in ((x + 1, y), (x, y + 1)):
                    if 0 <= nx < self.spec.width and 0 <= ny < self.spec.height and self.traversable[ny, nx]:
                        edges.append({"source": node_id, "target": f"{nx},{ny}", "cost": 1.0})
        return {
            "scene_id": self.spec.scene_id,
            "grid": asdict(self.spec),
            "nodes": nodes,
            "edges": edges,
        }


def _geometry_bounds(geometry: dict[str, Any]) -> tuple[float, float, float, float]:
    kind = geometry.get("type", "box")
    if kind == "box":
        min_x, min_y, max_x, max_y = [float(item) for item in geometry["bounds"]]
        return min_x, min_y, max_x, max_y
    if kind == "circle":
        cx, cy = [float(item) for item in geometry["center"][:2]]
        radius = float(geometry["radius"])
        return cx - radius, cy - radius, cx + radius, cy + radius
    if kind == "polygon":
        pts = np.asarray(geometry["points"], dtype=float)
        return float(np.min(pts[:, 0])), float(np.min(pts[:, 1])), float(np.max(pts[:, 0])), float(np.max(pts[:, 1]))
    raise ValueError(f"Unsupported geometry type: {kind}")


def _annotation_bounds(annotation: SceneAnnotation, margin: float) -> tuple[float, float, float, float]:
    bounds: list[tuple[float, float, float, float]] = []
    for region in annotation.traversable_regions:
        bounds.append(_geometry_bounds(region.geometry))
    for region in annotation.hazard_regions:
        bounds.append(_geometry_bounds(region.geometry))
    for goal in annotation.goal_regions:
        cx, cy = [float(item) for item in goal.center[:2]]
        radius = float(goal.radius)
        bounds.append((cx - radius, cy - radius, cx + radius, cy + radius))
    if not bounds:
        raise ValueError("Scene annotation has no geometry to derive grid bounds.")
    min_x = min(item[0] for item in bounds) - margin
    min_y = min(item[1] for item in bounds) - margin
    max_x = max(item[2] for item in bounds) + margin
    max_y = max(item[3] for item in bounds) + margin
    return min_x, min_y, max_x, max_y


def cell_to_world(spec: GridSpec, x: int, y: int) -> tuple[float, float]:
    return (
        float(spec.origin[0] + (x + 0.5) * spec.resolution),
        float(spec.origin[1] + (y + 0.5) * spec.resolution),
    )


def world_to_cell(spec: GridSpec, x: float, y: float) -> tuple[int, int]:
    cx = int(math.floor((float(x) - spec.origin[0]) / spec.resolution))
    cy = int(math.floor((float(y) - spec.origin[1]) / spec.resolution))
    return cx, cy


def _point_in_polygon(x: float, y: float, points: list[list[float]]) -> bool:
    inside = False
    j = len(points) - 1
    for i, point in enumerate(points):
        xi, yi = float(point[0]), float(point[1])
        xj, yj = float(points[j][0]), float(points[j][1])
        intersects = (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / max(yj - yi, 1e-12) + xi
        if intersects:
            inside = not inside
        j = i
    return inside


def _mask_geometry(spec: GridSpec, geometry: dict[str, Any]) -> np.ndarray:
    mask = np.zeros((spec.height, spec.width), dtype=bool)
    min_x, min_y, max_x, max_y = _geometry_bounds(geometry)
    x0, y0 = world_to_cell(spec, min_x, min_y)
    x1, y1 = world_to_cell(spec, max_x, max_y)
    x0 = max(0, min(spec.width - 1, x0))
    y0 = max(0, min(spec.height - 1, y0))
    x1 = max(0, min(spec.width - 1, x1))
    y1 = max(0, min(spec.height - 1, y1))
    kind = geometry.get("type", "box")
    for cy in range(y0, y1 + 1):
        for cx in range(x0, x1 + 1):
            wx, wy = cell_to_world(spec, cx, cy)
            if kind == "box":
                inside = min_x <= wx <= max_x and min_y <= wy <= max_y
            elif kind == "circle":
                center = geometry["center"]
                radius = float(geometry["radius"])
                inside = (wx - float(center[0])) ** 2 + (wy - float(center[1])) ** 2 <= radius ** 2
            elif kind == "polygon":
                inside = _point_in_polygon(wx, wy, geometry["points"])
            else:
                raise ValueError(f"Unsupported geometry type: {kind}")
            if inside:
                mask[cy, cx] = True
    return mask


def build_traversability_grid(annotation: SceneAnnotation, *, resolution: float = 0.05, margin: float = 0.5) -> TraversabilityGrid:
    if resolution <= 0:
        raise ValueError("resolution must be positive.")
    min_x, min_y, max_x, max_y = _annotation_bounds(annotation, margin)
    width = max(1, int(math.ceil((max_x - min_x) / resolution)))
    height = max(1, int(math.ceil((max_y - min_y) / resolution)))
    spec = GridSpec(origin=[float(min_x), float(min_y)], resolution=float(resolution), width=width, height=height, scene_id=annotation.scene_id)
    traversable = np.zeros((height, width), dtype=bool)
    for region in annotation.traversable_regions:
        region_mask = _mask_geometry(spec, region.geometry)
        if region.traversable:
            traversable |= region_mask
        else:
            traversable &= ~region_mask
    hazard = np.zeros((height, width), dtype=bool)
    for region in annotation.hazard_regions:
        hazard |= _mask_geometry(spec, region.geometry)
    for obj in annotation.objects:
        if obj.category in {"obstacle", "solid_obstacle"} and obj.geometry:
            traversable &= ~_mask_geometry(spec, obj.geometry)
    return TraversabilityGrid(spec=spec, traversable=traversable, hazard=hazard)


def save_traversability_grid(path: str | Path, grid: TraversabilityGrid) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = np.zeros((grid.spec.height, grid.spec.width), dtype=np.uint8)
    payload[grid.traversable] = 1
    payload[grid.hazard] = 2
    np.save(output, payload)
    sidecar = output.with_suffix(output.suffix + ".json")
    sidecar.write_text(json.dumps({"grid": asdict(grid.spec), "legend": {"0": "obstacle", "1": "traversable", "2": "hazard"}}, indent=2), encoding="utf-8")
    return output


def load_traversability_grid(path: str | Path) -> TraversabilityGrid:
    grid_path = Path(path)
    values = np.load(grid_path)
    meta = json.loads(grid_path.with_suffix(grid_path.suffix + ".json").read_text(encoding="utf-8"))
    spec = GridSpec(**meta["grid"])
    return TraversabilityGrid(spec=spec, traversable=values > 0, hazard=values == 2)


def write_nav_graph(path: str | Path, grid: TraversabilityGrid) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(grid.to_nav_graph(), indent=2), encoding="utf-8")
    return output
