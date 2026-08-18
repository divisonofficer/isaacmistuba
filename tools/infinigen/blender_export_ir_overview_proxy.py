"""Blender-side compiler for the IR viewer's compact, semantic GLB proxy."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import bpy
from mathutils import Vector

SCHEMA = "robomituba.ir_scene_overview_proxy.v1"
COLORS = {
    "structural": (0.23, 0.31, 0.38, 1.0), "furniture": (0.62, 0.47, 0.31, 1.0),
    "fixture": (0.32, 0.49, 0.58, 1.0), "navigation": (0.48, 0.50, 0.48, 1.0),
}


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage1-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--triangle-target", type=int, required=True)
    parser.add_argument("--triangle-cap", type=int, required=True)
    return parser.parse_args(list(__import__("sys").argv[__import__("sys").argv.index("--") + 1:]))


def _category(unit: dict) -> str:
    kind, semantic = str(unit.get("kind") or ""), str(unit.get("semantic_type") or "")
    if kind in {"structure", "door", "window"} or semantic in {"wall", "glass_wall", "glass_door"}:
        return "structural"
    if kind == "light":
        return "fixture"
    return "furniture" if kind == "furniture" else "navigation"


def _triangles(obj: bpy.types.Object) -> int:
    return sum(len(poly.vertices) - 2 for poly in obj.data.polygons) if obj.type == "MESH" else 0


def main() -> None:
    args = _args(); manifest = json.loads(args.stage1_manifest.read_text(encoding="utf-8"))
    units = {str(unit.get("blender_name")): unit for unit in manifest.get("units") or []}
    kept: list[tuple[bpy.types.Object, str]] = []
    for obj in list(bpy.data.objects):
        if obj.type != "MESH":
            bpy.data.objects.remove(obj, do_unlink=True); continue
        unit = units.get(obj.name)
        category = _category(unit or {})
        dimensions = (unit or {}).get("dimensions") or list(obj.dimensions)
        diagonal = math.sqrt(sum(float(v) ** 2 for v in dimensions[:3]))
        keep = category == "structural" or (category == "furniture" and diagonal >= 0.70)
        if not keep:
            bpy.data.objects.remove(obj, do_unlink=True); continue
        kept.append((obj, category))
    materials = {}
    for category, color in COLORS.items():
        material = bpy.data.materials.new(f"IROverview_{category}"); material.diffuse_color = color
        material.use_nodes = True; bsdf = material.node_tree.nodes.get("Principled BSDF")
        if bsdf: bsdf.inputs["Base Color"].default_value = color; bsdf.inputs["Roughness"].default_value = 0.82; bsdf.inputs["Metallic"].default_value = 0.0
        materials[category] = material
    initial = sum(_triangles(obj) for obj, _ in kept)
    # Leave a small margin for decimator rounding.  A proxy that barely exceeds
    # its declared cap is worse than a slightly simpler overview mesh.
    # Blender's decimator preserves boundary topology and can overshoot a
    # requested aggregate ratio materially on architectural meshes.  Target
    # below the public cap so the exported mesh remains valid under that bias.
    target = max(1, int(args.triangle_target))
    ratio = min(1.0, float(target) / max(initial, 1))
    for obj, category in kept:
        obj.data.materials.clear(); obj.data.materials.append(materials[category])
        if ratio < 0.999 and _triangles(obj) > 80:
            bpy.context.view_layer.objects.active = obj; obj.select_set(True)
            modifier = obj.modifiers.new("IROverviewDecimate", "DECIMATE"); modifier.ratio = max(0.01, ratio)
            bpy.ops.object.modifier_apply(modifier=modifier.name); obj.select_set(False)
    # Decimate once more if Blender's per-object rounding kept the aggregate
    # above the target.  This also covers a modifier that had to retain a few
    # triangles to keep a mesh valid.
    for _ in range(3):
        current = sum(_triangles(obj) for obj, _ in kept)
        if current <= args.triangle_cap:
            break
        correction = max(0.005, min(0.95, float(target) / max(current, 1)))
        for obj, _category_name in kept:
            if _triangles(obj) <= 16:
                continue
            bpy.context.view_layer.objects.active = obj; obj.select_set(True)
            modifier = obj.modifiers.new("IROverviewDecimateCorrection", "DECIMATE")
            modifier.ratio = correction
            bpy.ops.object.modifier_apply(modifier=modifier.name); obj.select_set(False)
    # Open architectural meshes and topology-preserving decimation can have a
    # high irreducible triangle floor.  Enforce the *aggregate* cap by dropping
    # the densest non-structural mesh last; this is an overview aid, so keeping
    # room envelope and a representative set of large furniture is preferable
    # to emitting an over-budget asset that downstream must reject.
    if sum(_triangles(obj) for obj, _ in kept) > args.triangle_cap:
        removable = sorted(
            ((obj, category) for obj, category in kept if category != "structural"),
            key=lambda pair: _triangles(pair[0]), reverse=True,
        )
        for obj, _category_name in removable:
            if sum(_triangles(item) for item, _ in kept) <= args.triangle_cap:
                break
            bpy.data.objects.remove(obj, do_unlink=True)
            kept = [pair for pair in kept if pair[0] != obj]
    if sum(_triangles(obj) for obj, _ in kept) > args.triangle_cap:
        raise RuntimeError(f"proxy triangle cap cannot preserve structural geometry: {sum(_triangles(obj) for obj, _ in kept)} > {args.triangle_cap}")
    # Blender's glTF exporter performs the canonical Z-up -> glTF Y-up conversion.
    bpy.ops.object.select_all(action="SELECT")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.export_scene.gltf(filepath=str(args.out), export_format="GLB", use_selection=True,
                              export_materials="EXPORT", export_cameras=False, export_lights=False,
                              export_yup=True, export_apply=True)
    # glTF export applies Blender Z-up -> glTF Y-up: (x, y, z) -> (x, z, -y).
    # Report bounds in the exported mesh convention, which is also the
    # dataset's Mitsuba Y-up convention.
    points = []
    for obj, _ in kept:
        for corner in obj.bound_box:
            point = obj.matrix_world @ Vector(corner[:])
            points.append(Vector((point.x, point.z, -point.y)))
    low = [min(point[i] for point in points) for i in range(3)] if points else [0.0] * 3
    high = [max(point[i] for point in points) for i in range(3)] if points else [0.0] * 3
    args.summary.write_text(json.dumps({"schema": SCHEMA, "coordinate_system": "mitsuba_y_up", "triangles": sum(_triangles(obj) for obj, _ in kept),
        "initial_triangles": initial, "object_count": len(kept), "triangle_target": args.triangle_target, "triangle_cap": args.triangle_cap,
        "semantic_groups": ["structural", "large_furniture"], "categories": {key: sum(1 for _, value in kept if value == key) for key in COLORS},
        "bounds": {"min": low, "max": high}}, indent=2), encoding="utf-8")


if __name__ == "__main__": main()
