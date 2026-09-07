#!/usr/bin/env python3
"""Content fingerprint of a prepared scene, so two builds can be compared.

A pipeline that skips work it has already done never runs a stage twice, so it
never produces a second copy to compare, so a non-deterministic stage stays
invisible for the life of the project. A peer's bake pipeline had exactly this
shape: `_existing_matches` compared the source blend's sha256 and skipped the
bake on a match, and a forced rebake -- the first second copy that had ever
existed there -- showed 22 of 240 atlases materially different, because the UV
unwrap moves islands between runs and an atlas baked over a moved layout is a
different image everywhere. Nothing was wrong with the check that skipped the
work; the gap was that there was no check for this at all.

Byte-comparing .blend files does not answer the question. They embed absolute
paths and save timestamps, so two identical scenes never match and the answer
is always "differs" -- another check that returns one answer regardless of the
truth. This hashes what the renderer actually consumes instead: vertex
positions, loop normals, the first UV layer, world matrices, material slot
assignment, and every material's node graph reduced to its input values and
image references.

UVs are called out separately in the report because that is where the peer's
defect lived and it is invisible in a triangle count: same topology, moved
islands, identical `verts`/`polys`, different `uv`.

Usage:
    # write a fingerprint
    python3 tools/infinigen/run_bundled_blender.py --background --python-exit-code 1 \
        <scene>/ir_scene.blend --python apps/fingerprint_prepared_scene.py -- --out fp.json

    # compare two
    python3 apps/fingerprint_prepared_scene.py --compare fp_a.json fp_b.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

FIELDS = ("verts", "polys", "loops", "co", "uv", "normal", "matrix", "materials")


def _extract(out_path: Path) -> None:
    """Run inside Blender against the open scene."""
    import bpy
    import numpy as np

    def digest(array) -> str:
        return hashlib.sha256(array.tobytes()).hexdigest()[:16]

    objects: dict[str, dict] = {}
    for obj in sorted(bpy.data.objects, key=lambda o: o.name):
        if obj.type != "MESH" or obj.data is None:
            continue
        mesh = obj.data
        coordinates = np.empty(len(mesh.vertices) * 3, np.float32)
        mesh.vertices.foreach_get("co", coordinates)
        loops = len(mesh.loops)
        normals = np.zeros(1, np.float32)
        try:
            normals = np.empty(loops * 3, np.float32)
            mesh.loops.foreach_get("normal", normals)
        except (RuntimeError, ValueError):
            normals = np.zeros(1, np.float32)
        uv = np.zeros(1, np.float32)
        if mesh.uv_layers:
            uv = np.empty(loops * 2, np.float32)
            mesh.uv_layers[0].data.foreach_get("uv", uv)
        objects[obj.name] = {
            "verts": len(mesh.vertices), "polys": len(mesh.polygons), "loops": loops,
            "co": digest(coordinates), "uv": digest(uv), "normal": digest(normals),
            "matrix": digest(np.array(obj.matrix_world, np.float64)),
            "materials": [slot.material.name if slot.material else None
                          for slot in obj.material_slots],
        }

    materials: dict[str, str | None] = {}
    for material in sorted(bpy.data.materials, key=lambda m: m.name):
        if not material.use_nodes:
            materials[material.name] = None
            continue
        nodes = []
        for node in sorted(material.node_tree.nodes, key=lambda n: n.name):
            values = []
            for socket in node.inputs:
                value = getattr(socket, "default_value", None)
                if value is None:
                    values.append(None)
                elif hasattr(value, "__len__"):
                    values.append([round(float(v), 6) for v in value])
                else:
                    try:
                        values.append(round(float(value), 6))
                    except (TypeError, ValueError):
                        values.append(str(value))
            # The image *name* matters and its pixels do not: a texture is a
            # reference here, and hashing megabytes of it would make this
            # unusable on a scene with 60 atlases.
            nodes.append([node.name, node.type, values,
                          getattr(getattr(node, "image", None), "name", None)])
        materials[material.name] = hashlib.sha256(
            json.dumps(nodes, sort_keys=True).encode()).hexdigest()[:16]

    out_path.write_text(json.dumps({"objects": objects, "materials": materials},
                                   indent=1, sort_keys=True), encoding="utf-8")
    print(f"[fingerprint] {len(objects)} objects, {len(materials)} materials -> {out_path}")


def _compare(left: Path, right: Path) -> int:
    a = json.loads(left.read_text(encoding="utf-8"))
    b = json.loads(right.read_text(encoding="utf-8"))
    objects_a, objects_b = a["objects"], b["objects"]
    only_a = sorted(set(objects_a) - set(objects_b))
    only_b = sorted(set(objects_b) - set(objects_a))
    differing: dict[str, list[str]] = {field: [] for field in FIELDS}
    for name in sorted(set(objects_a) & set(objects_b)):
        for field in FIELDS:
            if objects_a[name][field] != objects_b[name][field]:
                differing[field].append(name)

    print(f"objects: {len(objects_a)} vs {len(objects_b)}"
          + (f"   only in A: {only_a[:3]}" if only_a else "")
          + (f"   only in B: {only_b[:3]}" if only_b else ""))
    for field in FIELDS:
        names = differing[field]
        print(f"  {field:10s} {'OK' if not names else f'DIFFERS on {len(names)}: {names[:3]}'}")
    materials_a, materials_b = a["materials"], b["materials"]
    material_diff = sorted(k for k in set(materials_a) & set(materials_b)
                           if materials_a[k] != materials_b[k])
    print(f"materials: {len(materials_a)} vs {len(materials_b)}  "
          + ("OK" if not material_diff else f"DIFFERS on {len(material_diff)}: {material_diff[:3]}"))

    # Same topology with different UVs is the signature of a non-deterministic
    # unwrap, and it is worth naming because a triangle-count check calls it
    # clean.
    moved = [n for n in differing["uv"]
             if n not in differing["verts"] and n not in differing["polys"]]
    if moved:
        print(f"\n  {len(moved)} object(s) have identical topology and different UVs.")
        print("  That is a moved unwrap, not a changed mesh: any texture baked")
        print("  against one layout is wrong for the other, everywhere.")
    ok = not any(differing.values()) and not material_diff and not only_a and not only_b
    print("\nRESULT:", "reproducible" if ok else "NOT reproducible")
    return 0 if ok else 1


def main() -> int:
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, help="write a fingerprint of the open Blender scene")
    parser.add_argument("--compare", type=Path, nargs=2, metavar=("A", "B"))
    args = parser.parse_args(argv)
    if args.compare:
        return _compare(*args.compare)
    if not args.out:
        parser.error("need --out (inside Blender) or --compare A B")
    _extract(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
