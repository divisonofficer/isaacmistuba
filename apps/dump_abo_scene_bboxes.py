"""World-space bounding boxes for every object in a prepared ABO scene.

Run inside Blender, against ir_scene.blend:

    python3 tools/infinigen/run_bundled_blender.py --background --python-exit-code 1 \
        <scene>/ir_scene.blend --python apps/dump_abo_scene_bboxes.py -- <out.json>

Exists because the composer's manifest records each instance's transform, and a
transform is not a position. An ABO GLB puts its origin on the object's base,
which is the host table's surface, so the manifest translation of a mug on a
table is a point on the table. A hover camera aimed there frames the tabletop:
measured on abo_cornell_0900, origin z=0.770, table height 0.770, actual centre
z=1.002, against a frame only 0.62 m tall at 1 m radius.

Emitting the boxes rather than the centres alone is deliberate -- the hover
generator also needs them as occluders, and a centre cannot be a blocker.

Root objects only. Instance order matches scene_manifest.json's `instances`,
which is how the consumer joins these boxes back to source_ids.
"""
import json
import sys

import bpy
from mathutils import Vector


def world_bbox(obj):
    """The box around this object and everything parented under it, or None.

    The mesh data lives on the children of an imported glTF root, so a box
    measured on the root alone is empty and an empty box is not an error the
    caller can see. Objects with no mesh anywhere below them are dropped here
    instead of being reported as a point at the origin.
    """
    low = Vector((1e9,) * 3)
    high = Vector((-1e9,) * 3)
    found = False
    for part in [obj, *obj.children_recursive]:
        if part.type != "MESH" or not part.data.vertices:
            continue
        found = True
        matrix = part.matrix_world
        for corner in part.bound_box:
            point = matrix @ Vector(corner)
            low = Vector(min(low[i], point[i]) for i in range(3))
            high = Vector(max(high[i], point[i]) for i in range(3))
    return (list(low), list(high)) if found else None


def main() -> int:
    if "--" not in sys.argv:
        raise SystemExit("usage: ... --python this.py -- <out.json>")
    out_path = sys.argv[sys.argv.index("--") + 1]

    rows = []
    for obj in bpy.data.objects:
        if obj.parent is not None:
            continue
        measured = world_bbox(obj)
        if measured is None:
            continue
        low, high = measured
        rows.append({
            "name": obj.name,
            # The object's own origin, which is what scene_manifest's
            # blender_matrix records for the instance. It is the only thing
            # here that identifies WHICH instance this box belongs to: root
            # node names are whatever the source glTF called them, and this
            # corpus mixes "RootNode" with "root" in the same scene, so
            # neither the name nor the list order is a join key.
            "origin": [round(v, 6) for v in obj.matrix_world.translation],
            "lo": [round(v, 4) for v in low],
            "hi": [round(v, 4) for v in high],
            "centre": [round((low[i] + high[i]) / 2.0, 4) for i in range(3)],
            "size": [round(high[i] - low[i], 4) for i in range(3)],
        })
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(rows, handle, indent=1)
    print(f"[bbox] {len(rows)} root objects -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
