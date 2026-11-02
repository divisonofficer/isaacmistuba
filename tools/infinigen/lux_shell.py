"""L1 lux showroom floor shell (kit stage, idempotent via scene["ir_lux_shell"]); ROOM_LUX_SHELL=1 enables every part, ROOM_LUX_SKIP=<comma list of main,entry,gallery,vip,light> switches parts off (clean, main, mainfloor, entry, gallery, vip, furn, island, vase, light).
Rooms (break-room_0/N): 0 entry_hall (0-12 x 0-10), 1 gallery (0-12 x 10-20), 2 main_lounge (12-30 x 0-12), 3 vip_lounge (12-30 x 12-20); wall height ~6.2 m. Everything is read from each room's floor / ceiling bbox.
main     hammered mirror-steel ceiling (metallic, low roughness, lumpy bump), 10 bronze U-ribbon loops hanging from it (layout_main_lounge.json ceiling_features, local (x, y) -> floor (xmin + y, ymax - x)),
         a black perimeter soffit band with downlights, white fluted partition cladding along the west wall
entry    ~6 x 7 m LED wall on the back wall (emissive abstract green / white burst, no text), glossy dark-grey 1.2 x 0.8 m stone (ROOM_LUX_ENTRY_STONE=0 restores 60 cm tile), LED under-glow on the white_island plinth
gallery  beige carpet, light oak vertical panel wall (back wall), cove-lit ceiling strips
vip      dark brown wall panels, glossy dark 60 cm tile, a dropped ceiling at 3.5 m with linear LED slots, backlit magazine shelving on the back wall
light    warm 3500 K downlight spots on a ~3.2 m grid in every room (ROOM_LUX_DL_W per spot, default 140)
"""
from __future__ import annotations

import math
import os
import random

import bpy
import bmesh
from mathutils import Vector

ROOMS = {"entry": "break-room_0/0", "gallery": "break-room_0/1", "main": "break-room_0/2", "vip": "break-room_0/3"}


def _bb(name):
    if name.endswith(".floor"):                                  # floor boxes out to the walls' INNER faces (the entry hall's S wall sits ~0.12 m inside the floor box; audit 10-25)
        import wall_face
        return wall_face.inner_box(name[:-6])
    o = bpy.data.objects.get(name)
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(p[i] for p in pts) for i in range(3)], [max(p[i] for p in pts) for i in range(3)]


def _lib(name):
    from room_planner import lib_objects
    return lib_objects.factory(name)


def _fl():
    from room_planner import proc_boutique_flagship as fl
    return fl


def _pa():
    from room_planner import proc_assets as pa
    return pa


def _emit(name, rgb, strength):
    m = _pa()._flat(name, rgb, 0.4); b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*rgb, 1.0); b.inputs["Emission Strength"].default_value = strength
    return m


def _tile(name, rgb, rough, size=0.6, grout=0.012, mrgb=None):
    """World-space square tile floor: Brick texture (square cells) with a darker mortar."""
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = _pa()._flat(name, rgb, rough, 0.0); m["weathered"] = True
    nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); br = N.new("ShaderNodeTexBrick"); L.new(tc.outputs["Object"], br.inputs["Vector"])
    br.offset = 0.0; br.inputs["Scale"].default_value = 1.0 / size; br.inputs["Brick Width"].default_value = 1.0; br.inputs["Row Height"].default_value = 1.0; br.inputs["Mortar Size"].default_value = grout / size
    br.inputs["Color1"].default_value = (*rgb, 1); br.inputs["Color2"].default_value = (rgb[0] * 0.9, rgb[1] * 0.9, rgb[2] * 0.9, 1); br.inputs["Mortar"].default_value = (*(mrgb or [c * 0.4 for c in rgb]), 1)
    L.new(br.outputs["Color"], b.inputs["Base Color"])
    return m


def _set_floor(room, mat):
    f = bpy.data.objects.get(f"{room}.floor")
    for sl in f.material_slots:
        sl.material = mat


def _set_ceiling(room, mat):
    c = bpy.data.objects.get(f"{room}.ceiling")
    for sl in c.material_slots:
        sl.material = mat


def _rm_ceiling_clutter(lo, hi, zc, names=("CeilingGridFactory", "LinearLedFactory", "DiffuserFactory", "DropCeilingFactory", "CeilingLightFactory", "CeilingBeamFactory", "SoffitFactory", "TrackRailFactory", "TrackSpotFactory")):
    for o in list(bpy.data.objects):
        if o.name.startswith(names):
            pts = [o.matrix_world @ Vector(c) for c in o.bound_box]; cx = sum(p.x for p in pts) / 8; cy = sum(p.y for p in pts) / 8             # bbox centre: a ceiling piece's origin can sit at the world origin (r3: the drop ceiling stayed)
            if lo[0] - 0.3 <= cx <= hi[0] + 0.3 and lo[1] - 0.3 <= cy <= hi[1] + 0.3 and max(p.z for p in pts) > 2.0:
                bpy.data.objects.remove(o, do_unlink=True)


def _ribbon(name, pts, width, thick, mat):
    """A bent strip along `pts` (global points), `width` across global x, `thick` thick across the path."""
    bm = bmesh.new(); rings = []
    for i, p in enumerate(pts):
        a = pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]; a.normalize(); nrm = a.cross(Vector((1, 0, 0))).normalized()
        rings.append([bm.verts.new(p + Vector((sx * width / 2, 0, 0)) + nrm * (sz * thick / 2)) for sx, sz in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
    for i in range(len(rings) - 1):
        for k in range(4):
            bm.faces.new((rings[i][k], rings[i][(k + 1) % 4], rings[i + 1][(k + 1) % 4], rings[i + 1][k]))
    bm.faces.new(rings[0][::-1]); bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


def _hammered_ceiling():
    """Neutral silver sheet with shallow dimples; cell colour must not tint metal."""
    name = "ir_lux_hammered_pkg_l1c"
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    m["weathered"] = True
    nt = m.node_tree; N, L = nt.nodes, nt.links
    b = N["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.7, 0.7, 0.72, 1.0)
    b.inputs["Metallic"].default_value = 1.0
    b.inputs["Roughness"].default_value = 0.22
    tc = N.new("ShaderNodeTexCoord")
    vo = N.new("ShaderNodeTexVoronoi"); vo.feature = "F1"
    vo.inputs["Scale"].default_value = 9.0
    bu = N.new("ShaderNodeBump")
    bu.inputs["Strength"].default_value = 0.35
    bu.inputs["Distance"].default_value = 0.012
    L.new(tc.outputs["Object"], vo.inputs["Vector"])
    L.new(vo.outputs["Distance"], bu.inputs["Height"])
    L.new(bu.outputs["Normal"], b.inputs["Normal"])
    return m


def _main(stats):
    r = ROOMS["main"]; lo, _ = _bb(f"{r}.floor"); hi = _bb(f"{r}.floor")[1]; zc = _bb(f"{r}.ceiling")[0][2]
    fl = _fl(); pa = _pa()
    _rm_ceiling_clutter(lo, hi, zc)
    m = _hammered_ceiling()
    _set_ceiling(r, m)
    bronze = pa._flat("ir_lux_bronze", (0.42, 0.22, 0.09), 0.3, 1.0); bronze["weathered"] = True
    n = 0
    for lx, ly, h in ((3.2, 3.0, 5.7), (3.2, 6.0, 5.7), (3.2, 9.0, 5.7), (3.2, 12.0, 5.7), (3.2, 15.0, 5.7), (10.2, 3.0, 5.7), (10.2, 6.0, 5.7), (10.2, 9.0, 5.7), (10.2, 12.0, 5.7), (10.2, 15.0, 5.7)):
        fx, fy = lo[0] + ly, hi[1] - lx; R = 0.6; zb = max(zc - h, 0.9) + R; pts = []
        for i in range(12):
            pts.append(Vector((fx, fy - R, zc - 0.02 - i * (zc - 0.02 - zb) / 11)))
        for i in range(1, 16):
            a = math.pi * i / 16; pts.append(Vector((fx, fy - R * math.cos(a), zb - R * math.sin(a))))
        for i in range(12):
            pts.append(Vector((fx, fy + R, zb + i * (zc - 0.02 - zb) / 11)))
        _ribbon(f"LuxURibbon{n}", pts, 0.15, 0.01, bronze); n += 1
    blk = pa._flat("ir_lux_soffit", (0.02, 0.02, 0.022), 0.5); dl = _emit("ir_lux_dl", (1.0, 0.82, 0.6), 30.0)
    band, discs = [], []
    ex0, ex1, ey0, ey1 = lo[0] + 0.1, hi[0] - 0.1, lo[1] + 0.1, hi[1] - 0.1
    for (cx, cy, sx, sy) in (((ex0 + ex1) / 2, ey0 + 0.35, ex1 - ex0, 0.7), ((ex0 + ex1) / 2, ey1 - 0.35, ex1 - ex0, 0.7), (ex0 + 0.35, (ey0 + ey1) / 2, 0.7, ey1 - ey0), (ex1 - 0.35, (ey0 + ey1) / 2, 0.7, ey1 - ey0)):
        band.append(("box", cx, cy, zc - 0.25, sx, sy, 0.5))
    for i in range(14):
        discs.append(("cyl", (ex0 + 0.35 + i * (ex1 - ex0 - 0.7) / 13, ey0 + 0.35, zc - 0.51), (ex0 + 0.35 + i * (ex1 - ex0 - 0.7) / 13, ey0 + 0.35, zc - 0.52), 0.06, 14))
        discs.append(("cyl", (ex0 + 0.35 + i * (ex1 - ex0 - 0.7) / 13, ey1 - 0.35, zc - 0.51), (ex0 + 0.35 + i * (ex1 - ex0 - 0.7) / 13, ey1 - 0.35, zc - 0.52), 0.06, 14))
    fl.mesh_object("LuxSoffitBand", [(blk, band), (dl, discs)], bevel=False)
    wh = pa._flat("ir_lux_flute", (0.9, 0.9, 0.88), 0.4); flutes = []
    xw = lo[0] + 0.03; y0, y1 = lo[1] + 0.9, hi[1] - 0.9
    for i in range(int((y1 - y0) // 0.07)):
        flutes.append(("box", xw + 0.02, y0 + 0.07 * (i + 0.5), 1.6, 0.04, 0.05, 3.0))
    fl.mesh_object("LuxFlutedWall", [(wh, flutes + [("box", xw, (y0 + y1) / 2, 1.6, 0.02, y1 - y0, 3.0)])], bevel=False)
    stats["lux_main"] = {"ribbons": n}


def _led_burst_mat(cx, y, zm, W):
    """pkg_l1: framed green/white flowing screen, visible without diffuse GI spill."""
    name = "ir_lux_ledwall"
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
    m.use_nodes = True
    m["weathered"] = True
    m["pkg_l1"] = "flowing_screen"
    nodes, links = m.node_tree.nodes, m.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    coord = nodes.new("ShaderNodeTexCoord")
    separate = nodes.new("ShaderNodeSeparateXYZ")
    links.new(coord.outputs["Generated"], separate.inputs["Vector"])

    def math_node(operation, first, second=None):
        node = nodes.new("ShaderNodeMath")
        node.operation = operation
        for index, value in enumerate((first, second)):
            if value is None:
                continue
            if isinstance(value, (int, float)):
                node.inputs[index].default_value = value
            else:
                links.new(value, node.inputs[index])
        return node.outputs[0]

    u, v = separate.outputs["X"], separate.outputs["Z"]
    bend = math_node("MULTIPLY", math_node("SINE", math_node("MULTIPLY", v, 4.5)), .12)
    flow = math_node("ADD", math_node("ADD", u, math_node("MULTIPLY", v, .55)), bend)
    bands = []
    for center, width in ((.38, .13), (.90, .20), (1.36, .10)):
        distance = math_node("ABSOLUTE", math_node("SUBTRACT", flow, center))
        falloff = math_node("MAXIMUM", math_node("SUBTRACT", 1, math_node("DIVIDE", distance, width)), 0)
        bands.append(math_node("POWER", falloff, 1.7))
    whiteness = math_node("MAXIMUM", math_node("MAXIMUM", bands[0], bands[1]), bands[2])
    color = nodes.new("ShaderNodeMixRGB")
    color.inputs[1].default_value = (.025, .38, .095, 1)
    color.inputs[2].default_value = (.92, 1.0, .95, 1)
    links.new(whiteness, color.inputs[0])
    emission = nodes.new("ShaderNodeEmission")
    emission.inputs["Strength"].default_value = .85
    links.new(color.outputs[0], emission.inputs["Color"])
    dark = nodes.new("ShaderNodeBsdfDiffuse")
    dark.inputs["Color"].default_value = (.012, .015, .012, 1)
    path = nodes.new("ShaderNodeLightPath")
    visible = math_node("MAXIMUM", path.outputs["Is Camera Ray"], path.outputs["Is Glossy Ray"])
    mix = nodes.new("ShaderNodeMixShader")
    links.new(visible, mix.inputs[0])
    links.new(dark.outputs[0], mix.inputs[1])
    links.new(emission.outputs[0], mix.inputs[2])
    links.new(mix.outputs[0], output.inputs["Surface"])
    return m


def _entry_screen(lo, hi, zc, stats):
    """Rebuild only the display and its neutral fill; safe on existing kit scenes."""
    for name in ("LuxLedWall", "ir_lux_ledwall_light"):
        old = bpy.data.objects.get(name)
        if old is not None:
            data = old.data
            kind = old.type
            bpy.data.objects.remove(old, do_unlink=True)
            if data is not None and data.users == 0:
                if kind == "MESH":
                    bpy.data.meshes.remove(data)
                elif kind == "LIGHT":
                    bpy.data.lights.remove(data)
    width = min(6.0, hi[0] - lo[0] - 1.0)
    height = min(7.0, zc - .6)
    cx, y, zm = (lo[0] + hi[0]) / 2, hi[1] - .04, .2 + height / 2
    frame = _fl()._flat("ir_lux_ledframe", (.03, .03, .034), .4, .8)
    panel = [("box", cx, y, zm, width, .03, height)]
    bars = [("box", cx, y - .005, .16, width + .12, .06, .08),
            ("box", cx, y - .005, .24 + height, width + .12, .06, .08)]
    for side in (-1, 1):
        bars.append(("box", cx + side * (width / 2 + .04), y - .005,
                     zm, .08, .06, height + .16))
    obj = _fl().mesh_object("LuxLedWall", [(_led_burst_mat(cx, y, zm, width), panel),
                                         (frame, bars)], bevel=False)
    ld = bpy.data.lights.new("ir_lux_ledwall_light", "AREA")
    ld.shape, ld.size, ld.size_y = "RECTANGLE", width, height
    ld.energy, ld.color = 20, (1.0, 1.0, 1.0)
    light = bpy.data.objects.new(ld.name, ld)
    light.location = (cx, y - .1, zm)
    light.rotation_euler = (math.pi / 2, 0, math.pi)
    bpy.context.scene.collection.objects.link(light)
    stats["lux_entry_screen"] = {"graphic": "flowing_green_white", "fill_watts": 20,
                                  "emission_strength": .85, "diffuse_gi": False,
                                  "frame_sides": 4}


def _entry_floor():
    """pkg_l1b: metre-scaled 1.2 x 0.8 m entry stone; opt out independently."""
    if os.environ.get("ROOM_LUX_ENTRY_STONE", "1") == "0":
        return _tile("ir_lux_entry_tile", (0.2, 0.21, 0.23), 0.12)
    name = "ir_lux_entry_stone_pkg_l1b"
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    mat["weathered"] = True
    mat["pkg_l1b_entry_stone"] = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    output = nodes.new("ShaderNodeOutputMaterial")
    stone = nodes.new("ShaderNodeBsdfPrincipled")
    stone.inputs["Metallic"].default_value = 0.0
    stone.inputs["Roughness"].default_value = 0.18
    links.new(stone.outputs["BSDF"], output.inputs["Surface"])
    geometry = nodes.new("ShaderNodeNewGeometry")
    tile = nodes.new("ShaderNodeTexBrick")
    tile.label = "1.2 x 0.8 m stone; 2 mm grout"
    tile.offset = 0.0
    tile.inputs["Scale"].default_value = 1.0
    tile.inputs["Brick Width"].default_value = 1.2
    tile.inputs["Row Height"].default_value = 0.8
    tile.inputs["Mortar Size"].default_value = 0.002
    tile.inputs["Mortar Smooth"].default_value = 0.001
    tile.inputs["Color1"].default_value = (0.09, 0.095, 0.10, 1)
    tile.inputs["Color2"].default_value = (0.082, 0.087, 0.092, 1)
    tile.inputs["Mortar"].default_value = (0.065, 0.067, 0.07, 1)
    links.new(geometry.outputs["Position"], tile.inputs["Vector"])
    mineral = nodes.new("ShaderNodeTexNoise")
    mineral.inputs["Scale"].default_value = 5.0
    mineral.inputs["Detail"].default_value = 3.0
    mineral.inputs["Roughness"].default_value = 0.65
    links.new(geometry.outputs["Position"], mineral.inputs["Vector"])
    variation = nodes.new("ShaderNodeMixRGB")
    variation.blend_type = "MULTIPLY"
    variation.inputs[0].default_value = 0.12
    links.new(tile.outputs["Color"], variation.inputs[1])
    links.new(mineral.outputs["Fac"], variation.inputs[2])
    links.new(variation.outputs[0], stone.inputs["Base Color"])
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.2
    bump.inputs["Distance"].default_value = 0.00035
    links.new(mineral.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], stone.inputs["Normal"])
    return mat


def _entry(stats):
    r = ROOMS["entry"]; lo = _bb(f"{r}.floor")[0]; hi = _bb(f"{r}.floor")[1]; zc = _bb(f"{r}.ceiling")[0][2]; fl = _fl()
    _rm_ceiling_clutter(lo, hi, zc)
    _set_floor(r, _entry_floor())
    try:
        _entry_screen(lo, hi, zc, stats)
    except Exception as ex:
        stats["lux_entry_screen_error"] = repr(ex)[:160]
    g = _emit("ir_lux_plinth_glow", (1.0, 0.78, 0.5), 12.0); n = 0
    for obj in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("WhiteIslandFactory")]:
        t = obj.matrix_world.translation
        if lo[0] <= t.x <= hi[0] and lo[1] <= t.y <= hi[1]:
            pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]; mn = [min(p[i] for p in pts) for i in range(3)]; mx = [max(p[i] for p in pts) for i in range(3)]
            fl.mesh_object(f"LuxPlinthGlow{n}", [(g, [("box", (mn[0] + mx[0]) / 2, mn[1] - 0.005, mn[2] + 0.06, mx[0] - mn[0] - 0.1, 0.012, 0.03), ("box", (mn[0] + mx[0]) / 2, mx[1] + 0.005, mn[2] + 0.06, mx[0] - mn[0] - 0.1, 0.012, 0.03),
                                                       ("box", mn[0] - 0.005, (mn[1] + mx[1]) / 2, mn[2] + 0.06, 0.012, mx[1] - mn[1] - 0.1, 0.03), ("box", mx[0] + 0.005, (mn[1] + mx[1]) / 2, mn[2] + 0.06, 0.012, mx[1] - mn[1] - 0.1, 0.03)])], bevel=False); n += 1
    stats["lux_entry"] = {"plinth_glow": n}


def _gallery_kiosk(stats):
    """Replace the inherited cafe cabinet with a rounded touchscreen pedestal."""
    name = "LuxGalleryKiosk"
    if bpy.data.objects.get(name):
        return
    old = bpy.data.objects.get("CafeCounterFactory(8).spawn_asset(8)")
    if old is None:
        raise RuntimeError("Gallery kiosk source cabinet not found")
    lo, hi = _bb(old.name)
    x, y, z = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2]
    def material(label, rgb, rough, metal=0.0):
        m = bpy.data.materials.new(label); m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*rgb, 1)
        b.inputs["Roughness"].default_value = rough
        b.inputs["Metallic"].default_value = metal
        m["weathered"] = True
        return m
    white = material("ir_lux_kiosk_white", (0.86, 0.86, 0.84), 0.3)
    frame = material("ir_lux_kiosk_frame", (0.018, 0.02, 0.022), 0.27)
    screen = material("ir_lux_kiosk_screen", (0.025, 0.06, 0.055), 0.16)
    ink = material("ir_lux_kiosk_ui", (0.42, 0.65, 0.53), 0.45)
    fl = _fl()
    body = fl.mesh_object(name, [(white, [
        ("box", x, y, z + 0.025, 0.48, 0.42, 0.05),
        ("box", x, y + 0.055, z + 0.48, 0.25, 0.24, 0.91),
        ("box", x, y + 0.055, z + 0.935, 0.34, 0.27, 0.06)])], bevel=False)
    def finish(obj, width):
        bevel = obj.modifiers.new("Rounded fabricated edges", "BEVEL")
        bevel.width = width; bevel.segments = 3
        bevel.limit_method = "ANGLE"
        obj.modifiers.new("Weighted surface normals", "WEIGHTED_NORMAL")
    finish(body, 0.018)
    # Display front faces the gallery approach (-Y), tilted upward by 30 degrees.
    centre = Vector((x, y, z + 1.015))
    rot = math.radians(60)
    def panel(label, mat, offset, sx, sy, thick, bevel=0.006):
        obj = fl.mesh_object(label, [(mat, [("box", 0, 0, 0, sx, sy, thick)])], bevel=False)
        obj.rotation_euler.x = rot
        obj.location = centre + Vector((0, -math.sin(rot) * offset, math.cos(rot) * offset))
        finish(obj, bevel)
        return obj
    panel("LuxGalleryKioskHousing", white, 0, 0.49, 0.35, 0.045, 0.018)
    panel("LuxGalleryKioskBezel", frame, 0.025, 0.455, 0.315, 0.008)
    panel("LuxGalleryKioskGlass", screen, 0.030, 0.415, 0.275, 0.004)
    # A local geometric site-map interface: paths and building footprints, no invented text.
    ui = fl.mesh_object("LuxGalleryKioskMap", [(ink, [
        ("box", 0, 0, 0, 0.018, 0.22, 0.002),
        ("box", 0, 0.02, 0, 0.35, 0.012, 0.002),
        ("box", -0.11, -0.06, 0, 0.07, 0.055, 0.002),
        ("box", 0.10, 0.075, 0, 0.08, 0.06, 0.002),
        ("box", 0.11, -0.065, 0, 0.06, 0.045, 0.002)])], bevel=False)
    ui.rotation_euler.x = rot
    ui.location = centre + Vector((0, -math.sin(rot) * 0.033, math.cos(rot) * 0.033))
    old.hide_render = True; old.hide_viewport = True
    stats["lux_gallery_kiosk"] = {"replaced": old.name, "display_tilt_from_vertical_deg": 30}


def _gallery(stats):
    import scanned_wood as sw
    r = ROOMS["gallery"]; lo = _bb(f"{r}.floor")[0]; hi = _bb(f"{r}.floor")[1]; zc = _bb(f"{r}.ceiling")[0][2]; fl = _fl(); pa = _pa()
    _rm_ceiling_clutter(lo, hi, zc)
    car = pa._flat("ir_lux_carpet", (0.68, 0.56, 0.42), 0.95); car["weathered"] = True
    nt = car.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); no = N.new("ShaderNodeTexNoise"); no.inputs["Scale"].default_value = 260.0; mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs["Factor"].default_value = 0.12
    mx.inputs["A"].default_value = (0.68, 0.56, 0.42, 1); L.new(tc.outputs["Object"], no.inputs["Vector"]); L.new(no.outputs["Color"], mx.inputs["B"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
    _set_floor(r, car)
    oak = sw.material("oak_plank", size_m=1.0, tint=(1.0, 0.95, 0.85), rough=(0.4, 0.6), space="object", grain="z"); pw = 0.6; prims = []
    z0, z1 = 0.12, zc - 0.7; h = z1 - z0; n = int((hi[0] - lo[0] - 0.2) // pw)
    for i in range(n):
        prims.append(("box", lo[0] + 0.1 + pw * (i + 0.5), hi[1] - 0.012, z0 + h / 2, pw - 0.006, 0.02, h))
    fl.mesh_object("LuxGalleryPanels", [(oak, prims)], bevel=False)
    glow = _emit("ir_lux_cove", (1.0, 0.8, 0.55), 10.0)
    strips = [("box", (lo[0] + hi[0]) / 2, hi[1] - 0.35, zc - 0.6, hi[0] - lo[0] - 0.4, 0.04, 0.02), ("box", (lo[0] + hi[0]) / 2, lo[1] + 0.35, zc - 0.6, hi[0] - lo[0] - 0.4, 0.04, 0.02),
              ("box", lo[0] + 0.35, (lo[1] + hi[1]) / 2, zc - 0.6, 0.04, hi[1] - lo[1] - 0.4, 0.02), ("box", hi[0] - 0.35, (lo[1] + hi[1]) / 2, zc - 0.6, 0.04, hi[1] - lo[1] - 0.4, 0.02)]
    fl.mesh_object("LuxCoveStrips", [(glow, strips)], bevel=False)
    _gallery_kiosk(stats)
    stats["lux_gallery"] = {"panels": n}


def _vip_art(stats):
    """Six framed matte prints sharing one curved neutral abstract composition."""
    if bpy.data.objects.get("LuxVipArtFrames"):
        return
    old = bpy.data.objects.get("MenuBoardFactory(57).spawn_asset(57)")
    if old is None:
        raise RuntimeError("VIP artwork source menu board not found")
    lo, hi = _bb(f"{ROOMS['vip']}.floor")
    wall = hi[0]
    old_lo, old_hi = _bb(old.name)
    cy, cz = (old_lo[1] + old_hi[1]) / 2, 2.10
    def material(name, rgb, rough):
        m = bpy.data.materials.new(name); m.use_nodes = True; m["weathered"] = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*rgb, 1)
        b.inputs["Roughness"].default_value = rough
        return m
    paper = material("ir_lux_vip_art_paper", (0.80, 0.77, 0.68), 0.78)
    sand = material("ir_lux_vip_art_sand", (0.46, 0.31, 0.19), 0.78)
    ivory = material("ir_lux_vip_art_ivory", (0.92, 0.90, 0.83), 0.78)
    ink = material("ir_lux_vip_art_ink", (0.025, 0.021, 0.018), 0.78)
    frame = material("ir_lux_vip_art_frame", (0.025, 0.022, 0.02), 0.32)
    def ellipse(x, y, rx, ry):
        return [(x + rx*math.cos(i*2*math.pi/160), y + ry*math.sin(i*2*math.pi/160)) for i in range(160)]
    def clip(poly, xmin, xmax, ymin, ymax):
        for axis, edge, sign in ((0,xmin,1),(0,xmax,-1),(1,ymin,1),(1,ymax,-1)):
            result = []
            if not poly:
                break
            prev = poly[-1]; pin = sign*(prev[axis]-edge) >= 0
            for cur in poly:
                cin = sign*(cur[axis]-edge) >= 0
                if cin != pin:
                    t = (edge-prev[axis])/(cur[axis]-prev[axis])
                    result.append((prev[0]+t*(cur[0]-prev[0]),prev[1]+t*(cur[1]-prev[1])))
                if cin:
                    result.append(cur)
                prev, pin = cur, cin
            poly = result
        return poly
    shapes = [(sand, [(-1.2,-.45),(1.2,-.45),(1.2,.45),(.45,.45)]),
              (ink, ellipse(.15,.33,1.10,.70)),
              (ivory, ellipse(.05,.43,1.10,.70))]
    bars = []
    for row in range(2):
        for col in range(3):
            ymin = -1.2 + col*.81; ymax = ymin+.78
            zmin = -.45 + row*.465; zmax = zmin+.435
            ym, zm = cy+(ymin+ymax)/2, cz+(zmin+zmax)/2
            for yy in (cy+ymin,cy+ymax):
                bars.append(("box",wall-.04,yy,zm,.05,.014,.449))
            for zz in (cz+zmin,cz+zmax):
                bars.append(("box",wall-.04,ym,zz,.05,.794,.014))
            polygons = [(paper,[(ymin,zmin),(ymax,zmin),(ymax,zmax),(ymin,zmax)])]
            polygons += [(mat,clip(poly,ymin,ymax,zmin,zmax)) for mat,poly in shapes]
            verts, faces, slots = [], [], []
            for layer,(mat,poly) in enumerate(polygons):
                if len(poly) < 3:
                    continue
                start = len(verts)
                verts.extend((wall-.062-layer*.0001,cy+y,cz+z) for y,z in poly)
                faces.append(tuple(range(start,start+len(poly)))); slots.append(mat)
            mesh = bpy.data.meshes.new(f"LuxVipArtPanel{row}_{col}")
            mesh.from_pydata(verts,[],faces)
            for i,mat in enumerate(slots):
                mesh.materials.append(mat); mesh.polygons[i].material_index=i
            obj = bpy.data.objects.new(mesh.name,mesh); bpy.context.scene.collection.objects.link(obj)
    obj = _fl().mesh_object("LuxVipArtFrames",[(frame,bars)],bevel=False)
    bevel = obj.modifiers.new("Frame edge finish","BEVEL"); bevel.width=.0015; bevel.segments=3
    obj.modifiers.new("Frame normals","WEIGHTED_NORMAL")
    old.hide_render = True; old.hide_viewport = True
    stats["lux_vip_art"] = {"panels":6,"wall_inner_x":wall,"replaced":old.name}


def _vip(stats):
    import scanned_wood as sw
    r = ROOMS["vip"]; lo = _bb(f"{r}.floor")[0]; hi = _bb(f"{r}.floor")[1]; zc = _bb(f"{r}.ceiling")[0][2]; fl = _fl(); pa = _pa()
    _rm_ceiling_clutter(lo, hi, zc)
    _set_floor(r, _tile("ir_lux_vip_tile", (0.075, 0.048, 0.037), 0.1, mrgb=(0.03, 0.02, 0.015)))
    wood = sw.material("walnut", size_m=1.0, tint=(0.55, 0.42, 0.36), rough=(0.3, 0.5), space="object", grain="z"); pw, t = 0.9, 0.02; zt = 3.5; prims = []
    for (a0, a1, fixed, alx, sgn) in ((lo[0] + 0.1, hi[0] - 0.1, hi[1] - 0.01, True, -1), (lo[1] + 0.1, hi[1] - 0.1, lo[0] + 0.01, False, 1), (lo[1] + 0.1, hi[1] - 0.1, hi[0] - 0.01, False, -1)):
        k = int((a1 - a0) // pw)
        for i in range(k):
            c = a0 + pw * (i + 0.5)
            prims.append(("box", c, fixed + sgn * t / 2, zt / 2 + 0.1, pw - 0.01, t, zt) if alx else ("box", fixed + sgn * t / 2, c, zt / 2 + 0.1, t, pw - 0.01, zt))
    fl.mesh_object("LuxVipPanels", [(wood, prims)], bevel=False)
    dark = pa._flat("ir_lux_vip_ceiling", (0.05, 0.035, 0.03), 0.6); slot = _emit("ir_lux_vip_slot", (1.0, 0.82, 0.58), 16.0)
    plate = [("box", (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, zt + 0.1 + 0.02, hi[0] - lo[0] - 0.1, hi[1] - lo[1] - 0.1, 0.04)]
    slots = [("box", (lo[0] + hi[0]) / 2, lo[1] + (hi[1] - lo[1]) * (j + 0.5) / 6, zt + 0.1 - 0.001, (hi[0] - lo[0]) - 1.6, 0.06, 0.012) for j in range(6)]
    fl.mesh_object("LuxVipCeiling", [(dark, plate), (slot, slots)], bevel=False)
    for j in range(6):
        ld = bpy.data.lights.new(f"ir_lux_vip_slot_{j}", "AREA"); ld.shape = "RECTANGLE"; ld.size = (hi[0] - lo[0]) - 1.6; ld.size_y = 0.08; ld.energy = 140; ld.color = (1.0, 0.85, 0.65)
        o = bpy.data.objects.new(ld.name, ld); o.location = ((lo[0] + hi[0]) / 2, lo[1] + (hi[1] - lo[1]) * (j + 0.5) / 6, zt + 0.05); o.rotation_euler = (math.pi, 0, 0); bpy.context.scene.collection.objects.link(o)
    shelf = pa._flat("ir_lux_vip_shelf", (0.1, 0.07, 0.055), 0.5, wood=True); glow = _emit("ir_lux_vip_shelfglow", (1.0, 0.75, 0.45), 8.0)
    rg = random.Random(3); boards, strips = [], []
    from room_planner import proc_bookstore as pb
    bm = bmesh.new(); uvl = bm.loops.layers.uv.verify(); nmag = 0
    for cx in (lo[0] + (hi[0] - lo[0]) * 0.3, lo[0] + (hi[0] - lo[0]) * 0.7):
        for z in (0.9, 1.4, 1.9, 2.4):
            boards.append(("box", cx, hi[1] - 0.2, z, 3.4, 0.38, 0.03)); strips.append(("box", cx, hi[1] - 0.07, z - 0.04, 3.2, 0.02, 0.012))
            y = cx - 1.6
            while y < cx + 1.55:
                if rg.random() < 0.1:                                                   # a gap
                    y += rg.uniform(0.12, 0.3); continue
                w = rg.uniform(0.19, 0.24); hgt = rg.uniform(0.25, 0.31)
                if rg.random() < 0.18:                                                  # a short flat stack at a gap
                    for k in range(rg.randint(2, 4)):
                        pb.add_book(bm, uvl, (y + w / 2, hi[1] - 0.2, z + 0.015 + 0.012 * k + 0.006), (w, 0.27, 0.012), "flat", rg.randrange(pb.meta()["n_covers"]), yaw=rg.uniform(-0.2, 0.2))
                else:
                    ve = pb.add_book(bm, uvl, (y + w / 2, hi[1] - 0.2 - 0.12, z + 0.015 + hgt / 2), (0.012, w, hgt), "face_out", rg.randrange(pb.meta()["n_covers"]))
                    lean = rg.uniform(0.05, 0.28)                                       # leaning back against the panel
                    bmesh.ops.rotate(bm, cent=(y + w / 2, hi[1] - 0.2 - 0.12, z + 0.015), matrix=__import__("mathutils").Matrix.Rotation(lean, 3, "Y"), verts=ve)
                    nmag += 1
                y += w + rg.uniform(0.005, 0.03)
    fl.mesh_object("LuxVipShelving", [(shelf, boards), (glow, strips)], bevel=False)
    me = bpy.data.meshes.new("LuxVipMagazines"); bm.to_mesh(me); bm.free(); me.materials.append(pb.atlas_material(0))
    mo = bpy.data.objects.new("LuxVipMagazines", me); bpy.context.scene.collection.objects.link(mo); stats["lux_vip_mags"] = nmag
    stats["lux_vip"] = 1


def _lights(stats):
    W = float(os.environ.get("ROOM_LUX_DL_W") or 140); n = 0
    for key, r in ROOMS.items():
        lo = _bb(f"{r}.floor")[0]; hi = _bb(f"{r}.floor")[1]; zc = _bb(f"{r}.ceiling")[0][2]; zl = (3.5 if key == "vip" else zc) - 0.1
        nx, ny = max(1, int((hi[0] - lo[0]) // 3.2)), max(1, int((hi[1] - lo[1]) // 3.2))
        for i in range(nx):
            for j in range(ny):
                ld = bpy.data.lights.new(f"ir_lux_dl_{key}_{i}_{j}", "SPOT"); ld.energy = W; ld.spot_size = math.radians(80); ld.spot_blend = 0.6; ld.color = (1.0, 0.8, 0.58); ld.shadow_soft_size = 0.05
                o = bpy.data.objects.new(ld.name, ld); o.location = (lo[0] + (hi[0] - lo[0]) * (i + 0.5) / nx, lo[1] + (hi[1] - lo[1]) * (j + 0.5) / ny, zl); bpy.context.scene.collection.objects.link(o); n += 1
    stats["lux_lights"] = n


def _clean(stats):
    """r2: no Infinigen square columns / pilasters / exposed ceiling beams anywhere on the floor."""
    k = 0
    for o in list(bpy.data.objects):
        if o.name.startswith(("ColumnFactory", "RoundPillarFactory", "PilasterFactory", "CeilingBeamFactory")):
            bpy.data.objects.remove(o, do_unlink=True); k += 1
    stats["lux_clean_removed"] = k


def _main_floor(stats):
    r = ROOMS["main"]
    m = _tile("ir_lux_main_tile", (0.66, 0.63, 0.58), 0.22, size=0.75, grout=0.006, mrgb=(0.5, 0.48, 0.45))
    if not m.get("lux_vein"):
        nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
        src = b.inputs["Base Color"].links[0].from_socket; tc = N.new("ShaderNodeTexCoord"); no = N.new("ShaderNodeTexNoise"); no.inputs["Scale"].default_value = 2.2; no.inputs["Detail"].default_value = 8.0; no.inputs["Distortion"].default_value = 1.5
        mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs["Factor"].default_value = 0.10
        L.new(tc.outputs["Object"], no.inputs["Vector"]); L.new(src, mx.inputs["A"]); L.new(no.outputs["Color"], mx.inputs["B"]); L.new(mx.outputs["Result"], b.inputs["Base Color"]); m["lux_vein"] = 1
    _set_floor(r, m); stats["lux_main_floor"] = 1


def _recolour(o, rgb, name):
    """The largest-area slot of an imported piece (its upholstery) takes a flat leather / fabric of `rgb`."""
    if o.type != "MESH" or not o.data.materials:
        return
    area = {}
    for p in o.data.polygons:
        area[p.material_index] = area.get(p.material_index, 0.0) + p.area
    i = max(area, key=area.get)
    if i >= len(o.data.materials):
        return
    m = _pa()._flat(name, rgb, 0.45); m["weathered"] = True
    o.data = o.data.copy(); o.data.materials[i] = m


def _lounge_bouquets(stats):
    """Local HSSD hydrangeas/roses on main-room tables, replacing rod props."""
    if all(bpy.data.objects.get(f"LuxLoungeBouquet{i}") for i in range(10)):
        return
    import real_assets as ra
    tables = [bpy.data.objects.get(f"LuxPedestal{i}") for i in range(10)]
    if any(obj is None for obj in tables):
        raise RuntimeError("Expected ten main lounge pedestal tables")
    centres = []
    for table in tables:
        lo, hi = _bb(table.name)
        centres.append(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, hi[2]))
    old = []
    for obj in bpy.data.objects:
        if obj.type != "MESH" or not obj.name.startswith(("LuxTableVase", "LuxWaterGlass", "LuxBrochures", "LuxSaucer", "CupFactory")):
            continue
        lo, hi = _bb(obj.name)
        x, y = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        if any(math.hypot(x-cx, y-cy) < 0.30 and z-0.01 <= lo[2] <= z+0.12 for cx, cy, z in centres):
            old.append(obj)
    spawned = []
    for i, (x, y, z) in enumerate(centres):
        if bpy.data.objects.get(f"LuxLoungeBouquet{i}"):
            continue
        # Pinned real floral arrangements; no generated stand-ins if an import fails.
        asset = "0ecf535491d4cb3d7d5904f0594eb925c4157cbf" if i % 3 != 1 else "fcd3cdb03e553cd619428f7b0029ea46bd6bd977"
        width = 0.27 if i < 5 else 0.36
        obj = ra.hssd(asset, 0, x, y, z, i * 0.71, fit=(width, width, 0.38), size=(0.0, 2.0))
        if obj is None:
            for created in spawned:
                bpy.data.objects.remove(created, do_unlink=True)
            raise RuntimeError(f"Local floral asset unavailable: {asset}")
        obj.name = f"LuxLoungeBouquet{i}"
        obj["lux_floral_asset"] = asset
        spawned.append(obj)
    for obj in old:
        obj.hide_render = True; obj.hide_viewport = True
    stats["lux_lounge_bouquets"] = {"arrangements": 10, "replaced_props": len(old), "asset_ids": ["0ecf535491d4cb3d7d5904f0594eb925c4157cbf", "fcd3cdb03e553cd619428f7b0029ea46bd6bd977"]}


def _curved_sectional(stats):
    """Four upholstered arc modules, opening toward the existing lounge table."""
    if bpy.data.objects.get("LuxSectionalBase"):
        return
    old = bpy.data.objects.get("AboSofaFactory(B07J2JGT7Y).spawn_asset(10)")
    if old is None:
        raise RuntimeError("Main lounge sectional source sofa not found")
    lo, hi = _bb(old.name)
    cx = (lo[0] + hi[0]) / 2
    cy = (lo[1] + hi[1]) / 2 + 1.52
    z = lo[2]
    fabric = bpy.data.materials.new("ir_lux_sectional_ivory"); fabric.use_nodes = True
    fabric["weathered"] = True
    nt = fabric.node_tree; b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.86, 0.84, 0.79, 1)
    b.inputs["Roughness"].default_value = 0.72
    tc = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise"); noise.inputs["Scale"].default_value = 360
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.12
    bump.inputs["Distance"].default_value = 0.0005
    nt.links.new(tc.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], b.inputs["Normal"])
    dark = bpy.data.materials.new("ir_lux_sectional_recess"); dark.use_nodes = True
    dark.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.025, 0.022, 0.018, 1)
    dark.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.48
    dark["weathered"] = True
    def arc(name, inner, outer, bottom, top, a0, a1, mat, bevel):
        count = max(8, int((a1 - a0) / 1.5))
        verts = []
        for i in range(count + 1):
            angle = math.radians(a0 + (a1 - a0) * i / count)
            for radius, height in ((inner, bottom), (outer, bottom), (outer, top), (inner, top)):
                verts.append((cx + radius * math.sin(angle), cy - radius * math.cos(angle), z + height))
        faces = []
        for i in range(count):
            for j in range(4):
                faces.append((4*i+j, 4*(i+1)+j, 4*(i+1)+(j+1)%4, 4*i+(j+1)%4))
        faces += [(3, 2, 1, 0), tuple(4*count+j for j in range(4))]
        mesh = bpy.data.meshes.new(name); mesh.from_pydata(verts, [], faces); mesh.materials.append(mat)
        obj = bpy.data.objects.new(name, mesh); bpy.context.scene.collection.objects.link(obj)
        bm = bmesh.new(); bm.from_mesh(mesh); bmesh.ops.recalc_face_normals(bm, faces=bm.faces); bm.to_mesh(mesh); bm.free()
        for face in mesh.polygons:
            face.use_smooth = True
        mod = obj.modifiers.new("Soft upholstered edges", "BEVEL"); mod.width = bevel; mod.segments = 5; mod.limit_method = "ANGLE"
        obj.modifiers.new("Upholstery normals", "WEIGHTED_NORMAL")
        return obj
    arc("LuxSectionalBase", 1.40, 2.20, 0.08, 0.31, -62, 62, fabric, 0.04)
    for i in range(4):
        a0, a1 = -62 + 31*i + 0.25, -62 + 31*(i+1) - 0.25
        arc(f"LuxSectionalSeat{i}", 1.35, 2.08, 0.30, 0.45, a0, a1, fabric, 0.045)
        arc(f"LuxSectionalBack{i}", 2.04, 2.30, 0.33, 0.85, a0, a1, fabric, 0.045)
    for side in (-1, 1):
        a0, a1 = (-62, -58) if side < 0 else (58, 62)
        arc(f"LuxSectionalArm{side}", 1.36, 2.27, 0.35, 0.67, a0, a1, fabric, 0.035)
    feet = []
    for angle in (-52, -18, 18, 52):
        for radius in (1.57, 2.04):
            a = math.radians(angle); x, y = cx + radius*math.sin(a), cy - radius*math.cos(a)
            feet.append(("cyl", (x, y, z), (x, y, z + 0.11), 0.035, 16))
    _fl().mesh_object("LuxSectionalFeet", [(dark, feet)], bevel=False)
    old.hide_render = True; old.hide_viewport = True
    stats["lux_curved_sectional"] = {"replaced": old.name, "modules": 4, "opening": "+Y", "centre_xy": [cx, cy]}


def _furniture(stats):
    cream, yellow, brown = (0.9, 0.86, 0.76), (0.85, 0.58, 0.08), (0.36, 0.22, 0.14)
    n = {"main": 0, "vip": 0}
    r = ROOMS["main"]; lo = _bb(f"{r}.floor")[0]; hi = _bb(f"{r}.floor")[1]; arm = 0
    for o in sorted([o for o in bpy.data.objects if o.type == "MESH" and o.parent is None], key=lambda o: o.name):
        t = o.matrix_world.translation; f = o.name.split("(")[0]
        if f not in ("AboArmchairFactory", "AboSofaFactory", "AboCafechairFactory", "VelvetSofaFactory"):
            continue
        if lo[0] <= t.x <= hi[0] and lo[1] <= t.y <= hi[1]:
            if f == "AboArmchairFactory":
                arm += 1
                _recolour(o, yellow if arm <= 2 else cream, "ir_lux_yellow" if arm <= 2 else "ir_lux_cream")
            else:
                _recolour(o, cream, "ir_lux_cream")
            n["main"] += 1
    fl = _fl(); pa = _pa(); r = ROOMS["main"]; lo = _bb(f"{r}.floor")[0]; hi = _bb(f"{r}.floor")[1]; z0 = _bb(f"{r}.floor")[1][2]
    dk = pa._flat("ir_lux_pedestal", (0.06, 0.05, 0.05), 0.3, 0.6); k = 0
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and o.name.startswith("CafeTableFactory")]:
        t = o.matrix_world.translation
        if lo[0] <= t.x <= hi[0] and lo[1] <= t.y <= hi[1]:
            pts = [o.matrix_world @ Vector(c) for c in o.bound_box]; cx = sum(p.x for p in pts) / 8; cy = sum(p.y for p in pts) / 8
            o.hide_render = True; o.hide_viewport = True
            fl.mesh_object(f"LuxPedestal{k}", [(dk, [("cyl", (cx, cy, z0 + 0.02), (cx, cy, z0 + 0.03), 0.22, 24), ("cyl", (cx, cy, z0 + 0.03), (cx, cy, z0 + 0.52), 0.035, 12), ("cyl", (cx, cy, z0 + 0.52), (cx, cy, z0 + 0.56), 0.32, 28)])], bevel=False)
            if k % 5 != 4:
                _table_props(cx, cy, z0 + 0.56, random.Random(k * 13 + 1), pa, fl, _lib("CupFactory"))
            k += 1
    n["pedestals"] = k
    rv = ROOMS["vip"]; lov = _bb(f"{rv}.floor")[0]; hiv = _bb(f"{rv}.floor")[1]; kv = 0
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and o.name.startswith(("CafeTableFactory", "BreakTableFactory"))]:
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]; cx = sum(p.x for p in pts) / 8; cy = sum(p.y for p in pts) / 8
        if lov[0] <= cx <= hiv[0] and lov[1] <= cy <= hiv[1] and max(p.z for p in pts) < 1.0:
            if kv % 5 != 4:
                _table_props(cx, cy, max(p.z for p in pts), random.Random(kv * 7 + 3), pa, fl, _lib("CupFactory"), tray=(kv == 0))
            kv += 1
    r = ROOMS["vip"]; lo = _bb(f"{r}.floor")[0]; hi = _bb(f"{r}.floor")[1]
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and o.name.startswith(("AboArmchairFactory", "AboSofaFactory", "VelvetSofaFactory"))]:
        t = o.matrix_world.translation
        if lo[0] <= t.x <= hi[0] and lo[1] <= t.y <= hi[1]:
            _recolour(o, brown, "ir_lux_brown"); n["vip"] += 1
    _curved_sectional(stats)
    _lounge_bouquets(stats)
    stats["lux_furniture"] = n


def _model_material(label, rgb, rough, metal=0.0, emission=0.0, transmission=0.0, grain=0.0):
    """Model-only materials: physical scale microtexture, no shared-room material edits."""
    name = 'ir_lux_model_pkg_l1_model_' + label
    old = bpy.data.materials.get(name)
    if old:
        return old
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (*rgb, 1)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    b.inputs['Transmission Weight'].default_value = transmission
    b.inputs['IOR'].default_value = 1.49
    b.inputs['Emission Color'].default_value = (*rgb, 1)
    b.inputs['Emission Strength'].default_value = emission
    if grain:
        tc = nt.nodes.new('ShaderNodeTexCoord'); noise = nt.nodes.new('ShaderNodeTexNoise')
        noise.inputs['Scale'].default_value = 650; noise.inputs['Detail'].default_value = 2
        nt.links.new(tc.outputs['Object'], noise.inputs['Vector'])
        bump = nt.nodes.new('ShaderNodeBump'); bump.inputs['Strength'].default_value = .16
        bump.inputs['Distance'].default_value = grain
        nt.links.new(noise.outputs['Fac'], bump.inputs['Height']); nt.links.new(bump.outputs['Normal'], b.inputs['Normal'])
        ramp = nt.nodes.new('ShaderNodeMapRange')
        ramp.inputs['To Min'].default_value = max(.015, rough - .035)
        ramp.inputs['To Max'].default_value = min(1, rough + .035)
        nt.links.new(noise.outputs['Fac'], ramp.inputs['Value']); nt.links.new(ramp.outputs['Result'], b.inputs['Roughness'])
    return m


def _architectural_model(name, cx, cy, z0, lx, ly):
    """Three handcrafted, setback towers on a landscaped architectural display.

    Local U follows the long side; every feature stays inside the original island.
    Window panes, floor slabs and mullions are actual geometry, not a printed grid.
    """
    if bpy.data.objects.get(name + 'Site'):
        return
    fl = _fl(); long_x = lx >= ly; length, width = max(lx, ly), min(lx, ly)
    top = z0 + .9; ground = top + .052
    rg = random.Random(47313801 + round(cx * 100) + round(cy * 100))
    mats = {
        'plinth': _model_material('porcelain', (.84, .835, .80), .24, grain=.00012),
        'metal': _model_material('champagne_aluminium', (.40, .35, .26), .28, .82, grain=.000025),
        'stone': _model_material('limestone', (.65, .61, .51), .57, grain=.00009),
        'frame': _model_material('ivory_facade', (.80, .81, .77), .32, .12, grain=.000025),
        'core': _model_material('recessed_core', (.075, .09, .10), .48),
        'grass': _model_material('grass', (.14, .25, .075), .94, grain=.0007),
        'grass2': _model_material('planted_beds', (.24, .34, .10), .93, grain=.0006),
        'road': _model_material('asphalt', (.09, .105, .11), .88, grain=.0002),
        'path': _model_material('paving', (.63, .60, .51), .73, grain=.0001),
        'water': _model_material('reflecting_pool', (.035, .22, .25), .10, .3, transmission=.18, grain=.000035),
        'bark': _model_material('tree_trunks', (.18, .105, .045), .9),
        'leaf0': _model_material('leaves_dark', (.065, .17, .035), .95, grain=.0004),
        'leaf1': _model_material('leaves_light', (.24, .35, .065), .94, grain=.0004),
        'leaf2': _model_material('leaves_mid', (.12, .27, .07), .93, grain=.0004),
        'mark': _model_material('road_markings', (.82, .79, .65), .8),
        'glow': _model_material('diffused_light', (.95, .80, .53), .38, emission=1.8),
        'acrylic': _model_material('clear_acrylic', (.97, .985, 1), .025, transmission=1),
    }
    for i, (col, e) in enumerate([((.11,.19,.23),.04),((.18,.27,.29),.06),((.29,.35,.34),.04),((.62,.48,.25),.28)]):
        mats['win'+str(i)] = _model_material('glazing'+str(i), col, .16 + .025*i, .28, e, .08)
    groups = {}
    def pos(u, v, z):
        return (cx + u, cy + v, z) if long_x else (cx + v, cy + u, z)
    def box(mat, u, v, z, a, b, h):
        x, y, z = pos(u, v, z)
        groups.setdefault(mat, []).append(('box', x, y, z, a if long_x else b, b if long_x else a, h))
    def rod(mat, p, q, radius):
        groups.setdefault(mat, []).append(('cyl', pos(*p), pos(*q), radius, 8))
    def sphere(mat, u, v, z, radius):
        groups.setdefault(mat, []).append(('sph', pos(u, v, z), radius, 2))
    def finish(suffix, bevel):
        obj = fl.mesh_object(name + suffix, [(mats[m], p) for m,p in groups.items()], bevel=False)
        if bevel:
            mod = obj.modifiers.new('Scale-appropriate edge highlights', 'BEVEL'); mod.width = bevel; mod.segments = 3
            mod.limit_method = 'ANGLE'
            normal = obj.modifiers.new('Weighted corner normals', 'WEIGHTED_NORMAL'); normal.keep_sharp = True
        obj['ir_lux_model'] = 'pkg_l1_model'; groups.clear()
        return obj
    # Original footprint and elevation retained; recessed toe kick and fine metal trim.
    box('plinth', 0, 0, z0+.48, length, width, .84)
    box('core', 0, 0, z0+.055, length-.10, width-.10, .11)
    box('metal', 0, 0, top+.008, length-.012, width-.012, .016)
    box('glow', 0, 0, z0+.052, length-.06, width-.06, .012)
    finish('Plinth', .012)
    box('grass', 0, 0, top+.032, length-.12, width-.12, .04)
    for sign in [-1,1]:
        box('road', 0, sign*(width/2-.17), ground+.002, length-.28, .13, .005)
        box('path', 0, sign*(width/2-.295), ground+.006, length-.29, .08, .008)
        for j in range(int(length/.11)-2):
            box('mark', -length/2+.19+j*.11, sign*(width/2-.17), ground+.005, .045, .006, .001)
        # Thin acrylic perimeter, open above the towers as in the reference.
        box('acrylic', 0, sign*(width/2-.035), top+.19, length-.07, .006, .32)
        box('metal', 0, sign*(width/2-.035), top+.352, length-.06, .009, .008)
    for sign in [-1,1]:
        box('acrylic', sign*(length/2-.035), 0, top+.19, .006, width-.07, .32)
        box('metal', sign*(length/2-.035), 0, top+.352, .009, width-.06, .008)
        for side in [-1,1]:
            box('metal', sign*(length/2-.035), side*(width/2-.035), top+.19, .009, .009, .33)
    # A dark pool liner, pale coping and inset, physically reflective water.
    pu, pv, pw, pd = -length*.405, 0, length*.10, min(.57,width*.26)
    box('stone', pu, pv, ground+.010, pw+.035, pd+.035, .022)
    box('core', pu, pv, ground+.022, pw, pd, .006)
    box('water', pu, pv, ground+.026, pw-.012, pd-.012, .003)
    # Transverse pedestrian links and scored paving around each podium.
    for u in [-length*.13, length*.13]:
        box('path', u, 0, ground+.008, .065, width-.50, .01)
    finish('Site', .001)
    tower_specs = [(-length*.26, .96, .54), (0, 1.53, .62), (length*.26, 1.20, .57)]
    for ti, (u, height, tw) in enumerate(tower_specs):
        depth = min(.54, width*.32); v = .035 if ti==1 else -.025
        bz = ground+.105
        box('stone',u,v,ground+.032,tw+.20,depth+.16,.06)
        # Glazed two-storey podium, a fine arcade and roof terrace.
        box('win1',u,v,ground+.072,tw+.16,depth+.12,.066)
        for k in range(9):
            box('frame',u-(tw+.16)/2+k*(tw+.16)/8,v-depth/2-.061,ground+.072,.008,.01,.07)
        box('frame',u,v,ground+.107,tw+.23,depth+.19,.012)
        # Three narrowing tiers give each tower a distinct, legible silhouette.
        for tier, (start, stop, scale) in enumerate([(0,.62,1),(.62,.85,.86),(.85,1,.71)]):
            w, d = tw*scale, depth*scale
            zbase = bz+height*start; floors = max(3,round(height*(stop-start)/.049))
            pitch = height*(stop-start)/floors
            box('core',u,v,zbase+(height*(stop-start))/2,w-.012,d-.012,height*(stop-start))
            for fi in range(floors):
                zz = zbase+pitch*(fi+.5)
                # Slab bands are separate from recessed window panes.
                box('frame',u,v,zbase+pitch*fi,w+.012,d+.012,.0065)
                for axis, span, fixed in [(0,w,d),(1,d,w)]:
                    bays=max(5,round(span/.068)); bay=span/bays
                    for side in [-1,1]:
                        for j in range(bays):
                            a=-span/2+(j+.5)*bay; col='win'+str(3 if rg.random()<.13 else rg.randrange(3))
                            if axis==0:
                                box(col,u+a,v+side*(fixed/2-.001),zz,bay-.009,.007,pitch-.009)
                                box('frame',u-span/2+j*bay,v+side*(fixed/2+.004),zz,.007,.012,pitch)
                            else:
                                box(col,u+side*(fixed/2-.001),v+a,zz,.007,bay-.009,pitch-.009)
                                box('frame',u+side*(fixed/2+.004),v-span/2+j*bay,zz,.012,.007,pitch)
                for su in [-1,1]:
                    for sv in [-1,1]:
                        box('frame',u+su*w/2,v+sv*d/2,zz,.012,.012,pitch)
            roof=zbase+height*(stop-start)
            box('stone',u,v,roof+.003,w+.024,d+.024,.012)
            # Raised parapet coping; top roof has vents and mechanical screens.
            for side in [-1,1]:
                box('frame',u+side*w/2,v,roof+.017,.009,d+.025,.022)
                box('frame',u,v+side*d/2,roof+.017,w+.025,.009,.022)
        roof=bz+height
        box('metal',u,v,roof+.047,tw*.34,depth*.33,.064)
        for j in range(5):
            box('core',u-tw*.13+j*tw*.065,v-depth*.17,roof+.05,.012,.003,.038)
        for side in [-1,1]:
            box('metal',u+side*tw*.22,v+.03,roof+.03,.06,.055,.032)
            box('core',u+side*tw*.22,v+.03,roof+.048,.045,.038,.003)
        rod('metal',(u+.035,v+.015,roof+.08),(u+.035,v+.015,roof+.16),.002)
        finish('Tower'+str(ti+1), .0008)
        # Flush museum label in the landscape, with restrained engraved-looking text.
        lu, lv = u, -(width/2-.40)
        box('metal',lu,lv,ground+.020,.22,.085,.016); finish('Label'+str(ti+1),.002)
        curve=bpy.data.curves.new(name+'LabelText'+str(ti+1),'FONT')
        curve.body='0'+str(ti+1)+'  /  '+str(round(height/.049))+' FLOORS'; curve.size=.014; curve.align_x='CENTER'; curve.extrude=.0001
        text=bpy.data.objects.new(curve.name,curve); bpy.context.scene.collection.objects.link(text)
        text.location=pos(lu,lv-.008,ground+.029); text.rotation_euler.z=0 if long_x else math.pi/2
        curve.materials.append(mats['mark']); text['ir_lux_model']='pkg_l1_model'
    # Fine trunks, branched clustered foliage and low hedges, with deterministic variation.
    for side in [-1,1]:
        for j in range(max(8,round(length/.23))):
            u=-length/2+.23+j*(length-.46)/(max(8,round(length/.23))-1)
            v=side*(width/2-.40)+rg.uniform(-.015,.015)
            # Keep the tower labels readable from the front.
            if side<0 and any(abs(u-spec[0])<.16 for spec in tower_specs):
                continue
            h=rg.uniform(.095,.16); rad=rg.uniform(.034,.05)
            rod('bark',(u,v,ground),(u,v,ground+h),.003)
            for k in range(7):
                angle=k*2.399; off=rad*.55
                x,y=u+math.cos(angle)*off,v+math.sin(angle)*off
                z=ground+h+rg.uniform(-.01,.035)
                rod('bark',(u,v,ground+h*.65),(x,y,z),.0013)
                sphere('leaf'+str(rg.randrange(3)),x,y,z,rad*rg.uniform(.55,.85))
        # Small, clipped shrubs on both ends and around the broad entry lawns.
        for j in range(12):
            sphere('leaf2',length*.40,side*(.12+j*.009),ground+.025,.024)
    if width>2:
        for j in range(18):
            u=rg.uniform(-length*.42,length*.42);v=rg.choice([-1,1])*rg.uniform(.65,width/2-.43)
            sphere('grass2',u,v,ground+.012,rg.uniform(.025,.055))
    finish('Trees', 0)
    bpy.data.objects[name+'Site']['tower_count']=3
    bpy.data.objects[name+'Site']['tower_heights']=[s[1] for s in tower_specs]


def _islands(stats):
    """Upgrade only the entry/gallery scale-model displays; retain their footprints."""
    n = 0
    for key, dims in (("entry", (4.0, 3.0)), ("gallery", (6.0, 1.5))):
        lo, hi = _bb(f'{ROOMS[key]}.floor')
        candidates = [o for o in bpy.data.objects if o.type == 'MESH'
                      and (o.name.startswith('WhiteIslandFactory') or
                           (key == 'gallery' and o.name.startswith('CafeCounterFactory') and max(o.dimensions) > 2.5))
                      and lo[0] <= o.matrix_world.translation.x <= hi[0]
                      and lo[1] <= o.matrix_world.translation.y <= hi[1]]
        for o in candidates:
            pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
            cx = sum(p.x for p in pts)/8; cy = sum(p.y for p in pts)/8; z0 = min(p.z for p in pts)
            alx = max(p.x for p in pts)-min(p.x for p in pts) >= max(p.y for p in pts)-min(p.y for p in pts)
            lx, ly = dims if alx else dims[::-1]
            _architectural_model(f'LuxModel{key}{n}', cx, cy, z0, lx, ly)
            o.hide_render = True; o.hide_viewport = True
            n += 1
    stats['lux_islands'] = n
    stats['lux_architectural_models'] = {'displays':n, 'towers_per_display':3, 'tag':'pkg_l1_model'}


def _vase_table(stats):
    fl = _fl(); pa = _pa(); r = ROOMS["vip"]; lo = _bb(f"{r}.floor")[0]; hi = _bb(f"{r}.floor")[1]
    cx, cy = (lo[0] + hi[0]) / 2, lo[1] + (hi[1] - lo[1]) * 0.3; z0 = lo[2] if False else _bb(f"{r}.floor")[1][2]
    dark = pa._flat("ir_lux_vase_table", (0.07, 0.05, 0.04), 0.35, wood=True); gl = pa._flat("ir_lux_vase_glass", (0.9, 0.95, 0.95), 0.02, transmission=0.9)
    leaf = pa._flat("ir_lux_vase_leaf", (0.12, 0.4, 0.1), 0.6); flower = pa._flat("ir_lux_vase_flower", (0.95, 0.95, 0.88), 0.5)
    tb = [("box", cx, cy, z0 + 0.74, 3.6, 0.8, 0.05)] + [("box", cx + sx * 1.7, cy + sy * 0.34, z0 + 0.36, 0.06, 0.06, 0.72) for sx in (-1, 1) for sy in (-1, 1)]
    vs, ls, fs = [], [], []
    for i in range(7):
        x = cx - 1.5 + i * 0.5; hv = 0.3 + (i % 3) * 0.08
        vs.append(("cyl", (x, cy, z0 + 0.765), (x, cy, z0 + 0.765 + hv), 0.07, 16)); ls.append(("cyl", (x, cy, z0 + 0.765 + hv * 0.6), (x, cy, z0 + 0.765 + hv + 0.35), 0.035 + (i % 2) * 0.04, 10))
        fs.append(("cyl", (x, cy, z0 + 0.765 + hv + 0.28), (x, cy, z0 + 0.765 + hv + 0.38), 0.06, 12))
    fl.mesh_object("LuxVaseTable", [(dark, tb), (gl, vs), (leaf, ls), (flower, fs)], bevel=False); stats["lux_vase_table"] = 1


def _table_props(cx, cy, ztop, rg, pa, fl, lib_cup, tray=False):
    """A few use props on a side table top: coffee cup + saucer, brochure stack, small vase, water glass (about half of the tables get one or two)."""
    kind = rg.choice(("cup", "brochure", "vase", "glass"))
    if tray:                                                                                   # a tray with 2 cups (the VIP table between the sofa and the armchair)
        tr = pa._flat("ir_lux_tray", (0.08, 0.06, 0.05), 0.35, 0.5)
        fl.mesh_object("LuxTray", [(tr, [("box", cx, cy, ztop + 0.012, 0.38, 0.24, 0.024)])], bevel=False)
        for dx in (-0.09, 0.09):
            if lib_cup is not None:
                o = lib_cup(rg.randrange(1 << 20)).spawn_asset(rg.randrange(999)); k_ = min(1.0, 0.09 / max(o.dimensions.z, 1e-3), 0.1 / max(o.dimensions.x, o.dimensions.y, 1e-3)); o.scale = (k_, k_, k_); o.location = (cx + dx, cy, ztop + 0.024)
        return
    if kind == "cup":
        sau = pa._flat("ir_lux_saucer", (0.95, 0.95, 0.93), 0.2)
        fl.mesh_object("LuxSaucer", [(sau, [("cyl", (cx, cy, ztop), (cx, cy, ztop + 0.012), 0.075, 20)])], bevel=False)
        if lib_cup is not None:
            o = lib_cup(rg.randrange(1 << 20)).spawn_asset(rg.randrange(999)); k = min(1.0, 0.09 / max(o.dimensions.z, 1e-3), 0.11 / max(o.dimensions.x, o.dimensions.y, 1e-3)); o.scale = (k, k, k); o.location = (cx, cy, ztop + 0.012)
    elif kind == "brochure":
        pap = [pa._flat(f"ir_lux_brochure{i}", c, 0.5) for i, c in enumerate(((0.9, 0.9, 0.88), (0.15, 0.3, 0.2), (0.85, 0.7, 0.3)))]
        fl.mesh_object("LuxBrochures", [(pap[i % 3], [("box", cx + rg.uniform(-0.01, 0.01), cy + rg.uniform(-0.01, 0.01), ztop + 0.005 + 0.006 * i, 0.21, 0.15, 0.01, rg.uniform(-0.25, 0.25))]) for i in range(5)], bevel=False)
    elif kind == "vase":
        gl = pa._flat("ir_lux_tv_glass", (0.9, 0.95, 0.95), 0.02, transmission=0.9); lf = pa._flat("ir_lux_tv_leaf", (0.12, 0.4, 0.1), 0.6)
        fl.mesh_object("LuxTableVase", [(gl, [("cyl", (cx, cy, ztop), (cx, cy, ztop + 0.16), 0.04, 14)]), (lf, [("cyl", (cx, cy, ztop + 0.1), (cx, cy, ztop + 0.34), 0.05, 10)])], bevel=False)
    else:
        gl = pa._flat("ir_lux_tv_water", (0.9, 0.95, 0.95), 0.02, transmission=0.92)
        fl.mesh_object("LuxWaterGlass", [(gl, [("cyl", (cx, cy, ztop), (cx, cy, ztop + 0.11), 0.032, 14)])], bevel=False)


def apply(stats):
    sc = bpy.context.scene
    if sc.get("ir_lux_shell") or bpy.data.objects.get(f"{ROOMS['main']}.floor") is None:
        return 0
    skip = set((os.environ.get("ROOM_LUX_SKIP") or "").split(",")); n = 0
    for key, fn in (("clean", _clean), ("main", _main), ("mainfloor", _main_floor), ("entry", _entry), ("gallery", _gallery), ("vip", _vip), ("vipart", _vip_art), ("furn", _furniture), ("island", _islands), ("vase", _vase_table), ("light", _lights)):
        if key in skip:
            continue
        try:
            bpy.context.view_layer.update(); fn(stats); n += 1
        except Exception as ex:                                  # noqa: BLE001 -- a part that fails must not sink the kit stage
            stats[f"lux_{key}_error"] = repr(ex)[:160]
    sc["ir_lux_shell"] = 1
    return n
