"""Pure-Python acceptance checks for the wide glass office population.

The Blender probe supplies one record per generated factory root.  Keeping this
module Blender-free makes the business rules directly unit-testable and ensures
that a failed candidate can be rejected before it is promoted to ``full/``.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from typing import Iterable


DOMESTIC_MARKERS = (
    "bedfactory", "bedframefactory", "mattressfactory", "pillowfactory",
    "blanketfactory", "comforterfactory",
)


def classify_factory(record: dict) -> str | None:
    value = " ".join(str(record.get(key) or "") for key in ("factory", "name", "asset_key")).lower()
    if any(marker in value for marker in DOMESTIC_MARKERS):
        return "domestic"
    if "simpledeskfactory" in value:
        return "desk"
    if "officechairfactory" in value:
        return "office_chair"
    if "chairfactory" in value:
        return "chair"
    if "monitorfactory" in value:
        return "monitor"
    if "tablediningfactory" in value:
        return "meeting_table"
    if "toiletfactory" in value:
        return "toilet"
    if "bathroomsinkfactory" in value or "standingsinkfactory" in value:
        return "sink"
    if "largeshelffactory" in value:
        return "shelf"
    if "rackfactory" in value:
        return "rack"
    return None


def _room_type(room_id: str) -> str:
    return str(room_id).split("_", 1)[0]


def _count(items: Iterable[dict], kind: str) -> int:
    return sum(1 for item in items if item.get("kind") == kind)


def audit_population(records: Iterable[dict], office_manifest: dict) -> dict:
    """Return a deterministic audit document; no Blender or filesystem access."""
    profile = office_manifest.get("profile") or (office_manifest.get("office_profile") or {}).get("profile")
    if profile != "modern_glass_office_v2":
        raise ValueError("office population audit only accepts modern_glass_office_v2")

    rooms = list(office_manifest.get("room_ids") or [])
    if not rooms:
        raise ValueError("office population audit requires room_ids from the source floor plan")
    work_bays = list(office_manifest.get("work_bay_rooms") or [])
    if not (3 <= len(work_bays) <= 4):
        raise ValueError("wide office must declare three or four work bays")
    reception_support_rooms = list(office_manifest.get("reception_support_rooms") or [])
    if len(reception_support_rooms) != 1:
        raise ValueError("wide office must declare exactly one reception/support room")

    normalized = []
    for raw in records:
        item = dict(raw)
        item["room"] = item.get("room")
        item["kind"] = item.get("kind") or classify_factory(item)
        if item["kind"]:
            normalized.append(item)

    errors: list[str] = []
    glass_spec = office_manifest.get("structural_glass") or {}
    segments = glass_spec.get("segments") or []
    if int(glass_spec.get("requested_partition_count") or 0) != 10 or len(segments) != 10:
        errors.append("structural glass contract is not ten partitions")
    if int(glass_spec.get("requested_pane_count") or 0) != 20:
        errors.append("structural glass contract is not twenty panes")
    if any(len(segment.get("door_opening_m") or []) != 2 for segment in segments):
        errors.append("structural glass segment missing door opening")
    installed_partition_ids = set(office_manifest.get("installed_partition_ids") or [])
    expected_partition_ids = {str(segment.get("segment_id")) for segment in segments}
    if installed_partition_ids != expected_partition_ids:
        errors.append("installed structural glass partition IDs do not match manifest")
    if int(office_manifest.get("installed_pane_count") or 0) != 20:
        errors.append("installed structural glass pane count is not 20")
    rooms_set = set(rooms)
    unassigned = [item["asset_key"] for item in normalized if item.get("room") not in rooms_set]
    if unassigned:
        errors.append(f"primary assets outside programmed rooms: {len(unassigned)}")
    domestic = [item["asset_key"] for item in normalized if item["kind"] == "domestic"]
    if domestic:
        errors.append(f"domestic assets present: {len(domestic)}")

    workstation_layout = office_manifest.get("workstation_layout")
    if workstation_layout is not None:
        if workstation_layout.get("status") != "passed":
            errors.append("workstation post-process did not pass")
        if not workstation_layout.get("layout_digest"):
            errors.append("workstation post-process digest missing")
        # The workstation post-process contract covers only work bays and the
        # reception/support area.  Generic focus/manager offices may contain
        # incidental desks but are not required one-to-one workstation rooms.
        expected_workstation_rooms = set(work_bays) | set(reception_support_rooms)
        mapped_rooms = set(workstation_layout.get("expected_rooms") or [])
        if mapped_rooms != expected_workstation_rooms:
            errors.append("workstation post-process room set does not match office contract")

    by_room: dict[str, list[dict]] = defaultdict(list)
    for item in normalized:
        if item.get("room") in rooms_set:
            by_room[item["room"]].append(item)

    for room in work_bays:
        items = by_room[room]
        desks, chairs, monitors = _count(items, "desk"), _count(items, "office_chair"), _count(items, "monitor")
        if not 6 <= desks <= 10:
            errors.append(f"{room}: desk count {desks} not in [6,10]")
        if chairs < 6:
            errors.append(f"{room}: office chair count {chairs} < 6")
        if monitors < 6:
            errors.append(f"{room}: monitor count {monitors} < 6")
        primary = [item for item in items if item["kind"] in {"desk", "office_chair"}]
        cells = Counter(tuple(item.get("cell") or ()) for item in primary)
        cells.pop((), None)
        if len(cells) < 4:
            errors.append(f"{room}: primary furniture occupies {len(cells)} < 4 two-metre cells")
        if primary and cells and max(cells.values()) > math.ceil(len(primary) * 0.25):
            errors.append(f"{room}: primary furniture concentration exceeds 25% in one cell")

    for room in rooms:
        items = by_room[room]
        room_type = _room_type(room)
        if room_type == "office" and (_count(items, "desk") < 1 or _count(items, "office_chair") < 1 or _count(items, "monitor") < 1):
            errors.append(f"{room}: focus-office workstation quota missing")
        elif room_type == "factory-office" and (_count(items, "desk") < 1 or _count(items, "office_chair") < 1 or _count(items, "monitor") < 1):
            errors.append(f"{room}: reception/support workstation quota missing")
        elif room_type == "meeting-room" and (_count(items, "meeting_table") < 1 or _count(items, "chair") + _count(items, "office_chair") < 6):
            errors.append(f"{room}: meeting quota missing")
        elif room_type == "break-room" and (_count(items, "meeting_table") < 1 or _count(items, "chair") + _count(items, "office_chair") < 2):
            errors.append(f"{room}: break-room quota missing")
        elif room_type == "restroom" and (_count(items, "toilet") < 1 or _count(items, "sink") < 1):
            errors.append(f"{room}: restroom quota missing")
        elif room_type == "warehouse" and _count(items, "shelf") + _count(items, "rack") < 1:
            errors.append(f"{room}: storage quota missing")

    summary = {
        "schema": "robomituba.office_population_audit.v2",
        "profile": profile,
        "status": "passed" if not errors else "failed",
        "room_ids": rooms,
        "work_bay_rooms": work_bays,
        "reception_support_rooms": reception_support_rooms,
        "asset_count": len(normalized),
        "kind_counts": dict(sorted(Counter(item["kind"] for item in normalized).items())),
        "installed_partition_ids": sorted(installed_partition_ids),
        "installed_pane_count": int(office_manifest.get("installed_pane_count") or 0),
        "room_kind_counts": {
            room: dict(sorted(Counter(item["kind"] for item in by_room[room]).items())) for room in rooms
        },
        "errors": errors,
        "domestic_asset_keys": domestic,
        "unassigned_asset_keys": unassigned,
        "workstation_layout": workstation_layout,
    }
    digest_payload = {key: value for key, value in summary.items() if key != "audit_digest"}
    summary["audit_digest"] = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return summary
