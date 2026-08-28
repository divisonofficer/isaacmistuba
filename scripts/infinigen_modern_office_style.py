"""Blender-side modern office styling and structural-glass installation.

This module runs inside Infinigen's bundled Blender process after scene
generation.  Keeping it repository-owned avoids patching the Infinigen install
and makes the exact post-generation contract auditable from the output folder.
"""
from __future__ import annotations

import json
from pathlib import Path

import bpy
from mathutils import Vector


def install_door_bias(style: str) -> None:
    """Bias generated modern-office doors before Infinigen composes the scene."""
    if style not in {"modern_basic_v1", "modern_glass_v1", "modern_glass_v2"}:
        return
    from infinigen.assets.objects.elements import doors
    from infinigen.assets.objects.elements.doors.panel import GlassPanelDoorFactory
    from infinigen.core.constraints.example_solver.room import decorate

    def glass_panel_factory():
        return GlassPanelDoorFactory

    # decorate imported the function by value, so patch both call sites.
    doors.random_door_factory = glass_panel_factory
    decorate.random_door_factory = glass_panel_factory


def _material(name: str, color: tuple[float, float, float, float], roughness: float, metallic: float = 0.0, *, transmission: float = 0.0):
    material = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.use_nodes = True
    node = next((item for item in material.node_tree.nodes if item.type == "BSDF_PRINCIPLED"), None)
    if node is None:
        node = material.node_tree.nodes.new("ShaderNodeBsdfPrincipled")
    node.inputs["Base Color"].default_value = color
    node.inputs["Roughness"].default_value = roughness
    node.inputs["Metallic"].default_value = metallic
    if "Transmission Weight" in node.inputs:
        node.inputs["Transmission Weight"].default_value = transmission
    material.diffuse_color = color
    return material


def _assign(obj, material):
    if obj.type != "MESH":
        return
    obj.data.materials.clear()
    obj.data.materials.append(material)


def _cube(name: str, location, dimensions, material, props: dict):
    bpy.ops.mesh.primitive_cube_add(location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if material is not None:
        _assign(obj, material)
    for key, value in props.items():
        obj[key] = value
    return obj


def _wall_object(room: str):
    obj = bpy.data.objects.get(f"{room}.wall")
    if obj is None or obj.type != "MESH":
        raise RuntimeError(f"modern glass: required source wall is absent: {room}.wall")
    return obj


def _opaque_wall_owners(segment: dict) -> tuple[str, str]:
    """Return the two shell owners that share a structural-glass boundary."""
    owners = segment.get("opaque_wall_owners")
    if not isinstance(owners, list) or len(owners) != 2:
        raise RuntimeError(f"{segment.get('segment_id', '<unknown>')}: structural glass requires exactly two opaque wall owners")
    room, corridor = (str(item) for item in owners)
    if not room or not corridor or room == corridor:
        raise RuntimeError(f"{segment.get('segment_id', '<unknown>')}: invalid opaque wall owners")
    if room != str(segment.get("room") or "") or corridor != str(segment.get("corridor") or ""):
        raise RuntimeError(f"{segment.get('segment_id', '<unknown>')}: opaque wall owners must be [room, corridor]")
    return room, corridor


def _remove_wall_segments(wall, cuts: list[dict], owner: str):
    """Cut all requested shared boundaries from one opaque shell in one Boolean.

    Hallways commonly own several glass boundaries.  Joining their cutters first
    makes one exact Boolean per wall and prevents a later cut from operating on
    a topology already changed by an earlier modifier.
    """
    if not cuts:
        raise RuntimeError(f"modern glass: no cuts requested for {owner}.wall")
    # Blender 4.2 exposes every ``bound_box`` corner as ``bpy_prop_array``.
    # Unlike the older tuple-like value it cannot be multiplied directly by a
    # Matrix.  Convert at the Blender API boundary so this works in both the
    # generator's bundled Blender and headless repair runs.
    # ``tuple`` is intentional: some Blender versions expose a corner as a
    # ``bpy_prop_array`` that ``Vector`` accepts, but does not expose as a
    # matrix-multipliable sequence until it has been materialized.
    world_corners = [wall.matrix_world @ Vector(tuple(corner)) for corner in wall.bound_box]
    z0 = min(corner.z for corner in world_corners)
    z1 = max(corner.z for corner in world_corners)
    cutters = []
    for cut in cuts:
        segment_id = str(cut["segment_id"])
        (x0, y0), (x1, y1) = cut["wall_endpoints_m"]
        if abs(x0 - x1) < 1e-6:
            location, dimensions = ((x0, (y0 + y1) / 2, (z0 + z1) / 2), (0.60, abs(y1 - y0) + 0.08, (z1 - z0) + 0.10))
        else:
            location, dimensions = (((x0 + x1) / 2, y0, (z0 + z1) / 2), (abs(x1 - x0) + 0.08, 0.60, (z1 - z0) + 0.10))
        cutters.append(_cube(f"{segment_id}.{owner}.wall_cutter", location, dimensions, None, {}))
    bpy.ops.object.select_all(action="DESELECT")
    for cutter in cutters:
        cutter.select_set(True)
    bpy.context.view_layer.objects.active = cutters[0]
    if len(cutters) > 1:
        bpy.ops.object.join()
    cutter = bpy.context.view_layer.objects.active
    modifier = wall.modifiers.new(f"office_glass_{owner}.replace", "BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    modifier.object = cutter
    bpy.context.view_layer.objects.active = wall
    wall.select_set(True)
    try:
        bpy.ops.object.modifier_apply(modifier=modifier.name)
    except RuntimeError as exc:
        raise RuntimeError(f"{owner}.wall: failed to remove opaque source wall") from exc
    bpy.data.objects.remove(cutter, do_unlink=True)
    wall["office_wall_segment_ids"] = [str(cut["segment_id"]) for cut in cuts]
    wall["office_wall_replaced"] = True
    return z0, z1


def _glass_segments(endpoints, opening):
    (x0, y0), (x1, y1) = endpoints
    (dx0, dy0), (dx1, dy1) = opening
    if abs(x0 - x1) < 1e-6:
        lo, hi, d0, d1 = min(y0, y1), max(y0, y1), min(dy0, dy1), max(dy0, dy1)
        return [("v", x0, lo, d0), ("v", x0, d1, hi)]
    lo, hi, d0, d1 = min(x0, x1), max(x0, x1), min(dx0, dx1), max(dx0, dx1)
    return [("h", y0, lo, d0), ("h", y0, d1, hi)]


def _install_partition(segment: dict, glass, frame, style: str, *, z0: float, z1: float):
    segment_id = segment["segment_id"]
    glass_count = len(_glass_segments(segment["wall_endpoints_m"], segment["door_opening_m"]))
    expected_names = [
        *(f"{segment_id}.glass.{index}" for index in range(glass_count)),
        *(f"{segment_id}.frame_end.{index}" for index in range(2)),
        *(f"{segment_id}.frame_door.{index}" for index in range(2)),
    ]
    present = [name for name in expected_names if bpy.data.objects.get(name) is not None]
    if len(present) == len(expected_names):
        # A saved style repair may be re-run after a later pipeline failure.
        # Never boolean-cut the source wall twice or duplicate structural glass.
        return segment_id
    if present:
        raise RuntimeError(
            f"{segment_id}: partial pre-existing partition ({', '.join(present)}); "
            "refusing an unsafe duplicate wall cut"
        )
    height = (z1 - z0) - float(segment["frame"]["top_clearance_m"])
    center_z = z0 + height / 2
    props = {
        "glass_wall": True,
        "transparent_partition": True,
        "office_style": style,
        "office_wall_segment_id": segment_id,
        "glass_partition_id": segment_id,
    }
    profile = float(segment["frame"]["profile_m"])
    for index, (orientation, const, lo, hi) in enumerate(_glass_segments(segment["wall_endpoints_m"], segment["door_opening_m"])):
        if hi - lo <= 0.05:
            raise RuntimeError(f"{segment_id}: invalid glass span around door opening")
        if orientation == "v":
            location, dims = ((const, (lo + hi) / 2, center_z), (0.025, hi - lo, height))
        else:
            location, dims = (((lo + hi) / 2, const, center_z), (hi - lo, 0.025, height))
        _cube(
            f"{segment_id}.glass.{index}", location, dims, glass,
            {**props, "glass_pane": True, "glass_pane_index": index},
        )
    (x0, y0), (x1, y1) = segment["wall_endpoints_m"]
    for index, (x, y) in enumerate(((x0, y0), (x1, y1))):
        _cube(f"{segment_id}.frame_end.{index}", (x, y, center_z), (profile, profile, height), frame, props)
    for index, (x, y) in enumerate(segment["door_opening_m"]):
        _cube(f"{segment_id}.frame_door.{index}", (x, y, center_z), (profile, profile, height), frame, props)
    # The authored Infinigen door remains in its existing opening and is tagged
    # through the manifest rather than guessed from Blender object ordering.
    return segment_id


def apply_office_style(manifest_path: str | Path, style: str) -> dict:
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest.get("office_style") != style:
        raise RuntimeError("office style and layout manifest disagree")
    wall = _material("RM_ModernOffice_Wall", (0.78, 0.80, 0.82, 1.0), 0.62)
    floor = _material("RM_ModernOffice_Floor", (0.18, 0.22, 0.25, 1.0), 0.82)
    ceiling = _material("RM_ModernOffice_Ceiling", (0.92, 0.94, 0.96, 1.0), 0.72)
    for obj in bpy.data.objects:
        if obj.name.endswith(".wall"):
            _assign(obj, wall)
            obj["office_style"] = style
        elif obj.name.endswith(".floor"):
            _assign(obj, floor)
            obj["office_style"] = style
        elif obj.name.endswith(".ceiling"):
            _assign(obj, ceiling)
            obj["office_style"] = style
    installed = []
    if style in {"modern_glass_v1", "modern_glass_v2"}:
        spec = manifest.get("structural_glass") or {}
        requested = int(spec.get("requested_partition_count", 0))
        segments = spec.get("segments") or []
        expected = 3 if style == "modern_glass_v1" else 10
        if requested != expected or len(segments) != requested or int(spec.get("eligible_segment_count", 0)) < requested:
            raise RuntimeError(f"{style} manifest failed structural partition validation")
        if style == "modern_glass_v2" and int(spec.get("requested_pane_count", 0)) != 20:
            raise RuntimeError("modern_glass_v2 manifest must declare exactly 20 panes")
        glass = _material("RM_ModernOffice_Glass", (0.32, 0.52, 0.64, 1.0), 0.08, transmission=1.0)
        frame = _material("RM_ModernOffice_Frame", (0.025, 0.03, 0.04, 1.0), 0.28, metallic=0.80)
        # Validate the complete contract before changing a single source wall.
        for segment in segments:
            _opaque_wall_owners(segment)
        expected_names = [
            name
            for segment in segments
            for name in (
                *(f"{segment['segment_id']}.glass.{index}" for index in range(len(_glass_segments(segment["wall_endpoints_m"], segment["door_opening_m"])))),
                *(f"{segment['segment_id']}.frame_end.{index}" for index in range(2)),
                *(f"{segment['segment_id']}.frame_door.{index}" for index in range(2)),
            )
        ]
        present = [name for name in expected_names if bpy.data.objects.get(name) is not None]
        if present and len(present) != len(expected_names):
            raise RuntimeError("modern glass: partial pre-existing partition; refusing unsafe duplicate wall cut")
        if len(present) == len(expected_names):
            installed = [str(segment["segment_id"]) for segment in segments]
        else:
            cuts_by_owner: dict[str, list[dict]] = {}
            for segment in segments:
                for owner in _opaque_wall_owners(segment):
                    cuts_by_owner.setdefault(owner, []).append(segment)
            z_ranges: dict[str, tuple[float, float]] = {}
            for owner, cuts in cuts_by_owner.items():
                z_ranges[owner] = _remove_wall_segments(_wall_object(owner), cuts, owner)
            installed = []
            for segment in segments:
                owners = _opaque_wall_owners(segment)
                z0, z1 = z_ranges[owners[0]]
                other_z0, other_z1 = z_ranges[owners[1]]
                if abs(z0 - other_z0) > 0.02 or abs(z1 - other_z1) > 0.02:
                    raise RuntimeError(f"{segment['segment_id']}: opaque wall owners disagree on vertical bounds")
                installed.append(_install_partition(segment, glass, frame, style, z0=z0, z1=z1))
    scene = bpy.context.scene
    scene["office_style"] = style
    scene["office_style_digest"] = manifest.get("office_style_digest") or manifest.get("structural_glass", {}).get("digest", style)
    return {"style": style, "installed_partition_ids": installed, "installed_partition_count": len(installed)}
