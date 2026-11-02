"""General wall dressing for offices, lounges and meeting rooms (user 10-23 'walls are empty'). Hooked from kit_lighting after the ramen dressing, only when ROOM_WALL_DRESSING=1.

    from wall_dressing import apply; stats["wall_dressing"] = apply(stats)

Env: ROOM_WALL_DRESSING=1
     ROOM_WALL_DRESSING_ROOMS=break-room,meeting-room,office,hallway   room-name prefixes that get it (default: break-room, meeting-room, office, hallway)
     ROOM_WALL_DRESSING_RGB="r,g,b;r,g,b;..."   accent palette (linear; default muted teal / mustard / terracotta / navy / sage)
     ROOM_WALL_DRESSING_DENSITY=1.0     pieces per 6 m2 of floor (clamped 2..8 per room)
Per room, from its floor box: the four inner wall faces are scanned for free intervals (clear of every door / window / glass partition / furniture / column that stands within 0.6 m of that wall between 0.3 and
2.4 m), and the pieces are hung at the centres of the longest free intervals, 1.3-1.6 m above the floor, facing into the room. What hangs depends on the room type:
  meeting-room   a big whiteboard with abstract marker strokes, a wall display, two framed prints, an acoustic felt panel group
  break-room     (lounge / cafe / pantry) framed abstract prints (colour blocks), a cork pin board with notes, an acoustic felt panel group, a small shelf with a plant and books, a round wall clock
  office         framed prints, a pin board, a small shelf
  hallway        framed prints and a small sign plate
Text is abstract (bars and strokes): no readable words, no brands."""
from __future__ import annotations

import math
import os
import random
import re

import bpy
from mathutils import Vector

from room_planner import proc_assets as pa

R0 = (0, 0, 0)
TYPES = {"meeting-room": ("whiteboard", "display", "print", "print", "felt"), "break-room": ("print", "pinboard", "felt", "shelf", "print", "clock", "print"),
         "office": ("print", "pinboard", "shelf", "print"), "hallway": ("print", "sign", "print", "print")}


def _bb(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts), min(p.z for p in pts), max(p.z for p in pts)


def _piece(kind, r, pal):
    """One piece in its own frame: back at x = 0, front +x, centred on y, z up from its bottom. -> (groups, width, height)."""
    mat = lambda n, rgb, ro=0.6: pa._flat(n, rgb, ro)
    frame_b = mat("ir_wd_frame_black", (0.03, 0.03, 0.035), 0.5); frame_o = pa._flat("ir_wd_frame_oak", (0.5, 0.33, 0.17), 0.5, wood=True); white = mat("ir_wd_white", (0.93, 0.93, 0.9)); cork = mat("ir_wd_cork", (0.5, 0.33, 0.18), 0.8)
    ink = mat("ir_wd_ink", (0.03, 0.03, 0.04)); red = mat("ir_wd_red", (0.6, 0.05, 0.04)); blue = mat("ir_wd_blue", (0.05, 0.12, 0.35)); alu = pa._flat("ir_wd_alu", (0.7, 0.72, 0.74), 0.3, 1.0)
    G = {}
    add = lambda m, p: G.setdefault(m.name, (m, []))[1].append(p)
    if kind == "print":
        w, h = r.choice(((0.6, 0.8), (0.9, 0.6), (0.7, 0.7), (0.5, 0.7))); fr = r.choice((frame_b, frame_o))
        add(fr, ("box", (0.02, 0, h / 2), (0.04, w, h), R0)); add(white, ("box", (0.043, 0, h / 2), (0.006, w - 0.08, h - 0.08), R0))
        for k in range(r.randint(2, 4)):                                                       # abstract colour blocks
            c = r.choice(pal); bw, bh = r.uniform(0.15, 0.4) * w, r.uniform(0.15, 0.4) * h
            add(mat(f"ir_wd_c{int(c[0] * 100)}_{int(c[1] * 100)}_{int(c[2] * 100)}", c), ("box", (0.048, r.uniform(-0.2, 0.2) * w, h / 2 + r.uniform(-0.2, 0.2) * h), (0.004, bw, bh), R0))
        return G, w, h
    if kind == "whiteboard":
        w, h = r.choice((1.8, 2.2, 2.4)), 1.0
        add(alu, ("box", (0.02, 0, h / 2), (0.04, w, h), R0)); add(white, ("box", (0.043, 0, h / 2), (0.006, w - 0.06, h - 0.06), R0)); add(alu, ("box", (0.05, 0, 0.02), (0.08, w * 0.6, 0.03), R0))
        for k in range(r.randint(6, 9)):
            add(r.choice((ink, blue, red)), ("box", (0.048, r.uniform(-0.38, 0.38) * w, h * (0.85 - 0.09 * (k % 6))), (0.003, r.uniform(0.1, 0.3) * w, 0.012), (0, 0, 0)))
        return G, w, h
    if kind == "display":
        w, h = 1.3, 0.75
        add(frame_b, ("box", (0.025, 0, h / 2), (0.05, w, h), R0)); add(mat("ir_wd_screen", (0.01, 0.012, 0.016), 0.06), ("box", (0.052, 0, h / 2), (0.004, w - 0.04, h - 0.04), R0))
        return G, w, h
    if kind == "pinboard":
        w, h = r.choice((0.9, 1.2)), 0.7
        add(frame_o, ("box", (0.02, 0, h / 2), (0.04, w, h), R0)); add(cork, ("box", (0.043, 0, h / 2), (0.006, w - 0.06, h - 0.06), R0))
        for k in range(r.randint(7, 11)):
            c = r.choice(((0.93, 0.93, 0.9), (0.9, 0.8, 0.35), (0.85, 0.5, 0.5), (0.5, 0.7, 0.85)))
            add(mat(f"ir_wd_note{int(c[0] * 100)}_{int(c[2] * 100)}", c), ("box", (0.05, r.uniform(-0.4, 0.4) * w, h / 2 + r.uniform(-0.35, 0.35) * h), (0.004, r.uniform(0.08, 0.14), r.uniform(0.08, 0.14)), (0, 0, r.uniform(-0.2, 0.2))))
        return G, w, h
    if kind == "felt":                                                                          # a group of acoustic felt tiles in two or three colours
        n = r.choice((3, 4, 6)); cols = r.sample(list(pal), min(3, len(pal))); w = n * 0.42; h = 0.4
        for k in range(n):
            c = cols[k % len(cols)]
            add(mat(f"ir_wd_felt{int(c[0] * 100)}_{int(c[1] * 100)}_{int(c[2] * 100)}", c, 0.95), ("box", (0.015, -w / 2 + 0.21 + k * 0.42, h / 2 + (0.1 if k % 2 else 0.0)), (0.03, 0.38, 0.38), R0))
        return G, w, h + 0.1
    if kind == "shelf":
        w = 0.8; add(frame_o, ("box", (0.1, 0, 0.0), (0.2, w, 0.03), R0)); add(frame_b, ("box", (0.01, -w / 3, -0.03), (0.02, 0.02, 0.06), R0)); add(frame_b, ("box", (0.01, w / 3, -0.03), (0.02, 0.02, 0.06), R0))
        for k in range(r.randint(3, 5)):
            c = r.choice(pal); add(mat(f"ir_wd_book{int(c[0] * 100)}_{int(c[1] * 100)}", c), ("box", (0.1, -w / 2 + 0.08 + k * 0.045, 0.14), (0.14, 0.035, r.uniform(0.2, 0.26)), R0))
        add(mat("ir_wd_pot", (0.8, 0.78, 0.7)), ("cyl", (0.1, w / 2 - 0.15, 0.08), (0.06, 0.07, 0.14), R0)); add(mat("ir_wd_leaf", (0.07, 0.25, 0.07)), ("sph", (0.1, w / 2 - 0.15, 0.22), (0.1, 0.1, 0.12), R0))
        return G, w, 0.4
    if kind == "clock":
        add(frame_b, ("cyl", (0.02, 0, 0.0), (0.2, 0.2, 0.04), (0, 1.5708, 0))); add(white, ("cyl", (0.045, 0, 0.0), (0.18, 0.18, 0.006), (0, 1.5708, 0)))
        add(ink, ("box", (0.05, 0, 0.05), (0.004, 0.012, 0.1), R0)); add(ink, ("box", (0.05, 0.04, 0.0), (0.004, 0.08, 0.012), R0))
        return G, 0.4, 0.4
    w, h = 0.35, 0.12                                                                            # a small sign plate
    add(frame_b, ("box", (0.01, 0, h / 2), (0.02, w, h), R0)); add(white, ("box", (0.022, 0, h / 2), (0.004, w - 0.02, 0.03), R0))
    return G, w, h


def apply(stats):
    if os.environ.get("ROOM_WALL_DRESSING") != "1":
        return 0
    only = tuple(x.strip() for x in (os.environ.get("ROOM_WALL_DRESSING_ROOMS") or "break-room,meeting-room,office,hallway").split(",") if x.strip())
    pal = [tuple(float(v) for v in c.split(",")) for c in (os.environ.get("ROOM_WALL_DRESSING_RGB") or "0.04,0.25,0.28;0.6,0.42,0.06;0.45,0.18,0.1;0.05,0.1,0.3;0.3,0.4,0.28").split(";")]
    dens = float(os.environ.get("ROOM_WALL_DRESSING_DENSITY") or 1.0)
    rng = random.Random(41)
    objs = [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None]
    boxes = []
    for o in objs:
        if o.name.endswith((".floor", ".ceiling", ".wall", ".exterior", ".meshed")) or o.name.startswith(("RamenWallDecor", "WallDressing")) or re.match(r"^[a-z\-]+_\d+/\d+$", o.name):
            continue                                              # room shells (the room's own mesh objects) are the walls themselves, not things standing at them
        boxes.append((_bb(o), o.name))
    n_total = 0
    for f in [o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith(".floor")]:
        if not f.name.startswith(only):
            continue
        rtype = f.name.split("_")[0]; kinds = TYPES.get(rtype)
        if rtype == "office" and os.environ.get("ROOM_WALL_OFFICE_FELT") == "1":            # O3 r3 refs: acoustic wall panels in the private offices
            kinds = ("print", "felt", "pinboard", "print", "shelf")
        if not kinds:
            continue
        x0, x1, y0, y1, fz, _ = _bb(f)
        area = (x1 - x0) * (y1 - y0)
        if area < 6.0:
            continue
        n = max(2, min(8, int(round(area / 6.0 * dens))))
        cand = []                                                                               # free intervals: (length, wall id, start, end)
        for wid, (ln, lo, hi, fixed) in {"S": ((x1 - x0), x0, x1, y0), "N": ((x1 - x0), x0, x1, y1), "W": ((y1 - y0), y0, y1, x0), "E": ((y1 - y0), y0, y1, x1)}.items():
            blocked = []
            for (bx0, bx1, by0, by1, bz0, bz1), nm in boxes:
                if bz1 < fz + 0.3 or bz0 > fz + 2.4:
                    continue
                d_wall = (min(abs(by0 - fixed), abs(by1 - fixed)) if wid in "SN" else min(abs(bx0 - fixed), abs(bx1 - fixed)))
                inside = (by0 - 0.1 <= fixed <= by1 + 0.1) if wid in "SN" else (bx0 - 0.1 <= fixed <= bx1 + 0.1)
                if d_wall < 0.6 or inside:
                    a, b = (bx0, bx1) if wid in "SN" else (by0, by1)
                    if b > lo - 0.5 and a < hi + 0.5 and (bx1 - bx0 > 0.01 or wid in "WE") and (by1 - by0 > 0.01 or wid in "SN"):
                        blocked.append((a - 0.25, b + 0.25))
            blocked.sort(); cur = lo + 0.4
            for a, b in blocked + [(hi - 0.4, hi)]:
                if a - cur >= 0.8:
                    cand.append((a - cur, wid, cur, a))
                cur = max(cur, b)
        cand.sort(key=lambda c: -c[0])
        placed = 0; picks = list(kinds); rng.shuffle(picks)
        for ln, wid, a, b in cand:
            if placed >= n:
                break
            m = 0.4; pos = a + m
            while placed < n and pos < b - 0.3:
                kind = picks[placed % len(picks)]
                G, w, h = _piece(kind, rng, pal)
                if pos + w > b:
                    break
                c = pos + w / 2
                zb = {"whiteboard": 0.9, "display": 1.0, "shelf": 1.4, "clock": 2.0, "sign": 1.9, "felt": 1.15}.get(kind, 1.25) + rng.uniform(-0.05, 0.1)
                if kind == "clock":
                    zb += 0.0
                o = pa._prims(f"WallDressing({f.name}|{kind}|{placed})", [(m_, ps) for m_, ps in G.values()])
                rz, loc = {"S": (math.pi / 2, (c, y0 + 0.012, fz + zb)), "N": (-math.pi / 2, (c, y1 - 0.012, fz + zb)), "W": (0.0, (x0 + 0.012, c, fz + zb)), "E": (math.pi, (x1 - 0.012, c, fz + zb))}[wid]
                o.rotation_euler = (0, 0, rz); o.location = loc; o["src"] = "arch:kit_stage"
                placed += 1; n_total += 1; pos += w + 0.5
        print(f"WALL_DRESSING {f.name} type={rtype} pieces={placed}/{n} free_walls={len(cand)}", flush=True)
    stats["wall_dressing"] = {"pieces": n_total}
    return n_total
