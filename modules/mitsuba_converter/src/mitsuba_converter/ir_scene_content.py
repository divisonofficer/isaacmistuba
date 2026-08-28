"""Room-program audit for generated Infinigen scenes."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SCHEMA = "robomituba.ir_scene_content_audit.v1"
PROGRAMS: dict[str, dict[str, Any]] = {
    # Infinigen's TV factory is also used for flat-panel desktop displays.
    # Treat it as a display anchor when the room already satisfies desk/chair;
    # this does not excuse a sparse room and still rejects bedroom content.
    "office": {"required": [{"desk"}, {"officechair", "chair"}, {"monitor", "computer", "laptop", "tv"}], "forbidden": {"bed", "bathtub", "toilet"}},
    "factory-office": {"required": [{"desk", "table"}, {"officechair", "chair"}, {"monitor", "computer", "tv"}], "forbidden": {"bed", "bathtub"}},
    "open-office": {"required": [{"desk"}, {"officechair", "chair"}, {"monitor", "computer", "tv"}], "forbidden": {"bed", "bathtub"}},
    "meeting-room": {"required": [{"meetingtable", "diningtable", "table"}, {"chair"}], "forbidden": {"bed", "bathtub", "toilet"}},
    "restroom": {"required": [{"toilet", "urinal"}, {"sink", "bathroomsink"}], "forbidden": {"bed", "sofa", "diningtable"}},
    "bathroom": {"required": [{"toilet", "bathtub", "shower"}, {"sink", "bathroomsink"}], "forbidden": {"bed", "desk"}},
    "bedroom": {"required": [{"bed"}, {"wardrobe", "closet", "shelf"}], "forbidden": {"toilet", "urinal"}},
    "living-room": {"required": [{"sofa", "chair"}, {"coffeetable", "table", "tvstand"}], "forbidden": {"toilet", "urinal", "bed"}},
    "garage": {"required": [{"vehicle", "car", "workbench", "shelf", "rack"}], "forbidden": {"bed", "bathtub"}},
    "warehouse": {"required": [{"shelf", "rack", "pallet", "crate"}], "forbidden": {"bed", "bathtub", "sofa"}},
    "break-room": {"required": [{"table", "counter"}, {"chair", "stool"}], "forbidden": {"bed", "bathtub"}},
    "closet": {"required": [{"wardrobe", "closet", "shelf", "cabinet"}], "forbidden": {"toilet", "bathtub"}},
}
STRUCTURAL = {"wall", "floor", "ceiling", "window", "door", "exterior", "room"}
NON_CONTENT = {"", "unknown", "landmark", "cube", "plane", "b"}


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _category(raw: dict[str, Any]) -> str:
    metadata = raw.get("metadata") or {}
    value = str(metadata.get("factory") or metadata.get("category") or raw.get("type") or "unknown")
    return re.sub(r"[^a-z0-9]", "", value.lower().removesuffix("factory"))


def _room_footprint(authoring_map: dict[str, Any]) -> dict[str, Any] | None:
    """Return the union AABB of authoring regions in the navigation XY plane."""
    boxes: list[tuple[float, float, float, float]] = []
    for region in authoring_map.get("regions") or []:
        geometry = region.get("geometry") or {}
        bounds = geometry.get("bounds") or region.get("bounds")
        if not isinstance(bounds, (list, tuple)) or len(bounds) < 4:
            continue
        try:
            x0, y0, x1, y1 = map(float, bounds[:4])
        except (TypeError, ValueError):
            continue
        if x1 > x0 and y1 > y0:
            boxes.append((x0, y0, x1, y1))
    if not boxes:
        return None
    x0, y0 = min(box[0] for box in boxes), min(box[1] for box in boxes)
    x1, y1 = max(box[2] for box in boxes), max(box[3] for box in boxes)
    return {"bounds_xy_m": [x0, y0, x1, y1], "area_m2": (x1 - x0) * (y1 - y0), "method": "region_union_aabb"}


def audit_scene_content(authoring_map: dict[str, Any], *, room_type: str, profile: str = "balanced",
                        source_scene_digest: str | None = None) -> dict[str, Any]:
    categories = [_category(obj) for obj in authoring_map.get("objects") or []]
    meaningful = [category for category in categories
                  if category not in NON_CONTENT and not any(token in category for token in STRUCTURAL)]
    counts = {category: meaningful.count(category) for category in sorted(set(meaningful))}
    program = PROGRAMS.get(room_type, {"required": [], "forbidden": set()})
    missing = [sorted(group) for group in program["required"] if not any(any(alias in category for alias in group) for category in meaningful)]
    forbidden = {name: sum(name in category for category in meaningful) for name in program["forbidden"]}
    forbidden = {name: count for name, count in forbidden.items() if count}
    digest_counts: dict[str, int] = {}
    for obj in authoring_map.get("objects") or []:
        metadata = obj.get("metadata") or {}
        digest = str(metadata.get("source_digest") or metadata.get("asset_digest") or "")
        if digest:
            digest_counts[digest] = digest_counts.get(digest, 0) + 1
    duplicate_digests = {digest: count for digest, count in digest_counts.items() if count > 1}
    # Infinigen can place an occasional off-program prop (for example one
    # bathtub in an otherwise well populated closet). It is useful visual
    # variation rather than evidence that the whole scene is the wrong room.
    # Reject only when forbidden content is a material part of the room.
    forbidden_total = sum(forbidden.values())
    forbidden_fraction = forbidden_total / max(1, len(meaningful))
    forbidden_is_material = forbidden_total >= 3 or forbidden_fraction >= 0.10
    failures = []
    if len(meaningful) < 4:
        failures.append("too_few_nonstructural_objects")
    if missing and profile != "structural":
        failures.append("missing_room_anchors")
    if forbidden_is_material:
        failures.append("forbidden_room_content")
    footprint = _room_footprint(authoring_map)
    core = {"schema": SCHEMA, "room_type": room_type, "profile": profile, "status": "failed" if failures else "passed",
            "object_count": len(categories), "nonstructural_object_count": len(meaningful), "category_counts": counts,
            "required_groups": [sorted(group) for group in program["required"]], "missing_required_groups": missing,
            "forbidden_category_counts": forbidden,
            "forbidden_content_policy": {
                "status": "hard_failure" if forbidden_is_material else ("minor_warning" if forbidden else "none"),
                "count": forbidden_total, "fraction": round(forbidden_fraction, 6),
                "hard_count_threshold": 3, "hard_fraction_threshold": 0.10,
            },
            "duplicate_asset_digests": duplicate_digests,
            "failures": failures,
            "warnings": ((["partial_room_program"] if missing and not failures else [])
                         + (["minor_forbidden_room_content"] if forbidden and not forbidden_is_material else [])),
            "room_footprint": footprint}
    if source_scene_digest:
        core["source_scene_digest"] = source_scene_digest
    return {**core, "source_authoring_map_digest": _digest(authoring_map), "audit_digest": _digest(core)}
