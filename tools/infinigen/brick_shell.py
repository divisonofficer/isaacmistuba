"""S39 brick-loft restaurant shell (kit stage, idempotent via scene["ir_brick_shell"]); ROOM_BRICK_SHELL=1, ROOM_BRICK_SKIP=<parts>, ROOM_BRICK_LIGHT (gain on the lights added here, default 1.0).
One room (break-room_0/0, ~14 x 10 m, 6 m ceiling). Refs: floor_plans_v3/BRICK (plan: entrance at y = 0, tall glazing on the back (north) and right (east) walls, banquette along the left wall).
glaze     floor-to-ceiling black steel glazing with thin mullions on the north and east walls (terrace_open._glaze -> big_glass, street card) + full-height pleated white sheers at the piers
brick     deep red-brown brick with per-brick tone variation and recessed dark mortar (world-space shader + bump) on the walls and pilasters
floor     speckled beige terrazzo (dark + white chips, low roughness)
pendants  black enamel domes over every table + two Edison bare-bulb clusters on drop cords at varied heights, warm lights
furn      one family: realize's tables -> one ABO dining-table model in mahogany, the cafe table -> an ABO round table in black, every chair -> one ABO chair model upholstered olive / black leather on wood legs
banq      the banquette in cream with channel tufting; 3 framed B/W prints (ABO wall art, desaturated) + brass picture lights above it
cellar    the gold-beige beverage fridge -> a black glass-door wine cooler with wooden racks of library bottles and a warm interior light
sconce    brass wall sconces with pleated shades on the left and back walls; big plants (HSSD croton / money tree / ABO planters) in the window corner
"""
from __future__ import annotations

import math
import os
import random

import bpy
import bmesh
from mathutils import Vector

ROOM = "break-room_0/0"
STATS = {}


def _bb(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def _pa():
    from room_planner import proc_assets as pa
    return pa


def _flat(name, rgb, rough=0.5, metal=0.0, transmission=0.0):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name); m.use_nodes = True; b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough; b.inputs["Metallic"].default_value = metal
        b.inputs["Transmission Weight"].default_value = transmission; m["weathered"] = True
    return m


def _emit(name, rgb, s):
    m = _flat(name, rgb, 0.4); b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*rgb, 1); b.inputs["Emission Strength"].default_value = s
    return m


def _gain():
    return float(os.environ.get("ROOM_BRICK_LIGHT") or 1.0)


def _light(name, kind, loc, w, rgb=(1.0, 0.72, 0.45), r=0.05):
    ld = bpy.data.lights.new(name, kind); ld.energy = w * _gain(); ld.color = rgb; ld.shadow_soft_size = r
    o = bpy.data.objects.new(name, ld); o.location = loc; bpy.context.scene.collection.objects.link(o)
    return o


def _obj(name, bm, mat, smooth=True):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for p in me.polygons:
        p.use_smooth = smooth
    me.materials.append(mat) if not isinstance(mat, list) else [me.materials.append(m_) for m_ in mat]
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


def _lathe(bm, prof, cx, cy, z0, seg=32, pleat=0.0, mi=0):
    """Revolve [(r, z)] about the vertical axis at (cx, cy) from z0; pleat > 0 adds that many radial flutes (a pleated shade)."""
    rings = []
    for r, z in prof:
        ring = []
        for k in range(seg):
            a = 2 * math.pi * k / seg; rr = r * (1 + (0.04 * (1 if k % 2 else -1) if pleat else 0.0))
            ring.append(bm.verts.new((cx + rr * math.cos(a), cy + rr * math.sin(a), z0 + z)))
        rings.append(ring)
    for i in range(len(rings) - 1):
        for k in range(seg):
            f = bm.faces.new((rings[i][k], rings[i][(k + 1) % seg], rings[i + 1][(k + 1) % seg], rings[i + 1][k])); f.material_index = mi


def _room():
    f = bpy.data.objects.get(f"{ROOM}.floor"); c = bpy.data.objects.get(f"{ROOM}.ceiling")
    lo, hi = _bb(f)
    return lo, hi, _bb(c)[0][2] if c else 6.0


# ---------------------------------------------------------------- parts
def _glaze(lo, hi, zc, stats):
    from room_planner import terrace_open as to
    keep = {k: os.environ.get(k) for k in ("BIGGLASS_SIDE", "ROOM_TERRACE_CARD", "BIGGLASS_FRAC")}
    os.environ.pop("BIGGLASS_SIDE", None); os.environ["ROOM_TERRACE_CARD"] = "street"; os.environ["BIGGLASS_FRAC"] = "1"
    try:
        bb = (lo[0], hi[0], lo[1], hi[1]); n = 0
        for side in ("N", "E"):
            n += 1 if to._glaze(ROOM, bb, lo[2], zc, side, stats, random.Random(39)) else 0
    finally:
        for k, v in keep.items():
            os.environ.pop(k, None) if v is None else os.environ.__setitem__(k, v)
    sheer = _flat("ir_brick_sheer", (0.96, 0.95, 0.92), 0.6); b = sheer.node_tree.nodes["Principled BSDF"]
    b.inputs["Alpha"].default_value = 0.55; b.inputs["Subsurface Weight"].default_value = 0.0
    k = 0
    for side, L, line, a0 in (("N", hi[0] - lo[0], hi[1] - 0.18, lo[0]), ("E", hi[1] - lo[1], hi[0] - 0.18, lo[1])):
        for i in range(int(L // 2.6) + 1):                                 # a gathered 1.5 m sheer every 2.6 m, full height
            u0 = a0 + 0.15 + i * 2.6; w = 1.5; bm = bmesh.new(); nu, nz = 22, 6; grid = []
            for zi in range(nz + 1):
                row = []
                for ui in range(nu + 1):
                    u = u0 + w * ui / nu; d = 0.045 * (0.5 - 0.5 * math.cos(ui * 2 * math.pi / 3.0))      # r2: sin(ui*pi) was 0 everywhere = flat; 7 pleats per panel
                    z = lo[2] + 0.02 + (zc - 0.15 - lo[2]) * zi / nz
                    row.append(bm.verts.new((u, line - d, z) if side == "N" else (line - d, u, z)))
                grid.append(row)
            for zi in range(nz):
                for ui in range(nu):
                    bm.faces.new((grid[zi][ui], grid[zi][ui + 1], grid[zi + 1][ui + 1], grid[zi + 1][ui]))
            _obj(f"BrickSheer({side}{i})", bm, sheer); k += 1
    stats["brick_glaze"] = {"walls": n, "sheers": k}


def _brick_mat():
    m = bpy.data.materials.get("ir_brick_wall")
    if m is not None:
        return m
    m = bpy.data.materials.new("ir_brick_wall"); m.use_nodes = True; m["weathered"] = True
    N, L = m.node_tree.nodes, m.node_tree.links; b = N["Principled BSDF"]; b.inputs["Roughness"].default_value = 0.85
    tc = N.new("ShaderNodeTexCoord"); gm = N.new("ShaderNodeNewGeometry")
    # world position, wall plane: use x+y as the horizontal run so both wall directions get bricks
    sep = N.new("ShaderNodeSeparateXYZ"); L.new(gm.outputs["Position"], sep.inputs["Vector"])
    add = N.new("ShaderNodeMath"); add.operation = "ADD"; L.new(sep.outputs["X"], add.inputs[0]); L.new(sep.outputs["Y"], add.inputs[1])
    cmb = N.new("ShaderNodeCombineXYZ"); L.new(add.outputs[0], cmb.inputs["X"]); L.new(sep.outputs["Z"], cmb.inputs["Y"])
    br = N.new("ShaderNodeTexBrick"); br.offset = 0.5; br.squash = 1.0
    br.inputs["Scale"].default_value = 1.0; br.inputs["Brick Width"].default_value = 0.26; br.inputs["Row Height"].default_value = 0.09; br.inputs["Mortar Size"].default_value = 0.008
    # Reference orange masonry: wider courses, narrow mortar, shallow roughness relief.
    br.inputs["Color1"].default_value = (0.34, 0.115, 0.045, 1); br.inputs["Color2"].default_value = (0.18, 0.055, 0.025, 1); br.inputs["Mortar"].default_value = (0.24, 0.20, 0.16, 1)
    br.inputs["Bias"].default_value = 0.35
    L.new(cmb.outputs["Vector"], br.inputs["Vector"])
    no = N.new("ShaderNodeTexNoise"); no.inputs["Scale"].default_value = 40.0; no.inputs["Detail"].default_value = 6.0; L.new(cmb.outputs["Vector"], no.inputs["Vector"])
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs["Factor"].default_value = 0.25
    L.new(br.outputs["Color"], mx.inputs["A"]); L.new(no.outputs["Color"], mx.inputs["B"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
    bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 1.0; bu.inputs["Distance"].default_value = 0.004
    inv = N.new("ShaderNodeMath"); inv.operation = "SUBTRACT"; inv.inputs[0].default_value = 1.0; L.new(br.outputs["Fac"], inv.inputs[1])
    sum_ = N.new("ShaderNodeMath"); sum_.operation = "ADD"; L.new(inv.outputs[0], sum_.inputs[0]); mn = N.new("ShaderNodeMath"); mn.operation = "MULTIPLY"; mn.inputs[1].default_value = 0.15
    L.new(no.outputs["Fac"], mn.inputs[0]); L.new(mn.outputs[0], sum_.inputs[1]); L.new(sum_.outputs[0], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"])
    return m


def _brick(lo, hi, zc, stats):
    m = _brick_mat(); n = 0
    for o in bpy.data.objects:
        if o.type == "MESH" and (o.name == f"{ROOM}.wall" or o.name.startswith("PilasterFactory")):
            for i in range(len(o.material_slots)):
                o.material_slots[i].material = m
            n += 1
    stats["brick_walls"] = n


def _floor(lo, hi, zc, stats):
    """Dense angular terrazzo aggregate in world metres, S39 r9 reference."""
    m = bpy.data.materials.get("ir_brick_terrazzo")
    if m is None:
        m = bpy.data.materials.new("ir_brick_terrazzo")
        m.use_nodes = True
        m["weathered"] = True
        nodes = m.node_tree.nodes
        links = m.node_tree.links
        bs = nodes.get("Principled BSDF")
        bs.inputs["Roughness"].default_value = 0.27
        bs.inputs["Coat Weight"].default_value = 0.20
        bs.inputs["Coat Roughness"].default_value = 0.18
        geo = nodes.new("ShaderNodeNewGeometry")
        # Noise warps the two-dimensional cell boundaries by about 1.5 mm.
        noise = nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 90.0
        noise.inputs["Detail"].default_value = 2.0
        links.new(geo.outputs["Position"], noise.inputs["Vector"])
        warp = nodes.new("ShaderNodeVectorMath")
        warp.operation = "MULTIPLY_ADD"
        warp.inputs[1].default_value = (0.003, 0.003, 0.0)
        links.new(noise.outputs["Color"], warp.inputs[0])
        links.new(geo.outputs["Position"], warp.inputs[2])
        current = None
        palette = [(0.025, 0.022, 0.018, 1), (0.17, 0.13, 0.095, 1),
                   (0.40, 0.35, 0.28, 1), (0.65, 0.60, 0.52, 1)]
        for scale, keep in ((55.0, 0.45), (115.0, 0.4), (260.0, 0.35)):
            edge = nodes.new("ShaderNodeTexVoronoi")
            edge.voronoi_dimensions = '2D'
            edge.feature = 'DISTANCE_TO_EDGE'
            edge.inputs["Scale"].default_value = scale
            links.new(warp.outputs["Vector"], edge.inputs["Vector"])
            cell = nodes.new("ShaderNodeTexVoronoi")
            cell.voronoi_dimensions = '2D'
            cell.feature = 'F1'
            cell.inputs["Scale"].default_value = scale
            links.new(warp.outputs["Vector"], cell.inputs["Vector"])
            rgb = nodes.new("ShaderNodeSeparateColor")
            links.new(cell.outputs["Color"], rgb.inputs["Color"])
            inside = nodes.new("ShaderNodeMath")
            inside.operation = 'GREATER_THAN'
            inside.inputs[1].default_value = 0.09
            links.new(edge.outputs["Distance"], inside.inputs[0])
            selected = nodes.new("ShaderNodeMath")
            selected.operation = 'LESS_THAN'
            selected.inputs[1].default_value = keep
            links.new(rgb.outputs["Red"], selected.inputs[0])
            mask = nodes.new("ShaderNodeMath")
            mask.operation = 'MULTIPLY'
            links.new(inside.outputs[0], mask.inputs[0])
            links.new(selected.outputs[0], mask.inputs[1])
            colors = nodes.new("ShaderNodeValToRGB")
            colors.color_ramp.interpolation = 'CONSTANT'
            colors.color_ramp.elements.remove(colors.color_ramp.elements[1])
            for i, color in enumerate(palette):
                el = colors.color_ramp.elements[0] if i == 0 else colors.color_ramp.elements.new(i / 4)
                el.color = color
            links.new(rgb.outputs["Green"], colors.inputs["Fac"])
            mix = nodes.new("ShaderNodeMixRGB")
            mix.inputs[1].default_value = (0.36, 0.31, 0.25, 1)
            if current is not None:
                links.new(current, mix.inputs[1])
            links.new(mask.outputs[0], mix.inputs[0])
            links.new(colors.outputs["Color"], mix.inputs[2])
            current = mix.outputs["Color"]
        links.new(current, bs.inputs["Base Color"])
        rough = nodes.new("ShaderNodeMapRange")
        rough.inputs["To Min"].default_value = 0.14
        rough.inputs["To Max"].default_value = 0.22
        links.new(noise.outputs["Fac"], rough.inputs["Value"])
        links.new(rough.outputs["Result"], bs.inputs["Roughness"])
        m["pkg_h_S39b_aggregate_scales_per_m"] = [55.0, 115.0, 260.0]
        m["pkg_h_S39c_polish"] = {"roughness_min": .14, "roughness_max": .22, "coat": .20}
    floor = bpy.data.objects.get(f"{ROOM}.floor")
    if floor is not None:
        for slot in floor.material_slots:
            slot.material = m
    stats["brick_floor"] = 1


def _tables():
    return [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("TableDiningFactory", "CafeTableFactory", "BrickTable", "BrickRoundTable")) and o.parent is None]


def _pendants(lo, hi, zc, stats):
    blk = _flat("ir_brick_enamel", (0.02, 0.02, 0.022), 0.25); inner = _flat("ir_brick_enamel_in", (0.85, 0.5, 0.17), 0.3, 1.0); brass = _flat("ir_brick_brass", (0.72, 0.52, 0.25), 0.3, 1.0)
    bulb = _emit("ir_brick_filament", (1.0, 0.5, 0.18), 14.0); cord = _flat("ir_brick_cord", (0.02, 0.02, 0.02), 0.6)
    rg = random.Random(7); n = 0
    pos = []
    for t in _tables():
        b0, b1 = _bb(t); pos.append(((b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2))
    for i, (x, y) in enumerate(pos):                                   # a black dome over every table, hung 2.2-2.6 m above the floor
        zb = lo[2] + rg.uniform(2.2, 2.6)
        bm = bmesh.new(); _lathe(bm, [(0.02, 0.26), (0.06, 0.25), (0.14, 0.2), (0.2, 0.1), (0.23, 0.0)], x, y, zb, 40)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        o = _obj(f"BrickDome({i})", bm, blk); s = o.modifiers.new("t", "SOLIDIFY"); s.thickness = 0.006
        bm = bmesh.new(); _lathe(bm, [(0.05, 0.22), (0.12, 0.19), (0.18, 0.11), (0.215, 0.015)], x, y, zb, 40); bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        _obj(f"BrickDomeLiner({i})", bm, inner)      # ratio1: the ref domes glow amber inside (brushed brass liner under the bulb)
        bm = bmesh.new(); _lathe(bm, [(0.0, 0.0), (0.03, 0.02), (0.035, 0.06), (0.025, 0.1), (0.0, 0.11)], x, y, zb - 0.02, 16)
        _obj(f"BrickDomeBulb({i})", bm, bulb)
        bm = bmesh.new(); _lathe(bm, [(0.004, 0.0), (0.004, zc - zb - 0.26)], x, y, zb + 0.26, 8); _obj(f"BrickCord({i})", bm, cord)
        bm = bmesh.new(); _lathe(bm, [(0.0, 0.0), (0.06, 0.0), (0.06, 0.03), (0.0, 0.03)], x, y, zc - 0.03, 20); _obj(f"BrickRose({i})", bm, brass)
        _light(f"ir_brick_dome_{i}", "POINT", (x, y, zb + 0.05), 40, (1.0, 0.58, 0.28)); n += 1
    nb = 0                                                             # two Edison bare-bulb clusters near the windows
    for cx, cy in ((hi[0] - 3.0, hi[1] - 2.0), (lo[0] + 4.5, hi[1] - 1.6)):
        for k in range(12):
            x, y = cx + rg.uniform(-1.0, 1.0), cy + rg.uniform(-0.7, 0.7); zb = lo[2] + rg.uniform(2.2, 3.6)
            bm = bmesh.new(); _lathe(bm, [(0.0, 0.0), (0.04, 0.02), (0.058, 0.08), (0.054, 0.15), (0.028, 0.2), (0.02, 0.22)], x, y, zb, 18)      # r2: ~11 cm bulbs so they read at 512 px
            _obj(f"BrickEdison({nb})", bm, bulb)
            bm = bmesh.new(); _lathe(bm, [(0.02, 0.0), (0.02, 0.05)], x, y, zb + 0.22, 12); _obj(f"BrickEdisonCap({nb})", bm, brass)
            bm = bmesh.new(); _lathe(bm, [(0.003, 0.0), (0.003, zc - zb - 0.27)], x, y, zb + 0.27, 6); _obj(f"BrickEdisonCord({nb})", bm, cord)
            nb += 1
        _light(f"ir_brick_cluster_{cx:.0f}", "POINT", (cx, cy, lo[2] + 3.0), 220, r=0.6)
    stats["brick_pendants"] = {"domes": n, "bulbs": nb}


def _abo_pool(types, w, d, h, rx=None):
    import re
    import furnish_rooms as fr
    return fr._pool(types, w=w, d=d, h=h, name=(lambda e: re.search(rx, e["name"], re.I) is not None) if rx else None)


def _abo_one(pool, seed, x, y, z, front, fit, name):
    import abo_assets
    import real_assets as ra
    e = pool[seed % len(pool)]
    o = abo_assets._import(e, f"{name}({e['id']})")
    return ra._stand(o, x, y, z, front - math.atan2(-1.0, 0.0), fit)


def _recolour(o, rgb, name, rough=0.5, all_slots=False):
    if o is None or o.type != "MESH" or not o.data.materials:
        return
    area = {}
    for p in o.data.polygons:
        area[p.material_index] = area.get(p.material_index, 0.0) + p.area
    m = _flat(name, rgb, rough); o.data = o.data.copy()
    for i in (range(len(o.data.materials)) if all_slots else [max(area, key=area.get)]):
        if i < len(o.data.materials):
            o.data.materials[i] = m


def _legs_wood(o, z0):
    """r3 review: the legs read thin dark metal. Every face below 0.40 m (the legs and the lower rails) gets a warm oak material with grain."""
    if o is None or o.type != "MESH":
        return
    wm = bpy.data.materials.get("ir_brick_chair_oak")
    if wm is None:
        wm = _flat("ir_brick_chair_oak", (0.42, 0.26, 0.12), 0.45)
        try:
            from room_planner import proc_assets as pa
            pa._grain(wm, (0.42, 0.26, 0.12))
        except Exception:                                                   # noqa: BLE001
            pass
    me = o.data; me.materials.append(wm); wi = len(me.materials) - 1; mw = o.matrix_world
    for p_ in me.polygons:
        if (mw @ p_.center).z - z0 < 0.40:
            p_.material_index = wi


def _furn(lo, hi, zc, stats):
    tabs = [(_bb(t), t.name.startswith("CafeTableFactory")) for t in _tables()]
    chairs = [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and o.name.startswith(("ChairFactory", "AboCafechairFactory"))]
    cpos = [(_bb(c), c.name) for c in chairs]
    for o in [t for t in _tables()] + chairs:
        bpy.data.objects.remove(o, do_unlink=True)
    rect = _abo_pool(("TABLE",), (1.0, 1.8), (0.7, 1.1), (0.7, 0.8), r"dining|table") or _abo_pool(("TABLE",), (1.0, 1.8), (0.7, 1.1), (0.7, 0.8))
    rnd = _abo_pool(("TABLE",), (0.6, 1.4), (0.6, 1.4), (0.65, 0.82), r"round|pedestal|tulip") or [e for e in _abo_pool(("TABLE",), (0.7, 1.3), (0.7, 1.3), (0.65, 0.82)) if abs(e["extent_m"][0] - e["extent_m"][2]) < 0.05]
    import abo_assets as _aa                                          # r2: the regex picked moulded shell chairs; use upholstered wood-leg dining chairs by id (Ravenna Lamberton curved-back, Rivet mid-century, Stone & Beam)
    ids = {"B086JJQQZ3", "B086JJCP47", "B086JK1PJ2", "B086JJQQZ4", "B075YNJQLB", "B07B7B6PL8", "B075ZZYH4B", "B07FY8PZBH"}
    chp = [e for e in _aa.entries() if e["id"] in ids] or _abo_pool(("CHAIR",), (0.45, 0.65), (0.45, 0.65), (0.75, 0.95), r"upholster|padded|dining")
    nt = nc = 0; centres = []; legs = []
    for (b0, b1), cafe in tabs:
        cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2; dx, dy = b1[0] - b0[0], b1[1] - b0[1]; centres.append((cx, cy))
        if cafe and rnd:
            o = _abo_one(rnd, 3, cx, cy, lo[2], 0.0, (1.15, 1.15, 0.78), "BrickRoundTable"); _recolour(o, (0.025, 0.025, 0.028), "ir_brick_black_tbl", 0.35, all_slots=True)
        elif rect:
            o = _abo_one(rect, 5, cx, cy, lo[2], 0.0 if dx > dy else math.pi / 2, (max(dx, dy, 1.2), min(dx, dy) if min(dx, dy) > 0.7 else 0.8, 0.78), "BrickTable")
            _recolour(o, (0.13, 0.024, 0.014), "ir_brick_mahogany", 0.16, all_slots=True)      # r2: 0.22 linear read terracotta
        else:
            continue
        nt += 1
    for i, ((b0, b1), nm) in enumerate(cpos):
        if not chp:
            break
        x, y = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
        tx, ty = min(centres, key=lambda c: (c[0] - x) ** 2 + (c[1] - y) ** 2) if centres else (x, y + 1)
        front = math.atan2(ty - y, tx - x)
        o = _abo_one(chp, 11, x, y, lo[2], front, (0.6, 0.6, 0.95), "BrickChair")
        _recolour(o, (0.11, 0.14, 0.07) if i % 2 == 0 else (0.02, 0.02, 0.022), "ir_brick_olive" if i % 2 == 0 else "ir_brick_leather", 0.6 if i % 2 == 0 else 0.35)
        legs.append(o)
        nc += 1
    bpy.context.view_layer.update()                                    # ra._stand sets location / scale only: refresh matrix_world once before the leg pass
    for o in legs:
        _legs_wood(o, lo[2])
    for o in bpy.data.objects:                                         # the right-wall sofa: cream
        if o.type == "MESH" and o.name.startswith("AboSofaFactory"):
            _recolour(o, (0.86, 0.82, 0.72), "ir_brick_cream", 0.8)
    stats["brick_furn"] = {"tables": nt, "chairs": nc, "plan_tables": 9, "pools": [len(rect), len(rnd), len(chp)]}


def _banq(lo, hi, zc, stats):
    m = bpy.data.materials.get("ir_brick_tufted")
    if m is None:
        m = _flat("ir_brick_tufted", (0.86, 0.82, 0.72), 0.85); N, L = m.node_tree.nodes, m.node_tree.links; b = N["Principled BSDF"]
        gm = N.new("ShaderNodeNewGeometry"); wv = N.new("ShaderNodeTexWave"); wv.wave_type = "BANDS"; wv.bands_direction = "Y"; wv.inputs["Scale"].default_value = 18.0
        wv.inputs["Distortion"].default_value = 0.0; L.new(gm.outputs["Position"], wv.inputs["Vector"])
        bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 0.8; bu.inputs["Distance"].default_value = 0.02; L.new(wv.outputs["Fac"], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"])
    bq = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("BanquetteFactory")]
    for o in bq:
        o.data = o.data.copy()
        for i, sl in enumerate(o.data.materials):
            if sl and sl.name.startswith("ir_banquette"):
                o.data.materials[i] = m
    import real_assets as ra
    brass = _flat("ir_brick_brass", (0.72, 0.52, 0.25), 0.3, 1.0); na = 0
    if bq:
        b0, b1 = _bb(bq[0])
        import wall_face as wf
        xw = lo[0] + wf.inset(ROOM, "W")                                  # the wall's inner face (the floor box edge sits inside the 0.1 m wall)
        wood = _flat("ir_brick_frame", (0.035, 0.022, 0.014), 0.45); mat_ = _flat("ir_brick_mat", (0.9, 0.88, 0.82), 0.9)
        for k, fy in enumerate((0.2, 0.5, 0.8)):
            y = b0[1] + fy * (b1[1] - b0[1]); z = lo[2] + 1.95
            img = bpy.data.images.load(f"/jarvis/project/robomituba/data/venue_refs/brick_restaurant_01/prints/city_{k}.png", check_existing=True)
            pm = bpy.data.materials.get(f"ir_brick_print_{k}")
            if pm is None:
                pm = _flat(f"ir_brick_print_{k}", (0.5, 0.5, 0.5), 0.55); nt = pm.node_tree; bs_ = nt.nodes["Principled BSDF"]
                ti = nt.nodes.new("ShaderNodeTexImage"); ti.image = img; nt.links.new(ti.outputs["Color"], bs_.inputs["Base Color"])
            pw, ph = 0.72, 0.96; fw = 0.05; xs = xw + 0.01
            for nm, mat, sz, dx in ((f"BrickPrintFrame({k})", wood, (0.035, pw + 2 * fw + 0.1, ph + 2 * fw + 0.1), 0.0), (f"BrickPrintMat({k})", mat_, (0.036, pw + 0.1, ph + 0.1), 0.004)):
                bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0)
                for v in bm.verts:
                    v.co = (xs + dx + v.co.x * sz[0], y + v.co.y * sz[1], z + v.co.z * sz[2])
                _obj(nm, bm, mat, smooth=False)
            bm = bmesh.new(); uv = bm.loops.layers.uv.verify(); x_ = xs + 0.0225
            vs = [bm.verts.new((x_, y + dy, z + dz)) for dy, dz in ((-pw / 2, -ph / 2), (pw / 2, -ph / 2), (pw / 2, ph / 2), (-pw / 2, ph / 2))]
            f_ = bm.faces.new(vs[::-1])
            for lp, c in zip(f_.loops, ((1, 0), (0, 0), (0, 1), (1, 1))):
                lp[uv].uv = c
            _obj(f"BrickPrint({k})", bm, pm, smooth=False); na += 1
            bm = bmesh.new()                                               # brass picture light: wall plate, arm, bar
            _lathe(bm, [(0.025, 0.0), (0.025, 0.03)], xw + 0.015, y, z + 0.3, 16)
            bm.verts.ensure_lookup_table(); bmesh.ops.rotate(bm, cent=(xw + 0.015, y, z + 0.315), matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2, 3, "Y"), verts=list(bm.verts))
            o2 = _obj(f"BrickPicLightPlate({k})", bm, brass)
            bm = bmesh.new(); _lathe(bm, [(0.018, 0.0), (0.018, 0.42)], 0, 0, -0.21, 16)
            bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2, 3, "X"), verts=list(bm.verts))
            bmesh.ops.translate(bm, vec=(xw + 0.14, y, z + 0.42), verts=list(bm.verts)); _obj(f"BrickPicLightBar({k})", bm, brass)
            bm = bmesh.new(); _lathe(bm, [(0.006, 0.0), (0.006, 0.16)], 0, 0, 0, 8)
            bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(math.radians(60), 3, "Y"), verts=list(bm.verts))
            bmesh.ops.translate(bm, vec=(xw + 0.015, y, z + 0.32), verts=list(bm.verts)); _obj(f"BrickPicLightArm({k})", bm, brass)
            sp = _light(f"ir_brick_pic_{k}", "SPOT", (xw + 0.16, y, z + 0.4), 25); sp.data.spot_size = math.radians(70); sp.rotation_euler = (0, math.radians(-150), 0)
    nch = 0                                                           # r2: real channel tufting: vertical padded channels + buttons on the backrest, two pillows (ra.soft)
    if bq:
        cream = _flat("ir_brick_tuft_cream", (0.62, 0.56, 0.46), 0.85); btn = _flat("ir_brick_tuft_btn", (0.16, 0.12, 0.08), 0.5); seam = _flat("ir_brick_tuft_seam", (0.12, 0.09, 0.06), 0.9)
        bb0, bb1 = _bb(bq[0]); xb = bb0[0] + 0.1; zb0 = bb0[2] + 0.42; zb1 = bb1[2] - 0.04; n_ch = int((bb1[1] - bb0[1] - 0.1) // 0.2)
        for ci in range(n_ch):
            y = bb0[1] + 0.1 + (ci + 0.5) * (bb1[1] - bb0[1] - 0.1) / n_ch; bm = bmesh.new(); r_ = 0.085
            _lathe(bm, [(0.0, 0.0), (r_ * 0.7, 0.01), (r_, 0.04), (r_ * 1.0, (zb1 - zb0) - 0.05), (r_ * 0.6, (zb1 - zb0) - 0.01), (0.0, zb1 - zb0)], xb, y, zb0, 14)
            _obj(f"BrickTuftChannel({ci})", bm, cream); nch += 1
            sb = bmesh.new(); bmesh.ops.create_cube(sb, size=1.0)                         # a dark seam strip between this channel and the next
            for v_ in sb.verts:
                v_.co = (xb + r_ * 0.55 + v_.co.x * 0.02, y + (bb1[1] - bb0[1] - 0.1) / n_ch / 2 + v_.co.y * 0.014, (zb0 + zb1) / 2 + v_.co.z * (zb1 - zb0 - 0.04))
            _obj(f"BrickTuftSeam({ci})", sb, seam, smooth=False)
            for zz in (zb0 + 0.2, zb0 + 0.38):
                bm = bmesh.new(); _lathe(bm, [(0.0, 0.0), (0.026, 0.0), (0.026, 0.02), (0.0, 0.026)], xb + r_ - 0.01, y - r_ - 0.01, zz, 10); _obj(f"BrickTuftBtn({ci})", bm, btn)
        for k_, fy in enumerate((0.25, 0.75)):
            ra.soft(f"BrickBanqPillow({k_})", _flat("ir_brick_pillow", (0.42, 0.14, 0.09) if k_ else (0.22, 0.25, 0.14), 0.9), bb0[0] + 0.28, bb0[1] + fy * (bb1[1] - bb0[1]), bb0[2] + 0.62, 0.42, 0.42, 0.14, yaw=0.3 * (k_ - 0.5), seed=k_)
    stats["brick_banq"] = {"banquettes": len(bq), "prints": na, "channels": nch}


def _cellar(lo, hi, zc, stats):
    from room_planner import proc_boutique_flagship as fl
    from room_planner import lib_objects
    old = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("BeverageFridgeFactory", "DisplayCoolerFactory"))]
    if not old:
        return
    b0, b1 = _bb(old[0]); cx = (b0[0] + b1[0]) / 2; yb = b0[1]
    for o in old:
        bpy.data.objects.remove(o, do_unlink=True)
    w, d, h = 0.9, 0.66, 2.05; cy = yb + d / 2                       # back on the front wall, glass door facing +y into the room
    frame = _flat("ir_brick_cooler", (0.025, 0.025, 0.028), 0.4, 1.0); glass = _flat("ir_brick_cooler_glass", (0.9, 0.93, 0.95), 0.02, transmission=1.0)
    try:
        gb = glass.node_tree.nodes["Principled BSDF"]; gb.inputs["IOR"].default_value = 1.02; gb.inputs["Specular IOR Level"].default_value = 0.05          # r3: the door reflected the street and hid the racks
    except Exception:                                                   # noqa: BLE001
        pass
    warm = _flat("ir_brick_cooler_walnut", (0.06, 0.035, 0.02), 0.45); rack = _flat("ir_brick_rack", (0.42, 0.27, 0.14), 0.6)
    fr = [("box", cx, cy, 0.04, w, d, 0.08), ("box", cx, cy, h - 0.02, w, d, 0.04), ("box", cx - w / 2 + 0.02, cy, h / 2, 0.04, d, h), ("box", cx + w / 2 - 0.02, cy, h / 2, 0.04, d, h),
          ("box", cx, cy + d / 2 - 0.02, 0.1, w, 0.04, 0.12), ("box", cx, cy + d / 2 - 0.01, h - 0.07, w, 0.02, 0.1), ("box", cx - w / 2 + 0.07, cy + d / 2 + 0.02, 1.0, 0.02, 0.03, 0.6)]
    gl = [("box", cx, cy + d / 2 - 0.012, h / 2, w - 0.08, 0.008, h - 0.24)]; wm = [("box", cx, yb + 0.01, h / 2, w - 0.1, 0.01, h - 0.2)]; rk = []
    bf = lib_objects.factory("BottleFactory"); protos = []; nb = 0; rgl = random.Random(4)
    for r_ in range(12):
        z = lo[2] + 0.2 + r_ * 0.145; rk.append(("box", cx, cy, z, w - 0.08, d - 0.08, 0.012))
        for i_ in range(8):
            if bf is None:
                break
            bx = cx - w / 2 + 0.1 + i_ * 0.105
            if len(protos) < 5:
                bo = bf(200 + len(protos)).spawn_asset(nb); protos.append(bo)
            else:
                bo = protos[nb % 5].copy(); bpy.context.scene.collection.objects.link(bo); bo.scale = (1, 1, 1)
            kk = 0.3 / max(max(bo.dimensions), 1e-3); bo.scale = (kk, kk, kk)
            bo.rotation_mode = "XYZ"; bo.rotation_euler = (-math.pi / 2, 0, 0); bo.location = (bx, cy - 0.2, z + 0.05); nb += 1
    try:                                                                # r3: library bottles read beige: wine glass + foil capsule + paper label (S38 styling)
        import liq_shell as _ls
        seen = set()
        for k_, bo in enumerate(protos):
            if bo.data.name in seen or not bo.data.materials:
                continue
            seen.add(bo.data.name); area = {}
            for p_ in bo.data.polygons:
                area[p_.material_index] = area.get(p_.material_index, 0.0) + p_.area
            gi = None
            for i_ in sorted(area, key=area.get, reverse=True):
                m_ = bo.data.materials[i_] if i_ < len(bo.data.materials) else None
                if m_ is not None and not any(nd.type == "TEX_IMAGE" for nd in (m_.node_tree.nodes if m_.use_nodes else [])):
                    bo.data.materials[i_] = _ls._wine_glass(k_); gi = i_; break
            _ls._paper_label(bo.data, gi, k_)
    except Exception as ex:                                             # noqa: BLE001
        stats["brick_cooler_style_error"] = repr(ex)[:120]
    fl.mesh_object("BrickWineCooler", [(frame, [p for p in fr]), (glass, gl), (warm, wm), (rack, rk)], bevel=False)
    _light("ir_brick_cooler", "POINT", (cx, cy + 0.05, lo[2] + h - 0.25), 60, r=0.2); _light("ir_brick_cooler_low", "POINT", (cx, cy + 0.05, lo[2] + 0.6), 40, r=0.2)
    stats["brick_cellar"] = {"bottles": nb}


def _sconce(lo, hi, zc, stats):
    brass = _flat("ir_brick_brass", (0.72, 0.52, 0.25), 0.3, 1.0); shade = _flat("ir_brick_shade", (0.95, 0.9, 0.8), 0.7); glow = _emit("ir_brick_shade_glow", (1.0, 0.78, 0.5), 8.0)
    n = 0; z = lo[2] + 2.3
    spots = [(lo[0] + 0.03, lo[1] + f * (hi[1] - lo[1]), "W") for f in (0.12, 0.92)] + [(lo[0] + f * (hi[0] - lo[0]), lo[1] + 0.03, "S") for f in (0.15, 0.85)]
    for x, y, w_ in spots:
        ox, oy = (0.2, 0) if w_ == "W" else (0, 0.2)
        bm = bmesh.new(); _lathe(bm, [(0.05, 0.0), (0.05, 0.012)], 0, 0, 0, 16)
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2, 3, "Y" if w_ == "W" else "X"), verts=list(bm.verts))
        bmesh.ops.translate(bm, vec=(x, y, z), verts=list(bm.verts)); _obj(f"BrickSconcePlate({n})", bm, brass)
        bm = bmesh.new(); _lathe(bm, [(0.007, 0.0), (0.007, 0.22)], 0, 0, 0, 8)
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2 if w_ == "W" else -math.pi / 2, 3, "Y" if w_ == "W" else "X"), verts=list(bm.verts))
        bmesh.ops.translate(bm, vec=(x, y, z), verts=list(bm.verts)); _obj(f"BrickSconceArm({n})", bm, brass)
        bm = bmesh.new(); _lathe(bm, [(0.12, 0.0), (0.1, 0.08), (0.075, 0.18)], x + ox, y + oy, z - 0.02, 32, pleat=1)
        o = _obj(f"BrickSconceShade({n})", bm, shade); s = o.modifiers.new("t", "SOLIDIFY"); s.thickness = 0.004
        bm = bmesh.new(); _lathe(bm, [(0.0, 0.0), (0.02, 0.02), (0.0, 0.06)], x + ox, y + oy, z + 0.02, 12); _obj(f"BrickSconceBulb({n})", bm, glow)
        _light(f"ir_brick_sconce_{n}", "POINT", (x + ox, y + oy, z + 0.06), 70, r=0.08); n += 1
    import real_assets as ra                                           # big plants in the window corner (NE) and along the right wall
    np_ = 0
    for k, (x, y) in enumerate(((hi[0] - 0.7, hi[1] - 0.7), (hi[0] - 2.0, hi[1] - 0.65), (hi[0] - 0.65, hi[1] - 2.7), (lo[0] + 0.7, hi[1] - 0.7), (hi[0] - 0.65, hi[1] - 5.0))):
        o = ra.hssd(r"croton|money ?tree|pachira|fiddle|ficus|monstera|rubber plant", 30 + k, x, y, lo[2], 0.0, fit=(1.5, 1.5, 2.3), size=(1.6, 2.6), grow=True) or ra.abo("planter", 30 + k, x, y, lo[2], 0.0, fit=(1.2, 1.2, 2.1))
        np_ += 1 if o is not None else 0
    stats["brick_sconce"] = {"sconces": n, "plants": np_}


def _ratio1(lo, hi, zc, stats):
    """Reference-ratio pass (user 2026-10-26): decorated Christmas tree + LED string by the east glazing, varied lush plants (croton, areca palm), an entrance mat, a gridded AC cassette
    + white service pipes + ceiling speakers, two cushions on the cream sofa. Shared helpers in ratio1_common.py."""
    import ratio1_common as rc
    import real_assets as ra
    tx, ty = hi[0] - 1.9, hi[1] - 1.4; got = {}
    for o in list(bpy.data.objects):                                   # the plants that stood where the tree goes
        if o.type == "MESH" and o.name.startswith(("HssdPlant", "Real_hssd")):
            a, b = rc.bb(o)
            if abs((a[0] + b[0]) / 2 - tx) < 1.1 and abs((a[1] + b[1]) / 2 - ty) < 1.1:
                bpy.data.objects.remove(o, do_unlink=True)
    t = rc.tree(ra, tx, ty, lo[2], h=3.0, rad=1.6, seed=7, tag="brick"); got["tree"] = int(t is not None)
    if t is not None:
        rc.flat("ir_brick_treeglow", (1, 0.7, 0.4)); _light("ir_brick_tree_glow", "POINT", (tx, ty, lo[2] + 1.6), 25, (1.0, 0.72, 0.4), r=0.4)
    k = 0
    for i, (x, y, rx_, fit) in enumerate(((1.0, 2.3, r"croton|codiaeum", (1.0, 1.0, 1.5)), (hi[0] - 1.0, 1.2, r"areca|kentia|palm|bird of paradise|strelitzia", (1.4, 1.4, 2.4)),
                                          (hi[0] - 0.9, 5.2, r"croton|codiaeum|calathea|dracaena", (0.9, 0.9, 1.3)))):
        o = ra.hssd(rx_, 70 + i, x, y, lo[2], 0.0, fit=fit, size=(0.6, 3.0), grow=True)
        k += 1 if o is not None else 0
    got["plants"] = k
    d = bpy.data.objects.get("door"); dx = (rc.bb(d)[0][0] + rc.bb(d)[1][0]) / 2 if d is not None else (lo[0] + hi[0]) / 2
    got["mat"] = int(rc.mat(ra, dx, lo[1] + 0.85, lo[2], 1.3, 0.85, tag="brick") is not None)
    for o in list(bpy.data.objects):
        if o.name.startswith("AcCassetteFactory"):
            rc.grille_on(o, "brick")
    rc.cassette(lo[0] + 0.36 * (hi[0] - lo[0]), lo[1] + 0.5 * (hi[1] - lo[1]), zc, size=1.1, drop=0.3, tag="brick")
    rc.pipes_speakers(lo, hi, zc, 2.3, zc - 0.55, tag="brick", speakers=((0.22, 0.28), (0.62, 0.72)))
    cu = 0
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.startswith("AboSofaFactory"):
            a, b = rc.bb(o)
            for j, (u, rgb) in enumerate(((0.22, (0.55, 0.12, 0.08)), (0.78, (0.42, 0.45, 0.2)))):
                m = rc.flat(f"ir_brick_cushion{j}", rgb, 0.85)
                ra.soft(f"BrickSofaCushion({j})", m, a[0] + u * (b[0] - a[0]), (a[1] + b[1]) / 2, a[2] + 0.5, 0.42, 0.14, 0.4, yaw=0.0, seed=j, puff=0.55); cu += 1
    got["cushions"] = cu
    got["plant_fix"] = rc.plant_fix_all()
    stats["brick_ratio1"] = got



def _reference_plants(lo, hi, zc, stats):
    """S39 r8: retain dense real foliage and repair its invalid dielectric response."""
    targets = ("HssdPlant.002", "HssdPlant.003",
               "Real_hssd(HSSD_31c1ec3c3b94241e96e4a7bdb6f3bcca58342d58)",
               "Real_hssd(HSSD_bee09ebd1954d24c3e8835f38e994027d469bd8c)",
               "Real_hssd(HSSD_3ff3032b696bbcadd38e48b79690b5971ee0f26e)",
               "Real_hssd(HSSD_91238b52cec5f006f7dd6a0c7ae462ec065b93a6)")
    fixed = []
    for name in targets:
        o = bpy.data.objects.get(name)
        if o is None:
            continue
        # glTF leaf IOR=0 gives full Fresnel reflection and washes textured leaves white.
        o.data = o.data.copy()
        for slot in o.material_slots:
            if slot.material is None:
                continue
            slot.material = slot.material.copy()
            m = slot.material
            for bs in m.node_tree.nodes if m.use_nodes else ():
                if bs.type != "BSDF_PRINCIPLED":
                    continue
                for key, value in (("IOR", 1.45), ("Specular IOR Level", 0.3),
                                   ("Metallic", 0.0), ("Transmission Weight", 0.0),
                                   ("Emission Strength", 0.0), ("Roughness", 0.62),
                                   ("Coat Weight", 0.0)):
                    sock = bs.inputs.get(key)
                    if sock is not None:
                        for link in list(sock.links):
                            m.node_tree.links.remove(link)
                        sock.default_value = value
        fixed.append(o.name)
    stats["brick_reference_plants"] = fixed



def _reference_cellar(lo, hi, zc, stats):
    """S39 r8: ordinary dark cabinet surfaces, lights only on real LED rails."""
    o = bpy.data.objects.get("BrickWineCooler")
    if o is None:
        return
    o.data = o.data.copy()
    back = _flat("ir_brick_reference_walnut", (0.055, 0.028, 0.012), 0.48)
    fixed = []
    for slot in o.material_slots:
        m = slot.material
        if m is None:
            continue
        name = m.name
        if name.startswith(("ir_brick_cooler_warm", "ir_brick_cooler_walnut")):
            slot.material = back
            fixed.append("nonemissive walnut back")
            continue
        if name.startswith("ir_brick_cooler_glass"):
            m = m.copy()
            slot.material = m
            bs = m.node_tree.nodes.get("Principled BSDF")
            bs.inputs["IOR"].default_value = 1.45
            bs.inputs["Specular IOR Level"].default_value = 0.3
            bs.inputs["Base Color"].default_value = (0.8, 0.84, 0.78, 1)
            bs.inputs["Roughness"].default_value = 0.04
    for name, watts in (("ir_brick_cooler", 8.0), ("ir_brick_cooler_low", 5.0)):
        lamp = bpy.data.objects.get(name)
        if lamp is not None and lamp.type == "LIGHT":
            lamp.data.energy = watts * _gain()
    # Reuse the actual cabinet geometry; thin luminous rails are fixtures.
    if bpy.data.objects.get("BrickReferenceCabinetLED") is None:
        from room_planner import proc_boutique_flagship as fl
        a, b = _bb(o)
        y = a[1] + 0.11
        led = _emit("ir_brick_reference_led", (1.0, 0.65, 0.32), 3.0)
        prims = [("box", x, y, (a[2] + b[2]) / 2, 0.008, 0.012, b[2] - a[2] - 0.2)
                 for x in (a[0] + 0.07, b[0] - 0.07)]
        fl.mesh_object("BrickReferenceCabinetLED", [(led, prims)], bevel=False)
    stats["brick_reference_cellar"] = fixed


def _reference_cabinet_top(lo, hi, zc, stats):
    """S39 reference miniature parasol and real cabinet-top decor."""
    if bpy.data.objects.get("BrickCabinetParasol") is not None:
        return
    cabinet = bpy.data.objects.get("BrickWineCooler")
    if cabinet is None:
        return
    import real_assets as ra
    from room_planner import proc_boutique_flagship as fl
    a, b = _bb(cabinet)
    cx, cy, top = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, b[2] + 0.003
    made = []
    specs = (("box", "HSSD_695e49c5fe19b4a0e70078f755a2dece95533d86", -0.17, 0.03, (0.24, 0.18, 0.15)),
             ("flowers", "HSSD_1182b246f9dc763f898cf5a47feb003f8905d289", 0.09, -0.10, (0.19, 0.19, 0.30)),
             ("plant", "HSSD_52e54d4aedff229ec50eefe25bd168c60141c37f", 0.27, 0.08, (0.19, 0.19, 0.24)))
    for label, rx, dx, dy, fit in specs:
        o = ra.hssd(rx, 0, cx + dx, cy + dy, top, 0.0, fit=fit, grow=True)
        if o is None:
            raise RuntimeError("Missing real cabinet-top asset: " + label)
        o.name = "BrickCabinetTop_" + label
        o.data = o.data.copy()
        for slot in o.material_slots:
            if slot.material is None:
                continue
            slot.material = slot.material.copy()
            if not slot.material.use_nodes:
                continue
            for bs in slot.material.node_tree.nodes:
                if bs.type != "BSDF_PRINCIPLED":
                    continue
                bs.inputs["IOR"].default_value = 1.45
                bs.inputs["Emission Strength"].default_value = 0.0
                bs.inputs["Transmission Weight"].default_value = 0.0
                bs.inputs["Metallic"].default_value = 0.0
        made.append(o.name)
    # A miniature umbrella is curved cloth over actual radial ribs, not a proxy box.
    x, y = cx - 0.27, cy - 0.04
    cloth = _flat("ir_brick_parasol_cloth", (0.75, 0.69, 0.58), 0.85)
    wood = _flat("ir_brick_parasol_wood", (0.22, 0.12, 0.045), 0.5)
    bm = bmesh.new()
    _lathe(bm, [(0.0, 0.68), (0.07, 0.67), (0.17, 0.63), (0.27, 0.55),
                (0.285, 0.535)], x, y, top, seg=48)
    canopy = _obj("BrickCabinetParasol", bm, cloth)
    solid = canopy.modifiers.new("FabricThickness", "SOLIDIFY")
    solid.thickness = 0.0015
    ribs = [("cyl", (x, y, top + 0.02), (x, y, top + 0.68), 0.007, 12)]
    for i in range(12):
        angle = 2 * math.pi * i / 12
        ribs.append(("cyl", (x, y, top + 0.65),
                     (x + 0.27 * math.cos(angle), y + 0.27 * math.sin(angle), top + 0.548),
                     0.002, 6))
    fl.mesh_object("BrickCabinetParasolRibs", [(wood, ribs)], bevel=False)
    stats["brick_reference_cabinet_top"] = made + [canopy.name]

def _reference_picture_lights(lo, hi, zc, stats):
    """S39 r9: picture-light assemblies must clear the photograph frames."""
    from mathutils import Vector
    moved = []
    for k in range(3):
        frame = bpy.data.objects.get(f"BrickPrintFrame({k})")
        bar = bpy.data.objects.get(f"BrickPicLightBar({k})")
        if frame is None or bar is None:
            continue
        frame_top = _bb(frame)[1][2]
        bar_bottom = _bb(bar)[0][2]
        dz = max(0.0, frame_top + 0.12 - bar_bottom)
        if dz < 0.001:
            continue
        for prefix in ("BrickPicLightBar", "BrickPicLightArm", "BrickPicLightPlate"):
            obj = bpy.data.objects.get(f"{prefix}({k})")
            if obj is not None:
                obj.location.z += dz
        lamp = bpy.data.objects.get(f"ir_brick_pic_{k}")
        if lamp is not None:
            lamp.location.z += dz
            target = Vector((lo[0] + 0.08, lamp.location.y, frame_top - 0.45))
            lamp.rotation_euler = (target - lamp.location).to_track_quat('-Z', 'Y').to_euler()
        moved.append({"index": k, "rise_m": round(dz, 4), "frame_top_m": round(frame_top, 4)})
    stats["brick_reference_picture_lights"] = moved


def _reference_table_grain(lo, hi, zc, stats):
    """S39 r10: scanned continuous dark wood on dining tops, not supports."""
    from pathlib import Path
    scan = Path("/bean/ir_pbr_assets/texturecan_environment_merged_v1/texturecan/texturecan_wood_0035")
    paths = [scan / name for name in ("base_color.jpg", "roughness.jpg", "normal_gl.png")]
    if not all(path.is_file() for path in paths):
        raise FileNotFoundError("S39 tabletop wood scan is incomplete")
    images = [bpy.data.images.load(str(path), check_existing=True) for path in paths]
    images[0].colorspace_settings.name = "sRGB"
    images[1].colorspace_settings.name = "Non-Color"
    images[2].colorspace_settings.name = "Non-Color"
    # Linear luminance measured from this sRGB scan; avoid raw image-buffer colour space ambiguity.
    mean = .01930676
    made = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.name.startswith("BrickTable("):
            continue
        if obj.get("pkg_h_S39c_table_grain"):
            continue
        a, b = _bb(obj)
        along_y = b[1] - a[1] > b[0] - a[0]
        name = "ir_brick_reference_table_wood_" + ("Y" if along_y else "X")
        mat = bpy.data.materials.get(name)
        if mat is None:
            mat = bpy.data.materials.new(name)
            mat.use_nodes = True
            mat["weathered"] = True
            nodes, links = mat.node_tree.nodes, mat.node_tree.links
            bs = nodes.get("Principled BSDF")
            bs.inputs["Metallic"].default_value = 0
            bs.inputs["Emission Strength"].default_value = 0
            bs.inputs["Coat Weight"].default_value = .20
            bs.inputs["Coat Roughness"].default_value = .22
            geo = nodes.new("ShaderNodeNewGeometry")
            sep = nodes.new("ShaderNodeSeparateXYZ")
            links.new(geo.outputs["Position"], sep.inputs["Vector"])
            uv = nodes.new("ShaderNodeCombineXYZ")
            links.new(sep.outputs["Y" if along_y else "X"], uv.inputs["X"])
            links.new(sep.outputs["X" if along_y else "Y"], uv.inputs["Y"])
            maps = []
            for image in images:
                tex = nodes.new("ShaderNodeTexImage")
                tex.image = image
                tex.extension = "REPEAT"
                links.new(uv.outputs["Vector"], tex.inputs["Vector"])
                maps.append(tex)
            bw = nodes.new("ShaderNodeRGBToBW")
            links.new(maps[0].outputs["Color"], bw.inputs["Color"])
            variation = nodes.new("ShaderNodeMapRange")
            variation.clamp = True
            variation.inputs["From Min"].default_value = mean * .6
            variation.inputs["From Max"].default_value = mean * 1.4
            variation.inputs["To Min"].default_value = .25
            variation.inputs["To Max"].default_value = 1.9
            links.new(bw.outputs["Val"], variation.inputs["Value"])
            color = nodes.new("ShaderNodeMixRGB")
            color.blend_type = "MULTIPLY"
            color.inputs[0].default_value = 1
            color.inputs[1].default_value = (.13, .038, .017, 1)
            links.new(variation.outputs["Result"], color.inputs[2])
            links.new(color.outputs["Color"], bs.inputs["Base Color"])
            rough = nodes.new("ShaderNodeMapRange")
            rough.inputs["To Min"].default_value = .28
            rough.inputs["To Max"].default_value = .42
            links.new(maps[1].outputs["Color"], rough.inputs["Value"])
            links.new(rough.outputs["Result"], bs.inputs["Roughness"])
            bump = nodes.new("ShaderNodeBump")
            bump.inputs["Strength"].default_value = .2
            bump.inputs["Distance"].default_value = .00025
            links.new(bw.outputs["Val"], bump.inputs["Height"])
            links.new(bump.outputs["Normal"], bs.inputs["Normal"])
            mat["scan"] = str(scan)
            mat["grain_world_tile_m"] = 1.0
        mesh = obj.data.copy()
        obj.data = mesh
        mesh.materials.append(mat)
        idx = len(mesh.materials) - 1
        changed = 0
        for face in mesh.polygons:
            center = obj.matrix_world @ face.center
            if center.z >= b[2] - .065:
                face.material_index = idx
                changed += 1
        if not changed:
            raise ValueError("No tabletop faces found: " + obj.name)
        obj["pkg_h_S39c_table_grain"] = 1
        made.append({"object": obj.name, "top_faces": changed, "grain_axis": "Y" if along_y else "X"})
    stats["brick_reference_table_grain"] = made


def _reference_pendant_metal(lo, hi, zc, stats):
    """S39d cafe-021: textured brown metal domes with nonemissive copper liners."""
    from mathutils import Vector
    made = []
    for prefix, label, dark, light, roughness in (
        ("BrickDome(", "outer", (.030, .016, .009), (.105, .058, .025), .40),
        ("BrickDomeLiner(", "inner", (.30, .095, .025), (.62, .29, .09), .29),
    ):
        targets = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(prefix)]
        if not targets:
            continue
        name = "ir_pkg_h_S39d_pendant_" + label
        material = bpy.data.materials.get(name)
        if material is None:
            material = bpy.data.materials.new(name)
            material.use_nodes = True
            nodes, links = material.node_tree.nodes, material.node_tree.links
            shader = nodes.get("Principled BSDF")
            shader.inputs["Metallic"].default_value = 1.0
            shader.inputs["Roughness"].default_value = roughness
            shader.inputs["Emission Strength"].default_value = 0.0
            geometry = nodes.new("ShaderNodeNewGeometry")
            broad = nodes.new("ShaderNodeTexNoise")
            broad.inputs["Scale"].default_value = 34.0
            broad.inputs["Detail"].default_value = 3.0
            broad.inputs["Roughness"].default_value = .7
            links.new(geometry.outputs["Position"], broad.inputs["Vector"])
            color = nodes.new("ShaderNodeMixRGB")
            color.blend_type = "MIX"
            color.inputs[1].default_value = (*dark, 1)
            color.inputs[2].default_value = (*light, 1)
            links.new(broad.outputs["Fac"], color.inputs[0])
            links.new(color.outputs[0], shader.inputs["Base Color"])
            finish = nodes.new("ShaderNodeMapRange")
            finish.inputs["From Min"].default_value = 0
            finish.inputs["From Max"].default_value = 1
            finish.inputs["To Min"].default_value = roughness - .08
            finish.inputs["To Max"].default_value = roughness + .09
            links.new(broad.outputs["Fac"], finish.inputs["Value"])
            links.new(finish.outputs["Result"], shader.inputs["Roughness"])
            pores = nodes.new("ShaderNodeTexNoise")
            pores.inputs["Scale"].default_value = 850.0
            pores.inputs["Detail"].default_value = 2.0
            links.new(geometry.outputs["Position"], pores.inputs["Vector"])
            bump = nodes.new("ShaderNodeBump")
            bump.inputs["Distance"].default_value = .00015
            bump.inputs["Strength"].default_value = .22
            links.new(pores.outputs["Fac"], bump.inputs["Height"])
            links.new(bump.outputs["Normal"], shader.inputs["Normal"])
            material["weathered"] = True
            material["pkg_h_S39d"] = True
        for obj in targets:
            if len(obj.data.materials) == 1 and obj.data.materials[0] == material:
                continue
            obj.data = obj.data.copy()
            obj.data.materials.clear()
            obj.data.materials.append(material)
            for face in obj.data.polygons:
                face.material_index = 0
            made.append(obj.name)
    stats["brick_reference_pendant_metal"] = made


def _clean(lo, hi, zc, stats):
    """Track spots and the small round ceiling fixture leave (the domes / bulbs replace them)."""
    k = 0
    for o in list(bpy.data.objects):
        if o.name.startswith(("TrackSpotFactory", "TrackRailFactory", "AboCeilingFixtureFactory")) or (o.type == "LIGHT" and o.name.startswith(("TrackSpot", "AboCeiling"))):
            bpy.data.objects.remove(o, do_unlink=True); k += 1
    stats["brick_clean"] = k


def apply(stats):
    sc = bpy.context.scene
    if sc.get("ir_brick_shell") or bpy.data.objects.get(f"{ROOM}.floor") is None:
        return 0
    skip = set((os.environ.get("ROOM_BRICK_SKIP") or "").split(",")); lo, hi, zc = _room(); n = 0
    for key, fn in (("clean", _clean), ("glaze", _glaze), ("brick", _brick), ("floor", _floor), ("furn", _furn), ("pendants", _pendants), ("banq", _banq), ("cellar", _cellar), ("sconce", _sconce), ("ratio1", _ratio1)):
        if key in skip:
            continue
        try:
            bpy.context.view_layer.update(); fn(lo, hi, zc, stats); n += 1
        except Exception as ex:                                        # noqa: BLE001 -- a failing part must not sink the kit stage
            import traceback; traceback.print_exc()
            stats[f"brick_{key}_error"] = repr(ex)[:160]
    import ratio1_plants, ratio1_checkout; ratio1_plants.apply(stats); ratio1_checkout.apply(stats)
    try:
        bpy.context.view_layer.update()
        _reference_plants(lo, hi, zc, stats)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        stats["brick_reference_plants_error"] = repr(ex)[:160]
    try:
        bpy.context.view_layer.update()
        _reference_cellar(lo, hi, zc, stats)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        stats["brick_reference_cellar_error"] = repr(ex)[:160]
    try:
        bpy.context.view_layer.update()
        _reference_cabinet_top(lo, hi, zc, stats)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        stats["brick_reference_cabinet_top_error"] = repr(ex)[:160]
    try:
        bpy.context.view_layer.update()
        _reference_picture_lights(lo, hi, zc, stats)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        stats["brick_reference_picture_lights_error"] = repr(ex)[:160]
    try:
        bpy.context.view_layer.update()
        _reference_table_grain(lo, hi, zc, stats)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        stats["brick_reference_table_grain_error"] = repr(ex)[:160]
    try:
        bpy.context.view_layer.update()
        _reference_pendant_metal(lo, hi, zc, stats)
    except Exception as ex:
        import traceback
        traceback.print_exc()
        stats["brick_reference_pendant_metal_error"] = repr(ex)[:160]
    try:
        import real_assets as ra
        ra.report(stats, "brick")
    except Exception:                                                  # noqa: BLE001
        pass
    sc["ir_brick_shell"] = 1
    return n
