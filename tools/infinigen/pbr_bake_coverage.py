"""Pure helpers for validating that a baked atlas covers its referenced UV surface."""
from __future__ import annotations

from collections import defaultdict

import numpy as np


_BARYCENTRIC_SAMPLES = np.asarray([
    [1 / 3, 1 / 3, 1 / 3],
    [0.8, 0.1, 0.1],
    [0.1, 0.8, 0.1],
    [0.1, 0.1, 0.8],
], dtype=np.float64)


def validate_uv_coverage(
    uv_triangles: np.ndarray,
    triangle_areas: np.ndarray,
    material_indices: np.ndarray,
    coverage: np.ndarray,
    *,
    max_unbaked_ratio: float = 0.001,
    max_material_slot_unbaked_ratio: float | None = None,
    max_degenerate_ratio: float = 0.001,
    max_overlap_factor: float = 1.10,
    overlap_resolution: int = 512,
    known_disjoint_face_atlas: bool = False,
) -> dict:
    """Measure UV-referenced unbaked coverage using four interior samples/triangle.

    ``coverage`` is a top-left-origin boolean image loaded from the saved coverage PNG.
    OBJ/Blender UV has a bottom-left origin, hence the explicit V flip below.
    """
    triangles = np.asarray(uv_triangles, np.float64).reshape(-1, 3, 2)
    areas = np.asarray(triangle_areas, np.float64).reshape(-1)
    slots = np.asarray(material_indices, np.int64).reshape(-1)
    if not (len(triangles) == len(areas) == len(slots)):
        raise ValueError("triangle arrays must have equal length")
    original_triangle_count = len(triangles)
    uv_area = np.abs(
        (triangles[:, 1, 0] - triangles[:, 0, 0])
        * (triangles[:, 2, 1] - triangles[:, 0, 1])
        - (triangles[:, 1, 1] - triangles[:, 0, 1])
        * (triangles[:, 2, 0] - triangles[:, 0, 0])
    ) * 0.5
    finite_uv = np.isfinite(triangles).all(axis=(1, 2)) & np.isfinite(uv_area)
    valid_geometry = np.isfinite(areas) & (areas > 1e-20)
    renderable = finite_uv & valid_geometry
    valid_uv = renderable & (uv_area > 1e-14)
    invalid_geometry_ratio = 1.0 - float(np.mean(valid_geometry)) if original_triangle_count else 1.0
    uv_degenerate_count_ratio = (
        float(np.mean(~valid_uv[renderable])) if np.any(renderable) else 1.0
    )
    renderable_area = max(float(np.sum(areas[renderable])), 1e-20)
    uv_degenerate_surface_ratio = float(
        np.sum(areas[renderable & ~valid_uv]) / renderable_area
    )
    finite = valid_uv
    triangles, areas, slots = triangles[finite], areas[finite], slots[finite]
    uv_area = uv_area[finite]
    if not len(triangles):
        return {"passed": False, "reason": "no_valid_uv_triangles", "triangle_count": 0}

    points = np.einsum("sk,tkd->tsd", _BARYCENTRIC_SAMPLES, triangles)
    height, width = np.asarray(coverage).shape
    x = np.clip(np.rint(points[..., 0] * (width - 1)).astype(np.int64), 0, width - 1)
    y = np.clip(np.rint((1.0 - points[..., 1]) * (height - 1)).astype(np.int64), 0, height - 1)
    valid = np.asarray(coverage, bool)[y, x]
    invalid_fraction = 1.0 - valid.mean(axis=1)
    total_area = max(float(areas.sum()), 1e-20)
    weighted_unbaked = float(np.sum(areas * invalid_fraction) / total_area)
    all_unbaked = invalid_fraction >= 1.0
    weighted_all_unbaked = float(np.sum(areas * all_unbaked) / total_area)

    per_slot_area = defaultdict(float)
    per_slot_bad = defaultdict(float)
    for slot, area, fraction in zip(slots, areas, invalid_fraction):
        per_slot_area[int(slot)] += float(area)
        per_slot_bad[int(slot)] += float(area * fraction)
    per_slot = {
        str(slot): {
            "surface_area": per_slot_area[slot],
            "referenced_unbaked_ratio": per_slot_bad[slot] / max(per_slot_area[slot], 1e-20),
        }
        for slot in sorted(per_slot_area)
    }
    max_slot_unbaked = max(row["referenced_unbaked_ratio"] for row in per_slot.values())

    overlap = estimate_uv_overlap(triangles, uv_area, slots, resolution=overlap_resolution)
    uv_cross = uv_area * float(width * height)
    # Million-face generated foliage can contain tiny material parts whose UV
    # islands remain sub-pixel at 4K. Keep the strict surface-weighted global
    # gate, while allowing callers to use a separate bounded per-slot raster
    # tolerance instead of rejecting an otherwise 99.9%-covered object.
    slot_limit = (
        float(max_unbaked_ratio)
        if max_material_slot_unbaked_ratio is None
        else float(max_material_slot_unbaked_ratio)
    )
    coverage_passed = (
        weighted_unbaked <= max_unbaked_ratio
        and max_slot_unbaked <= slot_limit
    )
    # ``IRFaceAtlasUV`` is constructed by the exporter with one private grid
    # tile per polygon.  For very dense foliage its tiles can be smaller than a
    # texel even at the saved (4K) bake resolution; a raster *overlap* estimate
    # then aliases adjacent, mathematically disjoint tiles into a false overlap.
    # Keep the estimate in the audit record, but accept only this exporter-owned
    # UV layout by construction.  Authored/Smart UVs retain the strict overlap
    # gate, so this never masks genuinely stacked source shells.
    overlap_passed = bool(known_disjoint_face_atlas) or (
        overlap["overlap_factor"] <= max_overlap_factor
        and overlap["max_material_slot_overlap_factor"] <= max_overlap_factor
    )
    uv_quality_passed = (
        uv_degenerate_surface_ratio <= max_degenerate_ratio
        and overlap_passed
    )
    result = {
        "passed": bool(coverage_passed and uv_quality_passed),
        "reason": (
            "pass" if coverage_passed and uv_quality_passed else
            "referenced_unbaked_texels" if not coverage_passed else
            "degenerate_uv_triangles" if uv_degenerate_surface_ratio > max_degenerate_ratio else
            "overlapping_uv_triangles"
        ),
        "input_triangle_count": int(original_triangle_count),
        "triangle_count": int(len(triangles)),
        "sample_count": int(valid.size),
        "coverage_pixel_fraction": float(np.asarray(coverage, bool).mean()),
        "referenced_unbaked_ratio": weighted_unbaked,
        "referenced_all_unbaked_ratio": weighted_all_unbaked,
        "max_material_slot_unbaked_ratio": float(max_slot_unbaked),
        "invalid_triangle_fraction": float(np.mean(invalid_fraction > 0)),
        "fully_invalid_triangle_fraction": float(np.mean(all_unbaked)),
        "uv_triangle_pixel_area_p01": float(np.percentile(uv_cross, 1)),
        "uv_triangle_pixel_area_p50": float(np.percentile(uv_cross, 50)),
        "uv_triangle_pixel_area_min": float(np.min(uv_cross)),
        "invalid_geometry_triangle_ratio": float(invalid_geometry_ratio),
        "degenerate_uv_triangle_ratio": float(uv_degenerate_count_ratio),
        "degenerate_uv_surface_ratio": float(uv_degenerate_surface_ratio),
        **overlap,
        "max_unbaked_ratio": float(max_unbaked_ratio),
        "max_material_slot_unbaked_ratio_limit": float(slot_limit),
        "max_degenerate_ratio": float(max_degenerate_ratio),
        "max_overlap_factor": float(max_overlap_factor),
        "overlap_validation": "face_atlas_by_construction" if known_disjoint_face_atlas else "raster_estimate",
        "per_material_slot": per_slot,
    }
    return result


def estimate_uv_overlap(
    triangles: np.ndarray,
    triangle_uv_areas: np.ndarray,
    material_indices: np.ndarray,
    *,
    resolution: int = 512,
) -> dict:
    """Estimate packed-UV overlap from analytic area divided by rasterized union.

    The union is rasterized without bake dilation, so atlas margin cannot hide an
    overlap.  A modest gate (default 1.10) absorbs center-sampling error from tiny
    subpixel islands while still rejecting duplicated/stacked UV shells.
    """
    triangles = np.asarray(triangles, np.float64).reshape(-1, 3, 2)
    uv_areas = np.asarray(triangle_uv_areas, np.float64).reshape(-1)
    slots = np.asarray(material_indices, np.int64).reshape(-1)
    resolution = max(32, int(resolution))

    def raster_union(rows: np.ndarray) -> float:
        mask = np.zeros((resolution, resolution), dtype=bool)
        for tri in rows:
            pts = np.clip(tri, 0.0, 1.0) * resolution
            y_start = max(0, int(np.ceil(float(np.min(pts[:, 1])) - 0.5)))
            y_stop = min(resolution - 1, int(np.floor(float(np.max(pts[:, 1])) - 0.5)))
            for iy in range(y_start, y_stop + 1):
                y = iy + 0.5
                xs = []
                for edge in range(3):
                    a, b = pts[edge], pts[(edge + 1) % 3]
                    lo, hi = sorted((float(a[1]), float(b[1])))
                    if not (lo <= y < hi) or abs(float(b[1] - a[1])) < 1e-15:
                        continue
                    t = (y - float(a[1])) / float(b[1] - a[1])
                    xs.append(float(a[0] + t * (b[0] - a[0])))
                if len(xs) < 2:
                    continue
                x0 = max(0, int(np.ceil(min(xs) - 0.5)))
                x1 = min(resolution - 1, int(np.floor(max(xs) - 0.5)))
                if x1 >= x0:
                    mask[iy, x0:x1 + 1] = True
        return float(mask.mean())

    def factor(rows: np.ndarray, areas: np.ndarray) -> tuple[float, float]:
        union = raster_union(rows)
        summed = float(np.sum(areas))
        raw = summed / max(union, 1.0 / (resolution * resolution))
        return max(1.0, raw), union

    global_factor, global_union = factor(triangles, uv_areas)
    per_slot = {}
    for slot in sorted(set(int(x) for x in slots)):
        selected = slots == slot
        slot_factor, slot_union = factor(triangles[selected], uv_areas[selected])
        per_slot[str(slot)] = {
            "overlap_factor": float(slot_factor),
            "uv_union_fraction": float(slot_union),
            "uv_area_sum": float(np.sum(uv_areas[selected])),
        }
    return {
        "overlap_factor": float(global_factor),
        "uv_union_fraction": float(global_union),
        "uv_area_sum": float(np.sum(uv_areas)),
        "max_material_slot_overlap_factor": float(
            max((row["overlap_factor"] for row in per_slot.values()), default=1.0)
        ),
        "overlap_raster_resolution": int(resolution),
        "per_material_slot_overlap": per_slot,
    }


def adaptive_resolutions(base_resolution: int, maximum_resolution: int) -> list[int]:
    """Power-of-two escalation including non-power-of-two endpoints exactly once."""
    base = max(1, int(base_resolution))
    maximum = max(base, int(maximum_resolution))
    values = [base]
    while values[-1] < maximum:
        values.append(min(maximum, values[-1] * 2))
    return values
