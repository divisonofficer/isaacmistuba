"""F1 convention floor shell (floorF1_conv, convention_floor_01; kit stage, idempotent via scene["ir_convfloor_shell"]). ROOM_CONVFLOOR_SHELL=1 enables every part,
ROOM_CONVFLOOR_SKIP=<clean,floor,walls,flutes,ceiling,chandeliers,niches,chairs,stage,halls2,reception,foyer2,rooms2,r5,r6,lifts,plants,light> switches parts off, ROOM_CONVFLOOR_LIGHT scales every light the shell adds (default 0.35).
Rooms (rooms.json CONVF1 / Codex layout_spec): break-room_0/0 foyer (0-8 x 0-13), break-room_0/1 coffee_break, dining-room_0/0 hall_a, dining-room_0/1 hall_b, hallway_0/0 service_corridor,
hallway_0/1 main_corridor (8-34 x 10-13), meeting-room_0/0..2 breakout_a..c, living-room_0/0 speaker_lounge, restroom_0/0 restrooms. SUB2 review floorF1_conv_r2.md [kit] items.
clean        office troffers / drop ceilings / beams / plain pillars, whiteboards, lockers, laptops, paper, phones, takeaway cups
floor        polished cream marble tile with brown-marble inlay: a perimeter band in every public room + an elliptical ring in the foyer and both halls (world-space shader)
walls        cream stone panelling (1.2 x 0.6 m reveals) on every wall of the public rooms instead of the plaster / pallet-plank finishes
flutes       walnut + ivory fluted panels (real half-round flutes, bevelled) with brass trims between the doors, foyer / corridor / halls / lounge
ceiling      cream plaster + a warm perimeter cove in the public rooms
chandeliers  HSSD ring / crystal chandeliers: 3 in the foyer, 2 per hall, 1 in the lounge (+ a warm point light each)
niches       lit blank bronze poster niches between the main-corridor doors
chairs       navy velvet upholstery on the seats of the foyer / coffee / lounge / breakout B chairs, tan in the halls and breakouts A / C
stage        a carpeted stage with walnut fascia + steps, an HSSD podium and a blank projection screen on each hall's south wall
reception    a curved ivory fluted reception counter with a brass band and stone top in the foyer (east side)
lifts        a 3-car bronze lift bank on the foyer south wall
plants       real potted plants in the foyer / corridor / hall corners
light        warm 3000 K: existing lights warmed, area fill per public room
"""
from __future__ import annotations

import math
import os
import random

import bpy
from mathutils import Vector

import hotel5_shell as h5
import ratio3_common as rc
import real_assets as ra

FOYER, COFFEE, HALL_A, HALL_B, SERVICE, CORR, LOUNGE = "break-room_0/0", "break-room_0/1", "dining-room_0/0", "dining-room_0/1", "hallway_0/0", "hallway_0/1", "living-room_0/0"
BREAKOUTS = ("meeting-room_0/0", "meeting-room_0/1", "meeting-room_0/2")
PUBLIC = (FOYER, COFFEE, HALL_A, HALL_B, CORR, SERVICE, LOUNGE) + BREAKOUTS      # r4 #7: the service corridor gets the corridor finishes too
WARM = (1.0, 0.8, 0.6)
STATS = {}
_bb, _room, _flat, _emit, _wood = h5._bb, h5._room, h5._flat, h5._emit, h5._wood


_WIN = {}


def _win(rm, side):
    """Distance from a room's floor box to the inner face of its `side` wall ('S', 'N', 'W', 'E'). F1's long walls are ~0.107 m thick INSIDE the room box, so every
    wall-mounted piece placed at box + 12 mm (flutes, skirting, art, niches) sat buried in the wall (r5 #1/#7: 'pale cream wash, empty frames'). One ray per side from the
    room centre at 1.2 m; a side whose ray hits anything but the room's own wall falls back to 0.11 m."""
    key = (rm, side)
    if key not in _WIN:
        lo, hi = _room(rm); d = 0.11
        if lo is not None:
            v, edge = {"S": (Vector((0, -1, 0)), lo[1]), "N": (Vector((0, 1, 0)), hi[1]), "W": (Vector((-1, 0, 0)), lo[0]), "E": (Vector((1, 0, 0)), hi[0])}[side]
            dg = bpy.context.evaluated_depsgraph_get(); c = Vector(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, 1.2))
            h, loc, _n, _i, o, _m = bpy.context.scene.ray_cast(dg, c, v)
            if h and o is not None and o.name == f"{rm}.wall":
                d = abs((loc.y if v.y else loc.x) - edge)
        _WIN[key] = d + 0.003
    return _WIN[key]


_OPEN = {}


def _open_gaps(rm, ax, line, side, a0, a1):
    """Intervals of a wall run where there is NO wall (wide openings to the neighbouring room, windows, arches): a ray from 0.35 m inside the room at 1.5 m must hit the wall (or one of
    this shell's own wall pieces) within 0.6 m. r6 #2: the foyer's north wall flutes / wainscot stood IN the opening to the coffee break (the 'brown slab')."""
    key = (rm, ax, round(line, 2))
    if key not in _OPEN:
        dg = bpy.context.evaluated_depsgraph_get(); sc = bpy.context.scene
        d = Vector((0, -side, 0)) if ax == 0 else Vector((-side, 0, 0))
        gaps, cur = [], None; u = a0 + 0.1
        while u <= a1 - 0.1:
            o_ = Vector((u, line + side * 0.35, 1.5)) if ax == 0 else Vector((line + side * 0.35, u, 1.5))
            h, loc, _n, _i, ob, _m = sc.ray_cast(dg, o_, d, distance=0.8)
            solid = bool(h and ob is not None and (ob.name.endswith(".wall") or ob.name.startswith(("Cf", "H5", "Baseboard"))) and (loc - o_).length < 0.6)
            if not solid and cur is None:
                cur = u
            elif solid and cur is not None:
                gaps.append((cur - 0.15, u + 0.15)); cur = None
            u += 0.2
        if cur is not None:
            gaps.append((cur - 0.15, a1 + 0.1))
        _OPEN[key] = gaps
    return _OPEN[key]


def _gain():
    return float(os.environ.get("ROOM_CONVFLOOR_LIGHT") or 0.35)


def _light(name, kind, loc, energy, rgb=WARM, **kw):
    ld = bpy.data.lights.new(name, kind); ld.energy = energy * _gain(); ld.color = rgb
    if kind == "AREA":
        ld.shape = "RECTANGLE"; ld.size = kw.get("sx", 1.0); ld.size_y = kw.get("sy", 1.0)
    else:
        ld.shadow_soft_size = kw.get("r", 0.15)
    o = bpy.data.objects.new(name, ld); o.location = loc; bpy.context.scene.collection.objects.link(o)
    return o


def _zc(room):
    c = bpy.data.objects.get(f"{room}.ceiling")
    return _bb(c)[0][2] if c is not None else 3.7


def _mesh(name, groups, soft=True):
    groups = [(m, p) for m, p in groups if p]
    if not groups:
        return None
    h5._fl().mesh_object(name, groups, bevel=False)
    o = bpy.data.objects.get(name)
    if soft:
        h5._soft(o, 0.004)
    return o


# ---- clean ---------------------------------------------------------------------------------------------------------------------------
def _clean(stats):
    k = 0
    for rm in PUBLIC:
        lo, hi = _room(rm)
        if lo is None:
            continue
        k += h5._rm_in(lo, hi, ("CeilingLightFactory", "DropCeilingFactory", "CeilingBeamFactory", "CeilingGridFactory", "SoffitFactory", "TrackRailFactory", "TrackSpotFactory",
                                "AboCeilingFixtureFactory", "LinearLedFactory", "DiffuserFactory", "PillarFactory", "PilasterFactory", "ColumnFactory", "WhiteboardFactory",
                                "LockerFactory", "OpenLaptopFactory", "PaperStackFactory", "NotebookFactory", "PhoneFactory", "SpeakerphoneFactory", "BookStackFactory",
                                "TakeawayCupFactory", "DrinkCansFactory", "TaskChairFactory", "ClinicWallItemFactory"))
    for rm in (SERVICE, CORR):                                         # r3: an office motivational poster at the service end
        lo, hi = _room(rm)
        if lo is not None:
            k += h5._rm_in(lo, hi, ("WallArtFactory", "ClinicWallItemFactory"))
    for o in list(bpy.data.objects):                                  # the lights of the removed troffers / track spots (non-ir_ lights over the public rooms)
        if o.type == "LIGHT" and o.name.startswith(("CeilingLightFactory", "TrackSpotFactory", "AboCeilingFixtureFactory")):
            bpy.data.objects.remove(o, do_unlink=True); k += 1
    stats["cf_clean_removed"] = k


# ---- floor ---------------------------------------------------------------------------------------------------------------------------
def _inlay_floor(room, lo, hi, ring):
    """Cream marble tile (hotel5 _veined) + brown marble inlay: a 14 cm band 0.45 m inside the walls, and (ring=True) an elliptical 18 cm ring centred in the room."""
    base = h5._veined(f"ir_cf_marble_{room.replace('/', '_')}", (0.86, 0.8, 0.7), (0.62, 0.52, 0.42), 0.8, 0.0015, 0.12, vein_scale=3.0)
    m = base
    nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    if m.get("cf_inlay"):
        return m
    src = b.inputs["Base Color"].links[0].from_socket
    tc = N.new("ShaderNodeTexCoord"); geo = N.new("ShaderNodeNewGeometry"); sp = N.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Position"], sp.inputs["Vector"])     # world space: the floor's origin sits at the room centre

    def mth(op, a, c=None, clamp=False):
        n = N.new("ShaderNodeMath"); n.operation = op; n.use_clamp = clamp
        for i, s_ in enumerate((a, c)):
            if s_ is None:
                continue
            if isinstance(s_, (int, float)):
                n.inputs[i].default_value = s_
            else:
                L.new(s_, n.inputs[i])
        return n.outputs[0]
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2; hx, hy = (hi[0] - lo[0]) / 2, (hi[1] - lo[1]) / 2
    dx = mth("ABSOLUTE", mth("SUBTRACT", sp.outputs["X"], cx)); dy = mth("ABSOLUTE", mth("SUBTRACT", sp.outputs["Y"], cy))
    edge = mth("MINIMUM", mth("SUBTRACT", hx, dx), mth("SUBTRACT", hy, dy))          # distance to the nearest wall
    band = mth("LESS_THAN", mth("ABSOLUTE", mth("SUBTRACT", edge, 0.55)), 0.1)
    mask = band
    if ring:
        a, c = hx * 0.62, hy * 0.62
        r = mth("SQRT", mth("ADD", mth("POWER", mth("DIVIDE", dx, a), 2.0), mth("POWER", mth("DIVIDE", dy, c), 2.0)))
        ringm = mth("LESS_THAN", mth("ABSOLUTE", mth("SUBTRACT", r, 1.0)), 0.09 / min(a, c))
        inner = mth("LESS_THAN", mth("ABSOLUTE", mth("SUBTRACT", r, 0.86)), 0.025 / min(a, c))       # a thin second line inside the ring: the curved inlay pair of the ref
        mask = mth("MAXIMUM", mth("MAXIMUM", band, ringm), inner)
    no = N.new("ShaderNodeTexNoise"); no.inputs["Scale"].default_value = 5.0; no.inputs["Detail"].default_value = 8.0; L.new(tc.outputs["Object"], no.inputs["Vector"])
    br = N.new("ShaderNodeMix"); br.data_type = "RGBA"; br.inputs["A"].default_value = (0.1, 0.045, 0.02, 1); br.inputs["B"].default_value = (0.16, 0.08, 0.035, 1); L.new(no.outputs["Fac"], br.inputs["Factor"])      # r4 #3: deeper brown inlay (the noise link sat inside this comment until 10-25)
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; L.new(mask, mx.inputs["Factor"]); L.new(src, mx.inputs["A"]); L.new(br.outputs["Result"], mx.inputs["B"])
    L.new(mx.outputs["Result"], b.inputs["Base Color"]); m["cf_inlay"] = 1
    return m


def _floor(stats):
    n = 0
    for rm in (FOYER, COFFEE, HALL_A, HALL_B, CORR, SERVICE, LOUNGE):
        lo, hi = _room(rm)
        if lo is None:
            continue
        f = bpy.data.objects.get(f"{rm}.floor")
        f.data = f.data.copy()                                          # one material per room (its own inlay centre)
        m = _inlay_floor(rm, lo, hi, ring=rm in (FOYER, HALL_A, HALL_B))
        for sl in f.material_slots:
            sl.material = m
        n += 1
    rug = 0
    for rm in BREAKOUTS:                                               # breakouts: carpet stays only under the tables (the review): a pale wool tone, not dark grey
        lo, hi = _room(rm)
        if lo is not None:
            h5._set_floor(rm, h5._noise_mix("ir_cf_wool", (0.7, 0.64, 0.56), (0.62, 0.56, 0.48), 30.0, rough=0.9)); rug += 1
    stats["cf_floor"] = {"marble": n, "wool": rug}


# ---- walls ---------------------------------------------------------------------------------------------------------------------------
def _stone_panel():
    import lux_shell
    m = lux_shell._tile("ir_cf_stone_panel", (0.7, 0.62, 0.5), 0.45, size=0.6, grout=0.005, mrgb=(0.5, 0.45, 0.38))
    if not m.get("cf_rect"):                                         # 1.2 x 0.6 m panels: stretch the square brick cells 2:1
        br = next(n for n in m.node_tree.nodes if n.type == "TEX_BRICK"); br.inputs["Brick Width"].default_value = 2.0; br.offset = 0.5; m["cf_rect"] = 1
    return m


def _walls(stats):
    m = _stone_panel(); n = 0
    for rm in PUBLIC:
        w = bpy.data.objects.get(f"{rm}.wall")
        if w is None:
            continue
        for sl in w.material_slots:
            sl.material = m
        n += 1
    stats["cf_walls"] = n


# ---- fluted panels -------------------------------------------------------------------------------------------------------------------
def _flute_panel(pr, mats, axis, line, side, u0, u1, z0=0.12, z1=3.0, pitch=0.045, dark=True):
    """A walnut-backed panel of ivory half-round flutes between brass edge strips: axis 0 = wall along x at y=line, side = direction into the room."""
    def P(a, d, z, sa, sd, sz):
        return ("box", a, line + side * d, z, sa, sd, sz) if axis == 0 else ("box", line + side * d, a, z, sd, sa, sz)
    pr[mats["walnut"]].append(P((u0 + u1) / 2, 0.015, (z0 + z1) / 2, u1 - u0, 0.03, z1 - z0))
    k = int((u1 - u0 - 0.12) / pitch)
    for i in range(k):
        a = u0 + 0.06 + (i + 0.5) * (u1 - u0 - 0.12) / k
        p0, p1 = ((a, line + side * 0.03, z0 + 0.06), (a, line + side * 0.03, z1 - 0.06)) if axis == 0 else ((line + side * 0.03, a, z0 + 0.06), (line + side * 0.03, a, z1 - 0.06))
        pr[mats["walnut" if dark else "ivory"]].append(("cyl", p0, p1, pitch * 0.45, 10))
    for a in (u0 + 0.015, u1 - 0.015):
        pr[mats["brass"]].append(P(a, 0.035, (z0 + z1) / 2, 0.04, 0.045, z1 - z0))
    pr[mats["brass"]] += [P((u0 + u1) / 2, 0.035, z, u1 - u0, 0.04, 0.025) for z in (z0 + 0.012, z1 - 0.012)]


def _flute_mats():
    return {"walnut": _wood("ir_cf_walnut_dk", (0.16, 0.08, 0.04)), "ivory": _flat("ir_cf_ivory", (0.9, 0.86, 0.78), 0.35), "brass": _flat("ir_cf_brass", (0.85, 0.64, 0.3), 0.22, 1.0)}      # r4 #3: darker walnut, brighter brass (pale cream wash)


def _flutes(stats):
    """r6 #1: full-height fluted walnut + brass bays with cream stone piers between them (REF 01-09), starting above the wainscot where there is one; openings to neighbouring rooms are skipped."""
    mats = _flute_mats(); pier = _flat("ir_cf_pier", (0.88, 0.82, 0.7), 0.4); pr = {m: [] for m in mats.values()}; pr[pier] = []; n = npier = 0
    for rm, every, z0 in ((FOYER, 2.8, 1.2), (HALL_A, 2.8, 1.2), (HALL_B, 2.8, 1.2), (COFFEE, 2.6, 1.2), (BREAKOUTS[0], 2.4, 0.12), (BREAKOUTS[1], 2.4, 0.12), (BREAKOUTS[2], 2.4, 0.12), (LOUNGE, 9.0, 0.12)):
        lo, hi = _room(rm)
        if lo is None:
            continue
        zc = _zc(rm); zt = min(zc - 0.35, 3.1)
        walls = (("S", 0, lo[1] + _win(rm, 'S'), 1, lo[0], hi[0]), ("N", 0, hi[1] - _win(rm, 'N'), -1, lo[0], hi[0]), ("W", 1, lo[0] + _win(rm, 'W'), 1, lo[1], hi[1]), ("E", 1, hi[0] - _win(rm, 'E'), -1, lo[1], hi[1]))
        for nm, ax, line, side, a0, a1 in walls:
            if rm == FOYER and nm == "W":                                    # the entrance glazing side
                continue
            if rm in (HALL_A, HALL_B) and nm == "S":                         # the stage wall
                continue
            gaps = sorted(h5._door_gaps(ax, line, a0, a1, pad=0.25) + _open_gaps(rm, ax, line, side, a0, a1))
            for s0, s1 in h5._segments(a0 + 0.3, a1 - 0.3, gaps, minw=1.6 if rm != LOUNGE else 1.3):
                m_ = max(1, int(round((s1 - s0) / every))); bay = (s1 - s0) / m_
                for i in range(m_):
                    u = s0 + (i + 0.5) * bay
                    wd = bay - 0.02 if rm != LOUNGE else 1.6                    # r8: bays abut (one brass reveal where they meet), no slab gaps
                    if wd < 0.8:
                        continue
                    _flute_panel(pr, mats, ax, line, side, u - wd / 2, u + wd / 2, z0, zt, dark=True); n += 1
                if rm != LOUNGE:                                             # cream stone piers at the bay edges
                    for i in range(m_ + 1):
                        if i not in (0, m_) and i % 2:                         # r8: piers at corners / door jambs (segment ends) and every second bay edge, not between every bay
                            continue
                        u = s0 + i * bay
                        pr[pier].append(("box", u, line + side * 0.07, (z0 + zt) / 2, 0.45, 0.14, zt - z0) if ax == 0 else ("box", line + side * 0.07, u, (z0 + zt) / 2, 0.14, 0.45, zt - z0)); npier += 1   # r9: 45 x 14 cm pilasters so they read
    _mesh("CfFlutedPanels", list(pr.items()))
    stats["cf_flute_panels"] = n; stats["cf_piers"] = npier


# ---- ceiling + cove --------------------------------------------------------------------------------------------------------------------
def _ceiling(stats):
    plaster = _flat("ir_cf_ceiling", (0.93, 0.9, 0.84), 0.6); cove = _emit("ir_cf_cove", (1.0, 0.8, 0.55), 2.5); pr = []
    for rm in PUBLIC:
        lo, hi = _room(rm)
        if lo is None:
            continue
        h5._set_ceiling(rm, plaster); z = _zc(rm) - 0.22; i = 0.32
        pr += [("box", (lo[0] + hi[0]) / 2, lo[1] + i, z, hi[0] - lo[0] - 2 * i, 0.05, 0.02), ("box", (lo[0] + hi[0]) / 2, hi[1] - i, z, hi[0] - lo[0] - 2 * i, 0.05, 0.02),
               ("box", lo[0] + i, (lo[1] + hi[1]) / 2, z, 0.05, hi[1] - lo[1] - 2 * i, 0.02), ("box", hi[0] - i, (lo[1] + hi[1]) / 2, z, 0.05, hi[1] - lo[1] - 2 * i, 0.02)]
    sof = _flat("ir_cf_soffit", (0.93, 0.9, 0.84), 0.6); sp = []                       # the cove's dropped soffit lip hiding the strip
    for p in pr:
        _, x, y, z, sx, sy, sz = p
        sp.append(("box", x, y, z - 0.04, sx + 0.12 if sx > sy else 0.12, sy + 0.12 if sy > sx else 0.12, 0.03))
    _mesh("CfCoves", [(cove, pr), (sof, sp)], soft=False)
    stats["cf_coves"] = len(pr)


# ---- chandeliers ---------------------------------------------------------------------------------------------------------------------
def _hang(rx, seed, x, y, zc, fit, stats):
    o = ra.hssd(rx, seed, x, y, 0.0, 0.0, fit=fit, cats=None, size=(0.4, 1.6), grow=True)
    if o is None:
        return None
    o.location.z += (zc - 0.02) - ra.top(o)
    return o


def _chandeliers(stats):
    n = 0; miss = 0
    plan = []
    for rm, count, rx, fit in ((FOYER, 3, r"ring led chandelier", (1.2, 1.2, 0.5)), (HALL_A, 2, r"crystal chandelier|karrington", (1.3, 1.3, 1.0)),
                               (HALL_B, 2, r"crystal chandelier|karrington", (1.3, 1.3, 1.0)), (LOUNGE, 1, r"ring led chandelier", (0.9, 0.9, 0.4))):
        lo, hi = _room(rm)
        if lo is None:
            continue
        zc = _zc(rm)
        if rm == FOYER:
            pts = [((lo[0] + hi[0]) / 2, lo[1] + (hi[1] - lo[1]) * f) for f in (0.25, 0.5, 0.75)]
        elif rm == LOUNGE:
            pts = [((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)]
        else:
            pts = [(lo[0] + (hi[0] - lo[0]) * f, (lo[1] + hi[1]) / 2 + 0.6) for f in (0.3, 0.7)]
        for i, (x, y) in enumerate(pts[:count]):
            o = _hang(rx, 11 + i, x, y, zc, fit, stats)
            if o is None:
                miss += 1; continue
            bz = o.location.z + o.scale.z * min(c[2] for c in o.bound_box)
            _light(f"ir_cf_chand_{rm}_{i}", "POINT", (x, y, max(bz - 0.05, 1.9)), 160.0, r=0.35); n += 1
    stats["cf_chandeliers"] = {"placed": n, "missed": miss}


# ---- poster niches --------------------------------------------------------------------------------------------------------------------
def _niches(stats):
    lo, hi = _room(CORR)
    if lo is None:
        return
    bronze = _flat("ir_cf_bronze", (0.36, 0.24, 0.14), 0.3, 1.0); back = _flat("ir_cf_niche_back", (0.12, 0.08, 0.05), 0.6)
    poster = _emit("ir_cf_poster", (0.95, 0.88, 0.74), 1.4); pr = {bronze: [], back: [], poster: []}; n = 0
    for line, side in ((lo[1] + _win(CORR, 'S'), 1), (hi[1] - _win(CORR, 'N'), -1)):
        for s0, s1 in h5._segments(lo[0] + 0.4, hi[0] - 0.4, h5._door_gaps(0, line, lo[0], hi[0], pad=0.3), minw=1.6):
            u = (s0 + s1) / 2; W, H, zc = 0.8, 1.2, 1.55
            P = lambda a, d, z, sa, sd, sz: ("box", a, line + side * d, z, sa, sd, sz)
            pr[back].append(P(u, 0.04, zc, W + 0.12, 0.08, H + 0.12))
            pr[poster].append(P(u, 0.085, zc, W, 0.006, H))
            pr[bronze] += [P(u - W / 2 - 0.035, 0.09, zc, 0.05, 0.06, H + 0.12), P(u + W / 2 + 0.035, 0.09, zc, 0.05, 0.06, H + 0.12),
                           P(u, 0.09, zc - H / 2 - 0.035, W + 0.12, 0.06, 0.05), P(u, 0.09, zc + H / 2 + 0.035, W + 0.12, 0.06, 0.05)]
            n += 1
    _mesh("CfPosterNiches", list(pr.items()))
    stats["cf_poster_niches"] = n


# ---- chairs ---------------------------------------------------------------------------------------------------------------------------
def _velvet(name, rgb):
    m = bpy.data.materials.get(name)
    if m is None:
        m = _flat(name, rgb, 0.75); b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Sheen Weight"].default_value = 0.8; b.inputs["Sheen Tint"].default_value = (min(1, rgb[0] * 2.2), min(1, rgb[1] * 2.2), min(1, rgb[2] * 2.2), 1); b.inputs["Sheen Roughness"].default_value = 0.35
    return m


def _chairs(stats):
    navy = _velvet("ir_cf_navy_velvet", (0.05, 0.08, 0.2)); tan = _velvet("ir_cf_tan_velvet", (0.55, 0.4, 0.26)); n = {"navy": 0, "tan": 0}
    which = {FOYER: navy, COFFEE: navy, LOUNGE: navy, BREAKOUTS[1]: navy, HALL_A: tan, HALL_B: tan, BREAKOUTS[0]: tan, BREAKOUTS[2]: tan}
    for rm, mat in which.items():
        lo, hi = _room(rm)
        if lo is None:
            continue
        for o in list(bpy.data.objects):
            if o.type != "MESH" or not o.data.materials or not ("Chair" in o.name or "Armchair" in o.name or "Stool" in o.name or "Sofa" in o.name):
                continue
            if not h5._in_room(o, lo, hi):
                continue
            area = {}
            for p in o.data.polygons:
                area[p.material_index] = area.get(p.material_index, 0.0) + p.area
            i = max(area, key=area.get)
            if i < len(o.data.materials):
                o.data = o.data.copy(); o.data.materials[i] = mat; n["navy" if mat is navy else "tan"] += 1
    stats["cf_chairs"] = n


# ---- stage ----------------------------------------------------------------------------------------------------------------------------
def _stage(stats):
    carpet = h5._noise_mix("ir_cf_stage_carpet_dk", (0.05, 0.05, 0.06), (0.08, 0.07, 0.08), 40.0, rough=0.95); walnut = _wood("ir_cf_walnut_dk", (0.16, 0.08, 0.04))      # r4 #2: dark stage, not mauve
    brass = _flat("ir_cf_brass", (0.78, 0.6, 0.3), 0.28, 1.0); frame = _flat("ir_cf_screen_frame", (0.03, 0.03, 0.03), 0.4); screen = _screen_mat()
    n = 0; pod = 0
    for rm in (HALL_A, HALL_B):
        lo, hi = _room(rm)
        if lo is None:
            continue
        zc = _zc(rm); cx = (lo[0] + hi[0]) / 2; y0 = lo[1] + 0.02; W, D, H = 6.0, 2.4, 0.45
        for o in list(bpy.data.objects):                                 # nothing may stand on the stage footprint
            if o.type == "MESH" and h5._in_room(o, (cx - W / 2, y0, 0), (cx + W / 2, y0 + D, 0)) and not o.name.startswith((rm, "Cf", "ir_", "Baseboard")) and _bb(o)[0][2] < 0.6:
                bpy.data.objects.remove(o, do_unlink=True)
        pr = {carpet: [("box", cx, y0 + D / 2, 0.11 + H / 2, W, D, H)], walnut: [("box", cx, y0 + D + 0.015, 0.11 + H / 2, W + 0.03, 0.03, H)], brass: [("box", cx, y0 + D + 0.032, 0.11 + H - 0.02, W, 0.01, 0.025)]}
        for k in range(2):                                              # two steps at the stage front-left
            pr[walnut].append(("box", cx - W / 2 + 0.7, y0 + D + 0.17 + k * 0.28, 0.11 + (H - (k + 1) * 0.15) / 2 + 0.0, 1.0, 0.28, H - (k + 1) * 0.15))
        sw, sh = 4.0, 2.25; zs = 0.11 + H + 0.35 + sh / 2
        zs = min(zs, zc - 0.25 - sh / 2)
        pr[frame] = [("box", cx, lo[1] + 0.03, zs, sw + 0.12, 0.04, sh + 0.12)]; pr[screen] = [("box", cx, lo[1] + 0.052, zs, sw, 0.006, sh)]
        _mesh(f"CfStage({rm})", list(pr.items()))
        o = ra.hssd(r"^podium$|podium", 3, cx + W / 2 - 1.0, y0 + D - 0.6, 0.11 + H, math.pi, fit=(0.7, 0.7, 1.25), size=(0.4, 1.6), grow=True)
        pod += o is not None
        _light(f"ir_cf_stage_{rm}", "AREA", (cx, y0 + D + 1.5, zc - 0.3), 220.0, sx=4.0, sy=1.2)
        steel = _flat("ir_cf_truss", (0.05, 0.05, 0.055), 0.35, 1.0); ty_ = y0 + D + 0.6; zt_ = zc - 0.45; cans = []          # a black lighting bar over the stage front with 6 spot cans
        bar = [("cyl", (cx - W / 2, ty_, zt_), (cx + W / 2, ty_, zt_), 0.03, 12), ("cyl", (cx - W / 2 + 0.3, ty_, zt_), (cx - W / 2 + 0.3, ty_, zc), 0.012, 8), ("cyl", (cx + W / 2 - 0.3, ty_, zt_), (cx + W / 2 - 0.3, ty_, zc), 0.012, 8)]
        for k in range(6):
            sx_ = cx - W / 2 + 0.6 + k * (W - 1.2) / 5
            cans.append(("cyl", (sx_, ty_ + 0.02, zt_ - 0.08), (sx_, ty_ - 0.12, zt_ - 0.3), 0.07, 16))
            sp = bpy.data.lights.new(f"ir_cf_stagespot_{rm}_{k}", "SPOT"); sp.energy = 120.0 * _gain(); sp.spot_size = 0.6; sp.spot_blend = 0.4; sp.color = WARM
            so = bpy.data.objects.new(sp.name, sp); so.location = (sx_, ty_ - 0.15, zt_ - 0.32); so.rotation_euler = (math.radians(-35), 0, 0); bpy.context.scene.collection.objects.link(so)
        _mesh(f"CfStageTruss({rm})", [(steel, bar + cans)])
        n += 1
    stats["cf_stage"] = {"stages": n, "podiums": pod}


def _screen_mat():
    """A projected slide on the stage screen: screen_content atlas (generic, no brands), softly emissive."""
    m = bpy.data.materials.get("ir_cf_screen_img")
    if m is None:
        m = _emit("ir_cf_screen_img", (1, 1, 1), 1.2); nt = m.node_tree; b = nt.nodes["Principled BSDF"]
        im = nt.nodes.new("ShaderNodeTexImage"); im.image = bpy.data.images.load("/jarvis/project/robomituba/data/venue_refs/screen_content/screen_01.png", check_existing=True)
        nt.links.new(im.outputs["Color"], b.inputs["Base Color"]); nt.links.new(im.outputs["Color"], b.inputs["Emission Color"])
    return m


# ---- reception ------------------------------------------------------------------------------------------------------------------------
def _reception(stats):
    lo, hi = _room(FOYER)
    if lo is None:
        return
    for o in list(bpy.data.objects):                                     # r3's own counter / reception desk in the foyer gives way to the curved one
        if o.type == "MESH" and o.name.startswith(("CafeCounterFactory", "ReceptionDeskFactory", "CounterFactory", "WhiteIslandFactory")) and h5._in_room(o, lo, hi):
            bpy.data.objects.remove(o, do_unlink=True)
    ivory = _flat("ir_cf_ivory", (0.9, 0.86, 0.78), 0.35); brass = _flat("ir_cf_brass", (0.78, 0.6, 0.3), 0.28, 1.0)
    stone = h5._veined("ir_cf_counter_stone", (0.9, 0.86, 0.8), (0.55, 0.48, 0.4), 0.6, 0.0005, 0.15, vein_scale=5.0)
    cx, cy, R = hi[0] - 0.6, (lo[1] + hi[1]) / 2 + 1.0, 1.9                 # arc bulging west into the foyer (layout_spec: counter near the east wall, x 6, y 6-9)
    fl = []; base = []; top = []; band = []
    for i in range(48):                                                  # 48 flutes on a 100 deg arc
        a = math.radians(130 + 100 * (i + 0.5) / 48); x, y = cx + R * math.cos(a), cy + R * math.sin(a)
        fl.append(("cyl", (x, y, 0.16), (x, y, 1.02), 0.03, 10))
    for i in range(24):
        a0, a1 = math.radians(130 + 100 * i / 24), math.radians(130 + 100 * (i + 1) / 24); am = (a0 + a1) / 2
        L = 2 * (R + 0.05) * math.sin((a1 - a0) / 2) + 0.01; yaw = am + math.pi / 2
        base.append(("box", cx + (R + 0.05) * math.cos(am), cy + (R + 0.05) * math.sin(am), 0.13, L, 0.14, 0.05, yaw))
        top.append(("box", cx + (R + 0.12) * math.cos(am), cy + (R + 0.12) * math.sin(am), 1.08, L + 0.02, 0.42, 0.04, yaw))
        band.append(("box", cx + (R - 0.05) * math.cos(am), cy + (R - 0.05) * math.sin(am), 1.04, L, 0.03, 0.03, yaw))
        base.append(("box", cx + (R + 0.3) * math.cos(am), cy + (R + 0.3) * math.sin(am), 0.6, L, 0.04, 0.95, yaw))     # the staff-side back skin
    _mesh("CfReceptionCounter", [(ivory, fl + base), (stone, top), (brass, band)])
    for i, dy in enumerate((-0.6, 0.7)):                                 # two brass desk lamps
        ra.abo("tablelamp", 70 + i, cx - R * 0.98, cy + dy, 1.1, 0.0, fit=(0.35, 0.35, 0.5))
    ra.abo("bouquet", 77, cx - R * 0.98, cy, 1.1, 0.0, fit=(0.5, 0.5, 0.6))               # r6 #7: flowers on the desk
    stats["cf_reception"] = 1


# ---- lifts ----------------------------------------------------------------------------------------------------------------------------
def _lifts(stats):
    lo, hi = _room(FOYER)
    if lo is None:
        return
    br = _flat("ir_cf_bronze", (0.36, 0.24, 0.14), 0.3, 1.0); st = _flat("ir_cf_lift_leaf", (0.24, 0.16, 0.1), 0.38, 1.0); dk = _flat("ir_cf_black", (0.02, 0.02, 0.02), 0.4)
    btn = _emit("ir_cf_btn", (1.0, 0.85, 0.6), 4.0); ind = _emit("ir_cf_ind", (1.0, 0.45, 0.2), 3.0); pr = {m: [] for m in (br, st, dk, btn, ind)}
    ys = lo[1] + 0.03; xs = [lo[0] + (hi[0] - lo[0]) * f for f in (0.28, 0.52, 0.76)]
    for x in xs:
        W, H = 1.1, 2.4
        pr[st] += [("box", x - W / 4 - 0.002, ys + 0.03, 0.1 + H / 2, W / 2 - 0.004, 0.02, H), ("box", x + W / 4 + 0.002, ys + 0.03, 0.1 + H / 2, W / 2 - 0.004, 0.02, H)]
        pr[dk].append(("box", x, ys + 0.035, 0.1 + H / 2, 0.006, 0.02, H))
        for sx in (-1, 1):
            pr[br] += [("box", x + sx * (W / 2 + 0.05), ys + 0.12, 0.1 + (H + 0.1) / 2, 0.1, 0.03, H + 0.1), ("box", x + sx * (W / 2 + 0.005), ys + 0.07, 0.1 + H / 2, 0.01, 0.1, H)]
        pr[br] += [("box", x, ys + 0.12, 0.1 + H + 0.075, W + 0.2, 0.03, 0.15), ("box", x, ys + 0.07, 0.1 + H + 0.005, W, 0.1, 0.01)]
        pr[st].append(("box", x, ys + 0.12, 0.112, W + 0.1, 0.16, 0.02))
        pr[dk].append(("box", x, ys + 0.14, 0.1 + H + 0.3, 0.4, 0.02, 0.12)); pr[ind].append(("box", x, ys + 0.151, 0.1 + H + 0.3, 0.16, 0.004, 0.05))
        px = x + W / 2 + 0.28
        pr[br].append(("box", px, ys + 0.13, 1.15, 0.1, 0.02, 0.3))
        pr[btn] += [("cyl", (px, ys + 0.14, z), (px, ys + 0.15, z), 0.018, 12) for z in (1.08, 1.22)]
    for o in list(bpy.data.objects):                                     # nothing stands in front of the lift doors
        if o.type == "MESH" and h5._in_room(o, (lo[0] + 0.5, lo[1], 0), (hi[0] - 0.5, lo[1] + 1.4, 0)) and not o.name.startswith((FOYER, "Cf", "Baseboard", "door", "Door")) and _bb(o)[0][2] < 0.5:
            bpy.data.objects.remove(o, do_unlink=True)
    _mesh("CfLiftBank", list(pr.items()))
    stats["cf_lifts"] = len(xs)


# ---- r4: halls / foyer / rooms (SUB2 floorF1_conv_r3.md items 2-8) -------------------------------------------------------------------------
def _recolour(o, mat):
    """The largest-area slot of a real asset (its upholstery / body) takes `mat`."""
    if o is None or o.type != "MESH" or not o.data.materials:
        return
    area = {}
    for p in o.data.polygons:
        area[p.material_index] = area.get(p.material_index, 0.0) + p.area
    i = max(area, key=area.get)
    if i < len(o.data.materials):
        o.data = o.data.copy(); o.data.materials[i] = mat


def _retop(o, mat):
    """The material slot of the highest polygons (a table's top) takes `mat`: r6 #3 the pub tables' black glossy tops read as black discs."""
    if o is None or o.type != "MESH" or not o.data.materials:
        return
    top = max(o.data.polygons, key=lambda p: p.center.z)
    i = top.material_index
    if i < len(o.data.materials):
        o.data = o.data.copy(); o.data.materials[i] = mat


def _halls2(stats):
    """4 round banquet tables per hall (2x2, clear of the stage): pleated floor-length white cloth, library place settings + a centrepiece, 8 real dining chairs in white slip covers
    with a navy bow, replacing realize's long rectangular tables, their chairs, candles and vases."""
    import bmesh
    cloth = _flat("ir_cf_cloth", (0.95, 0.95, 0.93), 0.85); cover = _velvet("ir_cf_cover_satin", (0.92, 0.91, 0.88)); sash = _velvet("ir_cf_navy_velvet", (0.05, 0.08, 0.2))
    plate = _flat("ir_cf_plate", (0.96, 0.96, 0.94), 0.2); n = {"tables": 0, "chairs": 0, "covers": 0}
    for rm in (HALL_A, HALL_B):
        lo, hi = _room(rm)
        if lo is None:
            continue
        h5._rm_in(lo, hi, ("TableDiningFactory", "ChairFactory", "TableCandleFactory", "AboVaseFactory", "WineglassFactory", "WallArtFactory", "OliveTreeFactory", "CupFactory"))
        cx = (lo[0] + hi[0]) / 2; zt = 0.11 + 0.76; R = 0.9
        bm_c = bmesh.new()
        for tx in (cx - 2.5, cx + 2.5):
            for ty in (lo[1] + 4.9, lo[1] + 8.0):
                h5._pleated(f"CfBanquetCloth({rm}|{n['tables']})", cloth, tx, ty, R, zt, 0.12)
                for k in range(8):                                         # 8 settings + 8 chairs round the rim
                    a = 2 * math.pi * k / 8 + math.pi / 8; ux, uy = math.cos(a), math.sin(a)
                    ra.lib("PlateFactory", 100 + k, tx + ux * (R - 0.25), ty + uy * (R - 0.25), zt, 0.0, 0.92, mat=plate)
                    ra.lib("WineglassFactory", 200 + k, tx + math.cos(a + 0.3) * (R - 0.12), ty + math.sin(a + 0.3) * (R - 0.12), zt, 0.0, 1.4)
                    for nm_, off in (("LibForkFactory", -0.16), ("LibKnifeFactory", 0.16)):
                        ra.lib(nm_, 600 + k, tx + ux * (R - 0.25) - uy * off, ty + uy * (R - 0.25) + ux * off, zt + 0.002, a, 1.0)
                    px, py = tx + ux * (R + 0.34), ty + uy * (R + 0.34); yaw = math.atan2(-uy, -ux)          # the chair faces the table
                    ch = ra.hssd(r"Upholstered Dining Chair|Parsons|Dining Chair", 300,                       # one chair model per hall: a banquet is one matched set
                                  px, py, 0.11, yaw, fit=(0.5, 0.5, 0.95), size=(0.75, 1.1))
                    if ch is None:
                        continue
                    n["chairs"] += 1
                    zs = 0.11 + 0.47                                   # r4 #1: the cube covers read as boxes: the real chair stays, all its fabric in white, a navy sash bow on the back
                    ch.data = ch.data.copy()
                    for mi_ in range(len(ch.data.materials)):
                        ch.data.materials[mi_] = cover
                    n["covers"] += 1
                    if os.environ.get("ROOM_CONVFLOOR_BOWS") == "1":       # r5 test: the bow lobes read as blue mushrooms on the plain white chairs: off by default
                        h5._bow(bm_c, px + ux * 0.27, py + uy * 0.27, zs + 0.3, math.atan2(uy, ux) + math.pi / 2, 1)
                if (ra.abo("bouquet", n["tables"] * 7 + 1, tx, ty, zt, 0.0, fit=(0.45, 0.45, 0.55)) or ra.abo("smallplant", n["tables"] * 7 + 1, tx, ty, zt, 0.0, fit=(0.45, 0.45, 0.45))) is None:
                    pass
                n["tables"] += 1
        if bm_c.verts:
            me = bpy.data.meshes.new(f"CfBows({rm})"); bm_c.to_mesh(me); me.materials.append(cover); me.materials.append(sash)
            for p_ in me.polygons:
                p_.use_smooth = True
            bpy.context.scene.collection.objects.link(bpy.data.objects.new(f"CfBows({rm})", me))
        bm_c.free()
        zc = _zc(rm)                                                       # warm fill so the halls read bright (r3: near black)
        for i, x in enumerate((cx - 3.5, cx, cx + 3.5)):
            for j, y in enumerate((lo[1] + 4.0, lo[1] + 7.5)):
                _light(f"ir_cf_hallfill_{rm}_{i}_{j}", "AREA", (x, y, zc - 0.3), 420.0, sx=2.4, sy=2.4)
    stats["cf_halls2"] = n


def _foyer2(stats):
    """The office pantry leaves the foyer; two curved lounge groups (real sofa + 2 navy barrel chairs + round coffee table + rug) by the west glazing."""
    lo, hi = _room(FOYER)
    if lo is None:
        return
    k = h5._rm_in(lo, hi, ("PantryRunFactory", "EspressoMachineFactory", "MicrowaveFactory", "SnackBasketFactory", "DrinkCansFactory", "CupFactory", "PhoneFactory", "BreakTableFactory", "CafeChairFactory"))
    navy = _velvet("ir_cf_navy_velvet", (0.05, 0.08, 0.2)); tan = _velvet("ir_cf_tan_velvet", (0.55, 0.4, 0.26)); g = 0
    for cy in (lo[1] + 4.2, lo[1] + 9.6):
        cx = lo[0] + 2.4
        ra.abo("bigrug", 31 + g, cx + 0.3, cy, 0.112, 0.0, fit=(3.2, 2.6, 0.03))
        _recolour(ra.abo("loungesofa", 41 + g, cx - 0.75, cy, 0.11, 0.0, fit=(2.6, 1.0, 0.9)), tan)
        for dy in (-0.75, 0.75):
            _recolour(ra.abo("barrel", 51 + g, cx + 1.35, cy + dy, 0.11, math.pi, fit=(0.8, 0.8, 0.85)), navy)
        ra.abo("roundtable", 61 + g, cx + 0.3, cy, 0.11, 0.0, fit=(1.0, 1.0, 0.45))
        ra.abo("smallplant", 71 + g, cx + 0.3, cy, 0.56, 0.0, fit=(0.3, 0.3, 0.35))
        zc_ = _zc(FOYER); brass_r = _flat("ir_cf_brass_ring", (0.78, 0.6, 0.3), 0.25, 1.0); led_r = _emit("ir_cf_ring_led", (1.0, 0.85, 0.6), 8.0)      # r6 #7: two stacked brass rings over each lounge group
        h5._ring_pendant(f"CfRingPendant{g}", cx + 0.3, cy, zc_ - 0.75, brass_r, led_r)
        _light(f"ir_cf_ring_{g}", "POINT", (cx + 0.3, cy, zc_ - 0.95), 260, (1.0, 0.82, 0.58), r=0.3)
        g += 1
    stats["cf_foyer2"] = {"removed": k, "groups": g}


def _rooms2(stats):
    """Breakouts A / C: a long dining-height table + 8 upholstered tan chairs; B: classroom, 2 rows of light desks with navy chairs; coffee break: walnut buffet on the north wall,
    4 high round tables + navy stools; speaker lounge: cream sofa, navy armchairs, a glass-rod screen. Office tables, credenzas and desk clutter go."""
    navy = _velvet("ir_cf_navy_velvet", (0.05, 0.08, 0.2)); tan = _velvet("ir_cf_tan_velvet", (0.55, 0.4, 0.26)); cream = _velvet("ir_cf_cream_velvet", (0.85, 0.8, 0.7)); n = {}
    clutter = ("ConferenceTableFactory", "OakCredenzaFactory", "CupFactory", "NotebookFactory", "OpenLaptopFactory", "PaperStackFactory", "PenCupFactory", "SpeakerphoneFactory", "TakeawayCupFactory",
               "TaskChairFactory", "LanyardFactory", "ClipboardFactory", "WhiteboardFactory")
    for i, rm in enumerate(BREAKOUTS):
        lo, hi = _room(rm)
        if lo is None:
            continue
        h5._rm_in(lo, hi, clutter); cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2 - 0.2; c = 0
        if True:                                                           # r5 #2: B gets the A/C set too (white striped chairs at glass desks), navy chairs
            ra.abo("bigrug", 91 + i, cx, cy, 0.112, 0.0, fit=(3.4, 2.5, 0.03))                     # r4 #4: a rug, a walnut credenza + TV on the end wall
            ra.abo("credenza", 95 + i, cx, hi[1] - 0.3, 0.11, math.pi, fit=(1.8, 0.45, 0.75))
            tv_ = ra.abo("tv", 97 + i, cx, hi[1] - 0.06, 1.0, math.pi, fit=(1.4, 0.1, 0.85))
            tb_ = ra.hssd(r"oval (dining |conference )?table|racetrack table|conference table|boat shaped table", 11 + i, cx, cy, 0.11, 0.0, fit=(2.4, 1.1, 0.78), size=(1.6, 3.2)) or ra.hssd(r"Dining Table", 11 + i, cx, cy, 0.11, 0.0, fit=(2.4, 1.1, 0.78), size=(1.8, 2.5))
            for o_ in ([tb_] + list(tb_.children_recursive)) if tb_ is not None else []:      # the whole table (any child meshes too) in dark walnut: the top was a separate white slot
                if o_.type == "MESH" and o_.material_slots:
                    o_.data = o_.data.copy()
                    for sl_ in o_.material_slots:                         # slot-level: HSSD imports may link materials on the object
                        sl_.material = _wood("ir_cf_walnut_dk", (0.16, 0.08, 0.04))
            for o_ in [o_ for o_ in bpy.data.objects if o_.type == "MESH" and o_.name.startswith(("BreakTableFactory", "TableDiningFactory", "AboTableFactory", "AboDeskFactory")) and h5._in_room(o_, lo, hi)]:
                bpy.data.objects.remove(o_, do_unlink=True)                    # realize's white table left under the new one
            if tb_ is not None:
                for sx in (-0.85, -0.28, 0.28, 0.85):
                    for sy in (-1, 1):
                        _recolour(ra.hssd(r"Dining Chair|Side Chair", 21 + i, cx + sx, cy + sy * 0.85, 0.11, math.pi / 2 if sy < 0 else -math.pi / 2, fit=(0.5, 0.5, 0.95), size=(0.75, 1.1)), navy if i == 1 else tan); c += 1
            ra.abo("bouquet", 81 + i, cx, cy, 0.11 + 0.78, 0.0, fit=(0.35, 0.35, 0.45))
        else:
            for ry in (cy - 0.9, cy + 0.6):
                for rx in (cx - 0.85, cx + 0.85):
                    if ra.hssd(r"\bdesk\b|writing table|console table", 33, rx, ry, 0.11, 0.0, fit=(1.4, 0.6, 0.76), size=(1.0, 1.6)) is not None:
                        for dx in (-0.35, 0.35):
                            _recolour(ra.hssd(r"Dining Chair|Side Chair", 45, rx + dx, ry + 0.55, 0.11, -math.pi / 2, fit=(0.5, 0.5, 0.95), size=(0.75, 1.1)), navy); c += 1
        n[rm] = c
    lo, hi = _room(COFFEE)
    if lo is not None:
        h5._rm_in(lo, hi, ("PantryRunFactory", "EspressoMachineFactory", "MicrowaveFactory", "SnackBasketFactory", "DrinkCansFactory", "CupFactory", "TakeawayCupFactory", "BreakTableFactory", "CafeChairFactory"))
        ra.hssd(r"sideboard|buffet", 5, (lo[0] + hi[0]) / 2, hi[1] - 0.3, 0.11, math.pi, fit=(2.4, 0.5, 0.9), size=(1.4, 2.6), grow=True)
        c = 0
        for tx in (lo[0] + 2.0, lo[0] + 5.5):
            for ty in (lo[1] + 1.4, lo[1] + 3.0):
                tb_ = ra.hssd(r"Atlantis Pub Table|Bari Bar Table", 7, tx, ty, 0.11, 0.0, fit=(0.76, 0.76, 1.0), size=(0.6, 1.2), grow=True)
                if tb_ is not None:
                    _retop(tb_, _wood("ir_cf_pubtop", (0.42, 0.26, 0.13)))
                    for a in (0.0, math.pi):
                        _recolour(ra.hssd(r"Bar Stool|Counter Stool", 9, tx + 0.55 * math.cos(a), ty + 0.55 * math.sin(a), 0.11, a + math.pi, fit=(0.45, 0.45, 0.8), size=(0.6, 1.1)), navy)
                c += 1
        n[COFFEE] = c
    lo, hi = _room(LOUNGE)
    if lo is not None:
        for o in [o for o in bpy.data.objects if o.type == "MESH" and h5._in_room(o, lo, hi)]:
            if o.name.startswith("AboSofaFactory"):
                _recolour(o, cream)
            elif o.name.startswith(("AboArmchairFactory", "TaskChairFactory", "OfficeChairFactory")):        # r3: one 'armchair' was a castor office chair: two navy wing chairs instead
                bpy.data.objects.remove(o, do_unlink=True)
        for j, (wx, wy) in enumerate(((hi[0] - 1.3, (lo[1] + hi[1]) / 2 - 0.7), (hi[0] - 1.3, (lo[1] + hi[1]) / 2 + 0.7))):
            _recolour(ra.hssd(r"Wing Chair|Wingback", 4, wx, wy, 0.11, math.pi, fit=(0.85, 0.85, 1.1), size=(0.9, 1.2)), navy)
        glass = _flat("ir_cf_rod_glass", (0.82, 0.88, 0.88), 0.06)
        brass = _flat("ir_cf_brass", (0.78, 0.6, 0.3), 0.28, 1.0); x0 = lo[0] + 1.0; y0 = lo[1] + 0.9
        rods = [("cyl", (x0 + 0.06 * i, y0, 0.16), (x0 + 0.06 * i, y0, 2.4), 0.022, 12) for i in range(26)]
        _mesh("CfGlassRodScreen", [(glass, rods), (brass, [("box", x0 + 0.75, y0, 0.13, 1.62, 0.08, 0.04), ("box", x0 + 0.75, y0, 2.42, 1.62, 0.08, 0.04)])])
        n[LOUNGE] = 1
    stats["cf_rooms2"] = n


def _r6(stats):
    """r5 review #1 (pale cream wash): a 1.1 m dark walnut wainscot with raised panels and a brass cap rail on every public wall (doors skipped); #7: stray WallArtFactory /
    notice items hung on the corridor walls (their centre sat just outside the room box, so clean missed them)."""
    walnut = _wood("ir_cf_walnut_dk", (0.16, 0.08, 0.04)); dk = _wood("ir_cf_walnut_xdk", (0.06, 0.03, 0.015)); brass = _flat("ir_cf_brass", (0.85, 0.64, 0.3), 0.22, 1.0)
    pr = {walnut: [], dk: [], brass: []}; n = 0; H = 1.1
    for rm in (FOYER, CORR, SERVICE, HALL_A, HALL_B, COFFEE):
        lo, hi = _room(rm)
        if lo is None:
            continue
        for nm, ax, line, side, a0, a1 in (("S", 0, lo[1] + _win(rm, 'S'), 1, lo[0], hi[0]), ("N", 0, hi[1] - _win(rm, 'N'), -1, lo[0], hi[0]), ("W", 1, lo[0] + _win(rm, 'W'), 1, lo[1], hi[1]), ("E", 1, hi[0] - _win(rm, 'E'), -1, lo[1], hi[1])):
            if rm == FOYER and nm == "W":
                continue
            for u0, u1 in h5._segments(a0 + 0.05, a1 - 0.05, sorted(h5._door_gaps(ax, line, a0, a1, pad=0.08) + _open_gaps(rm, ax, line, side, a0, a1)), minw=0.4):
                def P(a, d, z, sa, sd, sz):
                    return ("box", a, line + side * d, z, sa, sd, sz) if ax == 0 else ("box", line + side * d, a, z, sd, sa, sz)
                pr[dk].append(P((u0 + u1) / 2, 0.012, 0.11 + H / 2, u1 - u0, 0.024, H))                         # the dark backing
                k = max(1, int((u1 - u0) // 0.9))
                for i in range(k):                                                                            # raised panels
                    a = u0 + (i + 0.5) * (u1 - u0) / k; w = (u1 - u0) / k - 0.12
                    pr[walnut].append(P(a, 0.03, 0.11 + 0.2 + (H - 0.4) / 2, w, 0.02, H - 0.4))
                pr[brass].append(P((u0 + u1) / 2, 0.035, 0.11 + H, u1 - u0, 0.05, 0.03))                      # brass cap rail
                pr[walnut].append(P((u0 + u1) / 2, 0.03, 0.11 + H + 0.03, u1 - u0, 0.06, 0.04)); n += 1
    _mesh("CfWainscot", list(pr.items()))
    rm_ = 0
    for rm in (CORR, SERVICE, FOYER):
        lo, hi = _room(rm)
        if lo is not None:
            rm_ += h5._rm_in((lo[0] - 0.3, lo[1] - 0.3, 0), (hi[0] + 0.3, hi[1] + 0.3, 0), ("WallArtFactory", "ClinicWallItemFactory", "NoticeBoardFactory", "CorkBoardFactory", "BulletinBoardFactory"))
    stats["cf_r6"] = {"wainscot_runs": n, "stray_wall_items": rm_}


def _rr_finish(lo, hi, n):
    """r10 #2: the restroom kept the generator's dark carpet floor and grey wall (the finish parts' room lists never named it): cream veined marble with the brown inlay band, a thin brass line on the band, cream stone wall panels."""
    rm = "restroom_0/0"
    f = bpy.data.objects.get(f"{rm}.floor")
    if f is not None:
        f.data = f.data.copy()
        m = _inlay_floor(rm, lo, hi, ring=False)
        for sl in f.material_slots:
            sl.material = m
    w = bpy.data.objects.get(f"{rm}.wall")
    if w is not None:
        pm = _stone_panel()
        for sl in w.material_slots:
            sl.material = pm
    brass = _flat("ir_cf_brass", (0.85, 0.64, 0.3), 0.22, 1.0)
    z = lo[2] + 0.004; d = 0.55 + 0.1 + 0.012                                  # just outside the 14 cm inlay band (its centre is 0.55 m from the walls)
    x0, x1, y0, y1 = lo[0] + d, hi[0] - d, lo[1] + d, hi[1] - d
    if x1 > x0 and y1 > y0:
        t = 0.015
        _mesh("CfRestroomBrassInlay", [(brass, [("box", (x0 + x1) / 2, y0, z, x1 - x0, t, 0.006), ("box", (x0 + x1) / 2, y1, z, x1 - x0, t, 0.006),
                                                 ("box", x0, (y0 + y1) / 2, z, t, y1 - y0, 0.006), ("box", x1, (y0 + y1) / 2, z, t, y1 - y0, 0.006)])], soft=False)
    n["restroom_door_closed"] = _rr_door(lo, hi)
    n["restroom_finish"] = 1


def _rr_door(lo, hi):
    """r10 #1: the restroom's door leaf stands open INTO the 1.78 m room (the vanity view looked at its back): swing it shut about the hinge, as h2_ref does for bath doors."""
    from mathutils import Matrix
    LEAF = ("LiteDoorFactory", "LouverDoorFactory", "GlassPanelDoorFactory", "PanelDoorFactory"); k = 0
    cas = [c for c in bpy.data.objects if c.type == "MESH" and c.name.startswith("DoorCasingFactory")]
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(LEAF)]:
        b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
        if not (lo[0] - 0.3 < cx < hi[0] + 0.3 and lo[1] - 0.6 < cy < hi[1] + 0.3):
            continue
        near = min(cas, key=lambda c_: sum(((_bb(c_)[0][i] + _bb(c_)[1][i]) / 2 - (cx, cy)[i]) ** 2 for i in range(2)), default=None)
        if near is None:
            continue
        n0, n1 = _bb(near); ncx, ncy = (n0[0] + n1[0]) / 2, (n0[1] + n1[1]) / 2
        if math.hypot(ncx - cx, ncy - cy) > 1.3:
            continue
        if (b1[0] - b0[0]) < (b1[1] - b0[1]):                         # leaf runs along y: hinge = the end nearer the casing centre
            hy = b0[1] if abs(b0[1] - ncy) < abs(b1[1] - ncy) else b1[1]; h = Vector((cx, hy, 0)); d = Vector((0, (b1[1] + b0[1]) - 2 * hy, 0)).normalized()
        else:
            hx = b0[0] if abs(b0[0] - ncx) < abs(b1[0] - ncx) else b1[0]; h = Vector((hx, cy, 0)); d = Vector(((b1[0] + b0[0]) - 2 * hx, 0, 0)).normalized()
        along_x = (n1[0] - n0[0]) > (n1[1] - n0[1]); t = Vector((1 if ncx > h.x else -1, 0, 0)) if along_x else Vector((0, 1 if ncy > h.y else -1, 0))
        ang = math.atan2(d.x * t.y - d.y * t.x, d.dot(t))
        if abs(ang) < 0.05:
            continue
        o.matrix_world = Matrix.Translation(h) @ Matrix.Rotation(ang, 4, "Z") @ Matrix.Translation(-h) @ o.matrix_world; k += 1
    bpy.context.view_layer.update()
    return k


def _restroom_vanity(lo, hi, n, t=0):
    """r9: the vanity (HSSD, floating look) on the east wall with its long axis ALONG the wall and its front facing the room (the r8 one stuck 0.69 m into the room with its 0.32 m side along the wall), the mirror centred over it, and a warm vanity strip + 2 downlights so the narrow restroom is not dark."""
    brass = _flat("ir_cf_brass", (0.85, 0.64, 0.3), 0.22, 1.0)
    h5._rm_in((lo[0], lo[1], 0), (hi[0], hi[1] - 1.8, 0), ("WashBasinFactory", "HomeVanityFactory"))
    yc = lo[1] + 1.05; xe = hi[0] - _win("restroom_0/0", "E")           # r10: the door end of the room (y 13.1-14.9, the stall starts at 14.98): the r9 centre (14.6) put half the mirror behind the stall
    v = ra.hssd(r"vanity", 85, xe - 0.28, yc, 0.11, math.pi, fit=(0.55, 1.4, 0.9), size=(0.6, 2.2), grow=True)       # r9: the ABO pick was a 0.25 x 0.55 m console; a real vanity unit, grown to ~1.4 m, long side along the wall
    if v is None:
        v = ra.abo("vanity", 85, xe - 0.28, yc, 0.11, math.pi, fit=(0.55, 1.6, 0.9))
    if v is not None and max(v.dimensions[0], v.dimensions[1]) < 0.9:                       # r10: the HSSD 'vanity' came out 0.32 x 0.34 m (a tiny cabinet): replace it by a proper walnut vanity with a stone top, an undermount basin and a faucet
        bpy.data.objects.remove(v, do_unlink=True); v = None
    wal = _wood("ir_cf_vanity_walnut", (0.25, 0.14, 0.08)); stone = _flat("ir_cf_vanity_stone", (0.88, 0.84, 0.76), 0.18); chrome = _flat("ir_cf_chrome", (0.8, 0.8, 0.82), 0.12, 1.0)
    if v is None:
        L, D, cx = 1.2, 0.5, xe - 0.26
        _mesh("CfRestroomVanity", [(wal, [("box", cx, yc, 0.42, D, L, 0.62), ("box", cx - D / 2 + 0.01, yc, 0.42, 0.02, L + 0.02, 0.62)]), (stone, [("box", cx, yc, 0.76, D + 0.04, L + 0.04, 0.04)]),
                                           (chrome, [("cyl", (cx - D / 2 + 0.02, yc - 0.3, 0.52), (cx - D / 2 + 0.02, yc - 0.3, 0.57), 0.025, 8), ("cyl", (cx - D / 2 + 0.02, yc + 0.3, 0.52), (cx - D / 2 + 0.02, yc + 0.3, 0.57), 0.025, 8)])], soft=True)
        bas = ra.hssd(r"wash ?basin|sink|lavatory", 87, cx + 0.02, yc, 0.78, math.pi, fit=(0.42, 0.5, 0.2), size=(0.3, 0.7))
        if bas is None:
            dark = _flat("ir_cf_basin", (0.92, 0.92, 0.9), 0.12)
            _mesh("CfRestroomBasin", [(dark, [("cyl", (cx + 0.02, yc, 0.775), (cx + 0.02, yc, 0.8), 0.19, 24)])], soft=False)
        _mesh("CfRestroomTap", [(chrome, [("cyl", (xe - 0.06, yc, 0.8), (xe - 0.06, yc, 0.92), 0.015, 8), ("cyl", (xe - 0.06, yc, 0.92), (xe - 0.17, yc, 0.92), 0.012, 8)])], soft=False)
    mir = _flat("ir_cf_mirror", (0.9, 0.9, 0.9), 0.02, 1.0)
    _mesh("CfRestroomMirror", [(mir, [("box", xe - 0.008, yc, 1.55, 0.01, 1.0, 0.8)]), (brass, [("box", xe - 0.013, yc, 1.55, 0.012, 1.06, 0.86)])], soft=False)
    strip = _emit("ir_cf_vanity_strip", (1.0, 0.85, 0.62), 6.0)
    _mesh("CfVanityStrip", [(strip, [("box", xe - 0.05, yc, 2.05, 0.04, 1.0, 0.04)])], soft=False)       # a real LED bar above the mirror (a fixture, not a wall emitter)
    for k, (x, y) in enumerate(((lo[0] + 0.9, yc - 0.3), (lo[0] + 0.9, yc + 1.5))):
        _light(f"ir_cf_rr_dl_{k}", "AREA", (x, y, 2.8), 70, sx=0.5, sy=0.5)
    _light("ir_cf_rr_vanity", "AREA", (xe - 0.35, yc, 2.0), 40, sx=0.2, sy=1.0)
    n["restroom"] = {"toilets_added": t, "vanity": v is not None}


def _r5(stats):
    """r4 review #3 (dark walnut skirting + door surrounds), #6 (coffee bar), #7 (ABO art in the corridor niches), #8 (restroom stalls + vanity)."""
    n = {}
    walnut = _wood("ir_cf_walnut_dk", (0.16, 0.08, 0.04)); brass = _flat("ir_cf_brass", (0.85, 0.64, 0.3), 0.22, 1.0); sk = []
    for rm in PUBLIC:                                                  # 12 cm dark walnut skirting along every public wall, broken at doors
        lo, hi = _room(rm)
        if lo is None:
            continue
        for ax, line, side, a0, a1 in ((0, lo[1] + _win(rm, 'S'), 1, lo[0], hi[0]), (0, hi[1] - _win(rm, 'N'), -1, lo[0], hi[0]), (1, lo[0] + _win(rm, 'W'), 1, lo[1], hi[1]), (1, hi[0] - _win(rm, 'E'), -1, lo[1], hi[1])):
            for u0, u1 in h5._segments(a0 + 0.02, a1 - 0.02, h5._door_gaps(ax, line, a0, a1, pad=0.05), minw=0.2):
                c, w = (u0 + u1) / 2, u1 - u0
                sk.append(("box", c, line + side * 0.012, 0.17, w, 0.024, 0.12) if ax == 0 else ("box", line + side * 0.012, c, 0.17, 0.024, w, 0.12))
    fr = []                                                            # walnut door surrounds with a brass inner bead on every door in the corridors / foyer / halls
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.startswith(("DoorCasingFactory",)):
            b0, b1 = _bb(o); cx_, cy_ = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            if not any(_room(r)[0] is not None and _room(r)[0][0] - 0.3 < cx_ < _room(r)[1][0] + 0.3 and _room(r)[0][1] - 0.3 < cy_ < _room(r)[1][1] + 0.3 for r in (CORR, FOYER, HALL_A, HALL_B, SERVICE)):
                continue
            o.data = o.data.copy()
            for i_ in range(len(o.data.materials)):
                o.data.materials[i_] = walnut
            fr.append(o.name)
    _mesh("CfSkirting", [(walnut, sk)])
    n["skirting"], n["door_frames"] = len(sk), len(fr)
    lo, hi = _room(COFFEE)                                             # coffee bar along the north wall: a walnut counter with a stone top, 2 HSSD coffee machines, urns, cups, pastries
    if lo is not None:
        h5._rm_in(lo, hi, ("AboSideboardFactory",)); bx0, bx1 = lo[0] + 1.0, hi[0] - 1.0; by = hi[1] - 0.35; zt = 0.11 + 0.92
        for o in [o for o in bpy.data.objects if o.type == "MESH" and h5._in_room(o, (bx0, by - 0.4, 0), (bx1, hi[1], 0)) and _bb(o)[0][2] < 0.5 and not o.name.startswith((COFFEE, "Cf", "Baseboard"))]:
            bpy.data.objects.remove(o, do_unlink=True)
        stone = _flat("ir_cf_bar_stone", (0.86, 0.82, 0.76), 0.25)
        _mesh("CfCoffeeBar", [(walnut, [("box", (bx0 + bx1) / 2, by, 0.11 + 0.45, bx1 - bx0, 0.6, 0.9)]), (stone, [("box", (bx0 + bx1) / 2, by - 0.02, zt - 0.015, bx1 - bx0 + 0.06, 0.66, 0.03)]),
                              (brass, [("box", (bx0 + bx1) / 2, by - 0.305, 0.11 + 0.08, bx1 - bx0, 0.01, 0.03)])])
        k = 0
        cxb = (bx0 + bx1) / 2                                              # r5 #3: machines + cups mid-bar, facing the room (they sat at the far west end, out of the wide views)
        for j, x in enumerate((cxb - 0.75, cxb - 0.15)):
            k += ra.hssd(r"espresso machine|coffee machine|coffee maker|gaggia|espressione", 50 + j, x, by, zt, math.pi, fit=(0.45, 0.45, 0.6), cats=("coffee_machine", "coffee_maker"), size=(0.28, 0.7), grow=True) is not None
        for j, x in enumerate((bx1 - 1.6, bx1 - 1.1)):
            k += ra.hssd(r"urn|dispenser|thermos|beverage", 60 + j, x, by, zt, math.pi, fit=(0.3, 0.3, 0.5), size=(0.2, 0.8), grow=True) is not None
        for j in range(3):
            k += ra.hssd(r"paper cup|cup stack|coffee cup", 70 + j, cxb + 0.4 + j * 0.2, by - 0.12, zt, 0.0, fit=(0.12, 0.12, 0.25), size=(0.05, 0.4), grow=True) is not None
        st_ = ra.hssd(r"^2 tier cake stand|cake stand", 3, bx1 - 0.5, by, zt, 0.0, fit=(0.32, 0.32, 0.3), cats=("tray",))
        k += st_ is not None
        n["coffee_bar"] = k
    lo, hi = _room(CORR)                                               # the corridor niches: framed ABO art instead of the blank glowing panels
    if lo is not None:
        h5._rm_in((lo[0] - 1, lo[1] - 1, 0), (hi[0] + 1, hi[1] + 1, 0), ("CfPosterNiches",))
        a = 0
        for line, side in ((lo[1] + _win(CORR, 'S'), 1), (hi[1] - _win(CORR, 'N'), -1)):
            for s0, s1 in h5._segments(lo[0] + 0.4, hi[0] - 0.4, h5._door_gaps(0, line, lo[0], hi[0], pad=0.3), minw=1.6):
                o = ra.abo("wallart", 120 + a, (s0 + s1) / 2, line + side * 0.07, 1.35, (math.pi / 2 if side > 0 else -math.pi / 2) + float(os.environ.get("ROOM_CF_ART_YAW") or 0.0), fit=(0.85, 0.06, 0.95))      # r5 #7: was 0 / pi = edge-on to the wall
                if o is not None:
                    a += 1
                    _light(f"ir_cf_artlight_{a}", "SPOT", ((s0 + s1) / 2, line + side * 0.45, 2.75), 45.0, r=0.05).rotation_euler = (math.radians(-25 * side), 0, 0)
        n["corridor_art"] = a
    lo, hi = _room("restroom_0/0")                                     # restroom: 2 WCs on the north wall boxed by HPL cubicles (hotel5 stalls2), a stone vanity with 2 basins + mirror
    if lo is not None:
        t = 0
        for j in range(2):
            x = lo[0] + 0.5 + j * 0.95
            if not any(o.name.startswith(("ToiletFactory", "ToiletStallFactory")) and h5._in_room(o, (x - 0.4, hi[1] - 1.6, 0), (x + 0.4, hi[1], 0)) for o in bpy.data.objects):
                t += ra.hssd(r"\btoilet\b|wc", 80 + j, x, hi[1] - 0.35, 0.11, math.pi, fit=(0.4, 0.65, 0.8), size=(0.3, 0.9)) is not None
        bpy.context.view_layer.update()
        try:
            h5._stalls2(stats)
        except Exception as ex:                                    # noqa: BLE001
            stats["cf_stalls_error"] = repr(ex)[:120]
        _rr_finish(lo, hi, n)
        _restroom_vanity(lo, hi, n, t)
    stats["cf_r5"] = n



# ---- plants ---------------------------------------------------------------------------------------------------------------------------
def _plants(stats):
    n = 0; rg = random.Random(5)
    for rm in (FOYER, CORR, HALL_A, HALL_B, LOUNGE, COFFEE):
        lo, hi = _room(rm)
        if lo is None:
            continue
        pts = [(lo[0] + 0.45, hi[1] - 0.45), (hi[0] - 0.45, hi[1] - 0.45)] if rm != CORR else [(lo[0] + 0.5, lo[1] + 0.5), (hi[0] - 0.5, hi[1] - 0.5)]
        if rm in (HALL_A, HALL_B):
            pts = [(lo[0] + 0.45, lo[1] + 0.45), (hi[0] - 0.45, lo[1] + 0.45), (lo[0] + 0.45, hi[1] - 0.45), (hi[0] - 0.45, hi[1] - 0.45)]
        for i, (x, y) in enumerate(pts):
            busy = any(o.type == "MESH" and not o.name.startswith((rm, "Baseboard", "Cf")) and abs((_bb(o)[0][0] + _bb(o)[1][0]) / 2 - x) < 0.45 and abs((_bb(o)[0][1] + _bb(o)[1][1]) / 2 - y) < 0.45 and _bb(o)[0][2] < 1.0
                       for o in bpy.data.objects if o.type == "MESH" and h5._in_room(o, lo, hi))
            if busy:
                continue
            o = ra.hssd(r"potted plant|fiddle|monstera|bird of paradise|areca|palm in|ficus|olive tree|snake plant", 40 + n, x, y, 0.11, rg.uniform(0, 6.28), fit=(0.7, 0.7, 1.7), size=(0.9, 2.2), grow=True)
            n += o is not None
    stats["cf_plants"] = n


# r7 review: foyer flowers / plants. The foyer probe cameras (r7 poses, embedded: the kit stage runs before the views are written): (location, target, hfov deg).
FOYER_CAMS = [[[0.9, 0.95, 1.81], [4.05, 6.5, 1.61], 65.0], [[7.01, 11.7, 1.81], [4.05, 6.5, 1.76], 65.0], [[0.9, 12.05, 1.81], [4.05, 6.5, 1.61], 65.0], [[7.4, 0.6, 1.81], [4.05, 6.5, 1.76], 65.0], [[1.0, 10.0, 1.7], [6.4, 7.6, 1.2], 70], [[3.0, 8.0, 1.7], [4.0, 0.8, 1.5], 70]]


def _cam_sees(x, y):
    """True if a point stands in the central 70 percent of a foyer camera's frame within 4 m, or within 1.0 m of the camera."""
    for loc, tgt, hf in FOYER_CAMS:
        dx, dy = x - loc[0], y - loc[1]; d = math.hypot(dx, dy)
        if d < 1.0:
            return True
        if d < 4.0:
            ang = abs((math.atan2(dy, dx) - math.atan2(tgt[1] - loc[1], tgt[0] - loc[0]) + math.pi) % (2 * math.pi) - math.pi)
            if ang < math.radians(hf) * 0.35:
                return True
    return False


def _edge_cams(x, y):
    """How many foyer cameras see (x, y) in the frame-edge band (0.55-0.95 of the half FOV) at 2-7 m, and none closer than 1 m."""
    k = 0
    for loc, tgt, hf in FOYER_CAMS:
        dx, dy = x - loc[0], y - loc[1]; d = math.hypot(dx, dy)
        if d < 1.0:
            return -1
        ang = abs((math.atan2(dy, dx) - math.atan2(tgt[1] - loc[1], tgt[0] - loc[0]) + math.pi) % (2 * math.pi) - math.pi)
        if 2.0 < d < 7.0 and math.radians(hf) * 0.55 < ang < math.radians(hf) * 0.95:
            k += 1
    return k


def _foyer3(stats):
    """Two side tables with bouquets and up to 4 real plants (1.4-1.9 m) at free spots of the foyer, off the cameras' central lines and not on the lift bank / reception."""
    lo, hi = _room(FOYER)
    if lo is None:
        return
    bpy.context.view_layer.update()
    objs = [(o, _bb(o)) for o in bpy.data.objects if o.type == "MESH" and h5._in_room(o, lo, hi) and not o.name.startswith(("Baseboard", FOYER)) and _bb(o)[0][2] < 1.2 and _bb(o)[1][2] > 0.25]

    def busy(x, y, r):
        for o, (b0, b1) in objs:
            if b0[0] - r < x < b1[0] + r and b0[1] - r < y < b1[1] + r and (b1[0] - b0[0] > 0.2 or b1[1] - b0[1] > 0.2) and not o.name.startswith(("CfFluted", "CfWain", "CfPier")):
                return True
        return False
    cands = []
    for i in range(int((hi[0] - lo[0]) / 0.4) + 1):
        for j in range(int((hi[1] - lo[1]) / 0.4) + 1):
            x, y = lo[0] + 0.5 + 0.4 * i, lo[1] + 0.5 + 0.4 * j
            if x > hi[0] - 0.5 or y > hi[1] - 0.5:
                continue
            near_wall = min(x - lo[0], hi[0] - x, y - lo[1], hi[1] - y) < 1.6
            ec = _edge_cams(x, y)
            if near_wall and ec >= 1 and not busy(x, y, 0.55):
                cands.append((x, y, ec))
    picked = []
    for x, y, _ec in sorted(cands, key=lambda c: -c[2]):                             # r9: most frame-edge views first
        if all(math.hypot(x - a, y - b) > 2.2 for a, b in picked):
            picked.append((x, y))
        if len(picked) >= 6:
            break
    n_pl = n_fl = 0
    rg = random.Random(8)
    for k, (x, y) in enumerate(picked):
        if k % 3 == 2 and n_fl < 2:
            t = ra.abo("sidetable", 90 + k, x, y, 0.11, rg.uniform(0, 6.28), fit=(0.6, 0.6, 0.75))
            if t is not None:
                bpy.context.view_layer.update(); zt = ra.top(t)
                ra.abo("bouquet", 95 + k, x, y, zt, 0.0, fit=(0.4, 0.4, 0.55)); n_fl += 1
                continue
        o = ra.hssd(r"potted plant|fiddle|monstera|bird of paradise|areca|palm in|ficus|olive tree|snake plant", 60 + k, x, y, 0.11, rg.uniform(0, 6.28), fit=(0.7, 0.7, 1.8), size=(1.2, 2.2), grow=True)
        n_pl += o is not None
    cnt = [o for o in bpy.data.objects if o.name == "CfReceptionCounter"]                  # r9: bouquets clearly on the reception counter top
    n_rb = 0
    if cnt:
        bpy.context.view_layer.update(); cx, cy, R = hi[0] - 0.6, (lo[1] + hi[1]) / 2 + 1.0, 1.9; ztop = _bb(cnt[0])[1][2]
        for k, dy in enumerate((-0.9, 0.5)):
            x = cx - math.sqrt((R + 0.12) ** 2 - dy * dy)
            n_rb += ra.abo("bouquet", 120 + k, x, cy + dy, ztop, 0.0, fit=(0.45, 0.45, 0.7)) is not None
    stats["cf_foyer3_reception_bouquets"] = n_rb
    stats["cf_foyer3"] = {"cands": len(cands), "plants": n_pl, "tables_flowers": n_fl, "spots": [(round(a, 2), round(b, 2)) for a, b in picked]}


# ---- light ----------------------------------------------------------------------------------------------------------------------------
def _lights(stats):
    k = 0
    for o in bpy.data.objects:                                          # every pre-existing lamp to 3000 K
        if o.type == "LIGHT" and not o.name.startswith("ir_cf_"):
            o.data.color = WARM; k += 1
    n = 0
    for rm in PUBLIC:
        lo, hi = _room(rm)
        if lo is None:
            continue
        zc = _zc(rm); W, D = hi[0] - lo[0], hi[1] - lo[1]
        nx, ny = max(1, round(W / 4.0)), max(1, round(D / 4.0))
        e = 70.0 if rm in (HALL_A, HALL_B, FOYER) else 20.0 if rm in (CORR, SERVICE) else 60.0 if rm == COFFEE else 130.0      # r4 test: breakouts / lounge read dark at 45; r5 #1: corridors / coffee were ~2 EV over (walnut read cream)
        for i in range(nx):
            for j in range(ny):
                _light(f"ir_cf_fill_{rm}_{i}_{j}", "AREA", (lo[0] + W * (i + 0.5) / nx, lo[1] + D * (j + 0.5) / ny, zc - 0.25), e, sx=1.6, sy=1.6); n += 1
    dim = 0                                                            # r5 #1: the 3 m corridors sat ~1.5-2 EV over (walnut and stone both read cream): every lamp over them at ROOM_CONVFLOOR_CORR_DIM (0.45)
    kdim = float(os.environ.get("ROOM_CONVFLOOR_CORR_DIM") or 0.45)
    for rm in (CORR, SERVICE):
        lo, hi = _room(rm)
        if lo is None:
            continue
        for o in bpy.data.objects:
            if o.type == "LIGHT" and not o.get("cf_dimmed"):
                p = o.matrix_world.translation
                if lo[0] - 0.2 < p.x < hi[0] + 0.2 and lo[1] - 0.2 < p.y < hi[1] + 0.2:
                    o.data = o.data.copy(); o.data.energy *= kdim; o["cf_dimmed"] = 1; dim += 1
    stats["cf_light"] = {"warmed": k, "fills": n, "corridor_dimmed": dim}



def _r3_hanging(lo, hi, zmin=1.6, rx=("Real_hssd", "CfRingPendant")):
    """Remove hanging fixtures (Real_hssd chandeliers whose underside is above zmin, the brass ring pendants and their cables) in a room."""
    n = 0
    for o in list(bpy.data.objects):
        if o.type == "MESH" and o.name.startswith(rx):
            b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            if lo[0] < cx < hi[0] and lo[1] < cy < hi[1] and (b0[2] > zmin or o.name.startswith("CfRingPendant")):
                bpy.data.objects.remove(o, do_unlink=True); n += 1
    return n


# ------------------------------------------------------------------------------------------------------ floors
def _r3_veins(stats):
    """Marble with real veining + broad curved brown inlay bands (ref: strongly veined stone, wide branching inlays) on every public floor."""
    n = 0
    for rm in (FOYER, COFFEE, HALL_A, HALL_B, CORR, LOUNGE):
        m = bpy.data.materials.get(f"ir_cf_marble_{rm.replace('/', '_')}")
        lo, hi = _room(rm)
        if m is None or lo is None or m.get("r3_veins"):
            continue
        nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
        for nd in N:                                               # thicker, darker veins in the base stone
            if nd.type == "MATH" and nd.operation == "SUBTRACT" and abs(nd.inputs[1].default_value - 0.42) < 1e-6:
                nd.inputs[1].default_value = 0.28
            if nd.type == "MIX" and nd.data_type == "RGBA" and tuple(round(c, 2) for c in nd.inputs["B"].default_value[:3]) == (0.62, 0.52, 0.42):
                nd.inputs["B"].default_value = (0.5, 0.38, 0.27, 1)
        mx = b.inputs["Base Color"].links[0].from_node
        if mx.type != "MIX":
            continue
        mask = mx.inputs["Factor"].links[0].from_socket
        geo = N.new("ShaderNodeNewGeometry"); sp = N.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Position"], sp.inputs["Vector"])

        def mth(op, a, c=None):
            nn = N.new("ShaderNodeMath"); nn.operation = op
            for i, s_ in enumerate((a, c)):
                if s_ is None:
                    continue
                if isinstance(s_, (int, float)):
                    nn.inputs[i].default_value = s_
                else:
                    L.new(s_, nn.inputs[i])
            return nn.outputs[0]
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2; hx, hy = (hi[0] - lo[0]) / 2, (hi[1] - lo[1]) / 2
        new = mask
        for ax, ay, rf, hw in ((-1.5, -0.7, 1.35, 0.17), (1.55, 0.8, 1.4, 0.17), (0.2, 2.2, 1.7, 0.1)):
            ccx, ccy = cx + ax * hx, cy + ay * hy; R = rf * max(hx, hy) * 1.1
            dd = mth("SQRT", mth("ADD", mth("POWER", mth("SUBTRACT", sp.outputs["X"], ccx), 2.0), mth("POWER", mth("SUBTRACT", sp.outputs["Y"], ccy), 2.0)))
            new = mth("MAXIMUM", new, mth("LESS_THAN", mth("ABSOLUTE", mth("SUBTRACT", dd, R)), hw))
        L.new(new, mx.inputs["Factor"]); m["r3_veins"] = 1; n += 1
    stats["r3_veins"] = n


# ------------------------------------------------------------------------------------------------------ foyer
def _r3_foyer(stats):
    lo, hi = _room(FOYER)
    if lo is None:
        return
    z0 = lo[2]; zc = _zc(FOYER)
    k = _r3_hanging(lo, hi)
    for i, (x, y, R) in enumerate(((3.0, 3.9, 0.85), (3.0, 9.8, 0.85), (4.7, 6.9, 1.15))):
        rc.crystal_ring(f"CfR3Ring{i}", x, y, zc - 0.55, R=R, drop=0.55)
    mats, pr = rc.niche_pr()
    brass = _flat("ir_cf_brass", (0.78, 0.6, 0.3), 0.28, 1.0); shade = _emit("ir_h5_shade", (1.0, 0.86, 0.66), 3.0); pr[brass] = []; pr[shade] = []
    for j, (sx, sy, dx, dy) in enumerate(((1.0, lo[1] + 0.03, 0, 1), (7.4, lo[1] + 0.03, 0, 1), (hi[0] - 0.03, 11.4, -1, 0), (hi[0] - 0.03, 2.0, -1, 0), (lo[0] + 0.03, 12.2, 1, 0))):
        rc.sconce(pr, brass, shade, sx, sy, z0 + 2.0, dx, dy, f"ir_cf_r3_sc_{j}")
    # reception: base LED, one central bouquet + a nameplate instead of the lamps / vases
    h5._rm_in((4.5, 5.5), (7.6, 9.6), ("Real_tablelamp", "Real_bouquet", "VaseFactory"))
    cx, cy, R = hi[0] - 0.6, (lo[1] + hi[1]) / 2 + 1.0, 1.9
    led = _emit("ir_r3_led", (1.0, 0.8, 0.5), 7.0); pr[led] = []
    for i in range(24):
        a0, a1 = math.radians(130 + 100 * i / 24), math.radians(130 + 100 * (i + 1) / 24); am = (a0 + a1) / 2; L_ = 2 * (R + 0.08) * math.sin((a1 - a0) / 2) + 0.01
        pr[led].append(("box", cx + (R + 0.08) * math.cos(am), cy + (R + 0.08) * math.sin(am), 0.19, L_, 0.03, 0.025, am + math.pi / 2))
    pr[brass].append(("box", cx - R * 0.9, cy, 1.14, 0.03, 0.4, 0.09))                                    # nameplate
    h5._emit_mesh("CfR3ReceptionDetail", pr)
    rc.bouquet(910, cx - R * 0.98, cy + 0.6, 1.1, 1.3, big=True)
    stats["r3_foyer"] = {"removed": k}


# ------------------------------------------------------------------------------------------------------ halls
def _r3_halls(stats):
    """Banquet halls: blank white projection screen, beige upholstered chairs, deep gold-trimmed coffer ceiling with big crystal-ring chandeliers, vertical wall lights, tall plants beside the stage, no track bar."""
    cover = bpy.data.materials.get("ir_cf_cover_satin")
    if cover is not None and not cover.get("r3_beige"):
        rc.recolor(cover, (0.7, 0.6, 0.45)); cover.node_tree.nodes["Principled BSDF"].inputs["Sheen Tint"].default_value = (0.9, 0.8, 0.6, 1); cover["r3_beige"] = 1
    scr = bpy.data.materials.get("ir_r3_screen_blank") or _emit("ir_r3_screen_blank", (0.93, 0.94, 0.96), 0.9)
    brass = _flat("ir_cf_brass", (0.78, 0.6, 0.3), 0.28, 1.0); cream = _flat("ir_cf_soffit", (0.93, 0.9, 0.84), 0.6)
    glow = _emit("ir_cf_cove", (1.0, 0.8, 0.55), 2.5); led = _emit("ir_r3_led", (1.0, 0.8, 0.5), 7.0)
    for rm in (HALL_A, HALL_B):
        lo, hi = _room(rm)
        if lo is None:
            continue
        z0 = lo[2]; zc = _zc(rm)
        o = bpy.data.objects.get(f"CfStage({rm})")
        if o is not None:
            for i, m in enumerate(o.data.materials):
                if m is not None and m.name.startswith("ir_cf_screen_img"):
                    o.data.materials[i] = scr
        for t in [t for t in bpy.data.objects if t.name.startswith(f"CfStageTruss({rm})")]:
            bpy.data.objects.remove(t, do_unlink=True)
        _r3_hanging(lo, hi, 1.8, rx=("Real_hssd",))
        W, D = hi[0] - lo[0], hi[1] - lo[1]; cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        pr = {cream: [], brass: [], glow: [], led: []}
        for i in range(0, 4):                                              # 3 x 2 coffer: beams 0.55 wide, 0.32 deep, brass edge, cove strips in the cells
            x = lo[0] + W * i / 3
            pr[cream].append(("box", x, cy, zc - 0.16, 0.55, D - 0.1, 0.32)); pr[brass].append(("box", x, cy, zc - 0.325, 0.57, D - 0.1, 0.015))
        for j in range(0, 3):
            y = lo[1] + D * j / 2
            pr[cream].append(("box", cx, y, zc - 0.16, W - 0.1, 0.55, 0.32)); pr[brass].append(("box", cx, y, zc - 0.33, W - 0.1, 0.57, 0.015))
        for i in range(3):
            for j in range(2):
                ccx, ccy = lo[0] + W * (i + 0.5) / 3, lo[1] + D * (j + 0.5) / 2
                for dx, dy, sx, sy in ((W / 6 - 0.4, 0, 0.04, D / 4 - 0.5), (-(W / 6 - 0.4), 0, 0.04, D / 4 - 0.5), (0, D / 4 - 0.4, W / 3 - 1.0, 0.04), (0, -(D / 4 - 0.4), W / 3 - 1.0, 0.04)):
                    pr[glow].append(("box", ccx + dx, ccy + dy, zc - 0.31, sx, sy, 0.02))
        for yy in (lo[1] + 2.2, lo[1] + 5.2, lo[1] + 8.2):                  # vertical wall lights between the panelling
            for xx in (lo[0] + 0.14, hi[0] - 0.14):
                pr[led].append(("box", xx, yy, 1.9, 0.03, 0.05, 1.0))
        h5._emit_mesh(f"CfR3Coffer({rm})", pr)
        for (x, y) in ((lo[0] + W * 0.25, cy + 0.4), (lo[0] + W * 0.75, cy + 0.4)):
            rc.crystal_ring(f"CfR3HallRing({rm}|{int(x)})", x, y, zc - 0.7, R=1.2, drop=0.6)
        plm = _flat("ir_r3_planter", (0.1, 0.1, 0.1), 0.35, 0.6); pp = {plm: []}
        cxs = (lo[0] + (hi[0] - lo[0]) / 2)
        for i, (px, py) in enumerate(((cxs - 3.7, lo[1] + 0.8), (cxs + 3.7, lo[1] + 0.8), (lo[0] + 0.7, hi[1] - 0.7))):
            pp[plm].append(("box", px, py, z0 + 0.275, 0.7, 0.7, 0.55)); pp[plm].append(("box", px, py, z0 + 0.57, 0.76, 0.76, 0.04))
            rc.plant("atrium", 30 + i, px, py, z0 + 0.55, 2.0, 1.1, yaw=i * 1.9, name="Real_r3_palm")
        h5._emit_mesh(f"CfR3Planters({rm})", pp)
    stats["r3_halls"] = 1


# ------------------------------------------------------------------------------------------------------ coffee / meeting / lounge / corridor
def _r3_rooms(stats):
    # coffee break: crystal rings over the high tables, flowers + cups on them
    lo, hi = _room(COFFEE)
    if lo is not None:
        zc = _zc(COFFEE)
        for i, (x, y) in enumerate(((lo[0] + 2.0, lo[1] + 2.2), (lo[0] + 5.5, lo[1] + 2.2))):
            rc.crystal_ring(f"CfR3CoffeeRing{i}", x, y, zc - 0.7, R=0.75, drop=0.45)
            for dy in (-0.8, 0.8):
                rc.bouquet(920 + i * 2 + (dy > 0), x, y + dy - 0.0, 1.11, 0.5, big=False)
    # meeting rooms: crystal ring over the table, sheer curtain wall on the window wall
    sheer = bpy.data.materials.get("ir_r3_sheer")
    if sheer is None:
        sheer = _flat("ir_r3_sheer", (0.95, 0.94, 0.9), 0.8); b = sheer.node_tree.nodes["Principled BSDF"]; b.inputs["Transmission Weight"].default_value = 0.6
    for i, rm in enumerate(BREAKOUTS):
        lo, hi = _room(rm)
        if lo is None:
            continue
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2 - 0.2; zc = _zc(rm)
        _r3_hanging(lo, hi, 1.8, rx=("Real_hssd", "CfRingPendant"))
        rc.crystal_ring(f"CfR3MeetRing{i}", cx, cy, zc - 0.6, R=0.6, drop=0.4)
        wy = hi[1] - 0.12                                                   # sheer curtains at both ends of the window wall; the TV / credenza centre stays free
        for j, (c0, c1) in enumerate(((lo[0] + 0.3, cx - 1.1), (cx + 1.1, hi[0] - 0.3))):
            h5._curtain(f"CfR3Sheer{i}{j}", sheer, c0, c1, wy, -1, lo[2] + 0.01, zc - 0.12, True, folds=8, depth=0.06, seed=i * 2 + j)
    stats["r3_rooms"] = 1



def _r3_garden(stats):
    """The windows look onto a formal garden (refs: garden-facing glazing, planted perimeter) instead of the city skyline."""
    im = bpy.data.images.load("/jarvis/project/robomituba/data/venue_refs/bigglass_cards/env_garden_04_photo.png", check_existing=True); n = 0
    for m in bpy.data.materials:
        if m.use_nodes and m.name.startswith("ir_bg_card_env"):
            for nd in m.node_tree.nodes:
                if nd.type == "TEX_IMAGE":
                    nd.image = im; n += 1
    stats["r3_garden"] = n


def _r3_lifts(stats):
    """Lift faces in brushed champagne steel with brass frames (they were bronze-brown and merged into the walnut panelling)."""
    leaf = bpy.data.materials.get("ir_cf_lift_leaf"); fr = bpy.data.materials.get("ir_cf_bronze")
    if leaf is not None and not leaf.get("r3_steel"):
        rc.recolor(leaf, (0.74, 0.7, 0.62)); b = leaf.node_tree.nodes["Principled BSDF"]; b.inputs["Metallic"].default_value = 0.85; b.inputs["Roughness"].default_value = 0.3; leaf["r3_steel"] = 1
    if fr is not None and not fr.get("r3_brass"):
        rc.recolor(fr, (0.8, 0.62, 0.3)); fr["r3_brass"] = 1
    stats["r3_lifts"] = 1


def _r3_classroom(stats):
    """Meeting B is the classroom of the reference: two rows of two long desks with navy chairs facing the TV wall, two crystal-ring pendants (the r5 boardroom set goes)."""
    rm = BREAKOUTS[1]; lo, hi = _room(rm)
    if lo is None:
        return
    z0 = lo[2]; cx = (lo[0] + hi[0]) / 2; zc = _zc(rm)
    for o in list(bpy.data.objects):
        if o.type == "MESH" and h5._in_room(o, (lo[0] + 0.3, lo[1] + 0.3, 0), (hi[0] - 0.3, hi[1] - 0.9, 0)) and o.name.startswith(("Real_hssd", "Real_bouquet", "Real_bigrug")) and _bb(o)[1][2] < 1.6:
            bpy.data.objects.remove(o, do_unlink=True)
    navy = _velvet("ir_cf_navy_velvet", (0.05, 0.08, 0.2)); k = 0
    rc.pool("r3_desk", "conftable", None)
    for j, yd in enumerate((16.2, 14.5)):
        for i, xd in enumerate((cx - 1.15, cx + 1.15)):
            d = rc.place("r3_desk", 700 + j * 2 + i, xd, yd, z0, 0.0, (1.9, 0.72, 0.76), "Real_r3_desk")
            for q in (-0.6, 0.0, 0.6):
                ch = ra.hssd(r"Dining Chair|Side Chair", 21, xd + q, yd - 0.62, z0, math.pi / 2, fit=(0.5, 0.5, 0.95), size=(0.75, 1.1))
                if ch is not None:
                    _recolour(ch, navy); ch.name = "Real_r3_chair"; k += 1
    for i, x in enumerate((cx - 1.2, cx + 1.2)):
        rc.crystal_ring(f"CfR3ClassRing{i}", x, 15.4, zc - 0.6, R=0.55, drop=0.4)
    stats["r3_classroom"] = k


def _r3_hatches(stats):
    brass = _flat("ir_cf_brass", (0.78, 0.6, 0.3), 0.28, 1.0); blk = _flat("ir_cf_black", (0.02, 0.02, 0.02), 0.4); pr = {brass: [], blk: []}
    for rm in (BREAKOUTS[0], BREAKOUTS[2]):
        lo, hi = _room(rm)
        if lo is None:
            continue
        cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2 - 0.2 + 0.25
        pr[brass].append(("cyl", (cx, cy, 0.11 + 0.78), (cx, cy, 0.11 + 0.795), 0.085, 28)); pr[blk].append(("cyl", (cx, cy, 0.11 + 0.795), (cx, cy, 0.11 + 0.8), 0.06, 28))
    h5._emit_mesh("CfR3Hatches", pr)
    lo, hi = _room(LOUNGE)
    if lo is not None:
        zc = _zc(LOUNGE); cx = (lo[0] + hi[0]) / 2
        for i, (x, y, R) in enumerate(((cx - 0.5, 15.2, 0.6), (cx + 0.6, 16.2, 0.45))):
            rc.crystal_ring(f"CfR3LivingRing{i}", x, y, zc - 0.7 - 0.2 * i, R=R, drop=0.4)
    stats["r3_hatches"] = 1


def _r3_corr(stats):
    lo, hi = _room(CORR)
    if lo is None:
        return
    o = bpy.data.objects.get("CfPosterNiches")
    if o is not None:
        bpy.data.objects.remove(o, do_unlink=True)
    mats, pr = rc.niche_pr(); n = 0
    for line, side in ((lo[1] + _win(CORR, "S"), 1), (hi[1] - _win(CORR, "N"), -1)):
        for s0, s1 in h5._segments(lo[0] + 0.4, hi[0] - 0.4, h5._door_gaps(0, line, lo[0], hi[0], pad=0.3), minw=1.6):
            n += rc.green_niche(pr, mats, 0, line + side * 0.01, side, (s0 + s1) / 2, w=0.85, h=1.5, zc=1.5, seed=200 + n)
    h5._emit_mesh("CfR3CorrNiches", pr)
    stats["r3_corr"] = n




def _ratio3(stats):
    """User 2026-10-26: Codex reference-match ratio >= 0.5 (refs_ratio.py): veined stone floors with broad curved inlays, crystal-ring chandeliers (foyer / halls / coffee / meeting / lounge), coffered halls with a blank
    projection screen, beige chairs, wall lights + palms, lit green recesses in the corridor, steel lift faces, reception base light + bouquet, classroom for meeting B. Runs last; ROOM_CONVFLOOR_SKIP=ratio3 turns it off."""
    for fn in (_r3_garden, _r3_veins, _r3_foyer, _r3_halls, _r3_rooms, _r3_corr, _r3_lifts, _r3_classroom, _r3_hatches):
        try:
            bpy.context.view_layer.update(); fn(stats)
        except Exception as ex:                                  # noqa: BLE001 -- a part that fails must not sink the kit stage
            import traceback; traceback.print_exc()
            stats[f"cf_{fn.__name__}_error"] = repr(ex)[:160]


def apply(stats):
    sc = bpy.context.scene
    if sc.get("ir_convfloor_shell") or bpy.data.objects.get(f"{FOYER}.floor") is None or bpy.data.objects.get(f"{HALL_B}.floor") is None:
        return 0
    skip = set((os.environ.get("ROOM_CONVFLOOR_SKIP") or "").split(",")); n = 0
    for key, fn in (("clean", _clean), ("floor", _floor), ("walls", _walls), ("flutes", _flutes), ("ceiling", _ceiling), ("chandeliers", _chandeliers), ("niches", _niches),
                    ("chairs", _chairs), ("stage", _stage), ("halls2", _halls2), ("reception", _reception), ("foyer2", _foyer2), ("rooms2", _rooms2), ("r5", _r5), ("r6", _r6), ("lifts", _lifts), ("plants", _plants), ("foyer3", _foyer3), ("light", _lights), ("ratio3", _ratio3)):
        if key in skip:
            continue
        try:
            bpy.context.view_layer.update(); fn(stats); n += 1
        except Exception as ex:                                  # noqa: BLE001 -- a part that fails must not sink the kit stage
            import traceback; traceback.print_exc()
            stats[f"cf_{key}_error"] = repr(ex)[:160]
    ra.report(stats, "cf")
    STATS.update({k: v for k, v in stats.items() if k.startswith("cf_")})
    sc["ir_convfloor_shell"] = 1
    return n
