"""Ramen cooking-line utensils (S32 r17 user note: 'primitive vocabulary, nothing has handles, lids, labels, utensils'). Hooked from kit_lighting after ramen_dressing, only when ROOM_RAMEN_UTENSILS=1.

    import ramen_utensils; stats["ramen_utensils"] = ramen_utensils.apply(stats)

Everything is placed in the RamenKitchenFactory's own frame (x = out from the back wall, y along the 6 m / 5.2 m block, z up), so the spots are the same as the factory's (sink at y0+0.55, work table y0+1.7, fridge +2.85, range +4.05,
noodle boiler +5.05; utensil rail at x 0.07, z 1.6):
  rail         3 procedural ladles, 2 tongs, 2 tebo strainer baskets (proc_utensils.py) and 4 library spoons / spatulas (scaled 1.5x, hung by the handle end) hang along the rail
  range        2-3 library stock pots (PotFactory, scaled to 0.38-0.46 m wide) with their library lids (LidFactory) on, tilted or leaning
  pass         a steel tray of 5 library bowls (rice-bowl size) on the work table beside the sink, and a cutting board with a library knife
Library models come from data/object_library_v2 through lib_objects (linked duplicates, 60k-face models). With ROOM_RAMEN_UTENSILS=1 the activity stage's RamenKitchenFactory skips its own primitive pots / rail items
(proc_lp.py reads the same variable), so nothing is doubled. Missing library -> the procedural parts only."""
from __future__ import annotations

import math
import os
import random

import bpy
from mathutils import Euler, Matrix, Vector


def _kitchen():
    ks = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("RamenKitchenFactory")]
    return ks[0] if ks else None


def _lib(cat, sp, rnd, target=None, axis_long=False):
    """One library object (linked duplicate), or None. target = wanted size (m) along the model's longest horizontal axis."""
    try:
        from room_planner import lib_objects as lo
        pool = [m for m in lo._index() if m["category"] == cat and m["species"] == sp]
        if not pool:
            return None
        m = rnd.choice(pool)
        o = bpy.data.objects.new(f"RamenLib_{sp}", lo._mesh(m, None)); bpy.context.scene.collection.objects.link(o)
        if target:
            k = target / max(m["size"][0], m["size"][1], 1e-3); o.scale = (k, k, k)
        return o
    except Exception as ex:                                  # noqa: BLE001
        print(f"[ramen_utensils] library {cat}/{sp}: {ex!r}"[:160], flush=True)
        return None


def _place(o, K, local, euler=(0, 0, 0), name=None, pre=None):
    """Put o at `local` (kitchen frame) with local rotation `euler`; keeps o.scale. pre = a model-space matrix applied first (used to stand a flat utensil upright and hang it from its end)."""
    sc = o.scale.copy()
    o.matrix_world = K.matrix_world @ Matrix.Translation(Vector(local)) @ Euler(euler).to_matrix().to_4x4() @ (pre if pre is not None else Matrix.Identity(4)) @ Matrix.Diagonal((sc.x, sc.y, sc.z, 1.0))
    o["src"] = "arch:ramen_utensils"
    if name:
        o.name = name


def _long_axis_down(o, head_down=True):
    """Rotation (euler) that stands a flat utensil upright: its longest axis along -Z, the heavier end (the head) down."""
    me = o.data; co = [v.co for v in me.vertices]
    ext = [max(c[i] for c in co) - min(c[i] for c in co) for i in range(3)]; ax = max(range(3), key=lambda i: ext[i])
    mid = (max(c[ax] for c in co) + min(c[ax] for c in co)) / 2
    mean = sum(c[ax] for c in co) / len(co)
    head_plus = mean > mid
    v = Vector((0, 0, 0)); v[ax] = 1.0 if head_plus else -1.0                       # the head end's direction in model space
    q = v.rotation_difference(Vector((0, 0, -1)))                                     # turn it to point down
    return q.to_euler(), ax


def apply(stats):
    if os.environ.get("ROOM_RAMEN_UTENSILS") != "1":
        return {}
    K = _kitchen()
    if K is None:
        print("RAMEN_UTENSILS skipped: no RamenKitchenFactory", flush=True)
        return {}
    for o in [x for x in bpy.data.objects if x.get("src") == "arch:ramen_utensils"]:
        bpy.data.objects.remove(o, do_unlink=True)                                    # idempotent re-run
    from room_planner import proc_utensils as pu
    rnd = random.Random(32)
    L = max(K.dimensions[1], 3.0); y0 = -L / 2
    yt, yr, yb = y0 + 1.7, y0 + 4.05, min(y0 + 5.05, L / 2 - 0.45)
    # --- the rail: x 0.07, z 1.6; the factory's own rail spans yt - 0.6 .. yr + 0.6
    r0, r1 = yt - 0.6, yr + 0.6
    slots = [r0 + 0.2 + k * (r1 - r0 - 0.4) / 10 for k in range(11)]; rnd.shuffle(slots)
    n = {"ladle": 0, "tongs": 0, "tebo": 0, "spoons": 0, "pots": 0, "lids": 0, "bowls": 0, "knife": 0}
    kinds = ["ladle"] * 3 + ["tongs"] * 2 + ["tebo"] * 2 + ["spoon"] * 4
    for kind, y in zip(kinds, slots):
        if kind == "ladle":
            o = pu.ladle(rnd); _place(o, K, (0.095, y, 1.585), (0, 0, math.pi / 2 + rnd.uniform(-0.15, 0.15)), "RamenLadle"); n["ladle"] += 1
        elif kind == "tongs":
            o = pu.tongs(rnd); _place(o, K, (0.095, y, 1.585), (0, 0, math.pi / 2 + rnd.uniform(-0.2, 0.2)), "RamenTongs"); n["tongs"] += 1
        elif kind == "tebo":
            o = pu.tebo(rnd); _place(o, K, (0.095, y, 1.585), (0, 0, math.pi / 2), "RamenTebo"); n["tebo"] += 1
        else:
            o = _lib("cutlery", rnd.choice(("spoon", "spatula")), rnd, target=0.26)
            if o is None:
                continue
            eul, ax = _long_axis_down(o)
            R = eul.to_matrix().to_4x4(); k = o.scale.x
            top = max((R @ Vector((v.co.x * k, v.co.y * k, v.co.z * k))).z for v in o.data.vertices)                                  # the top of the upright model: hung from there
            o.scale = (1, 1, 1)
            _place(o, K, (0.095, y, 1.585), (0, 0, math.pi / 2 + rnd.uniform(-0.2, 0.2)), pre=Matrix.Translation((0, 0, -top)) @ R @ Matrix.Diagonal((k, k, k, 1.0)))
            n["spoons"] += 1
    # --- stock pots on the range, with lids (the factory's pots stood at yr-0.3, yr+0.3, yr+0.02; x 0.3 +/- 0.1)
    for (py, px, w) in ((yr - 0.3, 0.2, 0.46), (yr + 0.3, 0.2, 0.4), (yr + 0.02, 0.42, 0.34)):
        po = _lib("cookware", "pot", rnd, target=w)
        if po is None:
            break
        po.rotation_euler = (0, 0, 0)
        _place(po, K, (px, py, 0.96), (0, 0, rnd.uniform(0, math.tau))); n["pots"] += 1
        h = po.dimensions.z
        lid = _lib("cookware", "lid", rnd, target=w * 0.98)
        if lid is not None:
            if rnd.random() < 0.6:                                                                                                    # lid on, slightly off-centre
                _place(lid, K, (px + rnd.uniform(-0.01, 0.01), py + rnd.uniform(-0.01, 0.01), 0.96 + h), (0, 0, rnd.uniform(0, math.tau)))
            else:                                                                                                                    # lid tilted on the rim
                _place(lid, K, (px, py, 0.96 + h + 0.02), (rnd.uniform(0.15, 0.3), 0, rnd.uniform(0, math.tau)))
            n["lids"] += 1
    # --- pass tray of bowls + a cutting board with a knife on the work table
    tray = pu._mat("ir_pu_tray", (0.62, 0.64, 0.66), 0.3, 1.0)
    import bmesh
    bm = bmesh.new(); res = bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=(0.34, 0.5, 0.02), verts=res["verts"]); me = bpy.data.meshes.new("RamenTray"); bm.to_mesh(me); bm.free(); me.materials.append(tray)
    to = bpy.data.objects.new("RamenTray", me); bpy.context.scene.collection.objects.link(to); _place(to, K, (0.3, yt + 0.0, 0.96))
    for k in range(5):
        bo = _lib("dishes", "bowl", rnd, target=0.125)
        if bo is None:
            break
        _place(bo, K, (0.3 + (-0.07 if k % 2 else 0.07), yt - 0.19 + k * 0.095, 0.97), (0, 0, rnd.uniform(0, math.tau))); n["bowls"] += 1
    board = pu._mat("ir_pu_board", (0.78, 0.66, 0.45), 0.55)
    bm = bmesh.new(); res = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=(0.24, 0.38, 0.025), verts=res["verts"]); me = bpy.data.meshes.new("RamenBoard"); bm.to_mesh(me); bm.free(); me.materials.append(board)
    bd = bpy.data.objects.new("RamenBoard", me); bpy.context.scene.collection.objects.link(bd); _place(bd, K, (0.34, yt + 0.55, 0.9725 - 0.0)); bd.location.z += 0.0
    kn = _lib("cutlery", "knife", rnd, target=0.28)
    if kn is not None:
        _place(kn, K, (0.34, yt + 0.55, 0.985), (0, 0, rnd.uniform(-0.4, 0.4))); n["knife"] += 1
    print(f"RAMEN_UTENSILS {n}", flush=True)
    stats["ramen_utensils"] = n
    return n
