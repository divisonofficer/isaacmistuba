"""Deterministic, child-scene quality variants for imported apartments.

The helpers in this module only mutate an in-memory authoring map.  The caller
is responsible for creating a new scene directory, which makes A/B variants
safe to inspect and render without changing the imported baseline.
"""
from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Iterable

from .navigation_blockers import navigation_blocker_candidates
from .object_footprint import footprint_bbox, object_footprint

HDR_ENVIRONMENT = "/bean/hdr/o8_sG_12-25-20-00-00/dataset/env_rgb.exr"
LIGHTING_PROFILES = frozenset({"softbox_only", "softbox_hdr"})
ORPHAN_POLICIES = frozenset({"support_validate_remove", "audit_only"})
_TABLETOP_TOKENS = ("lamp", "tableware", "cup", "bowl", "plate", "bottle", "fruit", "vase", "candle", "book")
_SUPPORT_TOKENS = ("table", "desk", "counter", "cabinet", "shelf", "nightstand", "bed", "stool")


def canonical_digest(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def traversable_regions(authoring_map: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for index, region in enumerate(authoring_map.get("regions") or []):
        geometry = region.get("geometry") or {}
        bounds = geometry.get("bounds")
        if region.get("type") == "traversable" and isinstance(bounds, list) and len(bounds) >= 4:
            result.append({"id": str(region.get("id") or f"room_{index:02d}"), "bounds": [float(v) for v in bounds[:4]]})
    return result


def _softbox_count(width: float, depth: float) -> int:
    area = max(0.0, width * depth)
    return 1 if area < 35.0 else 2 if area < 65.0 else 3 if area < 105.0 else 4


def _softbox_positions(bounds: list[float], count: int) -> list[tuple[float, float]]:
    x0, y0, x1, y1 = bounds
    width, depth = x1 - x0, y1 - y0
    cx, cy = x0 + width / 2.0, y0 + depth / 2.0
    if count == 1:
        return [(cx, cy)]
    if count == 2:
        return ([(x0 + width / 3.0, cy), (x0 + width * 2.0 / 3.0, cy)] if width >= depth
                else [(cx, y0 + depth / 3.0), (cx, y0 + depth * 2.0 / 3.0)])
    if count == 3:
        return ([(x0 + width * f, cy) for f in (0.25, 0.50, 0.75)] if width >= depth * 1.45
                else [(cx, y0 + depth * f) for f in (0.25, 0.50, 0.75)] if depth >= width * 1.45
                else [(x0 + width * .30, y0 + depth * .35), (x0 + width * .70, y0 + depth * .35), (x0 + width * .50, y0 + depth * .68)])
    return [(x0 + width * x, y0 + depth * y) for x, y in ((.33, .33), (.67, .33), (.33, .67), (.67, .67))]


def apply_room_softboxes(authoring_map: dict[str, Any], *, ceiling_height_m: float = 2.6,
                         gap_m: float = .05, radiance: float = 4.5) -> list[dict[str, Any]]:
    """Replace synthetic softboxes with deterministic room-level emitters."""
    objects = []
    for obj in authoring_map.get("objects") or []:
        if str(obj.get("id") or "").startswith("light_softbox_"):
            continue
        # Imported fixture meshes remain visible but softboxes become the
        # single controlled illumination variable for the A/B experiment.
        if obj.get("is_emitter"):
            obj = dict(obj)
            obj["is_emitter"] = False
            obj["emitter_intensity"] = 0.0
            obj["emitter_radiance"] = [0.0, 0.0, 0.0]
            obj.pop("emitter_shape", None)
            obj.setdefault("metadata", {})["lighting_policy"] = "decorative_non_emitting_fixture"
        objects.append(obj)
    softboxes: list[dict[str, Any]] = []
    for room in traversable_regions(authoring_map):
        x0, y0, x1, y1 = room["bounds"]
        width, depth = max(.1, x1 - x0), max(.1, y1 - y0)
        count = _softbox_count(width, depth)
        target_area = width * depth * .12 / count
        sx = min(2.2, max(.8, math.sqrt(max(target_area, .64))))
        sz = min(2.2, max(.8, target_area / sx))
        sx, sz = min(sx, width * .8), min(sz, depth * .8)
        for index, (x, y) in enumerate(_softbox_positions(room["bounds"], count)):
            softboxes.append({
                "id": f"light_softbox_{room['id']}_{index:02d}", "type": "landmark",
                "label": f"Softbox {room['id']} {index:02d}", "placement": "point", "category": "ceiling_light",
                "source_ref": None, "material": "infinigen_default", "navigation": {"blocks_navigation": False},
                "geometry": {"type": "point", "center": [round(x, 4), round(y, 4)], "yaw_deg": 0.0,
                             "pitch_deg": 0.0, "roll_deg": 0.0, "size_m": [round(sx, 4), .04, round(sz, 4)],
                             "base_height_m": round(ceiling_height_m - gap_m, 4)},
                "is_emitter": True, "emitter_shape": "ceiling_panel", "emitter_radiance": [radiance] * 3,
                "emitter_intensity": 1.0,
                "metadata": {"kind": "room_softbox", "region_id": room["id"], "region_bounds": room["bounds"],
                             "normal_world": [0.0, -1.0, 0.0], "lighting_policy": "quality_ab_room_softbox"},
            })
    authoring_map["objects"] = objects + softboxes
    return softboxes


def apply_lighting_profile(authoring_map: dict[str, Any], profile: str) -> dict[str, Any]:
    if profile not in LIGHTING_PROFILES:
        raise ValueError(f"unsupported lighting profile: {profile}")
    softboxes = apply_room_softboxes(authoring_map)
    environment = dict(authoring_map.get("environment") or {})
    if profile == "softbox_hdr":
        environment.update({"mode": "envmap", "envmap_ref": HDR_ENVIRONMENT, "intensity": .25, "background_visible": True})
    authoring_map["environment"] = environment
    return {"profile": profile, "softbox_count": len(softboxes), "environment": environment}


def _is_tabletop_prop(obj: dict[str, Any]) -> bool:
    text = " ".join(str(obj.get(key) or "") for key in ("id", "label", "type")).lower()
    return any(token in text for token in _TABLETOP_TOKENS)


def _is_support(obj: dict[str, Any]) -> bool:
    text = " ".join(str(obj.get(key) or "") for key in ("id", "label", "type")).lower()
    return any(token in text for token in _SUPPORT_TOKENS)


def _overlap_area(first: tuple, second: tuple) -> float:
    ax0, ay0, ax1, ay1 = footprint_bbox(first)
    bx0, by0, bx1, by1 = footprint_bbox(second)
    return max(0.0, min(ax1, bx1) - max(ax0, bx0)) * max(0.0, min(ay1, by1) - max(ay0, by0))


def support_validation(objects: Iterable[dict[str, Any]], *, tolerance_m: float = .12) -> list[dict[str, Any]]:
    """Find raised tabletop props without a remaining compatible support.

    This intentionally does not classify freestanding furniture.  A candidate
    must match a tabletop token and be above floor tolerance; therefore the
    pass cannot turn a floor chair or a wall-mounted fixture into a deletion.
    """
    rows = [obj for obj in objects if isinstance(obj, dict)]
    supports = [(obj, object_footprint(obj.get("geometry") or {})) for obj in rows if _is_support(obj)]
    unsupported = []
    for obj in rows:
        geometry = obj.get("geometry") or {}
        base = float(geometry.get("base_height_m") or 0.0)
        footprint = object_footprint(geometry)
        if not _is_tabletop_prop(obj) or base <= tolerance_m or footprint is None:
            continue
        matched = None
        for support, support_fp in supports:
            if support_fp is None or support is obj:
                continue
            sg = support.get("geometry") or {}
            size = sg.get("size_m") or []
            top = float(sg.get("base_height_m") or 0.0) + (abs(float(size[1])) if len(size) >= 2 else 0.0)
            if abs(base - top) <= tolerance_m and _overlap_area(footprint, support_fp) > 1e-4:
                matched = str(support.get("id") or "")
                break
        if matched is None:
            unsupported.append({"object_id": str(obj.get("id") or ""), "base_height_m": round(base, 4),
                                "reason": "unsupported_tabletop_prop"})
    return unsupported


def apply_blocker_and_orphan_policy(authoring_map: dict[str, Any], *, remove_blocker_ids: Iterable[str] = (),
                                    orphan_policy: str = "support_validate_remove") -> dict[str, Any]:
    if orphan_policy not in ORPHAN_POLICIES:
        raise ValueError(f"unsupported orphan policy: {orphan_policy}")
    objects = list(authoring_map.get("objects") or [])
    requested = {str(value) for value in remove_blocker_ids}
    candidates = {row["object_id"]: row for row in navigation_blocker_candidates(objects)}
    unknown = requested - set(candidates)
    if unknown:
        raise ValueError(f"requested blocker ids are not removable candidates: {sorted(unknown)}")
    objects = [obj for obj in objects if str(obj.get("id") or "") not in requested]
    initial_unsupported = support_validation(objects)
    unsupported = list(initial_unsupported)
    removed_orphans: set[str] = set()
    # A small prop can accidentally be classified as a support for another
    # small prop.  Remove in rounds so the final published child has no
    # transitive floating chain, while retaining the full pre-policy audit.
    if orphan_policy == "support_validate_remove":
        while unsupported:
            round_ids = {row["object_id"] for row in unsupported}
            removed_orphans.update(round_ids)
            objects = [obj for obj in objects if str(obj.get("id") or "") not in round_ids]
            unsupported = support_validation(objects)
    authoring_map["objects"] = objects
    return {"blocker_candidates": list(candidates.values()), "removed_blockers": [candidates[key] for key in sorted(requested)],
            "unsupported_before_policy": initial_unsupported, "removed_orphans": sorted(removed_orphans),
            "unsupported_after_policy": support_validation(authoring_map["objects"]), "policy": orphan_policy}
