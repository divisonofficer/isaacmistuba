"""Open terrace + full-height exterior glazing (P2b, user 2026-10-20: the reference terrace is an OPEN balcony with a glass railing, the living room has floor-to-ceiling glazing).

Hook (architecture_pass, once per room, after glass_partitions): terrace_open.apply(room_name, zc, stats). Everything is off unless ROOM_TERRACE_OPEN=1.

  balcony rooms        every side of the room that lies on the building's outer edge loses its wall (carved from 2 cm to 0.2 m under the ceiling, a head fascia stays), gets a glass railing
                       (steel posts every ~1.4 m, a top rail at 1.1 m, a base channel, glass panes between) 8 cm inside the floor edge, and a photo card + ground plane outside (the big_glass card,
                       ROOM_TERRACE_CARD=garden|street|skyline, default garden). The floor keeps whatever the tile pass gave it (ROOM_FLOOR_TILE_ROOMS=...,balcony).
  ROOM_TERRACE_GLAZE   comma list of room-name prefixes (e.g. living-room,dining-room): their exterior sides get a floor-to-ceiling glass wall with the big_glass card + sun, via
                       big_glass.apply on a frame built for that side (the wall at v = S), so the same mullions / frame / sweep apply. Rooms without an exterior side do nothing
                       (the dining <-> terrace wall is glass_partitions' job: ROOM_GLASS_PARTITIONS=dining-room with ROOM_TERRACE_OPEN=1 lets it glaze the balcony neighbour, no frosted band).
Segments are recorded in scene["ir_bigglass"] (by big_glass.apply), so the late sweep removes wall pieces left floating in the opening (late_walls runs it when ROOM_TERRACE_GLAZE is set too).
"""
from __future__ import annotations

import os

import bpy
from mathutils import Vector

from room_planner import big_glass as bg
from room_planner import proc_boutique_flagship as fl
from room_planner import rooftop_shell as rs

TOL = 0.45


def _bbox(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts), max(p.z for p in pts)


def _sides(room_name):
    """-> (room bbox, floor z, [side]) with side in W/E/S/N for each room edge that lies on the building's outer edge."""
    import room_dressing as rd
    rooms = rd._rooms()
    me = rooms.get(room_name)
    if me is None or "floor" not in me:
        return None, 0.0, []
    x0, x1, y0, y1, fz = _bbox(me["floor"])
    boxes = [_bbox(p["floor"]) for p in rooms.values() if "floor" in p]
    X0, X1 = min(b[0] for b in boxes), max(b[1] for b in boxes)
    Y0, Y1 = min(b[2] for b in boxes), max(b[3] for b in boxes)
    out = [s for s, on in (("W", abs(x0 - X0) < TOL), ("E", abs(x1 - X1) < TOL), ("S", abs(y0 - Y0) < TOL), ("N", abs(y1 - Y1) < TOL)) if on]
    return (x0, x1, y0, y1), fz, out


def _frame(bb, side):
    """(o0, ux, vx, vg, L, depth): ux runs along the wall, vx points from the room's low edge towards v = vg (the wall plane); depth = room extent along vx."""
    x0, x1, y0, y1 = bb
    if side in ("W", "E"):
        return Vector((x0, y0, 0)), Vector((0, 1, 0)), Vector((1, 0, 0)), (0.0 if side == "W" else x1 - x0), y1 - y0, x1 - x0
    return Vector((x0, y0, 0)), Vector((1, 0, 0)), Vector((0, 1, 0)), (0.0 if side == "S" else y1 - y0), x1 - x0, y1 - y0


def _railing(room_name, bb, fz, zc, side, stats):
    o0, ux, vx, vg, L, depth = _frame(bb, side)
    out_sgn = -1 if side in ("W", "S") else 1
    ua, ub, z1 = 0.12, L - 0.12, zc - 0.2
    removed = 0
    for suffix, band, dz in (("wall", 0.35, 0.0), ("exterior", 0.7, 0.3)):
        removed += bg._carve(bpy.data.objects.get(f"{room_name}.{suffix}"), o0, ux, vx, vg, ua, ub, 0.02, z1 + dz, band)
    wl = bpy.data.objects.get(f"{room_name}.wall")
    ztop = max(((wl.matrix_world @ Vector(c)).z for c in wl.bound_box), default=zc) if wl is not None else zc
    bg._patch(wl, o0, ux, vx, vg, [(ua - 0.12, ub + 0.12, z1, ztop)])                     # the head fascia; the jambs are the neighbouring walls
    for o in list(bpy.data.objects):                                                         # window / door meshes in the opening
        if "Window" in o.name and o.type == "MESH":
            d = o.matrix_world.translation - o0
            if abs(d.dot(vx) - vg) < 1.0 and ua < d.dot(ux) < ub:
                bpy.data.objects.remove(o, do_unlink=True)
    at = lambda u, v: (o0 + ux * u + vx * v).xy
    vr = vg - out_sgn * 0.08                                                                  # railing plane, inside the floor edge
    span = ub - ua; n = max(2, int(round(span / 1.4))); pitch = span / n
    black = os.environ.get("ROOM_TERRACE_BLACK") == "1"                                                    # P2b r36: black posts + a black top rail like the reference
    steel = fl._flat("ir_terr_steel_black", (0.02, 0.02, 0.022), 0.4, 0.8) if black else fl._flat("ir_terr_steel", (0.78, 0.78, 0.8), 0.3, 1.0); pane = rs._glass("ir_terr_glass", rough=0.0)
    along_y = side in ("W", "E")

    def box(u, v, z, su, sv, sz):                                                              # su: size along the wall, sv: across it
        x, y = at(u, v)
        return ("box", x, y, fz + z, *((sv, su) if along_y else (su, sv)), sz)
    parts = [box(ua + k * pitch, vr, 0.55, 0.07 if black else 0.05, 0.07 if black else 0.05, 1.1) for k in range(n + 1)]
    parts += [box((ua + ub) / 2, vr, 1.1, span, 0.07 if black else 0.05, 0.05 if black else 0.04), box((ua + ub) / 2, vr, 0.04, span, 0.07, 0.08)]
    fl.mesh_object(f"TerraceRailingFrame({room_name}|{side})", [(steel, parts)], bevel=False)
    q = lambda u, z: ((*at(u, vr), fz + z))
    rs._quads(f"TerraceRailingPanes({room_name}|{side})", [(q(ua + k * pitch + 0.03, 0.1), q(ua + (k + 1) * pitch - 0.03, 0.1), q(ua + (k + 1) * pitch - 0.03, 1.05), q(ua + k * pitch + 0.03, 1.05))
                                                           for k in range(n)], pane, thick=rs.GLASS_THICK)
    kind = os.environ.get("ROOM_TERRACE_CARD", "garden")
    if kind in bg.KINDS:                                                                      # the open edge looks onto a photo, not onto the void
        if out_sgn > 0:
            S, side_ = vg, 1
        else:
            S, side_ = depth, -1
        cq, cm, gq, grgb = bg._card(kind, lambda u, v: tuple(at(u, v)), L, side_, vg if out_sgn > 0 else 0.0, L / 2)
        rs._quads(f"TerraceCard({room_name}|{side})", [cq], cm)
        if kind == "skyline" and os.environ.get("ROOM_TERRACE_GROUND") != "1":         # an elevated skyline: the card reaches ~9 m below the balcony, so no ground plane (P2b r26: a long smeared streak of rooftops at the railing); ROOM_TERRACE_GROUND=1 restores it
            pass
        elif os.environ.get("BIGGLASS_FLAT_GROUND") != "1" and bg.photo_card(kind):          # the ground carries the photo's own bottom strip, like big_glass: no flat green slab ending in a hard line (P2b r22 ENV-01)
            bg._photo_ground(f"TerraceGround({room_name}|{side})", gq, kind)
        else:
            gm = bpy.data.materials.get(f"ir_bg_ground_{kind}")
            if gm is None:
                gm = bpy.data.materials.new(f"ir_bg_ground_{kind}"); gm.use_nodes = True; gb = gm.node_tree.nodes["Principled BSDF"]
                gb.inputs["Base Color"].default_value = (*grgb, 1); gb.inputs["Roughness"].default_value = 0.9
            rs._quads(f"TerraceGround({room_name}|{side})", [gq], gm)
    stats["terrace_open"] = stats.get("terrace_open", 0) + 1
    return removed


def _glaze(room_name, bb, fz, zc, side, stats, rng):
    """big_glass.apply on this side: its wall sits at v = S, u along the wall."""
    x0, x1, y0, y1 = bb
    if side == "W":
        L, S, at = y1 - y0, x1 - x0, (lambda u, v: (x1 - v, y0 + u))
    elif side == "E":
        L, S, at = y1 - y0, x1 - x0, (lambda u, v: (x0 + v, y0 + u))
    elif side == "S":
        L, S, at = x1 - x0, y1 - y0, (lambda u, v: (x0 + u, y1 - v))
    else:
        L, S, at = x1 - x0, y1 - y0, (lambda u, v: (x0 + u, y0 + v))
    keep = {k: os.environ.get(k) for k in ("ROOM_BIGGLASS", "BIGGLASS_ROOMS")}
    os.environ["ROOM_BIGGLASS"] = os.environ.get("ROOM_TERRACE_CARD", "garden"); os.environ.pop("BIGGLASS_ROOMS", None)
    try:
        n = [0]
        def name(base):
            n[0] += 1
            return f"{base}({room_name}|{side}|{n[0]})"
        return bg.apply(L, S, zc, at, name, rng, stats, room=room_name)
    finally:
        for k, v in keep.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def apply(room_name, zc, stats, rng=None):
    if os.environ.get("ROOM_TERRACE_OPEN") != "1":
        return 0
    import random
    rng = rng or random.Random(7)
    rtype = room_name.split("_")[0]
    glaze = tuple(x for x in os.environ.get("ROOM_TERRACE_GLAZE", "").split(",") if x)
    if rtype != "balcony" and not (glaze and rtype in glaze):
        return 0
    bb, fz, sides = _sides(room_name)
    if bb is None or not sides:
        return 0
    n = 0
    only = [x for x in os.environ.get("ROOM_TERRACE_GLAZE_SIDES", "").split(",") if x]     # e.g. S,E: glaze only these exterior sides (W/E/S/N) of a ROOM_TERRACE_GLAZE room
    for side in sides:
        if rtype != "balcony" and only and side not in only:
            continue
        if rtype == "balcony":
            n += 1 if _railing(room_name, bb, fz, zc, side, stats) >= 0 else 0
        else:
            n += 1 if _glaze(room_name, bb, fz, zc, side, stats, rng) else 0
    return n
