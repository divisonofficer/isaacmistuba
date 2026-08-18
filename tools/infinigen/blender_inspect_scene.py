"""Inspect an Infinigen scene.blend WITHOUT exporting anything.

Run with the bundled Blender (headless):

  modules/infinigen/blender-4.2.0-linux-x64/blender --background <scene.blend> \
      --python tools/infinigen/blender_inspect_scene.py -- --out /tmp/blend_inspect.json

Dumps a JSON summary of the object hierarchy, collections, mesh stats,
materials (Principled inputs / whether image-textured or procedural), lights,
cameras, and scene units/axis so the exporter can be written against reality.
"""

import json
import sys
from collections import Counter

import bpy  # type: ignore


def _argv_after_ddash():
    argv = sys.argv
    return argv[argv.index("--") + 1:] if "--" in argv else []


def _principled_summary(mat):
    """Return a compact summary of a material's Principled BSDF, if any."""
    if not mat or not mat.use_nodes or not mat.node_tree:
        return {"nodes": False}
    nt = mat.node_tree
    principled = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    image_nodes = [n for n in nt.nodes if n.type == "TEX_IMAGE"]
    images = []
    for n in image_nodes:
        img = getattr(n, "image", None)
        if img is not None:
            images.append({"name": img.name, "filepath": img.filepath, "source": img.source})
    out = {
        "nodes": True,
        "has_principled": principled is not None,
        "image_tex_count": len(image_nodes),
        "images": images[:6],
        "node_types": sorted({n.type for n in nt.nodes}),
    }
    if principled is not None:
        inp = {}
        for key in ("Base Color", "Metallic", "Roughness", "IOR", "Alpha", "Emission Strength"):
            sock = principled.inputs.get(key)
            if sock is None:
                continue
            linked = bool(sock.is_linked)
            val = None
            try:
                val = list(sock.default_value) if hasattr(sock.default_value, "__len__") else sock.default_value
            except Exception:
                val = None
            inp[key] = {"linked": linked, "default": val}
        out["principled_inputs"] = inp
    return out


def main():
    args = _argv_after_ddash()
    out_path = "/tmp/blend_inspect.json"
    if "--out" in args:
        out_path = args[args.index("--out") + 1]
    only = [args[index + 1].lower() for index, value in enumerate(args[:-1]) if value == "--only"]

    scene = bpy.context.scene
    summary = {
        "blend_filepath": bpy.data.filepath,
        "unit_system": scene.unit_settings.system,
        "unit_scale": scene.unit_settings.scale_length,
        "frame": scene.frame_current,
        "object_count": len(bpy.data.objects),
        "mesh_object_count": sum(1 for o in bpy.data.objects if o.type == "MESH"),
        "collections": [c.name for c in bpy.data.collections],
        "type_counts": dict(Counter(o.type for o in bpy.data.objects)),
    }

    # Per-collection object listing (top level structure)
    coll_objs = {}
    for c in bpy.data.collections:
        coll_objs[c.name] = [o.name for o in c.objects][:40]
    summary["collection_objects"] = coll_objs

    # Mesh objects: name, collections, polycount, world bbox, materials, custom props
    meshes = []
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        if only and not any(needle in o.name.lower() for needle in only):
            continue
        me = o.data
        try:
            npoly = len(me.polygons)
        except Exception:
            npoly = -1
        bb = [list(corner) for corner in o.bound_box]  # 8 corners in local space
        # world-space bbox
        ws = [o.matrix_world @ __import__("mathutils").Vector(c) for c in o.bound_box]
        xs = [v.x for v in ws]; ys = [v.y for v in ws]; zs = [v.z for v in ws]
        mats = [ms.material.name if ms.material else None for ms in o.material_slots]
        props = {k: str(o.get(k)) for k in o.keys()} if len(o.keys()) else {}
        meshes.append({
            "name": o.name,
            "collections": [c.name for c in o.users_collection],
            "parent": o.parent.name if o.parent else None,
            "polys": npoly,
            "smooth_polygon_count": sum(1 for polygon in me.polygons if polygon.use_smooth),
            "smooth_polygon_ratio": (
                sum(1 for polygon in me.polygons if polygon.use_smooth) / max(1, npoly)
            ),
            "sharp_edge_count": sum(1 for edge in me.edges if edge.use_edge_sharp),
            "uv_layers": [layer.name for layer in me.uv_layers],
            "world_bbox_min": [min(xs), min(ys), min(zs)],
            "world_bbox_max": [max(xs), max(ys), max(zs)],
            "dimensions": list(o.dimensions),
            "materials": mats,
            "custom_props": props,
        })
    meshes.sort(key=lambda m: -(m["polys"] if m["polys"] and m["polys"] > 0 else 0))
    summary["mesh_objects_top"] = meshes if only else meshes[:80]
    summary["mesh_objects_total"] = len(meshes)

    # Materials
    mats = []
    for m in bpy.data.materials:
        mats.append({"name": m.name, **_principled_summary(m)})
    summary["material_count"] = len(mats)
    summary["materials"] = mats[:120]
    summary["material_proc_vs_tex"] = {
        "with_images": sum(1 for m in mats if m.get("image_tex_count", 0) > 0),
        "procedural_only": sum(1 for m in mats if m.get("nodes") and m.get("image_tex_count", 0) == 0),
        "no_nodes": sum(1 for m in mats if not m.get("nodes")),
    }

    # Lights
    lights = []
    for o in bpy.data.objects:
        if o.type != "LIGHT":
            continue
        L = o.data
        lights.append({
            "name": o.name,
            "type": L.type,
            "color": list(L.color),
            "energy": getattr(L, "energy", None),
            "world_pos": list(o.matrix_world.translation),
        })
    summary["light_count"] = len(lights)
    summary["lights"] = lights[:40]

    # Cameras
    cams = []
    for o in bpy.data.objects:
        if o.type != "CAMERA":
            continue
        cams.append({"name": o.name, "world_pos": list(o.matrix_world.translation),
                     "lens": o.data.lens, "sensor_width": o.data.sensor_width})
    summary["cameras"] = cams

    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"[inspect] wrote {out_path}")
    print(f"[inspect] meshes={summary['mesh_objects_total']} materials={summary['material_count']} "
          f"lights={summary['light_count']} units={summary['unit_system']} scale={summary['unit_scale']}")
    print(f"[inspect] material proc/tex: {summary['material_proc_vs_tex']}")


if __name__ == "__main__":
    main()
