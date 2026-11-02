"""Pebble mulch on the atrium planters (user 10-24 on O2: 'the white and black pebble fill is missing'). Hooked from kit_lighting, only when ROOM_PLANTER_PEBBLES=1.

For every AtriumPlanterFactory object: its stone box top is at the object's local z = 0.5 (H) and the box is D x L = 0.9 x 3.4 (local x, y; scaled with the object); a single mesh of ~ROOM_PEBBLE_N (default 2200) flattened pebbles
(icospheres, 2-5 cm, squashed to 55-70 % height, random yaw) is scattered over that top in the planter's own frame, 70 % white / 30 % black river stone (two smooth stone materials), sitting 0.8 cm into the soil so
the bases are hidden; pebbles under a plant's footprint are skipped (the plant's pot / stems stand there). Idempotent: PlanterPebbles(...) objects are removed first."""
from __future__ import annotations

import math
import os
import random

import bmesh
import bpy
from mathutils import Matrix, Vector

import room_planner.proc_assets as pa


def apply(stats):
    for o in [o for o in bpy.data.objects if o.name.startswith("PlanterPebbles(")]:
        bpy.data.objects.remove(o, do_unlink=True)
    wht = pa._flat("ir_pb_white", (0.88, 0.87, 0.83), 0.35); blk = pa._flat("ir_pb_black", (0.03, 0.03, 0.035), 0.3)
    n_all = int(os.environ.get("ROOM_PEBBLE_N") or 2200); made = 0
    for pl in [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and o.name.startswith("AtriumPlanterFactory")]:
        rng = random.Random(pl.name); inv = pl.matrix_world.inverted()
        dims_l = [v for v in pl.bound_box]
        lx = (max(c[0] for c in dims_l) - min(c[0] for c in dims_l)); ly = (max(c[1] for c in dims_l) - min(c[1] for c in dims_l))
        x0, x1 = min(c[0] for c in dims_l), max(c[0] for c in dims_l); y0, y1 = min(c[1] for c in dims_l), max(c[1] for c in dims_l)
        W, Lh = min(x1 - x0, 0.9), min(y1 - y0, 3.4)                                 # the stone box only (plants stick out of the object's bbox)
        cx, cy = 0.45, 0.0
        zt = 0.5 + 0.008
        # plant footprints: objects of the planter are joined, so keep a 14 cm margin along the middle line where the stems stand, thinning the pebbles there by 70 %
        bm = bmesh.new()
        n = int(n_all * (W * Lh) / (0.9 * 3.4))
        for _ in range(n):
            x = cx + rng.uniform(-W / 2 + 0.04, W / 2 - 0.04); y = cy + rng.uniform(-Lh / 2 + 0.04, Lh / 2 - 0.04)
            if abs(x - cx) < 0.12 and rng.random() < 0.7:
                continue
            slot = 0 if rng.random() < 0.7 else 1
            r_ = rng.uniform(0.01, 0.025) * (1.3 if slot == 1 else 1.0); sq = rng.uniform(0.55, 0.7)            # the black stones are 30 % larger so the 30 % share reads in the render
            res = bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r_)
            bmesh.ops.scale(bm, vec=(rng.uniform(0.9, 1.3), 1.0, sq), verts=res["verts"])
            bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(rng.uniform(0, 6.28), 3, "Z"), verts=res["verts"])
            bmesh.ops.translate(bm, vec=(x, y, zt + r_ * sq * 0.6), verts=res["verts"])
            for f in {f for v in res["verts"] for f in v.link_faces}:
                f.material_index = slot; f.smooth = True
        me = bpy.data.meshes.new("PlanterPebbles"); bm.to_mesh(me); bm.free(); me.materials.append(wht); me.materials.append(blk)
        o = bpy.data.objects.new(f"PlanterPebbles({pl.name})", me); bpy.context.scene.collection.objects.link(o)
        o.parent = pl; o.matrix_parent_inverse = Matrix.Identity(4)
        made += 1
    stats["planter_pebbles"] = made
    return made
