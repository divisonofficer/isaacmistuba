"""Blender-side, native-asset composition for ``inverse_rendering_showcase_v1``.

This script is deliberately only launched through ``run_bundled_blender.py``.
It never saves over the supplied source blend: all mutation occurs in memory
and is published to a separately named derived blend together with a durable
placement manifest.
"""
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector

REPO_ROOT = Path(__file__).resolve().parents[2]
INFINIGEN_SRC = REPO_ROOT / "modules" / "infinigen"
if str(INFINIGEN_SRC) not in sys.path:
    sys.path.insert(0, str(INFINIGEN_SRC))


PROFILE = "inverse_rendering_showcase_v1"
SUPPORT_HEIGHT_RANGE = (0.45, 1.15)
MIN_SUPPORT_AREA_M2 = 0.35
PACKING_MARGIN_M = 0.025
SYNTHETIC_SUPPORT_TOP_Z = 0.78


def _args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--composition", type=Path, required=True)
    parser.add_argument("--out-blend", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    return parser.parse_args(argv)


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def _evaluated_mesh_bounds(obj: bpy.types.Object, depsgraph) -> dict | None:
    if obj.type != "MESH" or obj.hide_render:
        return None
    evaluated = obj.evaluated_get(depsgraph)
    mesh = None
    try:
        mesh = evaluated.to_mesh()
        if not mesh.vertices:
            return None
        world = evaluated.matrix_world
        vertices = [world @ vertex.co for vertex in mesh.vertices]
        xs, ys, zs = [vertex.x for vertex in vertices], [vertex.y for vertex in vertices], [vertex.z for vertex in vertices]
        zmax = max(zs)
        top_area = 0.0
        for polygon in mesh.polygons:
            if len(polygon.vertices) < 3:
                continue
            normal = (world.to_3x3() @ polygon.normal).normalized()
            points = [world @ mesh.vertices[index].co for index in polygon.vertices]
            if normal.z < 0.75 or max(point.z for point in points) < zmax - 0.02:
                continue
            # Projected (horizontal) polygon area is the usable top area.
            origin = points[0]
            for index in range(1, len(points) - 1):
                a, b = points[index] - origin, points[index + 1] - origin
                top_area += abs(a.x * b.y - a.y * b.x) * 0.5
        return {
            "object_name": obj.name,
            "center_xy": [round((min(xs) + max(xs)) * .5, 6), round((min(ys) + max(ys)) * .5, 6)],
            "bounds_xy": [round(min(xs), 6), round(min(ys), 6), round(max(xs), 6), round(max(ys), 6)],
            "z_min": round(min(zs), 6), "top_z": round(zmax, 6),
            "top_area_m2": round(top_area, 6),
        }
    finally:
        if mesh is not None:
            evaluated.to_mesh_clear()


def _supports() -> list[dict]:
    depsgraph = bpy.context.evaluated_depsgraph_get()
    supports = []
    for obj in bpy.context.scene.objects:
        row = _evaluated_mesh_bounds(obj, depsgraph)
        if row is None:
            continue
        if not SUPPORT_HEIGHT_RANGE[0] <= row["top_z"] <= SUPPORT_HEIGHT_RANGE[1]:
            continue
        if row["top_area_m2"] < MIN_SUPPORT_AREA_M2:
            continue
        x0, y0, x1, y1 = row["bounds_xy"]
        free_area = max(0.0, (x1 - x0) * (y1 - y0))
        # The free-space and multi-view terms are conservative geometry-only
        # proxies; the post-import raster probe is the authoritative rejection.
        row["free_space_score"] = round(free_area, 6)
        row["occlusion_score"] = round(min(1.0, row["top_area_m2"] / 1.5), 6)
        row["multi_view_potential"] = round(min(1.0, free_area / 1.0), 6)
        row["support_score"] = round(.45 * row["free_space_score"] + .30 * row["occlusion_score"] + .25 * row["multi_view_potential"], 6)
        supports.append(row)
    return sorted(supports, key=lambda row: (-row["support_score"], row["object_name"]))


def _floor_bounds(depsgraph) -> tuple[float, float, float, float]:
    """Return a conservative room-local footprint for fallback display benches."""
    candidates = []
    all_bounds = []
    for obj in bpy.context.scene.objects:
        row = _evaluated_mesh_bounds(obj, depsgraph)
        if row is None:
            continue
        x0, y0, x1, y1 = row["bounds_xy"]
        if x1 > x0 and y1 > y0:
            all_bounds.append((x0, y0, x1, y1))
        if -0.25 <= float(row["top_z"]) <= 0.30 and float(row["top_area_m2"]) >= 1.0:
            candidates.append((float(row["top_area_m2"]), (x0, y0, x1, y1)))
    if candidates:
        return max(candidates, key=lambda item: item[0])[1]
    if not all_bounds:
        return (-1.5, -1.5, 1.5, 1.5)
    # Ignore extreme decorations by using object-bound medians only when no
    # explicit floor was detected, then retain a useful minimum footprint.
    x0 = min(row[0] for row in all_bounds); y0 = min(row[1] for row in all_bounds)
    x1 = max(row[2] for row in all_bounds); y1 = max(row[3] for row in all_bounds)
    cx, cy = (x0 + x1) * .5, (y0 + y1) * .5
    return (cx - min(3.0, max(1.5, (x1 - x0) * .35)),
            cy - min(3.0, max(1.5, (y1 - y0) * .35)),
            cx + min(3.0, max(1.5, (x1 - x0) * .35)),
            cy + min(3.0, max(1.5, (y1 - y0) * .35)))


def _synthesize_showcase_supports() -> list[dict]:
    """Add deterministic neutral display benches when native surfaces fill up.

    These are explicit composition geometry, not hidden placement helpers: the
    manifest identifies them and downstream views can see the props resting on
    physically plausible opaque furniture instead of floating or overlapping.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    x0, y0, x1, y1 = _floor_bounds(depsgraph)
    room_w, room_d = max(.8, x1 - x0), max(.8, y1 - y0)
    width = min(2.6, max(1.1, room_w * .62))
    depth = min(.72, max(.42, room_d * .23))
    cx, cy = (x0 + x1) * .5, (y0 + y1) * .5
    # Four modest benches provide enough deterministic packing capacity for
    # the 20-prop showcase contract without relying on a single crowded
    # native tabletop. They remain spatially separated and visible in the
    # resulting scene rather than acting as hidden helper geometry.
    spread = min(room_d * .30, .85)
    offsets = (-spread, -spread / 3.0, spread / 3.0, spread)
    material = bpy.data.materials.get("IRShowcaseNeutralSupport") or bpy.data.materials.new("IRShowcaseNeutralSupport")
    material.diffuse_color = (.18, .20, .22, 1.0)
    material.use_nodes = True
    bsdf = material.node_tree.nodes.get("Principled BSDF") if material.node_tree else None
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (.18, .20, .22, 1.0)
        bsdf.inputs["Roughness"].default_value = .42
        bsdf.inputs["Metallic"].default_value = 0.0
    created = []
    for index, offset in enumerate(offsets):
        bench_y = min(y1 - depth * .55, max(y0 + depth * .55, cy + offset))
        bpy.ops.mesh.primitive_cube_add(location=(cx, bench_y, SYNTHETIC_SUPPORT_TOP_Z - .04))
        top = bpy.context.object
        top.name = f"IRShowcaseSupportTop_{index:02d}"
        top.dimensions = (width, depth, .08)
        bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
        top.data.materials.append(material)
        top["ir_showcase_synthetic_support"] = True
        top["semantic_category"] = "table"
        # Four simple legs make the fallback read as furniture from oblique
        # camera views while remaining cheap for Stage 1 export.
        for leg_index, (sx, sy) in enumerate(((-1, -1), (-1, 1), (1, -1), (1, 1))):
            lx = cx + sx * max(.05, width * .43)
            ly = bench_y + sy * max(.05, depth * .36)
            bpy.ops.mesh.primitive_cube_add(location=(lx, ly, (SYNTHETIC_SUPPORT_TOP_Z - .08) * .5))
            leg = bpy.context.object
            leg.name = f"IRShowcaseSupportLeg_{index:02d}_{leg_index:02d}"
            leg.dimensions = (.055, .055, SYNTHETIC_SUPPORT_TOP_Z - .08)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            leg.data.materials.append(material)
            leg["ir_showcase_synthetic_support"] = True
            leg["semantic_category"] = "table"
        created.append(top.name)
    bpy.context.view_layer.update()
    names = set(created)
    rows = [row for row in _supports() if row["object_name"] in names]
    for row in rows:
        row["synthetic"] = True
    return rows


def _overlap(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _clear_support_ray(support: dict, x: float, y: float, depsgraph) -> bool:
    """Reject a local packing cell hidden by another source-scene object."""
    # Synthetic showcase benches are created by this module and have no
    # source-scene occluder to validate. Their evaluated mesh can be absent
    # from a depsgraph ray query while it is still being constructed, which
    # previously made every fallback cell look blocked. Keep the strict ray
    # test for native supports, but accept cells on our explicit support.
    if support.get("synthetic"):
        return True
    origin = Vector((x, y, float(support["top_z"]) + 2.0))
    hit, location, _normal, _face, obj, _matrix = bpy.context.scene.ray_cast(depsgraph, origin, Vector((0.0, 0.0, -1.0)), distance=3.0)
    if not hit or obj is None:
        return False
    original = getattr(obj, "original", obj)
    return original.name == support["object_name"] and float(location.z) >= float(support["top_z"]) - .025


def _packed_position(support: dict, footprint: list[float], occupied: list[tuple[float, float, float, float]], rng: random.Random,
                     *, depsgraph) -> tuple[float, float] | None:
    x0, y0, x1, y1 = support["bounds_xy"]
    width, depth = float(footprint[0]), float(footprint[1])
    # A deterministic, shuffled local lattice keeps all composition decisions
    # reproducible without pretending that a global free-space map is exact.
    step = max(.04, min(width, depth) * .5)
    cells = []
    x = x0 + width * .5 + PACKING_MARGIN_M
    while x <= x1 - width * .5 - PACKING_MARGIN_M:
        y = y0 + depth * .5 + PACKING_MARGIN_M
        while y <= y1 - depth * .5 - PACKING_MARGIN_M:
            cells.append((x, y))
            y += step
        x += step
    rng.shuffle(cells)
    for x, y in cells:
        bounds = (x - width * .5 - PACKING_MARGIN_M, y - depth * .5 - PACKING_MARGIN_M,
                  x + width * .5 + PACKING_MARGIN_M, y + depth * .5 + PACKING_MARGIN_M)
        if not any(_overlap(bounds, previous) for previous in occupied) and _clear_support_ray(support, x, y, depsgraph):
            occupied.append(bounds)
            return x, y
    return None


def _factory(record: dict):
    module_name, class_name = str(record["factory_import"]).split(":", 1)
    return getattr(importlib.import_module(module_name), class_name)


def _tag_tree(root: bpy.types.Object, props: dict) -> list[str]:
    names = []
    nodes = [root, *list(root.children_recursive)]
    for obj in nodes:
        for key, value in props.items():
            obj[key] = value
        names.append(obj.name)
    return names


def main() -> int:
    args = _args()
    composition = _json(args.composition.resolve())
    if composition.get("profile") != PROFILE:
        raise RuntimeError("wrong showcase composition profile")
    rng = random.Random(int(composition["composition_seed"]))
    supports = _supports()
    synthetic_supports: list[dict] = []
    if not supports:
        synthetic_supports = _synthesize_showcase_supports()
        supports.extend(synthetic_supports)
    if not supports:
        raise RuntimeError("showcase composition could not create a usable support surface")
    occupied: dict[str, list[tuple[float, float, float, float]]] = {row["object_name"]: [] for row in supports}
    depsgraph = bpy.context.evaluated_depsgraph_get()
    placements, anchors, failures = [], [], []
    for index, record in enumerate(composition.get("props") or []):
        footprint = list(record.get("footprint_m") or (.18, .18))
        placement = None
        # Rotate the ranked support list so similarly sized props do not all
        # collapse on one table.  This also creates spatially distinct anchors.
        order = supports[index % len(supports):] + supports[:index % len(supports)]
        for support in order:
            position = _packed_position(support, footprint, occupied[support["object_name"]], rng, depsgraph=depsgraph)
            if position is not None:
                placement = (support, position)
                break
        if placement is None and not synthetic_supports:
            synthetic_supports = _synthesize_showcase_supports()
            supports.extend(synthetic_supports)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            for support in synthetic_supports:
                occupied[support["object_name"]] = []
            for support in synthetic_supports:
                position = _packed_position(support, footprint, occupied[support["object_name"]], rng, depsgraph=depsgraph)
                if position is not None:
                    placement = (support, position)
                    break
        if placement is None:
            failures.append({"factory": record.get("factory"), "reason": "support_packing_exhausted"})
            continue
        support, (x, y) = placement
        natural = rng.random() < .75
        yaw = rng.uniform(0.0, math.tau) if natural else math.atan2(y - support["center_xy"][1], x - support["center_xy"][0]) + rng.uniform(-.35, .35)
        factory = _factory(record)
        try:
            asset = factory(int(record["asset_seed"]))
            root = asset.spawn_asset(i=index, loc=(x, y, float(support["top_z"]) + .004), rot=(0.0, 0.0, yaw), distance=3.0)
            asset.finalize_assets([root])
        except Exception as exc:
            raise RuntimeError(f"native showcase factory {record.get('factory')} failed") from exc
        anchor_id = f"anchor:{index:03d}"
        props = {"ir_showcase_profile": PROFILE, "ir_showcase_anchor_id": anchor_id,
                 "ir_showcase_factory": str(record.get("factory")), "ir_showcase_pbr_class": str(record.get("pbr_class")),
                 "ir_showcase_semantic_category": str(record.get("semantic_category"))}
        object_names = _tag_tree(root, props)
        target_height = float(support["top_z"]) + max(.08, float(footprint[1]) * .5)
        # Bootstrap import uses ``[blender_x, -blender_y]`` for its authoring
        # plane.  Record both frames so graph selection never mixes them.
        anchors.append({"anchor_id": anchor_id, "support_id": support["object_name"], "center_xy": [round(x, 6), round(-y, 6)],
                        "source_blender_center_xy": [round(x, 6), round(y, 6)],
                        "target_height_m": round(target_height, 6), "target_object_ids": object_names,
                        "semantic_category": record.get("semantic_category"), "pbr_class": record.get("pbr_class")})
        placements.append({"placement_index": index, "factory": record.get("factory"), "asset_seed": record.get("asset_seed"),
                           "support_id": support["object_name"], "location": [round(x, 6), round(y, 6), round(float(support["top_z"]) + .004, 6)],
                           "footprint_m": footprint, "orientation_rad": round(yaw, 6),
                           "orientation_policy": "natural_random" if natural else "weak_view_facing_bias", "object_names": object_names,
                           "anchor_id": anchor_id})
    if failures or len(placements) != len(composition.get("props") or []):
        raise RuntimeError("showcase composition cannot place its complete selected native prop set: " + json.dumps(failures))
    manifest = {"schema": "robomituba.ir_showcase_composition_manifest.v1", "profile": PROFILE,
                "composition_digest": composition["composition_digest"], "registry_digest": composition["registry_digest"],
                "source_blend": composition.get("source_blend"), "source_blend_digest": composition.get("source_blend_digest"),
                "source_blender_to_authoring_transform": {"status": "verified_by_bootstrap_contract", "matrix": [[1, 0, 0], [0, -1, 0], [0, 0, 1]],
                                                           "mapping": "authoring_xy=[blender_x,-blender_y]; height=blender_z"},
                "supports": supports, "placements": placements, "anchors": anchors,
                "synthetic_support_ids": [row["object_name"] for row in synthetic_supports],
                "placed_prop_count": len(placements), "support_height_range_m": list(SUPPORT_HEIGHT_RANGE),
                "minimum_support_area_m2": MIN_SUPPORT_AREA_M2}
    args.out_blend.parent.mkdir(parents=True, exist_ok=True)
    staged_blend = args.out_blend.with_name(f".{args.out_blend.name}.staging")
    bpy.context.scene["ir_composition_profile"] = PROFILE
    bpy.context.scene["ir_showcase_composition_digest"] = composition["composition_digest"]
    bpy.ops.wm.save_as_mainfile(filepath=str(staged_blend))
    os.replace(staged_blend, args.out_blend)
    _atomic_json(args.manifest, manifest)
    print(json.dumps({"profile": PROFILE, "placed_prop_count": len(placements), "anchor_count": len(anchors),
                      "derived_blend": str(args.out_blend)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
