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


#: Least of the two axes the props may span, as a share of the floor slab.
#: A room whose objects all sit in one strip cannot be orbited: the camera
#: sampler needs a 1-2 m standoff and finds the ring falls outside the floor.
#: Measured on the generated rooms, a 7.7 x 6.0 m open office put all forty of
#: its props in a 0.9 m band (coverage 0.15) and yielded 28 poses against a
#: 50-pose floor, while two meeting rooms at 0.11 and 0.19 yielded none at all.
#: Every scene that reached the floor scored 0.79 or better, and only 14 of 384
#: scenes in the repository fall below 0.55, so this rejects a narrow, genuinely
#: unusable class rather than trimming the distribution.
MIN_OBJECT_SPREAD_FRACTION = 0.5


def _object_spread(authoring_map: dict[str, Any]) -> dict[str, Any] | None:
    """How much of the floor slab the props actually span, on its worse axis.

    Against the floor rather than the navigation regions: regions are inset by
    a robot radius, which would flatter a scene whose props hug the walls -- the
    exact case this measures.
    """
    slabs = []
    for record in authoring_map.get("objects") or []:
        name = str(record.get("id") or "").lower()
        kind = str(record.get("type") or record.get("kind") or "").lower()
        if not (name.endswith(".floor") or "floor" in kind):
            continue
        geometry = record.get("geometry") or {}
        size = geometry.get("size_m") or []
        if len(size) >= 3:
            try:
                slabs.append((float(size[0]), float(size[2])))
            except (TypeError, ValueError):
                continue
    # Measure the objects a camera would actually orbit, not every prop. Room-
    # spanning furniture reaches both walls in any scene and pins the ratio near
    # 1.0 whatever the small props do -- the first attempt measured that and
    # scored a room with all forty of its anchorables in one strip at 1.07.
    from .ir_object_anchors import candidate_anchors
    xs = [c["center_xy"][0] for c in candidate_anchors(authoring_map)]
    ys = [c["center_xy"][1] for c in candidate_anchors(authoring_map)]
    if not slabs or len(xs) < 5:
        return None
    floor_w = max(s[0] for s in slabs)
    floor_d = max(s[1] for s in slabs)
    if floor_w <= 0 or floor_d <= 0:
        return None
    span_x, span_y = max(xs) - min(xs), max(ys) - min(ys)
    return {"object_span_m": [round(span_x, 4), round(span_y, 4)],
            "floor_span_m": [round(floor_w, 4), round(floor_d, 4)],
            "coverage_fraction": round(min(span_x / floor_w, span_y / floor_d), 4),
            "minimum_coverage_fraction": MIN_OBJECT_SPREAD_FRACTION}


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
    spread = _object_spread(authoring_map)
    if spread is not None and spread["coverage_fraction"] < MIN_OBJECT_SPREAD_FRACTION:
        failures.append("object_placement_collapsed_to_strip")
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
            "room_footprint": footprint, "object_spread": spread}
    if source_scene_digest:
        core["source_scene_digest"] = source_scene_digest
    return {**core, "source_authoring_map_digest": _digest(authoring_map), "audit_digest": _digest(core)}
