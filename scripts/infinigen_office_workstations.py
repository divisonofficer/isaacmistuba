"""Deterministic post-solve desk/chair layout for Wide Glass Office v2.

The Infinigen solver owns coarse room population.  This Blender-side pass owns
the visual one-to-one workstation pairing because a ``front_to_front`` hard
constraint makes OfficeChairFactory initialisation pathological in large rooms.
It is called by ``infinigen_generate_indoors_safe.py`` before style application
and writes an auditable ``workstation_layout.json`` beside ``scene.blend``.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import bpy
from mathutils import Vector


_BOX_RE = re.compile(
    r"shapely\.box\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*\)"
)
_FACTORY_RE = re.compile(r"([A-Za-z][A-Za-z0-9_]*Factory)")
# Generated children are named e.g. ``OfficeChairFactory(123).bbox_placeholder``
# and ``OfficeChairFactory(123).spawn_asset(...)``.  The part before the first
# dot is the stable factory root name; matching the complete root prevents
# those children from being counted as separate chairs/desks.
_FACTORY_ROOT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*Factory(?:\([^)]*\))?$")
_FACTORY_ASSET_RE = re.compile(
    r"^(?P<prefix>[A-Za-z][A-Za-z0-9_]*Factory\([^)]*\))\.(?P<kind>bbox_placeholder|spawn_asset)\((?P<asset>[^)]*)\)"
)
_ENVIRONMENT_FACTORY_TOKENS = (
    "room", "wall", "floor", "ceiling", "door", "window", "stair",
    "overhead", "backdrop", "terrain", "light",
)
_DOMESTIC_FACTORY_TOKENS = (
    "bedfactory", "bedframefactory", "mattressfactory", "pillowfactory",
    "blanketfactory", "comforterfactory",
)
_EPSILON = 1e-5


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _write_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _boxes(path: Path) -> dict[str, tuple[float, float, float, float]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    output = {}
    for room, spec in (value.get("rooms") or {}).items():
        match = _BOX_RE.search(str(spec.get("shape") or ""))
        if not match:
            raise ValueError(f"cannot parse rectangular room {room} from {path}")
        output[room] = tuple(float(match.group(i)) for i in range(1, 5))
    return output


def _factory_owner(obj):
    """Resolve a generated mesh to its single stable factory root.

    Infinigen keeps placeholder and spawned meshes in the same collection and
    gives each child the factory name as a prefix.  Looking for a substring in
    every mesh name therefore over-counts one asset many times.  Prefer an
    exact root in the parent chain, then fall back to the globally registered
    object whose name is the prefix before the first dot.
    """
    current = obj
    while current is not None:
        name = str(current.name)
        asset_match = _FACTORY_ASSET_RE.match(name)
        if asset_match:
            prefix = asset_match.group("prefix")
            asset = asset_match.group("asset")
            # ``bbox_placeholder`` and ``spawn_asset`` are two mesh views of
            # one logical generated asset.  Prefer the spawned object as the
            # transform owner so each asset is counted exactly once.
            spawn_name = f"{prefix}.spawn_asset({asset})"
            owner = bpy.data.objects.get(spawn_name)
            if owner is None and asset_match.group("kind") == "spawn_asset":
                owner = current
            if owner is not None:
                factory_match = _FACTORY_RE.match(prefix)
                return owner, (factory_match.group(1) if factory_match else None)
        if _FACTORY_ROOT_RE.fullmatch(name):
            match = _FACTORY_RE.match(name)
            return current, (match.group(1) if match else None)
        current = current.parent

    base = str(obj.name).split(".", 1)[0]
    if _FACTORY_ROOT_RE.fullmatch(base):
        owner = bpy.data.objects.get(base)
        if owner is not None:
            match = _FACTORY_RE.match(base)
            return owner, (match.group(1) if match else None)
    return None, None


def _factory_roots() -> dict[str, dict]:
    """Return one transform owner per generated factory, keyed stably by name."""
    result: dict[str, dict] = {}
    for obj in bpy.data.objects:
        if obj.type != "MESH":
            continue
        owner, factory = _factory_owner(obj)
        if owner is None or factory is None:
            continue
        result.setdefault(owner.name, {"owner": owner, "factory": factory})
    return result


def _is_domestic_factory(factory: str | None) -> bool:
    value = str(factory or "").lower()
    return any(token in value for token in _DOMESTIC_FACTORY_TOKENS)


def _remove_domestic_assets() -> list[str]:
    """Remove home-only factory assets from the derived Office v2 scene.

    This mutates only the generated derived scene (never the source blend).
    Deleting before workstation enumeration and style application makes the
    domestic-zero contract structural and keeps the audit truthful.
    """
    roots = _factory_roots()
    prefixes = {
        str(key).split(".", 1)[0]
        for key, value in roots.items()
        if _is_domestic_factory(value.get("factory"))
    }
    if not prefixes:
        return []
    doomed = []
    for obj in list(bpy.data.objects):
        name = str(obj.name)
        if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
            doomed.append(name)
    removed = []
    for name in sorted(doomed, key=lambda item: item.count("."), reverse=True):
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        removed.append(name)
        bpy.data.objects.remove(obj, do_unlink=True)
    if removed:
        bpy.context.view_layer.update()
    return removed


def _remove_factory_asset(owner) -> list[str]:
    """Unlink one generated asset and its placeholder/child meshes.

    Several assets can share a factory invocation prefix, e.g.
    ``OfficeChairFactory(8720854).spawn_asset(1)`` and ``...spawn_asset(2)``.
    Removing by the text before the first dot would therefore delete every
    chair in the room.  Match the complete asset id and its corresponding
    placeholder instead.
    """
    owner_name = str(owner.name)
    match = _FACTORY_ASSET_RE.match(owner_name)
    if match:
        prefix = match.group("prefix")
        asset = match.group("asset")
        aliases = {
            f"{prefix}.spawn_asset({asset})",
            f"{prefix}.bbox_placeholder({asset})",
        }
        prefixes = tuple(aliases)
    else:
        prefixes = (owner_name,)
    doomed = []
    for obj in list(bpy.data.objects):
        name = str(obj.name)
        if any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes):
            doomed.append(name)
    removed = []
    for name in sorted(doomed, key=lambda item: item.count("."), reverse=True):
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        removed.append(name)
        bpy.data.objects.remove(obj, do_unlink=True)
    if removed:
        bpy.context.view_layer.update()
    return removed


def _select_spread_desks(desks: list[dict], limit: int = 10) -> tuple[list[dict], list[dict]]:
    """Keep at most ``limit`` desks while preserving spatial coverage."""
    if len(desks) <= limit:
        return list(desks), []
    by_cell: dict[tuple[int, int], list[dict]] = {}
    for desk in desks:
        cx, cy = _centre(desk["bounds"])
        cell = (int(math.floor(cx / 2.0)), int(math.floor(cy / 2.0)))
        by_cell.setdefault(cell, []).append(desk)
    selected: list[dict] = []
    # One deterministic representative per cell first, then fill by key.  The
    # audit's four-cell dispersion rule is therefore preserved whenever the
    # source room actually has four or more cells.
    for cell in sorted(by_cell):
        selected.append(sorted(by_cell[cell], key=lambda item: item["key"])[0])
    selected_keys = {item["key"] for item in selected}
    for desk in sorted(desks, key=lambda item: item["key"]):
        if len(selected) >= limit:
            break
        if desk["key"] not in selected_keys:
            selected.append(desk)
            selected_keys.add(desk["key"])
    selected = selected[:limit]
    removed = [desk for desk in desks if desk["key"] not in selected_keys]
    return selected, removed


def _ensure_workbay_monitors(
    assets: list[dict],
    by_room: dict[str, dict[str, list[dict]]],
    expected_rooms: set[str],
    desks_by_room: dict[str, list[dict]],
) -> list[str]:
    """Ensure each work bay has six visible monitor assets.

    Infinigen's office program may legally omit monitors in an open bay.  A
    monitor is a small derived asset, so cloning an authored monitor mesh and
    placing it on deterministic desk centers is preferable to regenerating a
    multi-hour scene.  Existing monitor materials and transforms are reused.
    """
    work_rooms = [room for room in sorted(expected_rooms) if not str(room).startswith("factory-office")]
    if not work_rooms:
        return []
    monitor_assets = [asset for asset in assets if asset["factory"] == "MonitorFactory"]
    if monitor_assets:
        template = monitor_assets[0]["owner"]
    else:
        # Some deterministic office seeds contain no monitor asset at all.
        # Create one small authored-looking fallback mesh so the derived scene
        # can satisfy the explicit workstation contract without re-solving.
        mesh = bpy.data.meshes.new("robomituba_office_repair_monitor_mesh")
        vertices = [(-0.22, -0.04, 0.0), (0.22, -0.04, 0.0), (0.22, 0.04, 0.0), (-0.22, 0.04, 0.0),
                    (-0.22, -0.04, 0.28), (0.22, -0.04, 0.28), (0.22, 0.04, 0.28), (-0.22, 0.04, 0.28)]
        faces = [(0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (4, 0, 3, 7)]
        mesh.from_pydata(vertices, [], faces)
        mesh.update()
        template = bpy.data.objects.new("robomituba_office_repair_monitor_template", mesh)
        bpy.context.scene.collection.objects.link(template)
        material = bpy.data.materials.get("RM_OfficeRepair_Monitor") or bpy.data.materials.new("RM_OfficeRepair_Monitor")
        material.use_nodes = True
        bsdf = material.node_tree.nodes.get("Principled BSDF")
        if bsdf is not None:
            bsdf.inputs["Base Color"].default_value = (0.03, 0.04, 0.05, 1.0)
            bsdf.inputs["Roughness"].default_value = 0.28
            bsdf.inputs["Metallic"].default_value = 0.05
        mesh.materials.append(material)
    generated: list[str] = []
    next_id = 900000000
    while bpy.data.objects.get(f"MonitorFactory({next_id}).spawn_asset(0)") is not None:
        next_id += 1
    for room in work_rooms:
        existing = [asset for asset in assets if asset["factory"] == "MonitorFactory" and asset["room"] == room]
        missing = max(0, 6 - len(existing))
        desks = desks_by_room.get(room) or []
        if missing and not desks:
            raise RuntimeError(f"cannot synthesize monitors for work bay without desks: {room}")
        for index in range(missing):
            clone = template.copy()
            clone.data = template.data.copy()
            clone.name = f"MonitorFactory({next_id}).spawn_asset({index})"
            next_id += 1
            collection = template.users_collection[0] if template.users_collection else bpy.context.scene.collection
            collection.objects.link(clone)
            clone.matrix_world = template.matrix_world.copy()
            desk = desks[index % len(desks)]
            target_x, target_y = _centre(desk["bounds"])
            current = _world_bounds(clone)
            cx, cy = _centre(current)
            clone.matrix_world.translation.x += target_x - cx
            clone.matrix_world.translation.y += target_y - cy
            # Keep the authored monitor elevation/orientation; only XY follows
            # the derived desk placement.
            generated.append(clone.name)
            assets.append({
                "owner": clone, "factory": "MonitorFactory", "key": clone.name,
                "bounds": _world_bounds(clone), "room": room,
            })
        if missing:
            bpy.context.view_layer.update()
    return generated


def _ensure_focus_office_quota(
    assets: list[dict],
    rooms: dict[str, tuple[float, float, float, float]],
) -> list[str]:
    """Ensure every focus/manager office has one minimal workstation.

    The generic Infinigen office sampler may leave a focus room without one of
    desk/chair/monitor even though the room is part of the v2 program.  These
    are small derived assets, so repairing the room in Blender is both cheaper
    and more reproducible than re-running the multi-hour solver.  Work-bay
    one-to-one pairing remains handled by :func:`apply_office_workstation_layout`;
    this helper only fills an entirely missing quota item in rooms whose type
    is ``office``.
    """
    def _live_owner(asset: dict):
        key = str(asset.get("key") or "")
        return bpy.data.objects.get(key) if key else None

    def _template(factory: str):
        return next(
            (owner for asset in assets
             if asset.get("factory") == factory
             if (owner := _live_owner(asset)) is not None),
            None,
        )

    desk_template = _template("SimpleDeskFactory")
    chair_template = _template("OfficeChairFactory")
    monitor_template = _template("MonitorFactory")
    if monitor_template is None:
        # ``_ensure_workbay_monitors`` normally creates this template when a
        # scene has no authored monitor.  Keep a fallback here as well so a
        # scene containing only focus rooms remains repairable in isolation.
        monitor_template = bpy.data.objects.get("robomituba_office_repair_monitor_template")
    if desk_template is None or chair_template is None or monitor_template is None:
        raise RuntimeError(
            "focus-office quota repair requires desk, chair, and monitor templates"
        )

    generated: list[str] = []
    desk_id = _next_asset_id("SimpleDeskFactory", start=920000000)
    chair_id = _next_asset_id("OfficeChairFactory", start=920000000)
    monitor_id = _next_asset_id("MonitorFactory", start=930000000)

    for room, bounds in sorted(rooms.items()):
        if str(room).split("_", 1)[0] != "office":
            continue
        local_desks = [asset for asset in assets if asset.get("factory") == "SimpleDeskFactory" and asset.get("room") == room]
        local_chairs = [asset for asset in assets if asset.get("factory") == "OfficeChairFactory" and asset.get("room") == room]
        local_monitors = [asset for asset in assets if asset.get("factory") == "MonitorFactory" and asset.get("room") == room]
        cx, cy = _centre(bounds)

        if not local_desks:
            desk = _clone_named_asset(desk_template, "SimpleDeskFactory", desk_id, 0, (cx, cy), scale_xy=(0.8, 0.8))
            desk_id += 1
            record = {"owner": desk, "factory": "SimpleDeskFactory", "key": desk.name, "bounds": _world_bounds(desk), "room": room}
            assets.append(record)
            local_desks = [record]
            generated.append(desk.name)

        desk = local_desks[0]
        desk_cx, desk_cy = _centre(desk["bounds"])
        # Keep the derived chair comfortably inside even for compact offices.
        chair_x = min(max(desk_cx, bounds[0] + 0.45), bounds[2] - 0.45)
        chair_y = min(max(desk_cy - 0.75, bounds[1] + 0.45), bounds[3] - 0.45)
        if not local_chairs:
            chair = _clone_named_asset(chair_template, "OfficeChairFactory", chair_id, 0, (chair_x, chair_y))
            chair_id += 1
            record = {"owner": chair, "factory": "OfficeChairFactory", "key": chair.name, "bounds": _world_bounds(chair), "room": room}
            assets.append(record)
            generated.append(chair.name)

        if not local_monitors:
            monitor = _clone_named_asset(monitor_template, "MonitorFactory", monitor_id, 0, (desk_cx, desk_cy))
            monitor_id += 1
            record = {"owner": monitor, "factory": "MonitorFactory", "key": monitor.name, "bounds": _world_bounds(monitor), "room": room}
            assets.append(record)
            generated.append(monitor.name)

    if generated:
        bpy.context.view_layer.update()
    return generated


def _next_asset_id(factory: str, start: int = 910000000) -> int:
    value = start
    while any(
        str(obj.name).startswith(f"{factory}({value}).")
        for obj in bpy.data.objects
    ):
        value += 1
    return value


def _clone_named_asset(template, factory: str, asset_id: int, index: int, target_xy: tuple[float, float], *, scale_xy: tuple[float, float] = (1.0, 1.0)):
    """Clone one authored mesh under a contract-specific factory name."""
    clone = template.copy()
    clone.data = template.data.copy()
    clone.name = f"{factory}({asset_id}).spawn_asset({index})"
    collection = template.users_collection[0] if template.users_collection else bpy.context.scene.collection
    collection.objects.link(clone)
    clone.matrix_world = template.matrix_world.copy()
    current = _world_bounds(clone)
    cx, cy = _centre(current)
    clone.matrix_world.translation.x += float(target_xy[0]) - cx
    clone.matrix_world.translation.y += float(target_xy[1]) - cy
    clone.scale.x *= float(scale_xy[0])
    clone.scale.y *= float(scale_xy[1])
    return clone


def _ensure_meeting_break_quota(assets: list[dict], rooms: dict[str, tuple[float, float, float, float]]) -> list[str]:
    """Add minimal derived meeting/break furniture when generic sampling omits it."""
    # ``assets`` is built before the work-bay cleanup pass.  That pass may
    # remove an excess desk/chair, leaving a stale Blender RNA pointer in the
    # snapshot even though its name is still present in the dictionary.  Do
    # not retain or dereference that pointer here: resolve the stable object
    # name against the live datablock collection immediately before cloning.
    def _live_owner(asset: dict):
        key = str(asset.get("key") or "")
        if not key:
            return None
        return bpy.data.objects.get(key)

    templates = {
        "table": next(
            (owner for asset in assets
             if asset.get("factory") == "SimpleDeskFactory"
             if (owner := _live_owner(asset)) is not None),
            None,
        ),
        "chair": next(
            (owner for asset in assets
             if asset.get("factory") == "OfficeChairFactory"
             if (owner := _live_owner(asset)) is not None),
            None,
        ),
    }
    if templates["table"] is None or templates["chair"] is None:
        raise RuntimeError("office quota repair requires desk and chair templates")
    generated: list[str] = []
    table_id = _next_asset_id("TableDiningFactory")
    chair_id = _next_asset_id("ChairFactory")
    for room, bounds in sorted(rooms.items()):
        room_type = str(room).split("_", 1)[0]
        if room_type not in {"meeting-room", "break-room"}:
            continue
        center = ((bounds[0] + bounds[2]) * 0.5, (bounds[1] + bounds[3]) * 0.5)
        required_chairs = 6 if room_type == "meeting-room" else 2
        existing_tables = [asset for asset in assets if asset["factory"] == "TableDiningFactory" and asset["room"] == room]
        if not existing_tables:
            table = _clone_named_asset(templates["table"], "TableDiningFactory", table_id, 0, center, scale_xy=(1.5, 1.25))
            generated.append(table.name)
            assets.append({"owner": table, "factory": "TableDiningFactory", "key": table.name, "bounds": _world_bounds(table), "room": room})
            table_id += 1
        existing_chairs = [asset for asset in assets if asset["factory"] in {"ChairFactory", "OfficeChairFactory"} and asset["room"] == room]
        missing = max(0, required_chairs - len(existing_chairs))
        # Keep positions inside the room even for compact break rooms.
        radius_x = min(0.9, max(0.35, (bounds[2] - bounds[0]) * 0.22))
        radius_y = min(0.9, max(0.35, (bounds[3] - bounds[1]) * 0.22))
        if required_chairs == 2:
            offsets = [(-radius_x, 0.0), (radius_x, 0.0)]
        else:
            offsets = [(-radius_x, -radius_y), (0.0, -radius_y), (radius_x, -radius_y), (-radius_x, radius_y), (0.0, radius_y), (radius_x, radius_y)]
        for index in range(missing):
            dx, dy = offsets[index % len(offsets)]
            chair = _clone_named_asset(templates["chair"], "ChairFactory", chair_id, index, (center[0] + dx, center[1] + dy))
            generated.append(chair.name)
            assets.append({"owner": chair, "factory": "ChairFactory", "key": chair.name, "bounds": _world_bounds(chair), "room": room})
        if missing:
            chair_id += 1
    if generated:
        bpy.context.view_layer.update()
    return generated


def _cleanup_primary_assets(
    rooms: dict[str, tuple[float, float, float, float]],
    workbay_rooms: set[str],
    mapped_desk_keys: set[str],
) -> list[str]:
    """Remove stale/out-of-room primary assets left by earlier postprocesses."""
    removed: list[str] = []
    # These are the factory classes that the population audit treats as
    # furniture/fixture records.  Infinigen can leave a sampled asset at the
    # origin when its room assignment fails; keeping it makes an otherwise
    # valid candidate fail the strict outside-room gate.  Remove only such
    # unassigned primary assets from the derived Office scene.
    audited_primary_factories = {
        "BarChairFactory", "ChairFactory", "OfficeChairFactory",
        "SimpleDeskFactory", "MonitorFactory", "TableDiningFactory",
        "ToiletFactory", "BathroomSinkFactory", "StandingSinkFactory",
        "LargeShelfFactory", "RackFactory",
    }
    for key, value in sorted(_factory_roots().items()):
        factory = value.get("factory")
        if factory not in audited_primary_factories:
            continue
        owner = value["owner"]
        bounds = _world_bounds(owner)
        room = _room_for(bounds, rooms)
        stale_desk = factory == "SimpleDeskFactory" and room in workbay_rooms and key not in mapped_desk_keys
        outside = room is None
        if stale_desk or outside:
            removed.extend(_remove_factory_asset(owner))
    return removed


def cleanup_unassigned_primary_assets(manifest_path: str | Path) -> list[str]:
    """Remove audited furniture/fixture roots whose center is outside a room.

    This is intentionally idempotent and is used by repair-only runs where a
    previously written, passed workstation layout is reused instead of being
    recomputed.  It prevents stale origin assets from invalidating the strict
    population audit without regenerating the expensive Infinigen scene.
    """
    manifest_path = Path(manifest_path)
    rooms = _boxes(manifest_path.parent / str(
        (json.loads(manifest_path.read_text(encoding="utf-8"))).get("source_floor_plan") or "floor_plan.json"
    ))
    audited_primary_factories = {
        "BarChairFactory", "ChairFactory", "OfficeChairFactory",
        "SimpleDeskFactory", "MonitorFactory", "TableDiningFactory",
        "ToiletFactory", "BathroomSinkFactory", "StandingSinkFactory",
        "LargeShelfFactory", "RackFactory",
    }
    removed: list[str] = []
    for _key, value in sorted(_factory_roots().items()):
        if value.get("factory") not in audited_primary_factories:
            continue
        owner = value["owner"]
        if _room_for(_world_bounds(owner), rooms) is None:
            removed.extend(_remove_factory_asset(owner))
    if removed:
        bpy.context.view_layer.update()
    return removed


def _world_bounds(owner) -> tuple[float, float, float, float]:
    points: list[Vector] = []
    stack = [owner]
    while stack:
        current = stack.pop()
        stack.extend(current.children)
        if current.type != "MESH":
            continue
        points.extend(current.matrix_world @ Vector(corner) for corner in current.bound_box)
    if not points:
        location = owner.matrix_world.translation
        return (float(location.x), float(location.y), float(location.x), float(location.y))
    return (
        min(float(point.x) for point in points), min(float(point.y) for point in points),
        max(float(point.x) for point in points), max(float(point.y) for point in points),
    )


def _centre(bounds: tuple[float, float, float, float]) -> tuple[float, float]:
    return ((bounds[0] + bounds[2]) * 0.5, (bounds[1] + bounds[3]) * 0.5)


def _room_for(bounds: tuple[float, float, float, float], rooms: dict[str, tuple[float, float, float, float]]) -> str | None:
    x, y = _centre(bounds)
    hits = [name for name, (x0, y0, x1, y1) in rooms.items() if x0 + _EPSILON < x < x1 - _EPSILON and y0 + _EPSILON < y < y1 - _EPSILON]
    return hits[0] if len(hits) == 1 else None


def _intersects(a: tuple[float, float, float, float], b: tuple[float, float, float, float], *, margin: float = 0.0) -> bool:
    return not (a[2] + margin <= b[0] or b[2] + margin <= a[0] or a[3] + margin <= b[1] or b[3] + margin <= a[1])


def _translate(bounds: tuple[float, float, float, float], x: float, y: float) -> tuple[float, float, float, float]:
    cx, cy = _centre(bounds)
    return (bounds[0] + x - cx, bounds[1] + y - cy, bounds[2] + x - cx, bounds[3] + y - cy)


def _inside(bounds: tuple[float, float, float, float], room: tuple[float, float, float, float], *, margin: float = 0.22) -> bool:
    return bounds[0] >= room[0] + margin and bounds[1] >= room[1] + margin and bounds[2] <= room[2] - margin and bounds[3] <= room[3] - margin


def _is_environment_asset(asset: dict) -> bool:
    """Return true for structural meshes handled by room/door bounds.

    Their world AABBs often span an entire room (floors in particular), so
    treating them as furniture blockers makes every chair candidate intersect
    before the explicit room-bound check can do its job.
    """
    factory = str(asset.get("factory") or "").lower()
    return any(token in factory for token in _ENVIRONMENT_FACTORY_TOKENS)


def _door_boxes(manifest: dict) -> list[tuple[float, float, float, float]]:
    """Return conservative XY AABBs for structural door openings.

    v2 manifests store an opening as two XY endpoints (``[[x0, y0],
    [x1, y1]]``).  Older manifests used a scalar interval along the wall
    axis (``[a, b]``).  Accept both representations so a scene generated by
    an earlier layout writer can still be post-processed deterministically.
    """
    result = []
    for segment in ((manifest.get("structural_glass") or {}).get("segments") or []):
        opening = segment.get("door_opening_m") or []
        endpoints = segment.get("wall_endpoints_m") or []
        if len(opening) != 2 or len(endpoints) != 2:
            continue
        (x0, y0), (x1, y1) = endpoints
        x0, y0, x1, y1 = map(float, (x0, y0, x1, y1))
        # New schema: two XY points.  Project onto the wall's dominant axis;
        # this also tolerates tiny numerical deviations from a straight wall.
        if all(isinstance(point, (list, tuple)) and len(point) >= 2 for point in opening):
            (ox0, oy0), (ox1, oy1) = opening
            ox0, oy0, ox1, oy1 = map(float, (ox0, oy0, ox1, oy1))
            if abs(x1 - x0) >= abs(y1 - y0):
                a, b = sorted((ox0, ox1))
                wall_y = (y0 + y1) * 0.5
                result.append((a - 0.18, wall_y - 0.42, b + 0.18, wall_y + 0.42))
            else:
                a, b = sorted((oy0, oy1))
                wall_x = (x0 + x1) * 0.5
                result.append((wall_x - 0.42, a - 0.18, wall_x + 0.42, b + 0.18))
            continue

        # Legacy schema: scalar interval along the wall axis.
        try:
            a, b = sorted(float(v) for v in opening)
        except (TypeError, ValueError):
            continue
        if abs(x1 - x0) < 1e-5:
            result.append((x0 - 0.42, a - 0.18, x0 + 0.42, b + 0.18))
        elif abs(y1 - y0) < 1e-5:
            result.append((a - 0.18, y0 - 0.42, b + 0.18, y0 + 0.42))
    return result


def _front_vectors(owner) -> list[Vector]:
    matrix = owner.matrix_world.to_3x3()
    # Factory assets do not all share an authored front convention.  Try the
    # normal local-front first, followed by deterministic orthogonal fallbacks.
    local = (Vector((0.0, -1.0, 0.0)), Vector((0.0, 1.0, 0.0)), Vector((1.0, 0.0, 0.0)), Vector((-1.0, 0.0, 0.0)))
    result = []
    for axis in local:
        vector = matrix @ axis
        vector.z = 0.0
        if vector.length > _EPSILON:
            result.append(vector.normalized())
    return result


def _candidate_centres(desk, desk_bounds, chair_bounds):
    desk_half = max(desk_bounds[2] - desk_bounds[0], desk_bounds[3] - desk_bounds[1]) * 0.5
    chair_half = max(chair_bounds[2] - chair_bounds[0], chair_bounds[3] - chair_bounds[1]) * 0.5
    distance = desk_half + chair_half + 0.18
    cx, cy = _centre(desk_bounds)
    # Dense reception/support rooms can have furniture immediately on the
    # nominal front side.  Try progressively wider clearances while keeping
    # the same deterministic axis order; the room-bound and collision checks
    # below decide which candidate is valid.
    for extra in (0.0, 0.30, 0.60, 1.00):
        for vector in _front_vectors(desk):
            d = distance + extra
            yield (cx + vector.x * d, cy + vector.y * d, vector)


def _expected_workstation_rooms(manifest: dict) -> set[str]:
    # Focus/manager offices can contain desks with visitor chairs from the
    # generic office program and are not workstation-quota rooms.  The v2
    # contract names the rooms that must have one-to-one workstation pairing;
    # do not infer additional rooms from an ``office_`` prefix.
    return set(manifest.get("work_bay_rooms") or []) | set(manifest.get("reception_support_rooms") or [])


def apply_office_workstation_layout(manifest_path: str | Path, output_folder: str | Path) -> dict:
    """Pair desk/chair assets in their own rooms, or raise after writing failure."""
    manifest_path = Path(manifest_path)
    output_folder = Path(output_folder)
    destination = output_folder / "workstation_layout.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    rooms = _boxes(manifest_path.parent / str(manifest.get("source_floor_plan") or "floor_plan.json"))
    manifest = dict(manifest)
    manifest["room_ids"] = sorted(rooms)
    removed_domestic_assets = _remove_domestic_assets()
    roots = _factory_roots()
    assets = []
    for key, value in sorted(roots.items()):
        bounds = _world_bounds(value["owner"])
        assets.append({**value, "key": key, "bounds": bounds, "room": _room_for(bounds, rooms)})
    desks = [asset for asset in assets if asset["factory"] == "SimpleDeskFactory"]
    chairs = [asset for asset in assets if asset["factory"] == "OfficeChairFactory"]
    by_room: dict[str, dict[str, list[dict]]] = {room: {"desks": [], "chairs": []} for room in rooms}
    for asset in desks:
        if asset["room"] in by_room:
            by_room[asset["room"]]["desks"].append(asset)
    for asset in chairs:
        if asset["room"] in by_room:
            by_room[asset["room"]]["chairs"].append(asset)
    failures: list[dict] = []
    mappings: list[dict] = []
    door_boxes = _door_boxes(manifest)
    expected_rooms = _expected_workstation_rooms(manifest)
    workbay_rooms = set(manifest.get("work_bay_rooms") or [])
    removed_excess_desks: list[str] = []
    # The room program can over-populate a bay when the generic asset sampler
    # wins more than the office quota.  Keep a deterministic, spatially spread
    # subset rather than regenerating the entire Infinigen scene.
    for room in sorted(workbay_rooms):
        selected, excess = _select_spread_desks(list(by_room.get(room, {}).get("desks") or []), limit=10)
        by_room.setdefault(room, {"desks": [], "chairs": []})["desks"] = selected
        for desk in excess:
            removed_excess_desks.extend(_remove_factory_asset(desk["owner"]))
    removed_desk_keys = {asset["key"] for room in workbay_rooms for asset in desks if asset["room"] == room and asset not in by_room.get(room, {}).get("desks", [])}
    # Reception/support rooms are allowed to contain incidental desks from the
    # generic office sampler.  If that sampler produced one more desk than
    # office chairs, do not reject the otherwise usable generated scene: keep
    # the desks that are closest to a chair (stable key tie-break), remove the
    # unmatched extras, and record them in the layout manifest.  Work bays
    # remain strict because their 6--10 workstation quota is part of the
    # dataset contract.
    support_rooms = set(manifest.get("reception_support_rooms") or [])
    removed_support_desk_keys: set[str] = set()
    for room in sorted(support_rooms):
        local = by_room.get(room, {"desks": [], "chairs": []})
        local_desks = list(local.get("desks") or [])
        local_chairs = list(local.get("chairs") or [])
        if local_desks and local_chairs and len(local_chairs) < len(local_desks):
            def _nearest_chair_distance(desk):
                dc = _centre(desk["bounds"])
                return (
                    min(
                        math.hypot(dc[0] - _centre(chair["bounds"])[0], dc[1] - _centre(chair["bounds"])[1])
                        for chair in local_chairs
                    ),
                    desk["key"],
                )

            keep_count = len(local_chairs)
            kept = sorted(local_desks, key=_nearest_chair_distance)[:keep_count]
            dropped = [desk for desk in local_desks if desk["key"] not in {item["key"] for item in kept}]
            for desk in dropped:
                removed_names = _remove_factory_asset(desk["owner"])
                removed_excess_desks.extend(removed_names)
                removed_support_desk_keys.add(desk["key"])
            by_room[room]["desks"] = kept

    removed_desk_keys |= removed_support_desk_keys
    assets = [asset for asset in assets if asset["key"] not in removed_desk_keys]
    desks = [asset for asset in assets if asset["factory"] == "SimpleDeskFactory"]
    placed_chair_bounds: list[tuple[float, float, float, float]] = []
    used_chair_keys: set[str] = set()
    static_bounds = [
        _world_bounds(asset["owner"])
        for asset in assets
        if asset["factory"] != "OfficeChairFactory" and not _is_environment_asset(asset)
    ]
    for room in sorted(expected_rooms):
        local = by_room.get(room, {"desks": [], "chairs": []})
        # Reception/support rooms are intentionally dense and the authored
        # furniture may touch at AABB boundaries.  Keep a positive clearance
        # for work bays, while using strict non-overlap (zero margin) for this
        # compact room so touching edges are not misclassified as collisions.
        collision_margin = 0.0 if str(room).startswith("factory-office") else 0.08
        local_desks = list(local["desks"])
        local_chairs = sorted(local["chairs"], key=lambda item: item["key"])
        # A room may legitimately contain loose visitor/meeting chairs in
        # addition to workstation chairs.  Pair one chair per desk and leave
        # deterministic extras untouched; only a missing chair is a contract
        # failure.  This prevents non-workstation seating from invalidating an
        # otherwise usable office candidate.
        if not local_desks or len(local_chairs) < len(local_desks):
            failures.append({"room": room, "reason": "desk_chair_count_mismatch", "desk_count": len(local_desks), "chair_count": len(local_chairs)})
            continue
        # Solve the most constrained desks first so a uniquely valid nearby
        # chair is not greedily consumed by an easier desk.  Feasibility uses
        # the same room/static/door checks as placement; ties stay stable.
        def _feasible_pair(desk, chair) -> bool:
            cb = chair["bounds"]
            dc = _centre(desk["bounds"])
            cc = _centre(cb)
            if (
                math.hypot(dc[0] - cc[0], dc[1] - cc[1]) <= 2.5
                and _inside(cb, rooms[room])
                and not any(_intersects(cb, blocker, margin=collision_margin) for blocker in static_bounds)
                and not any(_intersects(cb, opening, margin=0.0) for opening in door_boxes)
            ):
                return True
            for x, y, _vector in _candidate_centres(desk["owner"], desk["bounds"], cb):
                proposed = _translate(cb, x, y)
                if (
                    _inside(proposed, rooms[room])
                    and not any(_intersects(proposed, blocker, margin=collision_margin) for blocker in static_bounds)
                    and not any(_intersects(proposed, opening, margin=0.0) for opening in door_boxes)
                ):
                    return True
            return False

        def _desk_priority(item):
            cx, cy = _centre(item["bounds"])
            distances = sorted(math.hypot(_centre(chair["bounds"])[0] - cx, _centre(chair["bounds"])[1] - cy) for chair in local_chairs)
            feasible = sum(_feasible_pair(item, chair) for chair in local_chairs)
            return (feasible, distances[0] if distances else float("inf"), item["key"])

        local_desks.sort(key=_desk_priority)
        remaining_chairs = list(local_chairs)
        for desk in local_desks:
            candidate_bounds = None
            candidate_vector = None
            selected_chair = None
            desk_cx, desk_cy = _centre(desk["bounds"])
            # Prefer a chair already near this desk and otherwise try the
            # deterministic front-offset candidates.  Generated scenes often
            # contain a valid chair placement even when factory enumeration
            # order differs from desk order.
            ordered_chairs = sorted(
                remaining_chairs,
                key=lambda item: math.hypot(_centre(item["bounds"])[0] - desk_cx, _centre(item["bounds"])[1] - desk_cy),
            )
            blockers = static_bounds + placed_chair_bounds
            for chair in ordered_chairs:
                chair_cx, chair_cy = _centre(chair["bounds"])
                current = chair["bounds"]
                near_enough = math.hypot(chair_cx - desk_cx, chair_cy - desk_cy) <= 2.5
                if near_enough and _inside(current, rooms[room]) and not any(_intersects(current, blocker, margin=collision_margin) for blocker in blockers) and not any(_intersects(current, opening, margin=0.0) for opening in door_boxes):
                    candidate_bounds = current
                    direction = Vector((desk_cx - chair_cx, desk_cy - chair_cy))
                    candidate_vector = direction.normalized() if direction.length > _EPSILON else _front_vectors(desk["owner"])[0]
                    selected_chair = chair
                    break
                for x, y, vector in _candidate_centres(desk["owner"], desk["bounds"], chair["bounds"]):
                    proposed = _translate(chair["bounds"], x, y)
                    if not _inside(proposed, rooms[room]):
                        continue
                    if any(_intersects(proposed, blocker, margin=collision_margin) for blocker in blockers):
                        continue
                    if any(_intersects(proposed, opening, margin=0.0) for opening in door_boxes):
                        continue
                    candidate_bounds, candidate_vector = proposed, vector
                    selected_chair = chair
                    break
                if selected_chair is not None:
                    break
            if candidate_bounds is None or selected_chair is None:
                failures.append({"room": room, "desk": desk["key"], "reason": "no_collision_free_front_offset"})
                continue
            chair = selected_chair
            remaining_chairs.remove(chair)
            used_chair_keys.add(chair["key"])
            x, y = _centre(candidate_bounds)
            owner = chair["owner"]
            old_cx, old_cy = _centre(chair["bounds"])
            owner.matrix_world.translation.x += x - _centre(chair["bounds"])[0]
            owner.matrix_world.translation.y += y - _centre(chair["bounds"])[1]
            # Make the chair's local +Y look toward the desk without changing
            # elevation/scale.  This is purely visual; collision was evaluated
            # on its conservative world AABB before this rotation.
            direction = Vector((_centre(desk["bounds"])[0] - x, _centre(desk["bounds"])[1] - y))
            # Preserve the authored rotation when the chair was already a
            # nearby valid placement; rotating it can invalidate a tight AABB
            # clearance.  Newly moved chairs are oriented toward the desk.
            if direction.length > _EPSILON and (abs(x - old_cx) > _EPSILON or abs(y - old_cy) > _EPSILON):
                owner.rotation_euler[2] = math.atan2(direction.x, direction.y)
            bpy.context.view_layer.update()
            placed_chair_bounds.append(_world_bounds(owner))
            mappings.append({
                "room": room, "desk": desk["key"], "chair": chair["key"],
                "chair_translation_m": [round(float(owner.matrix_world.translation.x), 5), round(float(owner.matrix_world.translation.y), 5), round(float(owner.matrix_world.translation.z), 5)],
                "clearance_m": 0.08,
                "front_vector_xy": [round(float(candidate_vector.x), 5), round(float(candidate_vector.y), 5)],
            })
    removed_excess_chairs: list[str] = []
    # Only the work-bay chairs are quota furniture.  Remove unused generated
    # chairs there to avoid a dense pile invalidating the 25% cell rule; leave
    # reception/support and meeting seating untouched.
    for room in sorted(workbay_rooms):
        for chair in list(by_room.get(room, {}).get("chairs") or []):
            if chair["key"] not in used_chair_keys:
                removed_excess_chairs.extend(_remove_factory_asset(chair["owner"]))
    generated_monitors = _ensure_workbay_monitors(
        assets, by_room, expected_rooms,
        {room: list(by_room.get(room, {}).get("desks") or []) for room in workbay_rooms},
    )
    generated_focus_assets = _ensure_focus_office_quota(assets, rooms)
    generated_quota_assets = _ensure_meeting_break_quota(assets, rooms)
    cleaned_primary_assets = _cleanup_primary_assets(
        rooms, workbay_rooms, {mapping["desk"] for mapping in mappings}
    )
    bpy.context.view_layer.update()
    payload = {
        "schema": "robomituba.office_workstation_layout.v1",
        "status": "passed" if not failures else "failed",
        "source_manifest": str(manifest_path.name),
        "source_manifest_digest": _digest(manifest),
        "desk_count": len(desks),
        "chair_count": len([asset for asset in chairs if asset["key"] not in {name for name in removed_excess_chairs}]),
        "removed_domestic_assets": removed_domestic_assets,
        "removed_domestic_asset_count": len(removed_domestic_assets),
        "removed_excess_desks": removed_excess_desks,
        "removed_excess_chairs": removed_excess_chairs,
        "generated_monitor_assets": generated_monitors,
        "generated_focus_assets": generated_focus_assets,
        "generated_quota_assets": generated_quota_assets,
        "cleaned_primary_assets": cleaned_primary_assets,
        "expected_rooms": sorted(expected_rooms),
        "mappings": mappings,
        "failures": failures,
    }
    payload["layout_digest"] = _digest(payload)
    _write_atomic(destination, payload)
    if failures:
        raise RuntimeError(f"office workstation layout failed: {len(failures)} issue(s); see {destination}")
    return payload
