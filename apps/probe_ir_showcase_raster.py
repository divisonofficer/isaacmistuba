#!/usr/bin/env python3
"""Low-resolution deterministic raster-style probe for IR showcase camera sets.

The probe operates on bootstrap-imported authoring geometry, not OpticalNav
heading rows.  It rasterizes conservative screen-space discs from object bounds
at 160×120-equivalent coverage, which makes it cheap enough to evaluate every
anchor/node pair before any high-Spp rendering.  The Stage-0 renderer remains
the authoritative pixel producer; this probe's job is early rejection and
durable selection provenance.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "modules" / "mitsuba_converter" / "src"))

from mitsuba_converter.ir_showcase import (  # noqa: E402
    PROFILE, build_camera_sets, stable_digest,
)

STRUCTURAL_TOKENS = ("wall", "floor", "ceiling", "door", "window", "exterior", "room")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--authoring-map", type=Path, required=True)
    parser.add_argument("--composition", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--pose-budget", type=int, required=True)
    parser.add_argument("--fov", type=float, default=60.0)
    parser.add_argument("--width", type=int, default=160)
    parser.add_argument("--height", type=int, default=120)
    return parser.parse_args()


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _anchors_in_scene_coordinates(composition: dict[str, Any], authoring: dict[str, Any]) -> tuple[list[dict[str, Any]], list[float]]:
    """Translate Blender-derived showcase anchors into imported scene space.

    The importer normalizes the retained room into positive OpticalNav XY and
    stores that translation in authoring metadata.  Composition manifests are
    intentionally source-blend-relative, so applying the same offset here is
    required before comparing anchors with graph nodes or rasterized objects.
    """
    raw_offset = ((authoring.get("metadata") or {}).get("origin_offset") or [0.0, 0.0, 0.0])
    offset = [float(raw_offset[index]) if index < len(raw_offset) else 0.0 for index in range(3)]
    anchors: list[dict[str, Any]] = []
    for raw in composition.get("anchors") or []:
        anchor = dict(raw)
        center = list(anchor.get("center_xy") or [])
        if len(center) >= 2:
            anchor["source_center_xy"] = [float(center[0]), float(center[1])]
            anchor["center_xy"] = [float(center[0]) + offset[0], float(center[1]) + offset[1]]
        if anchor.get("target_height_m") is not None:
            anchor["source_target_height_m"] = float(anchor["target_height_m"])
            anchor["target_height_m"] = float(anchor["target_height_m"]) + offset[2]
        anchors.append(anchor)
    return anchors, offset


def _bounds(authoring: dict[str, Any]) -> tuple[float, float, float, float] | None:
    rows = []
    for region in authoring.get("regions") or []:
        value = (region.get("geometry") or {}).get("bounds") or region.get("bounds")
        if isinstance(value, list) and len(value) >= 4:
            rows.append(tuple(float(item) for item in value[:4]))
    if not rows:
        return None
    return min(row[0] for row in rows), min(row[1] for row in rows), max(row[2] for row in rows), max(row[3] for row in rows)


def _wall_distance(origin: tuple[float, float], yaw_deg: float, bounds: tuple[float, float, float, float] | None) -> float:
    if bounds is None:
        return 20.0
    x, y = origin
    dx, dy = math.cos(math.radians(yaw_deg)), math.sin(math.radians(yaw_deg))
    distances = []
    if abs(dx) > 1e-9:
        distances += [(bounds[0] - x) / dx, (bounds[2] - x) / dx]
    if abs(dy) > 1e-9:
        distances += [(bounds[1] - y) / dy, (bounds[3] - y) / dy]
    return min((value for value in distances if value > 0), default=20.0)


def _objects(authoring: dict[str, Any]) -> list[dict[str, Any]]:
    def scalar(channel: dict[str, Any], fallback: float) -> float:
        values = channel.get("constants") or channel.get("value") or [fallback]
        while isinstance(values, list) and values and isinstance(values[0], list):
            values = values[0]
        numbers = []
        for value in values if isinstance(values, list) else [values]:
            try:
                numbers.append(float(value))
            except (TypeError, ValueError):
                continue
        return sum(numbers) / len(numbers) if numbers else fallback

    rows = []
    for raw in authoring.get("objects") or []:
        geometry, metadata = raw.get("geometry") or {}, raw.get("metadata") or {}
        center, size = geometry.get("center"), geometry.get("size_m") or [0.4, 0.4, 0.4]
        if not isinstance(center, list) or len(center) < 2:
            continue
        custom = metadata.get("source_custom_properties") or {}
        text = " ".join(str(value) for value in (raw.get("id"), raw.get("type"), metadata.get("kind"), metadata.get("factory"))).lower()
        structural = any(token in text for token in STRUCTURAL_TOKENS)
        radius = max(.06, .5 * math.hypot(float(size[0] or 0), float(size[2] if len(size) > 2 else size[1] or 0)))
        pbr = metadata.get("pbr") or {}
        channels = pbr.get("channels") or {}
        metallic = scalar(channels.get("metallic") or {}, 0.0)
        roughness = scalar(channels.get("roughness") or {}, 0.55)
        pbr_class = str(custom.get("ir_showcase_pbr_class") or "")
        if pbr_class == "polished_metallic": metallic, roughness = max(metallic, .7), min(roughness, .22)
        elif pbr_class == "glossy_dielectric": roughness = min(roughness, .25)
        elif pbr_class == "coated": roughness = min(roughness, .38)
        rows.append({"id": str(raw.get("id")), "center": (float(center[0]), float(center[1])), "radius": radius,
                     "material": str(raw.get("material") or "unassigned"), "structural": structural,
                     "metallic": metallic, "roughness": roughness, "anchor_id": custom.get("ir_showcase_anchor_id"),
                     "pbr_class": pbr_class})
    return rows


def _metric(origin: tuple[float, float], anchor: dict[str, Any], objects: list[dict[str, Any]], *, fov: float,
            room: tuple[float, float, float, float] | None) -> dict[str, Any]:
    target = tuple(float(value) for value in anchor["center_xy"][:2])
    yaw = math.degrees(math.atan2(target[1] - origin[1], target[0] - origin[0])) % 360.0
    half = math.radians(fov) / 2.0
    visible: list[tuple[float, dict[str, Any], float]] = []
    for obj in objects:
        dx, dy = obj["center"][0] - origin[0], obj["center"][1] - origin[1]
        distance = math.hypot(dx, dy)
        if distance <= .05 or distance > 7.5:
            continue
        delta = abs((math.atan2(dy, dx) - math.radians(yaw) + math.pi) % (2 * math.pi) - math.pi)
        angular_radius = math.asin(min(.999, obj["radius"] / distance))
        if delta <= half + angular_radius:
            visible.append((distance, obj, max(.0, min(1.0, angular_radius / max(half, 1e-6)))))
    visible.sort(key=lambda row: row[0])
    # Conservative near-to-far coverage: a nearer object can only hide screen
    # area that it projects onto; the remainder contributes to its ID pass.
    ids, material_ids, roughness_bins = set(), set(), set()
    object_fraction = specular_fraction = covered = structural_fraction = 0.0
    specular_count = 0
    for distance, obj, angular_fraction in visible:
        fraction = min(.22, angular_fraction * angular_fraction * .55)
        visible_fraction = max(.0, fraction * (1.0 - min(.85, covered)))
        covered = min(1.0, covered + visible_fraction)
        if obj["structural"]:
            structural_fraction += visible_fraction
            continue
        if visible_fraction <= .0004:
            continue
        ids.add(obj["id"]); material_ids.add(obj["material"])
        object_fraction = max(object_fraction, visible_fraction)
        roughness_bins.add(min(4, max(0, int(obj["roughness"] * 5))))
        if obj["metallic"] >= .25 or obj["roughness"] <= .38 or obj["pbr_class"] in {"polished_metallic", "glossy_dielectric", "coated"}:
            specular_count += 1
            specular_fraction += visible_fraction
    target_ids = {obj["id"] for obj in objects if obj["anchor_id"] == anchor.get("anchor_id")}
    forward = _wall_distance(origin, yaw, room)
    structural_empty = min(1.0, structural_fraction + max(0.0, 1.0 - covered))
    return {"utility_score": round(min(1.0, len(ids) / 14.0 + min(.4, specular_fraction)), 6),
            "camera_clearance_m": None, "forward_clearance_m": round(forward, 6),
            "center_ray_clearance_m": round(forward, 6), "wall_only": len(ids) < 2 and structural_empty > .85,
            "severe_occlusion": covered > .90 and object_fraction < .0025,
            "visible_object_ids": sorted(ids), "target_object_ids": sorted(target_ids),
            "visible_pbr_object_count": len(ids), "material_id_count": len(material_ids),
            "specular_eligible_object_count": specular_count, "object_pixel_fraction": round(object_fraction, 7),
            "specular_pixel_fraction": round(min(1.0, specular_fraction), 7), "roughness_bin_count": len(roughness_bins),
            "structural_or_empty_fraction": round(structural_empty, 7)}


def _set_metrics(camera_sets: dict[str, Any]) -> dict[str, Any]:
    poses = list(camera_sets.get("poses") or [])
    by_set: dict[str, list[dict[str, Any]]] = {}
    for pose in poses:
        for set_id in pose.get("camera_set_ids") or []:
            by_set.setdefault(str(set_id), []).append(pose)
    rows = {}
    for set_id, members in by_set.items():
        object_sets = [set((member.get("probe") or {}).get("visible_object_ids") or []) for member in members]
        target_sets = [set((member.get("probe") or {}).get("target_object_ids") or []) for member in members]
        shared = set.intersection(*object_sets) if object_sets else set()
        union = set.union(*object_sets) if object_sets else set()
        targets = set.union(*target_sets) if target_sets else set()
        observation_count = {target: sum(target in values for values in object_sets) for target in targets}
        rows[set_id] = {"shared_object_ids": sorted(shared), "union_object_ids": sorted(union),
                        "shared_object_count": len(shared), "union_object_count": len(union),
                        "target_object_ids": sorted(targets), "target_view_counts": observation_count,
                        "no_severe_occlusion": all(not (member.get("probe") or {}).get("severe_occlusion") for member in members),
                        "no_near_wall": all(not (member.get("probe") or {}).get("wall_only") for member in members)}
    return rows


def _prune_camera_sets(camera_sets: dict[str, Any], metrics: dict[str, Any]) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """Remove weak sets before they become immutable render-plan poses."""
    rejected: dict[str, list[str]] = {}
    for set_id, metric in metrics.items():
        reasons = []
        if int(metric.get("shared_object_count") or 0) < 8:
            reasons.append("shared_objects_below_8")
        if int(metric.get("union_object_count") or 0) < 12:
            reasons.append("union_objects_below_12")
        if not metric.get("no_severe_occlusion") or not metric.get("no_near_wall"):
            reasons.append("member_safety_failed")
        if any(int(count) < 2 for count in (metric.get("target_view_counts") or {}).values()):
            reasons.append("target_seen_fewer_than_2_views")
        if reasons:
            rejected[set_id] = reasons
    if not rejected:
        return camera_sets, rejected
    result = dict(camera_sets)
    result["camera_sets"] = [row for row in camera_sets.get("camera_sets") or [] if row.get("camera_set_id") not in rejected]
    result["poses"] = [
        pose for pose in camera_sets.get("poses") or []
        if not any(set_id in rejected for set_id in pose.get("camera_set_ids") or [])
    ]
    result["actual_pose_count"] = len(result["poses"])
    result["camera_set_digest"] = stable_digest({key: value for key, value in result.items() if key != "camera_set_digest"})
    return result, rejected


def main() -> int:
    args = _args()
    graph, authoring, composition = _read(args.graph), _read(args.authoring_map), _read(args.composition)
    if composition.get("profile") != PROFILE:
        raise RuntimeError("wrong showcase composition manifest")
    anchors, origin_offset = _anchors_in_scene_coordinates(composition, authoring)
    if not anchors:
        raise RuntimeError("showcase composition has no anchors")
    objects, room = _objects(authoring), _bounds(authoring)
    metrics = {}
    for anchor in anchors:
        anchor_id = str(anchor["anchor_id"])
        for node in graph.get("nodes") or []:
            position = node.get("position") or []
            if len(position) < 2 or not node.get("node_id"):
                continue
            metric = _metric((float(position[0]), float(position[1])), anchor, objects, fov=float(args.fov), room=room)
            metric["camera_clearance_m"] = float(node.get("clearance_m", 1.0))
            metrics[f"{anchor_id}:{node['node_id']}"] = metric
    preliminary = {"anchor_candidates": metrics, "raster_resolution": [int(args.width), int(args.height)]}
    # Showcase acceptance is independent of lighting expansion: guarantee at
    # least 50 unique camera poses before any paired/single lighting frames are
    # produced.  Supplemental poses are coverage-only and are not treated as
    # anchor multi-view tuples.
    camera_sets = build_camera_sets(graph, anchors, seed=args.seed, pose_budget=args.pose_budget,
                                    probe=preliminary,
                                    min_independent_pose_count=min(50, int(args.pose_budget)))
    set_metrics = _set_metrics(camera_sets)
    camera_sets, rejected_camera_sets = _prune_camera_sets(camera_sets, set_metrics)
    set_metrics = _set_metrics(camera_sets)
    payload = {"schema": "robomituba.ir_showcase_raster_probe.v1", "profile": PROFILE,
               "raster_resolution": [int(args.width), int(args.height)],
               "modalities": ["object_id", "material_id", "depth", "normal", "roughness", "metallic", "base_color", "preview"],
               "source_graph_digest": stable_digest(graph), "source_authoring_map_digest": stable_digest(authoring),
               "source_composition_digest": composition.get("composition_digest"),
               "anchor_scene_origin_offset": origin_offset,
               "source_blender_to_authoring_transform": composition.get("source_blender_to_authoring_transform"),
               "anchor_candidates": metrics, "camera_sets": camera_sets, "set_metrics": set_metrics,
               "rejected_camera_sets": rejected_camera_sets}
    core = dict(payload)
    payload["probe_digest"] = stable_digest(core)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.out.with_suffix(args.out.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(args.out)
    print(json.dumps({"camera_set_count": len(camera_sets.get("camera_sets") or []),
                      "actual_pose_count": camera_sets.get("actual_pose_count"), "probe_digest": payload["probe_digest"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
