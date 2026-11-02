"""ir_fixture custom property on every light (request from the opticalnav simulator, 10-23): the name of the fixture MESH object the light belongs to, or "" when it has none (kit_svc*, sun / area fills, big-glass sun).
Post-pass, last in kit_lighting (always on; ROOM_FIXTURE_TAGS=0 off): each light is paired with the smallest non-architectural mesh whose bounding box (grown by 0.12 m) contains the light's position, preferring a mesh
whose name looks like a fixture (light / lamp / pendant / track / panel / strip / tube / downlight / fixture / sconce / chandelier / luminaire). Lights that already carry ir_fixture keep it.
    import fixture_tags; stats["fixture_tags"] = fixture_tags.apply(stats)
"""
from __future__ import annotations

import os
import re

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

NO_MESH = ("kit_svc", "ir_real_sun", "sun", "fill", "area_fill", "bigglass", "big_glass", "street", "env_", "window")
FIXTURE = ("light", "lamp", "pendant", "track", "panel", "strip", "tube", "downlight", "fixture", "sconce", "chandelier", "luminaire", "ceilingfixture", "spot", "hangingbars", "trackloop", "rail", "truss")
BIG_NEAR = 0.8                                                   # m: a light this close to a vertex of a fixture-named mesh belongs to it when no bbox contains it
ARCH = (".wall", ".floor", ".ceiling", "exterior", "ground", "backdrop", "card", "window", "baseboard", "skirt")
ROOM_ID = re.compile(r"^[\w\-]+_\d+/\d+")                      # a room object: "break-room_0/0", "hallway_0/1" (merged room shells are thousands of m3 and contain every light)
DECOR = ("vase", "plant", "book", "cup", "mug", "bowl", "plate", "bottle", "jar", "candle", "flower", "frame", "pillow", "cushion", "rug", "carpet", "curtain", "blanket", "towel", "sofa", "chair", "stool",
         "table", "desk", "bed", "shelf", "cabinet", "tree", "pot", "basket", "sculpture", "painting", "mirror", "clock", "toy", "fruit", "food", "cake", "clothes", "shirt")      # decor / furniture never carries a ceiling light


def apply(stats):
    if os.environ.get("ROOM_FIXTURE_TAGS") == "0":
        return {}
    meshes, big, bigarch = [], [], []
    for o in bpy.data.objects:
        if o.type != "MESH" or o.hide_render:
            continue
        n = o.name.lower()
        if any(k in n for k in ARCH) or ROOM_ID.match(o.name):
            continue
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))); hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
        vol = (hi.x - lo.x) * (hi.y - lo.y) * (hi.z - lo.z)
        fx = any(k in n for k in FIXTURE)
        if not fx and any(k in n for k in DECOR):
            continue
        if vol > 3.0:
            if vol <= 400.0:                                                                    # last resort (museum rotunda: lights inside RotundaDomeFactory 260 m3, StripCorniceFactory 99 m3): a big non-architectural mesh that CONTAINS the light
                bigarch.append((o.name, Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts))), Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))), vol))
            if not fx or len(o.data.vertices) > 400000:
                continue
            big.append((o.name, KDTree(len(o.data.vertices)), o.matrix_world)); kd = big[-1][1]               # a merged rail / track loop / hanging bars: pair by the nearest vertex instead of by bbox
            for i, v in enumerate(o.data.vertices):
                kd.insert(o.matrix_world @ v.co, i)
            kd.balance(); continue
        meshes.append((o.name, lo, hi, vol, fx))
        if fx and len(o.data.vertices) <= 50000:                                                           # small fixture meshes also join the nearest-vertex fallback (a hanging bar the light sits 0.5 m under)
            kd = KDTree(len(o.data.vertices)); big.append((o.name, kd, o.matrix_world))
            for i, v in enumerate(o.data.vertices):
                kd.insert(o.matrix_world @ v.co, i)
            kd.balance()
    tagged = paired = 0
    for L in bpy.data.objects:
        if L.type != "LIGHT" or "ir_fixture" in L:
            continue
        tagged += 1
        ln = L.name.lower()
        if ln == "area" or ln.startswith("area.") or ln == "sun" or ln.startswith("sun.") or any(k in ln for k in NO_MESH):               # Blender's default "Area" / "Sun" lights are fills
            L["ir_fixture"] = ""; continue
        p = L.matrix_world.translation; m = 0.12
        best = None
        for name, lo, hi, vol, fx in meshes:
            if lo.x - m <= p.x <= hi.x + m and lo.y - m <= p.y <= hi.y + m and lo.z - m <= p.z <= hi.z + m:
                key = (0 if fx else 1, vol)
                if best is None or key < best[0]:
                    best = (key, name)
        if best is None:
            for name, kd, mw in big:
                co, i, d = kd.find(p)
                if d <= BIG_NEAR and (best is None or d < best[0]):
                    best = (d, name)
            if best is not None:
                best = ((0, best[0]), best[1])
        if best is None:
            for name, lo, hi, vol in sorted(bigarch, key=lambda t: t[3]):                                   # inside a big non-architectural mesh: the smallest one wins
                if lo.x - m <= p.x <= hi.x + m and lo.y - m <= p.y <= hi.y + m and lo.z - m <= p.z <= hi.z + m:
                    best = ((2, vol), name); break
        L["ir_fixture"] = best[1] if best else ""
        paired += int(best is not None)
    return {"lights": tagged, "paired": paired}
