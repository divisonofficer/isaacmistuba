"""Delete objects lying absurdly far from the apartment and save the blend in place (2026-10-13).

Infinigen's room_pillars stage sometimes leaves pillars at ~(2.9e23, 6.8e22): invisible to every camera, but the walk planner sizes its
standable-cell grid from the bounds of all renderable meshes, so one such object turns walk planning into an endless ray-cast loop
(12644647: 3 h single-core before it was found). Also called from prepare_nobake_ir_scene.py.

    blender --background X.blend --python sanitize_far_objects.py -- [--limit-m 1000]
"""
import os
import sys

import bpy
from mathutils import Vector


def far_objects(limit_m=1000.0):
    out = []
    for o in bpy.data.objects:
        corners = [o.matrix_world @ Vector(c) for c in o.bound_box] + [o.matrix_world.translation]
        if any(abs(v) > limit_m or v != v for p in corners for v in p):     # v != v: NaN
            out.append(o)
    return out


def remove_far_objects(limit_m=1000.0) -> list:
    names = []
    for o in far_objects(limit_m):
        names.append(o.name)
        bpy.data.objects.remove(o, do_unlink=True)
    return names


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    limit = float(argv[argv.index("--limit-m") + 1]) if "--limit-m" in argv else 1000.0
    gone = remove_far_objects(limit)
    path = bpy.data.filepath
    if gone:
        tmp = path + ".sanitize.blend"
        bpy.ops.wm.save_as_mainfile(filepath=tmp, copy=True)
        os.replace(tmp, path)
    print("SANITIZE", path, len(gone), gone[:6], flush=True)
