"""Paired abstract prints (P2b refs: 'pairs of abstract prints', ours: random landscape photos). Late pass (kit_lighting; ROOM_ABSTRACT_ART = room-name prefixes, e.g. living-room,bedroom,hallway).

Every Infinigen WallArtFactory picture inside a listed room gets a SQUARE abstract print from data/venue_refs/print_assets_v3/art_wall_<nn>.png (ROOM_ABSTRACT_ART_IMGS=01,02,03,04 picks the set; default 14,09,10,02: soft blue-grey waves + indigo watercolour + sage fern + olive, cream-and-teal-compatible) and its frame is scaled to
0.7 x 0.7 m; the pictures of a room are taken two at a time and each PAIR shows the same print (so two hang side by side as a diptych). Stats: stats["abstract_art"] = pictures changed.
"""
from __future__ import annotations

import os

import bpy
from mathutils import Vector

ROOT = "/jarvis/project/robomituba/data/venue_refs/print_assets_v3/art_wall_%s.png"


def apply(stats):
    pref = tuple(x for x in os.environ.get("ROOM_ABSTRACT_ART", "").split(",") if x)
    if not pref:
        return 0
    from room_planner import terrace_open as to
    import room_dressing as rd
    imgs = [x for x in (os.environ.get("ROOM_ABSTRACT_ART_IMGS") or "14,09,10,02").split(",") if x]
    n = 0
    arts = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("WallArtFactory")]
    for rname, parts in rd._rooms().items():
        if not rname.startswith(pref) or "floor" not in parts:
            continue
        x0, x1, y0, y1, fz = to._bbox(parts["floor"])
        here = sorted((o for o in arts if x0 - 0.3 <= o.matrix_world.translation.x <= x1 + 0.3 and y0 - 0.3 <= o.matrix_world.translation.y <= y1 + 0.3 and o.matrix_world.translation.z > 0.6),
                      key=lambda o: (round(o.matrix_world.translation.x, 1), round(o.matrix_world.translation.y, 1)))
        for k, o in enumerate(here):
            path = ROOT % imgs[(k // 2 + sum(map(ord, rname))) % len(imgs)]
            if not os.path.isfile(path):
                continue
            im = bpy.data.images.load(path, check_existing=True)
            for m in o.data.materials:
                if m is not None and m.use_nodes:
                    for nd in m.node_tree.nodes:
                        if nd.bl_idname == "ShaderNodeTexImage":
                            nd.image = im
            d = o.dimensions
            w, h = (d.y, d.z) if d.y > 0 and d.z > 0 else (0.7, 0.7)
            o.scale = (o.scale.x, o.scale.y * 0.7 / max(w, 1e-3), o.scale.z * 0.7 / max(h, 1e-3))
            n += 1
    bpy.context.view_layer.update()
    stats["abstract_art"] = n
    return n
