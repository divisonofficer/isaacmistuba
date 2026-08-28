#!/usr/bin/env python3
"""Create a render-only OBJ with structural-glass openings cut from a GLB.

Run through ``run_bundled_blender.py``.  The source GLB is imported into an
empty temporary Blender scene; neither the original GLB nor an authoring blend
is changed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector


def _args() -> argparse.Namespace:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--segments", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def _cube(name: str, location: tuple[float, float, float], dimensions: tuple[float, float, float]):
    bpy.ops.mesh.primitive_cube_add(location=location)
    cube = bpy.context.object
    cube.name = name
    cube.dimensions = dimensions
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    return cube


def _sanitize_obj_normals(path: Path) -> int:
    """Replace an exporter-produced zero normal with a valid fallback.

    Blender can retain one normal for a Boolean-created degenerate corner even
    after topology cleanup. Mitsuba rejects the whole OBJ for that single zero
    vector. The affected corner has no stable geometric normal; use an upward
    fallback solely to keep the valid surrounding wall mesh loadable.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    fixed = 0
    output: list[str] = []
    for line in lines:
        fields = line.split()
        if len(fields) == 4 and fields[0] == "vn":
            try:
                length_sq = sum(float(value) ** 2 for value in fields[1:])
            except ValueError:
                length_sq = 1.0
            if length_sq < 1.0e-12:
                line = "vn 0.000000 1.000000 0.000000"
                fixed += 1
        output.append(line)
    if fixed:
        path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return fixed


def main() -> int:
    args = _args()
    segments = json.loads(args.segments.read_text(encoding="utf-8"))
    if not isinstance(segments, list) or not segments:
        raise ValueError("segments must be a non-empty JSON list")
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    bpy.ops.import_scene.gltf(filepath=str(args.source.resolve()))
    meshes = [obj for obj in bpy.context.scene.objects if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"no mesh imported from {args.source}")
    bpy.ops.object.select_all(action="DESELECT")
    for obj in meshes:
        obj.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    wall = bpy.context.view_layer.objects.active
    corners = [wall.matrix_world @ Vector(tuple(corner)) for corner in wall.bound_box]
    z0, z1 = min(p.z for p in corners), max(p.z for p in corners)
    cutters = []
    for index, segment in enumerate(segments):
        (x0, y0), (x1, y1) = segment["wall_endpoints_m"]
        if abs(float(x0) - float(x1)) < 1e-6:
            loc = (float(x0), (float(y0) + float(y1)) / 2, (z0 + z1) / 2)
            dims = (0.60, abs(float(y1) - float(y0)) + 0.08, (z1 - z0) + 0.10)
        else:
            loc = ((float(x0) + float(x1)) / 2, float(y0), (z0 + z1) / 2)
            dims = (abs(float(x1) - float(x0)) + 0.08, 0.60, (z1 - z0) + 0.10)
        cutters.append(_cube(f"glass_repair_cutter_{index}", loc, dims))
    bpy.ops.object.select_all(action="DESELECT")
    for cutter in cutters:
        cutter.select_set(True)
    bpy.context.view_layer.objects.active = cutters[0]
    if len(cutters) > 1:
        bpy.ops.object.join()
    cutter = bpy.context.view_layer.objects.active
    wall.select_set(True)
    bpy.context.view_layer.objects.active = wall
    modifier = wall.modifiers.new("render_only_glass_openings", "BOOLEAN")
    modifier.operation = "DIFFERENCE"
    modifier.solver = "EXACT"
    modifier.object = cutter
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    bpy.data.objects.remove(cutter, do_unlink=True)

    # Exact boolean cuts can leave zero-area slivers. Blender's OBJ exporter
    # writes these as zero-length ``vn`` entries, which Mitsuba rejects while
    # loading the whole scene. Remove degenerate topology and regenerate face
    # normals before exporting the render-only mesh.
    mesh = wall.data
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.dissolve_degenerate(bm, dist=1.0e-8, edges=list(bm.edges))
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    mesh.validate(clean_customdata=True)
    mesh.update()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    wall.select_set(True)
    bpy.context.view_layer.objects.active = wall
    bpy.ops.wm.obj_export(filepath=str(args.output.resolve()), export_selected_objects=True,
                          export_materials=False, export_uv=True, export_normals=True)
    replaced_zero_normals = _sanitize_obj_normals(args.output)
    print(json.dumps({"output": str(args.output), "segments": len(segments), "z_bounds": [z0, z1],
                      "replaced_zero_normals": replaced_zero_normals}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
