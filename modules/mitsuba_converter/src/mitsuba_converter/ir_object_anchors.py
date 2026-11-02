"""Object anchors for object-centric IR camera placement.

The IR camera universe has been the navigation viewpoint graph: positions from a
Poisson-disk floor sample, and at every position the same fixed 24-way yaw
sweep, all at one near-horizontal pitch.  Nothing in that aims at anything, so a
sizeable share of frames face a bare wall, and the camera-to-surface distance is
whatever the room geometry happens to give.

This derives what the camera should look *at*: the scene's own objects, from the
authoring map that the graph, plan and queue already share.

Coordinates come from ``geometry.center``, ``geometry.size_m`` and
``geometry.base_height_m``, never from ``metadata.world_bbox_*`` -- the latter is
object-local and pre-``origin_offset`` (verified: an object whose centre is
[2.1, 15.314] reports a bbox starting at [-0.431, -0.269, 0.0]), so using it
would place every anchor near the world origin.  ``size_m`` is ordered
``[x_extent, vertical_extent, authoring_y_extent]``.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from typing import Any, Iterable, Mapping, Sequence

SCHEMA = "robomituba.ir_object_anchors.v1"
ANCHOR_VERSION = "authoring-map-object-anchor-v1"

#: Reused from the visibility probe so structural filtering stays one rule.
STRUCTURAL_TOKENS = ("wall", "floor", "ceiling", "door", "window", "exterior", "room")
#: Objects mounted at or above this are ceiling fixtures, not things to inspect.
CEILING_FIXTURE_HEIGHT_M = 2.2
MIN_EXTENT_M = 0.15
#: Anything larger cannot be framed from a 1-2 m standoff without
#: dominating the shot, and the working distance is the constraint we
#: may not relax -- active NIR irradiance falls as 1/r^2.
MAX_EXTENT_M = 1.2
#: Preferred planar separation between two admitted anchors, so a shelf of
#: bottles does not consume the whole budget.
MIN_ANCHOR_SPACING_M = 0.8
#: Infinigen does not spread props evenly through a room: in a measured 39.8 m²
#: open office, 1036 of 1128 candidate pairs sat closer than 0.8 m and the
#: median separation was 0.365 m, because the props are packed onto a few
#: surfaces rather than distributed. A fixed 0.8 m floor then admitted 2 anchors
#: out of 43 candidates and the scene could not reach its pose budget.
#:
#: Relax the separation in steps until the scene yields enough anchors. Spread
#: is still preferred -- an evenly furnished room never leaves the first rung --
#: and the spacing actually used is recorded so a sparse selection is legible
#: rather than silent.
ANCHOR_SPACING_LADDER_M = (0.8, 0.6, 0.45, 0.35, 0.25)
#: Below this the remaining candidates are neighbours on one surface, and a
#: camera orbiting either sees the same thing.
ANCHOR_RELAX_TARGET = 12

MAX_PER_FACTORY = 3
#: Small props are grouped into one composite anchor: a 0.1 m bottle alone fills
#: too little of the frame at a metre to be worth a capture set.
CLUSTER_RADIUS_M = 0.45
CLUSTER_MIN_EXTENT_M = 0.30


def stable_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _text(record: Mapping[str, Any]) -> str:
    meta = record.get("metadata") or {}
    return " ".join(str(v or "").lower() for v in (
        record.get("id"), record.get("type"), record.get("label"),
        meta.get("factory"), meta.get("kind"), meta.get("semantic_type"),
    ))


def _category(record: Mapping[str, Any]) -> str:
    meta = record.get("metadata") or {}
    factory = str(meta.get("factory") or meta.get("kind") or record.get("type") or "unknown")
    return factory.removesuffix("Factory").split("_")[0].lower()


def _geometry(record: Mapping[str, Any]) -> tuple[float, float, float, float, float, float] | None:
    """Return ``(x, z_planar, half_x, half_y_planar, centre_height, vertical_extent)``.

    The vertical extent is carried separately from ``centre_height``: the camera
    sampler needs the object's real height to frame it, and substituting the
    planar extent for it made flat props (a book, chopsticks on a table) look
    several times taller than they are.
    """
    geometry = record.get("geometry") or {}
    centre = geometry.get("center")
    size = geometry.get("size_m") or []
    if not isinstance(centre, (list, tuple)) or len(centre) < 2 or len(size) < 3:
        return None
    try:
        x, planar_y = float(centre[0]), float(centre[1])
        ex, vertical, ey = float(size[0]), float(size[1]), float(size[2])
        base = float(geometry.get("base_height_m") or 0.0)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(v) for v in (x, planar_y, ex, vertical, ey, base)):
        return None
    return x, planar_y, ex / 2.0, ey / 2.0, base + vertical / 2.0, vertical


def _is_structural(record: Mapping[str, Any]) -> bool:
    text = _text(record)
    if any(token in text for token in STRUCTURAL_TOKENS):
        return True
    return str(record.get("type") or "").lower() in {"floor", "ceiling", "wall", "__room_shell__"}


def candidate_anchors(authoring_map: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every object that could reasonably be looked at, before selection."""
    out: list[dict[str, Any]] = []
    for record in authoring_map.get("objects") or []:
        if _is_structural(record) or record.get("is_emitter"):
            continue
        parsed = _geometry(record)
        if parsed is None:
            continue
        x, y, hx, hy, height, vertical = parsed
        extent = max(hx, hy) * 2.0
        # A tall thin object overflows the frame just as surely as a wide
        # one, so the size band is judged on every axis.
        if max(extent, vertical) > MAX_EXTENT_M or height >= CEILING_FIXTURE_HEIGHT_M:
            continue
        pbr = ((record.get("metadata") or {}).get("pbr") or {}).get("channels") or {}
        out.append({
            "object_id": str(record.get("id") or ""),
            "category": _category(record),
            "factory": str((record.get("metadata") or {}).get("factory") or ""),
            "center_xy": [x, y],
            "half_extent_xy": [hx, hy],
            "height_m": round(height, 6),
            "vertical_extent_m": round(vertical, 6),
            "extent_m": round(extent, 6),
            "pbr_channels": sorted(pbr),
        })
    return out


def _cluster(small: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Merge nearby small props into composite anchors."""
    remaining = list(small)
    clusters: list[dict[str, Any]] = []
    while remaining:
        seed = remaining.pop(0)
        members = [seed]
        keep = []
        for other in remaining:
            if math.dist(seed["center_xy"], other["center_xy"]) <= CLUSTER_RADIUS_M:
                members.append(other)
            else:
                keep.append(other)
        remaining = keep
        if len(members) < 2:
            continue
        xs = [m["center_xy"][0] for m in members]
        ys = [m["center_xy"][1] for m in members]
        hx = max(max(xs) - min(xs), max(m["half_extent_xy"][0] for m in members)) / 1.0
        hy = max(max(ys) - min(ys), max(m["half_extent_xy"][1] for m in members)) / 1.0
        clusters.append({
            "object_id": f"cluster:{members[0]['object_id']}",
            "category": members[0]["category"], "factory": "",
            "center_xy": [sum(xs) / len(xs), sum(ys) / len(ys)],
            "half_extent_xy": [max(hx / 2.0, CLUSTER_MIN_EXTENT_M / 2.0),
                               max(hy / 2.0, CLUSTER_MIN_EXTENT_M / 2.0)],
            "height_m": round(sum(m["height_m"] for m in members) / len(members), 6),
            "vertical_extent_m": round(max(m["vertical_extent_m"] for m in members), 6),
            "extent_m": round(max(hx, hy), 6),
            "pbr_channels": sorted({c for m in members for c in m["pbr_channels"]}),
            "member_object_ids": [m["object_id"] for m in members],
        })
    return clusters


def build_object_anchors(
    authoring_map: Mapping[str, Any], *, seed: int, max_anchors: int = 24,
) -> dict[str, Any]:
    """Select spatially spread, category-diverse anchors from the authoring map."""
    candidates = candidate_anchors(authoring_map)
    large = [c for c in candidates if c["extent_m"] >= MIN_EXTENT_M]
    small = [c for c in candidates if c["extent_m"] < MIN_EXTENT_M]
    pool = large + _cluster(small)

    rng = random.Random(int(seed))
    # Rank by material richness and category, with a deterministic tiebreak.
    def score(row: Mapping[str, Any]) -> tuple[float, str]:
        richness = len(row["pbr_channels"]) / 4.0
        size_fit = 1.0 - abs(math.log(max(row["extent_m"], 1e-3) / 0.6))
        return (-(richness + size_fit + rng.random() * 0.05), str(row["object_id"]))

    ordered = sorted(pool, key=score)

    def admit(spacing: float) -> list[Mapping[str, Any]]:
        keep: list[Mapping[str, Any]] = []
        counts: dict[str, int] = {}
        for candidate in ordered:
            if len(keep) >= max_anchors:
                break
            factory = candidate["factory"] or candidate["category"]
            if counts.get(factory, 0) >= MAX_PER_FACTORY:
                continue
            if any(math.dist(candidate["center_xy"], other["center_xy"]) < spacing
                   for other in keep):
                continue
            counts[factory] = counts.get(factory, 0) + 1
            keep.append(candidate)
        return keep

    spacing_used = ANCHOR_SPACING_LADDER_M[0]
    admitted = admit(spacing_used)
    for spacing in ANCHOR_SPACING_LADDER_M[1:]:
        if len(admitted) >= min(ANCHOR_RELAX_TARGET, max_anchors):
            break
        spacing_used = spacing
        admitted = admit(spacing)

    selected: list[dict[str, Any]] = []
    for row in admitted:
        anchor_id = "obj:" + "".join(
            ch if ch.isalnum() or ch in "._-" else "_" for ch in row["object_id"]
        )[:64]
        selected.append({
            **row, "anchor_id": anchor_id,
            # Mitsuba world is Y-up: (x, height, authoring_y).
            "center_mitsuba": [row["center_xy"][0], row["height_m"], row["center_xy"][1]],
            "vertical_extent_m": row["vertical_extent_m"],
            "target_height_m": row["height_m"],
        })

    core = {
        "schema": SCHEMA, "anchor_version": ANCHOR_VERSION,
        "source_authoring_map_digest": stable_digest(authoring_map),
        "sampling_seed": int(seed), "requested_anchor_count": int(max_anchors),
        "anchor_spacing_m": round(float(spacing_used), 3),
        "anchor_spacing_relaxed": bool(spacing_used < ANCHOR_SPACING_LADDER_M[0]),
        "candidate_count": len(pool), "anchor_count": len(selected),
        "anchors": selected,
    }
    return {**core, "anchor_digest": stable_digest(core)}


__all__ = [
    "ANCHOR_VERSION", "CEILING_FIXTURE_HEIGHT_M", "MAX_EXTENT_M", "MIN_EXTENT_M",
    "SCHEMA", "build_object_anchors", "candidate_anchors", "is_structural", "stable_digest",
]

#: Public alias: the 6-DoF camera sampler needs the same structural rule so the
#: room shell never enters the occluder set as one room-sized box.
is_structural = _is_structural
