"""S38 wine-shop shell (kit stage, idempotent via scene["ir_liq_shell"]); ROOM_LIQ_SHELL=1 enables every part, the parts can be switched off by ROOM_LIQ_SKIP=<comma list of ceil,back,brick,fascia,headers,leds,islands,checkout,cellar,glow,racks,endcaps,pack,floor,door,street,plants,light,wine>.

ceil     black ceiling, 4 black hung track rails with ~28 warm spot heads (ROOM_LIQ_SPOT_W per head, default 140), a dark 4-way cassette AC; the white LED panels / drop lights go
back     the back wall (high y): full-height black wine shelving (7 levels of library bottles, upright and lying) under 4 painted vineyard panels on a charcoal wall band
brick    red-brick feature wall on the right wall (high x) with 4 backlit floating shelves of library gift boxes
fascia   a walnut fascia above the left-wall cooler run
glow     warm LED under-glow strip along the checkout's customer-facing side (only for a CheckoutCounterFactory still there)
headers  (S38 ref 10-25) shelf-top category boards off the gondolas
leds     warm LED strips under every gondola / wine-wall shelf
islands  two low entrance islands with bottles, gift boxes, a plant (the layout's promo / snack gondolas are gone)
checkout one L-shaped walnut-slat / marble checkout with POS, card terminal, flowers, plant (replaces the CheckoutCounterFactory runs)
cellar   twin narrow glass-door wine-cellar fridges at the back right
(S38 r15, user 'another round' + SUB2 review r14) racks = 2 rear-right oak cubby racks of lying bottles; endcaps = price rails + shelf tags, gift cartons on the gondola ends; pack = ribbons, tissue, bag
labels, stained crates; floor = scanned oak planks with coat; door = black-framed glass swing leaf; street = glass-office plate, paving, kerb, asphalt, planters; plants = spider plants on the brick shelves,
entrance floor plants, a flower bouquet on the checkout; light = warm spots x ROOM_LIQ_SPOT_GAIN (1.8) + 3 fills (ROOM_LIQ_FILL_W 110); wine = every bottle narrowed to wine proportions, dark wine glass
Geometry from the break-room_0/0 floor / ceiling bbox (back = high y, right = high x, shopfront = low y, left glazing + coolers = low x).
"""
from __future__ import annotations

import math
import os
import random

import bpy
from mathutils import Matrix, Vector

ROOM = "break-room_0/0"


def _bb(name):
    o = bpy.data.objects.get(name)
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def _lib(name):
    from room_planner import lib_objects
    import real_assets as ra
    f = lib_objects.factory(name)
    if f is None:                                            # asset QA rev2 R1: a None here emptied the wine wall / islands / racks without a word
        ra._count(name, False, "(lib_objects.factory) ")
    return f


def _emit(name, rgb, strength):
    from room_planner import proc_assets as pa
    m = pa._flat(name, rgb, 0.4); b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*rgb, 1.0); b.inputs["Emission Strength"].default_value = strength
    return m


def _ceiling(lo, hi, zc, stats):
    from room_planner import proc_assets as pa
    from room_planner import proc_boutique_flagship as fl
    bpy.context.view_layer.update()
    for o in list(bpy.data.objects):
        if o.name.startswith(("CeilingGridFactory", "LinearLedFactory", "DiffuserFactory", "DropCeilingFactory", "CeilingLightFactory")):
            bpy.data.objects.remove(o, do_unlink=True)
    for ld in [o for o in bpy.data.objects if o.type == "LIGHT" and o.data.type == "AREA" and not o.name.startswith("ir_liq")]:
        bpy.data.objects.remove(ld, do_unlink=True)
    black = pa._flat("ir_liq_ceiling", (0.025, 0.025, 0.028), 0.8); black["weathered"] = True
    c = bpy.data.objects.get(f"{ROOM}.ceiling")
    for sl in c.material_slots:
        sl.material = black
    rail = fl._flat("ir_liq_rail", (0.02, 0.02, 0.022), 0.4, 0.9); W = float(os.environ.get("ROOM_LIQ_SPOT_W") or 140)
    zr = zc - 0.75; x0, x1, y0, y1 = lo[0] + 0.4, hi[0] - 0.4, lo[1] + 0.9, hi[1] - 0.9
    prims, heads = [], []
    for j in range(4):
        y = y0 + (y1 - y0) * (j + 0.5) / 4
        prims.append(("box", (x0 + x1) / 2, y, zr, x1 - x0, 0.035, 0.035))
        for e in (x0 + 0.3, x1 - 0.3, (x0 + x1) / 2):
            prims.append(("cyl", (e, y, zr), (e, y, zc), 0.006, 8))
        for i in range(7):
            x = x0 + (x1 - x0) * (i + 0.5) / 7; heads.append((x, y)); prims.append(("cyl", (x, y, zr - 0.02), (x, y, zr - 0.2), 0.04, 14))
    fl.mesh_object("LiqTrackRails", [(rail, prims)], bevel=False)
    for k, (x, y) in enumerate(heads):
        ld = bpy.data.lights.new(f"ir_liq_spot_{k}", "SPOT"); ld.energy = W; ld.spot_size = math.radians(62); ld.spot_blend = 0.5; ld.color = (1.0, 0.74, 0.46); ld.shadow_soft_size = 0.04
        o = bpy.data.objects.new(ld.name, ld); o.location = (x, y, zr - 0.2); o.rotation_euler = (math.radians(30) if y > (lo[1] + hi[1]) / 2 else 0.0, 0, 0); bpy.context.scene.collection.objects.link(o)     # the back-half heads lean 30 deg towards the wine wall (S38 r4: the pools stayed on the floor)
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2 + 0.6
    grey = pa._flat("ir_liq_ac", (0.16, 0.16, 0.17), 0.5)
    fl.mesh_object("LiqCassetteAC", [(grey, [("box", cx, cy, zc - 0.07, 0.9, 0.9, 0.14), ("box", cx, cy, zc - 0.145, 0.7, 0.7, 0.012)])], bevel=False)
    stats["liq_ceiling"] = {"spots": len(heads)}


def _vineyard_mat():
    """Procedural painted vineyard: sky gradient, soft hills, striped vine rows (object-space, albedo only)."""
    from room_planner import proc_assets as pa
    m = pa._flat("ir_liq_vineyard", (0.4, 0.55, 0.3), 0.85); m["weathered"] = True
    nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); sp = N.new("ShaderNodeSeparateXYZ"); L.new(tc.outputs["Generated"], sp.inputs["Vector"])      # generated: 0..1 over the panel band
    ramp = N.new("ShaderNodeValToRGB"); ramp.color_ramp.elements[0].position = 0.0; ramp.color_ramp.elements[0].color = (0.30, 0.38, 0.15, 1); ramp.color_ramp.elements[1].position = 1.0; ramp.color_ramp.elements[1].color = (0.62, 0.78, 0.9, 1)
    e = ramp.color_ramp.elements.new(0.5); e.color = (0.55, 0.62, 0.25, 1); e2 = ramp.color_ramp.elements.new(0.62); e2.color = (0.93, 0.85, 0.65, 1)
    mp = N.new("ShaderNodeMapRange"); mp.inputs["From Min"].default_value = 0.0; mp.inputs["From Max"].default_value = 1.15      # generated z: the old object-space -0.45..0.45 range put every pixel in the sky, so the panels read as white windows (S38 r12 refs)
    nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 3.0; nz.inputs["Detail"].default_value = 2.0
    add = N.new("ShaderNodeMath"); add.operation = "ADD"; mu = N.new("ShaderNodeMath"); mu.operation = "MULTIPLY"; mu.inputs[1].default_value = 0.18
    L.new(nz.outputs["Fac"], mu.inputs[0]); L.new(sp.outputs["Z"], mp.inputs["Value"]); L.new(mp.outputs["Result"], add.inputs[0]); L.new(mu.outputs[0], add.inputs[1]); L.new(add.outputs[0], ramp.inputs["Fac"])
    rows = N.new("ShaderNodeTexWave"); rows.wave_type = "BANDS"; rows.bands_direction = "Z"; rows.inputs["Scale"].default_value = 9.0; rows.inputs["Distortion"].default_value = 4.0
    mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.inputs["Factor"].default_value = 0.35
    L.new(ramp.outputs["Color"], mix.inputs["A"]); L.new(rows.outputs["Color"], mix.inputs["B"]); L.new(mix.outputs["Result"], b.inputs["Base Color"])
    dim = N.new("ShaderNodeMix"); dim.data_type = "RGBA"; dim.blend_type = "MULTIPLY"; dim.inputs["Factor"].default_value = 1.0; dim.inputs["B"].default_value = (*([float(os.environ.get("ROOM_LIQ_VINE_ALB") or 0.22)] * 3), 1)
    L.new(mix.outputs["Result"], dim.inputs["A"]); L.new(dim.outputs["Result"], b.inputs["Base Color"])      # S38 r12 refs: the panels sit under the wash light + 14 tilted spots; full-albedo paint blew out to white ("windows")
    return m


PANELS = "/jarvis/project/robomituba/data/venue_refs/floor_plans_v3/LIQUOR/panels/vine_{}.png"


def _panel_mat(k):
    """Printed vineyard art: explicit UVs and diffuse colour, without surface-detail mixes."""
    path = PANELS.format(k)
    if not os.path.exists(path):
        return None
    name = f"ir_liq_vine_{k}"
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    if not m.get("pkgg_print"):
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        out = nt.nodes.new("ShaderNodeOutputMaterial")
        bs = nt.nodes.new("ShaderNodeBsdfPrincipled")
        bs.inputs["Roughness"].default_value = 0.7
        bs.inputs["Specular IOR Level"].default_value = 0.15
        im = nt.nodes.new("ShaderNodeTexImage")
        im.image = bpy.data.images.load(path, check_existing=True)
        im.image.colorspace_settings.name = "sRGB"
        im.extension = "EXTEND"
        uv = nt.nodes.new("ShaderNodeUVMap")
        uv.uv_map = ""
        tint = nt.nodes.new("ShaderNodeMixRGB")
        tint.blend_type = "MULTIPLY"
        tint.inputs[0].default_value = 1.0
        value = float(os.environ.get("ROOM_LIQ_VINE_ALB") or 0.16)
        tint.inputs[2].default_value = (value, value, value, 1.0)
        nt.links.new(uv.outputs["UV"], im.inputs["Vector"])
        nt.links.new(im.outputs["Color"], tint.inputs[1])
        nt.links.new(tint.outputs["Color"], bs.inputs["Base Color"])
        nt.links.new(bs.outputs["BSDF"], out.inputs["Surface"])
        m["pkgg_print"] = 1
        m["weathered"] = True
    for node in m.node_tree.nodes:
        if node.type == "UVMAP":
            node.uv_map = ""
    return m


def _panel_uv(o):
    """Map each printed material's panel independently, preserving the frame material."""
    uv = o.data.uv_layers.get("LiqVineyardUV") or o.data.uv_layers.new(name="LiqVineyardUV")
    uv.active_render = True
    o.data.uv_layers.active_index = list(o.data.uv_layers).index(uv)
    for mi, mat in enumerate(o.data.materials):
        if mat is None or not mat.name.startswith("ir_liq_vine_"):
            continue
        faces = [f for f in o.data.polygons if f.material_index == mi]
        verts = [o.data.vertices[i].co for f in faces for i in f.vertices]
        if not verts:
            continue
        x0, x1 = min(v.x for v in verts), max(v.x for v in verts)
        z0, z1 = min(v.z for v in verts), max(v.z for v in verts)
        for face in faces:
            for li in face.loop_indices:
                v = o.data.vertices[o.data.loops[li].vertex_index].co
                uv.data[li].uv = ((v.x - x0) / max(x1 - x0, 1e-6), (v.z - z0) / max(z1 - z0, 1e-6))
    return o


def _back_levels(zc):
    """Raise the bottle display while reserving a framed artwork band below the ceiling."""
    height = min(3.15, zc - 0.65)
    panel_height = min(0.72, zc - height - 0.12)
    shelves = [0.2 + k * (height - 0.53) / 7 for k in range(8)]
    return height, panel_height, shelves


def _back(lo, hi, zc, stats):
    from room_planner import proc_assets as pa
    from room_planner import proc_boutique_flagship as fl
    W = hi[0] - lo[0]; x0, x1 = lo[0] + 0.085 * W, lo[0] + 0.755 * W; yb = hi[1] - 0.01; D = 0.34; H, ph, zs = _back_levels(zc)          # S38 r15 refs: a tall continuous wine wall, panels above it
    frame = fl._flat("ir_liq_frame", (0.03, 0.03, 0.034), 0.45, 0.8); back = fl._flat("ir_liq_back", (0.05, 0.04, 0.035), 0.85)
    wood = fl._flat("ir_liq_shelf", (0.12, 0.07, 0.04), 0.55, wood=True)
    parts = [("box", (x0 + x1) / 2, yb - 0.01, H / 2, x1 - x0, 0.02, H)]
    n_up = int((x1 - x0) // 0.95) + 1
    fr = [("box", x0 + k * (x1 - x0) / (n_up - 1), yb - D / 2, H / 2, 0.04, D, H) for k in range(n_up)]
    sh = [("box", (x0 + x1) / 2, yb - D / 2, z, x1 - x0, D, 0.03) for z in zs]
    fl.mesh_object("LiqWineWall", [(back, parts), (frame, fr), (wood, sh)], bevel=False)
    band = fl._flat("ir_liq_band", (0.045, 0.045, 0.05), 0.8)
    fl.mesh_object("LiqBackBand", [(band, [("box", (x0 + x1) / 2 + 0.2, yb - 0.003, (H + zc) / 2, (x1 - x0) + 2.0, 0.004, zc - H)])], bevel=False)
    vm = _vineyard_mat(); pw = (x1 - x0 - 0.5) / 4
    pan = [("box", x0 + 0.1 + pw * (k + 0.5) + k * 0.1, yb - 0.02, H + 0.04 + ph / 2, pw - 0.04, 0.02, ph - 0.04) for k in range(4)]
    frm = [("box", x0 + 0.1 + pw * (k + 0.5) + k * 0.1, yb - 0.015, H + 0.04 + ph / 2, pw, 0.012, ph) for k in range(4)]
    panels = fl.mesh_object("LiqVineyardPanels", [(frame, frm)] + [(_panel_mat(k) or vm, [pan[k]]) for k in range(4)], bevel=False)
    _panel_uv(panels)
    for k_, (zz, en) in enumerate(((3.45, 55.0), (1.8, 420.0))):        # S38 r12 refs: 500 W blew the vineyard panels out to white ("windows")                                  # wall wash: the vineyard panels (z ~3.1) and the upper bottle shelves; area lights facing the wall
        ld = bpy.data.lights.new(f"ir_liq_wash_{k_}", "AREA"); ld.shape = "RECTANGLE"; ld.size = x1 - x0; ld.size_y = 0.6; ld.energy = en; ld.color = (1.0, 0.8, 0.58)
        o = bpy.data.objects.new(ld.name, ld); o.location = ((x0 + x1) / 2, yb - 1.1, zz); o.rotation_euler = (math.pi / 2, 0, 0); bpy.context.scene.collection.objects.link(o)
    bf, rg, n = _lib("BottleFactory"), random.Random(11), 0
    if bf is not None:
        fac = bf(7); protos = []
        for li, z in enumerate(zs):
            x = x0 + 0.08
            while x < x1 - 0.08:
                if len(protos) < 14:                                        # S38 r15: 14 spawned prototypes, the rest linked copies (a spawn + view-layer update per bottle cost ~1 s each here)
                    o = _wine_label(fac.spawn_asset(n), rg); protos.append(o)
                else:
                    o = protos[n % len(protos)].copy(); bpy.context.scene.collection.objects.link(o); o.scale = (1, 1, 1)
                n += 1
                h = max(o.dimensions.z, 1e-3); k = min(1.0, 0.31 / h) * rg.uniform(0.9, 1.0); lying = (li % 3 == 2)
                if lying:
                    o.rotation_euler = (0, math.pi / 2, math.pi / 2 + rg.uniform(-0.05, 0.05)); step = max(o.dimensions.x, o.dimensions.y) * 0.0 + 0.085
                else:
                    o.rotation_euler = (0, 0, math.pi / 2 + rg.uniform(-0.3, 0.3)); step = max(0.07, max(o.dimensions.x, o.dimensions.y) * k + 0.012)
                o.scale = (k, k, k)
                o.location = (x + step / 2, yb - D / 2 + (rg.uniform(-0.04, 0.04) if not lying else 0.0), z + 0.015 + (o.dimensions.y * 0.0 if not lying else 0.04))
                x += step
                if rg.random() < 0.06:
                    x += 0.07                                                   # a gap in the row
    stats["liq_back_bottles"] = n


def _brick_mat():
    """Metre-scaled warm masonry on the right-hand wall."""
    from room_planner import proc_assets as pa
    m = pa._flat("ir_liq_brick", (0.34, 0.11, 0.045), 0.8)
    m["weathered"] = True
    nt = m.node_tree
    N, L = nt.nodes, nt.links
    b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord")
    sp = N.new("ShaderNodeSeparateXYZ")
    cb = N.new("ShaderNodeCombineXYZ")
    br = N.new("ShaderNodeTexBrick")
    L.new(tc.outputs["Object"], sp.inputs["Vector"])
    L.new(sp.outputs["Y"], cb.inputs["X"])
    L.new(sp.outputs["Z"], cb.inputs["Y"])
    L.new(cb.outputs["Vector"], br.inputs["Vector"])
    br.inputs["Color1"].default_value = (0.34, 0.11, 0.045, 1)
    br.inputs["Color2"].default_value = (0.18, 0.055, 0.025, 1)
    br.inputs["Mortar"].default_value = (0.20, 0.17, 0.14, 1)
    br.inputs["Scale"].default_value = 1.0
    br.inputs["Mortar Size"].default_value = 0.006
    br.inputs["Brick Width"].default_value = 0.26
    br.inputs["Row Height"].default_value = 0.085
    br.inputs["Bias"].default_value = 0.3
    L.new(br.outputs["Color"], b.inputs["Base Color"])
    bump = N.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.45
    bump.inputs["Distance"].default_value = 0.004
    bump.invert = True
    L.new(br.outputs["Fac"], bump.inputs["Height"])
    L.new(bump.outputs["Normal"], b.inputs["Normal"])
    return m


def _brick(lo, hi, zc, stats):
    from room_planner import proc_boutique_flagship as fl
    xw = hi[0] - 0.006; y0, y1 = lo[1] + 0.05, hi[1] - 0.05
    fl.mesh_object("LiqBrickWall", [(_brick_mat(), [("box", xw, (y0 + y1) / 2, (zc - 0.05) / 2, 0.01, y1 - y0, zc - 0.05)])], bevel=False)
    glow = _emit("ir_liq_shelf_glow", (1.0, 0.7, 0.4), 9.0); wood = fl._flat("ir_liq_float", (0.08, 0.06, 0.05), 0.5, wood=True)
    yc = lo[1] + 0.6375 * (hi[1] - lo[1]); Ls = 2.6; zs = [1.0, 1.5, 2.0, 2.5]
    fl.mesh_object("LiqFloatShelves", [(wood, [("box", xw - 0.16, yc, z, 0.3, Ls, 0.035) for z in zs]), (glow, [("box", xw - 0.2, yc, z - 0.03, 0.02, Ls - 0.1, 0.012) for z in zs])], bevel=False)
    import real_assets as ra
    n = 0
    for row, z in enumerate(zs):
        for col in range(5):
            y = yc - Ls / 2 + 0.23 + col * 0.49
            o = ra.hssd(GIFT_RX, 380 + row * 5 + col, xw - 0.16, y,
                        z + 0.0175, math.pi,
                        fit=(0.40, 0.30, 0.40), size=(0.2, 0.6), grow=True)
            if o is None:
                raise RuntimeError("S38 gift-wall presentation asset unavailable")
            o.name = f"LiqGiftWall_{row}_{col}"
            o["ir_role"] = "wine_gift_presentation"
            n += 1
    stats["liq_brick_boxes"] = n


def _fascia(lo, hi, zc, stats):
    """A shallow walnut valance just ahead of the actual left cooler front."""
    import scanned_wood as sw
    from room_planner import proc_boutique_flagship as fl
    banks = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.name.startswith("CoolerWallFactory"):
            continue
        a, b = _bb(obj.name)
        if a[0] < lo[0] + .20 and b[0] < lo[0] + 1.50 and b[1] - a[1] > 3.0:
            banks.append((a, b))
    if not banks:
        raise ValueError("Cannot locate left cooler bank for fitted fascia")
    front = max(b[0] for a, b in banks) + .025
    y0 = min(a[1] for a, b in banks)
    y1 = max(b[1] for a, b in banks)
    height, depth = .36, .12
    top = min(2.84, zc - .12)
    bottom = top - height
    m = sw.material("walnut", size_m=1.0, tint=(1.15, .95, .75), rough=(.40, .50), space="object", grain="y")
    obj = fl.mesh_object("LiqFascia", [(m, [("box", front - depth / 2, (y0 + y1) / 2, (bottom + top) / 2,
                                            depth, y1 - y0, height)])], bevel=False)
    bevel = obj.modifiers.new("Valance edge 2mm", "BEVEL")
    bevel.width = .002
    bevel.segments = 2
    stats["liq_fascia"] = 1
    stats["liq_fascia_fit"] = {"cooler_front": front - .025, "front": front, "depth": depth,
                               "y": [y0, y1], "z": [bottom, top]}


def _glow(lo, hi, stats):
    cx = (lo[0] + hi[0]) / 2; g = _emit("ir_liq_underglow", (1.0, 0.62, 0.3), 14.0); n = 0
    from room_planner import proc_boutique_flagship as fl
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("CheckoutCounterFactory")]:
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        mn = [min(p[i] for p in pts) for i in range(3)]; mx = [max(p[i] for p in pts) for i in range(3)]
        if mx[0] - mn[0] > 2.5 or mx[1] - mn[1] > 2.5 or max(mx[0] - mn[0], mx[1] - mn[1]) < 1.0:
            pass
        side = -1 if (mn[0] + mx[0]) / 2 > cx else 1                 # the face towards the room centre
        xs = mn[0] - 0.004 if side == -1 else mx[0] + 0.004
        fl.mesh_object(f"LiqUnderGlow({o.name})", [(g, [("box", xs, (mn[1] + mx[1]) / 2, mn[2] + 0.1, 0.012, (mx[1] - mn[1]) - 0.1, 0.03)])], bevel=False); n += 1
    stats["liq_glow"] = n


def _headers(lo, hi, stats):
    """S38 ref: no shelf-top category boards. The gondola mesh carries them as slots 2 (board) and 3 (letters) plus the last slot (the two hanger rods): those faces go."""
    import bmesh
    n = 0
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("GondolaFactory")]:
        ms = o.data.materials
        if len(ms) < 5:
            continue
        kill = {2, 3, len(ms) - 1}
        bm = bmesh.new(); bm.from_mesh(o.data)
        bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.material_index in kill], context="FACES")
        bm.to_mesh(o.data); bm.free(); n += 1
    stats["liq_headers_removed"] = n


def _shelf_leds(lo, hi, stats):
    """S38 ref: warm LED strip under the front lip of every gondola shelf (the shelf undersides of the gondola mesh) + under every wine-wall shelf."""
    from room_planner import proc_boutique_flagship as fl
    led = _emit("ir_liq_shelf_led", (1.0, 0.72, 0.4), 14.0)
    prims = []
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("GondolaFactory")]:
        mw = o.matrix_world; seen = set()
        for p in o.data.polygons:
            nz = (mw.to_3x3() @ p.normal).normalized().z
            c = mw @ p.center
            if nz > -0.95 or c.z < 0.35 or p.area < 0.08:
                continue
            vs = [mw @ o.data.vertices[i].co for i in p.vertices]
            x0, x1, y0, y1 = min(v.x for v in vs), max(v.x for v in vs), min(v.y for v in vs), max(v.y for v in vs)
            key = (round(c.z, 2), round(x0, 2), round(y0, 2))
            if key in seen:
                continue
            seen.add(key)
            if x1 - x0 > y1 - y0:                                  # long along x: lips at y0 / y1
                prims += [("box", (x0 + x1) / 2, yy, c.z - 0.008, x1 - x0 - 0.04, 0.012, 0.008) for yy in (y0 + 0.03, y1 - 0.03)]
            else:
                prims += [("box", xx, (y0 + y1) / 2, c.z - 0.008, 0.012, y1 - y0 - 0.04, 0.008) for xx in (x0 + 0.03, x1 - 0.03)]
    W = hi[0] - lo[0]; x0, x1 = lo[0] + 0.085 * W, lo[0] + 0.755 * W; yb = hi[1] - 0.01
    _, _, zs = _back_levels(_bb(f"{ROOM}.ceiling")[1][2])
    prims += [("box", (x0 + x1) / 2, yb - 0.33, z - 0.018, x1 - x0 - 0.1, 0.012, 0.008) for z in zs[1:]]
    fl.mesh_object("LiqShelfLeds", [(led, prims)], bevel=False)
    stats["liq_shelf_leds"] = len(prims)


def _gift_mats():
    from room_planner import proc_assets as pa
    return [pa._flat(f"ir_liq_gift_{i}", c, 0.45) for i, c in enumerate(((0.62, 0.05, 0.06), (0.04, 0.04, 0.05), (0.9, 0.87, 0.8), (0.12, 0.16, 0.3)))]


def _bottles_on(fac, x0, x1, y, z, rg, n0, step=0.085, k=0.85):
    """A row of upright library bottles along x at depth y on a shelf at height z; returns how many."""
    n = 0; x = x0 + step / 2; protos = []
    while x < x1 - step / 2:
        if len(protos) < 5:                                                 # S38 r15: 5 spawned prototypes per row, linked copies after (spawning every bottle cost ~70 s for the islands)
            o = _wine_label(fac.spawn_asset(n0 + n), rg); protos.append(o)
        else:
            o = protos[n % len(protos)].copy(); bpy.context.scene.collection.objects.link(o); o.scale = (1, 1, 1)
        h = max(o.dimensions.z, 1e-3); s = min(1.0, 0.32 / h) * k
        o.scale = (s, s, s); o.rotation_euler = (0, 0, rg.uniform(-0.4, 0.4)); o.location = (x, y + rg.uniform(-0.01, 0.01), z); x += step; n += 1
    return n


def _wine_label(o, rg):
    """Wine label art (product_labels_v2 drink_wine) in place of the library pack_atlas print: the label material (the one with an image) is copied per object and its image swapped."""
    try:
        from pathlib import Path
        files = sorted(Path("/jarvis/project/robomituba/data/venue_refs/product_labels_v2").glob("drink_wine_*.png")) ; files = [f for f in files if not any(k in f.name for k in ("_04", "_05"))] or files      # r17: no sake / whisky art on wine bottles
        if not files or o.type != "MESH":
            return o
        img = bpy.data.images.load(str(rg.choice(files)), check_existing=True)
        o.data = o.data.copy()
        for i, m in enumerate(o.data.materials):
            if m is not None and m.use_nodes and any(n.type == "TEX_IMAGE" for n in m.node_tree.nodes):
                m2 = m.copy(); o.data.materials[i] = m2
                for n in m2.node_tree.nodes:
                    if n.type == "TEX_IMAGE":
                        n.image = img
    except Exception:                                           # noqa: BLE001 -- a label is an extra
        pass
    return o


def _bm_obj(name, bm, mats, bevel=0.0, smooth=False):
    import bmesh
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for m in mats:
        me.materials.append(m)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    if bevel:
        md = o.modifiers.new("b", "BEVEL"); md.width = bevel; md.segments = 2; md.limit_method = "ANGLE"
    if smooth:
        for p_ in me.polygons:
            p_.use_smooth = True
    return o


def _cube(bm, c, s, mi, yaw=0.0):
    import bmesh
    from mathutils import Matrix
    r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=s, verts=r["verts"])
    if yaw:
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(yaw, 3, "Z"), verts=r["verts"])
    bmesh.ops.translate(bm, vec=c, verts=r["verts"])
    for f in {f for v in r["verts"] for f in v.link_faces}:
        f.material_index = mi


def _crate(name, x, y, z, yaw, opened, rg, bottle_fac):
    """A 2-bottle wooden wine crate (0.36 x 0.22 x 0.12 m): 5 mm base, end blocks, side boards as two planks with a gap, a grooved sliding lid of 3 planks; opened = lid slid half off with
    two library bottles lying inside. Wood-grain pine, burnt-in mark panel, bevelled edges."""
    import bmesh
    from mathutils import Matrix, Vector
    pa_ = __import__("room_planner.proc_assets", fromlist=["x"])
    pine = bpy.data.materials.get("ir_liq_crate_pine2")
    if pine is None:
        pine = pa_._flat("ir_liq_crate_pine2", (0.72, 0.52, 0.3), 0.6); pa_._grain(pine, (0.72, 0.52, 0.3))
    dark = pa_._flat("ir_liq_crate_brand", (0.25, 0.15, 0.08), 0.7)
    L, W, H, t = 0.36, 0.22, 0.12, 0.012
    bm = bmesh.new()
    _cube(bm, (0, 0, t / 2), (L, W, t), 0)                                       # base
    for sx in (-1, 1):
        _cube(bm, (sx * (L / 2 - t), 0, H / 2), (2 * t, W, H - 0.002), 0)            # end blocks
    for sy in (-1, 1):
        for zz, hh in ((t + 0.026, 0.05), (t + 0.08, 0.04)):                           # side planks with a gap
            _cube(bm, (0, sy * (W / 2 - t / 2), zz), (L - 4 * t, t, hh), 0)
    _cube(bm, (-L / 2 + t * 0.6, 0, H * 0.55), (0.002, W * 0.6, H * 0.4), 1)        # burnt mark on one end
    shift = (L * 0.45) if opened else 0.0
    for q in range(3):                                                                 # lid: 3 planks
        _cube(bm, (shift, -W / 2 + t + (q + 0.5) * (W - 2 * t) / 3, H + 0.004), (L - 2 * t, (W - 2 * t) / 3 - 0.003, 0.008), 0)
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(yaw, 3, "Z"), verts=bm.verts[:]); bmesh.ops.translate(bm, vec=(x, y, z), verts=bm.verts[:])
    o = _bm_obj(name, bm, [pine, dark], bevel=0.002)
    if opened and bottle_fac is not None:
        for j, dy in enumerate((-0.05, 0.05)):
            b = _wine_label(bottle_fac(rg.randrange(1 << 16)).spawn_asset(j), rg); h = max(b.dimensions.z, 1e-3); k = 0.28 / h
            b.scale = (k, k, k); b.rotation_euler = (0, math.pi / 2, yaw); c = Matrix.Rotation(yaw, 3, "Z") @ Vector((-0.02, dy, 0))
            b.location = (x + c.x - math.cos(yaw) * 0.14, y + c.y - math.sin(yaw) * 0.14, z + t + 0.04)
    return o


def _tube(name, x, y, z, rg):
    """A single-bottle presentation tube (Ø 9-10 cm, 34-38 cm), 64 segments, a slip-on cap with a fine gold rim, a printed band (no text)."""
    import bmesh
    pa_ = __import__("room_planner.proc_assets", fromlist=["x"])
    col = rg.choice(((0.32, 0.04, 0.07), (0.05, 0.05, 0.06), (0.86, 0.82, 0.74), (0.08, 0.16, 0.12)))
    body = pa_._flat(f"ir_liq_tube_{int(col[0] * 100)}_{int(col[1] * 100)}", col, 0.35); gold = pa_._flat("ir_liq_gold_foil", (0.83, 0.64, 0.28), 0.25, 1.0); band = pa_._flat("ir_liq_tube_band", (0.93, 0.9, 0.84), 0.5)
    r, h = rg.uniform(0.045, 0.05), rg.uniform(0.34, 0.38)
    bm = bmesh.new()
    def cyl(r_, z0, z1, mi):
        res = bmesh.ops.create_cone(bm, cap_ends=True, segments=64, radius1=r_, radius2=r_, depth=z1 - z0)
        bmesh.ops.translate(bm, vec=(0, 0, (z0 + z1) / 2), verts=res["verts"])
        for f in {f for v in res["verts"] for f in v.link_faces}:
            f.material_index = mi
    cyl(r, 0.0, h - 0.06, 0); cyl(r + 0.0025, h - 0.075, h, 0); cyl(r + 0.0032, h - 0.077, h - 0.071, 1); cyl(r + 0.001, h * 0.32, h * 0.52, 2); cyl(r + 0.0015, h * 0.335, h * 0.345, 1)
    bmesh.ops.translate(bm, vec=(x, y, z), verts=bm.verts[:])
    return _bm_obj(name, bm, [body, gold, band], bevel=0.0012, smooth=True)


def _bag(name, x, y, z, yaw, rg):
    """A kraft gift bag (0.16 x 0.09 x 0.36 m) with side gussets (inward V folds), a folded-over top cuff, and two twisted rope handles as tube curves."""
    import bmesh
    from mathutils import Matrix
    pa_ = __import__("room_planner.proc_assets", fromlist=["x"])
    kraft = pa_._flat("ir_liq_kraft", (0.6, 0.45, 0.3), 0.85); rope = pa_._flat("ir_liq_rope", (0.82, 0.76, 0.66), 0.9)
    w, d, h = 0.16, 0.09, 0.36
    bm = bmesh.new(); vs = []
    for zz in (0.0, h):                                                              # an 8-vertex ring per level: the gusset folds pinch the side centres inward
        ring = [(-w / 2, -d / 2), (0, -d / 2), (w / 2, -d / 2), (w / 2 - 0.025, 0), (w / 2, d / 2), (0, d / 2), (-w / 2, d / 2), (-w / 2 + 0.025, 0)]
        vs.append([bm.verts.new((px, py, zz)) for px, py in ring])
    for i in range(8):
        bm.faces.new((vs[0][i], vs[0][(i + 1) % 8], vs[1][(i + 1) % 8], vs[1][i]))
    bm.faces.new(vs[0][::-1])
    _cube(bm, (0, 0, h - 0.015), (w + 0.004, d + 0.004, 0.03), 0)                     # folded top cuff
    for f in bm.faces:
        f.material_index = 0
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(yaw, 3, "Z"), verts=bm.verts[:]); bmesh.ops.translate(bm, vec=(x, y, z), verts=bm.verts[:])
    o = _bm_obj(name, bm, [kraft], bevel=0.0015)
    sol = o.modifiers.new("s", "SOLIDIFY"); sol.thickness = 0.0015
    for sy in (-1, 1):                                                              # rope handles: a bezier arch on each face, round bevel
        cu = bpy.data.curves.new(f"{name}_h{sy}", "CURVE"); cu.dimensions = "3D"; cu.bevel_depth = 0.003; cu.bevel_resolution = 3
        sp = cu.splines.new("BEZIER"); sp.bezier_points.add(2)
        pts = [(-0.04, sy * (d / 2 - 0.004), h - 0.01), (0, sy * (d / 2 - 0.004), h + 0.09), (0.04, sy * (d / 2 - 0.004), h - 0.01)]
        for bp, p_ in zip(sp.bezier_points, pts):
            bp.co = p_; bp.handle_left_type = bp.handle_right_type = "AUTO"
        ho = bpy.data.objects.new(f"{name}_h{sy}", cu); ho.data.materials.append(rope); bpy.context.scene.collection.objects.link(ho)
        ho.rotation_euler = (0, 0, yaw); ho.location = (x, y, z)
    return o


GIFT_RX = r"christmas box present (red-blue|black-gold|white-gold|white-blue) [12] HSSD_"      # r17: the round "... 3" presents read as a steel pot + tins


def _gift(seed, x, y, z, yaw, size):
    """S38 r16: a real scanned gift box with ribbon (HSSD 'present' boxes: red-blue / black-gold / white-gold / white-blue), fitted to `size` m; None if the pool misses."""
    import real_assets as ra
    return ra.hssd(GIFT_RX, seed, x, y, z, yaw, fit=(size, size, size), size=(0.2, 0.6), grow=True)


def _islands(lo, hi, stats):
    """S38 ref: two separate low entrance islands (black steel frame, oak tiers) with bottles, red / black / cream gift boxes and a small plant on top."""
    from room_planner import proc_boutique_flagship as fl
    frame = fl._flat("ir_liq_frame", (0.03, 0.03, 0.034), 0.45, 0.8); oak = fl._flat("ir_liq_island_oak", (0.62, 0.45, 0.28), 0.5, wood=True)
    gifts = _gift_mats(); bf = _lib("BottleFactory"); rg = random.Random(21); nb = 0
    W, D = hi[0] - lo[0], hi[1] - lo[1]; L_, d_ = 1.35, 0.75
    for k, (u, v) in enumerate(((0.36, 0.29), (0.6, 0.29))):
        cx, cy = lo[0] + u * W, lo[1] + v * D
        tiers = (0.12, 0.45, 0.85)
        fr = [("box", cx + sx * (L_ / 2 - 0.02), cy + sy * (d_ / 2 - 0.02), 0.45, 0.035, 0.035, 0.9) for sx in (-1, 1) for sy in (-1, 1)]
        fr += [("box", cx, cy + sy * (d_ / 2 - 0.02), z, L_, 0.025, 0.03) for z in tiers for sy in (-1, 1)]
        sh = [("box", cx, cy, z + 0.02, L_ - 0.02, d_ - 0.02, 0.025) for z in tiers]
        boxes = {i: [] for i in range(4)}
        import real_assets as ra                                  # user 10-25 'make the boxes on the tables realistic': crates, tubes, kraft bags, library packs + bottles, no plain primitives
        ztop = 0.87 + 0.025; x0 = cx - L_ / 2 + 0.06
        _crate(f"LiqCrate{k}a", x0 + 0.2, cy + 0.17, ztop, rg.uniform(-0.08, 0.08), True, rg, bf)          # S38 r16 review: crates / tubes on the back row, the coloured gift boxes in front
        _crate(f"LiqCrate{k}b", x0 + 0.75, cy + 0.2, ztop, rg.uniform(-0.08, 0.08), False, rg, bf)
        _crate(f"LiqCrate{k}c", x0 + 0.76, cy + 0.2, ztop + 0.133, rg.uniform(-0.1, 0.1), k == 1, rg, bf)
        for j, (dx, dy) in enumerate(((0.47, 0.22), (0.58, 0.24), (0.52, 0.1))):
            _tube(f"LiqTube{k}{j}", x0 + dx + rg.uniform(-0.01, 0.01), cy + dy, ztop, rg)
        _bag(f"LiqBag{k}", x0 + 1.08, cy + 0.12, ztop, rg.uniform(-0.3, 0.3), rg)
        for j, (dx, dy, sz) in enumerate(((0.12, -0.2, 0.3), (0.42, -0.21, 0.26), (0.7, -0.2, 0.32), (0.98, -0.2, 0.27), (0.42, -0.21, 0.2))):
            if j == 4:
                ztop_ = ztop + 0.26; dx, dy = 0.43, -0.2                          # one box stacked on another
            else:
                ztop_ = ztop     # S38 r15 review: coloured gift boxes with ribbon (burgundy / navy / black / cream-gold), not beige packs
            if _gift(90 + k * 6 + j, x0 + dx, cy + dy, ztop_, rg.uniform(-0.25, 0.25), sz) is None:
                bx_ = ra.lib("FoodBoxFactory", 60 + k * 6 + j, x0 + dx, cy + dy, ztop_, rg.uniform(-0.25, 0.25), 1.0)
                if bx_ is not None:
                    _wine_label(bx_, rg)
        for j, dx in enumerate((-0.45, -0.1, 0.25)):                           # three more on the middle tier at its front edge
            _gift(110 + k * 4 + j, cx + dx, cy - d_ / 2 + 0.15, 0.45 + 0.033, rg.uniform(-0.3, 0.3), 0.28)
        fl.mesh_object(f"LiqIsland{k}", [(frame, fr), (oak, sh)] + [(gifts[i], boxes[i]) for i in range(4) if boxes[i]], bevel=False)
        if bf is not None:
            fac = bf(31 + k)
            for z in tiers[:2]:
                for yy in (cy - 0.2, cy + 0.2):
                    nb += _bottles_on(fac, cx - L_ / 2 + 0.03, cx + L_ / 2 - 0.03, yy, z + 0.033, rg, nb)
            nb += _bottles_on(fac, cx + 0.3, cx + L_ / 2 - 0.05, cy + 0.15, 0.893, rg, nb, step=0.09)
        try:
            from room_planner import plant_lib2
            pl = plant_lib2.plant("desk", 7 + k, k)
            if pl is not None:
                pl.location = (cx + 0.45, cy - 0.15, 0.895)
        except Exception:                                       # noqa: BLE001 -- a plant is an extra
            pass
    stats["liq_islands"] = {"islands": 2, "bottles": nb}


def _checkout(lo, hi, stats):
    """S38 ref: one L-shaped checkout at the right front (walnut slat front, white marble top, under-glow), POS screen, card terminal, flowers and a plant; replaces the pale CheckoutCounterFactory runs."""
    import scanned_wood as sw
    from room_planner import proc_assets as pa
    from room_planner import proc_boutique_flagship as fl
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("CheckoutCounterFactory")]:
        bpy.data.objects.remove(o, do_unlink=True)
    wal = sw.material("walnut", size_m=1.0, tint=(1.0, 0.9, 0.8), rough=(0.35, 0.55), space="object", grain="z")
    marble = pa._flat("ir_liq_marble", (0.93, 0.92, 0.9), 0.18); marble["weathered"] = True
    if not marble.get("veined"):
        nt = marble.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
        tc = N.new("ShaderNodeTexCoord"); wv = N.new("ShaderNodeTexWave"); wv.inputs["Scale"].default_value = 3.0; wv.inputs["Distortion"].default_value = 14.0; wv.inputs["Detail"].default_value = 6.0
        mr = N.new("ShaderNodeMapRange"); mr.inputs["From Min"].default_value = 0.0; mr.inputs["From Max"].default_value = 0.12
        mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.inputs["A"].default_value = (0.55, 0.55, 0.56, 1); mx.inputs["B"].default_value = (0.93, 0.92, 0.9, 1)
        L.new(tc.outputs["Object"], wv.inputs["Vector"]); L.new(wv.outputs["Fac"], mr.inputs["Value"]); L.new(mr.outputs["Result"], mx.inputs["Factor"]); L.new(mx.outputs["Result"], b.inputs["Base Color"]); marble["veined"] = 1
    dark = pa._flat("ir_liq_body_dark", (0.06, 0.05, 0.045), 0.6); glow = _emit("ir_liq_underglow", (1.0, 0.62, 0.3), 14.0)
    xa, xb, ya, yb = hi[0] - 1.65, hi[0] - 0.95, lo[1] + 0.9, lo[1] + 3.3            # long leg along the right wall
    ra0, ra1 = yb - 0.7, yb                                                           # return leg at its back end, to the wall
    body = [("box", (xa + xb) / 2, (ya + yb) / 2, 0.47, xb - xa, yb - ya, 0.94), ("box", (xb + hi[0]) / 2, (ra0 + ra1) / 2, 0.47, hi[0] - xb, ra1 - ra0, 0.94)]
    top = [("box", (xa + xb) / 2 - 0.02, (ya + yb) / 2, 0.965, xb - xa + 0.06, yb - ya + 0.04, 0.05), ("box", (xb + hi[0]) / 2, (ra0 + ra1) / 2 + 0.02, 0.965, hi[0] - xb, ra1 - ra0 + 0.06, 0.05)]
    slats = []
    y = ya + 0.03
    while y < yb - 0.03:
        slats.append(("box", xa - 0.015, y, 0.5, 0.03, 0.035, 0.78)); y += 0.06
    x = xa + 0.03
    while x < hi[0] - 0.05:
        slats.append(("box", x, ra1 + 0.015, 0.5, 0.035, 0.03, 0.78)); x += 0.06
    gl = [("box", xa - 0.04, (ya + yb) / 2, 0.09, 0.012, yb - ya - 0.06, 0.03), ("box", (xa + hi[0]) / 2, ra1 + 0.04, 0.09, hi[0] - xa - 0.06, 0.012, 0.03)]
    fl.mesh_object("LiqCheckoutL", [(dark, body), (marble, top), (wal, slats), (glow, gl)], bevel=False)
    blk = pa._flat("ir_liq_pos", (0.02, 0.02, 0.025), 0.3); scr = _emit("ir_liq_pos_screen", (0.55, 0.65, 0.8), 1.2)
    px, py = (xa + xb) / 2 + 0.05, ya + 1.1
    # S38 r15 review: a till-scale 12" touch screen on a short stand, a card reader with keypad, a receipt printer with a paper slot and a curl of receipt
    pos = [("cyl", (px, py, 0.99), (px, py, 1.0), 0.08, 24), ("cyl", (px, py, 1.0), (px, py, 1.1), 0.016, 12), ("box", px - 0.005, py, 1.2, 0.035, 0.3, 0.21)]
    grey = pa._flat("ir_liq_pos_grey", (0.22, 0.22, 0.24), 0.45); paper = pa._flat("ir_liq_receipt", (0.95, 0.95, 0.93), 0.7); keys = pa._flat("ir_liq_keys", (0.6, 0.6, 0.62), 0.4)
    rx, ry = xa + 0.17, py - 0.26                                                 # S38 r16 review: reader + printer were too small / set back: at the customer edge beside the till, a size up
    rdr = [("box", rx, ry, 1.005, 0.26, 0.13, 0.03, 0.25), ("box", rx + 0.01, ry, 1.045, 0.22, 0.11, 0.055, 0.25)]
    kp = [("box", rx + 0.03 + 0.03 * (i % 3) - 0.03, ry + 0.026 * (i // 3) - 0.026, 1.076, 0.02, 0.017, 0.005, 0.25) for i in range(9)]
    prn = [("box", px - 0.02, py + 0.30, 1.065, 0.2, 0.24, 0.15)]
    import real_assets as ra
    mon = ra.hssd(r"monitor arm - single", 3, px, py, 0.99, math.pi + 0.45, fit=(0.42, 0.42, 0.5), size=(0.3, 1.0), grow=True)      # S38 r15 review: the prim till read as a grey box; a scanned monitor on its arm, turned 25 deg towards the floor
    if mon is not None:
        pos, scr_ = [], []
    else:
        scr_ = [("box", px - 0.024, py, 1.2, 0.004, 0.27, 0.18)]
    grey = pa._flat("ir_liq_pos_grey2", (0.62, 0.62, 0.64), 0.4)                  # a light printer body: the dark one vanished against the walnut
    fl.mesh_object("LiqPOS", [(blk, pos + rdr), (keys, kp), (grey, prn), (paper, [("box", px - 0.02, py + 0.34, 1.15, 0.002, 0.11, 0.07)])] + ([(scr, scr_)] if scr_ else []))
    if mon is not None:
        _pos_screen(mon, stats)
    stats["liq_pos_real"] = int(mon is not None)
    vas = _lib("VaseFactory"); fw = pa._flat("ir_liq_flowers", (0.97, 0.96, 0.92), 0.7); st = pa._flat("ir_liq_stems", (0.25, 0.42, 0.2), 0.7)
    vx, vy = (xa + xb) / 2, ya + 0.25
    import real_assets as ra
    if ra.abo("smallplant", 77, vx, vy, 0.99, 0.0, fit=(0.35, 0.35, 0.45)) is not None:
        vas = None; fw = st = None                                # a real flowering plant replaces the vase + box blooms
    if vas is not None:
        v = vas(5).spawn_asset(0); s = 0.3 / max(v.dimensions.z, 1e-3); v.scale = (s, s, s); v.location = (vx, vy, 0.99)
    rg = random.Random(9)
    blooms = [("box", vx + rg.uniform(-0.13, 0.13), vy + rg.uniform(-0.13, 0.13), 1.33 + rg.uniform(0, 0.15), 0.07, 0.07, 0.06, rg.uniform(0, 3)) for _ in range(14)]
    leaves = [("box", vx + rg.uniform(-0.15, 0.15), vy + rg.uniform(-0.15, 0.15), 1.25 + rg.uniform(0, 0.1), 0.1, 0.03, 0.05, rg.uniform(0, 3)) for _ in range(10)]
    stems = [("cyl", (vx, vy, 1.1), (b_[1], b_[2], b_[3] - 0.03), 0.004, 5) for b_ in blooms]
    if fw is not None:
        fl.mesh_object("LiqCheckoutFlowers", [(fw, blooms), (st, leaves + stems)], bevel=False)
    try:
        from room_planner import plant_lib2
        pl = plant_lib2.plant("desk", 41, 3)
        if pl is not None:
            pl.location = ((xa + xb) / 2, yb - 0.25, 0.99)
    except Exception:                                           # noqa: BLE001
        pass
    stats["liq_checkout_L"] = 1


def _pos_screen(mon, stats):
    """S38 r16 review: the scanned monitor faced the room as a blank white panel. A dim emissive till UI (screen_content/pos_till_00.png: item rows, total, button grid) laid 4 mm
    in front of the display slot (the slot whose vertical faces all point one way)."""
    mw = mon.matrix_basis; n3 = mw.to_3x3()                            # real_assets places without a view-layer update: matrix_world is still identity here
    slots = {}                                                         # the display = the material slot whose vertical faces all point one way (the body slot has front + back)
    for p in mon.data.polygons:
        nw = (n3 @ p.normal).normalized()
        if abs(nw.z) < 0.5:
            a_ = p.area; e = slots.setdefault(p.material_index, [0.0, Vector((0, 0, 0)), []]); e[0] += a_; e[1] += nw * a_; e[2].append(p)
    cand = [(e[0], e) for e in slots.values() if e[0] > 0 and e[1].length / e[0] > 0.9]
    if not cand:
        return
    e = max(cand, key=lambda x: x[0])[1]
    nrm = e[1].normalized()
    on = [mw @ mon.data.vertices[i].co for p in e[2] for i in p.vertices]
    c = sum(on, Vector((0, 0, 0))) / len(on)
    mc = sum((mw @ Vector(q) for q in mon.bound_box), Vector((0, 0, 0))) / 8
    if (c - mc).dot(nrm) < 0:                                          # scanned meshes carry flipped normals: the display faces away from the monitor's centre
        nrm = -nrm
    t = Vector((0, 0, 1)).cross(nrm).normalized(); up = nrm.cross(t).normalized()      # t = the viewer's right when looking at the screen
    us = [(q - c).dot(t) for q in on]; vs = [(q - c).dot(up) for q in on]
    u0, u1, v0, v1 = min(us) + 0.01, max(us) - 0.01, min(vs) + 0.01, max(vs) - 0.01
    if u1 - u0 < 0.1 or v1 - v0 < 0.08:
        return
    o0 = c + nrm * 0.004
    quad = [o0 + t * u0 + up * v0, o0 + t * u1 + up * v0, o0 + t * u1 + up * v1, o0 + t * u0 + up * v1]
    m = bpy.data.materials.get("ir_liq_pos_ui")
    if m is None:
        m = bpy.data.materials.new("ir_liq_pos_ui"); m.use_nodes = True; m["weathered"] = True
        N, L = m.node_tree.nodes, m.node_tree.links; b = N["Principled BSDF"]
        im = N.new("ShaderNodeTexImage"); im.image = bpy.data.images.load("/jarvis/project/robomituba/data/venue_refs/screen_content/pos_till_00.png", check_existing=True)
        L.new(im.outputs["Color"], b.inputs["Base Color"]); L.new(im.outputs["Color"], b.inputs["Emission Color"])
        b.inputs["Emission Strength"].default_value = 1.4; b.inputs["Roughness"].default_value = 0.15
    from room_planner import rooftop_shell as rs
    rs._quads("LiqPOSScreen", [[tuple(q) for q in quad]], m)
    stats["liq_pos_screen"] = 1


def _cellar(lo, hi, stats):
    """S38 ref: twin narrow glass-door wine-cellar fridges at the back right (black frame, glass door, warm interior, racked bottles)."""
    from room_planner import proc_assets as pa
    from room_planner import proc_boutique_flagship as fl
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("DisplayCoolerFactory", "BeverageFridgeFactory"))]:
        b0 = [min((o.matrix_world @ Vector(c))[i] for c in o.bound_box) for i in range(3)]
        if b0[1] > lo[1] + 0.6 * (hi[1] - lo[1]) and b0[0] > lo[0] + 0.6 * (hi[0] - lo[0]):
            bpy.data.objects.remove(o, do_unlink=True)
    W = hi[0] - lo[0]; xs = lo[0] + 0.66 * W; yb = hi[1] - 0.02; d = 0.62; h = 2.05; w = 0.62      # r19: was .765 -> the wide1 probe camera (back-right corner) stood 0.41 m from the cabinet = the dark slab
    frame = fl._flat("ir_liq_frame", (0.03, 0.03, 0.034), 0.45, 0.8); glass = pa._flat("ir_liq_cellar_glass", (0.8, 0.85, 0.88), 0.03, transmission=0.92); glass["weathered"] = True
    warm = _emit("ir_liq_cellar_warm", (1.0, 0.72, 0.42), 6.0); rack = fl._flat("ir_liq_rack", (0.25, 0.16, 0.09), 0.6, wood=True); btl = pa._flat("ir_liq_cellar_bottle", (0.05, 0.12, 0.06), 0.15)
    cap = pa._flat("ir_liq_cellar_cap", (0.5, 0.06, 0.08), 0.4)
    fr, gl, wm, rk, bt, cp = [], [], [], [], [], []
    bf = _lib("BottleFactory"); rg = random.Random(91); protos = []; nlib = 0          # asset QA rev2 LQ-2: library wine bottles lying in the racks (were 240 cylinders + 120 caps)
    for k in range(2):
        cx = xs + w / 2 + k * (w + 0.04); cy = yb - d / 2
        fr += [("box", cx, cy, h / 2, w, d, 0.04), ("box", cx, cy, h - 0.02, w, d, 0.04), ("box", cx - w / 2 + 0.02, cy, h / 2, 0.04, d, h), ("box", cx + w / 2 - 0.02, cy, h / 2, 0.04, d, h),
               ("box", cx, cy - d / 2 + 0.03, 0.05, w, 0.06, 0.1), ("box", cx, cy - d / 2 + 0.01, h - 0.07, w, 0.02, 0.1), ("box", cx + w / 2 - 0.07, cy - d / 2 - 0.02, 1.05, 0.02, 0.03, 0.6)]
        gl.append(("box", cx, cy - d / 2 + 0.012, (0.12 + h - 0.12) / 2, w - 0.08, 0.008, h - 0.24))
        wm.append(("box", cx, yb - 0.01, h / 2, w - 0.1, 0.01, h - 0.2))
        for r_ in range(12):
            z = 0.2 + r_ * 0.145
            rk.append(("box", cx, cy, z, w - 0.08, d - 0.08, 0.012))
            for i_ in range(5):
                bx = cx - w / 2 + 0.1 + i_ * 0.105
                if bf is not None:
                    if len(protos) < 6:
                        bo = _wine_label(bf(93 + len(protos)).spawn_asset(nlib), rg); protos.append(bo)
                    else:
                        bo = protos[nlib % len(protos)].copy(); bpy.context.scene.collection.objects.link(bo); bo.scale = (1, 1, 1)
                    kk = 0.3 / max(max(bo.dimensions), 1e-3); bo.scale = (kk, kk, kk)
                    bo.rotation_euler = (math.pi / 2, 0, 0); bo.location = (bx, cy + 0.2, z + 0.05); nlib += 1      # base at the back, neck to the glass
                    continue
                bt.append(("cyl", (bx, cy + 0.2, z + 0.05), (bx, cy - 0.12, z + 0.05), 0.037, 10)); bt.append(("cyl", (bx, cy - 0.12, z + 0.05), (bx, cy - 0.24, z + 0.05), 0.014, 8))
                cp.append(("cyl", (bx, cy - 0.24, z + 0.05), (bx, cy - 0.255, z + 0.05), 0.016, 8))
    fl.mesh_object("LiqWineCellars", [(frame, fr), (glass, gl), (warm, wm), (rack, rk), (btl, bt), (cap, cp)], bevel=False)
    for k in range(2):                                          # a warm interior light per cabinet so the racked bottles read through the glass
        ld = bpy.data.lights.new(f"ir_liq_cellar_{k}", "POINT"); ld.energy = 25.0; ld.color = (1.0, 0.75, 0.5); ld.shadow_soft_size = 0.2
        o = bpy.data.objects.new(ld.name, ld); o.location = (xs + w / 2 + k * (w + 0.04), yb - d / 2, h - 0.25); bpy.context.scene.collection.objects.link(o)
    stats["liq_cellars"] = {"cabinets": 2, "lib_bottles": nlib}


def _in_room(o, lo, hi):
    c = o.matrix_world.translation
    return lo[0] - 0.2 < c.x < hi[0] + 0.2 and lo[1] - 0.2 < c.y < hi[1] + 0.2


def _light(lo, hi, zc, stats):
    """S38 r15 review: 1-2 stops dark and cool. Warm 3000 K spots at 1.8x, and 3 broad warm ceiling fills so the stock reads bright and warm (ROOM_LIQ_FILL_W per fill, default 110)."""
    k = 0
    for o in bpy.data.objects:
        if o.type == "LIGHT" and o.name.startswith("ir_liq_spot_"):
            o.data.energy *= float(os.environ.get("ROOM_LIQ_SPOT_GAIN") or 1.8); o.data.color = (1.0, 0.76, 0.52); k += 1
    fw = float(os.environ.get("ROOM_LIQ_FILL_W") or 110)
    for i, fy in enumerate((0.3, 0.55, 0.8)):
        ld = bpy.data.lights.new(f"ir_liq_fill_{i}", "AREA"); ld.shape = "RECTANGLE"; ld.size = (hi[0] - lo[0]) * 0.8; ld.size_y = 1.6; ld.energy = fw; ld.color = (1.0, 0.8, 0.6)
        o = bpy.data.objects.new(ld.name, ld); o.location = ((lo[0] + hi[0]) / 2, lo[1] + fy * (hi[1] - lo[1]), zc - 0.6); bpy.context.scene.collection.objects.link(o)
    # S38 r15 review: a visible ceiling wall-wash on the back wine wall -- a black recessed slot with a warm linear diffuser 0.35 m off the wall, and a grazing strip light tilted onto the wall
    from room_planner import proc_boutique_flagship as fl
    from room_planner import proc_assets as pa
    yw = hi[1] - 0.35; xa_, xb_ = lo[0] + 0.6, hi[0] - 1.6
    slot = pa._flat("ir_liq_wash_slot", (0.02, 0.02, 0.022), 0.5); lens = _emit("ir_liq_wash_lens", (1.0, 0.78, 0.52), 30.0)
    fl.mesh_object("LiqWallWash", [(slot, [("box", (xa_ + xb_) / 2, yw, zc - 0.03, xb_ - xa_ + 0.06, 0.1, 0.06)]), (lens, [("box", (xa_ + xb_) / 2, yw, zc - 0.062, xb_ - xa_, 0.05, 0.004)])], bevel=False)
    ld = bpy.data.lights.new("ir_liq_wallwash", "AREA"); ld.shape = "RECTANGLE"; ld.size = xb_ - xa_; ld.size_y = 0.08; ld.energy = float(os.environ.get("ROOM_LIQ_WASH_W") or 600); ld.color = (1.0, 0.76, 0.5)
    o = bpy.data.objects.new(ld.name, ld); o.location = ((xa_ + xb_) / 2, yw + 0.08, zc - 0.12); o.rotation_euler = (1.05, 0, 0); bpy.context.scene.collection.objects.link(o)      # S38 r20 A/B on r19 (wide3 wine-wall top 0.42 without, 0.61 at 650 W / 0.55 rad, 0.70 at 2200 W / 1.05 rad); S38 r16 review: invisible at 180 W; 650 W, nearer the wall (r19: the link call had slid into this comment, so the light never existed)
    stats["liq_light"] = {"spots": k, "fills": 3, "wallwash": 1}


_WINE_GLASS = {}


def _wine_glass(i):
    from room_planner import proc_assets as pa
    c = ((0.025, 0.07, 0.03), (0.06, 0.035, 0.015), (0.02, 0.045, 0.025))[i % 3]
    m = _WINE_GLASS.get(i % 3)
    if m is None:
        m = pa._flat(f"ir_liq_wine_glass_{i % 3}", c, 0.06); m["weathered"] = True
        b = m.node_tree.nodes["Principled BSDF"]
        for nm, v in (("Coat Weight", 0.6), ("Coat Roughness", 0.03), ("Specular IOR Level", 0.7)):
            if nm in b.inputs:
                b.inputs[nm].default_value = v
        _WINE_GLASS[i % 3] = m
    return m


def _paper_label(me, gi, k):
    """S38 r17 review: the label art wrapped the whole body like a coloured sleeve (read as beer). Label faces outside a front band (40 % of the body height, mid-body, ~150 deg arc) turn
    into the bottle's glass; the neck top (last 12 % of the length at the narrow end) gets a metallic foil capsule."""
    import math
    lab = [i for i, m in enumerate(me.materials) if m is not None and m.use_nodes and any(n.type == "TEX_IMAGE" for n in m.node_tree.nodes)]
    if not me.vertices:
        return
    lo_ = [min(v.co[a] for v in me.vertices) for a in range(3)]; hi_ = [max(v.co[a] for v in me.vertices) for a in range(3)]
    ax = max(range(3), key=lambda a: hi_[a] - lo_[a]); L = hi_[ax] - lo_[ax]
    if L <= 0:
        return
    o1, o2 = [a for a in range(3) if a != ax]; c1, c2 = (lo_[o1] + hi_[o1]) / 2, (lo_[o2] + hi_[o2]) / 2
    rad = lambda v: math.hypot(v.co[o1] - c1, v.co[o2] - c2)
    top = [rad(v) for v in me.vertices if v.co[ax] > hi_[ax] - 0.1 * L]; bot = [rad(v) for v in me.vertices if v.co[ax] < lo_[ax] + 0.1 * L]
    neck_hi = (sum(top) / max(len(top), 1)) < (sum(bot) / max(len(bot), 1))           # the narrow end is the neck
    if gi is None:
        gi = next((i for i in range(len(me.materials)) if i not in lab), None)
    if gi is None:
        me.materials.append(_wine_glass(k)); gi = len(me.materials) - 1
    from room_planner import proc_assets as pa
    foil = pa._flat(f"ir_liq_foil_{k % 3}", ((0.35, 0.03, 0.05), (0.03, 0.03, 0.035), (0.6, 0.45, 0.15))[k % 3], 0.3, 1.0); foil["weathered"] = True
    me.materials.append(foil); fi = len(me.materials) - 1
    for i in lab:                                                       # paper, not a printed sleeve: the label art at 45 % over cream paper, matte
        m = me.materials[i]; pm = bpy.data.materials.get(m.name + "_paper")
        if pm is None:
            pm = m.copy(); pm.name = m.name + "_paper"; nt = pm.node_tree; b_ = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
            src = b_.inputs["Base Color"].links[0].from_socket if b_ is not None and b_.inputs["Base Color"].links else None
            if src is not None:
                mx = nt.nodes.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.inputs["Factor"].default_value = 0.55; mx.inputs["B"].default_value = (0.93, 0.9, 0.82, 1)
                nt.links.new(src, mx.inputs["A"]); nt.links.new(mx.outputs["Result"], b_.inputs["Base Color"])
            if b_ is not None:
                b_.inputs["Roughness"].default_value = 0.75
            for n in nt.nodes:                                          # merch labels come from realize's liquor pool: swap the sake / whisky art for a wine one
                if n.type == "TEX_IMAGE" and n.image is not None and any(k in n.image.name for k in ("drink_wine_04", "drink_wine_05")):
                    n.image = bpy.data.images.load("/jarvis/project/robomituba/data/venue_refs/product_labels_v2/drink_wine_06.png", check_existing=True)
        me.materials[i] = pm
    for p in me.polygons:
        t = (p.center[ax] - lo_[ax]) / L
        t = t if neck_hi else 1.0 - t                                   # 0 = base, 1 = neck tip
        if t > 0.88:
            p.material_index = fi
        elif p.material_index in lab:
            ang = math.degrees(math.atan2(p.center[o2] - c2, p.center[o1] - c1))
            if not (0.17 < t < 0.43) or abs(ang) > 75:
                p.material_index = gi


def _wine(lo, hi, stats):
    """S38 r15 review: the merch bottles read as craft beer / oil / sauce. Every library bottle in the shop (gondolas, walls, islands) is narrowed to wine proportions (diameter = height / 4, the
    height is kept: it was already fitted to its shelf) and its body (the largest non-label slot) becomes dark green / brown wine glass; the label slot keeps its drink_wine art."""
    n, meshes = 0, {}
    for o in bpy.data.objects:
        if o.type != "MESH" or "Bottle" not in o.name or not _in_room(o, lo, hi):
            continue
        d = max(o.dimensions.x, o.dimensions.y); h = o.dimensions.z
        if d <= 0 or h <= 0:
            continue
        if o.dimensions.z < max(o.dimensions.x, o.dimensions.y):         # lying bottle (wine wall racks): narrow the two short axes
            ax = [0, 1, 2]; L = max(range(3), key=lambda i: o.dimensions[i]); k = (o.dimensions[L] / 4) / max(o.dimensions[i] for i in ax if i != L)
            if k < 1.0:
                sc = list(o.scale)
                for i in ax:
                    if i != L:
                        sc[i] *= k
                o.scale = sc
        else:
            k = (h / 4.0) / d
            if k < 1.0:
                o.scale = (o.scale.x * k, o.scale.y * k, o.scale.z)
        me = o.data
        if me.name not in meshes and me.materials:
            area = {}
            for p_ in me.polygons:
                area[p_.material_index] = area.get(p_.material_index, 0.0) + p_.area
            gi = None
            for i in sorted(area, key=area.get, reverse=True):
                m = me.materials[i] if i < len(me.materials) else None
                if m is not None and not any(nd.type == "TEX_IMAGE" for nd in (m.node_tree.nodes if m.use_nodes else [])):
                    me.materials[i] = _wine_glass(len(meshes)); gi = i; break
            _paper_label(me, gi, len(meshes))
            meshes[me.name] = 1
        n += 1
    stats["liq_wine_bottles"] = {"bottles": n, "meshes": len(meshes)}


def _pack(lo, hi, stats):
    """S38 r15 review: richer table packaging: a satin ribbon + bow on every tube, tissue paper puffing out of each kraft bag, a printed (blank) label panel on the bag front, crates stained darker."""
    import bmesh
    from room_planner import proc_assets as pa
    rib = pa._flat("ir_liq_ribbon", (0.62, 0.04, 0.06), 0.25); tis = pa._flat("ir_liq_tissue", (0.95, 0.93, 0.9), 0.8); lab = pa._flat("ir_liq_bag_label", (0.12, 0.1, 0.09), 0.5)
    rg = random.Random(77); n = 0
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("LiqTube")]:
        b0 = [min((o.matrix_world @ Vector(c))[i] for c in o.bound_box) for i in range(3)]; b1 = [max((o.matrix_world @ Vector(c))[i] for c in o.bound_box) for i in range(3)]
        cx, cy, r_ = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2, (b1[0] - b0[0]) / 2
        bm = bmesh.new(); zr = b0[2] + (b1[2] - b0[2]) * 0.62
        t = bmesh.ops.create_cone(bm, cap_ends=False, segments=48, radius1=r_ + 0.002, radius2=r_ + 0.002, depth=0.018); bmesh.ops.translate(bm, vec=(cx, cy, zr), verts=t["verts"])
        for sgn in (-1, 1):                                                # two bow loops: flattened tori
            tor = bmesh.ops.create_circle(bm, cap_ends=False, segments=16, radius=0.022)
            bmesh.ops.scale(bm, vec=(1.0, 0.35, 1.0), verts=tor["verts"]); bmesh.ops.translate(bm, vec=(cx + sgn * 0.022, cy - r_ - 0.004, zr), verts=tor["verts"])
        me = bpy.data.meshes.new(f"LiqRibbon{n}"); bm.to_mesh(me); bm.free(); me.materials.append(rib)
        ro = bpy.data.objects.new(me.name, me); bpy.context.scene.collection.objects.link(ro)
        sol = ro.modifiers.new("s", "SOLIDIFY"); sol.thickness = 0.004; n += 1
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("LiqBag") and "_h" not in o.name]:
        b0 = [min((o.matrix_world @ Vector(c))[i] for c in o.bound_box) for i in range(3)]; b1 = [max((o.matrix_world @ Vector(c))[i] for c in o.bound_box) for i in range(3)]
        cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
        bm = bmesh.new(); g = bmesh.ops.create_grid(bm, x_segments=14, y_segments=10, size=0.07)
        for v in g["verts"]:                                               # a crumpled tissue sheet bunched up out of the bag mouth
            r2 = (v.co.x ** 2 + v.co.y ** 2) ** 0.5
            v.co.z = 0.07 * (1 - min(1.0, r2 / 0.07)) + rg.uniform(-0.012, 0.012); v.co.x *= 1.1; v.co.y *= 0.55
        bmesh.ops.translate(bm, vec=(cx, cy, b1[2] - 0.01), verts=g["verts"])
        me = bpy.data.meshes.new(f"LiqTissue{n}"); bm.to_mesh(me); bm.free(); me.materials.append(tis)
        to = bpy.data.objects.new(me.name, me); bpy.context.scene.collection.objects.link(to)
        to.modifiers.new("ss", "SUBSURF").levels = 2; sol = to.modifiers.new("s", "SOLIDIFY"); sol.thickness = 0.001
        for p_ in me.polygons:
            p_.use_smooth = True
        from room_planner import proc_boutique_flagship as fl
        fl.mesh_object(f"LiqBagLabel{n}", [(lab, [("box", cx, b0[1] - 0.001, b0[2] + (b1[2] - b0[2]) * 0.55, 0.08, 0.002, 0.1)])], bevel=False); n += 1
    pine = bpy.data.materials.get("ir_liq_crate_pine2")
    if pine is not None and not pine.get("stained"):                       # a walnut-ish stain: the pale pine read as cardboard
        b = pine.node_tree.nodes["Principled BSDF"]
        for nd in pine.node_tree.nodes:
            if nd.type == "MIX" and nd.data_type == "RGBA":
                nd.inputs[6].default_value = (0.42, 0.26, 0.14, 1); nd.inputs[7].default_value = (0.27, 0.16, 0.08, 1)
        pine["stained"] = 1
    stats["liq_pack"] = n


def _floor(lo, hi, stats):
    """S38 r15 review: one flat orange tone. Scanned oak planks (visible seams), roughness variation, a thin clear coat for a subtle gloss."""
    import scanned_wood as sw
    m = sw.material("oak_plank", size_m=1.6, tint=(0.85, 0.56, 0.33), rough=(0.25, 0.5), coat=0.2, space="world", grain="x")     # warm honey oak (refs), not the pale scan
    f = bpy.data.objects.get(f"{ROOM}.floor")
    for sl in f.material_slots:
        sl.material = m
    stats["liq_floor"] = 1


def _door(lo, hi, stats):
    import shopfront_fix
    shopfront_fix.door(stats)


def _street(lo, hi, stats):
    import shopfront_fix
    shopfront_fix.street(lo, hi, stats)
    pav = bpy.data.materials.get("ir_liq_paving")                          # S38 r16 review: the paving read blotchy -> clean 300 mm concrete pavers, thin joints, slight per-slab tone
    if pav is not None and not pav.get("pavers"):
        nt = pav.node_tree; N, L = nt.nodes, nt.links
        for nd in [nd for nd in N if nd.type not in ("BSDF_PRINCIPLED", "OUTPUT_MATERIAL")]:
            N.remove(nd)
        b = N["Principled BSDF"]
        tc = N.new("ShaderNodeTexCoord"); br = N.new("ShaderNodeTexBrick"); br.offset = 0.0; br.squash = 1.0
        br.inputs["Scale"].default_value = 1.0 / 0.3; br.inputs["Brick Width"].default_value = 1.0; br.inputs["Row Height"].default_value = 1.0; br.inputs["Mortar Size"].default_value = 0.012; br.inputs["Mortar Smooth"].default_value = 0.2
        br.inputs["Color1"].default_value = (0.6, 0.6, 0.58, 1); br.inputs["Color2"].default_value = (0.55, 0.55, 0.53, 1); br.inputs["Mortar"].default_value = (0.32, 0.32, 0.31, 1); br.inputs["Bias"].default_value = 0.0
        L.new(tc.outputs["Object"], br.inputs["Vector"]); L.new(br.outputs["Color"], b.inputs["Base Color"])
        bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 0.4; bu.inputs["Distance"].default_value = 0.003
        L.new(br.outputs["Fac"], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"])
        b.inputs["Roughness"].default_value = 0.8; pav["pavers"] = 1


def _endcaps(lo, hi, stats):
    """S38 r15 review: bare black gondola ends, no price rails. A black price rail with white shelf-edge tags along every gondola shelf front, and a gift-box end display (red / navy / white cartons
    from the package library, wine labels) on the top of each gondola end."""
    from room_planner import proc_assets as pa
    from room_planner import proc_boutique_flagship as fl
    rail = pa._flat("ir_liq_price_rail", (0.03, 0.03, 0.035), 0.4); tag = pa._flat("ir_liq_price_tag", (0.95, 0.95, 0.92), 0.6)
    import real_assets as ra
    rg = random.Random(51); rp, tp, nb = [], [], 0
    gifts = _gift_mats()
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("GondolaFactory")]:
        mw = o.matrix_world; seen = set()
        for p in o.data.polygons:
            if (mw.to_3x3() @ p.normal).normalized().z < 0.95 or p.area < 0.08:
                continue
            c = mw @ p.center
            if c.z < 0.15:
                continue
            vs = [mw @ o.data.vertices[i].co for i in p.vertices]
            x0, x1, y0, y1 = min(v.x for v in vs), max(v.x for v in vs), min(v.y for v in vs), max(v.y for v in vs)
            key = (round(c.z, 2), round(x0, 2), round(y0, 2))
            if key in seen:
                continue
            seen.add(key)
            along_y = (y1 - y0) > (x1 - x0)
            for e in ((x0, x1) if along_y else (y0, y1)):                   # both long fronts of the shelf
                if along_y:
                    rp.append(("box", e + (-0.006 if e == x0 else 0.006), (y0 + y1) / 2, c.z - 0.018, 0.006, y1 - y0 - 0.02, 0.035))
                    yy = y0 + 0.12
                    while yy < y1 - 0.1:
                        tp.append(("box", e + (-0.01 if e == x0 else 0.01), yy, c.z - 0.018, 0.002, 0.05, 0.025)); yy += rg.uniform(0.25, 0.45)
                else:
                    rp.append(("box", (x0 + x1) / 2, e + (-0.006 if e == y0 else 0.006), c.z - 0.018, x1 - x0 - 0.02, 0.006, 0.035))
                    xx = x0 + 0.12
                    while xx < x1 - 0.1:
                        tp.append(("box", xx, e + (-0.01 if e == y0 else 0.01), c.z - 0.018, 0.05, 0.002, 0.025)); xx += rg.uniform(0.25, 0.45)
        b0 = [min((mw @ Vector(c_))[i] for c_ in o.bound_box) for i in range(3)]; b1 = [max((mw @ Vector(c_))[i] for c_ in o.bound_box) for i in range(3)]
        along_y = (b1[1] - b0[1]) > (b1[0] - b0[0])
        for end in ((0, 1) if os.environ.get("ROOM_LIQ_TOP_GIFTS") == "1" else ()):     # S38 r16 review: the ref keeps the gondola tops clear -> off by default again; ROOM_LIQ_TOP_GIFTS=1 turns them on
            for j in range(3):
                if along_y:
                    x = b0[0] + 0.15 + j * 0.28; y = (b0[1] + 0.18) if end == 0 else (b1[1] - 0.18)
                else:
                    y = b0[1] + 0.15 + j * 0.28; x = (b0[0] + 0.18) if end == 0 else (b1[0] - 0.18)
                if _gift(400 + nb, x, y, b1[2] + 0.002, rg.uniform(-0.25, 0.25), rg.uniform(0.2, 0.26)) is not None:
                    nb += 1; continue
                bx_ = ra.lib("FoodBoxFactory", 300 + nb, x, y, b1[2] + 0.002, rg.uniform(-0.2, 0.2), 1.0)
                if bx_ is None:
                    continue
                kk = min(0.26 / max(bx_.dimensions.z, 1e-3), 0.22 / max(bx_.dimensions.x, bx_.dimensions.y, 1e-3)); bx_.scale = (kk, kk, kk)
                _wine_label(bx_, rg)
                me = bx_.data
                if me.materials:                                           # the carton body (largest non-label slot) in a gift colour
                    area = {}
                    for p_ in me.polygons:
                        area[p_.material_index] = area.get(p_.material_index, 0.0) + p_.area
                    for i in sorted(area, key=area.get, reverse=True):
                        m = me.materials[i] if i < len(me.materials) else None
                        if m is not None and not any(nd.type == "TEX_IMAGE" for nd in (m.node_tree.nodes if m.use_nodes else [])):
                            me.materials[i] = gifts[nb % 4]; break
                nb += 1
    if rp:
        fl.mesh_object("LiqPriceRails", [(rail, rp), (tag, tp)], bevel=False)
    stats["liq_endcaps"] = {"rails": len(rp), "tags": len(tp), "gift_boxes": nb}


def _trailing_greenery(lo, hi, stats):
    """Supported cascading vines assembled from real HSSD pot and textured leaf geometry."""
    import real_assets as ra
    from mathutils import Matrix, Euler
    from room_planner import proc_boutique_flagship as fl
    source = ra.hssd(r"HSSD_09b1df19e95ab47e50c8aac06137ef2f51144d34", 0, 0, 0, 0, 0)
    if source is None:
        raise ValueError("Native trailing-plant geometry unavailable")
    source.data = source.data.copy()
    source.data.transform(Matrix.Rotation(math.pi / 2, 4, "X"))
    source.data.update()
    source.scale = (1, 1, 1)
    source.rotation_euler = (0, 0, 0)
    source.location = (0, 0, 0)
    bpy.context.view_layer.update()
    mesh = source.data
    def components(slot):
        polys = [p for p in mesh.polygons if p.material_index == slot]
        neighbours = {}
        for poly in polys:
            ids = list(poly.vertices)
            for v in ids:
                neighbours.setdefault(v, set()).update(ids)
        seen, assignments, result = set(), {}, []
        for v in neighbours:
            if v in seen:
                continue
            todo = [v]
            seen.add(v)
            group = len(result)
            result.append([])
            while todo:
                q = todo.pop()
                assignments[q] = group
                for r in neighbours[q]:
                    if r not in seen:
                        seen.add(r)
                        todo.append(r)
        for poly in polys:
            result[assignments[poly.vertices[0]]].append(poly)
        return result
    def bounds(polys):
        verts = [mesh.vertices[i].co for p in polys for i in p.vertices]
        return Vector(tuple(min(v[i] for v in verts) for i in range(3))), Vector(tuple(max(v[i] for v in verts) for i in range(3)))
    def subset(name, polys, mat, pot=False):
        a, b = bounds(polys)
        center = (a + b) / 2
        if pot:
            center.z = a.z
        ids = sorted({i for p in polys for i in p.vertices})
        index = {v: i for i, v in enumerate(ids)}
        data = bpy.data.meshes.new(name)
        data.from_pydata([tuple(mesh.vertices[i].co - center) for i in ids], [], [[index[i] for i in p.vertices] for p in polys])
        data.materials.append(mat)
        if mesh.uv_layers.active is not None:
            uv = data.uv_layers.new(name="NativeLeafUV")
            values = [mesh.uv_layers.active.data[i].uv.copy() for p in polys for i in p.loop_indices]
            for loop, value in zip(uv.data, values):
                loop.uv = value
        for face in data.polygons:
            face.use_smooth = True
        return data, b - a
    leaf_slot = next(i for i, m in enumerate(mesh.materials) if "::003" in m.name)
    pot_slot = next(i for i, m in enumerate(mesh.materials) if "::001" in m.name)
    native_leaf = mesh.materials[leaf_slot]
    image = next(n.image for n in native_leaf.node_tree.nodes
                 if n.type == "TEX_IMAGE" and n.image and n.image.filepath.endswith("/image_006.png"))
    leaf = bpy.data.materials.new("ir_liq_trailing_leaf")
    leaf.use_nodes = True
    leaf["weathered"] = True
    nodes, links = leaf.node_tree.nodes, leaf.node_tree.links
    bs = nodes.get("Principled BSDF")
    bs.inputs["Metallic"].default_value = 0
    bs.inputs["Roughness"].default_value = .6
    bs.inputs["IOR"].default_value = 1.45
    bs.inputs["Specular IOR Level"].default_value = .25
    bs.inputs["Emission Strength"].default_value = 0
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = image
    uv_node = nodes.new("ShaderNodeUVMap")
    uv_node.uv_map = "NativeLeafUV"
    links.new(uv_node.outputs["UV"], tex.inputs["Vector"])
    links.new(tex.outputs["Color"], bs.inputs["Base Color"])
    pot = mesh.materials[pot_slot].copy()
    pot.name = "ir_liq_trailing_pot"
    pot["weathered"] = True
    pbs = next(n for n in pot.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    for key, value in (("IOR", 1.45), ("Metallic", 0), ("Roughness", .6), ("Coat Weight", 0), ("Emission Strength", 0)):
        for link in list(pbs.inputs[key].links):
            pot.node_tree.links.remove(link)
        pbs.inputs[key].default_value = value
    candidates = []
    for part in components(leaf_slot):
        a, b = bounds(part)
        ext = sorted(b - a, reverse=True)
        # Reject round planter/soil disks; retain the native curved narrow leaves.
        if ext[0] > .03 and ext[1] > .005 and ext[0] / ext[1] > 2:
            candidates.append(part)
    if not candidates:
        raise ValueError("No native leaf component found")
    prototypes = [subset("LiqNativeLeaf", c, leaf) for c in candidates[:6]]
    pots = components(pot_slot)
    primary = max(pots, key=lambda c: len(c))
    a, b = bounds(primary)
    center = (a + b) / 2
    selected = []
    for part in pots:
        pa, pb = bounds(part)
        pc = (pa + pb) / 2
        if (pc - center).length < .08:
            selected.extend(part)
    pot_mesh, extent = subset("LiqNativePot", selected, pot, pot=True)
    pot_scale = .10 / max(extent)
    from room_planner import proc_assets as pa
    stem_mat = pa._flat("ir_liq_trailing_stem", (.045, .09, .018), .7)
    mounts = [(hi[0] - .22, 4.19, 2.5175, (-1, 0, 0)), (hi[0] - .22, 6.22, 2.5175, (-1, 0, 0)),
              (hi[0] - .22, 4.19, 1.5175, (-1, 0, 0)), (hi[0] - .22, 6.22, 1.0175, (-1, 0, 0)),
              (7.65, hi[1] - .15, 3.15, (0, -1, 0))]
    bracket_mat = pa._flat("ir_liq_trailing_bracket", (.025, .025, .025), .45, .2)
    # A real wall bracket supports the cooler-side pot; other pots stand on existing shelves.
    fl.mesh_object("LiqTrailingBracket", [(bracket_mat, [("box", 7.65, hi[1] - .10, 3.139, .18, .18, .018),
                          ("box", 7.65, hi[1] - .012, 3.08, .06, .012, .12)])], bevel=False)
    rg = random.Random(38027)
    for j, (x, y, z, normal) in enumerate(mounts):
        pot_obj = bpy.data.objects.new("LiqTrailingPot", pot_mesh)
        bpy.context.scene.collection.objects.link(pot_obj)
        pot_obj.scale = (pot_scale,) * 3
        pot_obj.location = (x, y, z + .002)
        normal = Vector(normal)
        tangent = Vector((-normal.y, normal.x, 0))
        root = Vector((x, y, z + .12))
        for branch in range(3):
            length = .46 + .045 * branch
            side = (branch - 1) * .045
            points = []
            for k in range(15):
                t = k / 14
                point = root + normal * (.015 + .09 * min(1, t * 4)) + tangent * (side + .025 * math.sin(t * 6 + branch))
                point.z -= length * t
                points.append(point)
                if k == 0:
                    continue
                proto, ext = prototypes[(j * 7 + branch * 3 + k) % len(prototypes)]
                obj = bpy.data.objects.new("LiqTrailingLeaf", proto)
                bpy.context.scene.collection.objects.link(obj)
                scale = rg.uniform(.035, .055) / max(ext)
                obj.scale = (scale,) * 3
                obj.location = point + tangent * ((-1 if k % 2 else 1) * .024)
                obj.rotation_mode = "QUATERNION"
                obj.rotation_quaternion = normal.to_track_quat("Z", "Y") @ Euler((rg.uniform(-.3, .3), rg.uniform(-.3, .3), rg.uniform(-.6, .6))).to_quaternion()
            curve = bpy.data.curves.new("LiqTrailingStem", "CURVE")
            curve.dimensions = "3D"
            curve.bevel_depth = .0013
            curve.bevel_resolution = 2
            spline = curve.splines.new("POLY")
            spline.points.add(len(points) - 1)
            for q, point in zip(spline.points, points):
                q.co = (*point, 1)
            stem = bpy.data.objects.new("LiqTrailingStem", curve)
            bpy.context.scene.collection.objects.link(stem)
            curve.materials.append(stem_mat)
            bpy.context.view_layer.update()
            stem_mesh = bpy.data.meshes.new_from_object(stem.evaluated_get(bpy.context.evaluated_depsgraph_get()))
            baked = bpy.data.objects.new("LiqTrailingStemMesh", stem_mesh)
            bpy.context.scene.collection.objects.link(baked)
            bpy.data.objects.remove(stem, do_unlink=True)
            if curve.users == 0:
                bpy.data.curves.remove(curve)
    bpy.data.objects.remove(source, do_unlink=True)
    stats["liq_trailing_greenery"] = {"pots": len(mounts), "leaves": len(mounts) * 42, "stems": len(mounts) * 3, "source": "HSSD_09b1df19e95ab47e50c8aac06137ef2f51144d34"}
    return len(mounts)


def _plants(lo, hi, stats):
    """S38 r15 review + refs: trailing greenery on the brick-wall shelves (Infinigen spider plants, arching leaves over the shelf edge), two tall floor plants inside the entrance, a real
    flower bouquet (Infinigen wild-flower stems in a glass vase) on the checkout instead of the tiny ABO plant."""
    from room_planner import plant_lib2
    from room_planner import proc_assets as pa
    n = 0
    trailing = False
    before = set(bpy.data.objects.keys())
    try:
        n += _trailing_greenery(lo, hi, stats)
        trailing = True
    except Exception as ex:
        stats["liq_trailing_greenery_error"] = repr(ex)[:160]
        for name in set(bpy.data.objects.keys()) - before:
            obj = bpy.data.objects.get(name)
            if obj is not None:
                bpy.data.objects.remove(obj, do_unlink=True)
    keep = os.environ.get("ROOM_DESK_PLANT_SPECIES")
    os.environ["ROOM_DESK_PLANT_SPECIES"] = "spiderplant"
    try:
        sh = bpy.data.objects.get("LiqFloatShelves")
        if sh is not None and not trailing:
            b0 = [min((sh.matrix_world @ Vector(c))[i] for c in sh.bound_box) for i in range(3)]; b1 = [max((sh.matrix_world @ Vector(c))[i] for c in sh.bound_box) for i in range(3)]
            for i, (fy, z) in enumerate(((0.15, 2.5), (0.85, 2.0), (0.2, 1.5), (0.8, 2.5), (0.5, 1.0))):
                # S38 r16: arching spider plants at the shelf FRONT edge, larger (0.55 m), so the leaves spill over the edge (r15: 0.38 m pots set back read as nothing;
                # the scanned HSSD 'Hanging plant' rendered as white strings -- no usable texture)
                pl = plant_lib2.plant("desk", 120 + i, i, h=0.8)
                if pl is not None:
                    _grow(pl, 0.85)                                             # S38 r16: plant_lib2 returned 0.26-0.3 m plants for h=0.55
                    pl.location = (b0[0] + 0.06, b0[1] + fy * (b1[1] - b0[1]), z + 0.0175); n += 1
    finally:
        if keep is None:
            os.environ.pop("ROOM_DESK_PLANT_SPECIES", None)
        else:
            os.environ["ROOM_DESK_PLANT_SPECIES"] = keep
    dr = bpy.data.objects.get("LiqGlassDoor")
    if dr is not None:                                                      # S38 r16 review: flank the DOOR, inside the glazing line
        d0 = min((dr.matrix_world @ Vector(c)).x for c in dr.bound_box); d1 = max((dr.matrix_world @ Vector(c)).x for c in dr.bound_box)
        xs = (max(lo[0] + 0.4, d0 - 0.5), d1 + 1.6)               # r20: the second plant at d1+0.55 swallowed the wide0 camera (1.36, 1.09)
    else:
        xs = (lo[0] + 0.55, lo[0] + 3.4)
    for i, x in enumerate(xs):
        pl = plant_lib2.plant("floor", 140 + i, i, h=1.85)                  # S38 r15 review: two TALL floor plants flank the entrance (r15: 1.26-1.48 m read as small pots)
        if pl is not None:
            _grow(pl, 1.85)
            pl.location = (x, lo[1] + 0.6, 0.0); n += 1
    for i, (px, py) in enumerate(((lo[0] + 3.97, lo[1] + 0.7), (lo[0] + 5.27, lo[1] + 0.7))):       # r21: against the south glass wall between the entrance plants and the checkout: outside the central 70% of every probe frame within 4 m, >= 1 m from each camera (r20 (3.4, 1.45) and (7.5, 3.0) stood in front of the lenses)
        pl = plant_lib2.plant("floor", 150 + i, i, h=1.8)
        if pl is not None:
            _grow(pl, 1.8); pl.location = (px, py, 0.0); n += 1
    for o in [o for o in bpy.data.objects if o.name.startswith("Real_smallplant")]:
        bpy.data.objects.remove(o, do_unlink=True)
    co = bpy.data.objects.get("LiqCheckoutL")
    if co is not None:
        import real_assets as ra
        c0 = [min((co.matrix_world @ Vector(c))[i] for c in co.bound_box) for i in range(3)]; c1 = [max((co.matrix_world @ Vector(c))[i] for c in co.bound_box) for i in range(3)]
        b = ra.hssd(r"hydrangea & lilacs|lily arrangement|dendrobium orchid|phalaenopsis", 17, hi[0] - 1.3, c0[1] + 0.35, 0.99, math.pi, fit=(0.4, 0.4, 0.45), cats=("vase", "plant", "flower", "flowerpot"), size=(0.2, 0.9), grow=True)
        b = b or ra.hssd(r"rose bouquet|bouquet|flowers? vase|tulips?|peony|hydrangea", 17, hi[0] - 1.3, c0[1] + 0.35, 0.99, 0.0, fit=(0.35, 0.35, 0.45), cats=("vase", "plant", "flower"), size=(0.2, 0.9), grow=True)   # r15: the narrow single 'Rose Bouquet Vase' (12 cm) read as nothing
        if b is None:                                                       # asset QA rev2 R4: the scanned bouquet first, the Infinigen bud vase only as the fallback
            pa.STYLE.setdefault("infinigen_plants", True)
            b = pa.BudVaseFactory(17, big=True).spawn_asset(0)
            sb = 0.45 / max(b.dimensions.z, 1e-3)                           # a ~45 cm counter bouquet (the big bud vase grew 0.8 m stems)
            b.scale = (sb, sb, sb); b.location = (hi[0] - 1.3, c0[1] + 0.3, 0.99)
        n += 1
    stats["liq_plants"] = n


def _grow(o, h):
    """Uniform scale so the object's height is h (plant_lib2 often returns shorter plants than asked)."""
    hz = o.dimensions.z or 1e-3
    if hz < h * 0.9:
        k = h / hz; o.scale = tuple(v * k for v in o.scale)


def _racks(lo, hi, stats):
    """S38 refs: two rear-right horizontal bottle racks (oak cubby racks, bottles lying neck-out): one on the right wall behind the brick shelves, one on the back wall right of the cellar."""
    from room_planner import proc_boutique_flagship as fl
    oak = fl._flat("ir_liq_rack_oak", (0.32, 0.2, 0.11), 0.55, wood=True)
    bf = _lib("BottleFactory"); rg = random.Random(61); nb = 0; prims = []
    W, H, D, nx, nz = 0.9, 1.8, 0.34, 6, 11
    specs = (("x", hi[0] - 0.01 - D / 2, hi[1] - 1.0 - W / 2), ("y", hi[0] - 0.55, hi[1] - 0.01 - D / 2))
    import real_assets as ra
    real_ = 0
    CX, CZ = (-0.325, -0.195, -0.065, 0.065, 0.195, 0.325), (0.10, 0.24, 0.38, 0.52)   # the scanned rack's 6 x 4 diamond cells (unit 0.80 x 0.62 x 0.29, local, front -y)
    for axis, a, b in list(specs):                                          # asset QA rev2 LQ-12: the scanned HSSD '30 Bottle Wine Rack' stacked 3 high instead of 38 oak boxes, library bottles lying in its cells
        th = math.pi if axis == "x" else -math.pi / 2; z0 = 0.0; got = []; dep = 0.29
        px, py = ((hi[0] - 0.01 - dep / 2, b) if axis == "x" else (a, hi[1] - 0.01 - dep / 2))
        nl = 2 if axis == "x" else 3                                         # the right-wall rack stays under the brick wall's lowest floating shelf (1.5 m)
        for lvl in range(nl):
            o = ra.hssd(r"^30 bottle wine rack", 600 + lvl, px, py, z0, th, fit=(W, 0.4, H / 3), grow=True)
            if o is None:
                break
            got.append((o, z0, o.scale.x)); z0 = ra.top(o)
        if len(got) < nl:
            for o, _z, _k in got:
                bpy.data.objects.remove(o, do_unlink=True)
            continue
        real_ += 1; specs = tuple(sp for sp in specs if sp[0] != axis)
        if bf is None:
            continue
        fac = bf(71); protos = []
        for o, zb, k in got:
            for cx in CX:
                for cz in CZ:
                    if rg.random() < 0.1:
                        continue
                    if len(protos) < 8:
                        bo = _wine_label(fac.spawn_asset(nb), rg); protos.append(bo)
                    else:
                        bo = protos[nb % len(protos)].copy(); bpy.context.scene.collection.objects.link(bo); bo.scale = (1, 1, 1)
                    L_ = max(bo.dimensions); kk = min(0.30, 0.29 * k + 0.02) / max(L_, 1e-3)
                    bo.scale = (kk, kk, kk); u = cx * k; z = zb + cz * k                  # lying in the cell, base at the wall, neck out into the room
                    if axis == "x":
                        bo.rotation_euler = (0, -math.pi / 2, 0); bo.location = (hi[0] - 0.02, b + u, z)
                    else:
                        bo.rotation_euler = (math.pi / 2, 0, 0); bo.location = (a + u, hi[1] - 0.02, z)
                    nb += 1
    for axis, a, b in specs:
        cw, ch = W / nx, H / nz
        for i in range(nx + 1):
            u = -W / 2 + i * cw
            prims.append(("box", a, b + u, H / 2, D, 0.015, H) if axis == "x" else ("box", a + u, b, H / 2, 0.015, D, H))
        for j in range(nz + 1):
            z = j * ch
            prims.append(("box", a, b, z + 0.0075, D, W, 0.015) if axis == "x" else ("box", a, b, z + 0.0075, W, D, 0.015))
        if bf is None:
            continue
        fac = bf(71); protos = []
        for i in range(nx):
            for j in range(nz):
                if rg.random() < 0.12:
                    continue
                if len(protos) < 8:
                    o = _wine_label(fac.spawn_asset(nb), rg); protos.append(o)
                else:
                    o = protos[nb % len(protos)].copy(); bpy.context.scene.collection.objects.link(o); o.scale = (1, 1, 1)
                L = max(o.dimensions); k = min(0.3, D - 0.02) / max(L, 1e-3)
                o.scale = (k, k, k)
                u = -W / 2 + (i + 0.5) * cw; z = j * ch + 0.015 + 0.04
                if axis == "x":
                    o.rotation_euler = (0, math.pi / 2, 0); o.location = (a + 0.02, b + u, z)
                else:
                    o.rotation_euler = (math.pi / 2, 0, 0); o.location = (a + u, b + 0.02, z)
                nb += 1
    if prims:
        fl.mesh_object("LiqBottleRacks", [(oak, prims)])
    stats["liq_racks"] = {"racks": 2, "real": real_, "bottles": nb}


def _counter_card(c0, c1, zt, stats):
    """One illustrated, non-emissive counter sign facing the customer aisle."""
    import ratio1_common as rc
    from mathutils import Matrix
    mat = bpy.data.materials.get("ir_liq_counter_print")
    if mat is None:
        mat = bpy.data.materials.new("ir_liq_counter_print")
        mat.use_nodes = True
        mat["weathered"] = True
        nodes, links = mat.node_tree.nodes, mat.node_tree.links
        bs = nodes.get("Principled BSDF")
        bs.inputs["Base Color"].default_value = (0.82, 0.77, 0.65, 1)
        bs.inputs["Roughness"].default_value = 0.8
        bs.inputs["Emission Strength"].default_value = 0
        uv = nodes.new("ShaderNodeTexCoord")
        sep = nodes.new("ShaderNodeSeparateXYZ")
        links.new(uv.outputs["UV"], sep.inputs["Vector"])
        def op(kind, a, b):
            n = nodes.new("ShaderNodeMath")
            n.operation = kind
            for i, value in enumerate((a, b)):
                if isinstance(value, (float, int)):
                    n.inputs[i].default_value = value
                else:
                    links.new(value, n.inputs[i])
            return n.outputs[0]
        def rect(x0, x1, y0, y1):
            x = op("MULTIPLY", op("GREATER_THAN", sep.outputs["X"], x0), op("LESS_THAN", sep.outputs["X"], x1))
            y = op("MULTIPLY", op("GREATER_THAN", sep.outputs["Y"], y0), op("LESS_THAN", sep.outputs["Y"], y1))
            return op("MULTIPLY", x, y)
        # Printed bottle silhouette, neck and pale paper label; no luminous surface.
        silhouette = op("MAXIMUM", rect(.34, .66, .37, .76), rect(.43, .57, .73, .92))
        mix = nodes.new("ShaderNodeMixRGB")
        mix.inputs[1].default_value = (.82, .77, .65, 1)
        mix.inputs[2].default_value = (.055, .09, .048, 1)
        links.new(silhouette, mix.inputs[0])
        label = nodes.new("ShaderNodeMixRGB")
        label.inputs[2].default_value = (.89, .84, .72, 1)
        links.new(mix.outputs[0], label.inputs[1])
        links.new(rect(.37, .63, .47, .61), label.inputs[0])
        links.new(label.outputs[0], bs.inputs["Base Color"])
    x, y = c0[0] + .20, min(c1[1] - .40, c0[1] + 1.77)
    yaw, lean, width, height = -math.pi / 2, .16, .16, .23
    rc.card(x, y, zt, yaw, width, height, mat, tag="liq", lean=lean)
    face = next(o for o in reversed(list(bpy.data.objects)) if o.type == "MESH" and o.name.startswith("liq_CardFace") and o.data.materials[0] == mat)
    uv = face.data.uv_layers.new(name="CounterPrintUV")
    uv.active_render = True
    for poly in face.data.polygons:
        for li in poly.loop_indices:
            v = face.data.vertices[face.data.loops[li].vertex_index].co
            uv.data[li].uv = ((v.x + (width - .03) / 2) / (width - .03), (v.z - .015) / (height - .03))
    ink = rc.flat("ir_liq_counter_ink", (.025, .025, .023), .8)
    transform = Matrix.Translation((x, y, zt)) @ Matrix.Rotation(yaw, 4, "Z") @ Matrix.Rotation(-lean, 4, "X")
    for text, z, size in (("WINE", .052, .025), ("SELECTION", .027, .012)):
        data = bpy.data.curves.new("LiqCounterPrint", "FONT")
        data.body = text
        data.align_x = "CENTER"
        data.size = size
        data.extrude = 0
        obj = bpy.data.objects.new("LiqCounterPrint", data)
        bpy.context.scene.collection.objects.link(obj)
        data.materials.append(ink)
        obj.matrix_world = transform @ Matrix.Translation((0, -.010, z)) @ Matrix.Rotation(math.pi / 2, 4, "X")
        # The scene exporter retains meshes; bake glyph geometry before removing the temporary font.
        bpy.context.view_layer.update()
        mesh = bpy.data.meshes.new_from_object(obj.evaluated_get(bpy.context.evaluated_depsgraph_get()))
        if not mesh.polygons:
            raise ValueError("Counter sign lettering produced no exportable faces")
        printed = bpy.data.objects.new("LiqCounterPrintMesh", mesh)
        bpy.context.scene.collection.objects.link(printed)
        printed.matrix_world = obj.matrix_world.copy()
        if not mesh.materials:
            mesh.materials.append(ink)
        bpy.data.objects.remove(obj, do_unlink=True)
        if data.users == 0:
            bpy.data.curves.remove(data)
    stats["liq_counter_card"] = {"count": 1, "location": [x, y, zt], "front": "-X", "width": width, "height": height}


def _ratio1(lo, hi, zc, stats):
    """Reference-ratio pass (user 2026-10-26): gridded white AC cassette, entrance mat, trailing spider plants + small pots on the gondola ends, framed promo cards and a warm under-glow on the checkout,
    white-flower arrangement fix (see _plants), foliage fix. Shared helpers in ratio1_common.py."""
    import ratio1_common as rc
    import real_assets as ra
    from room_planner import plant_lib2
    got = {}
    for o in [o for o in bpy.data.objects if o.name.startswith("LiqCassetteAC")]:
        a, b = rc.bb(o); cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2; bpy.data.objects.remove(o, do_unlink=True)
        rc.cassette(cx, cy, zc, size=0.95, drop=0.16, tag="liq"); got["ac"] = 1
    dr = bpy.data.objects.get("door") or bpy.data.objects.get("LiqGlassDoor")
    dx = max(lo[0] + 0.8, (rc.bb(dr)[0][0] + rc.bb(dr)[1][0]) / 2) if dr is not None else lo[0] + 2.0
    got["mat"] = int(rc.mat(ra, dx, lo[1] + 0.9, lo[2], 1.2, 0.8, tag="liq") is not None)
    keep = os.environ.get("ROOM_DESK_PLANT_SPECIES"); os.environ["ROOM_DESK_PLANT_SPECIES"] = "spiderplant"; k = 0
    try:
        for gi, o in enumerate([o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("GondolaFactory")]):
            a, b = rc.bb(o); ay = (b[1] - a[1]) > (b[0] - a[0])
            for ei, e in enumerate((0, 1)):
                px, py = ((a[0] + b[0]) / 2, (a[1] + 0.3) if e == 0 else (b[1] - 0.3)) if ay else ((a[0] + 0.3) if e == 0 else (b[0] - 0.3), (a[1] + b[1]) / 2)
                pl = plant_lib2.plant("desk", 200 + gi * 2 + ei, gi * 2 + ei, h=0.42)
                if pl is not None:
                    _grow(pl, 0.42); pl.location = (px, py, b[2] + 0.01); k += 1
    finally:
        os.environ.pop("ROOM_DESK_PLANT_SPECIES", None) if keep is None else os.environ.__setitem__("ROOM_DESK_PLANT_SPECIES", keep)
    got["end_plants"] = k
    co = bpy.data.objects.get("LiqCheckoutL")
    if co is not None:
        c0, c1 = rc.bb(co); zt = c1[2]
        try:
            _counter_card(c0, c1, zt, stats)
        except Exception as ex:
            stats["liq_counter_card_error"] = repr(ex)[:160]
        g = _emit("ir_liq_counter_glow", (1.0, 0.64, 0.32), 16.0)
        from room_planner import proc_boutique_flagship as fl
        fl.mesh_object("LiqCounterGlow", [(g, [("box", (c0[0] + c1[0]) / 2, c0[1] - 0.004, c0[2] + 0.12, c1[0] - c0[0] - 0.2, 0.012, 0.03), ("box", c0[0] - 0.004, (c0[1] + c1[1]) / 2, c0[2] + 0.12, 0.012, c1[1] - c0[1] - 0.2, 0.03)])], bevel=False)
        got["counter"] = 1
    for card in bpy.data.objects:
        if card.type == "MESH" and card.name.startswith("liq_CardFace"):
            _panel_uv(card)
    got["plant_fix"] = rc.plant_fix_all()
    stats["liq_ratio1"] = got


def apply(stats):
    sc = bpy.context.scene
    if sc.get("ir_liq_shell") or bpy.data.objects.get(f"{ROOM}.floor") is None:
        return 0
    skip = set((os.environ.get("ROOM_LIQ_SKIP") or "").split(","))
    lo, hi = _bb(f"{ROOM}.floor"); zc = _bb(f"{ROOM}.ceiling")[1][2]; n = 0
    for key, fn in (("ceil", lambda: _ceiling(lo, hi, zc, stats)), ("back", lambda: _back(lo, hi, zc, stats)), ("brick", lambda: _brick(lo, hi, zc, stats)),
                    ("fascia", lambda: _fascia(lo, hi, zc, stats)), ("headers", lambda: _headers(lo, hi, stats)), ("leds", lambda: _shelf_leds(lo, hi, stats)),
                    ("islands", lambda: _islands(lo, hi, stats)), ("checkout", lambda: _checkout(lo, hi, stats)), ("cellar", lambda: _cellar(lo, hi, stats)), ("glow", lambda: _glow(lo, hi, stats)),
                    ("racks", lambda: _racks(lo, hi, stats)), ("endcaps", lambda: _endcaps(lo, hi, stats)), ("pack", lambda: _pack(lo, hi, stats)), ("floor", lambda: _floor(lo, hi, stats)),
                    ("door", lambda: _door(lo, hi, stats)), ("street", lambda: _street(lo, hi, stats)), ("plants", lambda: _plants(lo, hi, stats)), ("light", lambda: _light(lo, hi, zc, stats)),
                    ("wine", lambda: _wine(lo, hi, stats)), ("ratio1", lambda: _ratio1(lo, hi, zc, stats))):
        if key not in skip:
            import time as _t; t0_ = _t.time()
            try:
                bpy.context.view_layer.update(); fn(); n += 1
            except Exception as ex:                                       # noqa: BLE001 -- asset QA rev2 R8: one failing part must not abort the rest
                import traceback; traceback.print_exc(); stats[f"liq_{key}_error"] = repr(ex)[:160]
            stats.setdefault("liq_secs", {})[key] = round(_t.time() - t0_, 1); print(f"[liq_shell] {key} {_t.time() - t0_:.1f}s", flush=True)
    import ratio1_plants, ratio1_checkout; ratio1_plants.apply(stats); ratio1_checkout.apply(stats)
    import real_assets as ra
    ra.report(stats, "liq")
    sc["ir_liq_shell"] = 1
    return n
