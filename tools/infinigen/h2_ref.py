"""H2 hotel floor reference-gap pass (kit stage, idempotent via scene["ir_h2_ref"]); ROOM_H2_REF=1 enables every part, ROOM_H2_REF_SKIP=<comma list> switches parts off.
Ticket H2-REF (out/vlm_queue/floorH2_hotel_r22/refs_answer.json; refs floor_plans_v3/HOTEL). Rooms: bedroom_0/0..3 (grey, green, blue, pink), bathroom_0/0..3 north of them, hallway_0/0 south.
bed      SoftBed cover / bolster / runner / cushions cut off; a soft mattress, a lofted white duvet that drapes over the sides, 4 stacked white pillows, 2 accent cushions and a broad foot throw
         in the room colour (kit bed_throw_by_room); grey upholstered headboard band; fine vertical oak slats on the headboard wall
carpet   pale beige mottled broadloom in the bedrooms and the corridor; the patterned Abo rugs become one large pale rug under each bed
window   rooms without a window (0/1, 0/2) get a framed window with an exterior view plate on the wall opposite the bed head; every room gets a dark outer drape + sheer pair;
         the bathroom frosted windows become clear glass (the exterior cards are already outside)
furn     coordinated light-oak nightstands with brass / cream-shade lamps (lit), upholstered desk chairs instead of the office chairs, a desk under the TV where none, a potted plant where none
corr     full-height framed window + planter at both corridor ends, oak architraves round the room doors, large neutral abstract prints, recessed warm downlights instead of the surface battens
bath     beige stone walls, a geometric accent panel on the tub wall, a geometric patterned floor in the room colour, an oak vanity front, a backlit mirror, folded towels
Lights are scaled by ROOM_H2_REF_LIGHT (default 1.0; the scene's own lamps are ~90 W points).
"""
from __future__ import annotations

import math
import os
import random

import bpy
import real_assets as ra
import bmesh
from mathutils import Matrix, Vector

ROOMS = ("bedroom_0/0", "bedroom_0/1", "bedroom_0/2", "bedroom_0/3")
BATHS = ("bathroom_0/0", "bathroom_0/1", "bathroom_0/2", "bathroom_0/3")
HALL = "hallway_0/0"
ACCENT = {"bedroom_0/0": (0.22, 0.22, 0.235), "bedroom_0/1": (0.122, 0.164, 0.062), "bedroom_0/2": (0.03, 0.074, 0.184), "bedroom_0/3": (0.56, 0.198, 0.19)}
VIEW = "/jarvis/project/robomituba/data/venue_refs/bigglass_cards/src/{}.png"


def _bb(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def _room(n):
    f = bpy.data.objects.get(f"{n}.floor")
    return _bb(f) if f is not None else (None, None)


def _in(o, lo, hi):
    b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
    return lo[0] < cx < hi[0] and lo[1] < cy < hi[1]


def _objs(prefix, lo, hi):
    return [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(prefix) and _in(o, lo, hi)]


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


def _noise(name, c1, c2, scale, rough=0.8, detail=6.0, lo=0.3, hi=0.7):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = _flat(name, c1, rough); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); t = N.new("ShaderNodeTexNoise"); t.inputs["Scale"].default_value = scale; t.inputs["Detail"].default_value = detail
    mr = N.new("ShaderNodeMapRange"); mr.inputs["From Min"].default_value = lo; mr.inputs["From Max"].default_value = hi
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.inputs["A"].default_value = (*c1, 1); mx.inputs["B"].default_value = (*c2, 1)
    L.new(tc.outputs["Object"], t.inputs["Vector"]); L.new(t.outputs["Fac"], mr.inputs["Value"]); L.new(mr.outputs["Result"], mx.inputs["Factor"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
    return m


def _cement(name, accent, cell=0.2, wall_x=False, grey=False):
    """Ornamental cement-tile patchwork (r23 review): 20 cm tiles, each tile its own motif (diamond / medallion / square-in-square bands, picked per tile from a white-noise
    hash of the tile index) and its own colourway (room accent, cream, slate blue, terracotta, charcoal), 3 mm grey grout."""
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = _flat(name, accent, 0.5); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    def mth(op, a_, b_=None):
        n = N.new("ShaderNodeMath"); n.operation = op
        for i, s_ in enumerate((a_, b_)):
            if s_ is None:
                continue
            if isinstance(s_, (int, float)):
                n.inputs[i].default_value = s_
            else:
                L.new(s_, n.inputs[i])
        return n.outputs[0]
    def mixc(f, c0, c1):
        n = N.new("ShaderNodeMix"); n.data_type = "RGBA"
        for k_, c in (("A", c0), ("B", c1)):
            if isinstance(c, tuple):
                n.inputs[k_].default_value = (*c, 1)
            else:
                L.new(c, n.inputs[k_])
        L.new(f, n.inputs["Factor"]); return n.outputs["Result"]
    tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1 / cell, 1 / cell, 1.0 / cell); L.new(tc.outputs["Object"], mp.inputs["Vector"])
    if wall_x:                                                       # a panel on an x = const wall: the tile grid runs in (z, y)
        mp.inputs["Rotation"].default_value = (0.0, math.pi / 2, 0.0)
    fl_ = N.new("ShaderNodeVectorMath"); fl_.operation = "FLOOR"; L.new(mp.outputs["Vector"], fl_.inputs[0])
    wn = N.new("ShaderNodeTexWhiteNoise"); wn.noise_dimensions = "3D"; L.new(fl_.outputs[0], wn.inputs["Vector"])
    sp = N.new("ShaderNodeSeparateColor"); L.new(wn.outputs["Color"], sp.inputs["Color"])
    fr = N.new("ShaderNodeVectorMath"); fr.operation = "FRACTION"; L.new(mp.outputs["Vector"], fr.inputs[0])
    sb = N.new("ShaderNodeVectorMath"); sb.operation = "SUBTRACT"; sb.inputs[1].default_value = (0.5, 0.5, 0.0); L.new(fr.outputs[0], sb.inputs[0])
    se = N.new("ShaderNodeSeparateXYZ"); L.new(sb.outputs[0], se.inputs[0])
    ax, ay = mth("ABSOLUTE", se.outputs[0]), mth("ABSOLUTE", se.outputs[1])
    d_dia = mth("ADD", ax, ay); d_cir = mth("SQRT", mth("ADD", mth("MULTIPLY", ax, ax), mth("MULTIPLY", ay, ay))); d_sq = mth("MAXIMUM", ax, ay)
    r1 = sp.outputs[0]
    d = mth("ADD", mth("MULTIPLY", d_dia, mth("LESS_THAN", r1, 0.34)), mth("ADD", mth("MULTIPLY", d_cir, mth("MULTIPLY", mth("GREATER_THAN", r1, 0.34), mth("LESS_THAN", r1, 0.67))), mth("MULTIPLY", d_sq, mth("GREATER_THAN", r1, 0.67))))
    band = mth("GREATER_THAN", mth("SINE", mth("MULTIPLY", d, 31.4)), 0.15)                # concentric motif bands
    core = mth("LESS_THAN", d, 0.12)
    cr = N.new("ShaderNodeValToRGB"); cr.color_ramp.interpolation = "CONSTANT"; L.new(sp.outputs[1], cr.inputs["Fac"])
    pal = ((0.55, 0.56, 0.58), (0.36, 0.38, 0.41), (0.74, 0.74, 0.73), (0.2, 0.2, 0.21)) if grey else (accent, (0.26, 0.36, 0.48), (0.66, 0.36, 0.24), (0.16, 0.16, 0.17))     # r24 review: grey / white like the REF, not coral
    el = cr.color_ramp.elements; el[0].position = 0.0; el[0].color = (*pal[0], 1); el[1].position = 0.3; el[1].color = (*pal[1], 1)
    for pos, col in ((0.55, pal[2]), (0.8, pal[3])):
        e_ = el.new(pos); e_.color = (*col, 1)
    cream = (0.9, 0.87, 0.8)
    col = mixc(band, cream, cr.outputs["Color"]); col = mixc(core, col, cr.outputs["Color"])
    grout = mth("GREATER_THAN", d_sq, 0.485); col = mixc(grout, col, (0.55, 0.54, 0.52))
    L.new(col, b.inputs["Base Color"])
    return m


def _diamond(name, c1, c2, cell=0.2):
    """Geometric cement-tile look: a 45-degree checker in object space, cell `cell` m."""
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = _flat(name, c1, 0.45); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); mp.inputs["Rotation"].default_value = (0, 0, math.radians(45)); mp.inputs["Scale"].default_value = (1 / cell, 1 / cell, 1 / cell)
    ck = N.new("ShaderNodeTexChecker"); ck.inputs["Scale"].default_value = 1.0; ck.inputs["Color1"].default_value = (*c1, 1); ck.inputs["Color2"].default_value = (*c2, 1)
    ck2 = N.new("ShaderNodeTexChecker"); ck2.inputs["Scale"].default_value = 3.0; ck2.inputs["Color1"].default_value = (1, 1, 1, 1); ck2.inputs["Color2"].default_value = (0.82, 0.82, 0.8, 1)
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs["Factor"].default_value = 1.0
    L.new(tc.outputs["Object"], mp.inputs["Vector"]); L.new(mp.outputs["Vector"], ck.inputs["Vector"]); L.new(mp.outputs["Vector"], ck2.inputs["Vector"])
    L.new(ck.outputs["Color"], mx.inputs["A"]); L.new(ck2.outputs["Color"], mx.inputs["B"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
    return m


def _view_mat(kind, strength=1.4):
    """Emissive exterior photo for a window pane (bigglass_cards/src/<kind>.png), unit UVs from rooftop_shell._quads."""
    name = f"ir_h2_view_{kind}"
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = _flat(name, (0.7, 0.75, 0.8), 0.5); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (0.35, 0.8, 1.0); mp.inputs["Location"].default_value = (0.3, 0.1, 0.0)
    im = N.new("ShaderNodeTexImage"); im.image = bpy.data.images.load(VIEW.format(kind), check_existing=True); im.extension = "EXTEND"
    L.new(tc.outputs["UV"], mp.inputs["Vector"]); L.new(mp.outputs["Vector"], im.inputs["Vector"])
    L.new(im.outputs["Color"], b.inputs["Base Color"]); L.new(im.outputs["Color"], b.inputs["Emission Color"]); b.inputs["Emission Strength"].default_value = strength
    return m


def _light(name, kind, loc, energy, rgb=(1.0, 0.82, 0.62), size=0.1):
    ld = bpy.data.lights.new(name, kind); ld.energy = energy * float(os.environ.get("ROOM_H2_REF_LIGHT") or 1.0); ld.color = rgb
    if kind == "SPOT":
        ld.spot_size = math.radians(90); ld.spot_blend = 0.7; ld.shadow_soft_size = 0.05
    elif kind == "POINT":
        ld.shadow_soft_size = size
    else:
        ld.size = size
    o = bpy.data.objects.new(name, ld); o.location = loc; bpy.context.scene.collection.objects.link(o)
    return o


def _soft(name, mat, cx, cy, cz, sx, sy, sz, yaw=0.0, bevel=0.05, bump=0.0, seed=0):
    """A soft rounded pillow / cushion / mattress top: real_assets.soft (shared with hotel5_shell; inflated profile + subdivision, no sharp corners)."""
    return ra.soft(name, mat, cx, cy, cz, sx, sy, sz, yaw=yaw, seed=seed, lump=bump or 0.004, puff=0.08 if "Mattress" in name else 0.6)


def _drape(name, mat, x0, x1, y0, y1, ztop, hang, along_x, thick=0.05, seed=0):
    """Moved to real_assets.drape (shared with hotel5_shell)."""
    return ra.drape(name, mat, x0, x1, y0, y1, ztop, hang, along_x, thick=thick, seed=seed)


def _pleats(name, mat, axis, line, a0, a1, z0, z1, depth=0.04, pitch=0.12):
    """A pleated curtain panel hanging in the plane `line` (axis 0: along x at y = line, 1: along y at x = line), a0..a1 along it."""
    bm = bmesh.new(); n = max(4, int((a1 - a0) / (pitch / 4))); rows = []
    for zz in (z0, z1):
        row = []
        for i in range(n + 1):
            a = a0 + (a1 - a0) * i / n; off = depth * 0.5 * math.sin(2 * math.pi * (a - a0) / pitch)
            row.append(bm.verts.new((a, line + off, zz) if axis == 0 else (line + off, a, zz)))
        rows.append(row)
    for i in range(n):
        bm.faces.new((rows[0][i], rows[0][i + 1], rows[1][i + 1], rows[1][i]))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    o.modifiers.new("thick", "SOLIDIFY").thickness = 0.008
    return o


def _cut_slots(o, names):
    """Delete the faces of `o` whose material is one of `names` (a copy of the mesh, so other instances keep theirs)."""
    me = o.data.copy(); o.data = me
    bm = bmesh.new(); bm.from_mesh(me)
    idx = {i for i, m in enumerate(me.materials) if m is not None and m.name in names}
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index in idx], context="FACES")
    bm.to_mesh(me); bm.free()


def _accent(room):
    try:
        from room_planner import proc_assets as pa
        rgb = (pa.STYLE.get("bed_throw_by_room") or {}).get(room)
    except Exception:                                              # noqa: BLE001
        rgb = None
    return tuple(rgb) if rgb else ACCENT.get(room, (0.3, 0.3, 0.3))


def _bed_frame(bed):
    """(cx, cy, along_x, head_sign, L, W, mattress top z): the head is the side where the SoftBed's cream headboard faces sit."""
    b0, b1 = _bb(bed); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
    along_x = (b1[0] - b0[0]) >= (b1[1] - b0[1])
    me = bed.data; mw = bed.matrix_world; hx = hy = n = 0.0
    ci = [i for i, m in enumerate(me.materials) if m is not None and m.name.startswith("ir_sfb_cream")]
    for p in me.polygons:
        if p.material_index in ci:
            c = mw @ p.center; hx += c.x; hy += c.y; n += 1
    if n:
        hx /= n; hy /= n
    head = (1 if hx > cx else -1) if along_x else (1 if hy > cy else -1)
    L, W = ((b1[0] - b0[0]), (b1[1] - b0[1])) if along_x else ((b1[1] - b0[1]), (b1[0] - b0[0]))
    return cx, cy, along_x, head, L, W, b0, b1


def _p(cx, cy, along_x, a, b):
    """bed-local (a along the bed axis, b across) -> world xy."""
    return (cx + a, cy + b) if along_x else (cx + b, cy + a)


def _bed(stats):
    white = _flat("ir_h2_duvet", (0.93, 0.93, 0.91), 0.85); pill = _flat("ir_h2_pillow", (0.95, 0.95, 0.94), 0.85); matt = _flat("ir_h2_mattress", (0.9, 0.9, 0.88), 0.85)
    head_mat = _flat("ir_h2_headboard", (0.42, 0.42, 0.43), 0.9); oak = _noise("ir_h2_oak", (0.62, 0.45, 0.27), (0.5, 0.35, 0.2), 30.0, 0.5)
    n = 0
    for rn in ROOMS:
        lo, hi = _room(rn)
        if lo is None:
            continue
        acc = _accent(rn); thr = _flat(f"ir_h2_throw_{rn[-1]}", acc, 0.9); cush = _flat(f"ir_h2_cush_{rn[-1]}", tuple(min(1, c * 1.15) for c in acc), 0.9)
        for bed in _objs("SoftBedFactory", lo, hi):
            cx, cy, ax, hd, L, W, b0, b1 = _bed_frame(bed)
            _cut_slots(bed, {m.name for m in bed.data.materials if m and not m.name.startswith(("ir_sfb_oak", "ir_sfb_cream"))})
            for i, m in enumerate(bed.data.materials):
                if m and m.name.startswith("ir_sfb_cream"):
                    bed.data.materials[i] = head_mat
            fz = lo[2]; zt = fz + 0.62; hb = 0.12                     # mattress top; headboard depth eaten at the head end
            body = L - hb
            mc = _p(cx, cy, ax, -hd * hb / 2, 0)
            _soft(f"H2Mattress({rn})", matt, mc[0], mc[1], fz + 0.47, *((body - 0.04, W - 0.06) if ax else (W - 0.06, body - 0.04)), 0.3, bevel=0.04)
            dc = _p(cx, cy, ax, -hd * (hb / 2 + 0.06), 0)               # duvet from 0.3 m below the pillows to past the foot
            dl = body - 0.25
            x0, x1 = (dc[0] - dl / 2, dc[0] + dl / 2) if ax else (dc[0] - W / 2, dc[0] + W / 2)
            y0, y1 = (dc[1] - W / 2, dc[1] + W / 2) if ax else (dc[1] - dl / 2, dc[1] + dl / 2)
            _drape(f"H2Duvet({rn})", white, x0, x1, y0, y1, zt + 0.07, 0.3, ax, thick=0.06, seed=n)
            tc = _p(cx, cy, ax, -hd * (L / 2 - 0.42), 0)               # broad foot throw, darker, hanging over both sides
            tx0, tx1 = (tc[0] - 0.28, tc[0] + 0.28) if ax else (tc[0] - W / 2 - 0.02, tc[0] + W / 2 + 0.02)
            ty0, ty1 = (tc[1] - W / 2 - 0.02, tc[1] + W / 2 + 0.02) if ax else (tc[1] - 0.28, tc[1] + 0.28)
            _drape(f"H2Throw({rn})", thr, tx0, tx1, ty0, ty1, zt + 0.145, 0.36, ax, thick=0.025, seed=n + 7)
            for k, (aa, bb_, zz, tilt) in enumerate(((L / 2 - hb - 0.22, -W / 4, zt + 0.1, 0.0), (L / 2 - hb - 0.22, W / 4, zt + 0.1, 0.0),
                                                     (L / 2 - hb - 0.3, -W / 4, zt + 0.24, 0.0), (L / 2 - hb - 0.3, W / 4, zt + 0.24, 0.0))):
                pc = _p(cx, cy, ax, hd * aa, bb_)
                _soft(f"H2Pillow({rn}|{k})", pill, pc[0], pc[1], zz, *((0.2, 0.62) if ax else (0.62, 0.2)), 0.14 if k < 2 else 0.16, bevel=0.06, bump=0.008, seed=k + n)
            for k, bb_ in enumerate((-0.2, 0.2)):
                pc = _p(cx, cy, ax, hd * (L / 2 - hb - 0.5), bb_)
                _soft(f"H2Cushion({rn}|{k})", cush, pc[0], pc[1], zt + 0.24, *((0.14, 0.42) if ax else (0.42, 0.14)), 0.34, yaw=0.12 * (1 if k else -1), bevel=0.06, bump=0.006, seed=9 + k)
            # fine vertical oak slats on the headboard wall, bed width + nightstands
            if ax:
                wx = hi[0] - 0.012 if hd > 0 else lo[0] + 0.012; ya, yb = cy - W / 2 - 0.8, cy + W / 2 + 0.8
                slats = [("box", wx - hd * 0.015, ya + 0.045 * i, (fz + 2.62) / 2, 0.03, 0.03, 2.62 - fz) for i in range(int((yb - ya) / 0.045))]
            else:
                wy = hi[1] - 0.012 if hd > 0 else lo[1] + 0.012; xa, xb = cx - W / 2 - 0.8, cx + W / 2 + 0.8
                slats = [("box", xa + 0.045 * i, wy - hd * 0.015, (fz + 2.62) / 2, 0.03, 0.03, 2.62 - fz) for i in range(int((xb - xa) / 0.045))]
            _fl().mesh_object(f"H2Slats({rn})", [(oak, slats)], bevel=False)
            n += 1
    stats["h2_beds"] = n


def _grey_rug(seed, x, y, z, yaw, fit):
    """An ABO rug whose name says grey / woven / sisal / flatweave / textured (not a runner or shag); None if the pool is empty."""
    import re
    import abo_assets
    pool = [e for e in abo_assets.entries() if e.get("product_type") == "RUG" and re.search(r"gr[ae]y|silver|charcoal", e.get("name", ""), re.I)
            and re.search(r"woven|sisal|flatweave|textured|jute|wool", e.get("name", ""), re.I) and not re.search(r"runner|shag|floral|medallion|damask|moroccan|trellis|vintage|plaid|motion|ornate|kilim|tribal|persian|oriental|geometric|abstract|stripe|multi", e.get("name", ""), re.I)]
    if not pool:
        return ra.abo("bigrug", seed, x, y, z, yaw, fit=fit)
    try:
        e = abo_assets.pick(random.Random(seed), pool); o = abo_assets._import(e, f"Real_greyrug({e['id']})")
    except Exception:                                             # noqa: BLE001
        return ra.abo("bigrug", seed, x, y, z, yaw, fit=fit)
    return ra._stand(o, x, y, z, yaw - math.atan2(ra.ABO_FRONT[1], ra.ABO_FRONT[0]), fit, grow=True)


def _carpet(stats):
    m = _noise("ir_h2_broadloom", (0.72, 0.66, 0.57), (0.62, 0.56, 0.48), 3.5, 0.95, detail=10.0)
    nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    if not m.get("pile"):                                          # fine pile bump
        tc = N.new("ShaderNodeTexCoord"); t = N.new("ShaderNodeTexNoise"); t.inputs["Scale"].default_value = 400.0; bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 0.15
        L.new(tc.outputs["Object"], t.inputs["Vector"]); L.new(t.outputs["Fac"], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"]); m["pile"] = 1
    for rn in ROOMS + (HALL,):
        f = bpy.data.objects.get(f"{rn}.floor")
        if f is not None:
            for sl in f.material_slots:
                sl.material = m
    rug = _noise("ir_h2_rug", (0.8, 0.76, 0.68), (0.7, 0.66, 0.58), 14.0, 0.95, detail=4.0, lo=0.45, hi=0.55)
    bord = _flat("ir_h2_rug_border", (0.6, 0.55, 0.47), 0.95); k = 0
    for rn in ROOMS:
        lo, hi = _room(rn)
        if lo is None:
            continue
        old = _objs("AboRugFactory", lo, hi)
        if old and os.environ.get("ROOM_H2_RUG_KEEP") == "1":            # audit H2-1: keep the layout's ABO rug as is
            continue
        for o_ in old:                                                   # r25: the layout's ABO rug was ~1.6 x 1.3 m, hidden under the bed: a 2.2 x 3.0 m one from the head side to past the foot
            bpy.data.objects.remove(o_, do_unlink=True)
        for bed in _objs("SoftBedFactory", lo, hi):
            cx, cy, ax, hd, L_, W, b0, b1 = _bed_frame(bed)
            c = _p(cx, cy, ax, -hd * 0.8, 0); rl, rw = 3.2, 2.2         # r28: centre shifted 0.25 m toward the foot so ~1.2 m of rug shows past the duvet
            sx, sy = (rl, rw) if ax else (rw, rl)
            sx = min(sx, hi[0] - lo[0] - 0.3); sy = min(sy, hi[1] - lo[1] - 0.3)
            for try_ in range(8):                                        # r28: a runner-shaped pick fitted to 3.0 x 0.94 m: redraw until the short side is >= 1.4 m
                rg_ = _grey_rug(k + 5 + 11 * try_, c[0], c[1], lo[2], 0.0 if ax else math.pi / 2, fit=(sx, sy, 0.05) if ax else (sy, sx, 0.05))      # r26 #3: grey woven rug (REF), not a random pattern
                if rg_ is None:
                    break
                bpy.context.view_layer.update(); r0, r1 = _bb(rg_)
                if min(r1[0] - r0[0], r1[1] - r0[1]) >= 1.4 or try_ == 7:
                    break
                bpy.data.objects.remove(rg_, do_unlink=True); rg_ = None
            if rg_ is not None:
                bpy.context.view_layer.update(); r0, r1 = _bb(rg_)
                if ((r1[0] - r0[0]) > (r1[1] - r0[1])) != (sx > sy):         # long side along the bed axis
                    rg_.rotation_euler[2] += math.pi / 2; bpy.context.view_layer.update(); r0, r1 = _bb(rg_)
                rg_.location.x += c[0] - (r0[0] + r1[0]) / 2; rg_.location.y += c[1] - (r0[1] + r1[1]) / 2; rg_.location.z += lo[2] + 0.002 - r0[2]
                k += 1; continue
            _fl().mesh_object(f"H2Rug({rn})", [(bord, [("box", c[0], c[1], lo[2] + 0.006, sx, sy, 0.012)]), (rug, [("box", c[0], c[1], lo[2] + 0.008, sx - 0.16, sy - 0.16, 0.013)])], bevel=False); k += 1
    stats["h2_carpet"] = k


def _window_at(name, axis, line, side, a0, a1, z0, z1, kind="skyline"):
    """A framed window flush on a wall face: view plate + glass sheen + bronze frame + sill. side: +1 = the room lies at + of `line`."""
    from room_planner import rooftop_shell as rs
    e = 0.01 * side
    q = [(a0, line + e, z0), (a1, line + e, z0), (a1, line + e, z1), (a0, line + e, z1)] if axis == 0 else [(line + e, a0, z0), (line + e, a1, z0), (line + e, a1, z1), (line + e, a0, z1)]
    rs._quads(f"{name}View", [q], _view_mat(kind))
    fr = _flat("ir_h2_winframe", (0.16, 0.15, 0.14), 0.4, 1.0); prims = []
    t, d = 0.06, 0.08
    for u in (a0, (a0 + a1) / 2, a1):
        prims.append(("box", u, line + side * d / 2, (z0 + z1) / 2, t, d, z1 - z0 + t) if axis == 0 else ("box", line + side * d / 2, u, (z0 + z1) / 2, d, t, z1 - z0 + t))
    for z in (z0, z1):
        prims.append(("box", (a0 + a1) / 2, line + side * d / 2, z, a1 - a0 + t, d, t) if axis == 0 else ("box", line + side * d / 2, (a0 + a1) / 2, z, d, a1 - a0 + t, t))
    gl = _flat("ir_h2_winglass", (0.9, 0.93, 0.95), 0.03, transmission=0.95)
    g = [("box", (a0 + a1) / 2, line + side * 0.035, (z0 + z1) / 2, a1 - a0, 0.006, z1 - z0) if axis == 0 else ("box", line + side * 0.035, (a0 + a1) / 2, (z0 + z1) / 2, 0.006, a1 - a0, z1 - z0)]
    _fl().mesh_object(f"{name}Frame", [(fr, prims), (gl, g)], bevel=False)


def _curtains(name, axis, line, side, a0, a1, z1, acc):
    """Track + a dark outer drape each side + a sheer across, hanging 12-16 cm off the wall."""
    drape = _flat(f"ir_h2_drape", (0.3, 0.27, 0.24), 0.9); sheer = _flat("ir_h2_sheer", (0.95, 0.94, 0.91), 0.6, transmission=0.85)
    trk = _flat("ir_h2_track", (0.15, 0.15, 0.15), 0.4, 1.0)
    w = 0.45
    _pleats(f"{name}DrapeA", drape, axis, line + side * 0.16, a0 - 0.35, a0 - 0.35 + w, 0.14, z1)
    _pleats(f"{name}DrapeB", drape, axis, line + side * 0.16, a1 + 0.35 - w, a1 + 0.35, 0.14, z1)
    _pleats(f"{name}Sheer", sheer, axis, line + side * 0.11, a0 - 0.1, a0 + 0.45 * (a1 - a0), 0.14, z1 - 0.02, depth=0.03, pitch=0.09)      # half drawn: the view stays visible
    c = (a0 + a1) / 2
    _fl().mesh_object(f"{name}Track", [(trk, [("box", c, line + side * 0.14, z1 + 0.03, a1 - a0 + 0.9, 0.06, 0.03) if axis == 0 else ("box", line + side * 0.14, c, z1 + 0.03, 0.06, a1 - a0 + 0.9, 0.03)])], bevel=False)


def _window(stats):
    k = 0
    for rn in ROOMS:
        lo, hi = _room(rn)
        if lo is None:
            continue
        acc = _accent(rn)
        cur = _objs("CurtainFactory", lo, hi)
        wins = [o for o in bpy.data.objects if o.name.startswith("WindowFactory") and o.type == "MESH" and _in(o, (lo[0] - 0.4, lo[1], 0), (hi[0] + 0.4, hi[1], 0))]
        if wins:                                                    # a real window: the old curtain goes, a drape + sheer pair goes up round it
            for o in cur:
                bpy.data.objects.remove(o, do_unlink=True)
            b0, b1 = _bb(wins[0]); line = lo[0] if abs(b0[0] - lo[0]) < abs(b0[0] - hi[0]) else hi[0]; side = 1 if line == lo[0] else -1
            _curtains(f"H2Cur({rn})", 1, line, side, b0[1], b1[1], 2.6, acc); k += 1
            continue
        beds = _objs("SoftBedFactory", lo, hi)
        if not beds:
            continue
        cx, cy, ax, hd, L, W, b0, b1 = _bed_frame(beds[0])
        if ax:                                                      # the wall opposite the bed head
            line = lo[0] if hd > 0 else hi[0]; side = 1 if hd > 0 else -1; a0, a1 = lo[1] + 0.55, lo[1] + 2.35
            for o in [o for o in bpy.data.objects if o.name.startswith("WallArtFactory") and _in(o, lo, hi) and abs(_bb(o)[0][0] - line) < 0.2]:
                bpy.data.objects.remove(o, do_unlink=True)
            _window_at(f"H2Win({rn})", 1, line, side, a0, a1, 0.55, 2.45, "skyline"); _curtains(f"H2Cur({rn})", 1, line, side, a0, a1, 2.6, acc)
        else:
            line = lo[1] if hd > 0 else hi[1]; side = 1 if hd > 0 else -1; a0, a1 = lo[0] + 0.55, lo[0] + 2.35
            _window_at(f"H2Win({rn})", 0, line, side, a0, a1, 0.55, 2.45, "skyline"); _curtains(f"H2Cur({rn})", 0, line, side, a0, a1, 2.6, acc)
        _light(f"ir_h2_winfill_{rn}", "AREA", ((line + side * 0.4, (a0 + a1) / 2, 1.5) if ax else ((a0 + a1) / 2, line + side * 0.4, 1.5)), 60, (0.9, 0.95, 1.0), 1.5).rotation_euler = ((0, math.radians(-90 * side), 0) if ax else (math.radians(90 * side), 0, 0))
        k += 1
    clear = _view_mat("garden", 1.2)                                  # r23 test: transmissive glass showed a black void (no card behind the high bath window): the pane shows the view itself
    nb = 0
    for o in bpy.data.objects:                                       # bathroom frosted panes -> clear glass (the exterior card is outside)
        if o.name.startswith("WindowFactory") and o.type == "MESH":
            for i, m in enumerate(o.data.materials):
                if m is not None and m.name.startswith("ir_win_frost_glow"):
                    if o.data.users > 1:
                        o.data = o.data.copy()
                    o.data.materials[i] = clear; nb += 1
    stats["h2_windows"] = {"rooms": k, "bath_panes_cleared": nb}


def _lamp(name, x, y, z):
    brass = _flat("ir_h2_brass", (0.75, 0.56, 0.28), 0.3, 1.0); shade = _emit("ir_h2_shade", (0.98, 0.9, 0.75), 1.6)
    _fl().mesh_object(name, [(brass, [("cyl", (x, y, z), (x, y, z + 0.03), 0.08, 18), ("cyl", (x, y, z + 0.03), (x, y, z + 0.36), 0.012, 8)]),
                             (shade, [("cyl", (x, y, z + 0.32), (x, y, z + 0.52), 0.15, 24)])], bevel=False)
    _light(name + "_l", "POINT", (x, y, z + 0.42), 18, (1.0, 0.78, 0.55), 0.08)


def _furn(stats):
    oak = _noise("ir_h2_oak", (0.62, 0.45, 0.27), (0.5, 0.35, 0.2), 30.0, 0.5); dark = _flat("ir_h2_gap", (0.08, 0.06, 0.05), 0.6)
    s = {"stands": 0, "lamps": 0, "chairs": 0, "desks": 0, "plants": 0}
    for rn in ROOMS:
        lo, hi = _room(rn)
        if lo is None:
            continue
        fz = lo[2]; acc = _accent(rn); fab = _flat(f"ir_h2_chair_{rn[-1]}", tuple(min(1, c * 1.1) for c in acc), 0.9)
        for o in _objs("AboTableLampFactory", lo, hi):
            bpy.data.objects.remove(o, do_unlink=True)
        for o in _objs("AboNightstandFactory", lo, hi):           # coordinated oak cabinets, a lamp on each
            b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2; bpy.data.objects.remove(o, do_unlink=True)
            yw = math.atan2((lo[1] + hi[1]) / 2 - cy, (lo[0] + hi[0]) / 2 - cx)          # real models face the room (user 10-25: no box modelling)
            ns_ = ra.abo("nightstand", s["stands"] + 3, cx, cy, fz, yw, fit=(0.5, 0.45, 0.6))
            if ns_ is None:
                _fl().mesh_object(f"H2Stand({rn}|{s['stands']})", [(oak, [("box", cx, cy, fz + 0.28, 0.45, 0.42, 0.56)]), (dark, [("box", cx, cy, fz + 0.36, 0.452, 0.422, 0.008)])], bevel=False)
            zt_ = ra.top(ns_) if ns_ is not None else fz + 0.56
            if ra.abo("tablelamp", s["stands"] + 5 + 7 * int(rn.split("/")[1]), cx, cy, zt_, yw, fit=(0.38, 0.38, 0.55)) is not None:      # r26 #7: lamp model differs per room
                _light(f"H2Lamp({rn}|{s['stands']})_l", "POINT", (cx, cy, zt_ + 0.35), 18, (1.0, 0.78, 0.55), 0.08)
            else:
                _lamp(f"H2Lamp({rn}|{s['stands']})", cx, cy, zt_)
            s["stands"] += 1; s["lamps"] += 1
        for o in _objs("OfficeChairFactory", lo, hi):              # a low upholstered chair on slim oak legs
            b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2; bpy.data.objects.remove(o, do_unlink=True)
            _chair(f"H2Chair({rn})", fab, oak, cx, cy, fz, lo, hi); s["chairs"] += 1
        if not _objs("AboDeskFactory", lo, hi):                    # a slim oak console under the TV
            tv = _objs("WallDisplayFactory", lo, hi)
            if tv:
                b0, b1 = _bb(tv[0]); tx, ty = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
                if b1[0] - b0[0] < b1[1] - b0[1]:
                    sx = 1 if abs(tx - lo[0]) < abs(tx - hi[0]) else -1; wx = lo[0] if sx > 0 else hi[0]
                    _fl().mesh_object(f"H2Desk({rn})", [(oak, [("box", wx + sx * 0.25, ty, fz + 0.74, 0.48, 1.4, 0.04), ("box", wx + sx * 0.25, ty, fz + 0.62, 0.46, 1.38, 0.2)])], bevel=False)
                    _chair(f"H2Chair({rn})", fab, oak, wx + sx * 0.8, ty, fz, lo, hi)
                else:
                    sy = 1 if abs(ty - lo[1]) < abs(ty - hi[1]) else -1; wy = lo[1] if sy > 0 else hi[1]
                    _fl().mesh_object(f"H2Desk({rn})", [(oak, [("box", tx, wy + sy * 0.25, fz + 0.74, 1.4, 0.48, 0.04), ("box", tx, wy + sy * 0.25, fz + 0.62, 1.38, 0.46, 0.2)])], bevel=False)
                    _chair(f"H2Chair({rn})", fab, oak, tx, wy + sy * 0.8, fz, lo, hi)
                s["desks"] += 1; s["chairs"] += 1
        bpy.context.view_layer.update()
        for dk in _objs("AboDeskFactory", lo, hi) + _objs("H2Desk", lo, hi):     # r23 review: desk accessories (lamp, notepad, tray, cup), real assets
            b0, b1 = _bb(dk); zt_ = b1[2]; along_x = (b1[0] - b0[0]) >= (b1[1] - b0[1]); dcx, dcy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            P_ = (lambda t: (dcx + t, dcy)) if along_x else (lambda t: (dcx, dcy + t))
            ln = max(b1[0] - b0[0], b1[1] - b0[1])
            ra.abo("tablelamp", (__import__("zlib").crc32(rn.encode()) & 0xff), *P_(-ln / 2 + 0.18), zt_, 0.0, fit=(0.3, 0.3, 0.5))
            ra.abo("notepad", (__import__("zlib").crc32(rn.encode()) & 0xff), *P_(0.0), zt_, 0.2, fit=(0.3, 0.22, 0.03))
            tr_ = ra.abo("tray", (__import__("zlib").crc32(rn.encode()) & 0xff), *P_(ln / 2 - 0.22), zt_, 0.0, fit=(0.36, 0.26, 0.05))
            ra.lib("CupFactory", (__import__("zlib").crc32(rn.encode()) & 0xff), *P_(ln / 2 - 0.22), ra.top(tr_) - 0.03 if tr_ is not None else zt_, 0.4, 0.8)
        if not _objs("OliveTreeFactory", lo, hi) and not _objs("H2Plant", lo, hi):
            kr_ = int(rn.split("/")[1]); px_, py_ = lo[0] + 0.35, lo[1] + 0.35                  # r26 #7: the plant corner differs per room (first free corner from a per-room start)
            for c_ in range(4):
                cx_, cy_ = ((lo[0] + 0.35, lo[1] + 0.35), (hi[0] - 0.35, lo[1] + 0.35), (hi[0] - 0.35, hi[1] - 0.35), (lo[0] + 0.35, hi[1] - 0.35))[(kr_ + c_) % 4]
                if not any(o_.type == "MESH" and not o_.name.startswith(rn) and (lambda q0, q1: q0[0] - 0.25 < cx_ < q1[0] + 0.25 and q0[1] - 0.25 < cy_ < q1[1] + 0.25 and q1[2] > fz + 0.3 and q0[2] < fz + 1.5)(*_bb(o_)) for o_ in bpy.data.objects if _in(o_, lo, hi)):
                    px_, py_ = cx_, cy_; break
            _plant(f"H2Plant({rn})", px_, py_, fz); s["plants"] += 1
    stats["h2_furn"] = s


def _chair(name, fab, oak, cx, cy, fz, lo, hi):
    if ra.abo("deskchair", (__import__("zlib").crc32(name.encode()) & 0xff), cx, cy, fz, math.atan2((lo[1] + hi[1]) / 2 - cy, (lo[0] + hi[0]) / 2 - cx), fit=(0.6, 0.6, 0.95)) is not None:
        return
    legs = [("cyl", (cx + dx, cy + dy, fz), (cx + dx, cy + dy, fz + 0.42), 0.014, 8) for dx in (-0.2, 0.2) for dy in (-0.2, 0.2)]
    _fl().mesh_object(name + "Legs", [(oak, legs)], bevel=False)
    _soft(name + "Seat", fab, cx, cy, fz + 0.47, 0.5, 0.48, 0.1, bevel=0.03)
    d = (1 if cx < (lo[0] + hi[0]) / 2 else -1)                      # the back towards the nearer wall
    if abs(cx - lo[0]) < 0.9 or abs(cx - hi[0]) < 0.9:
        bx = cx + (-0.22 if abs(cx - lo[0]) < abs(cx - hi[0]) else 0.22); _soft(name + "Back", fab, bx, cy, fz + 0.72, 0.08, 0.46, 0.42, bevel=0.03)
    else:
        by = cy + (-0.22 if abs(cy - lo[1]) < abs(cy - hi[1]) else 0.22); _soft(name + "Back", fab, cx, by, fz + 0.72, 0.46, 0.08, 0.42, bevel=0.03)
    _ = d


def _plant(name, x, y, fz):
    if ra.abo("planter", (__import__("zlib").crc32(name.encode()) & 0xff), x, y, fz, 0.0, fit=(0.6, 0.6, 1.3)) is not None:
        return
    pot = _flat("ir_h2_pot", (0.2, 0.19, 0.18), 0.5); leaf = _flat("ir_h2_leaf", (0.12, 0.3, 0.1), 0.6); rg = random.Random(__import__("zlib").crc32(name.encode()) & 0xffff)
    leaves = []
    for i in range(26):
        a = rg.uniform(0, 6.28); h = rg.uniform(0.45, 1.25); r = rg.uniform(0.05, 0.28)
        leaves.append(("box", x + math.cos(a) * r, y + math.sin(a) * r, fz + h, 0.16, 0.06, 0.012, a))
        leaves.append(("cyl", (x, y, fz + 0.38), (x + math.cos(a) * r, y + math.sin(a) * r, fz + h), 0.006, 5))
    _fl().mesh_object(name, [(pot, [("cyl", (x, y, fz), (x, y, fz + 0.4), 0.17, 20)]), (leaf, leaves)], bevel=False)


def _corr(stats):
    lo, hi = _room(HALL)
    if lo is None:
        return
    fz = lo[2]; fl = _fl(); oak = _noise("ir_h2_oak", (0.62, 0.45, 0.27), (0.5, 0.35, 0.2), 30.0, 0.5)
    for o in list(bpy.data.objects):                                # clock / notices / small art / surface battens and their lamps
        if o.type == "MESH" and o.name.startswith(("ClinicWallItemFactory", "WallArtFactory", "CeilingLightFactory")) and _in(o, lo, hi):
            bpy.data.objects.remove(o, do_unlink=True)
    for o in list(bpy.data.objects):
        if o.type == "LIGHT" and lo[0] < o.location.x < hi[0] and lo[1] < o.location.y < hi[1] and o.name.startswith("PointLampFactory"):
            bpy.data.objects.remove(o, do_unlink=True)
    for k, (x, side) in enumerate(((lo[0], 1), (hi[0], -1))):       # full-height framed end windows + a planter
        _window_at(f"H2CorrWin{k}", 1, x, side, lo[1] + 0.35, hi[1] - 0.35, fz + 0.12, fz + 2.5, "garden")
        _plant(f"H2CorrPlant{k}", x + side * 0.4, hi[1] - 0.4, fz)
        _light(f"ir_h2_corrwin_{k}", "AREA", (x + side * 0.5, (lo[1] + hi[1]) / 2, 1.4), 50, (0.9, 0.95, 1.0), 1.5).rotation_euler = (0, math.radians(-90 * side), 0)
    def doors_on(yw):
        out = []
        for o in bpy.data.objects:
            if o.type == "MESH" and o.name.startswith(("door", "DoorCasing", "PanelDoor", "LiteDoor")):
                b0, b1 = _bb(o)
                if b0[1] - 0.15 < yw < b1[1] + 0.15 and lo[0] < (b0[0] + b1[0]) / 2 < hi[0]:
                    out.append((b0, b1))
        return out
    dl_, dh_ = doors_on(lo[1]), doors_on(hi[1])                     # r23: the room doors are on the low-y wall: architraves there, prints on the door-free wall
    WF = 0.075                                                     # the floor bbox runs to the wall centre lines: the inner wall face is ~6 cm in (r23: prints / architraves / skirting sat inside the walls)
    wl_ = bpy.data.objects.get(f"{HALL}.wall"); ylo_, yhi_ = lo[1] + WF, hi[1] - WF
    if wl_ is not None:                                              # the wall mesh's inner faces (H2: 0.117 / 1.883 for a 0..2 m floor)
        ys_ = [(wl_.matrix_world @ v.co).y for v in wl_.data.vertices]; mid_ = (lo[1] + hi[1]) / 2
        ylo_ = min((y_ for y_ in ys_ if lo[1] + 0.02 < y_ < mid_ - 0.3), default=ylo_); yhi_ = max((y_ for y_ in ys_ if mid_ + 0.3 < y_ < hi[1] - 0.02), default=yhi_)
    ydoor, yart = (ylo_, yhi_) if len(dl_) >= len(dh_) else (yhi_, ylo_); sd = 1 if ydoor < (lo[1] + hi[1]) / 2 else -1
    arch = []; spans = []
    for b0, b1 in sorted(dl_ if ydoor == lo[1] else dh_, key=lambda b: b[0][0]):
        if spans and b0[0] < spans[-1][1]:                          # leaf + casing of one door overlap: one opening
            spans[-1] = (spans[-1][0], max(spans[-1][1], b1[0]), max(spans[-1][2], b1[2])); continue
        spans.append((b0[0], b1[0], b1[2]))
    for xa, xb, zt_ in spans:
        zt = min(zt_, fz + 2.2); y = ydoor + sd * 0.015
        arch += [("box", xa - 0.035, y, (fz + zt) / 2 + 0.02, 0.07, 0.03, zt - fz + 0.07), ("box", xb + 0.035, y, (fz + zt) / 2 + 0.02, 0.07, 0.03, zt - fz + 0.07), ("box", (xa + xb) / 2, y, zt + 0.04, xb - xa + 0.14, 0.03, 0.07)]
    if arch:
        fl.mesh_object("H2Architraves", [(oak, arch)], bevel=False)
    art = _noise("ir_h2_abstract", (0.86, 0.83, 0.77), (0.35, 0.32, 0.3), 1.6, 0.7, detail=2.0, lo=0.45, hi=0.62); frm = _flat("ir_h2_artframe", (0.2, 0.17, 0.14), 0.5)
    prints = []; frames = []; sa = 1 if yart < (lo[1] + hi[1]) / 2 else -1; y = yart
    sk = [("box", (lo[0] + hi[0]) / 2, yart + sa * 0.008, fz + 0.05, hi[0] - lo[0] - 0.1, 0.016, 0.1)]       # oak skirting: the door-free wall full length, the door wall between the openings
    cur = lo[0] + 0.05
    for xa_, xb_, _ in spans + [(hi[0] - 0.05, hi[0], 0)]:
        if xa_ - 0.1 - cur > 0.1:
            sk.append(("box", (cur + xa_ - 0.1) / 2, ydoor + sd * 0.008, fz + 0.05, xa_ - 0.1 - cur, 0.016, 0.1))
        cur = xb_ + 0.1
    fl.mesh_object("H2CorrSkirting", [(oak, sk)], bevel=True)
    for x in [lo[0] + 1.6 + 2.6 * i for i in range(int((hi[0] - lo[0] - 2.0) / 2.6) + 1)]:
        if x > hi[0] - 1.2:
            break
        dy_ = sa
        prints.append(("box", x, y + dy_ * 0.012, fz + 1.55, 0.9, 0.006, 1.2)); frames.append(("box", x, y + dy_ * 0.004, fz + 1.55, 0.98, 0.012, 1.28))
    fl.mesh_object("H2CorrPrints", [(frm, frames), (art, prints)], bevel=False)
    dl = _emit("ir_h2_downlight", (1.0, 0.85, 0.65), 25.0); trim = _flat("ir_h2_trim", (0.9, 0.9, 0.88), 0.4); zc = 2.73; discs, trims = [], []
    xs = [lo[0] + 0.8 + 1.6 * i for i in range(int((hi[0] - lo[0] - 1.6) / 1.6) + 1)]
    for i, x in enumerate(xs):
        yc = (lo[1] + hi[1]) / 2
        trims.append(("cyl", (x, yc, zc - 0.006), (x, yc, zc - 0.003), 0.07, 20)); discs.append(("cyl", (x, yc, zc - 0.008), (x, yc, zc - 0.006), 0.05, 20))
        _light(f"ir_h2_corr_dl_{i}", "SPOT", (x, yc, zc - 0.05), 45)
    fl.mesh_object("H2CorrDownlights", [(trim, trims), (dl, discs)], bevel=False)
    stats["h2_corr"] = {"downlights": len(xs), "prints": len(prints), "architraves": len(arch) // 3}


def _bath(stats):
    stone = _noise("ir_h2_beige_stone", (0.8, 0.74, 0.64), (0.72, 0.66, 0.56), 2.5, 0.45, detail=8.0)
    fl = _fl(); oak = _noise("ir_h2_oak", (0.62, 0.45, 0.27), (0.5, 0.35, 0.2), 30.0, 0.5); towel = _flat("ir_h2_towel", (0.95, 0.94, 0.92), 0.95)
    led = _emit("ir_h2_mirror_led", (1.0, 0.88, 0.7), 6.0); mirror = _flat("ir_h2_mirror", (0.9, 0.9, 0.9), 0.02, 1.0); k = 0
    for rn, br in zip(BATHS, ROOMS):
        lo, hi = _room(rn)
        if lo is None:
            continue
        fz = lo[2]; acc = _accent(br); geo = _cement(f"ir_h2_cement_g{rn[-1]}", acc, grey=True)
        w = bpy.data.objects.get(f"{rn}.wall")
        if w is not None:
            for sl in w.material_slots:
                sl.material = stone
        f = bpy.data.objects.get(f"{rn}.floor")
        if f is not None:
            for sl in f.material_slots:
                sl.material = geo
        tub = _objs("BathtubFactory", lo, hi)
        if tub:                                                       # geometric accent panel on the wall at the tub end
            b0, b1 = _bb(tub[0]); xw = lo[0] + 0.012 if abs(b0[0] - lo[0]) < abs(b1[0] - hi[0]) else hi[0] - 0.012
            geo_w = _cement(f"ir_h2_cement_gw{rn[-1]}", acc, wall_x=True, grey=True)
            fl.mesh_object(f"H2BathAccent({rn})", [(geo_w, [("box", xw, (lo[1] + hi[1]) / 2, fz + 1.3, 0.012, hi[1] - lo[1] - 0.05, 2.4)])], bevel=False)
            tx_ = (b0[0] + b1[0]) / 2; ty_ = b1[1] - 0.09 if hi[1] - b1[1] < b0[1] - lo[1] else b0[1] + 0.09       # r24 review: visible taps on the tub deck at the wall side
            if ra.hssd(r"Classic Bath Shower Mixer|Bath ?/? ?Shower Mixer", k + 1, tx_, ty_, b1[2] - 0.01, 0.0 if ty_ > b0[1] + 0.2 else math.pi, fit=(0.4, 0.35, 0.3)) is None:
                chrome = _flat("ir_h2_chrome", (0.85, 0.86, 0.88), 0.12, 1.0)
                fl.mesh_object(f"H2TubTap({rn})", [(chrome, [("cyl", (tx_, ty_, b1[2]), (tx_, ty_, b1[2] + 0.2), 0.018, 16), ("cyl", (tx_, ty_, b1[2] + 0.2), (tx_, ty_ + (-0.16 if ty_ > b0[1] + 0.2 else 0.16), b1[2] + 0.2), 0.014, 16),
                                                              ("cyl", (tx_ - 0.1, ty_, b1[2]), (tx_ - 0.1, ty_, b1[2] + 0.07), 0.022, 16), ("cyl", (tx_ + 0.1, ty_, b1[2]), (tx_ + 0.1, ty_, b1[2] + 0.07), 0.022, 16)])], bevel=True)
        van = _objs("HomeVanityFactory", lo, hi)
        if van:                                                       # r23 review: a long vanity on the back wall (opposite the door) replaces the compact front sink
            b0o, b1o = _bb(van[0]); drs = [_bb(o) for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("door", "LiteDoor", "PanelDoor", "GlassPanelDoor")) and _in(o, lo, hi)]
            dcy = sum((d0[1] + d1[1]) / 2 for d0, d1 in drs) / len(drs) if drs else lo[1]
            wyb, syb = (hi[1], -1) if dcy < (lo[1] + hi[1]) / 2 else (lo[1], 1)
            tubs_ = [_bb(t) for t in tub]; xa_, xb_ = lo[0] + 0.1, hi[0] - 0.1
            for t0, t1 in tubs_:                                  # keep clear of the tub on that wall
                if abs((t0[1] + t1[1]) / 2 - wyb) < 1.0:
                    if t0[0] - lo[0] > hi[0] - t1[0]:
                        xb_ = min(xb_, t0[0] - 0.08)
                    else:
                        xa_ = max(xa_, t1[0] + 0.08)
            vl = min(1.6, xb_ - xa_)
            if vl > 0.8:
                nv = ra.abo("vanity", k + 3, (xa_ + xb_) / 2, wyb + syb * 0.3, fz, math.atan2(syb, 0), fit=(vl, 0.58, 1.0))
                if nv is not None:
                    for o_ in van:
                        bpy.data.objects.remove(o_, do_unlink=True)
                    bpy.context.view_layer.update(); van = [nv]
        if van:
            v = van[0]
            if v.data.users > 1:
                v.data = v.data.copy()
            for i, m in enumerate(v.data.materials):
                if m is not None and m.name.startswith("ir_vanity_white"):
                    v.data.materials[i] = oak
            b0, b1 = _bb(v); cx = (b0[0] + b1[0]) / 2
            wy, sy = (lo[1], 1) if abs(b0[1] - lo[1]) < abs(b1[1] - hi[1]) else (hi[1], -1)
            fl.mesh_object(f"H2Mirror({rn})", [(led, [("box", cx, wy + sy * 0.012, fz + 1.55, (b1[0] - b0[0]) + 0.06, 0.01, 0.86)]), (mirror, [("box", cx, wy + sy * 0.02, fz + 1.55, b1[0] - b0[0] - 0.02, 0.01, 0.8)])], bevel=False)
            _light(f"ir_h2_mirror_{rn}", "AREA", (cx, wy + sy * 0.3, fz + 1.6), 25, (1.0, 0.88, 0.7), 0.6).rotation_euler = (math.radians(90 * sy), 0, 0)
            nx_ = cx + (0.0 if abs(cx - (lo[0] + hi[0]) / 2) > 0.4 else 0.0)                          # recessed shower / bath niche on the tub wall: a darker stone inset with library bottles
            if tub:
                b0t, b1t = _bb(tub[0]); xw_ = lo[0] + 0.03 if abs(b0t[0] - lo[0]) < abs(b1t[0] - hi[0]) else hi[0] - 0.03; ny = (b0t[1] + b1t[1]) / 2
                inset = _flat("ir_h2_niche", (0.55, 0.5, 0.43), 0.4)
                fl.mesh_object(f"H2Niche({rn})", [(inset, [("box", xw_, ny, fz + 1.25, 0.02, 0.6, 0.34)]), (oak, [("box", xw_ + (0.04 if xw_ < cx else -0.04), ny, fz + 1.09, 0.08, 0.6, 0.02)])], bevel=True)
                for q_ in range(3):
                    ra.lib("BottleFactory", 900 + k * 3 + q_, xw_ + (0.04 if xw_ < cx else -0.04), ny - 0.18 + q_ * 0.17, fz + 1.1, 0.0, 0.55)
            for j in range(3):                                         # folded towels on the counter end
                _soft(f"H2Towel({rn}|{j})", towel, b1[0] - 0.16, (b0[1] + b1[1]) / 2, fz + 0.88 + j * 0.06, 0.24, 0.3, 0.055, bevel=0.02)
        k += 1
        sx_ = 0                                                       # r26 #4: the window 'sun' card behind the high bath window drew a hard diagonal streak on the tile: softer + weaker
        for L_ in [o for o in bpy.data.objects if o.type == "LIGHT" and o.name.startswith("ir_real_sun") and lo[0] - 1.0 < o.location.x < hi[0] + 1.0 and lo[1] - 1.0 < o.location.y < hi[1] + 1.0]:
            L_.data.energy *= 0.3; L_.data.shadow_soft_size = max(L_.data.shadow_soft_size, 1.0)
            if L_.data.type == "AREA":
                L_.data.size = max(L_.data.size, 2.0); L_.data.size_y = max(getattr(L_.data, "size_y", 0.0), 1.5)
                if hasattr(L_.data, "spread"):
                    L_.data.spread = math.radians(160)
            sx_ += 1
        stats["h2_bath_sun_softened"] = stats.get("h2_bath_sun_softened", 0) + sx_
        tub = _objs("BathtubFactory", lo, hi)                        # r26 #8: a fixed glass shower screen on the tub's open long edge, at the tap end
        if tub:
            t0, t1 = _bb(tub[0]); glass = _flat("ir_h2_shower_glass", (0.9, 0.95, 0.95), 0.02, transmission=0.95); chrome = _flat("ir_h2_chrome", (0.85, 0.85, 0.87), 0.12, 1.0)
            along_x = (t1[0] - t0[0]) >= (t1[1] - t0[1]); ztop = t1[2]
            if along_x:
                ye = t0[1] + 0.02 if (t0[1] - lo[1]) > (hi[1] - t1[1]) else t1[1] - 0.02; xa = t0[0] if abs(t0[0] - lo[0]) < abs(t1[0] - hi[0]) else t1[0] - 0.85
                fl.mesh_object(f"H2ShowerScreen({rn})", [(glass, [("box", xa + 0.425, ye, ztop + 0.72, 0.85, 0.008, 1.4)]), (chrome, [("box", xa + 0.425, ye, ztop + 1.43, 0.87, 0.02, 0.02), ("box", xa + 0.425, ye, ztop + 0.01, 0.87, 0.02, 0.02)])], bevel=True)
            else:
                xe = t0[0] + 0.02 if (t0[0] - lo[0]) > (hi[0] - t1[0]) else t1[0] - 0.02; ya = t0[1] if abs(t0[1] - lo[1]) < abs(t1[1] - hi[1]) else t1[1] - 0.85
                fl.mesh_object(f"H2ShowerScreen({rn})", [(glass, [("box", xe, ya + 0.425, ztop + 0.72, 0.008, 0.85, 1.4)]), (chrome, [("box", xe, ya + 0.425, ztop + 1.43, 0.02, 0.87, 0.02), ("box", xe, ya + 0.425, ztop + 0.01, 0.02, 0.87, 0.02)])], bevel=True)
    stats["h2_baths"] = k


def _planks(name, rgb):
    """Light oak floor planks (r24 review: timber surround): 1.2 x 0.18 m staggered boards, thin dark joints, per-board tone + fine grain."""
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = _flat(name, rgb, 0.45); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); br = N.new("ShaderNodeTexBrick"); L.new(tc.outputs["Object"], br.inputs["Vector"])
    br.offset = 0.5; br.inputs["Scale"].default_value = 1.0; br.inputs["Brick Width"].default_value = 1.2; br.inputs["Row Height"].default_value = 0.18; br.inputs["Mortar Size"].default_value = 0.002
    br.inputs["Color1"].default_value = (*rgb, 1); br.inputs["Color2"].default_value = (*(c * 0.82 for c in rgb), 1); br.inputs["Mortar"].default_value = (*(c * 0.35 for c in rgb), 1)
    wv = N.new("ShaderNodeTexWave"); wv.bands_direction = "X"; wv.inputs["Scale"].default_value = 30.0; wv.inputs["Distortion"].default_value = 6.0; L.new(tc.outputs["Object"], wv.inputs["Vector"])
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs["Factor"].default_value = 0.12
    L.new(br.outputs["Color"], mx.inputs["A"]); L.new(wv.outputs["Color"], mx.inputs["B"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
    bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 0.3; bu.inputs["Distance"].default_value = 0.001; L.new(br.outputs["Fac"], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"])
    return m


def _floor(stats):
    """r24 review: bedroom floors were plain beige broadloom; REF = warm timber with a woven rug under the bed (the rug is the carpet part's ABO rug)."""
    oak = _planks("ir_h2_oak_planks", (0.55, 0.4, 0.25)); k = 0
    for rn in ROOMS:
        f = bpy.data.objects.get(f"{rn}.floor")
        if f is not None:
            for sl in f.material_slots:
                sl.material = oak
            k += 1
    stats["h2_floor_planks"] = k


def _art(stats):
    """r24 review: the corridor prints (procedural noise) and the WallArtFactory paintings read as grey water stains: real ABO WALL_ART, flush on the wall, facing the room."""
    k = miss = 0
    spots = []
    for o in list(bpy.data.objects):
        if o.type == "MESH" and o.name.startswith(("WallArtFactory", "H2CorrPrints")):
            if o.name.startswith("H2CorrPrints"):                         # one entry per print: the frame boxes, read back from the mesh islands
                me = o.data; bm = bmesh.new(); bm.from_mesh(me); bm.transform(o.matrix_world)
                isl = []
                for f in bm.faces:
                    c = f.calc_center_median()
                    if f.material_index == 0:
                        isl.append(c)
                bm.free()
                xs_ = sorted(c.x for c in isl); y = sum(c.y for c in isl) / max(len(isl), 1); z = sum(c.z for c in isl) / max(len(isl), 1)
                groups, xs = [], []
                for x_ in xs_:                                           # one frame = its faces within ~0.6 m in x
                    if groups and x_ - groups[-1][-1] < 0.6:
                        groups[-1].append(x_)
                    else:
                        groups.append([x_])
                xs = [(g[0] + g[-1]) / 2 for g in groups]
                for x in xs:
                    spots.append((x, y, z, 0.6, 0.9, 1))                       # r25: ~0.6 x 0.9 m frames (REF); 0.95 x 1.2 read oversized
            else:
                b0, b1 = _bb(o); spots.append(((b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2, (b0[2] + b1[2]) / 2, min(max(b1[0] - b0[0], b1[1] - b0[1]), 0.6 if _in(o, *_room(HALL)) else 0.9), min(b1[2] - b0[2], 0.9 if _in(o, *_room(HALL)) else 1.0), 0))
            bpy.data.objects.remove(o, do_unlink=True)
    for i, (x, y, z, w, h, corr) in enumerate(spots):
        rn = next((r for r in ROOMS + (HALL,) if (lambda lo, hi: lo is not None and lo[0] - 0.2 <= x <= hi[0] + 0.2 and lo[1] - 0.2 <= y <= hi[1] + 0.2)(*_room(r))), None)
        if rn is None:
            continue
        lo, hi = _room(rn)
        d = {"W": x - lo[0], "E": hi[0] - x, "S": y - lo[1], "N": hi[1] - y}; side = min(d, key=d.get)
        nrm = {"W": (1, 0), "E": (-1, 0), "S": (0, 1), "N": (0, -1)}[side]
        yaw = math.atan2(nrm[1], nrm[0])
        o = ra.abo("wallart", 40 + i * 7 + (__import__("zlib").crc32(rn.encode()) & 0x3f), x, y, z - h / 2, yaw, fit=(w, w, h))
        if o is None:
            miss += 1; continue
        bpy.context.view_layer.update()
        b0, b1 = _bb(o); ext = (b1[0] - b0[0], b1[1] - b0[1])
        if (abs(nrm[0]) and ext[0] > ext[1]) or (abs(nrm[1]) and ext[1] > ext[0]):       # the thin axis must face out of the wall
            o.rotation_euler[2] += math.pi / 2; bpy.context.view_layer.update(); b0, b1 = _bb(o)
        if abs(nrm[0]):                                                    # back flush on the wall plane the old picture hung on
            o.location.x += (x - (b0[0] if nrm[0] > 0 else b1[0])) + nrm[0] * 0.004
        else:
            o.location.y += (y - (b0[1] if nrm[1] > 0 else b1[1])) + nrm[1] * 0.004
        if corr:
            _light(f"ir_h2_artlight_{i}", "SPOT", (x + nrm[0] * 0.35, y + nrm[1] * 0.35, z + h / 2 + 0.25), 25, (1.0, 0.85, 0.65)).rotation_euler = (math.radians(35) * (-nrm[1]), math.radians(35) * nrm[0], 0)
        k += 1
    stats["h2_art"] = {"placed": k, "missed": miss}


def _ceil(stats):
    """r24 review: bedrooms have flush mounts, a track rail and vent grilles; REF = a grid of round recessed downlights (+ the bedside lamps)."""
    dl = _emit("ir_h2_downlight", (1.0, 0.85, 0.65), 25.0); trim = _flat("ir_h2_trim", (0.9, 0.9, 0.88), 0.4); n = 0
    for rn in ROOMS:
        lo, hi = _room(rn)
        if lo is None:
            continue
        for o in list(bpy.data.objects):
            if o.type == "MESH" and o.name.startswith(("AboCeilingFixtureFactory", "TrackRailFactory", "TrackSpotFactory", "MfgVent", "CeilingLightFactory", "AcCassetteFactory", "DiffuserFactory", "VentFactory")) and _in(o, lo, hi) and _bb(o)[1][2] > 2.2:
                bpy.data.objects.remove(o, do_unlink=True)
        for o in list(bpy.data.objects):                              # their lamps (track spots / dome points) too, not the bedside lamps
            if o.type == "LIGHT" and lo[0] < o.location.x < hi[0] and lo[1] < o.location.y < hi[1] and o.location.z > 2.2 and not o.name.startswith(("H2", "ir_h2")):
                bpy.data.objects.remove(o, do_unlink=True)
        c = bpy.data.objects.get(f"{rn}.ceiling"); zc = _bb(c)[0][2] if c is not None else 2.73
        if c is not None:
            c["ir_no_vent"] = 1                                          # r25: mfg_detail's ceiling grilles run after this hook; it skips ceilings carrying this prop
        discs, trims = [], []
        for i in range(2):
            for j in range(3):
                x = lo[0] + (hi[0] - lo[0]) * (0.28 + 0.44 * i); y = lo[1] + (hi[1] - lo[1]) * (0.2 + 0.3 * j)
                trims.append(("cyl", (x, y, zc - 0.006), (x, y, zc - 0.002), 0.065, 24)); discs.append(("cyl", (x, y, zc - 0.009), (x, y, zc - 0.006), 0.045, 24))
                _light(f"ir_h2_room_dl_{rn[-1]}_{i}{j}", "SPOT", (x, y, zc - 0.05), 45, (1.0, 0.8, 0.58)); n += 1
        _fl().mesh_object(f"H2Downlights({rn})", [(trim, trims), (dl, discs)], bevel=False)
        _light(f"ir_h2_room_fill_{rn[-1]}", "AREA", ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, zc - 0.15), 90, (1.0, 0.8, 0.6), 2.2)      # r26 #1: warm fill (bedrooms read dark / grey)
    stats["h2_downlights"] = n


def _walls(stats):
    """r24 review: the horizontal pallet-plank wall (late_walls slat slot) beside the vertical headboard slats: the bedroom walls become smooth warm plaster, the slats stay on the bed wall only."""
    plaster = _noise("ir_h2_plaster", (0.86, 0.83, 0.77), (0.83, 0.8, 0.74), 1.2, 0.85, detail=3.0, lo=0.45, hi=0.55); k = 0
    for rn in ROOMS:
        w = bpy.data.objects.get(f"{rn}.wall")
        if w is None:
            continue
        for sl in w.material_slots:
            if sl.material is not None:                                  # every bedroom wall slot (concrete, slat, the plank 'material_N'): the vertical oak slats are their own objects
                sl.material = plaster; k += 1
    stats["h2_walls_plastered"] = k


def _doors(stats):
    """r24 review: the door leaves read as flat slabs: two raised panels per face in the leaf's own veneer (bevelled), 3 brass hinges on the hinge edge."""
    brass = _flat("ir_h2_hinge", (0.75, 0.58, 0.3), 0.3, 1.0); n = 0
    LEAF = ("LiteDoorFactory", "LouverDoorFactory", "GlassPanelDoorFactory", "PanelDoorFactory")
    cas_all = [c for c in bpy.data.objects if c.type == "MESH" and c.name.startswith("DoorCasingFactory")]
    closed = 0
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(LEAF)]:      # r25: the bathroom leaves stood open into the tiny bathrooms and filled the review views: swing them shut about the hinge
        b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
        near = min(cas_all, key=lambda c_: sum(((_bb(c_)[0][i] + _bb(c_)[1][i]) / 2 - (cx, cy)[i]) ** 2 for i in range(2)), default=None)
        if near is None:
            continue
        n0, n1 = _bb(near); ncx, ncy = (n0[0] + n1[0]) / 2, (n0[1] + n1[1]) / 2
        is_bath = any((lambda lo, hi: lo is not None and lo[0] - 0.3 < ncx < hi[0] + 0.3 and abs(ncy - lo[1]) < 0.35)(*_room(bn)) for bn in BATHS)
        is_bed = any((lambda lo, hi: lo is not None and lo[0] - 0.3 < ncx < hi[0] + 0.3 and (abs(ncy - lo[1]) < 0.4 or abs(ncy - hi[1]) < 0.4))(*_room(rn)) for rn in ROOMS)
        if not (is_bath or is_bed) or math.hypot(ncx - cx, ncy - cy) > 1.3:          # r29: the bedroom entry leaves stood open into the rooms (0-2 / 0-3 wide0: 15-40 deg of the frame): close them like the bath leaves
            continue
        thin_x = (b1[0] - b0[0]) < (b1[1] - b0[1])
        if thin_x:                                                     # leaf runs along y: hinge = the end nearer the casing centre
            hy = b0[1] if abs(b0[1] - ncy) < abs(b1[1] - ncy) else b1[1]; h = Vector((cx, hy, 0)); d = Vector((0, (b1[1] + b0[1]) - 2 * hy, 0)).normalized()
        else:
            hx = b0[0] if abs(b0[0] - ncx) < abs(b1[0] - ncx) else b1[0]; h = Vector((hx, cy, 0)); d = Vector(((b1[0] + b0[0]) - 2 * hx, 0, 0)).normalized()
        along_x = (n1[0] - n0[0]) > (n1[1] - n0[1]); t = Vector((1 if ncx > h.x else -1, 0, 0)) if along_x else Vector((0, 1 if ncy > h.y else -1, 0))
        ang = math.atan2(d.x * t.y - d.y * t.x, d.dot(t))
        if abs(ang) < 0.05:
            continue
        o.matrix_world = Matrix.Translation(h) @ Matrix.Rotation(ang, 4, "Z") @ Matrix.Translation(-h) @ o.matrix_world; closed += 1
    bpy.context.view_layer.update()
    stats["h2_bath_doors_closed"] = closed
    mould = _flat("ir_h2_oak_mould", (0.42, 0.29, 0.17), 0.45)
    for o in list(bpy.data.objects):
        if not (o.type == "MESH" and o.name.startswith(("LiteDoorFactory", "LouverDoorFactory", "GlassPanelDoorFactory", "PanelDoorFactory"))):
            continue
        b0, b1 = _bb(o); dx, dy = b1[0] - b0[0], b1[1] - b0[1]
        thin_x = dx < dy; w = dy if thin_x else dx; t = dx if thin_x else dy; z0, z1 = b0[2], b1[2]
        if w < 0.5 or z1 - z0 < 1.8:
            continue
        vene = next((sl.material for sl in o.material_slots if sl.material and "veneer" in sl.material.name), None) or _noise("ir_h2_oak", (0.62, 0.45, 0.27), (0.5, 0.35, 0.2), 30.0, 0.5)
        cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2; pan = []; hin = []
        h = z1 - z0; pw = w - 0.24; mo = []
        for zc_, ph in ((z0 + h * 0.3, h * 0.36), (z0 + h * 0.72, h * 0.36)):
            for sgn in (-1, 1):
                off = sgn * (t / 2 + 0.006); off2 = sgn * (t / 2 + 0.016)
                pan.append(("box", cx + off, cy, zc_, 0.012, pw, ph) if thin_x else ("box", cx, cy + off, zc_, pw, 0.012, ph))
                for du, dz, su, sz in ((0, ph / 2, pw + 0.04, 0.03), (0, -ph / 2, pw + 0.04, 0.03), (pw / 2, 0, 0.03, ph), (-pw / 2, 0, 0.03, ph)):     # r25: a raised moulding round each panel, darker: the panels read
                    mo.append(("box", cx + off2, cy + du, zc_ + dz, 0.02, su, sz) if thin_x else ("box", cx + du, cy + off2, zc_ + dz, su, 0.02, sz))
        cas = [_bb(c) for c in bpy.data.objects if c.type == "MESH" and c.name.startswith("DoorCasingFactory")]
        near = min(cas, key=lambda q: (((q[0][0] + q[1][0]) / 2 - cx) ** 2 + ((q[0][1] + q[1][1]) / 2 - cy) ** 2), default=None)
        if near is not None:                                            # the hinge edge = the leaf end nearer the casing centre
            ncx, ncy = (near[0][0] + near[1][0]) / 2, (near[0][1] + near[1][1]) / 2
            if thin_x:
                ey = b0[1] + 0.01 if abs(b0[1] - ncy) < abs(b1[1] - ncy) else b1[1] - 0.01; hin = [("cyl", (cx, ey, z0 + zz), (cx, ey, z0 + zz + 0.1), 0.009, 10) for zz in (0.2, h / 2, h - 0.3)]
            else:
                ex = b0[0] + 0.01 if abs(b0[0] - ncx) < abs(b1[0] - ncx) else b1[0] - 0.01; hin = [("cyl", (ex, cy, z0 + zz), (ex, cy, z0 + zz + 0.1), 0.009, 10) for zz in (0.2, h / 2, h - 0.3)]
        _fl().mesh_object(f"H2DoorPanels({o.name[:24]})", [(vene, pan), (mould, mo)] + ([(brass, hin)] if hin else []), bevel=True); n += 1
    stats["h2_door_panels"] = n
    hl, hh = _room(HALL); k = 0                                        # r25: a brass room-number plate beside each room entry, on the corridor face
    if hl is not None:
        import parking_lobby as pl_
        ink = _flat("ir_h2_plate_ink", (0.06, 0.05, 0.04), 0.5)
        for c_ in sorted(cas_all, key=lambda c_: _bb(c_)[0][0]):
            n0, n1 = _bb(c_)
            if not (n0[1] < hh[1] < n1[1] + 0.05 and n1[0] - n0[0] > n1[1] - n0[1]):     # casings in the corridor's north wall
                continue
            k += 1; yf = n0[1] - 0.004; xp = n1[0] + 0.18; zp = hl[2] + 1.5
            _fl().mesh_object(f"H2NumPlate({k})", [(brass, [("box", xp, yf - 0.004, zp, 0.28, 0.008, 0.16)]), (ink, pl_._text(f"10{k}", "N", yf - 0.009, xp - 0.07, zp, 0.09, None))], bevel=True)
    stats["h2_num_plates"] = k


def _guests(stats):
    """r25: per-room variation (port of hotel5 'guests'), deterministic per room id: fresh / checked-in (suitcase, shoes, laptop, phone + water, shirt on the chair) /
    lived-in (blanket + towel on the bed foot, book + mug on a nightstand, room-service tray, trousers on the chair); bedside lamps off in every other room."""
    import random
    out = {"fresh": 0, "checked_in": 0, "lived_in": 0}
    for rn in ROOMS:
        lo, hi = _room(rn)
        if lo is None:
            continue
        k = int(rn.split("/")[1]); rg = random.Random(2000 + k); fz = lo[2]
        state = ("checked_in", "lived_in", "fresh", "lived_in")[k % 4]; out[state] += 1
        if k == 3:                                                   # r26 #1: only one dim (lived-in, lamps off) room
            for o in bpy.data.objects:
                if o.type == "LIGHT" and o.name.startswith(f"H2Lamp({rn}|"):
                    o.data.energy = 0.0
        if state == "fresh":
            continue
        beds = _objs("SoftBedFactory", lo, hi)
        if not beds:
            continue
        cx, cy, ax, hd, L, W, b0, b1 = _bed_frame(beds[0]); zt = 0.62
        hv = (hd, 0) if ax else (0, hd)
        def pt(a, b):
            return cx + hv[0] * a - hv[1] * b, cy + hv[1] * a + hv[0] * b
        yfoot = math.atan2(-hv[1], -hv[0])
        stands = _objs("Real_nightstand", lo, hi); desks = _objs(("AboDeskFactory", "H2Desk"), lo, hi); chairs = _objs(("Real_deskchair", "AccentArmchairFactory", "AboArmchairFactory"), lo, hi)
        st = stands[rg.randrange(len(stands))] if stands else None
        def on_top(o):
            q0, q1 = _bb(o); return (q0[0] + q1[0]) / 2, (q0[1] + q1[1]) / 2, q1[2]
        if state == "checked_in":
            sx, sy = pt(-L / 2 - 0.5, W / 2 + 0.15)
            if lo[0] + 0.35 < sx < hi[0] - 0.35 and lo[1] + 0.35 < sy < hi[1] - 0.35:
                ra.abo("suitcase", k, sx, sy, fz, yfoot + rg.uniform(-0.3, 0.3), fit=(0.7, 0.45, 0.32))
            for j in range(2):
                ra.abo("shoes", k * 3 + j, *pt(-0.2 - j * 0.25, -(W / 2 + 0.3)), fz, yfoot + rg.uniform(-0.4, 0.4), fit=(0.3, 0.15, 0.15))
            if st is not None:
                x_, y_, z_ = on_top(st); ra.abo("phone", k, x_ - 0.08, y_, z_, rg.uniform(0, 6.28), fit=(0.17, 0.09, 0.02)); ra.lib("BottleFactory", k, x_ + 0.1, y_ + 0.05, z_, 0.0, 1.0)
            if desks:
                x_, y_, z_ = on_top(desks[0]); ra.abo("laptop", k, x_ - 0.15, y_, z_, rg.uniform(-0.5, 0.5), fit=(0.36, 0.27, 0.3))
            if chairs:
                x_, y_, z_ = on_top(chairs[0]); ra.soft(f"H2Shirt({k})", _flat(f"ir_h2_shirt_{k % 3}", ((0.82, 0.84, 0.88), (0.55, 0.65, 0.78), (0.86, 0.8, 0.72))[k % 3], 0.85), x_, y_, z_ + 0.035, 0.36, 0.28, 0.07, yaw=rg.uniform(0, 6.28), seed=k, puff=0.5)      # r29: Infinigen ShirtFactory is a flat 1 cm sheet (teal paper slab): a soft folded shirt
        else:
            ra.soft(f"H2Blanket({k})", _flat(f"ir_h2_blanket_{k % 2}", ((0.62, 0.5, 0.38), (0.5, 0.56, 0.62))[k % 2], 0.95), *pt(-L / 2 + 0.35, rg.uniform(-0.2, 0.2)), zt + 0.14, 0.9, 0.42, 0.1, yaw=yfoot + rg.uniform(-0.3, 0.3), seed=k + 3, puff=0.45)      # r29: a thick folded blanket, not Infinigen's zero-thickness sheet
            ra.abo("towel", k, *pt(-L / 2 + 0.2, rg.uniform(-0.3, 0.3)), zt + 0.14, rg.uniform(0, 6.28), fit=(0.4, 0.4, 0.08))
            if st is not None:
                x_, y_, z_ = on_top(st); ra.abo("book", k, x_ - 0.06, y_, z_, rg.uniform(0, 6.28), fit=(0.25, 0.18, 0.05)); ra.abo("mug", k, x_ + 0.1, y_ + 0.04, z_, rg.uniform(0, 6.28), fit=(0.12, 0.12, 0.11))
            if desks:
                x_, y_, z_ = on_top(desks[0]); tr = ra.abo("tray", k + 10, x_ + 0.2, y_, z_, rg.uniform(-0.3, 0.3), fit=(0.5, 0.36, 0.06))
                zt_ = ra.top(tr) - 0.04 if tr is not None else z_
                ra.lib("PlateFactory", 600 + k, x_ + 0.14, y_, zt_, 0.0, 0.8); ra.lib("CupFactory", 600 + k, x_ + 0.34, y_ + 0.06, zt_, rg.uniform(0, 6.28), 1.0)
            if chairs:
                x_, y_, z_ = on_top(chairs[-1]); ra.soft(f"H2Pants({k})", _flat(f"ir_h2_denim_{k % 2}", ((0.16, 0.22, 0.36), (0.2, 0.2, 0.22))[k % 2], 0.9), x_, y_, z_ + 0.045, 0.44, 0.26, 0.09, yaw=rg.uniform(0, 6.28), seed=k + 5, puff=0.5)      # r29: folded trousers instead of the flat sheet
    stats["h2_guests"] = out


def apply(stats):
    sc = bpy.context.scene
    if sc.get("ir_h2_ref") or bpy.data.objects.get(f"{ROOMS[0]}.floor") is None:
        return 0
    skip = set((os.environ.get("ROOM_H2_REF_SKIP") or "").split(",")); n = 0
    for key, fn in (("bed", _bed), ("carpet", _carpet), ("floor", _floor), ("walls", _walls), ("ceil", _ceil), ("window", _window), ("furn", _furn), ("corr", _corr), ("art", _art), ("doors", _doors), ("bath", _bath), ("guests", _guests)):
        if key in skip:
            continue
        try:
            bpy.context.view_layer.update(); fn(stats); n += 1
        except Exception as ex:                                  # noqa: BLE001 -- a part that fails must not sink the kit stage
            import traceback; traceback.print_exc()
            stats[f"h2_{key}_error"] = repr(ex)[:160]
    sc["ir_h2_ref"] = 1
    return n
