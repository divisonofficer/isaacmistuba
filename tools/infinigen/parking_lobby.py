"""S28F car-park pedestrian spaces (kit stage, idempotent via scene["ir_parking_lobby"]); ROOM_PARKING_LOBBY=1. User 2026-10-25: 'the lift has a strange panel; the pedestrian spaces are lacking'.
Rooms: hallway_0/0 ramp entry, hallway_0/1 lift lobby, hallway_0/2 stair (S28F, x 34-40). ROOM_PARKING_LOBBY_SKIP=<plug,clean,lobby,lifts,stair,ramp,hall> (r15 refs pass 10-25: lobby plain white + grey skirting + 3 recessed panels + stainless split lift leaves, no signs/bench/dado;
        ramp charcoal stripe + exposed pipes/trays + escape signs; stair blue direction sign + red recessed cabinet; hall column ID bands + corner guards + blue direction boards + cones + bollards) switches parts off.
plug    window plugs that stuck out 0.2 m into the rooms (the white slab over the right lift) are pressed flush with the wall face
clean   framed art, wall clock / small wall items and round ceiling domes (+ their lamps) go from the three rooms
lobby   porcelain tile floor, door mat, glass leaf on the door to the parking hall, blue dado + yellow/black stripe band, corner guards, 'B1' level graphic, exit / pay / wayfinding signs,
        steel bench, bin, extinguisher cabinet, two linear LED ceiling lights
lifts   steel surround round each lift, a call-button panel between them, a floor indicator above each
stair   the open-tread wooden flight is replaced by a solid concrete flight with yellow nosings, tube handrails both sides, the same dado band, a red fire door, an emergency light
ramp    a yellow/black height-limit bar at the ramp mouth and yellow bollards at its edges
"""
from __future__ import annotations

import math
import os

import bpy
from mathutils import Vector

RAMP, LOBBY, STAIR = "hallway_0/0", "hallway_0/1", "hallway_0/2"


def _bb(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def _room(n):
    import wall_face                                             # box out to the walls' INNER faces: the W walls of the hallways / warehouse sit ~0.11 m inside the floor box (audit 10-25)
    return wall_face.inner_box(n)


def _fl():
    from room_planner import proc_boutique_flagship as fl
    return fl


def _flat(name, rgb, rough=0.5, metal=0.0, transmission=0.0):
    from room_planner import proc_assets as pa
    m = pa._flat(name, rgb, rough, metal, transmission=transmission); m["weathered"] = True
    return m


def _emit(name, rgb, s):
    m = _flat(name, rgb, 0.4); b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*rgb, 1); b.inputs["Emission Strength"].default_value = s
    return m


def _in(o, lo, hi, pad=0.2):
    b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
    return lo[0] - pad < cx < hi[0] + pad and lo[1] - pad < cy < hi[1] + pad


def _light(name, loc, energy, sx, sy, rgb=(1.0, 0.95, 0.88)):
    ld = bpy.data.lights.new(name, "AREA"); ld.energy = energy; ld.shape = "RECTANGLE"; ld.size = sx; ld.size_y = sy; ld.color = rgb
    o = bpy.data.objects.new(name, ld); o.location = loc; bpy.context.scene.collection.objects.link(o)


SEG = {"Lt": (-0.5, 0.25, 0, 0.5), "Lb": (-0.5, -0.25, 0, 0.5), "Tb": (-0.08, 0.5, 0.84, 0), "Mb": (-0.08, 0, 0.84, 0), "Bb": (-0.08, -0.5, 0.84, 0), "Rt2": (0.4, 0.25, 0, 0.42), "Rb2": (0.4, -0.25, 0, 0.42), "L": (-0.5, 0, 0, 1), "R": (0.5, 0, 0, 1), "Rt": (0.5, 0.25, 0, 0.5), "Rb": (0.5, -0.25, 0, 0.5), "T": (0, 0.5, 1, 0), "M": (0, 0, 1, 0), "B": (0, -0.5, 1, 0), "C": (0, 0, 0, 1)}
GLYPH = {"B": "L Rt2 Rb2 Tb Mb Bb", "1": "C", "P": "L Rt T M", "A": "L R T M", "0": "L R T B", "2": "T Rt M Lb B", "3": "T Rt M Rb B", "4": "Lt Rt M Rb", "5": "T Lt M Rb B",
         "6": "T L M Rb B", "7": "T R", "8": "L R T M B", "9": "T Lt R M B"}


def _text(word, wall, line, u0, zc, h, mat):
    """Block letters on a wall face. wall 'N'/'S' (u = x) or 'E'/'W' (u = y); `line` = the face coordinate (a hair inside the room)."""
    prims = []; w = h * 0.62; t = h * 0.14; pitch = w + h * 0.25
    dr = 1 if wall in "NW" else -1                                    # the viewer's right along u (r14: S-wall 'P' read as '9', mirrored)
    for i, ch in enumerate(word):
        cu = u0 + dr * i * pitch
        for sx, sz, sw, sh in (SEG[k] for k in GLYPH[ch].split()):
            lu, lz = cu + dr * sx * w, zc + sz * h
            du, dz = (sw * w if sw else t), (sh * h if sh else t)
            prims.append(("box", lu, line, lz, du, 0.012, dz) if wall in "NS" else ("box", line, lu, lz, 0.012, du, dz))
    return prims


def _dedupe_plugs(stats):
    """S28F root cause of the black plugs: parking_fixtures makes one plug per 'window' object AND one per its WindowFactory child, so every opening got two overlapping boxes with coincident faces, and Cycles renders that coincident pair black. Keep the first of each overlapping pair."""
    plugs = sorted([o for o in bpy.data.objects if o.name.startswith("ParkingFixtures(windowplug") and o.type == "MESH"], key=lambda o: o.name)
    kept, gone = [], 0
    def ov(a0, a1, b0, b1):
        return max(0.0, min(a1, b1) - max(a0, b0)) / max(1e-6, min(a1 - a0, b1 - b0))
    for o in plugs:
        b0, b1 = _bb(o)
        if any(ov(b0[1], b1[1], c1[1], c2[1]) > 0.7 and ov(b0[2], b1[2], c1[2], c2[2]) > 0.7 and ov(b0[0], b1[0], c1[0], c2[0]) > 0.3 for c1, c2 in kept):
            bpy.data.objects.remove(o, do_unlink=True); gone += 1
        else:
            kept.append((b0, b1))
    stats["pl_plugs_deduped"] = gone


def _plug(stats):
    _dedupe_plugs(stats)
    k = 0
    for rn in (RAMP, LOBBY, STAIR):
        lo, hi = _room(rn)
        if lo is None:
            continue
        for o in [o for o in bpy.data.objects if o.name.startswith("ParkingFixtures(windowplug") and o.type == "MESH" and _in(o, lo, hi, 0.5)]:
            b0, b1 = _bb(o)
            if b0[0] < hi[0] - 0.01 and b1[0] > hi[0] - 0.5:               # east-wall plug sticking into the room: slid out until its face sits a hair behind the wall face (squashing it left black z-fighting slabs)
                o.location.x += hi[0] + 0.004 - b0[0]
                pm = _flat("ir_pl_plugwall", (0.6, 0.6, 0.58), 0.9)            # r21: plain grey wall, NO emission (the scenes feed an IR/PBR dataset: an emitting wall becomes a GT emitter). Solid from the wall's inner face outwards, so its visible face is flush with the wall beside it.
                o.data = o.data.copy(); o.data.materials.clear(); o.data.materials.append(pm)
                k += 1
    stats["pl_plugs_flushed"] = k


def _clean(stats):
    k = 0
    for rn in (RAMP, LOBBY, STAIR):
        lo, hi = _room(rn)
        if lo is None:
            continue
        for o in list(bpy.data.objects):
            if o.name.startswith(("WallArtFactory", "ClinicWallItemFactory", "AboCeilingFixtureFactory", "PointLampFactory(added)")) and _in(o, lo, hi):
                bpy.data.objects.remove(o, do_unlink=True); k += 1
    stats["pl_clean_removed"] = k


def _gaps(axis, line, lo_, hi_):
    out = []
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.startswith(("door", "DoorCasing", "ElevatorDoor", "ParkingLiftFrame")):
            b0, b1 = _bb(o)
            if b0[1 - axis] - 0.3 <= line <= b1[1 - axis] + 0.3 and b1[axis] > lo_ and b0[axis] < hi_:
                out.append((b0[axis] - 0.1, b1[axis] + 0.1))
    segs, cur = [], lo_
    for a, b in sorted(out):
        if a - cur > 0.15:
            segs.append((cur, a))
        cur = max(cur, b)
    if hi_ - cur > 0.15:
        segs.append((cur, hi_))
    return segs


def _dado(room, stats):
    """Blue-grey painted dado (0-1.0 m) + 10 cm yellow/black stripe band + corner guards on the four walls, broken at doors / lifts."""
    lo, hi = _room(room); fl = _fl()
    blue = _flat("ir_pl_dado", (0.18, 0.28, 0.42), 0.55); yel = _flat("ir_pl_yellow", (0.9, 0.68, 0.05), 0.5); blk = _flat("ir_pl_black", (0.03, 0.03, 0.03), 0.5)
    d, y_, k_ = [], [], []; z0 = lo[2]
    walls = (("S", 0, lo[1] + 0.012, lo[0], hi[0]), ("N", 0, hi[1] - 0.012, lo[0], hi[0]), ("W", 1, lo[0] + 0.012, lo[1], hi[1]), ("E", 1, hi[0] - 0.012, lo[1], hi[1]))
    for nm, ax, line, a0, a1 in walls:
        for u0, u1 in _gaps(ax, line, a0 + 0.02, a1 - 0.02):
            c, w = (u0 + u1) / 2, u1 - u0
            d.append(("box", c, line, z0 + 0.5, w, 0.012, 1.0) if ax == 0 else ("box", line, c, z0 + 0.5, 0.012, w, 1.0))
            n = max(1, int(w / 0.3))
            for i in range(n):                                   # 15 cm diagonal-look stripes: alternating 30 cm blocks
                cc = u0 + (i + 0.5) * w / n
                (y_ if i % 2 == 0 else k_).append(("box", cc, line, z0 + 1.05, w / n, 0.014, 0.1) if ax == 0 else ("box", line, cc, z0 + 1.05, 0.014, w / n, 0.1))
    for cx, cy in ((lo[0], lo[1]), (lo[0], hi[1]), (hi[0], lo[1]), (hi[0], hi[1])):
        for i in range(6):
            (y_ if i % 2 == 0 else k_).append(("box", cx + (0.04 if cx == lo[0] else -0.04), cy + (0.04 if cy == lo[1] else -0.04), z0 + 0.1 + i * 0.2 + 0.1, 0.08, 0.08, 0.2))
    fl.mesh_object(f"ParkingDado({room})", [(blue, d), (yel, y_), (blk, k_)], bevel=False)


def _skirt(room, h=0.1):
    """10 cm grey skirting on the four walls, broken at doors / lifts."""
    lo, hi = _room(room); g = _flat("ir_pl_skirt", (0.42, 0.42, 0.43), 0.5); pr = []
    for ax, line, a0, a1 in ((0, lo[1] + 0.006, lo[0], hi[0]), (0, hi[1] - 0.006, lo[0], hi[0]), (1, lo[0] + 0.006, lo[1], hi[1]), (1, hi[0] - 0.006, lo[1], hi[1])):
        for u0, u1 in _gaps(ax, line, a0 + 0.02, a1 - 0.02):
            c, w = (u0 + u1) / 2, u1 - u0
            pr.append(("box", c, line, lo[2] + h / 2, w, 0.012, h) if ax == 0 else ("box", line, c, lo[2] + h / 2, 0.012, w, h))
    _fl().mesh_object(f"ParkingSkirt({room})", [(g, pr)], bevel=True)


def _exit_sign(name, wall, line, u, z):
    """A lit green running-man escape sign (green box, white pictogram strokes) on a wall face."""
    green = _emit("ir_pl_exit", (0.05, 0.75, 0.25), 3.0); white = _flat("ir_pl_white", (0.95, 0.95, 0.93), 0.5); sd = 1 if wall in "WS" else -1
    def bx(du, dz, su, sz, dd=0.035):
        return ("box", line + sd * dd, u + du, z + dz, 0.012, su, sz) if wall in "WE" else ("box", u + du, line + sd * dd, z + dz, su, 0.012, sz)
    body = [("box", line + sd * 0.025, u, z, 0.05, 0.42, 0.16) if wall in "WE" else ("box", u, line + sd * 0.025, z, 0.42, 0.05, 0.16)]
    fig = [bx(-0.1, 0.04, 0.03, 0.03), bx(-0.1, 0.0, 0.025, 0.05), bx(-0.13, -0.03, 0.05, 0.015), bx(-0.07, -0.04, 0.04, 0.015), bx(0.05, 0.0, 0.16, 0.022), bx(0.12, 0.02, 0.05, 0.015), bx(0.12, -0.02, 0.05, 0.015)]
    _fl().mesh_object(name, [(green, body), (white, fig)], bevel=True)


def _panels(name, lo, hi, n, zc=2.57):
    """n broad rectangular recessed light panels (1.2 x 0.6 m) along the room's long axis, with area lights."""
    led = _emit("ir_pl_panel", (1.0, 0.98, 0.94), 5.0); trim = _flat("ir_pl_panel_trim", (0.85, 0.85, 0.84), 0.4); pr, tr = [], []
    along_x = (hi[0] - lo[0]) >= (hi[1] - lo[1]); cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    for i in range(n):
        f_ = (i + 0.5) / n; px, py = (lo[0] + (hi[0] - lo[0]) * f_, cy) if along_x else (cx, lo[1] + (hi[1] - lo[1]) * f_)
        sx, sy = (0.6, 1.2) if along_x else (1.2, 0.6)
        pr.append(("box", px, py, zc, sx, sy, 0.01)); tr.append(("box", px, py, zc + 0.006, sx + 0.06, sy + 0.06, 0.012))
        _light(f"ir_pl_panel_{name}_{i}", (px, py, zc - 0.03), 45, sx, sy)
    _fl().mesh_object(name, [(led, pr), (trim, tr)], bevel=False)


def _lobby(stats):
    lo, hi = _room(LOBBY)
    if lo is None:
        return
    fl = _fl(); z0 = lo[2]
    import lux_shell
    tile = lux_shell._tile("ir_pl_porcelain", (0.72, 0.72, 0.7), 0.25, size=0.6, grout=0.004, mrgb=(0.5, 0.5, 0.5))
    f = bpy.data.objects.get(f"{LOBBY}.floor")
    for sl in f.material_slots:
        sl.material = tile
    door = bpy.data.objects.get("door.001")
    if door is not None:
        b0, b1 = _bb(door); mat = _flat("ir_pl_mat", (0.08, 0.08, 0.09), 0.95)
        if door.type == "MESH" and door.data.materials:                   # the leaf (largest slot) becomes glass in a steel frame
            area = {}
            for p in door.data.polygons:
                area[p.material_index] = area.get(p.material_index, 0.0) + p.area
            i = max(area, key=area.get); door.data = door.data.copy(); door.data.materials[i] = _flat("ir_pl_doorglass", (0.85, 0.9, 0.92), 0.05, transmission=0.9)
    _skirt(LOBBY)                                                         # r15 refs: plain white walls, grey skirting, an unfurnished lobby, 3 broad recessed panels
    green = _emit("ir_pl_exit", (0.05, 0.75, 0.25), 3.0); white = _flat("ir_pl_white", (0.95, 0.95, 0.93), 0.5); cx = (lo[0] + hi[0]) / 2
    if door is not None:
        b0, b1 = _bb(door); dy = (b0[1] + b1[1]) / 2
        _exit_sign("ParkingExitSign", "W", lo[0], dy, z0 + 2.35)
    _panels("ParkingLobbyPanels", lo, hi, 3)
    stats["pl_lobby"] = 1


def _lifts(stats):
    lo, hi = _room(LOBBY)
    lifts = sorted([o for o in bpy.data.objects if o.name.startswith("ElevatorDoorFactory") and o.type == "MESH" and _in(o, lo, hi)], key=lambda o: _bb(o)[0][1])
    if not lifts:
        return
    fl = _fl(); steel = _flat("ir_pl_lift_surround", (0.62, 0.63, 0.65), 0.3, 1.0); dark = _flat("ir_pl_signdark", (0.07, 0.08, 0.1), 0.5); red = _emit("ir_pl_indicator", (1.0, 0.2, 0.05), 4.0); btn = _emit("ir_pl_button", (0.9, 0.9, 1.0), 2.0)
    pr, dk, rd, bt = [], [], [], []
    for o in lifts:
        b0, b1 = _bb(o); x = b0[0] - 0.02; ya, yb, zt = b0[1], b1[1], b1[2]
        pr += [("box", x, ya - 0.06, (lo[2] + zt) / 2 + 0.05, 0.08, 0.12, zt - lo[2] + 0.1), ("box", x, yb + 0.06, (lo[2] + zt) / 2 + 0.05, 0.08, 0.12, zt - lo[2] + 0.1), ("box", x, (ya + yb) / 2, zt + 0.08, 0.08, yb - ya + 0.24, 0.16)]
        dk.append(("box", x - 0.045, (ya + yb) / 2, zt + 0.3, 0.02, 0.36, 0.14)); rd.append(("box", x - 0.056, (ya + yb) / 2, zt + 0.3, 0.004, 0.16, 0.06))
    mid = (_bb(lifts[0])[1][1] + _bb(lifts[-1])[0][1]) / 2 if len(lifts) > 1 else _bb(lifts[0])[1][1] + 0.3
    xw = hi[0] - 0.02
    pr.append(("box", xw - 0.01, mid, lo[2] + 1.15, 0.02, 0.1, 0.3)); bt += [("cyl", (xw - 0.02, mid, lo[2] + 1.22), (xw - 0.03, mid, lo[2] + 1.22), 0.018, 12), ("cyl", (xw - 0.02, mid, lo[2] + 1.08), (xw - 0.03, mid, lo[2] + 1.08), 0.018, 12)]
    ss = _flat("ir_pl_stainless", (0.72, 0.72, 0.74), 0.22, 1.0); sm = _flat("ir_pl_seam", (0.05, 0.05, 0.05), 0.5); lv, sea = [], []
    for o in lifts:                                                       # r15 refs: smooth stainless split leaves, not the ribbed Infinigen door
        b0, b1 = _bb(o); x = b0[0] - 0.012; ya, yb, zt = b0[1], b1[1], b1[2]; ym = (ya + yb) / 2
        lv += [("box", x, (ya + ym) / 2, (lo[2] + zt) / 2, 0.01, ym - ya - 0.004, zt - lo[2]), ("box", x, (ym + yb) / 2, (lo[2] + zt) / 2, 0.01, yb - ym - 0.004, zt - lo[2])]
        sea.append(("box", x - 0.001, ym, (lo[2] + zt) / 2, 0.008, 0.004, zt - lo[2]))
    fl.mesh_object("ParkingLiftFrame", [(steel, pr), (dark, dk), (red, rd), (btn, bt), (ss, lv), (sm, sea)], bevel=False)
    stats["pl_lifts"] = len(lifts)


def _stair(stats):
    lo, hi = _room(STAIR)
    if lo is None:
        return
    st = [o for o in bpy.data.objects if o.name.startswith("StairFlightFactory") and o.type == "MESH" and _in(o, lo, hi)]
    if not st:
        return
    b0, b1 = _bb(st[0]); fl = _fl(); z0 = lo[2]
    vs = [st[0].matrix_world @ v.co for v in st[0].data.vertices]
    low = [v for v in vs if v.z < z0 + 0.3]; ylow = sum(v.y for v in low) / len(low)
    sgn = -1 if ylow > (b0[1] + b1[1]) / 2 else 1                       # direction of travel up the flight
    for o in st:
        bpy.data.objects.remove(o, do_unlink=True)
    con = _flat("ir_pl_concrete", (0.58, 0.57, 0.55), 0.85); yel = _flat("ir_pl_yellow", (0.9, 0.68, 0.05), 0.5); steel = _flat("ir_pl_steel", (0.7, 0.7, 0.72), 0.3, 1.0)
    xa, xb = b0[0] + 0.02, b1[0] - 0.02; w = xb - xa; ys = ylow; rise, go = 0.165, 0.28
    n = int(min(abs(b1[1] - b0[1]) / go, (2.55 - z0) / rise)); steps, nos, rail = [], [], []
    for k in range(n):
        yc = ys + sgn * (k + 0.5) * go; zt = z0 + (k + 1) * rise
        steps.append(("box", (xa + xb) / 2, yc, (z0 + zt) / 2, w, go, zt - z0))
        nos.append(("box", (xa + xb) / 2, ys + sgn * k * go + sgn * 0.025, zt + 0.003, w - 0.04, 0.05, 0.008))
    ye = ys + sgn * n * go; zt = z0 + n * rise
    for xr in (xa + 0.05, xb - 0.05):                                  # tube handrails 0.9 m over the nosing line, posts every 3 steps
        rail.append(("cyl", (xr, ys - sgn * 0.3, z0 + 0.9), (xr, ys, z0 + 0.9), 0.02, 10))
        rail.append(("cyl", (xr, ys, z0 + 0.9), (xr, ye, zt + 0.9), 0.02, 10))
        for k in range(0, n + 1, 3):
            yk = ys + sgn * k * go; zk = z0 + k * rise
            rail.append(("cyl", (xr, yk + sgn * 0.14, zk + (rise if k < n else 0)), (xr, yk + sgn * 0.14, zk + 0.9 + (rise if k < n else 0)), 0.018, 8))
    fl.mesh_object("ParkingConcreteStair", [(con, steps), (yel, nos), (steel, rail)], bevel=False)
    _skirt(STAIR)
    blue = _flat("ir_pl_stairblue", (0.06, 0.25, 0.62), 0.4); white = _flat("ir_pl_white", (0.95, 0.95, 0.93), 0.5)
    sx_ = lo[0] + 0.012; sy_ = (lo[1] + hi[1]) / 2 + 1.2                  # blue stair-direction sign (up arrow) beside the access, green escape sign above the door
    arrow = [("box", sx_ + 0.02, sy_, z0 + 1.75, 0.01, 0.05, 0.28), ("box", sx_ + 0.02, sy_ - 0.05, z0 + 1.85, 0.01, 0.12, 0.04, 0.0), ("box", sx_ + 0.02, sy_ + 0.05, z0 + 1.85, 0.01, 0.12, 0.04, 0.0)]
    fl.mesh_object("ParkingStairSign", [(blue, [("box", sx_ + 0.01, sy_, z0 + 1.75, 0.012, 0.42, 0.5)]), (white, arrow + [("box", sx_ + 0.02, sy_ - 0.12, z0 + 1.62, 0.01, 0.08, 0.04), ("box", sx_ + 0.02, sy_ - 0.04, z0 + 1.66, 0.01, 0.08, 0.04), ("box", sx_ + 0.02, sy_ + 0.04, z0 + 1.7, 0.01, 0.08, 0.04)])], bevel=False)
    ext = [o for o in bpy.data.objects if o.name.startswith("FireExtinguisherFactory") and _in(o, lo, hi)]
    if ext:                                                               # r15 refs: a red recessed cabinet in the core, a real (Poly Haven) extinguisher in it
        b0e, b1e = _bb(ext[0]); ex = (b0e[0] + b1e[0]) / 2; wy = hi[1]
        import real_assets as ra
        if ra.abo("extinguisher", 1, ex, wy - 0.13, z0 + 0.08, math.pi, fit=(0.3, 0.2, 0.6)) is not None:
            for o_ in ext:
                bpy.data.objects.remove(o_, do_unlink=True); red = _flat("ir_pl_red", (0.7, 0.05, 0.04), 0.4); gl_ = _flat("ir_pl_cabglass", (0.85, 0.9, 0.92), 0.05, transmission=0.9)
        fl.mesh_object("ParkingStairCabinet", [(red, [("box", ex, wy - 0.02, z0 + 0.55, 0.6, 0.04, 1.0), ("box", ex - 0.3, wy - 0.12, z0 + 0.55, 0.03, 0.22, 1.0), ("box", ex + 0.3, wy - 0.12, z0 + 0.55, 0.03, 0.22, 1.0),
                                                        ("box", ex, wy - 0.12, z0 + 1.04, 0.6, 0.22, 0.03), ("box", ex, wy - 0.12, z0 + 0.06, 0.6, 0.22, 0.03)]), (gl_, [("box", ex, wy - 0.235, z0 + 0.55, 0.56, 0.006, 0.96)])], bevel=True)
    d2 = bpy.data.objects.get("door.002")
    if d2 is not None and d2.type == "MESH" and d2.data.materials:
        d2.data = d2.data.copy(); fd = _flat("ir_pl_firedoor", (0.45, 0.06, 0.05), 0.45)
        for i in range(len(d2.data.materials)):
            d2.data.materials[i] = fd
        b0d, b1d = _bb(d2); dy = (b0d[1] + b1d[1]) / 2
        fl.mesh_object("ParkingEmergencyLight", [(_flat("ir_pl_white", (0.95, 0.95, 0.93), 0.5), [("box", lo[0] + 0.05, dy, z0 + 2.38, 0.08, 0.35, 0.1)]), (_emit("ir_pl_exit", (0.05, 0.75, 0.25), 3.0), [("box", lo[0] + 0.095, dy, z0 + 2.38, 0.01, 0.3, 0.07)])], bevel=False)
    stats["pl_stair_steps"] = n


def _band(room, z0_, z1_, mat, name):
    """A horizontal paint band on the four walls (broken at doors)."""
    lo, hi = _room(room); pr = []
    for ax, line, a0, a1 in ((0, lo[1] + 0.008, lo[0], hi[0]), (0, hi[1] - 0.008, lo[0], hi[0]), (1, lo[0] + 0.008, lo[1], hi[1]), (1, hi[0] - 0.008, lo[1], hi[1])):
        for u0, u1 in _gaps(ax, line, a0 + 0.02, a1 - 0.02):
            c, w = (u0 + u1) / 2, u1 - u0
            pr.append(("box", c, line, lo[2] + (z0_ + z1_) / 2, w, 0.01, z1_ - z0_) if ax == 0 else ("box", line, c, lo[2] + (z0_ + z1_) / 2, 0.01, w, z1_ - z0_))
    _fl().mesh_object(name, [(mat, pr)], bevel=False)


def _services(name, lo, hi, z):
    """Exposed services under the slab along the room's long axis: 3 pipes (grey, red sprinkler main, white), a ladder cable tray with cables, hangers."""
    along_x = (hi[0] - lo[0]) >= (hi[1] - lo[1]); a0, a1 = ((lo[0], hi[0]) if along_x else (lo[1], hi[1])); c0 = ((lo[1] + hi[1]) / 2 if along_x else (lo[0] + hi[0]) / 2)
    grey = _flat("ir_pl_pipe_grey", (0.55, 0.56, 0.57), 0.4, 1.0); redp = _flat("ir_pl_pipe_red", (0.6, 0.06, 0.05), 0.4); whp = _flat("ir_pl_pipe_white", (0.88, 0.88, 0.86), 0.5); galv = _flat("ir_pl_tray", (0.65, 0.66, 0.68), 0.35, 1.0); cab = _flat("ir_pl_cable", (0.05, 0.05, 0.05), 0.6)
    def P(off, dz, r):
        return ("cyl", (a0 + 0.05, c0 + off, z + dz), (a1 - 0.05, c0 + off, z + dz), r, 16) if along_x else ("cyl", (c0 + off, a0 + 0.05, z + dz), (c0 + off, a1 - 0.05, z + dz), r, 16)
    def B(off, dz, sw, sh, u=None, su=None):
        uu = (a0 + a1) / 2 if u is None else u; ss = (a1 - a0 - 0.1) if su is None else su
        return ("box", uu, c0 + off, z + dz, ss, sw, sh) if along_x else ("box", c0 + off, uu, z + dz, sw, ss, sh)
    pipes = {grey: [P(-0.9, 0.0, 0.06)], redp: [P(-0.6, 0.02, 0.05)], whp: [P(0.9, 0.03, 0.04)]}
    tray = [B(0.3, -0.02, 0.4, 0.008), B(0.1, 0.01, 0.01, 0.06), B(0.5, 0.01, 0.01, 0.06)]
    cables = [P(0.2 + 0.05 * q, -0.005, 0.012) for q in range(5)]
    hang = []
    for k in range(int((a1 - a0) / 1.5)):
        u = a0 + 0.75 + k * 1.5
        hang += [B(o_, 0.12, 0.012, 0.25, u, 0.012) for o_ in (-0.9, -0.6, 0.1, 0.5, 0.9)]
    _fl().mesh_object(name, [(grey, pipes[grey]), (redp, pipes[redp]), (whp, pipes[whp]), (galv, tray + hang), (cab, cables)], bevel=False)


def _ramp(stats):
    """r15 refs: a broad charcoal horizontal wall stripe, exposed pipes + cable trays under the slab, green escape signs (no height bar / bollards: not in the reference)."""
    lo, hi = _room(RAMP)
    if lo is None:
        return
    _band(RAMP, 0.85, 1.35, _flat("ir_pl_charcoal", (0.12, 0.12, 0.13), 0.6), "ParkingRampStripe")
    _services("ParkingRampServices", lo, hi, 2.4)
    _exit_sign("ParkingRampExit0", "W", lo[0], (lo[1] + hi[1]) / 2 - 1.5, lo[2] + 2.2)
    _exit_sign("ParkingRampExit1", "N", hi[1], (lo[0] + hi[0]) / 2, lo[2] + 2.2)
    r = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("VehicleRampFactory")]
    if r:                                                                   # r20: skin + arrow from the ramp's REAL side profile (the r19 version used the bbox height 3.36 m -> a 28 deg plane; the surface is ~11 deg: skin 0.8 m too tall, arrow floating up to the ceiling)
        import bmesh
        o = r[0]; b0, b1 = _bb(o); vs = [o.matrix_world @ v.co for v in o.data.vertices]
        side = [v for v in vs if v.x < b0[0] + 0.05]; top = {}
        for v in side:
            k = round(v.y, 2); top[k] = max(top.get(k, -9), v.z)
        prof = sorted((y, z) for y, z in top.items() if z > b0[2] + 0.05 or y in (min(top), max(top)))
        prof = [(y, z) for y, z in prof if z <= 1.7] or prof                 # the crest opening above y = 1 m is not drive surface
        yA, zA = prof[-1][0], prof[-1][1]; yB, zB = prof[0][0], prof[0][1]   # foot (large y) and crest (small y)
        surf = lambda y: zA + (zB - zA) * (y - yA) / (yB - yA)
        zf = b0[2]; con = _flat("ir_pl_rampskin", (0.55, 0.55, 0.53), 0.85)
        for nm, xs in (("W", b0[0] - 0.03), ("E", b1[0] + 0.03)):
            if nm == "E" and abs(xs - hi[0]) < 0.3:
                continue                                                      # the east side stands against the building wall
            bm = bmesh.new(); pts = []
            for q in [(yB, zf)] + [(y, z) for y, z in prof] + [(yA, zf)]:
                if not pts or abs(q[0] - pts[-1][0]) + abs(q[1] - pts[-1][1]) > 1e-3:
                    pts.append(q)
            if len(pts) > 2 and abs(pts[0][0] - pts[-1][0]) + abs(pts[0][1] - pts[-1][1]) < 1e-3:
                pts.pop()
            bm.faces.new([bm.verts.new((xs, y, z)) for y, z in pts]); me = bpy.data.meshes.new("ParkingRampSkin"); bm.to_mesh(me); bm.free(); me.materials.append(con)
            sk = bpy.data.objects.new("ParkingRampSkin" + nm, me); bpy.context.scene.collection.objects.link(sk)
            sl = sk.modifiers.new("s", "SOLIDIFY"); sl.thickness = 0.05; sl.offset = 1.0 if nm == "W" else -1.0     # thickness goes outwards, the stripe on the drive edge stays visible
        fl = _fl(); wht = _flat("ir_pl_arrow", (0.95, 0.95, 0.93), 0.5)
        for m_ in o.data.materials:                                          # the blocky arrow = the white ramp faces: cut them
            if m_ is not None and m_.name == "ir_ramp_white":
                idx = [i for i, q in enumerate(o.data.materials) if q is m_][0]
                bm = bmesh.new(); bm.from_mesh(o.data); bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index == idx], context="FACES"); bm.to_mesh(o.data); bm.free()
        cx = (b0[0] + b1[0]) / 2; yt = yA - 1.1; shaft, head, w, hw = 1.2, 0.6, 0.25, 0.8        # tail 1.1 m up the slope from the foot; points uphill (-y)
        poly = [(yt, -w / 2), (yt - shaft, -w / 2), (yt - shaft, -hw / 2), (yt - shaft - head, 0.0), (yt - shaft, hw / 2), (yt - shaft, w / 2), (yt, w / 2)]
        bm = bmesh.new(); vv = [bm.verts.new((cx + v, y, surf(y) + 0.006)) for y, v in poly]; bm.faces.new(vv); me = bpy.data.meshes.new("ParkingRampArrow"); bm.to_mesh(me); bm.free(); me.materials.append(wht)
        ob = bpy.data.objects.new("ParkingRampArrow", me); bpy.context.scene.collection.objects.link(ob); stats["pl_ramp_arrow"] = {"slope": round((zB - zA) / (yB - yA), 3), "tail_y": round(yt, 2)}
    stats["pl_ramp"] = 1


def _cone(name, x, y, z):
    """A real tapered traffic cone (0.7 m, 32 segments): rounded square base, orange body, two white reflective sleeves (the catalog prop is a straight cylinder)."""
    import bmesh
    orange = _flat("ir_pl_cone", (0.95, 0.32, 0.02), 0.45); white = _flat("ir_pl_white", (0.95, 0.95, 0.93), 0.5); blk = _flat("ir_pl_black", (0.03, 0.03, 0.03), 0.5)
    bm = bmesh.new()
    def cone(r0, r1, z0, z1, mi):
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=32, radius1=r0, radius2=r1, depth=z1 - z0)
        bmesh.ops.translate(bm, vec=(0, 0, (z0 + z1) / 2), verts=res["verts"])
        for f in {f for v in res["verts"] for f in v.link_faces}:
            f.material_index = mi
    R = lambda zz: 0.13 - (0.13 - 0.025) * (zz - 0.04) / 0.66
    cone(R(0.04), R(0.30), 0.04, 0.30, 0); cone(R(0.30) + 0.002, R(0.40) + 0.002, 0.30, 0.40, 1); cone(R(0.40), R(0.48), 0.40, 0.48, 0); cone(R(0.48) + 0.002, R(0.56) + 0.002, 0.48, 0.56, 1); cone(R(0.56), 0.025, 0.56, 0.70, 0)
    res = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=(0.38, 0.38, 0.04), verts=res["verts"]); bmesh.ops.translate(bm, vec=(0, 0, 0.02), verts=res["verts"])
    for f in {f for v in res["verts"] for f in v.link_faces}:
        f.material_index = 2
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for m in (orange, white, blk):
        me.materials.append(m)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o); o.location = (x, y, z)
    md = o.modifiers.new("b", "BEVEL"); md.width = 0.006; md.segments = 2; md.limit_method = "ANGLE"
    for p_ in me.polygons:
        p_.use_smooth = True
    return o


def _hall(stats):
    """Parking hall (warehouse_0/0), r15 refs: black column ID bands with white labels (A / B rows + numbers), slim yellow/black corner guards, blue overhead direction boards,
    orange traffic cones and slim yellow-striped bollards at the lane ends."""
    lo, hi = _room("warehouse_0/0")
    if lo is None:
        return
    fl = _fl(); blk = _flat("ir_pl_black", (0.03, 0.03, 0.03), 0.5); white = _flat("ir_pl_white", (0.95, 0.95, 0.93), 0.5); yel = _flat("ir_pl_yellow", (0.9, 0.68, 0.05), 0.5)
    cols = sorted([o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("ColumnWithPlateFactory", "ColumnFactory"))], key=lambda o: (round(_bb(o)[0][1]), _bb(o)[0][0]))
    import bmesh
    for me_ in {o.data for o in cols if o.name.startswith("ColumnWithPlate")}:          # r16: the factory's wide yellow/black base wraps read as horizontal bands (REF: vertical corner guards)
        idx_ = [i for i, m_ in enumerate(me_.materials) if m_ and (m_.name in ("ir_pk_yellow", "ir_pk_black") or m_.name.startswith("ir_print_parkplate"))]   # r17: + the factory's printed head plate (low-res print at 2.23-2.51 m, read as unreadable): ours replaces it
        if idx_:
            bm_ = bmesh.new(); bm_.from_mesh(me_); bmesh.ops.delete(bm_, geom=[f for f in bm_.faces if f.material_index in idx_], context="FACES"); bm_.to_mesh(me_); bm_.free()
    boxes_ = [(lambda b_: (b_[0][0] - 0.12, b_[1][0] + 0.12, b_[0][1] - 0.12, b_[1][1] + 0.12))(_bb(o)) for o in cols]
    for pf in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("ParkingFixtures(warehouse")]:   # parking_fixtures' hazard wraps round the columns (same horizontal bands)
        idx_ = [i for i, m_ in enumerate(pf.data.materials) if m_ and m_.name in ("ir_pf_yellow", "ir_pf_black", "ir_pf_green")]   # r17: + the green column panels that covered the new ID plates
        if not idx_:
            continue
        mw_ = pf.matrix_world; bm_ = bmesh.new(); bm_.from_mesh(pf.data)
        dead_ = [f for f in bm_.faces if f.material_index in idx_ and any(q[0] < (mw_ @ f.calc_center_median()).x < q[1] and q[2] < (mw_ @ f.calc_center_median()).y < q[3] for q in boxes_)]
        bmesh.ops.delete(bm_, geom=dead_, context="FACES"); bm_.to_mesh(pf.data); bm_.free(); stats["pl_column_wraps_cut"] = len(dead_)
    rows = sorted({round(_bb(o)[0][1]) for o in cols}); band, lab, guard_y, guard_k = [], [], [], []
    for o in cols:
        b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
        vs = [o.matrix_world @ v.co for v in o.data.vertices]; mid = [v for v in vs if 1.2 < v.z < 2.2] or vs        # the shaft at band height (the bbox includes the head plate / hazard wrap)
        hw = max(max(abs(v.x - cx) for v in mid), max(abs(v.y - cy) for v in mid)) + 0.004
        r_ = "AB"[rows.index(round(b0[1])) % 2]; num = 13 + [c for c in cols if round(_bb(c)[0][1]) == round(b0[1])].index(o); txt = f"{r_}{num}"
        gh_ = 0.25; zid = 1.86                                              # r17: ID plates on the two aisle faces only, 25 cm white glyphs on a black plate (r16's 17 cm 4-face band read as an unreadable band)
        w_ = gh_ * 0.62 * len(txt) + gh_ * 0.25 * (len(txt) - 1)
        for face, line, u in (("N", cy - hw - 0.007, cx), ("S", cy + hw + 0.007, cx)):      # face codes = the side the viewer looks from (see _text)
            sd_ = -1 if face == "N" else 1; dr = 1 if face in "NW" else -1
            band.append(("box", cx, line + sd_ * 0.004, zid, max(2 * hw, w_ + 0.12), 0.012, gh_ + 0.1))
            lab += _text(txt, face, line + sd_ * 0.012, u - dr * (w_ / 2 - gh_ * 0.31), zid, gh_, None)
        for sx in (-1, 1):
            for sy in (-1, 1):                                              # r17: one continuous 1.4 m yellow corner guard per corner (8 cm angle) with black edge lines, reads vertical
                gx_, gy_ = cx + sx * (hw + 0.012), cy + sy * (hw + 0.012)
                guard_y.append(("box", gx_, gy_, 0.12 + 0.7, 0.08, 0.08, 1.4))
                guard_k += [("box", gx_, gy_, 0.12 + 0.01, 0.085, 0.085, 0.02), ("box", gx_, gy_, 0.12 + 1.39, 0.085, 0.085, 0.02)]
    fl.mesh_object("ParkingColumnIDs", [(blk, band + guard_k), (white, lab), (yel, guard_y)], bevel=False)
    blue = _flat("ir_pl_dirblue", (0.06, 0.25, 0.62), 0.4); steel = _flat("ir_pl_steel", (0.7, 0.7, 0.72), 0.3, 1.0); pr_b, pr_w, pr_s = [], [], []
    lane_y = (rows[0] + rows[1]) / 2 + 0.35 if len(rows) > 1 else (lo[1] + hi[1]) / 2
    def _board(x, y_, bw=2.4, bh=0.7, zc=2.25):                          # r19: bigger (2.4 x 0.7 m) boards every 7 m so any aisle view has one in frame; white arrow + P, readable from both ends
        pr_b.append(("box", x, y_, zc, 0.05, bw, bh)); pr_s.extend([("cyl", (x, y_ + d_, zc + bh / 2), (x, y_ + d_, 2.68), 0.012, 6) for d_ in (-bw * 0.4, bw * 0.4)])
        for side in (-1, 1):
            xx = x + side * 0.03
            pr_w.extend([("box", xx, y_ - bw * 0.16, zc, 0.01, bw * 0.38, 0.1), ("box", xx, y_ - bw * 0.16 + bw * 0.19 - 0.03, zc + 0.09, 0.01, 0.1, 0.1), ("box", xx, y_ - bw * 0.16 + bw * 0.19 - 0.03, zc - 0.09, 0.01, 0.1, 0.1)])
            pr_w.extend(_text("P", "W" if side > 0 else "E", xx, y_ + bw * 0.32 * (1 if side > 0 else -1), zc, 0.5, None))
    for i_ in range(4):
        _board(lo[0] + 4.0 + 7.0 * i_, lane_y)
    occ_ = [0] * int((hi[1] - lo[1]) * 10 + 1)                           # r17: drive lanes = y bands free of cars and columns (the batten rows sit over the parked rows)
    for o in bpy.data.objects:
        if o.type == "MESH" and (o.get("ir_car_src") or o in cols):
            b0_, b1_ = _bb(o)
            if b1_[0] < lo[0] or b0_[0] > hi[0]:
                continue
            for i_ in range(max(0, int((b0_[1] - lo[1]) * 10)), min(len(occ_), int((b1_[1] - lo[1]) * 10) + 1)):
                occ_[i_] += 1
    lanes_, st_ = [], None
    for i_, v_ in enumerate(occ_ + [1]):
        if v_ == 0 and st_ is None:
            st_ = i_
        elif v_ and st_ is not None:
            if i_ - st_ > 25:
                lanes_.append(lo[1] + (st_ + i_) / 20)
            st_ = None
    stats["pl_lanes"] = [round(v_, 2) for v_ in lanes_]
    for y_ in lanes_:
        if abs(y_ - lane_y) < 1.5:
            continue
        for i_ in range(4):
            _board(lo[0] + 7.5 + 7.0 * i_, y_, 2.0, 0.6, 2.3)
    fl.mesh_object("ParkingDirBoards", [(blue, pr_b), (white, pr_w), (steel, pr_s)], bevel=False)
    ne_ = 0
    for d_ in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("door") and _bb(o)[0][0] - 0.6 < hi[0] < _bb(o)[1][0] + 0.6]:   # r17: lit green exit sign over every hall door on the east wall
        b0d, b1d = _bb(d_); _exit_sign(f"ParkingHallExit{ne_}", "E", hi[0] - 0.01, (b0d[1] + b1d[1]) / 2, 2.35); ne_ += 1
    for x in (lo[0] + (hi[0] - lo[0]) * 0.25, lo[0] + (hi[0] - lo[0]) * 0.75):     # + hanging exit signs over the main lane (seen from the aisles)
        _exit_sign(f"ParkingHallExitHang{ne_}", "W", x, lane_y + 0.9, 2.45); ne_ += 1
    stats["pl_hall_exits"] = ne_
    n_c = 0
    for o in [o for o in bpy.data.objects if o.name.startswith("TrafficConeFactory")]:      # the catalog cones are straight cylinders: real tapered cones in their place
        b0, b1 = _bb(o); bpy.data.objects.remove(o, do_unlink=True); _cone(f"ParkingConeR{n_c}", (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2, b0[2]); n_c += 1
    for (x, y) in ((lo[0] + 1.2, lane_y - 0.6), (lo[0] + 1.2, lane_y + 0.6), (hi[0] - 1.8, lane_y - 0.6), (hi[0] - 1.8, lane_y + 0.6)):
        _cone(f"ParkingCone{n_c}", x, y, lo[2]); n_c += 1
    for k, o in enumerate(cols):                                       # r16: cones in view, beside every other column on its lane side
        if k % 2:
            continue
        b0, b1 = _bb(o); cy_ = (b0[1] + b1[1]) / 2
        _cone(f"ParkingCone{n_c}", b1[0] + 0.45, cy_ + (1.0 if cy_ < lane_y else -1.0), lo[2]); n_c += 1
    bol_y, bol_k = [], []
    for (x, y) in ((lo[0] + 0.5, lane_y - 1.4), (lo[0] + 0.5, lane_y + 1.4), (hi[0] - 0.5, lane_y - 1.4), (hi[0] - 0.5, lane_y + 1.4)):
        for i in range(5):
            (bol_y if i % 2 == 0 else bol_k).append(("cyl", (x, y, lo[2] + i * 0.2), (x, y, lo[2] + (i + 1) * 0.2), 0.045, 16))
    fl.mesh_object("ParkingBollards", [(yel, bol_y), (blk, bol_k)], bevel=True)
    stats["pl_hall"] = {"columns": len(cols), "cones": n_c}


def _aisles(stats):
    """r16: the aisle ceiling showed blue girders + a ribbed deck; REF: a bare grey slab with pipe / tray runs and surface LED battens every ~4 m."""
    lo, hi = _room("warehouse_0/0")
    if lo is None:
        return
    for mn, rgb in (("ir_wh_steel", (0.5, 0.5, 0.49)), ("ir_wh_deck", (0.56, 0.56, 0.55)), ("ir_pk_beam", (0.5, 0.5, 0.49))):
        m = bpy.data.materials.get(mn)
        if m is not None and m.node_tree:
            b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if b is not None:
                for l_ in list(b.inputs["Base Color"].links):
                    m.node_tree.links.remove(l_)
                b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Metallic"].default_value = 0.0; b.inputs["Roughness"].default_value = 0.85
    ys = [lo[1] + 2.6, lo[1] + 6.9, lo[1] + 14.0, hi[1] - 2.6]
    for i, y in enumerate(ys):
        _services(f"ParkingAisleServices{i}", (lo[0] + 0.3, y - 1.2, lo[2]), (hi[0] - 0.3, y + 1.2, lo[2]), 2.45)
    wh = _flat("ir_pl_batten", (0.92, 0.92, 0.9), 0.4); dif = _emit("ir_pl_batten_led", (1.0, 0.95, 0.85), 6.0); hous, lens = [], []; W = float(os.environ.get("ROOM_PARKING_BATTEN_W") or 30); n = 0
    for y in (lo[1] + 3.4, lo[1] + 8.3, lo[1] + 14.8, hi[1] - 3.4):
        x = lo[0] + 2.0
        while x < hi[0] - 1.0:
            hous.append(("box", x, y, 2.36, 1.5, 0.12, 0.06)); lens.append(("box", x, y, 2.325, 1.44, 0.09, 0.012))
            _light(f"ir_pl_batten_{n}", (x, y, 2.31), W, 1.4, 0.1); n += 1
            x += 4.0
    _fl().mesh_object("ParkingBattens", [(wh, hous), (dif, lens)], bevel=True)
    stats["pl_aisles"] = {"service_runs": len(ys), "battens": n}


def _cars(stats):
    """r16: a yellow compact, a green car and a microcar remained; car paint whose hue is yellow..green and saturated is pulled to a neutral grey in every car material (tail lights, blues, reds stay), the microcar goes."""
    k = d = 0
    for o in list(bpy.data.objects):
        src = str(o.get("ir_car_src") or "")
        if src == "objv:20":                                      # the smart-size microcar (3.0 m)
            bpy.data.objects.remove(o, do_unlink=True); d += 1
    done = set(); body_ = set()
    for o in bpy.data.objects:
        if o.get("ir_car_src") and o.type == "MESH" and o.data.materials:
            ar_ = {}
            for p_ in o.data.polygons:
                ar_[p_.material_index] = ar_.get(p_.material_index, 0.0) + p_.area
            m_ = o.data.materials[max(ar_, key=ar_.get)] if ar_ and max(ar_, key=ar_.get) < len(o.data.materials) else None
            if m_ is not None:
                body_.add(m_.name)
    for o in bpy.data.objects:
        if not o.get("ir_car_src") or o.type != "MESH":
            continue
        for m in o.data.materials:
            if m is None or m.name in done or not m.node_tree:
                continue
            done.add(m.name); nt = m.node_tree; N, L = nt.nodes, nt.links
            b = next((n_ for n_ in N if n_.type == "BSDF_PRINCIPLED"), None)
            if b is None:
                continue
            src_ = b.inputs["Base Color"].links[0].from_socket if b.inputs["Base Color"].links else None
            rgb = N.new("ShaderNodeRGB"); rgb.outputs[0].default_value = b.inputs["Base Color"].default_value
            sh = N.new("ShaderNodeSeparateColor"); sh.mode = "HSV"; L.new(src_ or rgb.outputs[0], sh.inputs[0])
            def mth(op, a, c=None):
                n_ = N.new("ShaderNodeMath"); n_.operation = op
                for i_, v in enumerate((a, c)):
                    if v is None:
                        continue
                    if isinstance(v, (int, float)):
                        n_.inputs[i_].default_value = v
                    else:
                        L.new(v, n_.inputs[i_])
                return n_.outputs[0]
            H, S = sh.outputs[0], sh.outputs[1]
            mask = mth("MULTIPLY", mth("MULTIPLY", mth("GREATER_THAN", H, 0.08), mth("LESS_THAN", H, 0.45)), mth("GREATER_THAN", S, 0.35))
            if m.name in body_:                                    # r17: the car's body paint (largest-area slot): every saturated hue except navy/dark blue goes neutral (small red / blue / yellow cars far back)
                mask = mth("MULTIPLY", mth("GREATER_THAN", S, 0.3), mth("SUBTRACT", 1.0, mth("MULTIPLY", mth("GREATER_THAN", H, 0.55), mth("LESS_THAN", H, 0.7))))
            cm = N.new("ShaderNodeCombineColor"); cm.mode = "HSV"; L.new(H, cm.inputs[0]); L.new(mth("ADD", mth("MULTIPLY", S, mth("SUBTRACT", 1.0, mask)), mth("MULTIPLY", mask, 0.04)), cm.inputs[1])
            L.new(mth("ADD", mth("MULTIPLY", sh.outputs[2], mth("SUBTRACT", 1.0, mask)), mth("MULTIPLY", mask, 0.45)), cm.inputs[2])
            L.new(cm.outputs[0], b.inputs["Base Color"]); k += 1
    stats["pl_cars"] = {"materials_neutralised": k, "microcars_dropped": d}


def _wear(stats):
    """r19 floor wear (REF: tyre marks along the lane, oil stains in the stalls): thin dark decals whose alpha comes from a world-space noise mask, subtle."""
    import random
    lo, hi = _room("warehouse_0/0")
    if lo is None:
        return
    rg = random.Random(28); fl = _fl()
    def mat(name, base, scale, lo_, hi_, strength):
        m = _flat(name, base, 0.35); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
        tc = N.new("ShaderNodeTexCoord"); no = N.new("ShaderNodeTexNoise"); no.inputs["Scale"].default_value = scale; no.inputs["Detail"].default_value = 6.0
        mr = N.new("ShaderNodeMapRange"); mr.inputs["From Min"].default_value = lo_; mr.inputs["From Max"].default_value = hi_; mr.inputs["To Max"].default_value = strength
        L.new(tc.outputs["Object"], no.inputs["Vector"]); L.new(no.outputs["Fac"], mr.inputs["Value"]); L.new(mr.outputs["Result"], b.inputs["Alpha"]); m.blend_method = "HASHED"
        return m
    tyre = mat("ir_pl_tyre", (0.02, 0.02, 0.02), 2.2, 0.45, 0.75, 0.55); oil = mat("ir_pl_oil", (0.015, 0.012, 0.01), 5.0, 0.35, 0.7, 0.8)
    rows = sorted({round(_bb(o)[0][1]) for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("ColumnWithPlate")})
    z = lo[2] + 0.004; tr, oi = [], []
    lanes = [lo[1] + 8.5, lo[1] + 15.5] if len(rows) < 2 else [(rows[0] + rows[1]) / 2 + 0.35, rows[0] - 2.4, rows[-1] + 2.4]
    for y in lanes:
        for dy in (-0.75, 0.75):
            tr.append(("box", (lo[0] + hi[0]) / 2, y + dy, z, hi[0] - lo[0] - 1.0, 0.22, 0.002))
    for _ in range(26):
        x, y = rg.uniform(lo[0] + 2, hi[0] - 2), rg.uniform(lo[1] + 1.5, hi[1] - 1.5); r = rg.uniform(0.15, 0.4)
        oi.append(("cyl", (x, y, z + 0.001), (x, y, z + 0.003), r, 10))
    fl.mesh_object("ParkingTyreMarks", [(tyre, tr)], bevel=False); fl.mesh_object("ParkingOilStains", [(oil, oi)], bevel=False)
    stats["pl_wear"] = {"tracks": len(tr), "stains": len(oi)}


def _warm(stats):
    """S28F r15 review: the hall and lobby are too dark and cool: every lamp / area light in the parking rooms gets 3500 K and 1.8x energy."""
    k = 0
    for o in bpy.data.objects:
        if o.type == "LIGHT" and o.data.type in ("POINT", "AREA", "SPOT"):
            o.data.color = (1.0, 0.86, 0.7); o.data.energy *= float(os.environ.get("ROOM_PARKING_LIGHT_GAIN") or 1.8); k += 1
    stats["pl_warm_lights"] = k


def apply(stats):
    sc = bpy.context.scene
    if sc.get("ir_parking_lobby") or bpy.data.objects.get(f"{LOBBY}.floor") is None:
        return 0
    skip = set((os.environ.get("ROOM_PARKING_LOBBY_SKIP") or "").split(",")); n = 0
    for key, fn in (("plug", _plug), ("clean", _clean), ("lobby", _lobby), ("lifts", _lifts), ("stair", _stair), ("ramp", _ramp), ("hall", _hall), ("aisles", _aisles), ("cars", _cars), ("wear", _wear), ("warm", _warm)):
        if key in skip:
            continue
        try:
            bpy.context.view_layer.update(); fn(stats); n += 1
        except Exception as ex:                                  # noqa: BLE001
            import traceback; traceback.print_exc()
            stats[f"pl_{key}_error"] = repr(ex)[:160]
    sc["ir_parking_lobby"] = 1
    return n
