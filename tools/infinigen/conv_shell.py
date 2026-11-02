"""S37 convenience-store shell (kit stage, idempotent via scene["ir_conv_shell"]); every part has its own flag, all opt-in.

ROOM_CONV_CEIL=1    swap the square LED panels (CeilingGridFactory + its area lights) for 6 long linear LED strips across the room (ROOM_CONV_LED_W per strip, default 20), recessed
                    downlights (emissive discs) and one 4-way cassette AC; the room's other lights are scaled by ROOM_CONV_LIGHT_X (default 1)
ROOM_CONV_SLATS=1   walnut vertical slat panels (4 cm slats, 1 cm gaps) on the back (high y) and right (high x) walls from 2.35 m to the ceiling
ROOM_CONV_NOSIGNS=1 delete the hanging CategorySign boards (the ref has none; the header bands sit on the units)
ROOM_PEG_LIB=1      pegboard endcaps hang real library bags / boxes instead of flat cards
ROOM_CONV_NOCOL=1   delete every ColumnFactory / RoundPillarFactory (the ref sales floor has no columns)
ROOM_CONV_REF=1     reference-similarity pass (S37 r9 refs_answer, user 10-25); ROOM_CONV_REF_SKIP=<blank,headers,counters,checkout,coffee,floor,cams,plants> switches parts off:
                    blank = header boards without words; headers = full-length yellow top bands on gondolas / endcaps; counters = checkout + coffee counters black with a yellow front;
                    checkout = POS screen, card terminal, impulse rack; coffee = 2 coffee machines, cup towers, pastry dome, fruit bowl, supply shelves, blank coffee lightbox;
                    floor = 70 cm grey square tile; cams = 2 ceiling dome cameras. ROOM_CONV_SLAT_TINT="r,g,b" warms the walnut slats (default 1.0,0.9,0.8).
Geometry from break-room_0/0 floor / ceiling bbox (back wall = high y, right wall = high x, shopfront = low y / low x).
"""
from __future__ import annotations

import math
import os

import bpy
from mathutils import Vector

ROOM = "break-room_0/0"


def _bb(name):
    o = bpy.data.objects.get(name)
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def _ceiling(lo, hi, zc, stats):
    from room_planner import proc_boutique_flagship as fl
    from room_planner import proc_assets as pa
    bpy.context.view_layer.update()                       # background mode: matrix_world of parented lights is stale until updated
    n = 0
    for o in list(bpy.data.objects):
        if o.name.startswith(("CeilingGridFactory", "LinearLedFactory", "DiffuserFactory", "DropCeilingFactory", "CeilingLightFactory")):
            bpy.data.objects.remove(o, do_unlink=True); n += 1
    k = float(os.environ.get("ROOM_CONV_LIGHT_X") or 1.0)
    for ld in [o for o in bpy.data.objects if o.type == "LIGHT" and o.data.type == "AREA" and not o.name.startswith("ir_conv")]:         # single room: every area light is a ceiling panel light (matrix_world of parented lights is unreliable in background mode)
        bpy.data.objects.remove(ld, do_unlink=True)
    for ld in [o for o in bpy.data.objects if o.type == "LIGHT" and o.data.type != "SUN"]:
        ld.data.energy *= k
    glow = pa._flat("ir_conv_led", (1.0, 0.98, 0.94), 0.4); b = glow.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (1.0, 0.92, 0.80, 1)
    b.inputs["Emission Strength"].default_value = 1.5
    disc_glow = glow.copy()
    disc_glow.name = "ir_conv_downlight"
    disc_glow.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value = (1.0, 0.98, 0.94, 1)
    disc_glow.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 1.0
    white = pa._flat("ir_conv_ac", (0.9, 0.9, 0.88), 0.4); dark = pa._flat("ir_conv_ac_louver", (0.1, 0.1, 0.11), 0.5)
    W = float(os.environ.get("ROOM_CONV_LED_W") or 20)
    x0, x1, y0, y1 = lo[0] + 0.6, hi[0] - 0.6, lo[1] + 0.8, hi[1] - 0.8
    strips, discs = [], []
    for j in range(6):
        y = y0 + (y1 - y0) * (j + 0.5) / 6; strips.append(("box", (x0 + x1) / 2, y, zc - 0.03, x1 - x0, 0.06, 0.04))
        ld = bpy.data.lights.new(f"ir_conv_strip_{j}", "AREA"); ld.shape = "RECTANGLE"; ld.size = x1 - x0; ld.size_y = 0.08; ld.energy = W; ld.color = (1.0, 0.92, 0.80)
        o = bpy.data.objects.new(ld.name, ld); o.location = ((x0 + x1) / 2, y, zc - 0.07); o.rotation_euler = (0, 0, 0); bpy.context.scene.collection.objects.link(o)
        for i in range(5):
            x = x0 + (x1 - x0) * (i + 0.5) / 5; yy = y + (y1 - y0) / 12 * (1 if i % 2 else -1)
            discs.append(("cyl", (x, yy, zc - 0.02), (x, yy, zc - 0.035), 0.055, 16))
    cx, cy = (lo[0] + hi[0]) / 2, hi[1] - 1.6
    ac = [("box", cx, cy, zc - 0.07, 0.9, 0.9, 0.14)]
    louv = [("box", cx + dx, cy + dy, zc - 0.145, sx, sy, 0.012) for dx, dy, sx, sy in ((0, 0.4, 0.8, 0.05), (0, -0.4, 0.8, 0.05), (0.4, 0, 0.05, 0.8), (-0.4, 0, 0.05, 0.8))]
    fl.mesh_object("ConvLinearLed", [(glow, strips), (disc_glow, discs)], bevel=False); fl.mesh_object("ConvCassetteAC", [(white, ac), (dark, louv)], bevel=False)
    stats["conv_ceiling"] = {"removed": n, "strips": 6, "downlights": len(discs), "strip_W": W, "direction": "-Z"}


def _slats(lo, hi, zc, stats):
    import scanned_wood as sw
    import wall_face
    lo, hi = wall_face.inner_box(ROOM)
    from room_planner import proc_boutique_flagship as fl
    tint = tuple(float(v) for v in (os.environ.get("ROOM_CONV_SLAT_TINT") or "1.0,0.9,0.8").split(","))     # S37 ref: the ref slats are warmer / redder walnut
    m = sw.material("walnut", size_m=1.0, tint=tint, rough=(0.35, 0.55), space="object", grain="z")
    z0, z1 = 2.35, zc - 0.05; h = z1 - z0; pitch, w, t = 0.075, 0.055, 0.028; prims = []
    n = int((hi[0] - lo[0]) // pitch)
    for i in range(n):
        prims.append(("box", lo[0] + pitch * (i + 0.5), hi[1] - 0.005 - t / 2, z0 + h / 2, w, t, h))
    n = int((hi[1] - lo[1]) // pitch)
    for i in range(n):
        prims.append(("box", hi[0] - 0.005 - t / 2, lo[1] + pitch * (i + 0.5), z0 + h / 2, t, w, h))
    backing = fl._flat("ir_conv_slat_back", (0.06, 0.04, 0.03), 0.8)
    bk = [("box", (lo[0] + hi[0]) / 2, hi[1] - 0.003, z0 + h / 2, hi[0] - lo[0], 0.004, h), ("box", hi[0] - 0.003, (lo[1] + hi[1]) / 2, z0 + h / 2, 0.004, hi[1] - lo[1], h)]
    fl.mesh_object("ConvWalnutSlats", [(m, prims), (backing, bk)], bevel=False); stats["conv_slats"] = len(prims)


def _floor(stats):
    """ROOM_CONV_FLOOR=<grey> (default 0.62): multiply the floor tile's colour by a neutral grey (the ref is a mid-light grey 60 cm tile with dark grout; the texturecan tile reads near white)."""
    g = float(os.environ.get("ROOM_CONV_FLOOR") or 0.62)
    o = bpy.data.objects.get(f"{ROOM}.floor")
    for sl in o.material_slots:
        m = sl.material
        if m is None or not m.use_nodes or m.get("conv_floor"):
            continue
        nt = m.node_tree; b = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is None:
            continue
        mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs["Factor"].default_value = 1.0; mx.inputs["B"].default_value = (g, g, g, 1)
        lk = b.inputs["Base Color"].links
        if lk:
            src = lk[0].from_socket; nt.links.remove(lk[0]); nt.links.new(src, mx.inputs["A"])
        else:
            mx.inputs["A"].default_value = b.inputs["Base Color"].default_value
        nt.links.new(mx.outputs["Result"], b.inputs["Base Color"]); m["conv_floor"] = 1; m["weathered"] = True
    stats["conv_floor"] = g


def _peg_items(stats):
    """ROOM_PEG_LIB=1: the pegboard endcaps' flat coloured cards (faces on the ir_peg_card_* materials) are cut away and real library snack bags / small boxes (data/object_library_v2, pack_atlas labels)
    hang on the 25 hooks instead (hook grid from PegboardEndcapFactory: y = -0.45 + 0.1 + q * 0.17, z = 0.28 + row * 0.27 + 0.1, board at local x = -0.23, front +X)."""
    import bmesh
    import random
    from mathutils import Matrix
    from room_planner import lib_objects
    fb, bx = lib_objects.factory("FoodBagFactory"), lib_objects.factory("FoodBoxFactory")
    if fb is None:
        return
    n = 0
    for F in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("PegboardEndcapFactory")]:
        me = F.data; bm = bmesh.new(); bm.from_mesh(me)
        dead = [f for f in bm.faces if f.material_index < len(me.materials) and me.materials[f.material_index] and me.materials[f.material_index].name.startswith("ir_peg_card")]
        if dead:
            bmesh.ops.delete(bm, geom=dead, context="FACES")
        bm.to_mesh(me); bm.free()
        r = random.Random(hash(F.name) & 0xffff)
        faces = (1, -1) if os.environ.get("ROOM_PEG_BOTH") == "1" else (1,)                  # S37 r4: the board's back face carries items too (it stood as a blank black slab from the aisle)
        full = os.environ.get("ROOM_PEG_BOTH") == "1"
        dense = os.environ.get("ROOM_PEG_DENSE") == "1"                                  # S37 r5: 6 rows of larger packs (0.165 x 0.235 m) so the 0.9 x 1.7 m board reads full
        for fs_, row, q in [(f_, rw_, qq_) for f_ in faces for rw_ in range(6 if dense else 5) for qq_ in range(5)]:
            if True:
                if not full and r.random() < 0.12:
                    continue
                fac = (fb if (bx is None or r.random() < 0.6) else bx)(r.randrange(1 << 20))
                o = fac.spawn_asset(n)
                k = min((0.165 if dense else 0.14) / max(o.dimensions.x, o.dimensions.y, 1e-3), (0.235 if dense else 0.2) / max(o.dimensions.z, 1e-3), 1.6 if dense else 1.0)
                hz = (0.34 + row * 0.25 + 0.1) if dense else (0.28 + row * 0.27 + 0.1); hy = -0.45 + 0.1 + q * 0.17
                o.rotation_euler = (0, 0, math.pi / 2 + r.uniform(-0.1, 0.1)); o.scale = (k, k, k)
                bpy.context.view_layer.update()
                o.matrix_world = F.matrix_world @ Matrix.Translation((-0.23 + 0.07 * fs_ - (0.0 if fs_ == 1 else 0.03), hy * fs_, hz - o.dimensions.z)) @ Matrix.Rotation((math.pi / 2 if fs_ == 1 else -math.pi / 2) + r.uniform(-0.1, 0.1), 4, "Z") @ Matrix.Scale(k, 4)
                n += 1
    stats["conv_peg_items"] = n


def _obb(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def _flat(name, rgb, rough=0.5, metal=0.0, emit=0.0, transmission=0.0, plain=False):
    from room_planner import proc_assets as pa
    m = pa._flat(name, rgb, rough, metal, transmission=transmission); m["weathered"] = True
    if plain:                                                          # S37 r15: _flat's scanned-luminance colour mix read as grey wood grain on the black top and mustard on the yellow
        b = m.node_tree.nodes["Principled BSDF"]
        for l_ in list(b.inputs["Base Color"].links):
            m.node_tree.links.remove(l_)
        b.inputs["Base Color"].default_value = (*rgb, 1)
    if emit:
        b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Emission Color"].default_value = (*rgb, 1); b.inputs["Emission Strength"].default_value = emit
    if name in ("ir_conv_yellow", "ir_conv_yellow_hdr"):
        _paint_yellow(m)
    return m


YELLOW = (0.98, 0.78, 0.005)
YELLOW_GLOW = 0.0


def _paint_yellow(m):
    b = m.node_tree.nodes["Principled BSDF"]
    for name in ("Base Color", "Normal"):
        for link in list(b.inputs[name].links):
            m.node_tree.links.remove(link)
    b.inputs["Base Color"].default_value = (*YELLOW, 1)
    b.inputs["Emission Strength"].default_value = 0
    b.inputs["Roughness"].default_value = 0.35
    b.inputs["Specular IOR Level"].default_value = 0.5


def _blank_headers(stats):
    """The header boards keep their yellow, the dark stroke words go (refs: blank yellow fascia, no DAIRY / GIFT / DELI)."""
    import bmesh
    k = 0
    for o in [o for o in bpy.data.objects if o.type == "MESH" and any(sl.material and sl.material.name == "ir_header_ink_dark" for sl in o.material_slots)]:
        idx = [i for i, sl in enumerate(o.material_slots) if sl.material and sl.material.name == "ir_header_ink_dark"]
        bm = bmesh.new(); bm.from_mesh(o.data)
        dead = [f for f in bm.faces if f.material_index in idx]
        bmesh.ops.delete(bm, geom=dead, context="FACES"); bm.to_mesh(o.data); bm.free(); k += len(dead)
    stats["conv_ref_glyph_faces_cut"] = k


def _pa_style():
    from room_planner import proc_assets as pa
    return pa.STYLE


def _headers(stats):
    """Full-length yellow fascia on top of every gondola, wall gondola and pegboard endcap (refs: every unit wears a continuous yellow top band on both faces)."""
    from room_planner import proc_boutique_flagship as fl
    y = _flat("ir_conv_yellow", YELLOW, 0.45, emit=YELLOW_GLOW, plain=True); prims = []
    import bmesh
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("GondolaFactory", "WallGondolaFactory"))]:
        hi_ = [i for i, sl in enumerate(o.material_slots) if sl.material and sl.material.name.startswith("ir_header_") and not sl.material.name.startswith("ir_header_ink")]
        if not hi_:
            continue                                                    # S37 r12: the raised end header board + its two rods stood up as tall yellow flaps over every end: cut them
        bm = bmesh.new(); bm.from_mesh(o.data)
        hz = min((min(v.co.z for v in f.verts) for f in bm.faces if f.material_index in hi_), default=None)
        if hz is not None:
            ymax = max(v.co.y for v in bm.verts)
            dead = [f for f in bm.faces if f.material_index in hi_ or (min(v.co.z for v in f.verts) >= hz - 0.06 and min(v.co.y for v in f.verts) >= ymax - 0.05)]
            bmesh.ops.delete(bm, geom=dead, context="FACES"); bm.to_mesh(o.data); stats["conv_ref_end_headers_cut"] = stats.get("conv_ref_end_headers_cut", 0) + 1
        bm.free()
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("PegboardEndcapFactory")]:     # S37 r14 #1: the open endcap's header stood ~8 cm proud and met the gondola band at an angle: drop it flush
        hi_ = [i for i, sl in enumerate(o.material_slots) if sl.material and sl.material.name == "ir_conv_yellow_hdr"]
        if not hi_:
            continue
        bm = bmesh.new(); bm.from_mesh(o.data)
        vs = {v for f in bm.faces if f.material_index in hi_ for v in f.verts}
        body_top = max((v.co.z for v in bm.verts if v not in vs), default=None)
        if vs and body_top is not None:
            dz = body_top - max(v.co.z for v in vs) - 0.005
            for v in vs:
                v.co.z += dz
            bm.to_mesh(o.data); stats["conv_ref_endcap_hdr_lowered"] = stats.get("conv_ref_endcap_hdr_lowered", 0) + 1
        bm.free()
    for nm_ in ("ir_conv_yellow_hdr", "ir_conv_yellow"):                     # r14 #1: 'dull mustard' -> the checkout's saturated yellow with a faint print glow
        m_ = bpy.data.materials.get(nm_) or (_flat(nm_, YELLOW, 0.45) if nm_ == "ir_conv_yellow" else None)
        if m_ is not None and m_.use_nodes:
            b_ = m_.node_tree.nodes.get("Principled BSDF")
            if b_ is not None:
                _paint_yellow(m_)                    # r14's (1.0, 0.78, 0) + 0.15 glow here overrode YELLOW on every header: the mustard (S37 r17)
    bpy.context.view_layer.update()
    own_hdr = lambda o_: any(sl.material and sl.material.name == "ir_conv_yellow_hdr" for sl in o_.material_slots)    # S37 r16: pa.STYLE is empty at kit stage, so endcap_open read False and the open endcaps got a second board on top of their own header (the tall near board in wide0)
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("GondolaFactory", "WallGondolaFactory", "PegboardEndcapFactory")) and not own_hdr(o)]:
        b0, b1 = _obb(o); dx, dy = b1[0] - b0[0], b1[1] - b0[1]; cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
        zt = b1[2] - 0.02 if not o.name.startswith("PegboardEndcap") else b1[2]
        t, hh = 0.02, 0.18                                            # S37 r11: a thin board on each long face, not a capped volume (refs: ~25 cm x 2 cm fascia, frame visible behind)
        if dx >= dy:
            prims += [("box", cx, cy + s_ * (dy / 2 + t / 2), zt - hh / 2 + 0.01, dx, t, hh) for s_ in (-1, 1)]
        else:
            prims += [("box", cx + s_ * (dx / 2 + t / 2), cy, zt - hh / 2 + 0.01, t, dy, hh) for s_ in (-1, 1)]
    fl.mesh_object("ConvYellowFascia", [(y, prims)], bevel=False); stats["conv_ref_fascias"] = len(prims)
    ycm = bpy.data.materials.get("ir_conv_yellow")                          # S37 r19: one datablock for every yellow (counter front, fascias, the gondolas' own header boards ir_header_*, endcap headers): the reviewer saw the gondola boards as dull mustard next to the counter front
    nsw = 0
    if ycm is not None:
        for o_ in bpy.data.objects:
            if o_.type == "MESH" and o_.name.startswith(("GondolaFactory", "WallGondolaFactory", "PegboardEndcapFactory")):
                for i_, m_ in enumerate(o_.data.materials):
                    if m_ is not None and m_ is not ycm and (m_.name.startswith("ir_header_") and not m_.name.startswith("ir_header_ink") or m_.name == "ir_conv_yellow_hdr"):
                        o_.data.materials[i_] = ycm; nsw += 1
    stats["conv_ref_yellow_unified"] = nsw


def _counters():
    cs = sorted([o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("CheckoutCounterFactory", "CafeCounterFactory"))], key=lambda o: _obb(o)[0][0])
    return cs


def _top_z(o):
    zs = [(o.matrix_world @ v.co).z for v in o.data.vertices]
    b0, b1 = _obb(o)
    top = [z for z in zs if z < b0[2] + 1.15]                           # ignore the packs / screen standing on it
    return max(top) if top else b1[2]


def _counter_paint(stats):
    black = _flat("ir_conv_counter_black", (0.035, 0.035, 0.04), 0.4, plain=True); top = _flat("ir_conv_counter_top_matte", (0.025, 0.025, 0.028), 0.55, plain=True)      # r14 #2: the glossy 0.08 top mirrored the LED ceiling and read as a pale grey wood slab
    from room_planner import proc_boutique_flagship as fl
    y = _flat("ir_conv_yellow", YELLOW, 0.45, emit=YELLOW_GLOW, plain=True); prims = []
    for o in _counters():
        o.data = o.data.copy()
        for i, sl in enumerate(o.material_slots):
            if sl.material and sl.material.name.startswith(("ir_checkout_wood", "ir_cafe_counter", "ir_counter")):
                o.data.materials[i] = black
            elif sl.material and sl.material.name.startswith(("ir_checkout_top", "ir_counter_top")):
                o.data.materials[i] = top
        b0, b1 = _obb(o); zt = _top_z(o)
        prims.append(("box", (b0[0] + b1[0]) / 2, b0[1] - 0.012, b0[2] + (zt - b0[2]) * 0.55, b1[0] - b0[0] - 0.1, 0.02, (zt - b0[2]) * 0.5))      # yellow front band, customer side (-y)
    fl.mesh_object("ConvCounterYellow", [(y, prims)], bevel=False); stats["conv_ref_counters"] = len(prims)


def _checkout(stats):
    cs = _counters()
    if not cs:
        return
    o = cs[0]; b0, b1 = _obb(o); zt = _top_z(o); cx = (b0[0] + b1[0]) / 2; yb = b1[1] - 0.3
    from room_planner import proc_boutique_flagship as fl
    dark = _flat("ir_conv_pos_body", (0.05, 0.05, 0.055), 0.4); scr = _flat("ir_conv_pos_screen", (0.25, 0.45, 0.7), 0.2, emit=1.5); grey = _flat("ir_conv_pos_grey", (0.35, 0.35, 0.37), 0.4)
    pos = [("cyl", (cx - 0.3, yb, zt), (cx - 0.3, yb, zt + 0.25), 0.03, 10), ("box", cx - 0.3, yb, zt + 0.02, 0.22, 0.18, 0.04), ("box", cx - 0.3, yb, zt + 0.42, 0.36, 0.05, 0.26)]
    screen = [("box", cx - 0.3, yb - 0.028, zt + 0.42, 0.33, 0.005, 0.23)]
    term = [("box", cx + 0.15, b0[1] + 0.18, zt + 0.06, 0.08, 0.16, 0.1)]; termk = [("box", cx + 0.15, b0[1] + 0.105, zt + 0.08, 0.06, 0.005, 0.05)]
    ty = b0[1] + 0.16
    rack = []
    import random
    rg = random.Random(37)
    import real_assets as ra
    groups = {i: [] for i in range(5)}
    cols = []
    count = 0
    if os.environ.get("RATIO1_CHECKOUT") != "1":
        for tray in range(3):
            tx = b0[0] + 0.40 + tray * 0.35
            rack.append(("box", tx, ty, zt + 0.012, 0.32, 0.26, 0.024))
            for j in range(8):
                x, y = tx - 0.105 + (j % 4) * 0.07, ty - 0.055 + (j // 4) * 0.11
                o_ = ra.lib(("FoodBagFactory", "FoodBoxFactory")[(tray + j) % 2],
                            300 + tray * 8 + j, x, y, zt + 0.026)
                if o_ is None:
                    raise RuntimeError("S37 labelled checkout pack unavailable")
                ra._stand(o_, x, y, zt + 0.026, rg.uniform(-0.08, 0.08), (0.065, 0.10, 0.16))
                o_.name = f"ConvCheckoutPack_{tray}_{j}"
                count += 1
    stats["conv_checkout_packs"] = count
    fl.mesh_object("ConvCheckoutKit", [(dark, pos + term + rack), (scr, screen), (grey, termk)], bevel=False)
    stats["conv_ref_checkout"] = 1


def _coffee(lo, hi, stats):
    cs = _counters()
    if len(cs) < 2:
        return
    o = cs[1]; b0, b1 = _obb(o); zt = _top_z(o); yb = b0[1] + 0.35; x0 = b0[0] + 0.25
    from room_planner import proc_boutique_flagship as fl
    blk = _flat("ir_conv_cm_body", (0.04, 0.04, 0.045), 0.35); steel = _flat("ir_conv_cm_steel", (0.75, 0.75, 0.78), 0.25, 1.0); disp = _flat("ir_conv_cm_disp", (0.3, 0.6, 0.95), 0.3, emit=2.0)
    white = _flat("ir_conv_cup_white", (0.95, 0.95, 0.93), 0.4); kraft = _flat("ir_conv_cup_kraft", (0.55, 0.38, 0.22), 0.7); glass = _flat("ir_conv_dome", (0.9, 0.93, 0.95), 0.03, transmission=0.9)
    bun = _flat("ir_conv_bun", (0.62, 0.38, 0.15), 0.6); tray = _flat("ir_conv_tray", (0.2, 0.2, 0.2), 0.4)
    fr = [_flat("ir_conv_fruit_o", (0.95, 0.45, 0.05), 0.5), _flat("ir_conv_fruit_y", (0.95, 0.85, 0.15), 0.5), _flat("ir_conv_fruit_r", (0.75, 0.08, 0.06), 0.5)]
    mach, stl, dsp, cups, kr, dome, buns, tr = [], [], [], [], [], [], [], []
    import real_assets as ra
    for k in range(2):                                                    # 2 coffee machines on the back half: scanned HSSD espresso / coffee machines (asset QA rev2 CV-1a), box only as the fallback
        mx = x0 + 0.25 + k * 0.55
        machine = ra.hssd(r"espresso machine|coffee machine|coffee maker|gaggia|espressione", 50 + k, mx, yb, zt, -math.pi / 2, fit=(0.45, 0.45, 0.6), cats=("coffee_machine", "coffee_maker"), size=(0.28, 0.7), grow=True)
        if machine is not None:
            machine.name = f"ConvCoffeeMachine_{k}"
            continue
        mach.append(("box", mx, yb, zt + 0.32, 0.42, 0.42, 0.64)); stl.append(("box", mx, yb - 0.215, zt + 0.25, 0.3, 0.01, 0.28)); stl.append(("box", mx, yb - 0.17, zt + 0.02, 0.3, 0.12, 0.03))
        dsp.append(("box", mx, yb - 0.215, zt + 0.5, 0.18, 0.006, 0.1))
    cx = b0[0] + 1.35
    for k in range(2):                                                    # cup towers: the scanned paper hot cups stacked 6 high (CV-1b), cylinders only as the fallback
        zc_ = zt; ok_ = True
        for j in range(6):
            o_ = ra.hssd(r"hot cups", 0, cx + k * 0.25, yb, zc_, 0.0, fit=(0.10, 0.10, 0.14), grow=True)
            if o_ is None:
                ok_ = False; break
            o_.name = f"ConvCoffeeCup_{k}_{j}"
            zc_ = zc_ + 0.035
        if ok_:
            continue
        for j in range(9):
            (cups if k == 0 else kr).append(("cyl", (cx + k * 0.14, yb, zt + j * 0.035), (cx + k * 0.14, yb, zt + j * 0.035 + 0.04), 0.045 - 0.0005 * j, 14))
    px = b1[0] - 0.35; py = b0[1] + 0.3                                    # pastry: a scanned cake stand + donuts (CV-1c); tray / dome / bun cylinders only as the fallback
    st_ = ra.hssd(r"^2 tier cake stand|cake stand", 3, px, py, zt, 0.0, fit=(0.32, 0.32, 0.3), cats=("tray",))
    if st_ is not None:
        ra.hssd(r"food buffet donuts$|food buffet donuts ", 4, px, py, zt + 0.002, 0.3, fit=(0.2, 0.2, 0.1), cats=("food", "teapot"))
    else:
        tr.append(("cyl", (px, py, zt), (px, py, zt + 0.02), 0.2, 24)); dome.append(("cyl", (px, py, zt + 0.02), (px, py, zt + 0.2), 0.19, 24))
        for i in range(6):
            a = i * 1.05; buns.append(("cyl", (px + 0.1 * math.cos(a), py + 0.1 * math.sin(a), zt + 0.02), (px + 0.1 * math.cos(a), py + 0.1 * math.sin(a), zt + 0.07), 0.045, 10))
    fx, fy = px - 0.45, py; bowl = [("cyl", (fx, fy, zt), (fx, fy, zt + 0.08), 0.16, 20)]; fruits = {0: [], 1: [], 2: []}
    def _fit(o, size):                                                    # S37 r12: library fruit came in at 2-8 m (their own units); scale every piece to its real size
        if o is not None and max(o.dimensions) > 0:
            o.scale = tuple(v * size / max(o.dimensions) for v in o.scale)
        return o
    if _fit(ra.lib("BowlFactory", 71, fx, fy, zt, 0.0, 1.0), 0.28) is not None:
        bowl = []
        for i in range(6):
            a = i * 1.05
            _fit(ra.lib(("LibAppleFactory", "LibFruitFactory")[i % 2], 80 + i, fx + 0.06 * math.cos(a), fy + 0.06 * math.sin(a), zt + 0.03, a, 1.0), (0.075, 0.1)[i % 2])
    for i in range(7 if bowl else 0):
        a = i * 0.9; r_ = 0.08 if i < 6 else 0.0
        fruits[i % 3].append(("cyl", (fx + r_ * math.cos(a), fy + r_ * math.sin(a), zt + 0.07), (fx + r_ * math.cos(a), fy + r_ * math.sin(a), zt + 0.14), 0.04, 10))
    yw = hi[1] - 0.17; xs0, xs1 = b0[0] + 0.1, b1[0] - 0.1; shelves, stock = [], []        # supply shelving on the back wall over the counter + a blank coffee lightbox above it
    for z in (zt + 0.45, zt + 0.75):
        shelves.append(("box", (xs0 + xs1) / 2, yw, z, xs1 - xs0, 0.28, 0.025))
        x = xs0 + 0.08
        while x < xs1 - 0.12:                                             # supply stock: library cartons / cans (CV-1d), a box only when the library misses
            o_ = ra.lib(("FoodBoxFactory", "CanFactory", "FoodBoxFactory")[int(x * 7) % 3], 400 + int(x * 100) + int(z * 10), x + 0.06, yw, z + 0.0125, 0.0, 1.0)
            if o_ is not None and max(o_.dimensions) > 0:
                o_.scale = tuple(v * 0.14 / max(o_.dimensions) for v in o_.scale)
            else:
                stock.append(("box", x + 0.06, yw, z + 0.08, 0.12, 0.22, 0.14))
            x += 0.15
    lb = _flat("ir_conv_coffee_lightbox", (0.42, 0.24, 0.11), 0.5, emit=1.2); cream = _flat("ir_conv_coffee_cream", (0.95, 0.88, 0.72), 0.5, emit=1.5)
    lx = (b0[0] + b1[0]) / 2; lz = zt + 1.18
    light = [("box", lx, hi[1] - 0.04, lz, 1.4, 0.06, 0.42)]; cup = [("cyl", (lx - 0.35, hi[1] - 0.075, lz - 0.12), (lx - 0.35, hi[1] - 0.075, lz + 0.1), 0.08, 18), ("box", lx + 0.2, hi[1] - 0.075, lz, 0.6, 0.006, 0.05), ("box", lx + 0.1, hi[1] - 0.075, lz - 0.1, 0.4, 0.006, 0.03)]
    fl.mesh_object("ConvCoffeeStation", [(blk, mach + shelves), (steel, stl), (disp, dsp), (white, cups), (kraft, kr + stock), (tray, tr + bowl), (glass, dome), (bun, buns), (lb, light), (cream, cup)]
                   + [(fr[i], fruits[i]) for i in range(3)], bevel=False)
    stats["conv_ref_coffee"] = 1


def _ref_floor(stats):
    """Warm stone tiles in world metres; geometry and navigation stay fixed."""
    name = "ir_conv_floor_S37b"
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        N, L = m.node_tree.nodes, m.node_tree.links
        bs = N["Principled BSDF"]
        geo = N.new("ShaderNodeNewGeometry")
        brick = N.new("ShaderNodeTexBrick")
        brick.offset = 0.0
        brick.offset_frequency = 1
        brick.inputs["Scale"].default_value = 1.0
        brick.inputs["Brick Width"].default_value = 0.60
        brick.inputs["Row Height"].default_value = 0.60
        brick.inputs["Mortar Size"].default_value = 0.004
        brick.inputs["Color1"].default_value = (0.312, 0.3016, 0.2808, 1)
        brick.inputs["Color2"].default_value = (0.288, 0.2784, 0.2592, 1)
        brick.inputs["Mortar"].default_value = (0.11, 0.105, 0.10, 1)
        L.new(geo.outputs["Position"], brick.inputs["Vector"])
        noise = N.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 1.0
        noise.inputs["Detail"].default_value = 2.0
        L.new(geo.outputs["Position"], noise.inputs["Vector"])
        tone = N.new("ShaderNodeMapRange")
        tone.inputs["To Min"].default_value = 0.98
        tone.inputs["To Max"].default_value = 1.02
        L.new(noise.outputs["Fac"], tone.inputs["Value"])
        mix = N.new("ShaderNodeMixRGB")
        mix.blend_type = "MULTIPLY"
        mix.inputs[0].default_value = 1.0
        L.new(brick.outputs["Color"], mix.inputs[1])
        L.new(tone.outputs["Result"], mix.inputs[2])
        L.new(mix.outputs["Color"], bs.inputs["Base Color"])
        rough = N.new("ShaderNodeMapRange")
        rough.inputs["To Min"].default_value = 0.24
        rough.inputs["To Max"].default_value = 0.38
        L.new(noise.outputs["Fac"], rough.inputs["Value"])
        L.new(rough.outputs["Result"], bs.inputs["Roughness"])
        bump = N.new("ShaderNodeBump")
        bump.inputs["Distance"].default_value = 0.0003
        bump.inputs["Strength"].default_value = 0.4
        bump.invert = True
        L.new(brick.outputs["Fac"], bump.inputs["Height"])
        L.new(bump.outputs["Normal"], bs.inputs["Normal"])
        m["weathered"] = True
    o = bpy.data.objects.get(f"{ROOM}.floor")
    for sl in o.material_slots:
        sl.material = m
    stats["conv_ref_floor"] = 0.60


def _cams(lo, hi, zc, stats):
    from room_planner import proc_boutique_flagship as fl
    w = _flat("ir_conv_cam_base", (0.92, 0.92, 0.9), 0.4); d = _flat("ir_conv_cam_dome", (0.05, 0.05, 0.06), 0.1)
    import real_assets as ra
    zc = _bb(f"{ROOM}.ceiling")[0][2]                                     # the ceiling's underside (the caller passes its top: the old domes sat inside the slab)
    pts = ((lo[0] + 2.0, hi[1] - 1.2), (hi[0] - 2.5, lo[1] + 1.5)); a, b = [], []; nr = 0
    for i, (x, y) in enumerate(pts):                                       # asset QA rev2 CV-5: scanned dome CCTV (HSSD), hung upside down from the ceiling
        o = ra.hssd(r"dome cctv camera", 40 + i, x, y, 0.0, 0.0, cats=("security_camera", "camera"))
        if o is not None:
            o.rotation_euler = (math.pi, 0, 0); bpy.context.view_layer.update()                 # flipped, then its top (the mounting base) pushed up to the ceiling's underside
            o.location.z += zc - max((o.matrix_world @ Vector(c)).z for c in o.bound_box); nr += 1
            continue
        a.append(("cyl", (x, y, zc - 0.03), (x, y, zc), 0.08, 20)); b.append(("cyl", (x, y, zc - 0.11), (x, y, zc - 0.03), 0.065, 20))
    if a:
        fl.mesh_object("ConvSecurityCams", [(w, a), (d, b)], bevel=False)
    stats["conv_ref_cams"] = {"real": nr, "prim": len(a)}


def _plants(lo, hi, stats):
    """S37 r14 #7 / r18: potted plants from the plant library, grown to a real height (the library returned ~0.3 m for a 0.55 m request) and re-drawn when the pick is a sprawling stalk (r17: a bent stem poked across the doorway)."""
    from room_planner import plant_lib2
    import real_assets as ra

    def _dims(o):
        c = [Vector(v) for v in o.bound_box]; sc = o.scale
        return [(max(q[i] for q in c) - min(q[i] for q in c)) * sc[i] for i in range(3)]

    def _pick(kind, seed0, idx, h):
        for t in range(5):
            pl = plant_lib2.plant(kind, seed0 + 13 * t, idx + t, h=h)
            if pl is None:
                continue
            d = _dims(pl)
            if d[2] > 1e-3 and max(d[0], d[1]) <= 0.85 * d[2]:           # upright, not a sprawling stalk
                if d[2] < 0.9 * h:                                        # library under-delivers height: scale up
                    k = h / d[2]; pl.scale = tuple(v * k for v in pl.scale)
                return pl
            bpy.data.objects.remove(pl, do_unlink=True)
        ra._count("plant_lib2:" + kind, False, "(conv plant) ")
        return None
    n = 0
    spots = [(lo[0] + 2.25, lo[1] + 0.5, 1.4), (hi[0] - 0.5, lo[1] + 0.5, 1.5), (lo[0] + 0.45, hi[1] - 0.45, 1.6), (hi[0] - 0.45, (lo[1] + hi[1]) / 2, 1.5),
             (hi[0] - 0.5, hi[1] - 0.5, 1.8), (lo[0] + 0.5, (lo[1] + hi[1]) / 2 + 1.2, 1.3)]           # r18: entrance, window corners, right wall: 1.3-1.8 m
    for i, (x, y, h) in enumerate(spots):
        pl = _pick("floor", 160 + 7 * i, i, h)
        if pl is not None:
            pl.location = (x, y, 0.0); n += 1
    cs = _counters()
    if cs:                                                               # a small desk plant on the checkout end
        b0, b1 = _obb(cs[0]); pl = plant_lib2.plant("desk", 180, 4, h=0.35)
        if pl is not None:
            pl.location = (b1[0] - 0.2, (b0[1] + b1[1]) / 2, _top_z(cs[0])); n += 1
    stats["conv_ref_plants"] = n


def _endcap_hdr(stats):
    """S37 r15: the open-endcap header (proc_grocery ir_conv_yellow_hdr) stood above the unit in a duller yellow: same saturated plain yellow, top flush with the unit."""
    m = bpy.data.materials.get("ir_conv_yellow_hdr")
    if m is not None and m.use_nodes:
        _paint_yellow(m)
    import bmesh
    n = 0
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("PegboardEndcapFactory")]:
        idx = [i for i, sl in enumerate(o.material_slots) if sl.material and sl.material.name == "ir_conv_yellow_hdr"]
        if not idx:
            continue
        body = [v.co.z for p in o.data.polygons if p.material_index not in idx for v in (o.data.vertices[i] for i in p.vertices)]
        if not body:
            continue
        top = max(body)
        hz = [o.data.vertices[i].co.z for p in o.data.polygons if p.material_index in idx for i in p.vertices]
        h0, h1 = min(hz), max(hz); k_ = 0.18 / max(h1 - h0, 1e-3) if h1 - h0 > 0.19 else 1.0       # r15: the 0.25 m endcap board read as a slab: 0.18 m, top flush with the unit
        vids = {i for p in o.data.polygons if p.material_index in idx for i in p.vertices}
        for i in vids:
            v = o.data.vertices[i]; v.co.z = top - (h1 - v.co.z) * k_
        n += 1
    stats["conv_ref_endcap_hdr_flush"] = n


def _nolabel(stats):
    """S37 r15: white pillow-shaped packs = FoodBags that never got a printed label (no image texture): removed."""
    k = 0
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("FoodBagFactory")]:
        if not any(n.type == "TEX_IMAGE" for sl in o.material_slots if sl.material and sl.material.use_nodes for n in sl.material.node_tree.nodes):
            bpy.data.objects.remove(o, do_unlink=True); k += 1
    stats["conv_ref_unlabelled_bags_removed"] = k


def _rails(stats):
    """Continuous white shelf carriers with dark lips and individual printed price cards."""
    from room_planner import proc_boutique_flagship as fl
    rail = _flat("ir_conv_price_carrier", (0.86, 0.86, 0.82), 0.45, plain=True)
    tag = _flat("ir_conv_price_tag", (0.95, 0.95, 0.92), 0.6, plain=True)
    ink = _flat("ir_conv_price_ink", (0.015, 0.015, 0.018), 0.7, plain=True)
    for mat in (rail, tag, ink):
        bs = mat.node_tree.nodes["Principled BSDF"]
        for link in list(bs.inputs["Normal"].links):
            mat.node_tree.links.remove(link)
        bs.inputs["Emission Strength"].default_value = 0
    carriers, cards, lips, labels = [], [], [], []
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("GondolaFactory", "WallGondolaFactory"))]:
        mw = o.matrix_world
        seen = set()
        for face in o.data.polygons:
            if (mw.to_3x3() @ face.normal).normalized().z < 0.95 or face.area < 0.08:
                continue
            c = mw @ face.center
            if c.z < 0.15:
                continue
            vs = [mw @ o.data.vertices[i].co for i in face.vertices]
            x0, x1 = min(v.x for v in vs), max(v.x for v in vs)
            y0, y1 = min(v.y for v in vs), max(v.y for v in vs)
            key = (round(c.z, 2), round(x0, 2), round(y0, 2))
            if key in seen:
                continue
            seen.add(key)
            along_y = (y1 - y0) > (x1 - x0)
            for side, e in enumerate((x0, x1) if along_y else (y0, y1)):
                sign = -1 if side == 0 else 1
                start, end = (y0, y1) if along_y else (x0, x1)
                mid, length, z = (start + end) / 2, end - start - 0.02, c.z - 0.018
                if along_y:
                    carriers.append(("box", e + sign * 0.007, mid, z, 0.006, length, 0.035))
                    lips.append(("box", e + sign * 0.007, mid, z - 0.0165, 0.008, length, 0.002))
                else:
                    carriers.append(("box", mid, e + sign * 0.007, z, length, 0.006, 0.035))
                    lips.append(("box", mid, e + sign * 0.007, z - 0.0165, length, 0.008, 0.002))
                t = start + 0.09
                while t < end - 0.06:
                    if along_y:
                        cards.append(("box", e + sign * 0.0113, t, z, 0.002, 0.065, 0.030))
                        labels.append(((e + sign * 0.0127, t, z), sign * math.pi / 2))
                    else:
                        cards.append(("box", t, e + sign * 0.0113, z, 0.065, 0.002, 0.030))
                        labels.append(((t, e + sign * 0.0127, z), math.pi if sign > 0 else 0))
                    t += 0.18
    if carriers:
        fl.mesh_object("ConvPriceRails", [(rail, carriers), (tag, cards), (ink, lips)], bevel=False)
    fonts = []
    for i, price in enumerate(("2.99", "3.49", "4.99", "1.99", "5.99")):
        font = bpy.data.curves.new(f"ConvPriceFont_{i}", "FONT")
        font.body, font.align_x, font.align_y = price, "CENTER", "CENTER"
        font.size = 0.008
        font.materials.append(ink)
        fonts.append(font)
    for i, (position, yaw) in enumerate(labels):
        text = bpy.data.objects.new(f"ConvPriceText_{i}", fonts[i % len(fonts)])
        text.location = position
        text.rotation_euler = (math.pi / 2, 0, yaw)
        bpy.context.scene.collection.objects.link(text)
    stats["conv_ref_rails"] = len(carriers)
    stats["conv_ref_price_cards"] = len(cards)
    stats["conv_ref_price_texts"] = len(labels)


def _left_wall(lo, hi, stats):
    """S37 r15 #7: the bare left wall gets a promo poster bay: 3 framed lit posters (ads/*.png when the Codex ad set exists, else blank warm panels) over a low wall shelf of library packs."""
    from room_planner import proc_boutique_flagship as fl
    import glob, random
    import real_assets as ra
    x = lo[0] + 0.02; yc = (lo[1] + hi[1]) / 2; frame = _flat("ir_conv_poster_frame", (0.04, 0.04, 0.045), 0.4)
    ads = sorted(glob.glob("/jarvis/project/robomituba/data/venue_refs/convenience_emart_01/ads/*.png")) or \
        sorted(glob.glob("/jarvis/project/robomituba/data/venue_refs/convenience_emart_01/promo_fallback/*.png"))     # S37 r16: blank panels read as placeholders; 1+1 / 2+1 / NEW promo posters built from the product-label art until the Codex ads land
    k = 0
    for i, dy in enumerate((-1.3, 0.0, 1.3)):
        y = yc + dy
        if any(o.type == "MESH" and o.name.startswith(("door", "Door", "Window", "window")) and abs((o.matrix_world.translation.y) - y) < 0.8 and abs(o.matrix_world.translation.x - lo[0]) < 0.5 for o in bpy.data.objects):
            continue
        fl.mesh_object(f"ConvPosterFrame{i}", [(frame, [("box", x + 0.015, y, 1.75, 0.03, 0.9, 1.2)])], bevel=True)
        if ads:
            m = bpy.data.materials.new(f"ir_conv_poster_{i}"); m.use_nodes = True; N, L = m.node_tree.nodes, m.node_tree.links; b = N["Principled BSDF"]
            im = N.new("ShaderNodeTexImage"); im.image = bpy.data.images.load(ads[i % len(ads)], check_existing=True)
            L.new(im.outputs["Color"], b.inputs["Base Color"]); L.new(im.outputs["Color"], b.inputs["Emission Color"]); b.inputs["Emission Strength"].default_value = 0.6; m["weathered"] = True
        else:
            m = _flat(f"ir_conv_poster_blank_{i}", (0.95, 0.78, 0.2) if i != 1 else (0.9, 0.9, 0.86), 0.5, emit=0.5, plain=True)
        from room_planner import rooftop_shell as rs
        rs._quads(f"ConvPoster{i}", [[(x + 0.032, y - 0.42, 1.18), (x + 0.032, y + 0.42, 1.18), (x + 0.032, y + 0.42, 2.32), (x + 0.032, y - 0.42, 2.32)]], m)
        k += 1
    stats["conv_ref_posters"] = k



def _rack_basket(cx, cy, z, width, depth):
    """Black welded-wire shelf basket; all dimensions in metres."""
    rods = []
    rim = 0.075
    for height in (z + 0.025, z + rim):
        for sy in (-1, 1):
            rods.append(("cyl", (cx - width / 2, cy + sy * depth / 2, height),
                         (cx + width / 2, cy + sy * depth / 2, height), 0.004, 8))
        for sx in (-1, 1):
            rods.append(("cyl", (cx + sx * width / 2, cy - depth / 2, height),
                         (cx + sx * width / 2, cy + depth / 2, height), 0.004, 8))
    count = max(2, round(width / 0.035))
    for i in range(1, count):
        x = cx - width / 2 + width * i / count
        rods.append(("cyl", (x, cy - depth / 2, z), (x, cy + depth / 2, z), 0.0025, 6))
        for sy in (-1, 1):
            rods.append(("cyl", (x, cy + sy * depth / 2, z),
                         (x, cy + sy * depth / 2, z + rim), 0.0025, 6))
    count = max(2, round(depth / 0.035))
    for i in range(1, count):
        y = cy - depth / 2 + depth * i / count
        rods.append(("cyl", (cx - width / 2, y, z), (cx + width / 2, y, z), 0.0025, 6))
    return rods


def _ratio1(lo, hi, zc, stats):
    """Reference-ratio pass (user 2026-10-26): gridded white AC cassette, entrance mat, wire side racks with library snacks + white price rails on the gondola ends, dense shrubs in tall dark
    square planters at the entrance, a crowded checkout (impulse packs, cup towers), foliage fix. Shared helpers in ratio1_common.py."""
    import random
    import ratio1_common as rc
    import real_assets as ra
    from room_planner import proc_boutique_flagship as fl
    got = {}
    for o in [o for o in bpy.data.objects if o.name.startswith("ConvCassetteAC")]:
        a, b = rc.bb(o); cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2; bpy.data.objects.remove(o, do_unlink=True)
        rc.cassette(cx, cy, zc, size=1.0, drop=0.16, tag="conv"); got["ac"] = 1
    dr = bpy.data.objects.get("door") or bpy.data.objects.get("LiqGlassDoor")
    dx = max(lo[0] + 0.8, (rc.bb(dr)[0][0] + rc.bb(dr)[1][0]) / 2) if dr is not None else lo[0] + 2.0
    got["mat"] = int(rc.mat(ra, dx, lo[1] + 0.48, lo[2], 1.3, 0.85, tag="conv") is not None)
    steel = _flat("ir_conv_rack_wire", (0.018, 0.020, 0.018), 0.42, 0.15); white = _flat("ir_conv_rack_rail", (0.95, 0.95, 0.92), 0.5)
    rg = random.Random(37); wire, rails, nit = [], [], 0
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("GondolaFactory")]:
        a, b = rc.bb(o); ay = (b[1] - a[1]) > (b[0] - a[0])
        for e in (0, 1):
            cx_, cy_ = (((a[0] + b[0]) / 2, (a[1] - 0.22) if e == 0 else (b[1] + 0.22)) if ay else (((a[0] - 0.22) if e == 0 else (b[0] + 0.22)), (a[1] + b[1]) / 2))
            if not (lo[0] + 0.4 < cx_ < hi[0] - 0.4 and lo[1] + 0.4 < cy_ < hi[1] - 0.4):
                continue
            w, d = (0.4, 0.26) if ay else (0.26, 0.4)
            for sx in (-1, 1):
                for sy in (-1, 1):
                    wire.append(("cyl", (cx_ + sx * w / 2, cy_ + sy * d / 2, lo[2]), (cx_ + sx * w / 2, cy_ + sy * d / 2, lo[2] + 1.5), 0.007, 8))
            for t in range(4):
                z = lo[2] + 0.3 + t * 0.34
                for sy in (-1, 1):
                    wire.append(("cyl", (cx_ - w / 2, cy_ + sy * d / 2, z), (cx_ + w / 2, cy_ + sy * d / 2, z), 0.005, 6))
                for sx in (-1, 1):
                    wire.append(("cyl", (cx_ + sx * w / 2, cy_ - d / 2, z), (cx_ + sx * w / 2, cy_ + d / 2, z), 0.005, 6))
                # A real wire basket floor and raised retaining rim support the packs.
                # Keep the existing end-cap footprint and four shelf heights.
                wire.extend(_rack_basket(cx_, cy_, z, w, d))
                fx, fy = (cx_, cy_ + (-1 if (e == 0) == ay else 1) * d / 2) if ay else (cx_ + (-1 if e == 0 else 1) * w / 2, cy_)
                rails.append(("box", fx, fy, z + 0.01, (w if ay else 0.006), (0.006 if ay else d), 0.03))
                for i in range(3):
                    u = (i - 1) * 0.12
                    _fit(ra.lib("FoodBagFactory" if (t + i) % 2 else "FoodBoxFactory", rg.randrange(1000), cx_ + (u if ay else 0), cy_ + (0 if ay else u), z + 0.005, rg.uniform(0, 6.28)), 0.17, z + 0.005); nit += 1
    if wire:
        fl.mesh_object("ConvSideRacks", [(steel, wire), (white, rails)], bevel=False)
    got["racks"] = {"racks": len(rails) // 4, "items": nit}
    k = 0
    for i, x in enumerate((lo[0] + 1.2, lo[0] + 3.0)):
        pl = ra.abo("planter", 80 + i, x, lo[1] + 0.55, lo[2], 0.0, fit=(0.5, 0.5, 0.75))
        if pl is None:
            continue
        for q in range(len(pl.data.materials) or 1):
            pass
        _dark_all(pl)
        bpy.context.view_layer.update(); top = rc.bb(pl)[1][2]
        sh = ra.hssd(r"schefflera bush|hedge|topiary|laurel|boxwood|ficus", 90 + i, x, lo[1] + 0.55, top - 0.1, 0.0, fit=(0.7, 0.7, 1.1), size=(0.8, 2.2), grow=True)
        k += 1 if sh is not None else 0
    got["planters"] = k
    cs = _counters()
    if cs:
        b0, b1 = _obb(cs[0]); zt = _top_z(cs[0]); n = 0
        for j in range(14):
            o = _fit(ra.lib("FoodBoxFactory" if j % 2 else "FoodBagFactory", 300 + j, b0[0] + 0.15 + (j % 7) * 0.09, b0[1] + 0.12 + (j // 7) * 0.12, zt, rg.uniform(0, 6.28)), 0.13, zt)
            n += 1 if o is not None else 0
        for j in range(2):
            o = ra.hssd(r"hot cups", 0, b1[0] - 0.4 - j * 0.14, (b0[1] + b1[1]) / 2 + 0.1, zt, 0.0)
            n += 1 if o is not None else 0
        got["counter_props"] = n
    got["plant_fix"] = rc.plant_fix_all()
    stats["conv_ratio1"] = got


def _fit(o, ext, z):
    """Scale a library pack to a max extent of ext metres and stand it on z."""
    if o is None:
        return None
    k = ext / max(max(o.dimensions), 1e-3); o.scale = tuple(v * k for v in o.scale); bpy.context.view_layer.update()
    o.location.z += z - min((o.matrix_world @ Vector(c)).z for c in o.bound_box)
    return o


def _dark_all(o):
    if o is None or o.type != "MESH":
        return
    m = _flat("ir_conv_planter_dark", (0.03, 0.03, 0.033), 0.45); o.data = o.data.copy()
    for i in range(len(o.data.materials)):
        o.data.materials[i] = m


def _cooler_glazing(stats):
    """Change only explicitly named cooler glass slots, preserving all stock and frames."""
    changed = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.name.startswith("CoolerWallFactory"):
            continue
        slots = [i for i, slot in enumerate(obj.material_slots)
                 if slot.material and slot.material.name.startswith("ir_cooler_glass")]
        if not slots:
            continue
        obj.data = obj.data.copy()
        for index in slots:
            old = obj.data.materials[index]
            mat = bpy.data.materials.get("ir_conv_cooler_clear_S37c")
            if mat is None:
                mat = bpy.data.materials.new("ir_conv_cooler_clear_S37c")
                mat.use_nodes = True
                mat["weathered"] = True
                bs = mat.node_tree.nodes.get("Principled BSDF")
                bs.inputs["Base Color"].default_value = (1, 1, 1, 1)
                bs.inputs["Transmission Weight"].default_value = 1
                bs.inputs["IOR"].default_value = 1.45
                bs.inputs["Roughness"].default_value = .02
                bs.inputs["Metallic"].default_value = 0
                bs.inputs["Alpha"].default_value = 1
                bs.inputs["Emission Strength"].default_value = 0
            count = sum(poly.material_index == index for poly in obj.data.polygons)
            obj.data.materials[index] = mat
            changed.append({"object": obj.name, "slot": index, "old": old.name, "faces": count})
    if not changed:
        raise ValueError("No named cooler door glass slots found; refusing broad material replacement")
    stats["conv_ref_glazing"] = changed


def _ref(lo, hi, zc, stats):
    skip = set((os.environ.get("ROOM_CONV_REF_SKIP") or "").split(","))
    for key, fn in (("blank", lambda: _blank_headers(stats)), ("headers", lambda: _headers(stats)), ("counters", lambda: _counter_paint(stats)), ("checkout", lambda: _checkout(stats)),
                    ("coffee", lambda: _coffee(lo, hi, stats)), ("floor", lambda: _ref_floor(stats)), ("cams", lambda: _cams(lo, hi, zc, stats)), ("plants", lambda: _plants(lo, hi, stats)), ("endhdr", lambda: _endcap_hdr(stats)), ("nolabel", lambda: _nolabel(stats)),
                    ("rails", lambda: _rails(stats)), ("leftwall", lambda: _left_wall(lo, hi, stats)), ("ratio1", lambda: _ratio1(lo, hi, zc, stats)), ("glazing", lambda: _cooler_glazing(stats))):
        if key in skip:
            continue
        try:
            bpy.context.view_layer.update(); fn()
        except Exception as ex:                                  # noqa: BLE001 -- a part that fails must not sink the kit stage
            stats[f"conv_ref_{key}_error"] = repr(ex)[:160]


def apply(stats):
    sc = bpy.context.scene
    if sc.get("ir_conv_shell") or bpy.data.objects.get(f"{ROOM}.floor") is None:
        return 0
    lo, _ = _bb(f"{ROOM}.floor"); hi = _bb(f"{ROOM}.floor")[1]; zc = _bb(f"{ROOM}.ceiling")[1][2]; n = 0
    if os.environ.get("ROOM_CONV_NOCOL") == "1":
        k = 0
        for o in list(bpy.data.objects):
            if o.name.startswith(("ColumnFactory", "RoundPillarFactory")):
                bpy.data.objects.remove(o, do_unlink=True); k += 1
        stats["conv_columns_removed"] = k; n += 1
    if os.environ.get("ROOM_CONV_CEIL") == "1":
        _ceiling(lo, hi, zc, stats); n += 1
    if os.environ.get("ROOM_CONV_NOSIGNS") == "1":
        k = 0
        for o in list(bpy.data.objects):
            if o.name.startswith("CategorySignFactory"):
                bpy.data.objects.remove(o, do_unlink=True); k += 1
        stats["conv_signs_removed"] = k; n += 1
    if os.environ.get("ROOM_PEG_LIB") == "1":
        _peg_items(stats); n += 1
    if os.environ.get("ROOM_CONV_FLOOR"):
        _floor(stats); n += 1
    if os.environ.get("ROOM_CONV_SLATS") == "1":
        _slats(lo, hi, zc, stats); n += 1
    if os.environ.get("ROOM_CONV_REF") == "1":
        _ref(lo, hi, zc, stats); n += 1
    import ratio1_plants, ratio1_checkout; ratio1_plants.apply(stats); ratio1_checkout.apply(stats)
    import real_assets as ra
    ra.report(stats, "conv")
    sc["ir_conv_shell"] = 1
    return n
